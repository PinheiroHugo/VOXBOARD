"""Respaldo/restauración SQLite. Detener VOXBOARD antes de restaurar."""
import argparse
from contextlib import closing
from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3
import tempfile

from app import BASE_DIR, DATABASE


def validate(database):
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError('No existe el archivo SQLite indicado.')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('La copia no supera la comprobación de integridad.')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('La copia contiene relaciones inválidas.')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'teachers', 'courses', 'students', 'attendance', 'grades'} <= tables:
            raise ValueError('El archivo no contiene una base VOXBOARD reconocida.')


def backup_database(database, folder):
    database = Path(database).resolve()
    validate(database)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('voxboard-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
    validate(target)
    return target


def restore_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    validate(source)
    if source == destination:
        raise ValueError('El respaldo y el destino deben ser archivos diferentes.')
    if any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Hay archivos auxiliares SQLite. Detené todas las instancias y revisá la base antes de restaurar.')
    previous = None
    if destination.exists():
        try:
            previous = backup_database(destination, destination.parent / 'backups')
        except (ValueError, sqlite3.DatabaseError):
            # Preservar también una base dañada para permitir recuperar una copia válida.
            folder = destination.parent / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            previous = folder / ('antes-restauracion-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.damaged')
            shutil.copy2(destination, previous)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.restore-', suffix='.sqlite3', dir=destination.parent)
    os.close(descriptor)
    staged = Path(name)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as saved, closing(sqlite3.connect(staged)) as current:
            saved.backup(current)
        validate(staged)
        os.replace(staged, destination)
    finally:
        if staged.exists():
            staged.unlink()
    return previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'restore'))
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--source', type=Path, help='Archivo de respaldo para restaurar')
    parser.add_argument('--server-stopped', action='store_true', help='Confirma que se detuvieron todas las instancias')
    args = parser.parse_args()
    database = BASE_DIR / 'instance/demo/voxboard.sqlite3' if args.demo else DATABASE
    try:
        if args.action == 'backup':
            print(backup_database(database, database.parent / 'backups'))
        else:
            if not args.source or not args.server_stopped:
                parser.error('Restaurar requiere --source ARCHIVO y --server-stopped; detener servidor y túnel antes.')
            previous = restore_database(args.source, database)
            print('Restauración verificada. Respaldo previo:', previous or 'no había base anterior')
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
