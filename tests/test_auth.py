from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash
from app import create_app


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'auth.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def token(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session['csrf_token']

    def setup_account(self):
        self.client.get('/crear-cuenta')
        return self.client.post('/crear-cuenta', data={
            'username': 'Docente', 'password': 'ClaveSegura2026',
            'password_confirmation': 'ClaveSegura2026', 'csrf_token': self.token()})

    def rows(self, query):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(query).fetchall()

    def logout(self):
        return self.client.post('/cerrar-sesion', data={'csrf_token': self.token()})

    def login(self, password='ClaveSegura2026'):
        self.client.get('/iniciar-sesion')
        return self.client.post('/iniciar-sesion', data={
            'username': 'DOCENTE', 'password': password, 'csrf_token': self.token()})

    def test_first_use_logo_and_password_hash_single_account(self):
        response = self.client.get('/')
        self.assertTrue(response.location.endswith('/crear-cuenta'))
        response = self.client.get('/crear-cuenta')
        self.assertIn('branding/voxboard-logo.png', response.get_data(as_text=True))
        self.assertEqual(self.setup_account().status_code, 302)
        username, hashed = self.rows('SELECT username,password_hash FROM teachers')[0]
        self.assertEqual(username, 'docente')
        self.assertNotEqual(hashed, 'ClaveSegura2026')
        self.assertTrue(check_password_hash(hashed, 'ClaveSegura2026'))
        self.assertIn('Cerrar sesión', self.client.get('/').get_data(as_text=True))
        self.client.post('/crear-cuenta', data={'username': 'intruso', 'password': 'otra_clave', 'csrf_token': self.token()})
        self.assertEqual(len(self.rows('SELECT * FROM teachers')), 1)
        self.assertEqual(self.rows('SELECT username FROM teachers'), [('docente',)])

    def test_validation_and_csrf(self):
        self.client.get('/crear-cuenta')
        for data in (
            {'username': 'ab', 'password': '12345678', 'password_confirmation': '12345678'},
            {'username': 'docente', 'password': 'corta', 'password_confirmation': 'corta'},
            {'username': 'docente', 'password': '12345678', 'password_confirmation': '87654321'},
        ):
            response = self.client.post('/crear-cuenta', data={**data, 'csrf_token': self.token()})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM teachers'), [])
        self.assertEqual(self.client.post('/crear-cuenta', data={'username': 'docente'}).status_code, 400)
        self.setup_account()
        self.assertEqual(self.client.post('/sesiones', data={'class_date': '2026-11-17'}).status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM class_sessions'), [])
        response = self.client.post('/sesiones/1/resumen', json={'summary': 'No guardar'}, headers={'X-CSRF-Token': 'incorrecto'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('página venció', response.json['error'])

    def test_all_pages_apis_and_exports_require_login_even_in_testing(self):
        self.setup_account()
        client = self.app.test_client()
        for path in ('/', '/sesiones/1', '/sesiones/1/pizarra', '/sesiones/1/trivia',
                     '/sesiones/1/trivia/proyectar', '/cursos/1/comentarios?student_id=1',
                     '/cursos/1/rendimiento', '/cursos/1/rendimiento.csv', '/cursos/1/rendimiento.xlsx'):
            response = client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response.location.endswith('/iniciar-sesion'))
        self.assertEqual(client.get('/api/voz/estado').status_code, 401)
        self.assertEqual(client.post('/api/voz/transcribir', data=b'audio', content_type='audio/wav').status_code, 401)
        self.assertEqual(client.post('/sesiones/1/voz/confirmar', json={'token': 'x'}).status_code, 401)
        self.assertEqual(client.post('/sesiones/1/resumen', json={'summary': 'x'}).status_code, 401)
        with client.get('/static/branding/voxboard-logo.png') as logo:
            self.assertEqual(logo.status_code, 200)

    def test_wrong_credentials_login_logout_and_cookie_flags(self):
        self.setup_account()
        self.logout()
        self.assertEqual(self.login('incorrecta').status_code, 400)
        self.assertTrue(self.client.get('/').location.endswith('/iniciar-sesion'))
        result = self.login()
        self.assertEqual(result.status_code, 302)
        self.assertIn('HttpOnly', result.headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', result.headers['Set-Cookie'])
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/').headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/cerrar-sesion').status_code, 405)
        self.assertEqual(self.logout().status_code, 302)
        self.assertTrue(self.client.get('/').location.endswith('/iniciar-sesion'))

    def test_session_survives_restart_and_original_records_are_preserved(self):
        before = {table: self.rows(f'SELECT * FROM {table}') for table in ('courses', 'students')}
        self.setup_account()
        secret = self.app.config['SECRET_KEY']
        cookie = self.client.get_cookie('session').value
        restarted = create_app(self.config)
        self.assertEqual(secret, restarted.config['SECRET_KEY'])
        client = restarted.test_client()
        client.set_cookie('session', cookie)
        self.assertEqual(client.get('/').status_code, 200)
        self.assertEqual({table: self.rows(f'SELECT * FROM {table}') for table in before}, before)

    def test_attempt_limit_expires(self):
        self.setup_account(); self.logout()
        for _ in range(5):
            self.assertEqual(self.login('incorrecta').status_code, 400)
        self.assertEqual(self.login().status_code, 429)
        with patch('auth.time.time', return_value=time.time() + 61):
            self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.rows('SELECT failed_attempts,locked_until FROM teachers'), [(0, 0.0)])


if __name__ == '__main__':
    unittest.main()
