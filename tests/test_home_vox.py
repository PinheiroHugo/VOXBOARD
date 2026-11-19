from auth_helpers import authenticate_client
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import create_app
from unittest.mock import patch


class HomeVoxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'vox.sqlite3'
        self.enterContext(patch('app.local_today', return_value='2026-11-18'))
        self.client = authenticate_client(create_app({'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}).test_client())

    def test_home_menus_and_local_recorder_assets(self):
        html = self.client.get('/').get_data(as_text=True)
        for text in ('Mi curso', 'Seguimiento del curso', 'Estudiantes del curso', 'Gestiones anteriores',
                     'Asistencia', 'Calificaciones', 'Cuadro de honor', 'Comentarios de boletín', 'Hablar con Vox'):
            self.assertIn(text, html)
        self.assertNotIn('id="course-menu" open', html)
        self.assertNotIn('id="tracking-menu" open', html)
        self.assertIn('/cursos/1/rendimiento#cuadro-de-honor', html)
        for name in ('home-vox.js', 'resource-commands.js', 'voice.js', 'audio-wav.js'):
            with self.client.get('/static/' + name) as response:
                self.assertEqual(response.status_code, 200)

    def test_resource_session_selection_and_creation_preserve_data(self):
        response = self.client.post('/sesiones', data={'class_date': '2026-11-18', 'resource': 'ciclo-del-agua'})
        self.assertIn('/sesiones/1/pizarra?', response.location)
        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('data-initial-resource="ciclo-del-agua"', html)
        self.assertIn('Abrí el ciclo del agua', html)
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('id="vox-resource-dialog"', html)
        self.assertIn('data-auto-stop="true"', html)
        html = self.client.get('/sesiones/1/pizarra?resource=desconocido&from_vox=1').get_data(as_text=True)
        self.assertIn('data-initial-resource="sistema-solar"', html)
        self.assertNotIn('Abrí el ciclo del agua', html)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM students').fetchone()[0], 5)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attendance').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM grades').fetchone()[0], 0)

    def test_missing_school_data_resume_and_cancel_without_saving(self):
        url = '/cursos/1/voz/vista-previa'
        response = self.client.post(url, json={'text': 'registrar nota ochenta y cinco al estudiante uno'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['needs'], [])
        created = self.client.post('/cursos/1/voz/crear-sesion', json={'class_date': '2026-11-18'})
        self.assertEqual(created.status_code, 200)
        preview = self.client.post(url, json={'text': 'registrar nota ochenta y cinco al estudiante uno'}).json['preview']
        self.assertEqual(preview['class_date'], '2026-11-18')
        self.assertEqual(preview['name'], 'Ana García')
        self.assertEqual(preview['value'], 85)
        # Descartar la vista previa (Cancelar) nunca escribe la nota.
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM grades').fetchall(), [])
        partial = self.client.post(url, json={'text': 'registrar nota'})
        self.assertEqual(partial.json['needs'], ['student', 'value'])
        response = self.client.post(url, json={'text': 'registrar nota', 'student_id': 1, 'value': '0'})
        self.assertEqual(response.json['needs'], [])
        token = response.json['preview']['token']
        self.client.post('/voz/confirmar', json={'token': token})
        self.client.post('/voz/confirmar', json={'token': token})
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM grades').fetchall(), [(1, 1, 0)])

    def test_school_commands_validate_course_and_values(self):
        self.client.post('/cursos/1/voz/crear-sesion', json={'class_date': '2026-11-18'})
        url = '/cursos/1/voz/vista-previa'
        for data in ({'text': 'registrar nota 101 al estudiante uno'},
                     {'text': 'registrar nota', 'student_id': 1, 'value': '-1'},
                     {'text': 'registrar nota', 'student_id': 1, 'value': '85.5'},
                     {'text': 'marcar ausente al estudiante 999'},
                     {'text': 'registrar nota 85 al estudiante uno', 'session_id': 999}):
            self.assertEqual(self.client.post(url, json=data).status_code, 400)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO courses VALUES (2,'Otro curso','Otro docente',2026)")
            db.execute("INSERT INTO students VALUES (6,2,'Otro','Alumno')")
        self.assertEqual(self.client.post(url, json={'text': 'marcar ausente al estudiante seis'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
