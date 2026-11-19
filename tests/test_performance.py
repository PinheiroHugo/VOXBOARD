from auth_helpers import authenticate_client
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from flask import template_rendered
from app import create_app
from performance import honor_roll
from report_comments import student_stats


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'performance.sqlite3'
        self.app = create_app({'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database})
        self.client = authenticate_client(self.app.test_client())
        self.url = '/cursos/1/rendimiento'

    def sql(self, query):
        with closing(sqlite3.connect(self.database)) as db, db:
            return db.execute(query).fetchall()

    def view(self):
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True), contexts[0]

    def seed(self):
        for date in ('2026-11-01', '2026-11-02', '2026-11-03'):
            self.client.post('/sesiones', data={'class_date': date})
        self.client.post('/sesiones/1', data={'form_type': 'grades', 'grade_1': '0', 'grade_2': '100', 'grade_3': '90', 'grade_4': '50'})
        self.client.post('/sesiones/2', data={'form_type': 'grades', 'grade_1': '100'})
        self.client.post('/sesiones/1', data={'status_1': 'presente', 'status_2': 'ausente'})
        self.client.post('/sesiones/2', data={'status_1': 'ausente'})

    def test_zero_pending_attendance_and_third_place_tie(self):
        self.seed()
        html, context = self.view()
        rows = {row['id']: row for row in context['rows']}
        self.assertEqual(context['sessions'], 3)
        self.assertEqual(rows[1]['average'], 50.0)
        self.assertEqual(rows[1]['grade_count'], 2)
        self.assertEqual(rows[1]['present'], 1)
        self.assertEqual(rows[1]['absent'], 1)
        self.assertEqual(rows[1]['pending_attendance'], 1)
        self.assertEqual(rows[1]['attendance_percent'], 50)
        self.assertEqual(rows[2]['attendance_percent'], 0)
        self.assertEqual(rows[2]['present'], 0)
        self.assertIsNone(rows[5]['average'])
        self.assertEqual(rows[5]['grade_count'], 0)
        self.assertIsNone(rows[5]['attendance_percent'])
        self.assertEqual([(row['id'], row['position']) for row in context['honor']], [(2, 1), (3, 2), (1, 3), (4, 3)])
        self.assertIn('50.00', html)
        self.assertIn('50.00 %', html)
        self.assertIn('0.00 %', html)
        self.assertIn('Sin registros', html)
        self.assertIn('Descargar CSV', html)
        # Los indicadores académicos conservan los mismos cálculos que el boletín.
        with closing(sqlite3.connect(self.database)) as db:
            stats = student_stats(db, 1, 1)
        for name in stats:
            self.assertEqual(rows[1][name], stats[name])

    def test_missing_data_zero_average_and_no_writes(self):
        html, context = self.view()
        self.assertIn('Todavía no hay sesiones', html)
        self.assertEqual(context['honor'], [])
        self.assertEqual(len(context['rows']), 5)
        self.seed()
        self.sql('UPDATE grades SET score = 0 WHERE student_id = 1')
        tables = ['courses', 'students', 'class_sessions', 'grades', 'attendance',
                  'session_summaries', 'session_trivias', 'report_comments']
        before = {table: self.sql(f'SELECT * FROM {table}') for table in tables}
        html, context = self.view()
        row = next(row for row in context['rows'] if row['id'] == 1)
        self.assertEqual(row['average'], 0)
        self.assertIn('0.00', html)
        self.assertEqual({table: self.sql(f'SELECT * FROM {table}') for table in tables}, before)
        # Un promedio 0 sigue siendo elegible si hay menos de tres valores superiores.
        self.sql('DELETE FROM grades WHERE student_id IN (3, 4)')
        _, context = self.view()
        self.assertIn(1, [row['id'] for row in context['honor']])

    def test_course_isolation_and_navigation(self):
        self.seed()
        self.sql("INSERT INTO courses VALUES (2, 'Otro curso', 'Docente', 2026)")
        self.sql("INSERT INTO students VALUES (6, 2, 'Otra', 'Persona')")
        self.sql("INSERT INTO class_sessions VALUES (4, 2, '2026-11-04')")
        self.sql('INSERT INTO grades VALUES (4, 1, 1)')
        self.sql("INSERT INTO attendance VALUES (4, 1, 'ausente')")
        self.sql('INSERT INTO grades VALUES (4, 6, 100)')
        _, context = self.view()
        self.assertEqual(context['sessions'], 3)
        self.assertEqual(len(context['rows']), 5)
        row = next(row for row in context['rows'] if row['id'] == 1)
        self.assertEqual(row['average'], 50)
        self.assertEqual(row['attendance_percent'], 50)
        self.assertIn(self.url, self.client.get('/').get_data(as_text=True))
        self.assertEqual(self.client.get('/cursos/999/rendimiento').status_code, 404)

    def test_honor_uses_two_decimals_and_shared_dense_positions(self):
        def row(id, average, count=1):
            return {'id': id, 'average': average, 'grade_count': count, 'last_name': str(id), 'first_name': 'Estudiante'}
        rows = [row(1, 99), row(2, 99), row(3, 90), row(4, 80.004), row(5, 80.003), row(6, 79.99), row(7, None, 0)]
        honor = honor_roll(rows)
        self.assertEqual([(item['id'], item['position']) for item in honor], [(1, 1), (2, 1), (3, 2), (4, 3), (5, 3)])
        self.assertEqual([f"{item['average']:.2f}" for item in honor], ['99.00', '99.00', '90.00', '80.00', '80.00'])


if __name__ == '__main__':
    unittest.main()
