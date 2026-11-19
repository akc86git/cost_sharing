"""Экспорт отчёта о должниках в XLSX (кнопка «Выгрузить XLS»)
и PDF (кнопка «Выгрузить PDF»).

Для PDF регистрируется TTF-шрифт с поддержкой кириллицы (DejaVu Sans,
Liberation Sans — в порядке приоритета).
"""
import os
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

THIN = Side(style='thin', color='B6C2D4')

_FONTS_DIR = Path(__file__).resolve().parent / 'fonts'

_FONT_CANDIDATES = (
    ('DejaVu', _FONTS_DIR / 'DejaVuSans.ttf', _FONTS_DIR / 'DejaVuSans-Bold.ttf'),
    ('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('Arial', r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf'),
    ('LiberationSans',
     '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
     '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
)


def _register_pdf_font():
    """Регистрирует TTF-шрифт с кириллицей и возвращает (обычный, полужирный)."""
    for name, regular, bold in _FONT_CANDIDATES:
        if os.path.exists(regular):
            pdfmetrics.registerFont(TTFont(name, regular))
            if os.path.exists(bold):
                bold_name = f'{name}-Bold'
                pdfmetrics.registerFont(TTFont(bold_name, bold))
                return name, bold_name
            return name, name
    return 'Helvetica', 'Helvetica-Bold'


def build_xlsx(report) -> bytes:
    """Формирует XLSX-файл отчёта и возвращает его содержимое."""
    event = report['event']
    n = report['size']

    wb = Workbook()
    ws = wb.active
    ws.title = 'Долги'

    ws['A1'] = f'Отчёт о должниках — событие «{event.description}» ({event.date:%d.%m.%Y})'
    ws['A1'].font = Font(bold=True, size=13)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n + 2)

    ws['A2'] = ('На пересечении строки и столбца — сколько участник из строки должен '
                'участнику из столбца; минус — долг в обратную сторону.')
    ws['A2'].font = Font(italic=True, size=9, color='666666')
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n + 2)

    header_row = 3
    ws.cell(row=header_row, column=1, value='Участник')
    for col, person in enumerate(report['participants'], start=2):
        ws.cell(row=header_row, column=col,
                value=f'{person["nickname"]} ({person["full_name"]})')
    ws.cell(row=header_row, column=n + 2, value='Итого')

    for offset, row_data in enumerate(report['rows']):
        row_idx = header_row + 1 + offset
        ws.cell(row=row_idx, column=1,
                value=f'{row_data["person"]["full_name"]} ({row_data["person"]["nickname"]})')
        for col_idx, value in enumerate([*row_data['values'], row_data['total']], start=2):
            cell = ws.cell(row=row_idx, column=col_idx, value=round(float(value), 2))
            cell.number_format = '0.00'

    for row in ws.iter_rows(min_row=header_row, max_row=header_row + n,
                            min_col=1, max_col=n + 2):
        for cell in row:
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            if cell.row == header_row:
                cell.font = Font(bold=True)
                cell.fill = PatternFill('solid', fgColor='E8EDFB')
                cell.alignment = Alignment(horizontal='center', vertical='center',
                                           wrap_text=True)
            elif cell.column == 1:
                cell.alignment = Alignment(horizontal='left', vertical='center',
                                           wrap_text=True)
            else:
                cell.alignment = Alignment(horizontal='right', vertical='center')

    ws.column_dimensions['A'].width = 34
    for col in range(2, n + 3):
        ws.column_dimensions[get_column_letter(col)].width = 20
    ws.freeze_panes = 'B4'

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def build_pdf(report) -> bytes:
    """Формирует PDF-файл отчёта и возвращает его содержимое."""
    event = report['event']
    n = report['size']
    regular, bold = _register_pdf_font()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title='Отчёт о должниках', author='Разделение затрат',
    )

    title_style = ParagraphStyle('title', fontName=bold, fontSize=15, leading=20,
                                 spaceAfter=4)
    sub_style = ParagraphStyle('sub', fontName=regular, fontSize=10, leading=14,
                               textColor=colors.HexColor('#444444'))
    cell_style = ParagraphStyle('cell', fontName=regular, fontSize=8, leading=10)
    cell_bold = ParagraphStyle('cellb', fontName=bold, fontSize=8, leading=10)
    legend_style = ParagraphStyle('legend', fontName=regular, fontSize=8.5, leading=12,
                                  textColor=colors.HexColor('#555555'))

    story = [
        Paragraph(f'Отчёт о должниках — событие «{event.description}»', title_style),
        Paragraph(f'Дата события: {event.date:%d.%m.%Y}. Участников: {n}.', sub_style),
        Spacer(1, 8),
    ]

    if n == 0:
        story.append(Paragraph('В событии пока нет покупок и участников.', cell_style))
        doc.build(story)
        return buf.getvalue()

    def head(txt):
        return Paragraph(txt, cell_bold)

    def name(txt):
        return Paragraph(txt, cell_style)

    data = [[head('Участник')]
            + [head(f'{p["nickname"]}<br/>{p["full_name"]}') for p in report['participants']]
            + [head('Итого')]]
    for row_data in report['rows']:
        row = [name(f'{row_data["person"]["full_name"]}<br/>({row_data["person"]["nickname"]})')]
        row += [f'{value:.2f}' for value in row_data['values']]
        row.append(f'{row_data["total"]:.2f}')
        data.append(row)

    usable = A4[0] - 30 * mm
    name_col = min(55 * mm, usable * 0.35)
    others = (usable - name_col) / (n + 1)

    table = Table(data, colWidths=[name_col] + [others] * (n + 1), repeatRows=1)
    style = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#9DB2D0')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8EDFB')),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#F4F6FB')),
        ('FONTNAME', (1, 1), (-1, -1), regular),
        ('FONTSIZE', (1, 1), (-1, -1), 8),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    for d in range(n):  # нули на главной диагонали — серым
        style.append(('TEXTCOLOR', (d + 1, d + 1), (d + 1, d + 1),
                      colors.HexColor('#999999')))
    table.setStyle(TableStyle(style))

    story += [
        table,
        Spacer(1, 10),
        Paragraph('На пересечении строки и столбца — сколько участник из строки должен '
                  'участнику из столбца (взаимные долги пары зачтены). На главной диагонали '
                  'всегда нули. Значение со знаком «минус» означает, что долг направлен в '
                  'обратную сторону: участник из столбца должен участнику из строки.', legend_style),
        Spacer(1, 4),
        Paragraph('Выше главной диагонали — долг участника из строки участнику из столбца; '
                  'ниже диагонали — те же значения зеркально, поэтому отчёт можно читать '
                  'по верхнему треугольнику матрицы.', legend_style),
    ]
    doc.build(story)
    return buf.getvalue()
