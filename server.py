"""Waitress loopback: configuración local o detrás de Quick Tunnel HTTPS."""
import argparse
from contextlib import closing
import sqlite3

from app import BASE_DIR, DATABASE, create_app


def build_app(*, demo=False, tunnel=False):
    database = BASE_DIR / 'instance' / 'demo' / 'voxboard.sqlite3' if demo else DATABASE
    # No habilitar configuración inicial de cuenta en una URL pública.
    if tunnel:
        if not database.is_file():
            raise ValueError('Primero iniciá sin --tunnel y creá la cuenta docente localmente.')
        with closing(sqlite3.connect(database)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'teachers' not in tables or db.execute('SELECT COUNT(*) FROM teachers').fetchone()[0] != 1:
                raise ValueError('Primero creá la cuenta docente localmente, sin --tunnel.')
    application = create_app({'DATABASE': database, 'SEED_DEMO_DATA': demo,
                              'DEBUG': False, 'TESTING': False,
                              'SESSION_COOKIE_SECURE': tunnel,
                              'MAX_CONTENT_LENGTH': 2_000_000})
    if tunnel and len(application.secret_key or '') < 32:
        raise ValueError('La clave persistente debe tener al menos 32 caracteres para el túnel.')
    return application


def server_options(*, tunnel=False, port=8080):
    # Solo cloudflared/cliente local puede llegar al origen. No confiar en
    # cabeceras Forwarded arbitrarias: el modo túnel fija el esquema HTTPS.
    return dict(host='127.0.0.1', port=port, threads=8,
                url_scheme='https' if tunnel else 'http',
                clear_untrusted_proxy_headers=True,
                max_request_body_size=2_000_000, expose_tracebacks=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Usar SQLite ficticio separado en instance/demo')
    parser.add_argument('--tunnel', action='store_true', help='Cookies Secure y esquema HTTPS; requiere cuenta previa')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Puerto fuera de rango.')
    try:
        application = build_app(demo=args.demo, tunnel=args.tunnel)
    except (ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    from waitress import serve
    print('VOXBOARD: datos ' + ('ficticios separados' if args.demo else 'habituales') +
          f', origen 127.0.0.1:{args.port}, ' + ('modo HTTPS/túnel.' if args.tunnel else 'modo local.'), flush=True)
    serve(application, **server_options(tunnel=args.tunnel, port=args.port))


if __name__ == '__main__':
    main()
