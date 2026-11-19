"""Comentarios editables basados en registros del curso, sin inferir conductas."""
import json
import re

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from ollama_client import OllamaError, generate_json

COMMENT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'frases': {'type': 'array', 'minItems': 2, 'maxItems': 3,
                              'items': {'type': 'string', 'minLength': 1, 'maxLength': 1000,
                                        'description': 'Una sola oración sobre este estudiante, sin puntos internos.'}}},
    'required': ['frases'],
}


def student_stats(db, course_id, student_id):
    sessions = db.execute('SELECT COUNT(*) FROM class_sessions WHERE course_id = ?', (course_id,)).fetchone()[0]
    grades = db.execute('''SELECT COUNT(*), AVG(g.score) FROM grades g
                           JOIN class_sessions s ON s.id = g.session_id
                           WHERE s.course_id = ? AND g.student_id = ?''', (course_id, student_id)).fetchone()
    attendance = db.execute('''SELECT a.status, COUNT(*) FROM attendance_by_date a
                               WHERE a.course_id = ? AND a.student_id = ? GROUP BY a.status''',
                            (course_id, student_id)).fetchall()
    dates = db.execute('SELECT COUNT(DISTINCT class_date) FROM class_sessions WHERE course_id = ?', (course_id,)).fetchone()[0]
    counts = {row[0]: row[1] for row in attendance}
    present, absent = counts.get('presente', 0), counts.get('ausente', 0)
    return {'sessions': sessions, 'grade_count': grades[0],
            'average': round(grades[1], 2) if grades[1] is not None else None,
            'present': present, 'absent': absent,
            'pending_grades': sessions - grades[0], 'pending_attendance': dates - present - absent}


def validate_comment(data):
    if not isinstance(data, dict) or set(data) != {'frases'} or not isinstance(data['frases'], list) or len(data['frases']) not in (2, 3):
        raise OllamaError('Ollama devolvió un comentario inválido: debe contener dos o tres frases. Se conserva el texto anterior.')
    sentences = []
    for sentence in data['frases']:
        if not isinstance(sentence, str) or not 1 <= len(sentence.strip()) <= 1000:
            raise OllamaError('Ollama devolvió un comentario vacío o demasiado largo. Se conserva el texto anterior.')
        sentence = ' '.join(sentence.split())
        if re.search(r'[_{}]|\bnull\b', sentence, flags=re.IGNORECASE):
            raise OllamaError('Ollama devolvió etiquetas de datos en vez de un comentario. Se conserva el texto anterior; volvé a generar.')
        parts = [part for part in re.split(r'[.!?]+(?:\s+|$)', sentence) if part.strip()]
        if len(parts) != 1:
            raise OllamaError('Ollama devolvió un comentario con un formato de frases inválido. Se conserva el texto anterior.')
        sentences.append(sentence if sentence[-1] in '.!?' else sentence + '.')
    return ' '.join(sentences)


def generate_comment(stats, config):
    average = f"{stats['average']:.2f} sobre 100" if stats['average'] is not None else 'pendiente: no hay notas registradas'
    facts = (f"Sesiones del curso: {stats['sessions']}.\n"
             f"Promedio de las notas registradas: {average}.\n"
             f"Cantidad de notas registradas: {stats['grade_count']}.\n"
             f"Notas pendientes: {stats['pending_grades']}.\n"
             f"Sesiones en las que estuvo presente: {stats['present']}.\n"
             f"Sesiones en las que estuvo ausente: {stats['absent']}.\n"
             f"Asistencias pendientes: {stats['pending_attendance']}.")
    data = generate_json(
        config, schema=COMMENT_SCHEMA, num_predict=700,
        system=('Escribí un comentario de boletín en español de DOS oraciones breves y neutrales '
                'sobre UN SOLO estudiante, basándote SOLO en los datos numéricos provistos. '
                'Devolvé frases con dos elementos; CADA elemento contiene UNA sola oración, no un párrafo. '
                'Redactá en español natural para el boletín; no copies etiquetas de datos. '
                'Primera oración: promedio, cantidad de notas registradas y notas pendientes. '
                'Segunda oración: sesiones presente, sesiones ausente y asistencias pendientes. '
                'Son registros de un estudiante por sesión, NO cantidades de alumnos del curso. '
                'Describí el promedio y la cantidad de notas si existen; describí las cantidades '
                'de presentes y ausentes si hay asistencia registrada. Incluí los datos pendientes '
                'como pendientes, nunca como cero, ausencia ni nota baja. Si el promedio es null, '
                'no hay promedio calculable. Un promedio de cero sí es un dato válido. '
                'No atribuyas conductas, actitudes, esfuerzo, capacidades ni responsabilidad. '
                'No expliques ni justifiques ausencias. No inventes avances, mejoras, retrocesos '
                'ni comparaciones temporales. No agregues recomendaciones ni causas. '
                'No inventes información faltante. Cada elemento de frases debe ser una sola '
                'oración, sin títulos, abreviaturas ni listas. Devolvé solo el JSON solicitado.'),
        prompt='Datos de este estudiante en todas las sesiones del curso:\n' + facts
               + '\nEsquema JSON:\n' + json.dumps(COMMENT_SCHEMA, ensure_ascii=False),
    )
    return validate_comment(data)


def create_comments_blueprint(connect):
    blueprint = Blueprint('comments', __name__)

    @blueprint.route('/cursos/<int:course_id>/comentarios', methods=['GET', 'POST'])
    def editor(course_id):
        with connect() as db:
            course = db.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
            if course is None:
                abort(404)
            students = db.execute('SELECT * FROM students WHERE course_id = ? ORDER BY last_name, first_name', (course_id,)).fetchall()
            raw_id = request.args.get('student_id')
            student = next((student for student in students if str(student['id']) == raw_id), None)
            if raw_id is not None and student is None:
                abort(404)
            stats = student_stats(db, course_id, student['id']) if student else None
            saved = db.execute('SELECT comment FROM report_comments WHERE course_id = ? AND student_id = ?',
                               (course_id, student['id'])).fetchone() if student else None
        draft = saved['comment'] if saved else ''
        error, generated, code = '', False, 200
        has_data = stats is not None and (stats['grade_count'] > 0 or stats['present'] + stats['absent'] > 0)
        if request.method == 'POST':
            if student is None:
                abort(400)
            draft = request.form.get('comment', draft)
            try:
                if len(draft) > 4000:
                    raise OllamaError('El comentario debe tener hasta 4000 caracteres. No se guardó ningún cambio.')
                action = request.form.get('action')
                if action == 'generate':
                    if not has_data:
                        raise OllamaError('Todavía no hay notas ni asistencia registradas. Completá datos antes de generar un comentario.')
                    draft = generate_comment(stats, current_app.config)
                    generated = True
                elif action == 'save':
                    with connect() as db:
                        db.execute('''INSERT INTO report_comments (course_id, student_id, comment) VALUES (?, ?, ?)
                                      ON CONFLICT (course_id, student_id) DO UPDATE SET comment = excluded.comment''',
                                   (course_id, student['id'], draft))
                    return redirect(url_for('comments.editor', course_id=course_id, student_id=student['id'], saved=1))
                else:
                    raise OllamaError('Elegí Generar comentario o Guardar.')
            except OllamaError as exc:
                error, code = str(exc), 400
        return render_template('report_comments.html', course=course, students=students, student=student,
                               stats=stats, has_data=has_data, draft=draft, error=error, generated=generated,
                               saved=request.args.get('saved') == '1'), code

    return blueprint
