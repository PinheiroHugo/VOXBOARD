from auth_helpers import authenticate_client
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from ollama_client import OllamaError
from report_comments import generate_comment, validate_comment


class CommentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'comments.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}
        self.app = create_app(self.config)
        self.client = authenticate_client(self.app.test_client())
        self.url = '/cursos/1/comentarios?student_id=1'

    def sql(self, query, args=()):
        with closing(sqlite3.connect(self.database)) as db, db:
            return db.execute(query, args).fetchall()

    def seed(self):
        for date in ('2026-11-01', '2026-11-02', '2026-11-03'):
            self.client.post('/sesiones', data={'class_date': date})
        self.client.post('/sesiones/1', data={'form_type': 'grades', 'grade_1': '0'})
        self.client.post('/sesiones/2', data={'form_type': 'grades', 'grade_1': '100'})
        self.client.post('/sesiones/1', data={'status_1': 'presente'})
        self.client.post('/sesiones/2', data={'status_1': 'ausente'})

    def test_no_data_never_calls_ollama_and_empty_is_pending(self):
        self.client.post('/sesiones', data={'class_date': '2026-11-15'})
        with patch('report_comments.generate_comment') as generate:
            page = self.client.get(self.url).get_data(as_text=True)
            self.assertIn('Pendiente: no hay notas registradas', page)
            self.assertIn('Todavía no hay notas ni asistencia', page)
            response = self.client.post(self.url, data={'action': 'generate', 'comment': 'Texto del docente'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('Texto del docente', response.get_data(as_text=True))
            generate.assert_not_called()
        self.assertEqual(self.sql('SELECT * FROM report_comments'), [])
        self.assertIn('Comentarios de boletín', self.client.get('/').get_data(as_text=True))

    def test_aggregates_include_zero_pending_and_only_course_sessions(self):
        self.seed()
        # Registro de otro curso, que nunca debe entrar en el promedio.
        self.sql("INSERT INTO courses VALUES (2, 'Otro', 'Docente', 2026)")
        self.sql("INSERT INTO class_sessions VALUES (4, 2, '2026-11-04')")
        self.sql('INSERT INTO grades VALUES (4, 1, 20)')
        with patch('report_comments.generate_comment', return_value='Promedio de 50 en dos notas. Registra una presencia y una ausencia.') as generate:
            result = self.client.post(self.url, data={'action': 'generate'})
            self.assertEqual(result.status_code, 200)
            stats = generate.call_args.args[0]
        self.assertEqual(stats, {'sessions': 3, 'grade_count': 2, 'average': 50.0,
                                 'present': 1, 'absent': 1, 'pending_grades': 1, 'pending_attendance': 1})
        self.assertEqual(self.sql('SELECT * FROM report_comments'), [])
        self.assertIn('50.00 / 100', result.get_data(as_text=True))

    def test_partial_data_allows_generation_without_invented_average(self):
        self.client.post('/sesiones', data={'class_date': '2026-11-15'})
        self.client.post('/sesiones/1', data={'status_1': 'presente'})
        with patch('report_comments.generate_comment', return_value='Hay una presencia registrada. La nota está pendiente.') as generate:
            self.assertEqual(self.client.post(self.url, data={'action': 'generate'}).status_code, 200)
            self.assertIsNone(generate.call_args.args[0]['average'])
        self.client.post('/sesiones/1', data={'form_type': 'grades', 'grade_2': '0'})
        with patch('report_comments.generate_comment', return_value='El promedio es cero en una nota. La asistencia está pendiente.') as generate:
            self.assertEqual(self.client.post('/cursos/1/comentarios?student_id=2', data={'action': 'generate'}).status_code, 200)
            stats = generate.call_args.args[0]
            self.assertEqual(stats['average'], 0)
            self.assertEqual(stats['grade_count'], 1)
            self.assertEqual(stats['pending_attendance'], 1)

    def test_edit_save_update_restart_and_student_isolation(self):
        self.seed()
        before = {table: self.sql(f'SELECT * FROM {table}') for table in ('grades', 'attendance', 'students', 'class_sessions')}
        with patch('report_comments.generate_comment', return_value='Hay dos notas registradas. El promedio es 50.'):
            self.client.post(self.url, data={'action': 'generate'})
        self.assertEqual(self.sql('SELECT * FROM report_comments'), [])
        for text in ('Primer comentario del docente.', 'Comentario corregido y guardado con tildes: evaluación.'):
            result = self.client.post(self.url, data={'action': 'save', 'comment': text}, follow_redirects=True)
            self.assertIn('Comentario guardado correctamente.', result.get_data(as_text=True))
        self.assertEqual(self.sql('SELECT * FROM report_comments'), [(1, 1, text)])
        restarted = authenticate_client(create_app(self.config).test_client())
        self.assertIn(text, restarted.get(self.url).get_data(as_text=True))
        self.assertNotIn(text, restarted.get('/cursos/1/comentarios?student_id=2').get_data(as_text=True))
        self.assertEqual({table: self.sql(f'SELECT * FROM {table}') for table in before}, before)
        self.assertEqual(self.client.get('/cursos/1/comentarios?student_id=999').status_code, 404)
        self.sql("INSERT INTO courses VALUES (2, 'Otro', 'Docente', 2026)")
        self.sql("INSERT INTO students VALUES (6, 2, 'Otro', 'Alumno')")
        self.assertEqual(self.client.post('/cursos/1/comentarios?student_id=6', data={'action': 'save', 'comment': 'X'}).status_code, 404)

    def test_failure_preserves_saved_comment_and_unsaved_edits(self):
        self.seed()
        self.client.post(self.url, data={'action': 'save', 'comment': 'Versión guardada.'})
        for message in ('Ollama apagado', 'Ollama tardó demasiado', 'Salida inválida'):
            with patch('report_comments.generate_comment', side_effect=OllamaError(message)):
                response = self.client.post(self.url, data={'action': 'generate', 'comment': 'Edición pendiente.'})
                self.assertEqual(response.status_code, 400)
                self.assertIn('Edición pendiente.', response.get_data(as_text=True))
                self.assertIn(message, response.get_data(as_text=True))
            self.assertEqual(self.sql('SELECT comment FROM report_comments'), [('Versión guardada.',)])
        self.assertEqual(self.client.post(self.url, data={'action': 'save', 'comment': 'x' * 4001}).status_code, 400)
        self.assertEqual(self.sql('SELECT comment FROM report_comments'), [('Versión guardada.',)])

    def test_shared_client_prompt_and_sentence_validation(self):
        stats = {'sessions': 2, 'grade_count': 1, 'average': 0, 'present': 1, 'absent': 0,
                 'pending_grades': 1, 'pending_attendance': 1}
        with patch('report_comments.generate_json', return_value={'frases': ['El promedio es 0 en una nota.', 'Registra una presencia.']}) as client:
            self.assertEqual(generate_comment(stats, self.app.config), 'El promedio es 0 en una nota. Registra una presencia.')
            self.assertIs(client.call_args.args[0], self.app.config)
            prompt = client.call_args.kwargs
            self.assertIn('Promedio de las notas registradas: 0.00 sobre 100', prompt['prompt'])
            self.assertIn('Notas pendientes: 1', prompt['prompt'])
            self.assertIn('No atribuyas conductas', prompt['system'])
            self.assertIn('No expliques ni justifiques ausencias', prompt['system'])
        for data in ({}, {'frases': []}, {'frases': ['Una frase.']},
                     {'frases': ['Una.', 'Dos.', 'Tres.', 'Cuatro.']},
                     {'frases': ['Una.', '  ']}, {'frases': ['Una. Dos.', 'Tres.']},
                     {'frases': ['promedio: null.', 'cantidad_de_notas: 0.']}):
            with self.subTest(data=data), self.assertRaises(OllamaError):
                validate_comment(data)


if __name__ == '__main__':
    unittest.main()
