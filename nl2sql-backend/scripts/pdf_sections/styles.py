"""ReportLab PDF styling definitions, NumberedCanvas, and component builder helpers.
Enforces white background, dark high-contrast typography, and professional software engineering layout.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
    PageBreak,
    Preformatted,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

# Document Geometry
PAGE_WIDTH, PAGE_HEIGHT = letter  # 612 x 792 pt
MARGIN = 48  # 48 pt margins (printable = 516 pt)
PRINTABLE_WIDTH = 512  # Safe printable width to prevent 1-pt layout overflow

# Color Palette (Crisp High-Contrast Professional)
C_PRIMARY = colors.HexColor("#0F172A")     # Slate 900 (Headings, primary text)
C_BODY = colors.HexColor("#1E293B")        # Slate 800 (Body text)
C_MUTED = colors.HexColor("#475569")       # Slate 600 (Captions, subtitles)
C_TEAL = colors.HexColor("#0F766E")        # Teal 700 (Accent headers, brand)
C_TEAL_LIGHT = colors.HexColor("#F0FDFA")  # Teal 50 (Callout background)
C_BLUE = colors.HexColor("#1D4ED8")        # Blue 700 (Links, queries)
C_BORDER = colors.HexColor("#CBD5E1")      # Slate 300 (Dividers, borders)
C_BORDER_LIGHT = colors.HexColor("#E2E8F0")# Slate 200 (Light rules)
C_BG_CARD = colors.HexColor("#F8FAFC")     # Slate 50 (Card/table alternate rows)
C_BG_AMBER = colors.HexColor("#FFFBEB")    # Amber 50 (Warning boxes)
C_BORDER_AMBER = colors.HexColor("#F59E0B")# Amber 500
C_BG_GREEN = colors.HexColor("#F0FDF4")    # Green 50 (Success boxes)
C_BORDER_GREEN = colors.HexColor("#16A34A")# Green 600


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic total page count, running headers, and running footers."""

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
        page_w, page_h = letter

        # Running header on pages 2+
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(C_TEAL)
            self.drawString(MARGIN, page_h - 30, "NL2SQL — TECHNICAL PROJECT ANALYSIS & SYSTEM JURY DEFENSE")
            self.setFont("Helvetica", 8)
            self.setFillColor(C_MUTED)
            self.drawRightString(page_w - MARGIN, page_h - 30, "SENIOR TECHNICAL REVIEW SPECIFICATION")

            self.setStrokeColor(C_BORDER)
            self.setLineWidth(0.75)
            self.line(MARGIN, page_h - 34, page_w - MARGIN, page_h - 34)

        # Running footer on all pages
        self.setStrokeColor(C_BORDER_LIGHT)
        self.setLineWidth(0.75)
        self.line(MARGIN, 38, page_w - MARGIN, 38)

        self.setFont("Helvetica", 8)
        self.setFillColor(C_MUTED)
        self.drawString(MARGIN, 26, "Production Architecture Audit | Antigravity AI & Software Review")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(page_w - MARGIN, 26, page_str)

        self.restoreState()


# Typography Stylesheet
base_styles = getSampleStyleSheet()

STYLES = {
    "DocTitle": ParagraphStyle(
        "DocTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=C_PRIMARY,
        alignment=TA_LEFT,
        spaceAfter=6,
    ),
    "DocSubtitle": ParagraphStyle(
        "DocSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=15,
        textColor=C_MUTED,
        alignment=TA_LEFT,
        spaceAfter=12,
    ),
    "MetaLabel": ParagraphStyle(
        "MetaLabel",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=C_PRIMARY,
    ),
    "MetaValue": ParagraphStyle(
        "MetaValue",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=C_BODY,
    ),
    "SectionTitle": ParagraphStyle(
        "SectionTitle",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16.5,
        textColor=C_TEAL,
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
    ),
    "SubSectionTitle": ParagraphStyle(
        "SubSectionTitle",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=C_PRIMARY,
        spaceBefore=9,
        spaceAfter=4,
        keepWithNext=True,
    ),
    "SubSubTitle": ParagraphStyle(
        "SubSubTitle",
        parent=base_styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=13,
        textColor=C_BODY,
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True,
    ),
    "Body": ParagraphStyle(
        "Body",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11.5,
        textColor=C_BODY,
        alignment=TA_JUSTIFY,
        spaceAfter=4,
    ),
    "BodyBold": ParagraphStyle(
        "BodyBold",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11.5,
        textColor=C_PRIMARY,
        spaceAfter=3,
    ),
    "Bullet": ParagraphStyle(
        "Bullet",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11.5,
        textColor=C_BODY,
        leftIndent=10,
        firstLineIndent=-7,
        spaceAfter=2.5,
    ),
    "TableHead": ParagraphStyle(
        "TableHead",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=10.5,
        textColor=C_PRIMARY,
        alignment=TA_LEFT,
    ),
    "TableCell": ParagraphStyle(
        "TableCell",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9.5,
        textColor=C_BODY,
        alignment=TA_LEFT,
    ),
    "TableCellBold": ParagraphStyle(
        "TableCellBold",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9.5,
        textColor=C_PRIMARY,
        alignment=TA_LEFT,
    ),
    "CodeBlock": ParagraphStyle(
        "CodeBlock",
        parent=base_styles["Normal"],
        fontName="Courier",
        fontSize=7,
        leading=9.5,
        textColor=C_PRIMARY,
        leftIndent=6,
        rightIndent=6,
    ),
    "CalloutText": ParagraphStyle(
        "CalloutText",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=11,
        textColor=C_BODY,
    ),
    "CalloutTitle": ParagraphStyle(
        "CalloutTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11.5,
        textColor=C_PRIMARY,
        spaceAfter=2,
    ),
    "QuestionTitle": ParagraphStyle(
        "QuestionTitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=12,
        textColor=C_TEAL,
        spaceBefore=5,
        spaceAfter=2,
        keepWithNext=True,
    ),
    "ShortAnswer": ParagraphStyle(
        "ShortAnswer",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=C_PRIMARY,
        leftIndent=6,
        spaceAfter=2.5,
    ),
    "DeepAnswer": ParagraphStyle(
        "DeepAnswer",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10.5,
        textColor=C_BODY,
        leftIndent=6,
        alignment=TA_JUSTIFY,
        spaceAfter=2.5,
    ),
    "CodeRef": ParagraphStyle(
        "CodeRef",
        parent=base_styles["Normal"],
        fontName="Courier",
        fontSize=7,
        leading=9.5,
        textColor=C_MUTED,
        leftIndent=6,
        spaceAfter=5,
    ),
}


