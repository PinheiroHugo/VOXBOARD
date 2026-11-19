"""Ayuda compartida: configuración y navegación sin servicios externos."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from auth_helpers import authenticate_client


class HelpTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'help-test',
                               'DATABASE': Path(directory.name) / 'test.sqlite3',
                               'VOXBOARD_HELP_URL': '', 'SEED_DEMO_DATA': True})
        self.client = authenticate_client(self.app.test_client())

    def test_unconfigured_help_on_main_screens(self):
        for path in ('/', '/cursos/1', '/gestion/configurar', '/gestiones'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('<summary>Ayuda</summary>', html)
                self.assertIn('El centro de ayuda estará disponible próximamente.', html)
                self.assertNotIn('class="help-link"', html)
        self.assertEqual(self.client.get('/mi-curso').location, '/cursos/1')

    def test_configured_link_opens_in_new_tab(self):
        self.app.config['VOXBOARD_HELP_URL'] = 'https://soporte.example.test/recursos?tema=voz&tipo=guia'
        for path in ('/', '/cursos/1'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('https://soporte.example.test/recursos?tema=voz&amp;tipo=guia', html)
            self.assertIn('target="_blank" rel="noopener noreferrer"', html)
            self.assertNotIn('<summary>Ayuda</summary>', html)

    def test_invalid_url_has_safe_fallback(self):
        for value in ('javascript:alert(1)', '/no-existe', 'https://', 'https://[invalid', ''):
            self.app.config['VOXBOARD_HELP_URL'] = value
            self.assertIn('<summary>Ayuda</summary>', self.client.get('/').get_data(as_text=True))

    def test_environment_configuration(self):
        with patch.dict('os.environ', {'VOXBOARD_HELP_URL': 'https://soporte.example.test/recursos'}):
            app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'DATABASE': self.app.config['DATABASE']})
        self.assertEqual(app.config['VOXBOARD_HELP_URL'], 'https://soporte.example.test/recursos')
