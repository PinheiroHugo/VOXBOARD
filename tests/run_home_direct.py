"""Prueba real de navegador y VAD con audio sintético y transcripciones simuladas."""
from pathlib import Path
import hashlib
import math
import os
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from waitress import create_server


def main():
    original = ROOT / 'instance/voxboard.sqlite3'
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='vox-direct-') as directory:
        folder = Path(directory)
        audio = folder / 'voice-and-pause.wav'
        with wave.open(str(audio), 'wb') as output:
            output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            samples = [int(6000 * math.sin(2 * math.pi * 220 * i / 48000)) if 12000 <= i < 48000 else 0 for i in range(48000 * 4)]
            output.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
        database = folder / 'test.sqlite3'
        app = create_app({'DATABASE': database, 'TESTING': True})
        @app.get('/__test__/counts')
        def counts():
            with closing(sqlite3.connect(database)) as db:
                return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                        for table in ('grades', 'attendance', 'class_sessions', 'courses')}
        server = create_server(app, host='127.0.0.1', port=0, threads=8)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        env = {**os.environ, 'VOXBOARD_TEST_URL': f'http://127.0.0.1:{server.effective_port}', 'VOXBOARD_FAKE_AUDIO': str(audio)}
        try:
            subprocess.run(['node', str(ROOT / 'tests/browser_home_direct.cjs')], env=env, check=True, timeout=180)
            with closing(sqlite3.connect(database)) as db:
                assert db.execute('SELECT COUNT(*) FROM grades').fetchone()[0] == 1
                assert db.execute('SELECT COUNT(*) FROM attendance').fetchone()[0] == 2
                assert db.execute('SELECT COUNT(*) FROM courses').fetchone()[0] == 2
                assert db.execute('SELECT school_year FROM courses c JOIN annual_settings a ON a.active_course_id=c.id').fetchone()[0] == 2027
            print('SQLite: dos fechas de asistencia, nota conservada y ambas gestiones presentes.', flush=True)
        finally:
            server.close(); server.task_dispatcher.shutdown(); thread.join(timeout=5)
            assert before == hashlib.sha256(original.read_bytes()).hexdigest()
            print('Registros existentes intactos (SHA-256).', flush=True)


if __name__ == '__main__':
    main()