# Flowable Builder Helpers
def p(text: str, style_name: str = "Body") -> Paragraph:
    return Paragraph(text, STYLES[style_name])


def sec_header(num: int, title: str) -> list:
    return [
        Spacer(1, 8),
        Paragraph(f"SECTION {num} &mdash; {title.upper()}", STYLES["SectionTitle"]),
        HRFlowable(width="100%", thickness=1.0, color=C_TEAL, spaceBefore=2, spaceAfter=6),
    ]


def sub_header(title: str) -> Paragraph:
    return Paragraph(title, STYLES["SubSectionTitle"])


def sub_sub_header(title: str) -> Paragraph:
    return Paragraph(title, STYLES["SubSubTitle"])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"&bull;&nbsp;&nbsp;{text}", STYLES["Bullet"])


def callout(text: str, title: str = None, border_color=C_TEAL, bg_color=C_TEAL_LIGHT) -> Table:
    content = []
    if title:
        content.append(Paragraph(title, STYLES["CalloutTitle"]))
    content.append(Paragraph(text, STYLES["CalloutText"]))

    t = Table([[content]], colWidths=[PRINTABLE_WIDTH])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
        ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3.0, border_color),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def code_box(code_text: str, title: str = None) -> list:
    """Format monospace code with safe chunking so no single box exceeds page limits."""
    lines = code_text.strip().splitlines()
    chunk_size = 24
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
    
    elements = []
    for idx, chunk in enumerate(chunks):
        formatted_lines = []
        if idx == 0 and title:
            formatted_lines.append(f"<b>// {title}</b><br/>")
        chunk_text = "\n".join(chunk)
        escaped = (
            chunk_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
            .replace(" ", "&nbsp;")
        )
        formatted_lines.append(escaped)

        p_code = Paragraph("".join(formatted_lines), STYLES["CodeBlock"])
        t = Table([[p_code]], colWidths=[PRINTABLE_WIDTH])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_BG_CARD),
            ("BOX", (0, 0), (-1, -1), 0.75, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)
        if idx < len(chunks) - 1:
            elements.append(Spacer(1, 4))
            
    return elements


def ascii_diagram(diag_text: str, caption: str = None) -> list:
    """Format ASCII diagrams with safe chunking to prevent LayoutError on page overflows."""
    lines = diag_text.strip().splitlines()
    chunk_size = 22
    chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
    
    elements = []
    for idx, chunk in enumerate(chunks):
        chunk_text = "\n".join(chunk)
        escaped = (
            chunk_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
            .replace(" ", "&nbsp;")
        )
        p_diag = Paragraph(escaped, STYLES["CodeBlock"])
        t = Table([[p_diag]], colWidths=[PRINTABLE_WIDTH])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.75, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(t)
        if idx < len(chunks) - 1:
            elements.append(Spacer(1, 4))

    if caption:
        elements.append(Spacer(1, 2))
        elements.append(Paragraph(f"<i>Figure: {caption}</i>", STYLES["MetaValue"]))
    elements.append(Spacer(1, 6))
    return elements


def make_table(data_rows, col_widths, has_header: bool = True) -> Table:
    """Create a clean ReportLab table with wrapping paragraphs."""
    table_data = []
    for row_idx, row in enumerate(data_rows):
        formatted_row = []
        for col_idx, cell in enumerate(row):
            if isinstance(cell, str):
                if has_header and row_idx == 0:
                    formatted_row.append(Paragraph(cell, STYLES["TableHead"]))
                else:
                    formatted_row.append(Paragraph(cell, STYLES["TableCell"]))
            else:
                formatted_row.append(cell)
        table_data.append(formatted_row)

    t = Table(table_data, colWidths=col_widths, repeatRows=1 if has_header else 0)
    t_style = [
        ("BOX", (0, 0), (-1, -1), 0.75, C_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if has_header:
        t_style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")))
        for r_idx in range(1, len(data_rows)):
            if r_idx % 2 == 0:
                t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), C_BG_CARD))
    t.setStyle(TableStyle(t_style))
    return t


def jury_q(q_num: str, question: str, verbal_answer: str, deep_explanation: str, code_ref: str) -> list:
    """Render a structured jury question block."""
    items = [
        Paragraph(f"<b>Q{q_num}: {question}</b>", STYLES["QuestionTitle"]),
        Paragraph(f"<b>Verbal Jury Defense:</b> &ldquo;{verbal_answer}&rdquo;", STYLES["ShortAnswer"]),
        Paragraph(f"<b>Technical In-Depth Explanation:</b> {deep_explanation}", STYLES["DeepAnswer"]),
        Paragraph(f"<b>Code &amp; File Reference:</b> <font color='#0F766E'><b>{code_ref}</b></font>", STYLES["CodeRef"]),
        HRFlowable(width="100%", thickness=0.5, color=C_BORDER_LIGHT, spaceBefore=2, spaceAfter=4),
    ]
    return items

