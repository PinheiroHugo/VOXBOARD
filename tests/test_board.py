from auth_helpers import authenticate_client
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

from app import BOARD_RESOURCES, create_app


class BoardTests(unittest.TestCase):
    def test_local_resources_and_return_preserve_session_data(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'board.sqlite3'
            client = authenticate_client(create_app({'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': database}).test_client())
            session_url = client.post('/sesiones', data={'class_date': '2026-11-14'}).location
            client.post(session_url, data={'status_1': 'presente', 'status_2': 'ausente'})
            client.post(session_url, data={'form_type': 'grades', 'grade_1': '85', 'grade_2': '0'})
            with closing(sqlite3.connect(database)) as db:
                before = {table: db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                          for table in ('courses', 'students', 'class_sessions', 'attendance', 'grades')}
            board_url = session_url + '/pizarra'
            self.assertIn(f'href="{board_url}"', client.get(session_url).get_data(as_text=True))
            response = client.get(board_url)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn(f'href="{session_url}"', html)
            self.assertIn('Volver a la sesión', html)
            self.assertEqual(html.count('data-resource-id='), 5)
            for resource_id, title in BOARD_RESOURCES:
                self.assertIn(f'data-resource-id="{resource_id}"', html)
                self.assertIn(title, html)
                resource = client.get(f'/static/resources/{resource_id}.svg')
                self.assertEqual(resource.status_code, 200)
                root = ET.fromstring(resource.data)
                resource.close()
                self.assertEqual(root.attrib['viewBox'], '0 0 1200 620')
                self.assertIsNotNone(root.find('{http://www.w3.org/2000/svg}title'))
                # Las ilustraciones no requieren imágenes, fuentes ni scripts externos.
                for element in root.iter():
                    self.assertNotIn(element.tag.split('}')[-1], ('image', 'script', 'foreignObject'))
                    self.assertNotIn('href', element.attrib)
            for url in ('/static/board.js', '/static/style.css'):
                with client.get(url) as asset:
                    self.assertEqual(asset.status_code, 200)
            # Probar archivos reales y MIME: un mock de DOM no detecta fallos de carga.
            self.assertNotIn('type="module"', html)
            self.assertLess(html.index('audio-wav.js'), html.index('voice.js'))
            for name in ('audio-wav.js', 'voice.js', 'recorder-worklet.js'):
                with client.get(f'/static/{name}') as asset:
                    self.assertEqual(asset.status_code, 200)
                    self.assertEqual(asset.mimetype, 'text/javascript')
            restored = client.get(session_url).get_data(as_text=True)
            self.assertIn('name="status_1" value="presente" checked', restored)
            self.assertIn('name="status_2" value="ausente" checked', restored)
            self.assertIn('step="1" value="85"', restored)
            self.assertIn('step="1" value="0"', restored)
            with closing(sqlite3.connect(database)) as db:
                after = {table: db.execute(f'SELECT * FROM {table} ORDER BY 1, 2').fetchall()
                         for table in before}
            self.assertEqual(before, after)
            self.assertEqual(client.get('/sesiones/9999/pizarra').status_code, 404)


if __name__ == '__main__':
    unittest.main()
