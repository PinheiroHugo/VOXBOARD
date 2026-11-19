"""VOXBOARD: curso, sesiones de clase, asistencia y calificaciones."""

from datetime import date
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import re
import mimetypes
import os
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for, session as browser_session
from itsdangerous import URLSafeTimedSerializer, BadSignature
from school_records import parse_school_command, parse_school_intent, save_attendance, save_grade
from voice import create_voice_blueprint
from trivia import create_trivia_blueprint
from report_comments import create_comments_blueprint
from performance import create_performance_blueprint
from auth import configure_auth, persistent_secret
from annual import active_course, ensure_day, local_today, valid_date, migrate_annual, create_annual_blueprint


BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "instance" / "voxboard.sqlite3"

# Identificadores públicos estables para botones y futuros comandos de voz.
BOARD_RESOURCES = (
    ('sistema-solar', 'Sistema solar'),
    ('ciclo-del-agua', 'Ciclo del agua'),
    ('partes-de-una-planta', 'Partes de una planta'),
    ('estados-de-la-materia', 'Estados de la materia'),
    ('cadena-alimentaria', 'Cadena alimentaria'),
)


def init_db(database=DATABASE, seed_demo=False):
    """Crea la base y carga datos de ejemplo de forma idempotente."""
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute('''CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0
        )''')
        connection.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                teacher TEXT NOT NULL,
                school_year INTEGER NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY,
                course_id INTEGER NOT NULL REFERENCES courses(id),
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS class_sessions (
                id INTEGER PRIMARY KEY,
                course_id INTEGER NOT NULL REFERENCES courses(id),
                class_date TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                session_id INTEGER NOT NULL REFERENCES class_sessions(id),
                student_id INTEGER NOT NULL REFERENCES students(id),
                status TEXT NOT NULL CHECK (status IN ('presente', 'ausente')),
                PRIMARY KEY (session_id, student_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS grades (
                session_id INTEGER NOT NULL REFERENCES class_sessions(id),
                student_id INTEGER NOT NULL REFERENCES students(id),
                score INTEGER NOT NULL CHECK (typeof(score) = 'integer' AND score BETWEEN 0 AND 100),
                PRIMARY KEY (session_id, student_id)
            )
        """)
        connection.execute('''CREATE TABLE IF NOT EXISTS session_summaries (
            session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
            summary TEXT NOT NULL DEFAULT ''
        )''')
        connection.execute('''CREATE TABLE IF NOT EXISTS session_trivias (
            session_id INTEGER PRIMARY KEY REFERENCES class_sessions(id),
            content TEXT NOT NULL
        )''')
        connection.execute('''CREATE TABLE IF NOT EXISTS report_comments (
            course_id INTEGER NOT NULL REFERENCES courses(id),
            student_id INTEGER NOT NULL REFERENCES students(id),
            comment TEXT NOT NULL,
            PRIMARY KEY (course_id, student_id)
        )''')
        if seed_demo:
            connection.execute(
                "INSERT OR IGNORE INTO courses VALUES (?, ?, ?, ?)",
                (1, "Tercero de primaria · A", "María Fernández", 2026),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO students VALUES (?, ?, ?, ?)",
                [
                    (1, 1, "Ana", "García"),
                    (2, 1, "Mateo", "López"),
                    (3, 1, "Sofía", "Mamani"),
                    (4, 1, "Lucas", "Pérez"),
                    (5, 1, "Valentina", "Rojas"),
                ],
            )
        migrate_annual(connection)


def create_app(config=None):
    # Windows puede asociar .js a tipos ajenos a JavaScript en su registro.
    # AudioWorklet exige un MIME JavaScript válido.
    mimetypes.add_type('text/javascript', '.js')
    app = Flask(__name__)
    app.config['DATABASE'] = DATABASE
    app.config['SECRET_KEY'] = None
    app.config['VOXBOARD_HELP_URL'] = os.environ.get('VOXBOARD_HELP_URL', '')
    app.config['OLLAMA_MODEL'] = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')
    app.config['OLLAMA_URL'] = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
    app.config['OLLAMA_TIMEOUT'] = float(os.environ.get('OLLAMA_TIMEOUT', '120'))
    app.config['VOSK_MODEL_PATH'] = BASE_DIR / 'models' / 'vosk-model-small-es-0.42'
    if config:
        app.config.update(config)

    @app.context_processor
    def help_context():
        value = str(app.config.get('VOXBOARD_HELP_URL') or '').strip()
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme in ('http', 'https') and bool(parsed.hostname)
                     and not any(character.isspace() for character in value)
                     and not parsed.username and not parsed.password)
        except ValueError:
            valid = False
        return {'help_url': value if valid else ''}

    if not app.config['SECRET_KEY']:
        app.config['SECRET_KEY'] = persistent_secret(app.config['DATABASE'])
    init_db(app.config['DATABASE'], app.config.get('SEED_DEMO_DATA', False))
    app.register_blueprint(create_voice_blueprint(app.config['VOSK_MODEL_PATH']))
    command_signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='school-command')

    @contextmanager
    def connect():
        connection = sqlite3.connect(app.config['DATABASE'], timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @app.get("/")
    def index():
        with connect() as connection:
            course = active_course(connection)
            students = connection.execute(
                'SELECT * FROM students WHERE course_id = ? ORDER BY last_name,first_name',
                (course['id'],),
            ).fetchall() if course else []
        return render_template('index.html', course=course, students=students,
                               resources=BOARD_RESOURCES, today=local_today())

    @app.post('/sesiones')
    def create_session():
        raw_date = request.form.get('class_date', '')
        try:
            class_date = date.fromisoformat(raw_date).isoformat()
        except ValueError:
            abort(400, description='Ingresá una fecha válida para la sesión.')
        with connect() as connection:
            course = active_course(connection)
            if course is None:
                return redirect(url_for('annual.configure'))
            session_id = ensure_day(connection, course['id'], class_date)
        browser_session['active_class_session'] = session_id
        resource = request.form.get('resource')
        if resource in dict(BOARD_RESOURCES):
            return redirect(url_for('board', session_id=session_id, resource=resource, from_vox=1))
        return redirect(url_for('session_detail', session_id=session_id))

    @app.route('/sesiones/<int:session_id>', methods=['GET', 'POST'])
    def session_detail(session_id):
        with connect() as connection:
            session = connection.execute(
                '''SELECT s.*, c.name AS course_name FROM class_sessions s
                   JOIN courses c ON c.id = s.course_id WHERE s.id = ?''',
                (session_id,),
            ).fetchone()
            if session is None:
                abort(404)
            current = active_course(connection)
            read_only = current is None or current['id'] != session['course_id']
            if read_only and request.method == 'POST':
                abort(403, description='Esta gestión es de consulta. El curso activo pertenece a otra gestión.')
            students = connection.execute(
                '''SELECT st.*, a.status, g.score FROM students st
                   LEFT JOIN attendance_by_date a ON a.student_id = st.id AND a.course_id = st.course_id AND a.class_date = ?
                   LEFT JOIN grades g ON g.student_id = st.id AND g.session_id = ?
                   WHERE st.course_id = ? ORDER BY st.last_name, st.first_name''',
                (session['class_date'], session_id, session['course_id']),
            ).fetchall()
            grade_values = {student['id']: student['score'] if student['score'] is not None else ''
                            for student in students}
            if request.method == 'POST' and request.form.get('form_type') == 'grades':
                grade_values = {student['id']: request.form.get(f"grade_{student['id']}", '').strip()
                                for student in students}
                errors = {}
                scores = {}
                for student_id, value in grade_values.items():
                    if value == '':
                        scores[student_id] = None
                    elif not re.fullmatch(r'[0-9]{1,3}', value) or int(value) > 100:
                        errors[student_id] = 'Ingresá una nota entera de 0 a 100 o dejá el campo vacío.'
                    else:
                        scores[student_id] = int(value)
                if errors:
                    return render_template('session.html', session=session, students=students,
                                           grade_values=grade_values, grade_errors=errors,
                                           saved=False, grades_saved=False, read_only=read_only), 400
                for student_id, score in scores.items():
                    save_grade(connection, session_id, student_id, score)
                # El contexto confirma la transacción antes de devolver la respuesta.
                return redirect(url_for('session_detail', session_id=session_id, grades_saved=1))
            if request.method == 'POST':
                states = [(student['id'], request.form.get(f"status_{student['id']}", ''))
                          for student in students]
                if any(status not in ('', 'presente', 'ausente') for _, status in states):
                    abort(400, description='El estado de asistencia no es válido.')
                for student_id, status in states:
                    if status:
                        save_attendance(connection, session_id, student_id, status)
        if request.method == 'POST':
            return redirect(url_for('session_detail', session_id=session_id, saved=1))
        return render_template('session.html', session=session, students=students,
                               saved=request.args.get('saved') == '1',
                               grades_saved=request.args.get('grades_saved') == '1',
                               grade_values=grade_values, grade_errors={}, read_only=read_only)

    @app.get('/sesiones/<int:session_id>/pizarra')
    def board(session_id):
        with connect() as connection:
            session = connection.execute(
                '''SELECT s.*, c.name AS course_name FROM class_sessions s
                   JOIN courses c ON c.id = s.course_id WHERE s.id = ?''',
                (session_id,),
            ).fetchone()
        if session is None:
            abort(404)
        with connect() as connection:
            summary = connection.execute('SELECT summary FROM session_summaries WHERE session_id = ?', (session_id,)).fetchone()
        resource = request.args.get('resource')
        initial_resource = resource if resource in dict(BOARD_RESOURCES) else BOARD_RESOURCES[0][0]
        vox_message = 'Abrí el ciclo del agua' if initial_resource == 'ciclo-del-agua' and request.args.get('from_vox') == '1' else ''
        return render_template('board.html', session=session, resources=BOARD_RESOURCES,
                               summary=summary['summary'] if summary else '',
                               initial_resource=initial_resource, vox_message=vox_message)

    def require_session(db, session_id):
        session = db.execute('SELECT * FROM class_sessions WHERE id = ?', (session_id,)).fetchone()
        if session is None:
            abort(404)
        return session

    @app.route('/sesiones/<int:session_id>/resumen', methods=['GET', 'POST'])
    def session_summary(session_id):
        with connect() as db:
            require_session(db, session_id)
            if request.method == 'POST':
                summary = (request.get_json(silent=True) or {}).get('summary')
                if not isinstance(summary, str) or len(summary) > 20000:
                    return jsonify(error='El resumen debe ser texto de hasta 20000 caracteres.'), 400
                db.execute('''INSERT INTO session_summaries VALUES (?, ?)
                              ON CONFLICT (session_id) DO UPDATE SET summary = excluded.summary''', (session_id, summary))
                return jsonify(message='Resumen guardado.')
            row = db.execute('SELECT summary FROM session_summaries WHERE session_id = ?', (session_id,)).fetchone()
            return jsonify(summary=row['summary'] if row else '')

    def resolve_command(db, session_id, text):
        session = require_session(db, session_id)
        current = active_course(db)
        if current is None or current['id'] != session['course_id']:
            raise ValueError('Esta gestión es de consulta. No se pueden modificar sus registros desde la voz.')
        kind, student_id, value = parse_school_command(text)
        student = db.execute('SELECT * FROM students WHERE id = ? AND course_id = ?',
                             (student_id, session['course_id'])).fetchone()
        if student is None:
            raise ValueError('El estudiante no pertenece al curso de esta sesión.')
        return kind, student, value

    def signed_preview(session_id, text, kind, student, value):
        with connect() as db:
            context = db.execute('''SELECT s.class_date,c.name,c.school_year FROM class_sessions s
                                    JOIN courses c ON c.id = s.course_id WHERE s.id = ?''', (session_id,)).fetchone()
        return dict(token=command_signer.dumps({'session_id': session_id, 'text': text}),
                    session_id=session_id, student_id=student['id'],
                    name=f"{student['first_name']} {student['last_name']}", kind=kind, value=value,
                    class_date=context['class_date'],
                    context=f"{context['name']} · Gestión {context['school_year']} · Fecha {context['class_date']}")

    @app.post('/voz/vista-previa')
    @app.post('/cursos/<int:course_id>/voz/vista-previa')
    def home_school_preview(course_id=None):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('text'), str) or len(data['text']) > 500:
            return jsonify(error='El comando no es válido.'), 400
        try:
            kind, student_id, value = parse_school_intent(data['text'])
            day = valid_date(data.get('class_date', local_today()))
            with connect() as db:
                course = active_course(db)
                if course is None:
                    return jsonify(needs=['course'], kind=kind, configure_url=url_for('annual.configure'))
                if data.get('course_id') not in (None, '') and str(data['course_id']) != str(course['id']):
                    raise ValueError('La gestión activa cambió. Recargá el inicio para continuar.')
                if course_id is not None and course_id != course['id']:
                    raise ValueError('La gestión activa cambió. Recargá el inicio para continuar.')
                if data.get('session_id'):
                    legacy = db.execute('SELECT * FROM class_sessions WHERE id = ? AND course_id = ?', (data['session_id'], course['id'])).fetchone()
                    if legacy is None:
                        raise ValueError('El registro no pertenece al curso activo.')
                    if 'class_date' not in data:
                        day = legacy['class_date']
                if student_id is None and data.get('student_id') not in (None, ''):
                    if isinstance(data['student_id'], bool) or not str(data['student_id']).isdigit():
                        raise ValueError('Elegí un estudiante válido.')
                    student_id = int(data['student_id'])
                student = db.execute('SELECT * FROM students WHERE id = ? AND course_id = ?', (student_id, course['id'])).fetchone() if student_id is not None else None
                if student_id is not None and student is None:
                    raise ValueError('El estudiante no pertenece al curso anual activo.')
                if value is None and data.get('value') not in (None, ''):
                    value = data['value']
                    if kind == 'grade':
                        if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,3}', str(value)) or not 0 <= int(value) <= 100:
                            raise ValueError('La nota debe ser un entero de 0 a 100.')
                        value = int(value)
                    elif value not in ('presente', 'ausente'):
                        raise ValueError('Elegí Presente o Ausente.')
                needs = [key for key, missing in [('student', student_id is None), ('value', value is None)] if missing]
                if needs:
                    return jsonify(needs=needs, kind=kind, class_date=day, course_id=course['id'], student_id=student_id, value=value)
                canonical = f'registrar nota {value} al estudiante {student_id}' if kind == 'grade' else f'marcar {value} al estudiante {student_id}'
                token = command_signer.dumps({'annual': True, 'course_id': course['id'], 'class_date': day, 'text': canonical})
                context = f"{course['name']} · Gestión {course['school_year']} · Fecha {day}"
                if kind == 'grade':
                    context += ' · Calificación de la fecha'
                    old_context = db.execute('SELECT MIN(id) FROM class_sessions WHERE course_id = ? AND class_date = ?', (course['id'], day)).fetchone()[0]
                    if old_context is not None:
                        context += f' · Registro de notas {old_context}'
                        old_grade = db.execute('SELECT score FROM grades WHERE session_id = ? AND student_id = ?', (old_context, student_id)).fetchone()
                        if old_grade:
                            context += f" · Nota anterior: {old_grade['score']}"
                return jsonify(needs=[], preview=dict(token=token, course_id=course['id'], class_date=day,
                    name=f"{student['first_name']} {student['last_name']}", student_id=student_id,
                    kind=kind, value=value, context=context, source_text=data['text']))
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/voz/confirmar')
    def home_school_confirm():
        data = request.get_json(silent=True)
        token = data.get('token') if isinstance(data, dict) else None
        if not isinstance(token, str):
            return jsonify(error='Primero generá una vista previa.'), 400
        try:
            pending = command_signer.loads(token, max_age=300)
            if pending.get('annual') is not True:
                raise ValueError('La vista previa no corresponde al curso anual.')
            with connect() as db:
                current = active_course(db)
                if current is None or current['id'] != pending['course_id']:
                    raise ValueError('La gestión activa cambió. Volvé a revisar el comando antes de confirmar.')
                day = valid_date(pending['class_date'])
                session_id = ensure_day(db, current['id'], day)
                kind, student, value = resolve_command(db, session_id, pending['text'])
                if kind == 'attendance':
                    save_attendance(db, session_id, student['id'], value)
                else:
                    save_grade(db, session_id, student['id'], value)
            return jsonify(message=f'Cambio confirmado y guardado para {day}.', kind=kind,
                           student_id=student['id'], value=value, class_date=day)
        except BadSignature:
            return jsonify(error='La vista previa venció o no es válida. Revisá nuevamente el comando.'), 400
        except (ValueError, KeyError) as error:
            return jsonify(error=str(error)), 400

    @app.post('/cursos/<int:course_id>/voz/crear-sesion')
    def home_create_session(course_id):
        data = request.get_json(silent=True)
        try:
            class_date = date.fromisoformat(data.get('class_date', '') if isinstance(data, dict) else '').isoformat()
        except (TypeError, ValueError):
            return jsonify(error='Ingresá una fecha válida.'), 400
        with connect() as db:
            if not db.execute('SELECT 1 FROM courses WHERE id = ?', (course_id,)).fetchone():
                abort(404)
            current = active_course(db)
            if current is None or current['id'] != course_id:
                return jsonify(error='El curso no es la gestión activa.'), 400
            session_id = ensure_day(db, course_id, class_date)
        browser_session['active_class_session'] = session_id
        return jsonify(session_id=session_id, class_date=class_date)

    @app.post('/sesiones/<int:session_id>/voz/vista-previa')
    def school_preview(session_id):
        text = (request.get_json(silent=True) or {}).get('text')
        if not isinstance(text, str) or len(text) > 500:
            return jsonify(error='El comando no es válido.'), 400
        try:
            with connect() as db:
                kind, student, value = resolve_command(db, session_id, text)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(signed_preview(session_id, text, kind, student, value))

    @app.post('/sesiones/<int:session_id>/voz/confirmar')
    def school_confirm(session_id):
        token = (request.get_json(silent=True) or {}).get('token')
        if not isinstance(token, str):
            return jsonify(error='Primero generá una vista previa.'), 400
        try:
            pending = command_signer.loads(token, max_age=300)
            if pending['session_id'] != session_id:
                raise ValueError('La confirmación corresponde a otra sesión.')
            with connect() as db:
                kind, student, value = resolve_command(db, session_id, pending['text'])
                if kind == 'attendance':
                    save_attendance(db, session_id, student['id'], value)
                else:
                    save_grade(db, session_id, student['id'], value)
        except BadSignature:
            return jsonify(error='La vista previa venció o no es válida. Volvé a grabar el comando.'), 400
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(message='Cambio confirmado y guardado.', kind=kind, student_id=student['id'], value=value)

    configure_auth(app, connect)

    @app.before_request
    def archived_courses_are_read_only():
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return None
        args = request.view_args or {}
        with connect() as db:
            course_id = args.get('course_id')
            if 'session_id' in args:
                row = db.execute('SELECT course_id FROM class_sessions WHERE id = ?', (args['session_id'],)).fetchone()
                course_id = row['course_id'] if row else None
            if course_id is not None:
                current = active_course(db)
                if current is None or current['id'] != course_id:
                    if request.is_json:
                        return jsonify(error='Esta gestión es de consulta. Trabajá con el curso anual activo.'), 403
                    abort(403, description='Esta gestión es de consulta. Trabajá con el curso anual activo.')

    app.register_blueprint(create_annual_blueprint(connect))
    app.register_blueprint(create_trivia_blueprint(connect))
    app.register_blueprint(create_comments_blueprint(connect))
    app.register_blueprint(create_performance_blueprint(connect))
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
