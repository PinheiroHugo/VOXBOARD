from auth_helpers import authenticate_client
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.error import URLError, HTTPError

from flask import template_rendered
from app import create_app
from trivia import generate_trivia, validate_trivia, TriviaError, TRIVIA_SCHEMA


def valid_trivia():
    return {'preguntas': [{'enunciado': f'¿Qué necesita la planta? Pregunta {i + 1}',
                           'opciones': ['Agua', 'Plástico', 'Metal'], 'correcta': 'A'} for i in range(5)]}


def form_for(data, action='save'):
    result = {'action': action}
    for i, question in enumerate(data['preguntas']):
        result[f'q{i}'] = question['enunciado']
        result[f'correct{i}'] = question['correcta']
        for letter, option in zip('ABC', question['opciones']):
            result[f'q{i}_{letter}'] = option
    return result


class TriviaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'trivia.sqlite3'
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database, 'OLLAMA_MODEL': 'qwen2.5:3b'}
        self.app = create_app(self.config)
        self.client = authenticate_client(self.app.test_client())
        self.session_url = self.client.post('/sesiones', data={'class_date': '2026-11-15'}).location
        self.url = self.session_url + '/trivia'

    def rows(self, table):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(f'SELECT * FROM {table}').fetchall()

    def summary(self):
        self.client.post(self.session_url + '/resumen', json={'summary': 'Las plantas necesitan agua y luz.'})

    def test_empty_summary_does_not_call_ollama(self):
        with patch('trivia.generate_trivia') as generate:
            result = self.client.post(self.url, data={'action': 'generate'})
            self.assertEqual(result.status_code, 400)
            self.assertIn('Primero completá y guardá el resumen', result.get_data(as_text=True))
            generate.assert_not_called()
        self.assertEqual(self.rows('session_trivias'), [])

    def test_generate_edit_save_restart_project_and_isolation(self):
        self.summary()
        self.client.post(self.session_url, data={'status_1': 'presente'})
        self.client.post(self.session_url, data={'form_type': 'grades', 'grade_1': '85'})
        before = {table: self.rows(table) for table in ('courses', 'students', 'attendance', 'grades', 'session_summaries')}
        with patch('trivia.generate_trivia', return_value=valid_trivia()) as generate:
            result = self.client.post(self.url, data={'action': 'generate'}, follow_redirects=True)
            self.assertEqual(result.status_code, 200)
            self.assertIn('Borrador generado y guardado', result.get_data(as_text=True))
            self.assertEqual(generate.call_args.args[0], 'Las plantas necesitan agua y luz.')
        edited = valid_trivia()
        edited['preguntas'][0] = {'enunciado': 'Enunciado editado por el docente',
                                   'opciones': ['Tierra', 'Luz solar', 'Piedras'], 'correcta': 'B'}
        result = self.client.post(self.url, data=form_for(edited), follow_redirects=True)
        self.assertIn('Trivia guardada correctamente', result.get_data(as_text=True))
        self.assertEqual(len(self.rows('session_trivias')), 1)
        self.assertEqual(json.loads(self.rows('session_trivias')[0][1]), edited)
        restarted = authenticate_client(create_app(self.config).test_client())
        self.assertIn('Enunciado editado por el docente', restarted.get(self.url).get_data(as_text=True))
        contexts = []
        def capture(sender, template, context, **extra):
            contexts.append(context)
        with template_rendered.connected_to(capture, self.app):
            result = self.client.get(self.url + '/proyectar')
        html = result.get_data(as_text=True)
        self.assertEqual(result.status_code, 200)
        self.assertIn('Enunciado editado por el docente', html)
        self.assertNotIn('correcta', html)
        self.assertNotIn('selected', html)
        self.assertNotIn('name="correct', html)
        self.assertNotIn('data-correcta', html)
        self.assertTrue(all(set(q) == {'enunciado', 'opciones'} for q in contexts[0]['questions']))
        self.assertNotIn('draft', contexts[0])
        other = self.client.post('/sesiones', data={'class_date': '2026-11-16'}).location
        self.assertNotIn('Enunciado editado por el docente', self.client.get(other + '/trivia').get_data(as_text=True))
        self.assertEqual(self.client.get(other + '/trivia/proyectar').status_code, 302)
        self.assertEqual({table: self.rows(table) for table in before}, before)

    def test_generation_failures_preserve_saved_and_unsaved_draft(self):
        self.summary()
        original = valid_trivia()
        self.client.post(self.url, data=form_for(original))
        before = self.rows('session_trivias')
        edited = copy.deepcopy(original)
        edited['preguntas'][0]['enunciado'] = 'Edición pendiente sin guardar'
        for message in ('Ollama está apagado', 'Ollama tardó demasiado', 'Salida inválida'):
            with patch('trivia.generate_trivia', side_effect=TriviaError(message)):
                result = self.client.post(self.url, data=form_for(edited, 'generate'))
            self.assertEqual(result.status_code, 400)
            self.assertIn(message, result.get_data(as_text=True))
            self.assertIn('Edición pendiente sin guardar', result.get_data(as_text=True))
            self.assertEqual(self.rows('session_trivias'), before)
        invalid = copy.deepcopy(original)
        invalid['preguntas'][1]['opciones'] = ['Agua', ' agua ', 'Metal']
        result = self.client.post(self.url, data=form_for(invalid))
        self.assertEqual(result.status_code, 400)
        self.assertIn('deben ser distintas', result.get_data(as_text=True))
        self.assertEqual(self.rows('session_trivias'), before)

    def test_structure_rejects_incomplete_or_invalid_questions(self):
        invalid = [None, [], {}, {'preguntas': valid_trivia()['preguntas'][:4]}]
        for key, value in [('enunciado', ''), ('enunciado', 1), ('opciones', ['a', 'b']),
                           ('opciones', ['a', 'b', 'a']), ('opciones', ['a', 'b', '']),
                           ('correcta', 'D'), ('correcta', 1)]:
            data = valid_trivia()
            data['preguntas'][0][key] = value
            invalid.append(data)
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(TriviaError):
                validate_trivia(data)

    def test_http_schema_config_and_failures(self):
        config = {**self.app.config, 'OLLAMA_MODEL': 'modelo-local-configurado', 'OLLAMA_TIMEOUT': 3}
        opener = MagicMock()
        def reply(body):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = body
            opener.open.return_value = response
        with patch('ollama_client.http.build_opener', return_value=opener):
            reply(json.dumps({'done': True, 'response': json.dumps(valid_trivia())}).encode())
            self.assertEqual(generate_trivia('Resumen de prueba', config), valid_trivia())
            query = opener.open.call_args.args[0]
            payload = json.loads(query.data)
            self.assertEqual(query.full_url, 'http://127.0.0.1:11434/api/generate')
            self.assertEqual(payload['format'], TRIVIA_SCHEMA)
            self.assertFalse(payload['stream'])
            self.assertEqual(payload['model'], 'modelo-local-configurado')
            self.assertIn('Resumen de prueba', payload['prompt'])
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 3)
            for body in (b'not json', b'{}', b'{"done":true,"response":"not json"}',
                         json.dumps({'done': True, 'response': '{"preguntas":[]}'}).encode()):
                reply(body)
                with self.assertRaises(TriviaError):
                    generate_trivia('Resumen', config)
            for failure, message in [(TimeoutError(), 'tardó demasiado'),
                                     (URLError(ConnectionRefusedError()), 'conectar'),
                                     (HTTPError('http://localhost', 404, 'missing', {}, io.BytesIO()), 'no está disponible')]:
                opener.open.side_effect = failure
                with self.assertRaisesRegex(TriviaError, message):
                    generate_trivia('Resumen', config)
                if isinstance(failure, HTTPError):
                    self.assertTrue(failure.closed)


if __name__ == '__main__':
    unittest.main()
