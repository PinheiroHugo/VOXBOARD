from contextlib import closing
from pathlib import Path
import http.client
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import create_app
from auth_helpers import authenticate_client
from manage_data import backup_database, restore_database
from server import build_app, server_options
from waitress import create_server


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / 'real.sqlite3'

    def test_demo_is_separate_and_tunnel_requires_existing_account(self):
        with patch('server.BASE_DIR', self.root), patch('server.DATABASE', self.database):
            with self.assertRaises(ValueError):
                build_app(demo=True, tunnel=True)
            app = build_app(demo=True)
            self.assertFalse(self.database.exists())
            authenticate_client(app.test_client())
            public = build_app(demo=True, tunnel=True)
            self.assertTrue(public.config['SESSION_COOKIE_SECURE'])
            self.assertFalse(public.debug)
            self.assertFalse(public.testing)
            self.assertNotEqual(public.config['DATABASE'], self.database)
            self.assertEqual(app.secret_key, public.secret_key)
            with public.test_client() as client:
                self.assertEqual(client.get('/api/voz/estado').status_code, 401)
                self.assertEqual(client.get('/crear-cuenta').location, '/iniciar-sesion')

    def test_waitress_http_https_origin_and_authenticated_routes(self):
        app = create_app({'TESTING': True, 'DATABASE': self.database, 'SEED_DEMO_DATA': True,
                          'SESSION_COOKIE_SECURE': True})
        @app.get('/__test__/scheme')
        def scheme():
            from flask import request
            return {'scheme': request.scheme, 'host': request.host}
        client = authenticate_client(app.test_client())
        with client.session_transaction() as session:
            token = session['csrf_token']
        cookie = client.get_cookie('session').value
        server = create_server(app, **server_options(tunnel=True, port=0))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', int(server.effective_port), timeout=10)
        try:
            connection.request('GET', '/api/voz/estado', headers={'Host': 'demo.example.test'})
            response = connection.getresponse(); response.read()
            self.assertEqual(response.status, 401)
            headers = {'Host': 'demo.example.test', 'Cookie': 'session=' + cookie,
                       'X-Forwarded-Proto': 'http'}
            connection.request('GET', '/__test__/scheme', headers=headers)
            response = connection.getresponse()
            self.assertIn(b'"scheme":"https"', response.read())
            self.assertIn('Secure', response.getheader('Set-Cookie', ''))
            self.assertEqual(response.getheader('Permissions-Policy'), 'microphone=(self), camera=()')
            connection.request('POST', '/api/voz/transcribir', body=b'not a wav',
                               headers={**headers, 'Content-Type': 'audio/wav', 'X-CSRF-Token': token})
            response = connection.getresponse(); body = response.read()
            self.assertIn(response.status, (400, 503))
            self.assertIn(b'error', body)  # El POST llega a Vosk, no a la autenticación.
            connection.request('GET', '/', headers=headers)
            response = connection.getresponse(); html = response.read()
            self.assertIn(b'data-auto-stop="true"', html)
            self.assertIn(b'vox-resource-dialog', html)
            self.assertNotIn(b'http://127.0.0.1', html)
            connection.request('POST', '/cerrar-sesion', headers={**headers, 'X-CSRF-Token': token})
            response = connection.getresponse(); response.read()
            self.assertEqual(response.status, 302)
            self.assertIn('Expires=Thu, 01 Jan 1970', response.getheader('Set-Cookie', ''))
        finally:
            connection.close(); server.close(); server.task_dispatcher.shutdown()
            thread.join(timeout=3)

    def test_backup_restore_preserves_records_and_rejects_invalid_copy(self):
        create_app({'DATABASE': self.database, 'TESTING': True, 'SEED_DEMO_DATA': True})
        saved = backup_database(self.database, self.root / 'backups')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE courses SET name='Cambio ficticio' WHERE id=1")
        previous = restore_database(saved, self.database)
        self.assertTrue(previous.is_file())
        with closing(sqlite3.connect(self.database)) as db:
            self.assertNotEqual(db.execute('SELECT name FROM courses').fetchone()[0], 'Cambio ficticio')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM students').fetchone()[0], 5)
        invalid = self.root / 'invalid.sqlite3'
        sqlite3.connect(invalid).close()
        with self.assertRaises(ValueError):
            restore_database(invalid, self.database)
        self.database.write_bytes(b'base danada ficticia')
        damaged = restore_database(saved, self.database)
        self.assertEqual(damaged.read_bytes(), b'base danada ficticia')
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM students').fetchone()[0], 5)
