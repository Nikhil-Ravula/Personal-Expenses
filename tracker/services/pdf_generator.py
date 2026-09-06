import io
from decimal import Decimal
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to compute total page count dynamically.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        footer_text = f"Smart Expense Tracker  •  Page {self._pageNumber} of {page_count}"
        self.drawRightString(letter[0] - 36, 25, footer_text)
        self.drawString(36, 25, "Confidential & Generated automatically")
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(36, 36, letter[0] - 36, 36)
        self.restoreState()


def generate_expense_pdf(expenses_qs, title="Expense Report", filter_label="All Expenses", user=None):
    """
    Generates a professional PDF report from an Expense queryset.
    Returns:
      (pdf_bytes, filename)
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=45
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor("#4f46e5")  # Indigo
    dark_text = colors.HexColor("#0f172a")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12
    )
    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=dark_text
    )
    cell_style_bold = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=dark_text
    )
    header_cell_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )

    story = []

    # 1. Header Section
    story.append(Paragraph("Smart Expense Tracker", title_style))
    gen_time = timezone.now().strftime('%d %b %Y, %I:%M %p')
    user_str = f"User: {user.username}  •  " if user else ""
    story.append(Paragraph(f"{user_str}Scope: <b>{filter_label}</b>  •  Generated: {gen_time}", subtitle_style))
    story.append(Spacer(1, 8))

    # 2. Key Metrics Summary
    expenses = list(expenses_qs.select_related('category'))
    total_amount = sum((e.amount for e in expenses), Decimal('0.00'))
    item_count = len(expenses)
    avg_amount = (total_amount / item_count) if item_count > 0 else Decimal('0.00')

    summary_data = [
        [
            Paragraph(f"<b>Total Expenses</b><br/><font size=14 color='#4f46e5'><b>₹{total_amount:,.2f}</b></font>", cell_style),
            Paragraph(f"<b>Total Items</b><br/><font size=14 color='#0f172a'><b>{item_count}</b></font>", cell_style),
            Paragraph(f"<b>Average per Item</b><br/><font size=14 color='#059669'><b>₹{avg_amount:,.2f}</b></font>", cell_style),
            Paragraph(f"<b>Filter Scope</b><br/><font size=11 color='#334155'><b>{filter_label}</b></font>", cell_style),
        ]
    ]
    summary_table = Table(summary_data, colWidths=[135, 110, 140, 155])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # 3. Expenses Detailed Table
    table_data = [
        [
            Paragraph("#", header_cell_style),
            Paragraph("Date", header_cell_style),
            Paragraph("Category", header_cell_style),
            Paragraph("Description / Type", header_cell_style),
            Paragraph("Via", header_cell_style),
            Paragraph("Amount (₹)", header_cell_style),
        ]
    ]

    for idx, exp in enumerate(expenses, start=1):
        via_badge = "Bot" if exp.created_via == 'bot' else "Web"
        table_data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(exp.date.strftime('%d %b %Y'), cell_style),
            Paragraph(exp.category.name, cell_style),
            Paragraph(exp.type, cell_style),
            Paragraph(via_badge, cell_style),
            Paragraph(f"₹{exp.amount:,.2f}", cell_style_bold),
        ])

    # Add Grand Total row if list is not empty
    if expenses:
        table_data.append([
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("<b>GRAND TOTAL</b>", cell_style_bold),
            Paragraph("", cell_style),
            Paragraph(f"<b>₹{total_amount:,.2f}</b>", cell_style_bold),
        ])
    else:
        table_data.append([
            Paragraph("-", cell_style),
            Paragraph("-", cell_style),
            Paragraph("No expenses found for the specified filter.", cell_style),
            Paragraph("", cell_style),
            Paragraph("", cell_style),
            Paragraph("₹0.00", cell_style),
        ])

    # Col widths sum to 540 (which fits letter width 612 - 72pt margins)
    col_widths = [30, 80, 105, 195, 45, 85]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)

    t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#312e81")),  # Deep indigo header
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
    ]

    # Alternating row colors
    for row in range(1, len(table_data) - (1 if expenses else 0)):
        if row % 2 == 0:
            t_style.append(('BACKGROUND', (0, row), (-1, row), colors.HexColor("#f8fafc")))
        else:
            t_style.append(('BACKGROUND', (0, row), (-1, row), colors.white))

    # Highlight total row
    if expenses:
        total_row_idx = len(table_data) - 1
        t_style.append(('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), colors.HexColor("#e0e7ff")))
        t_style.append(('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 1.5, colors.HexColor("#4338ca")))

    table.setStyle(TableStyle(t_style))
    story.append(table)

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    safe_slug = "".join(c for c in filter_label if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
    filename = f"expense_report_{safe_slug or 'all'}_{timezone.now().strftime('%Y%m%d_%H%M')}.pdf"
    return buffer.getvalue(), filename
