from auth_helpers import authenticate_client
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import create_app
from school_records import parse_school_command


class Phase3CTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'school.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database, 'SECRET_KEY': 'test-secret'}
        self.client = authenticate_client(create_app(self.config).test_client())
        self.url = self.client.post('/sesiones', data={'class_date': '2026-11-15'}).location

    def rows(self, table):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()

    def preview(self, text, url=None):
        return self.client.post((url or self.url) + '/voz/vista-previa', json={'text': text})

    def confirm(self, token, url=None):
        return self.client.post((url or self.url) + '/voz/confirmar', json={'token': token})

    def test_summary_edit_reload_restart_and_session_isolation(self):
        before = {table: self.rows(table) for table in ('courses', 'students', 'attendance', 'grades')}
        self.assertEqual(self.client.get(self.url + '/resumen').json['summary'], '')
        for text in ('Las plantas necesitan agua.\nmostrar ciclo del agua', 'Resumen editado con tildes: raíz.'):
            self.assertEqual(self.client.post(self.url + '/resumen', json={'summary': text}).status_code, 200)
        self.client = authenticate_client(create_app(self.config).test_client())
        self.assertEqual(self.client.get(self.url + '/resumen').json['summary'], text)
        self.assertIn(text, self.client.get(self.url + '/pizarra').get_data(as_text=True))
        other = self.client.post('/sesiones', data={'class_date': '2026-11-16'}).location
        self.assertEqual(self.client.get(other + '/resumen').json['summary'], '')
        self.assertEqual(len(self.rows('session_summaries')), 1)
        self.assertEqual(self.client.post(self.url + '/resumen', json={'summary': 'a' * 20001}).status_code, 400)
        self.assertEqual(self.client.get(self.url + '/resumen').json['summary'], text)
        self.client.post(self.url + '/resumen', json={'summary': ''})
        self.assertEqual(self.client.get(self.url + '/resumen').json['summary'], '')
        self.assertEqual({table: self.rows(table) for table in before}, before)

    def test_preview_cancel_confirm_update_without_duplicates(self):
        self.client.post(self.url, data={'status_1': 'presente'})
        self.client.post(self.url, data={'form_type': 'grades', 'grade_1': '70'})
        for text, table, expected in (
            ('marcar ausente al estudiante uno', 'attendance', 'ausente'),
            ('registrar nota ochenta y cinco al estudiante uno', 'grades', 85),
        ):
            original = self.rows(table)
            response = self.preview(text)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['name'], 'Ana García')
            self.assertEqual(response.json['value'], expected)
            # Cancelar descarta la vista previa en el cliente, sin POST de confirmación.
            self.assertEqual(self.rows(table), original)
            confirmed = self.confirm(response.json['token'])
            self.assertEqual(confirmed.status_code, 200)
            self.confirm(response.json['token'])
            self.assertEqual(self.rows(table), [(1, 1, expected)])
        for text, expected in [('registrar nota 0 al estudiante 1', 0), ('registrar nota cien al estudiante uno', 100)]:
            self.confirm(self.preview(text).json['token'])
            self.assertEqual(self.rows('grades'), [(1, 1, expected)])
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('(ID: 1)', html)
        self.assertIn('value="ausente" checked', html)
        self.assertIn('step="1" value="100"', html)

    def test_invalid_values_membership_token_and_session(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO courses VALUES (2, 'Otro curso', 'Otro docente', 2026)")
            db.execute("INSERT INTO students VALUES (6, 2, 'Otro', 'Estudiante')")
        for text in ('registrar nota 101 al estudiante uno', 'registrar nota -1 al estudiante uno',
                     'registrar nota 85.5 al estudiante uno', 'registrar nota ochenta y medio al estudiante uno',
                     'marcar ausente al estudiante seis', 'marcar presente al estudiante 999',
                     'marcar presente al estudiante cero', 'hola clase'):
            with self.subTest(text=text):
                self.assertEqual(self.preview(text).status_code, 400)
        self.assertEqual(self.rows('attendance'), [])
        self.assertEqual(self.rows('grades'), [])
        token = self.preview('marcar presente al estudiante uno').json['token']
        other = self.client.post('/sesiones', data={'class_date': '2026-11-16'}).location
        self.assertEqual(self.confirm(token, other).status_code, 400)
        self.assertEqual(self.confirm('alterado').status_code, 400)
        self.assertEqual(self.client.post(self.url + '/voz/confirmar', json={'student_id': 1, 'value': 100}).status_code, 400)
        self.assertEqual(self.rows('attendance'), [])
        # Se vuelve a comprobar pertenencia al confirmar, incluso después de la vista previa.
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE students SET course_id = 2 WHERE id = 1')
        self.assertEqual(self.confirm(token).status_code, 400)

    def test_numbers_and_fixed_formats(self):
        for phrase, expected in [('cero', 0), ('dieciséis', 16), ('veintidós', 22), ('treinta y uno', 31),
                                 ('noventa y nueve', 99), ('cien', 100), ('85', 85)]:
            self.assertEqual(parse_school_command(f'¡REGISTRAR NOTA {phrase} AL ESTUDIANTE UNO!'), ('grade', 1, expected))
        self.assertEqual(parse_school_command('marcar presente al estudiante 1'), ('attendance', 1, 'presente'))


if __name__ == '__main__':
    unittest.main()
