from auth_helpers import authenticate_client
import io
from importlib.machinery import ModuleSpec
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import MagicMock, patch
import wave

from app import create_app


def wav_audio(channels=1, rate=16000, frames=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b'\x00\x00' * frames * channels)
    return buffer.getvalue()


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'voice.sqlite3'
        model_path = Path(self.temp.name) / 'model'
        model_path.mkdir()
        self.config = {'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database,
                       'VOSK_MODEL_PATH': model_path}
        self.client = authenticate_client(create_app(self.config).test_client())

    def post(self, data):
        return self.client.post('/api/voz/transcribir', data=data, content_type='audio/wav')

    def test_missing_model_and_dependency(self):
        client = authenticate_client(create_app({**self.config, 'VOSK_MODEL_PATH': Path(self.temp.name) / 'missing'}).test_client())
        self.assertFalse(client.get('/api/voz/estado').json['available'])
        response = client.post('/api/voz/transcribir', data=wav_audio())
        self.assertEqual(response.status_code, 503)
        self.assertIn('Falta el modelo', response.json['error'])
        with patch('voice.importlib.util.find_spec', return_value=None):
            self.assertIn('Falta instalar Vosk', self.client.get('/api/voz/estado').json['message'])

    def test_reject_invalid_audio_before_recognition(self):
        for data in (b'', b'not a wav', wav_audio(channels=2), wav_audio(rate=48000),
                     wav_audio(frames=0), wav_audio(frames=480001), wav_audio()[:-10]):
            with self.subTest(length=len(data)):
                self.assertEqual(self.post(data).status_code, 400)
        self.assertEqual(self.post(b'0' * 1000001).status_code, 413)

    def test_recognition_accumulates_segments_and_does_not_modify_session(self):
        url = self.client.post('/sesiones', data={'class_date': '2026-11-14'}).location
        self.client.post(url, data={'status_1': 'presente'})
        self.client.post(url, data={'form_type': 'grades', 'grade_1': '80'})
        def snapshot():
            with closing(sqlite3.connect(self.database)) as db:
                return {table: db.execute(f'SELECT * FROM {table}').fetchall()
                        for table in ('courses', 'students', 'class_sessions', 'attendance', 'grades')}
        before = snapshot()
        fake = MagicMock()
        fake.__spec__ = ModuleSpec('vosk', loader=None)
        recognizer = fake.KaldiRecognizer.return_value
        recognizer.AcceptWaveform.side_effect = lambda data: True
        recognizer.Result.return_value = json.dumps({'text': 'hola'})
        recognizer.FinalResult.return_value = json.dumps({'text': 'mundo'})
        with patch.dict('sys.modules', {'vosk': fake}):
            response = self.post(wav_audio(frames=4000))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['text'], 'hola mundo')
            self.post(wav_audio(frames=4000))
            fake.Model.assert_called_once_with(str(self.config['VOSK_MODEL_PATH']))
            self.assertEqual(fake.KaldiRecognizer.call_count, 2)
        self.assertEqual(snapshot(), before)

    def test_empty_transcript_and_model_load_error(self):
        fake = MagicMock()
        fake.__spec__ = ModuleSpec('vosk', loader=None)
        fake.KaldiRecognizer.return_value.AcceptWaveform.return_value = False
        fake.KaldiRecognizer.return_value.FinalResult.return_value = '{"text": ""}'
        with patch.dict('sys.modules', {'vosk': fake}):
            response = self.post(wav_audio())
            self.assertEqual(response.json['text'], '')
            self.assertIn('No se reconoció texto', response.json['message'])
        self.client = authenticate_client(create_app(self.config).test_client())
        fake.Model.side_effect = RuntimeError('incomplete model')
        with patch.dict('sys.modules', {'vosk': fake}):
            response = self.post(wav_audio())
            self.assertEqual(response.status_code, 503)
            self.assertIn('No se pudo cargar', response.json['error'])


if __name__ == '__main__':
    unittest.main()
