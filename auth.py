"""Acceso de un docente local con contraseña almacenada como hash scrypt."""
from datetime import timedelta
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def persistent_secret(database):
    path = Path(database).parent / '.secret_key'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='ascii') as file:
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return path.read_text(encoding='ascii').strip()


def configure_auth(app, connect):
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    blueprint = Blueprint('auth', __name__)

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']

    def start_session(teacher):
        session.clear()
        session['teacher_id'] = teacher['id']
        session.permanent = True
        csrf_token()

    @app.context_processor
    def auth_context():
        return {'csrf_token': csrf_token, 'current_teacher': getattr(g, 'teacher', None)}

    @app.before_request
    def protect():
        g.teacher = None
        if request.endpoint == 'static':
            return None
        with connect() as db:
            teacher = db.execute('SELECT * FROM teachers WHERE id = 1').fetchone()
        if teacher and session.get('teacher_id') == teacher['id']:
            g.teacher = teacher
        public = request.endpoint in ('auth.login', 'auth.setup')
        if not public and g.teacher is None:
            if request.is_json or request.mimetype == 'audio/wav' or request.path.startswith('/api/'):
                return jsonify(error='Tu sesión no está activa. Iniciá sesión para continuar.'), 401
            return redirect(url_for('auth.login' if teacher else 'auth.setup'))
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            provided = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            expected = session.get('csrf_token', '')
            if not expected or not hmac.compare_digest(provided, expected):
                if request.is_json or request.mimetype == 'audio/wav':
                    return jsonify(error='La página venció. Recargala antes de volver a guardar.'), 400
                return render_template('auth.html', setup=not teacher,
                                       error='La página venció. Volvé a completar el formulario.'), 400

    @blueprint.route('/crear-cuenta', methods=['GET', 'POST'])
    def setup():
        with connect() as db:
            if db.execute('SELECT 1 FROM teachers').fetchone():
                return redirect(url_for('index' if g.teacher else 'auth.login'))
        error = ''
        if request.method == 'POST':
            username = request.form.get('username', '').strip().casefold()
            password = request.form.get('password', '')
            if not re.fullmatch(r'[\w.-]{3,40}', username):
                error = 'Usá un usuario de 3 a 40 caracteres: letras, números, punto, guion o guion bajo.'
            elif not 8 <= len(password) <= 128 or not password.strip():
                error = 'La contraseña debe tener entre 8 y 128 caracteres.'
            elif password != request.form.get('password_confirmation'):
                error = 'Las contraseñas no coinciden.'
            else:
                try:
                    with connect() as db:
                        db.execute('INSERT INTO teachers (id, username, password_hash) VALUES (1, ?, ?)',
                                   (username, generate_password_hash(password)))
                        teacher = db.execute('SELECT * FROM teachers WHERE id = 1').fetchone()
                    start_session(teacher)
                    return redirect(url_for('index'))
                except sqlite3.IntegrityError:
                    return redirect(url_for('auth.login'))
        return render_template('auth.html', setup=True, error=error), 400 if error else 200

    @blueprint.route('/iniciar-sesion', methods=['GET', 'POST'])
    def login():
        if g.teacher:
            return redirect(url_for('index'))
        with connect() as db:
            teacher = db.execute('SELECT * FROM teachers WHERE id = 1').fetchone()
        if teacher is None:
            return redirect(url_for('auth.setup'))
        error = ''
        code = 200
        if request.method == 'POST':
            if teacher['locked_until'] > time.time():
                error, code = 'Demasiados intentos. Esperá un minuto antes de volver a intentar.', 429
            else:
                password = request.form.get('password', '')
                valid_password = len(password) <= 128 and check_password_hash(teacher['password_hash'], password)
                if request.form.get('username', '').strip().casefold() == teacher['username'] and valid_password:
                    with connect() as db:
                        db.execute('UPDATE teachers SET failed_attempts = 0, locked_until = 0 WHERE id = 1')
                    start_session(teacher)
                    return redirect(url_for('index'))
                with connect() as db:
                    db.execute('''UPDATE teachers SET failed_attempts = failed_attempts + 1,
                                  locked_until = CASE WHEN failed_attempts + 1 >= 5 THEN ? ELSE 0 END
                                  WHERE id = 1''', (time.time() + 60,))
                error, code = 'Usuario o contraseña incorrectos.', 400
        return render_template('auth.html', setup=False, error=error), code

    @blueprint.post('/cerrar-sesion')
    def logout():
        session.clear()
        return redirect(url_for('auth.login'))

    @app.after_request
    def private_pages(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'microphone=(self), camera=()'
        return response

    app.register_blueprint(blueprint)
