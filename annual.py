"""Curso anual activo y registros diarios internos, sin borrar el historial."""
from datetime import date, datetime, timedelta, timezone
import sqlite3

from flask import Blueprint, abort, redirect, render_template, request, url_for


def local_today():
    return datetime.now(timezone(timedelta(hours=-4))).date().isoformat()


def valid_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError('Ingresá una fecha válida.') from None


def migrate_annual(db):
    db.execute('''CREATE TABLE IF NOT EXISTS annual_courses (
        school_year INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL UNIQUE REFERENCES courses(id)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS annual_settings (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        active_course_id INTEGER REFERENCES courses(id)
    )''')
    # Los cursos anteriores se conservan, incluso si había más de uno por año.
    db.execute('''INSERT OR IGNORE INTO annual_courses
                  SELECT school_year, MIN(id) FROM courses GROUP BY school_year''')
    db.execute('''INSERT OR IGNORE INTO annual_settings (id, active_course_id)
                  VALUES (1, (SELECT course_id FROM annual_courses ORDER BY school_year DESC LIMIT 1))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_days (
        course_id INTEGER NOT NULL REFERENCES courses(id),
        class_date TEXT NOT NULL,
        session_id INTEGER UNIQUE REFERENCES class_sessions(id),
        PRIMARY KEY(course_id, class_date)
    )''')
    db.execute('''INSERT OR IGNORE INTO course_days
                  SELECT course_id, class_date, MIN(id) FROM class_sessions GROUP BY course_id, class_date''')
    # Vista no destructiva. Si había varias sesiones de un día, la asistencia
    # más reciente del estudiante representa ese día; los originales siguen allí.
    db.execute('''CREATE VIEW IF NOT EXISTS attendance_by_date AS
        SELECT s.course_id, a.student_id, s.class_date, a.status, a.session_id
        FROM attendance a JOIN class_sessions s ON s.id = a.session_id
        WHERE a.session_id = (
            SELECT MAX(a2.session_id) FROM attendance a2
            JOIN class_sessions s2 ON s2.id = a2.session_id
            WHERE s2.course_id = s.course_id AND s2.class_date = s.class_date
              AND a2.student_id = a.student_id
        )''')


def active_course(db):
    return db.execute('''SELECT c.* FROM courses c JOIN annual_settings a
                         ON c.id = a.active_course_id WHERE a.id = 1''').fetchone()


def ensure_day(db, course_id, class_date):
    """Reserva la fecha bajo el bloqueo de escritura, antes de crear su contexto."""
    class_date = valid_date(class_date)
    db.execute('INSERT OR IGNORE INTO course_days (course_id,class_date) VALUES (?,?)', (course_id, class_date))
    row = db.execute('SELECT session_id FROM course_days WHERE course_id = ? AND class_date = ?', (course_id, class_date)).fetchone()
    if row[0] is not None:
        return row[0]
    existing = db.execute('SELECT MIN(id) FROM class_sessions WHERE course_id = ? AND class_date = ?', (course_id, class_date)).fetchone()[0]
    if existing is None:
        existing = db.execute('INSERT INTO class_sessions (course_id,class_date) VALUES (?,?)', (course_id, class_date)).lastrowid
    db.execute('UPDATE course_days SET session_id = ? WHERE course_id = ? AND class_date = ?', (existing, course_id, class_date))
    return existing


