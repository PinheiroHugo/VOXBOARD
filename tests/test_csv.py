from auth_helpers import authenticate_client
import csv
from contextlib import closing
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from openpyxl import load_workbook


class IndicatorTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = 0
        self.active = self.cell = False
        self.rows = []
        self.row = []
        self.value = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.tables += 1
            self.active = self.tables == 1
        if self.active and tag == 'tr':
            self.row = []
        if self.active and tag in ('th', 'td'):
            self.cell = True
            self.value = ''

    def handle_data(self, data):
        if self.cell:
            self.value += data

    def handle_endtag(self, tag):
        if self.active and tag in ('th', 'td'):
            self.row.append(self.value.strip())
            self.cell = False
        if self.active and tag == 'tr':
            self.rows.append(self.row)
        if tag == 'table':
            self.active = False


class CsvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'csv.sqlite3'
        self.client = authenticate_client(create_app({'TESTING': True, 'SEED_DEMO_DATA': True, 'DATABASE': self.database}).test_client())
        self.url = '/cursos/1/rendimiento.csv'

    def sql(self, query, args=()):
        with closing(sqlite3.connect(self.database)) as db, db:
            return db.execute(query, args).fetchall()

    def seed(self):
        for day in (1, 2, 3):
            self.client.post('/sesiones', data={'class_date': f'2026-11-0{day}'})
            self.client.post(f'/sesiones/{day}', data={'form_type': 'grades', 'grade_1': '0', 'grade_4': '0' if day == 1 else '100'})
        self.client.post('/sesiones/1', data={'status_1': 'presente', 'status_2': 'ausente', 'status_3': 'presente'})
        self.client.post('/sesiones/2', data={'status_1': 'ausente'})

    def download(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        stream = io.StringIO(response.data.decode('utf-8-sig'), newline='')
        self.assertEqual(stream.readline(), 'sep=;\r\n')
        rows = list(csv.reader(stream, delimiter=';'))
        return response, rows

    def test_download_bom_separator_headers_course_and_local_date(self):
        instant = datetime(2026, 11, 15, 23, 59, tzinfo=timezone(timedelta(hours=-4)))
        with patch('performance.datetime') as clock:
            clock.now.return_value = instant
            response, rows = self.download()
            self.assertEqual(clock.now.call_args.args[0].utcoffset(None), timedelta(hours=-4))
        self.assertTrue(response.data.startswith(b'\xef\xbb\xbf'))
        self.assertTrue(response.data.startswith(b'\xef\xbb\xbfsep=;\r\nEstudiante;Promedio;'))
        self.assertEqual(response.content_type, 'text/csv; charset=utf-8')
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('tercero-de-primaria-a_curso-1_2026-11-15.csv', response.headers['Content-Disposition'])
        self.assertEqual(rows[0], ['Estudiante', 'Promedio', 'Cantidad de notas', 'Presentes', 'Ausentes', 'Porcentaje de asistencia'])
        self.assertEqual(len(rows), 6)
        self.assertIn('Ana García', rows[1][0])
        self.assertIn(b';', response.data)
        self.assertIn(b'\r\n', response.data)
        self.assertTrue(all(len(row) == 6 for row in rows))

    def test_csv_matches_rendered_screen_zero_pending_and_rounding(self):
        self.seed()
        parser = IndicatorTable()
        html = self.client.get('/cursos/1/rendimiento').get_data(as_text=True)
        self.assertIn(self.url, html)
        parser.feed(html)
        _, exported = self.download()
        self.assertEqual(len(exported) - 1, len(parser.rows) - 1)
        for screen, record in zip(parser.rows[1:], exported[1:]):
            self.assertEqual(record[0], screen[0])
            expected = ['' if value == 'Sin registros' else value.removesuffix(' %').replace('.', ',') for value in screen[1:]]
            self.assertEqual(record[1:], expected)
        by_student = {record[0]: record[1:] for record in exported[1:]}
        self.assertEqual(by_student['Ana García'], ['0,00', '3', '1', '1', '50,00'])
        self.assertEqual(by_student['Mateo López'], ['', '0', '0', '1', '0,00'])
        self.assertEqual(by_student['Sofía Mamani'], ['', '0', '1', '0', '100,00'])
        self.assertEqual(by_student['Lucas Pérez'], ['66,67', '3', '', '', ''])
        self.assertEqual(by_student['Valentina Rojas'], ['', '0', '', '', ''])

    def test_course_isolation_no_writes_and_missing_course(self):
        self.seed()
        self.sql("INSERT INTO courses VALUES (2, 'Otro curso', 'Docente', 2026)")
        self.sql("INSERT INTO students VALUES (6, 2, 'Otra', 'Persona')")
        self.sql("INSERT INTO class_sessions VALUES (4, 2, '2026-11-04')")
        self.sql('INSERT INTO grades VALUES (4, 1, 100)')
        tables = ['courses', 'students', 'class_sessions', 'attendance', 'grades', 'session_summaries', 'session_trivias', 'report_comments']
        before = {table: self.sql(f'SELECT * FROM {table}') for table in tables}
        _, rows = self.download()
        self.assertEqual(len(rows) - 1, 5)
        self.assertNotIn('Otra Persona', [row[0] for row in rows])
        self.assertEqual(rows[1][1], '0,00')
        self.assertEqual({table: self.sql(f'SELECT * FROM {table}') for table in tables}, before)
        self.assertEqual(self.client.get('/cursos/999/rendimiento.csv').status_code, 404)

    def test_csv_escapes_names_and_empty_course_has_header_only(self):
        name = 'Ana; "María"\nLuz'
        self.sql('UPDATE students SET first_name = ? WHERE id = 1', (name,))
        _, rows = self.download()
        self.assertEqual(rows[1][0], name + ' García')
        self.assertEqual(len(rows), 6)
        self.sql("INSERT INTO courses VALUES (2, 'Sin alumnos', 'Docente', 2026)")
        response = self.client.get('/cursos/2/rendimiento.csv')
        self.assertEqual(response.status_code, 200)
        stream = io.StringIO(response.data.decode('utf-8-sig'))
        self.assertEqual(stream.readline().strip(), 'sep=;')
        records = list(csv.reader(stream, delimiter=';'))
        self.assertEqual(len(records), 1)

    def test_excel_unicode_column_widths_numbers_and_blank_cells(self):
        self.seed()
        response = self.client.get('/cursos/1/rendimiento.xlsx')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('.xlsx', response.headers['Content-Disposition'])
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        workbook = load_workbook(io.BytesIO(response.data))
        self.addCleanup(workbook.close)
        sheet = workbook.active
        self.assertEqual(sheet.max_row, 6)
        self.assertEqual(sheet.max_column, 6)
        self.assertEqual(sheet['A2'].value, 'Ana García')
        self.assertEqual(sheet['A3'].value, 'Mateo López')
        self.assertEqual(sheet['A4'].value, 'Sofía Mamani')
        self.assertEqual(sheet['A5'].value, 'Lucas Pérez')
        self.assertEqual(sheet['B2'].value, 0)
        self.assertEqual(sheet['B2'].data_type, 'n')
        self.assertEqual(sheet['B2'].number_format, '0.00')
        self.assertEqual(sheet['B5'].value, 66.67)
        self.assertEqual(sheet['F2'].value, 0.5)
        self.assertEqual(sheet['F3'].value, 0)
        self.assertEqual(sheet['F2'].number_format, '0.00%')
        self.assertIsNone(sheet['B6'].value)
        self.assertEqual(sheet['C6'].value, 0)
        self.assertIsNone(sheet['D6'].value)
        self.assertIsNone(sheet['F6'].value)
        self.assertGreaterEqual(sheet.column_dimensions['A'].width, 32)
        self.assertGreaterEqual(sheet.column_dimensions['F'].width, 28)
        self.assertTrue(sheet['A1'].font.bold)
        self.assertEqual(sheet.freeze_panes, 'B2')
        self.assertEqual(sheet.auto_filter.ref, 'A1:F6')
        self.assertEqual(self.client.get('/cursos/999/rendimiento.xlsx').status_code, 404)

    def test_excel_names_are_unicode_text_including_special_characters(self):
        name = '=Ana; "María" Ñúñez'
        self.sql('UPDATE students SET first_name = ? WHERE id = 1', (name,))
        response = self.client.get('/cursos/1/rendimiento.xlsx')
        workbook = load_workbook(io.BytesIO(response.data))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.active['A2'].value, name + ' García')
        self.assertEqual(workbook.active['A2'].data_type, 's')


if __name__ == '__main__':
    unittest.main()
