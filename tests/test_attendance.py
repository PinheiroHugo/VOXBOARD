from auth_helpers import authenticate_client
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import create_app


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'test.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}
        self.client = authenticate_client(create_app(self.config).test_client())

    def rows(self, query):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute(query).fetchall()

    def new_session(self, day='2026-11-14'):
        response = self.client.post('/sesiones', data={'class_date': day})
        self.assertEqual(response.status_code, 302)
        return response.headers['Location']

    def test_save_correct_reload_and_restart(self):
        original_students = self.rows('SELECT * FROM students ORDER BY id')
        original_courses = self.rows('SELECT * FROM courses ORDER BY id')
        url = self.new_session()
        page = self.client.get(url).get_data(as_text=True)
        self.assertEqual(page.count('type="radio"'), 10)
        self.assertNotIn('checked', page)
        self.assertEqual(self.rows('SELECT * FROM attendance'), [])
        states = {f'status_{i}': 'presente' for i in range(1, 6)}
        response = self.client.post(url, data=states, follow_redirects=True)
        self.assertIn('Asistencia guardada correctamente.', response.get_data(as_text=True))
        self.assertEqual(len(self.rows('SELECT * FROM attendance')), 5)
        states['status_2'] = 'ausente'
        self.client.post(url, data=states)
        self.client.post(url, data=states)
        self.assertEqual(len(self.rows('SELECT * FROM attendance')), 5)
        self.assertEqual(self.rows('SELECT status FROM attendance WHERE student_id = 2'), [('ausente',)])
        restarted = authenticate_client(create_app(self.config).test_client())
        html = restarted.get(url).get_data(as_text=True)
        self.assertIn('name="status_2" value="ausente" checked', html)
        self.assertEqual(html.count('checked'), 5)
        self.assertEqual(self.rows('SELECT * FROM students ORDER BY id'), original_students)
        self.assertEqual(self.rows('SELECT * FROM courses ORDER BY id'), original_courses)
        self.assertEqual(len(self.rows('SELECT * FROM class_sessions')), 1)
        self.assertEqual(len(self.rows('SELECT * FROM attendance')), 5)
        self.assertIn(url, restarted.get('/cursos/1').get_data(as_text=True))

    def test_partial_attendance_and_independent_sessions(self):
        first = self.new_session()
        second = self.new_session('2026-11-15')
        self.client.post(first, data={'status_1': 'presente'})
        self.assertEqual(len(self.rows('SELECT * FROM attendance')), 1)
        self.assertEqual(self.client.get(first).get_data(as_text=True).count('checked'), 1)
        self.assertNotIn('checked', self.client.get(second).get_data(as_text=True))
        self.client.post(second, data={'status_1': 'ausente'})
        self.assertEqual(len(self.rows('SELECT * FROM attendance')), 2)

    def test_invalid_input_does_not_write(self):
        self.assertEqual(self.client.post('/sesiones', data={'class_date': '2026-02-30'}).status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM class_sessions'), [])
        url = self.new_session()
        self.assertEqual(self.client.post(url, data={'status_1': 'presente', 'status_2': 'inválido'}).status_code, 400)
        self.assertEqual(self.rows('SELECT * FROM attendance'), [])
        self.assertEqual(self.client.get('/sesiones/9999').status_code, 404)

    def test_migration_preserves_existing_data(self):
        # Simula una base de fase 1 con datos ya modificados por el docente.
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('DROP TABLE attendance')
            connection.execute('DROP TABLE class_sessions')
            connection.execute("UPDATE courses SET teacher = 'Docente existente' WHERE id = 1")
            connection.execute("UPDATE students SET first_name = 'Nombre existente' WHERE id = 1")
        before = self.rows('SELECT * FROM students ORDER BY id')
        create_app(self.config)
        create_app(self.config)
        self.assertEqual(self.rows('SELECT * FROM students ORDER BY id'), before)
        self.assertEqual(self.rows('SELECT teacher FROM courses'), [('Docente existente',)])
        self.assertEqual(self.rows('SELECT * FROM class_sessions'), [])


if __name__ == '__main__':
    unittest.main()
