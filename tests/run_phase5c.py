"""Ensayo de navegador con SQLite temporal; no detiene Ollama ni usa el micrófono físico."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
original = ROOT / 'instance' / 'voxboard.sqlite3'
before = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None

from app import create_app
from werkzeug.serving import make_server, WSGIRequestHandler


class QuietRequests(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        pass


def main():
    with tempfile.TemporaryDirectory(prefix='voxboard-ensayo-') as folder:
        database = Path(folder) / 'ensayo.sqlite3'
        app = create_app({'DATABASE': database, 'SEED_DEMO_DATA': True, 'TESTING': True})
        offline = socket.socket()
        offline.bind(('127.0.0.1', 0))
        # Un socket enlazado pero sin listen rechaza conexiones sin interferir con Ollama.
        @app.post('/__test__/ollama/unavailable')
        def unavailable():
            app.config['OLLAMA_URL'] = f'http://127.0.0.1:{offline.getsockname()[1]}'
            return {'testing': True}
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietRequests)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = {**os.environ, 'VOXBOARD_TEST_URL': f'http://127.0.0.1:{server.server_port}',
               'VOXBOARD_FULL_TEST': os.environ.get('VOXBOARD_FULL_TEST', '1')}
        try:
            subprocess.run(['node', str(ROOT / 'tests' / 'browser_voice_smoke.cjs')], env=env, check=True, timeout=420)
            with closing(sqlite3.connect(database)) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
                for table, keys in [('attendance','session_id,student_id'), ('grades','session_id,student_id')]:
                    assert not db.execute(f'SELECT {keys}, COUNT(*) FROM {table} GROUP BY {keys} HAVING COUNT(*) > 1').fetchall()
            print('SQLite temporal: integridad y unicidad correctas.', flush=True)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5); offline.close()
            after = hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None
            assert before == after, 'La base existente cambió durante el ensayo.'
            print('Base existente preservada: SHA-256 idéntico antes y después.', flush=True)


if __name__ == '__main__':
    main()
