"""Guardado compartido y formatos fijos de comandos escolares."""
import re
import unicodedata


def save_attendance(db, session_id, student_id, status):
    context = db.execute('SELECT course_id,class_date FROM class_sessions WHERE id = ?', (session_id,)).fetchone()
    if context is None:
        raise ValueError('No existe el registro de la fecha.')
    # Corregir el registro efectivo de ese día, incluso si venía de otra sesión
    # histórica de la misma fecha. No se crean nuevas filas para una corrección.
    previous = db.execute('''SELECT session_id FROM attendance_by_date
                             WHERE course_id = ? AND class_date = ? AND student_id = ?''',
                          (context[0], context[1], student_id)).fetchone()
    if previous:
        session_id = previous[0]
    db.execute('''INSERT INTO attendance VALUES (?, ?, ?)
                  ON CONFLICT (session_id, student_id) DO UPDATE SET status = excluded.status''',
               (session_id, student_id, status))


def save_grade(db, session_id, student_id, score):
    if score is None:
        db.execute('DELETE FROM grades WHERE session_id = ? AND student_id = ?', (session_id, student_id))
    else:
        db.execute('''INSERT INTO grades VALUES (?, ?, ?)
                      ON CONFLICT (session_id, student_id) DO UPDATE SET score = excluded.score''',
                   (session_id, student_id, score))


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[¿?¡!.,;:]', ' ', text).split())


UNITS = ['cero', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve',
         'diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciseis', 'diecisiete', 'dieciocho', 'diecinueve']
NUMBERS = {word: value for value, word in enumerate(UNITS)}
NUMBERS.update({'veinte': 20, 'cien': 100})
NUMBERS.update({'veinti' + UNITS[i]: 20 + i for i in range(1, 10)})
for tens, word in enumerate(['treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa'], 3):
    NUMBERS[word] = tens * 10
    NUMBERS.update({word + ' y ' + UNITS[i]: tens * 10 + i for i in range(1, 10)})


def number(text):
    if re.fullmatch(r'[0-9]{1,9}', text):
        return int(text)
    if text in NUMBERS:
        return NUMBERS[text]
    raise ValueError('Usá un número entero en palabras o en dígitos.')


def parse_school_command(text):
    text = normalize(text)
    attendance = re.fullmatch(r'marcar (presente|ausente) al estudiante (.+)', text)
    grade = re.fullmatch(r'registrar nota (.+) al estudiante (.+)', text)
    if attendance:
        return 'attendance', number(attendance[2]), attendance[1]
    if grade:
        score = number(grade[1])
        if not 0 <= score <= 100:
            raise ValueError('La nota debe ser un entero de 0 a 100.')
        return 'grade', number(grade[2]), score
    raise ValueError('Probá «marcar ausente al estudiante uno» o «registrar nota ochenta y cinco al estudiante uno».')


def parse_school_intent(text):
    """Permite completar en pantalla los datos omitidos, sin adivinarlos."""
    text = normalize(text)
    attendance = re.fullmatch(r'marcar(?: (presente|ausente))?(?: al estudiante(?: (.*))?)?', text)
    if attendance:
        return 'attendance', number(attendance[2]) if attendance[2] else None, attendance[1]
    if text == 'registrar nota' or text.startswith('registrar nota '):
        body = text[len('registrar nota'):].strip()
        parts = re.fullmatch(r'(?:(.*?) )?al estudiante(?: (.*))?', body)
        score_text, student_text = (parts[1] or '', parts[2] or '') if parts else (body, '')
        score = number(score_text) if score_text else None
        if score is not None and not 0 <= score <= 100:
            raise ValueError('La nota debe ser un entero de 0 a 100.')
        return 'grade', number(student_text) if student_text else None, score
    raise ValueError('Probá «marcar ausente al estudiante uno» o «registrar nota ochenta y cinco al estudiante uno».')
