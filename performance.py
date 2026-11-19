"""Indicadores del curso y cuadro de honor con posiciones compartidas."""
from decimal import Decimal
import csv
from datetime import datetime, timedelta, timezone
import io
import re
import unicodedata

from flask import Blueprint, Response, abort, render_template
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from report_comments import student_stats

EXPORT_HEADERS = ['Estudiante', 'Promedio', 'Cantidad de notas', 'Presentes', 'Ausentes', 'Porcentaje de asistencia']


def export_filename(course, extension):
    slug = unicodedata.normalize('NFKD', course['name']).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', slug).strip('-').lower() or 'curso'
    day = datetime.now(timezone(timedelta(hours=-4))).date().isoformat()
    return f"rendimiento_{slug[:80]}_curso-{course['id']}_{day}.{extension}"


def honor_roll(rows):
    # Ordenar con el mismo valor de dos decimales que verá el docente.
    eligible = [row for row in rows if row['grade_count'] > 0]
    ordered = sorted(eligible, key=lambda row: (
        -Decimal(f"{row['average']:.2f}"), row['last_name'].casefold(),
        row['first_name'].casefold(), row['id'],
    ))
    result, position, previous = [], 0, None
    for row in ordered:
        average = Decimal(f"{row['average']:.2f}")
        if average != previous:
            position += 1
            previous = average
        if position > 3:
            break
        result.append({**row, 'position': position})
    return result


def indicator_cells(row):
    """Valores visibles compartidos: None significa «Sin registros»."""
    has_attendance = row['attendance_percent'] is not None
    return {
        'average': f"{row['average']:.2f}" if row['average'] is not None else None,
        'grade_count': str(row['grade_count']),
        'present': str(row['present']) if has_attendance else None,
        'absent': str(row['absent']) if has_attendance else None,
        'attendance_percent': f"{row['attendance_percent']:.2f}" if has_attendance else None,
    }


def create_performance_blueprint(connect):
    blueprint = Blueprint('performance', __name__)

    def load_course(course_id):
        with connect() as db:
            course = db.execute('SELECT * FROM courses WHERE id = ?', (course_id,)).fetchone()
            if course is None:
                abort(404)
            students = db.execute('SELECT * FROM students WHERE course_id = ? ORDER BY last_name, first_name',
                                  (course_id,)).fetchall()
            rows = []
            for student in students:
                stats = student_stats(db, course_id, student['id'])
                recorded = stats['present'] + stats['absent']
                rows.append({**dict(student), **stats,
                             'attendance_percent': 100 * stats['present'] / recorded if recorded else None})
                rows[-1]['indicators'] = indicator_cells(rows[-1])
            sessions = db.execute('SELECT COUNT(*) FROM class_sessions WHERE course_id = ?', (course_id,)).fetchone()[0]
        return course, rows, sessions

    @blueprint.get('/cursos/<int:course_id>/rendimiento')
    def overview(course_id):
        course, rows, sessions = load_course(course_id)
        return render_template('performance.html', course=course, rows=rows, sessions=sessions,
                               honor=honor_roll(rows))

    @blueprint.get('/cursos/<int:course_id>/rendimiento.csv')
    def download_csv(course_id):
        course, rows, _ = load_course(course_id)
        output = io.StringIO(newline='')
        # Excel reconoce esta directiva aunque Windows use otro separador regional.
        output.write('sep=;\r\n')
        writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
        writer.writerow(EXPORT_HEADERS)
        for row in rows:
            cells = row['indicators']
            writer.writerow([
                f"{row['first_name']} {row['last_name']}",
                cells['average'].replace('.', ',') if cells['average'] is not None else '',
                cells['grade_count'], cells['present'] if cells['present'] is not None else '',
                cells['absent'] if cells['absent'] is not None else '',
                cells['attendance_percent'].replace('.', ',') if cells['attendance_percent'] is not None else '',
            ])
        response = Response(output.getvalue().encode('utf-8-sig'), content_type='text/csv; charset=utf-8')
        response.headers.set('Content-Disposition', 'attachment', filename=export_filename(course, 'csv'))
        return response

    @blueprint.get('/cursos/<int:course_id>/rendimiento.xlsx')
    def download_excel(course_id):
        course, rows, _ = load_course(course_id)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Rendimiento del curso'
        sheet.append(EXPORT_HEADERS)
        for row in rows:
            cells = row['indicators']
            sheet.append([
                f"{row['first_name']} {row['last_name']}",
                float(cells['average']) if cells['average'] is not None else None,
                int(cells['grade_count']),
                int(cells['present']) if cells['present'] is not None else None,
                int(cells['absent']) if cells['absent'] is not None else None,
                float(cells['attendance_percent']) / 100 if cells['attendance_percent'] is not None else None,
            ])
            # Los nombres se guardan como texto Unicode, incluso si empiezan con =.
            sheet.cell(sheet.max_row, 1).data_type = 's'
            sheet.cell(sheet.max_row, 2).number_format = '0.00'
            sheet.cell(sheet.max_row, 6).number_format = '0.00%'
            for cell in sheet[sheet.max_row]:
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            sheet.row_dimensions[sheet.max_row].height = 32
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='173F50')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
        sheet.row_dimensions[1].height = 34
        for index, minimum in enumerate((32, 16, 22, 16, 16, 28), 1):
            longest = max((len(str(cell.value or '')) for cell in sheet[get_column_letter(index)]), default=0)
            sheet.column_dimensions[get_column_letter(index)].width = min(55, max(minimum, longest + 3))
        sheet.freeze_panes = 'B2'
        sheet.auto_filter.ref = sheet.dimensions
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        response = Response(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response.headers.set('Content-Disposition', 'attachment', filename=export_filename(course, 'xlsx'))
        return response

    return blueprint
