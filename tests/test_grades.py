from auth_helpers import authenticate_client
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import create_app


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'grades.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}
        self.client = authenticate_client(create_app(self.config).test_client())
        self.url = self.client.post('/sesiones', data={'class_date': '2026-11-14'}).location

    def rows(self, query):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(query).fetchall()

    def save(self, values, **kwargs):
        return self.client.post(self.url, data={'form_type': 'grades', **values}, **kwargs)

    def test_save_correct_delete_and_restart(self):
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('name="grade_1" type="number" min="0" max="100" step="1" value=""', html)
        response = self.save({'grade_1': '0', 'grade_2': '100', 'grade_3': '75'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Calificaciones guardadas correctamente.', response.get_data(as_text=True))
        self.assertEqual(self.rows('SELECT student_id, score FROM grades ORDER BY student_id'), [(1, 0), (2, 100), (3, 75)])
        self.save({'grade_1': '90', 'grade_2': '100', 'grade_3': '75'})
        self.save({'grade_1': '90', 'grade_2': '100', 'grade_3': '75'})
        self.assertEqual(self.rows('SELECT student_id, score FROM grades ORDER BY student_id'), [(1, 90), (2, 100), (3, 75)])
        self.save({'grade_1': '', 'grade_2': '100', 'grade_3': '75'})
        self.client = authenticate_client(create_app(self.config).test_client())
        self.assertEqual(self.rows('SELECT student_id, score FROM grades ORDER BY student_id'), [(2, 100), (3, 75)])
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertIn('name="grade_1" type="number" min="0" max="100" step="1" value=""', html)
        self.assertIn('name="grade_2" type="number" min="0" max="100" step="1" value="100"', html)

    def test_invalid_values_reject_entire_form_and_keep_input(self):
        self.save({'grade_1': '70', 'grade_2': '80', 'grade_3': '90'})
        before = self.rows('SELECT * FROM grades ORDER BY student_id')
        for invalid in ('-1', '101', '50.5', 'texto', '1e2', '999999999999999999'):
            with self.subTest(value=invalid):
                response = self.save({'grade_1': '22', 'grade_2': invalid, 'grade_3': ''})
                self.assertEqual(response.status_code, 400)
                html = response.get_data(as_text=True)
                self.assertIn('No se guardó ninguna calificación.', html)
                self.assertIn('value="22"', html)
                self.assertIn(f'value="{invalid}"', html)
                self.assertIn('aria-invalid="true"', html)
                self.assertEqual(self.rows('SELECT * FROM grades ORDER BY student_id'), before)

    def test_attendance_and_other_sessions_are_preserved(self):
        self.client.post(self.url, data={'status_1': 'presente', 'status_2': 'ausente'})
        attendance = self.rows('SELECT * FROM attendance ORDER BY student_id')
        self.save({'grade_1': '85'})
        self.save({'grade_1': '101'})
        self.assertEqual(self.rows('SELECT * FROM attendance ORDER BY student_id'), attendance)
        self.client.post(self.url, data={'status_1': 'ausente', 'status_2': 'ausente'})
        self.assertEqual(self.rows('SELECT student_id, score FROM grades'), [(1, 85)])
        self.assertEqual(self.rows('SELECT status FROM attendance WHERE student_id = 1'), [('ausente',)])
        other = self.client.post('/sesiones', data={'class_date': '2026-11-15'}).location
        self.client.post(other, data={'form_type': 'grades', 'grade_1': '40'})
        self.assertEqual(len(self.rows('SELECT * FROM grades')), 2)
        self.assertIn('value="85"', self.client.get(self.url).get_data(as_text=True))
        self.assertIn('value="40"', self.client.get(other).get_data(as_text=True))

    def test_database_rejects_duplicate_and_invalid_scores(self):
        self.save({'grade_1': '50'})
        with closing(sqlite3.connect(self.database)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO grades VALUES (1, 1, 70)')
            for score in (-1, 101, 50.5):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('UPDATE grades SET score = ?', (score,))


if __name__ == '__main__':
    unittest.main()
