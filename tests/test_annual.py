from auth_helpers import authenticate_client
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import create_app, init_db
from annual import ensure_day
from report_comments import student_stats


class AnnualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'annual.sqlite3'
        self.config = {'TESTING': True, 'DATABASE': self.database}
        self.client = authenticate_client(create_app(self.config).test_client())

    def sql(self, query, args=()):
        with closing(sqlite3.connect(self.database)) as db, db:
            return db.execute(query, args).fetchall()

    def configure(self, year=2026, names='Ana;García\nMateo;López'):
        return self.client.post('/gestion/configurar', data={'school_year': str(year),
            'name': f'Curso {year}', 'teacher': 'Docente de prueba', 'new_students': names})

    def preview(self, text='marcar presente al estudiante uno', day='2026-11-18'):
        response = self.client.post('/voz/vista-previa', json={'text': text, 'class_date': day})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def confirm(self, preview):
        return self.client.post('/voz/confirmar', json={'token': preview['token']})

    def test_no_active_course_home_and_resources_are_available(self):
        self.assertEqual(self.sql('SELECT * FROM courses'), [])
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('id="vox-resource-dialog"', html)
        self.assertIn('Ciclo del agua', html)
        self.assertNotIn('Crear sesión', html)
        self.assertNotIn('Seleccioná una sesión', html)
        with self.client.get('/static/resources/ciclo-del-agua.svg') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.preview()['needs'], ['course'])
        self.assertTrue(self.client.get('/mi-curso').location.endswith('/gestion/configurar'))

    def test_attendance_two_dates_and_correction_without_manual_sessions(self):
        self.assertEqual(self.configure().status_code, 302)
        # Vista previa y cancelación no crean contextos ni registros.
        first = self.preview()['preview']
        self.assertEqual(first['class_date'], '2026-11-18')
        self.assertIn('Curso 2026', first['context'])
        self.assertEqual(self.sql('SELECT * FROM class_sessions'), [])
        self.assertEqual(self.sql('SELECT * FROM attendance'), [])
        self.assertEqual(self.confirm(first).status_code, 200)
        other = self.preview('marcar ausente al estudiante uno', '2026-11-19')['preview']
        self.assertEqual(self.confirm(other).status_code, 200)
        corrected = self.preview('marcar presente al estudiante uno', '2026-11-19')['preview']
        self.confirm(corrected); self.confirm(corrected)
        self.assertEqual(self.sql('SELECT class_date,status FROM attendance_by_date ORDER BY class_date'),
                         [('2026-11-18', 'presente'), ('2026-11-19', 'presente')])
        self.assertEqual(len(self.sql('SELECT * FROM attendance')), 2)
        self.assertEqual(len(self.sql('SELECT * FROM class_sessions')), 2)
        for _ in range(2):
            self.assertEqual(self.client.get('/mi-curso/registro?fecha=2026-11-18').status_code, 302)
        self.assertEqual(len(self.sql('SELECT * FROM class_sessions')), 2)

    def test_local_today_and_date_correction_before_confirm(self):
        self.configure()
        with patch('app.local_today', return_value='2026-11-18'):
            response = self.client.post('/voz/vista-previa', json={'text': 'marcar ausente al estudiante uno'})
        self.assertEqual(response.json['preview']['class_date'], '2026-11-18')
        changed = self.preview('marcar ausente al estudiante uno', '2026-11-17')['preview']
        self.confirm(changed)
        self.assertEqual(self.sql('SELECT class_date FROM attendance_by_date'), [('2026-11-17',)])
        self.assertEqual(self.client.post('/voz/vista-previa', json={'text': 'marcar presente al estudiante uno', 'class_date': '2026-02-30'}).status_code, 400)

    def test_grades_keep_date_history_and_partial_command(self):
        self.configure()
        missing = self.client.post('/voz/vista-previa', json={'text': 'registrar nota', 'class_date': '2026-11-18'}).json
        self.assertEqual(missing['needs'], ['student', 'value'])
        for day, grade in [('2026-11-18', 0), ('2026-11-19', 85), ('2026-11-19', 90)]:
            preview = self.preview(f'registrar nota {grade} al estudiante uno', day)['preview']
            self.assertIn(day, preview['context'])
            self.assertIn('Calificación', preview['context'])
            self.confirm(preview)
        self.assertEqual(self.sql('SELECT s.class_date,g.score FROM grades g JOIN class_sessions s ON s.id=g.session_id ORDER BY s.class_date'),
                         [('2026-11-18', 0), ('2026-11-19', 90)])

    def test_new_year_preserves_history_and_invalidates_old_pending_preview(self):
        self.configure()
        self.confirm(self.preview()['preview'])
        self.confirm(self.preview('registrar nota 85 al estudiante uno')['preview'])
        pending = self.preview('registrar nota 90 al estudiante uno')['preview']
        records = {table: self.sql(f'SELECT * FROM {table}') for table in ('attendance', 'grades', 'class_sessions')}
        self.assertEqual(self.configure(2027, 'Sofía;Mamani').status_code, 302)
        self.assertEqual(self.sql('SELECT c.school_year FROM courses c JOIN annual_settings a ON a.active_course_id=c.id'), [(2027,)])
        self.assertEqual(self.client.get('/mi-curso').location, '/cursos/2')
        self.assertEqual({table: self.sql(f'SELECT * FROM {table}') for table in records}, records)
        self.assertEqual(self.confirm(pending).status_code, 400)
        self.assertEqual(self.client.post('/sesiones/1', data={'status_1': 'ausente'}).status_code, 403)
        self.assertEqual(self.client.get('/sesiones/1').status_code, 200)
        history = self.client.get('/gestiones').get_data(as_text=True)
        self.assertIn('2026', history); self.assertIn('2027', history)
        self.assertEqual(self.configure(2027, 'Otra;Persona').status_code, 400)
        self.assertEqual(len(self.sql('SELECT * FROM courses')), 2)

    def test_migration_preserves_legacy_rows_and_deduplicates_only_the_daily_view(self):
        self.configure()
        self.sql("INSERT INTO class_sessions VALUES (1,1,'2026-11-18')")
        self.sql("INSERT INTO class_sessions VALUES (2,1,'2026-11-18')")
        self.sql("INSERT INTO attendance VALUES (1,1,'presente')")
        self.sql("INSERT INTO attendance VALUES (2,1,'ausente')")
        self.sql('INSERT INTO grades VALUES (1,1,70)')
        self.sql('INSERT INTO grades VALUES (2,1,90)')
        original = {table: self.sql(f'SELECT * FROM {table}') for table in ('courses','students','class_sessions','attendance','grades')}
        init_db(self.database); init_db(self.database)
        self.assertEqual({table: self.sql(f'SELECT * FROM {table}') for table in original}, original)
        with closing(sqlite3.connect(self.database)) as db:
            stats = student_stats(db, 1, 1)
        self.assertEqual(stats['absent'], 1); self.assertEqual(stats['present'], 0)
        self.assertEqual(stats['average'], 80); self.assertEqual(stats['grade_count'], 2)
        self.confirm(self.preview()['preview'])
        self.assertEqual(len(self.sql('SELECT * FROM attendance')), 2)
        self.assertEqual(self.sql('SELECT status FROM attendance_by_date'), [('presente',)])
        self.assertEqual(self.sql('SELECT * FROM grades'), original['grades'])

    def test_same_day_reservation_is_unique_under_concurrent_requests(self):
        self.configure()
        ids, errors = [], []
        def reserve():
            try:
                with closing(sqlite3.connect(self.database, timeout=10)) as db, db:
                    ids.append(ensure_day(db, 1, '2026-11-18'))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=reserve) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.sql('SELECT * FROM class_sessions')), 1)


if __name__ == '__main__':
    unittest.main()