def create_annual_blueprint(connect):
    blueprint = Blueprint('annual', __name__)

    @blueprint.route('/gestion/configurar', methods=['GET', 'POST'])
    def configure():
        edit_id = request.args.get('course_id', type=int)
        with connect() as db:
            current = active_course(db)
            course = db.execute('SELECT * FROM courses WHERE id = ?', (edit_id,)).fetchone() if edit_id else None
            if edit_id and (course is None or current is None or course['id'] != current['id']):
                abort(403)
            students = db.execute('SELECT * FROM students WHERE course_id = ? ORDER BY id', (edit_id,)).fetchall() if course else []
        error = ''
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            teacher = request.form.get('teacher', '').strip()
            try:
                year = int(request.form.get('school_year', ''))
                if not 2000 <= year <= 2200:
                    raise ValueError('Ingresá una gestión entre 2000 y 2200.')
                if not 1 <= len(name) <= 120 or not 1 <= len(teacher) <= 120:
                    raise ValueError('Completá el nombre del curso y del docente (hasta 120 caracteres).')
                new_students = []
                for line in request.form.get('new_students', '').splitlines():
                    if not line.strip():
                        continue
                    parts = [part.strip() for part in line.split(';')]
                    if len(parts) != 2 or any(not part or len(part) > 80 for part in parts):
                        raise ValueError('Escribí un estudiante por línea con el formato Nombres;Apellidos (hasta 80 caracteres por campo).')
                    new_students.append(parts)
                if len(new_students) + len(students) > 100:
                    raise ValueError('Esta versión admite hasta 100 estudiantes por curso.')
                if not course and not new_students:
                    raise ValueError('Ingresá al menos un estudiante.')
                edits = []
                for student in students:
                    first = request.form.get(f'first_{student["id"]}', '').strip()
                    last = request.form.get(f'last_{student["id"]}', '').strip()
                    if not first or not last or len(first) > 80 or len(last) > 80:
                        raise ValueError('Completá los nombres y apellidos de los estudiantes existentes.')
                    edits.append((first, last, student['id']))
                with connect() as db:
                    if course:
                        if year != course['school_year'] or active_course(db)['id'] != course['id']:
                            raise ValueError('La gestión cambió. Recargá la página antes de editar.')
                        course_id = course['id']
                        db.execute('UPDATE courses SET name = ?, teacher = ? WHERE id = ?', (name, teacher, course_id))
                        db.executemany('UPDATE students SET first_name = ?, last_name = ? WHERE id = ?', edits)
                    else:
                        if db.execute('SELECT 1 FROM annual_courses WHERE school_year = ?', (year,)).fetchone():
                            raise ValueError('Esa gestión ya tiene un curso. Consultala en el historial o editá el curso activo.')
                        course_id = db.execute('INSERT INTO courses (name,teacher,school_year) VALUES (?,?,?)', (name, teacher, year)).lastrowid
                        db.execute('INSERT INTO annual_courses VALUES (?,?)', (year, course_id))
                        db.execute('UPDATE annual_settings SET active_course_id = ? WHERE id = 1', (course_id,))
                    db.executemany('INSERT INTO students (course_id,first_name,last_name) VALUES (?,?,?)',
                                   [(course_id, first, last) for first, last in new_students])
                return redirect(url_for('annual.course', course_id=course_id, saved=1))
            except (ValueError, sqlite3.IntegrityError) as exc:
                error = str(exc) if isinstance(exc, ValueError) else 'No se pudo configurar la gestión. Recargá e intentá nuevamente.'
        return render_template('annual_setup.html', course=course, students=students, error=error,
                               default_year=int(local_today()[:4])), 400 if error else 200

    @blueprint.get('/mi-curso')
    def active():
        with connect() as db:
            course = active_course(db)
        if course is None:
            return redirect(url_for('annual.configure'))
        return redirect(url_for('annual.course', course_id=course['id']))

    @blueprint.get('/cursos/<int:course_id>')
    def course(course_id):
        with connect() as db:
            course = db.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
            if course is None:
                abort(404)
            current = active_course(db)
            students = db.execute('SELECT * FROM students WHERE course_id = ? ORDER BY last_name,first_name', (course_id,)).fetchall()
            records = db.execute('SELECT * FROM class_sessions WHERE course_id = ? ORDER BY class_date DESC,id DESC', (course_id,)).fetchall()
        return render_template('annual_course.html', course=course, students=students, records=records,
                               is_active=current is not None and current['id'] == course_id)

    @blueprint.get('/gestiones')
    def history():
        with connect() as db:
            courses = db.execute('SELECT * FROM courses ORDER BY school_year DESC,id').fetchall()
            current = active_course(db)
        return render_template('annual_history.html', courses=courses, active=current)

    @blueprint.get('/mi-curso/registro')
    def daily():
        try:
            day = valid_date(request.args.get('fecha', local_today()))
        except ValueError as exc:
            abort(400, description=str(exc))
        with connect() as db:
            course = active_course(db)
            if course is None:
                return redirect(url_for('annual.configure'))
            session_id = ensure_day(db, course['id'], day)
        section = request.args.get('seccion', 'asistencia')
        if section == 'pizarra':
            return redirect(url_for('board', session_id=session_id))
        if section == 'trivia':
            return redirect(url_for('trivia.editor', session_id=session_id))
        return redirect(url_for('session_detail', session_id=session_id, _anchor='calificaciones' if section == 'calificaciones' else 'asistencia'))

    return blueprint
