import io
from decimal import Decimal
from collections import defaultdict
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to compute total page count dynamically
    and add a sleek header stripe and running footer on every page.
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
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        # Top subtle indigo accent bar
        self.setFillColor(colors.HexColor('#4f46e5'))
        self.rect(0, letter[1] - 4, letter[0], 4, fill=1, stroke=0)

        # Footer
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#64748b'))
        footer_text = f"Smart Expense Tracker  •  Page {self._pageNumber} of {page_count}"
        self.drawRightString(letter[0] - 36, 20, footer_text)
        self.drawString(36, 20, "Confidential  •  Generated automatically")
        self.setStrokeColor(colors.HexColor('#e2e8f0'))
        self.setLineWidth(0.5)
        self.line(36, 32, letter[0] - 36, 32)
        self.restoreState()


def generate_expense_pdf(expenses_qs, title="Expense Report", filter_label="All Expenses", user=None):
    """
    Generates an executive-grade, modern PDF expense statement.
    Features:
      - Clean two-column header with total expenditure stat card
      - 4 KPI metric cards (Total Spent, Transactions, Avg/Item, Top Category)
      - Category breakdown table with spend amounts and percentage shares
      - Detailed transaction ledger with alternating rows & highlighted total
      - Professional typography & colors (using Rs. currency to prevent glyph errors)

    Returns:
      (pdf_bytes, filename)
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=28,
        bottomMargin=45
    )

    styles = getSampleStyleSheet()

    # Typography Styles
    doc_brand = ParagraphStyle('DocBrand', fontName='Helvetica-Bold', fontSize=14, leading=17, textColor=colors.HexColor('#4f46e5'))
    doc_title = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=colors.HexColor('#0f172a'))
    doc_meta = ParagraphStyle('DocMeta', fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor('#475569'))

    head_box_label = ParagraphStyle('HeadBoxLabel', fontName='Helvetica-Bold', fontSize=7.5, leading=9, textColor=colors.HexColor('#64748b'), alignment=2)
    head_box_amt = ParagraphStyle('HeadBoxAmt', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=colors.HexColor('#1e1b4b'), alignment=2)
    head_box_sub = ParagraphStyle('HeadBoxSub', fontName='Helvetica', fontSize=7.5, leading=9, textColor=colors.HexColor('#94a3b8'), alignment=2)

    section_hdr = ParagraphStyle('SectionHdr', fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#1e293b'))

    kpi_label = ParagraphStyle('KpiLabel', fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=colors.HexColor('#64748b'))
    kpi_val_indigo = ParagraphStyle('KpiValIndigo', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#4f46e5'))
    kpi_val_dark = ParagraphStyle('KpiValDark', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#0f172a'))
    kpi_val_green = ParagraphStyle('KpiValGreen', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#059669'))
    kpi_val_violet = ParagraphStyle('KpiValViolet', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.HexColor('#7c3aed'))

    tbl_header = ParagraphStyle('TblHdr', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white)
    tbl_header_right = ParagraphStyle('TblHdrR', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white, alignment=2)

    cell_text = ParagraphStyle('CellText', fontName='Helvetica', fontSize=8, leading=10.5, textColor=colors.HexColor('#334155'))
    cell_bold = ParagraphStyle('CellBold', fontName='Helvetica-Bold', fontSize=8, leading=10.5, textColor=colors.HexColor('#0f172a'))
    cell_right = ParagraphStyle('CellRight', fontName='Helvetica', fontSize=8, leading=10.5, textColor=colors.HexColor('#334155'), alignment=2)
    cell_right_bold = ParagraphStyle('CellRightBold', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.HexColor('#0f172a'), alignment=2)
    cell_center = ParagraphStyle('CellCenter', fontName='Helvetica', fontSize=8, leading=10.5, textColor=colors.HexColor('#64748b'), alignment=1)

    story = []

    # Safe extraction of expenses
    if hasattr(expenses_qs, 'select_related'):
        expenses = list(expenses_qs.select_related('category'))
    else:
        expenses = list(expenses_qs)

    total_amount = sum((e.amount for e in expenses), Decimal('0.00'))
    item_count = len(expenses)
    avg_amount = (total_amount / item_count) if item_count > 0 else Decimal('0.00')

    # Category Breakdown
    cat_map = defaultdict(lambda: {'count': 0, 'total': Decimal('0.00')})
    for e in expenses:
        cat_name = e.category.name if getattr(e, 'category', None) else 'Uncategorized'
        cat_map[cat_name]['count'] += 1
        cat_map[cat_name]['total'] += e.amount

    sorted_cats = sorted(cat_map.items(), key=lambda x: x[1]['total'], reverse=True)
    top_cat_name = sorted_cats[0][0] if sorted_cats else 'None'
    top_cat_amt = sorted_cats[0][1]['total'] if sorted_cats else Decimal('0.00')

    # 1. Header Block (Left metadata + Right Total Card)
    gen_time = timezone.localtime().strftime('%d %b %Y, %I:%M %p')
    user_display = user.username if user else "Account Owner"

    header_left = [
        Paragraph('SMART EXPENSE TRACKER', doc_brand),
        Spacer(1, 2),
        Paragraph(title, doc_title),
        Spacer(1, 4),
        Paragraph(f"Account: <b>{user_display}</b> &nbsp;•&nbsp; Scope: <b>{filter_label}</b>", doc_meta)
    ]

    header_right_card = Table([
        [Paragraph('TOTAL EXPENDITURE', head_box_label)],
        [Paragraph(f"Rs. {total_amount:,.2f}", head_box_amt)],
        [Paragraph(f"Generated: {gen_time}", head_box_sub)],
    ], colWidths=[200])
    header_right_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#c7d2fe')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))

    header_table = Table([[header_left, header_right_card]], colWidths=[330, 210])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width='100%', thickness=1.5, color=colors.HexColor('#e0e7ff'), spaceAfter=8))

    # 2. KPI Metric Cards (4 Tiles)
    count_label = f"{item_count} item" if item_count == 1 else f"{item_count} items"
    top_cat_label = f"{top_cat_name} (Rs. {top_cat_amt:,.0f})" if item_count > 0 else "None"

    kpi_data = [
        [
            [Paragraph('TOTAL EXPENDITURE', kpi_label), Spacer(1, 3), Paragraph(f"Rs. {total_amount:,.2f}", kpi_val_indigo)],
            [Paragraph('TRANSACTIONS', kpi_label), Spacer(1, 3), Paragraph(count_label, kpi_val_dark)],
            [Paragraph('AVG PER ITEM', kpi_label), Spacer(1, 3), Paragraph(f"Rs. {avg_amount:,.2f}", kpi_val_green)],
            [Paragraph('TOP CATEGORY', kpi_label), Spacer(1, 3), Paragraph(top_cat_label, kpi_val_violet)],
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[130, 110, 140, 160])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (0, 0), 0.75, colors.HexColor('#c7d2fe')),
        ('BOX', (1, 0), (1, 0), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (2, 0), (2, 0), 0.5, colors.HexColor('#e2e8f0')),
        ('BOX', (3, 0), (3, 0), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # 3. Category Breakdown Table
    if sorted_cats:
        story.append(Paragraph('SPENDING BY CATEGORY', section_hdr))
        story.append(Spacer(1, 4))

        cat_table_data = [[
            Paragraph('Category', tbl_header),
            Paragraph('Transactions', tbl_header),
            Paragraph('Total Spent', tbl_header_right),
            Paragraph('Share', tbl_header_right),
        ]]
        for cname, cdata in sorted_cats:
            pct = (cdata['total'] / total_amount * 100) if total_amount > 0 else Decimal('0.00')
            c_count_label = f"{cdata['count']} item" if cdata['count'] == 1 else f"{cdata['count']} items"
            cat_table_data.append([
                Paragraph(f"<b>{cname}</b>", cell_bold),
                Paragraph(c_count_label, cell_text),
                Paragraph(f"Rs. {cdata['total']:,.2f}", cell_right_bold),
                Paragraph(f"{pct:.1f}%", cell_right),
            ])

        cat_table = Table(cat_table_data, colWidths=[180, 110, 130, 120])
        cat_t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#312e81')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ]
        for r in range(1, len(cat_table_data)):
            bg = colors.HexColor('#f8fafc') if r % 2 == 0 else colors.white
            cat_t_style.append(('BACKGROUND', (0, r), (-1, r), bg))
        cat_table.setStyle(TableStyle(cat_t_style))
        story.append(cat_table)
        story.append(Spacer(1, 12))

    # 4. Detailed Transactions Table
    story.append(Paragraph('TRANSACTION DETAILS', section_hdr))
    story.append(Spacer(1, 4))

    tx_data = [[
        Paragraph('#', tbl_header),
        Paragraph('Date', tbl_header),
        Paragraph('Category', tbl_header),
        Paragraph('Description', tbl_header),
        Paragraph('Via', tbl_header),
        Paragraph('Amount (Rs.)', tbl_header_right),
    ]]

    if expenses:
        for idx, e in enumerate(expenses, 1):
            via = 'Bot' if getattr(e, 'created_via', None) == 'bot' else 'Web'
            c_name = e.category.name if getattr(e, 'category', None) else 'Uncategorized'
            tx_data.append([
                Paragraph(str(idx), cell_center),
                Paragraph(e.date.strftime('%d %b %Y'), cell_text),
                Paragraph(f"<b>{c_name}</b>", cell_bold),
                Paragraph(e.type, cell_text),
                Paragraph(via, cell_center),
                Paragraph(f"Rs. {e.amount:,.2f}", cell_right_bold),
            ])

        # Grand Total Row
        tx_data.append([
            Paragraph('', cell_text),
            Paragraph('', cell_text),
            Paragraph('', cell_text),
            Paragraph('<b>TOTAL EXPENDITURE</b>', cell_bold),
            Paragraph(count_label, cell_center),
            Paragraph(f"<b>Rs. {total_amount:,.2f}</b>", cell_right_bold),
        ])
    else:
        tx_data.append([
            Paragraph('-', cell_center),
            Paragraph('-', cell_text),
            Paragraph('-', cell_text),
            Paragraph('No expenses recorded for this period.', cell_text),
            Paragraph('-', cell_center),
            Paragraph('Rs. 0.00', cell_right),
        ])

    tx_table = Table(tx_data, colWidths=[28, 75, 95, 212, 45, 85], repeatRows=1)
    tx_t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e1b4b')),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#f1f5f9')),
    ]
    for r in range(1, len(tx_data) - (1 if expenses else 0)):
        bg = colors.HexColor('#f8fafc') if r % 2 == 0 else colors.white
        tx_t_style.append(('BACKGROUND', (0, r), (-1, r), bg))

    if expenses:
        total_idx = len(tx_data) - 1
        tx_t_style.append(('BACKGROUND', (0, total_idx), (-1, total_idx), colors.HexColor('#eef2ff')))
        tx_t_style.append(('LINEABOVE', (0, total_idx), (-1, total_idx), 1.5, colors.HexColor('#4f46e5')))

    tx_table.setStyle(TableStyle(tx_t_style))
    story.append(tx_table)

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    safe_slug = "".join(c for c in filter_label if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()
    filename = f"expense_report_{safe_slug or 'all'}_{timezone.localdate().strftime('%Y%m%d')}.pdf"
    return buffer.getvalue(), filename
