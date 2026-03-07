#!/usr/bin/env python3
"""Generate full manuscript PDF for 'Assumed Role' with Terminal Noir aesthetic."""

import os
import re
import math
from reportlab.lib.pagesizes import inch
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted,
    Flowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

# --- Paths ---
BASE = "/Users/rk/Vault/code/assumed-role"
FONTS = "/Users/rk/.claude/skills/canvas-design/canvas-fonts"
OUTPUT = os.path.join(BASE, "assumed-role-manuscript.pdf")
COVER_PDF = os.path.join(BASE, "assumed-role-cover.pdf")

# --- Page setup ---
W, H = 6 * inch, 9 * inch
MARGIN_TOP = 0.75 * inch
MARGIN_BOT = 0.7 * inch
MARGIN_L = 0.7 * inch
MARGIN_R = 0.7 * inch

# --- Colors (Dark mode — terminal aesthetic) ---
BG_PAGE = Color(0.098, 0.106, 0.141)    # VS Code dark: #191b24
BG_CODE = Color(0.065, 0.071, 0.098)    # Slightly deeper for code blocks
TEXT_BODY = Color(0.80, 0.82, 0.87)      # Soft off-white body text
TEXT_CODE = Color(0.72, 0.78, 0.85)      # Slightly blue-tinted code text
TEXT_DIM = Color(0.45, 0.48, 0.55)       # Muted labels, page numbers
TEXT_BRIGHT = Color(0.92, 0.93, 0.96)    # Chapter titles, emphasis
RED_ACCENT = Color(0.82, 0.11, 0.09)    # Alert red
RULE_COLOR = Color(0.25, 0.27, 0.33)    # Scene break rules

# --- Register fonts ---
font_map = {
    "CrimsonPro": "CrimsonPro-Regular.ttf",
    "CrimsonProItalic": "CrimsonPro-Italic.ttf",
    "CrimsonProBold": "CrimsonPro-Bold.ttf",
    "Italiana": "Italiana-Regular.ttf",
    "JetBrains": "JetBrainsMono-Regular.ttf",
    "JetBrainsBold": "JetBrainsMono-Bold.ttf",
    "JuraLight": "Jura-Light.ttf",
    "JuraMedium": "Jura-Medium.ttf",
    "Lora": "Lora-Regular.ttf",
    "LoraItalic": "Lora-Italic.ttf",
    "LoraBold": "Lora-Bold.ttf",
    "LoraBoldItalic": "Lora-BoldItalic.ttf",
}
for name, filename in font_map.items():
    pdfmetrics.registerFont(TTFont(name, os.path.join(FONTS, filename)))

# --- Styles ---
styles = {}

styles["body"] = ParagraphStyle(
    "body", fontName="Lora", fontSize=10, leading=15.5,
    textColor=TEXT_BODY, alignment=TA_JUSTIFY, spaceAfter=8,
    firstLineIndent=0, backColor=None,
)

styles["body_indent"] = ParagraphStyle(
    "body_indent", parent=styles["body"], firstLineIndent=18,
)

styles["chapter_title"] = ParagraphStyle(
    "chapter_title", fontName="Italiana", fontSize=28, leading=34,
    textColor=TEXT_BRIGHT, alignment=TA_CENTER, spaceBefore=4, spaceAfter=6,
)

styles["chapter_subtitle"] = ParagraphStyle(
    "chapter_subtitle", fontName="JuraLight", fontSize=10, leading=14,
    textColor=TEXT_DIM, alignment=TA_CENTER, spaceAfter=36,
)

styles["epigraph"] = ParagraphStyle(
    "epigraph", fontName="LoraItalic", fontSize=11, leading=17,
    textColor=TEXT_DIM, alignment=TA_CENTER, spaceBefore=180, spaceAfter=8,
)

styles["epigraph_attr"] = ParagraphStyle(
    "epigraph_attr", fontName="Lora", fontSize=9, leading=13,
    textColor=TEXT_DIM, alignment=TA_CENTER, spaceAfter=0,
)

styles["disclaimer"] = ParagraphStyle(
    "disclaimer", fontName="Lora", fontSize=9.5, leading=15,
    textColor=TEXT_DIM, alignment=TA_CENTER, spaceBefore=220,
)

styles["section_heading"] = ParagraphStyle(
    "section_heading", fontName="LoraBold", fontSize=12, leading=16,
    textColor=TEXT_BRIGHT, alignment=TA_LEFT, spaceBefore=20, spaceAfter=10,
)

styles["code"] = ParagraphStyle(
    "code", fontName="JetBrains", fontSize=5.8, leading=8.8,
    textColor=TEXT_CODE, alignment=TA_LEFT, spaceBefore=6, spaceAfter=6,
    leftIndent=12, rightIndent=12,
)

styles["author_note_body"] = ParagraphStyle(
    "author_note_body", fontName="Lora", fontSize=10, leading=15.5,
    textColor=TEXT_BODY, alignment=TA_JUSTIFY, spaceAfter=10, backColor=None,
)

styles["list_item"] = ParagraphStyle(
    "list_item", fontName="Lora", fontSize=10, leading=15.5,
    textColor=TEXT_BODY, alignment=TA_LEFT, spaceAfter=4,
    leftIndent=18, bulletIndent=6,
)

styles["about"] = ParagraphStyle(
    "about", fontName="LoraItalic", fontSize=10, leading=15.5,
    textColor=TEXT_DIM, alignment=TA_CENTER, spaceBefore=180,
)


# --- Custom flowables ---
class HRule(Flowable):
    """Centered horizontal rule for scene breaks."""
    def __init__(self, width=60):
        super().__init__()
        self.rule_width = width

    def wrap(self, availWidth, availHeight):
        self.avail = availWidth
        return (availWidth, 24)

    def draw(self):
        x = (self.avail - self.rule_width) / 2
        self.canv.setStrokeColor(RULE_COLOR)
        self.canv.setLineWidth(0.4)
        self.canv.line(x, 12, x + self.rule_width, 12)


class SceneBreak(Flowable):
    """Three centered dots for scene breaks."""
    def __init__(self):
        super().__init__()

    def wrap(self, availWidth, availHeight):
        self.avail = availWidth
        return (availWidth, 30)

    def draw(self):
        cx = self.avail / 2
        self.canv.setFillColor(TEXT_DIM)
        for dx in [-12, 0, 12]:
            self.canv.circle(cx + dx, 15, 1.2, fill=1, stroke=0)


class CodeBlock(Flowable):
    """Code block with dark background. Wraps long lines."""
    TEXT_X = 14
    PAD_R = 14

    def __init__(self, text, style):
        super().__init__()
        self.text = text
        self.style = style

    def _wrap_lines(self, max_w):
        """Split long lines to fit within max_w pixels."""
        font = self.style.fontName
        size = self.style.fontSize
        result = []
        for line in self.text.split('\n'):
            if pdfmetrics.stringWidth(line, font, size) <= max_w:
                result.append(line)
            else:
                # Wrap at character boundary
                current = ''
                for ch in line:
                    test = current + ch
                    if pdfmetrics.stringWidth(test, font, size) > max_w:
                        result.append(current)
                        current = '  ' + ch  # indent continuation
                    else:
                        current = test
                if current:
                    result.append(current)
        return result

    def wrap(self, availWidth, availHeight):
        self.avail = availWidth
        max_w = availWidth - 8 - self.TEXT_X - self.PAD_R
        self.rendered_lines = self._wrap_lines(max_w)
        self.block_height = len(self.rendered_lines) * self.style.leading + 14
        return (availWidth, self.block_height)

    def draw(self):
        self.canv.setFillColor(BG_CODE)
        self.canv.roundRect(
            4, 0, self.avail - 8, self.block_height,
            3, fill=1, stroke=0
        )
        self.canv.setFillColor(TEXT_CODE)
        self.canv.setFont(self.style.fontName, self.style.fontSize)
        y = self.block_height - 10
        for line in self.rendered_lines:
            self.canv.drawString(self.TEXT_X, y, line)
            y -= self.style.leading


class ChapterArt(Flowable):
    """Small abstract art piece at chapter opening. Terminal Noir aesthetic."""

    ART_H = 72  # 1 inch tall
    PAD = 8

    def __init__(self, chapter_num):
        super().__init__()
        self.chapter_num = chapter_num

    def wrap(self, availWidth, availHeight):
        self.avail = availWidth
        return (availWidth, self.ART_H + 16)

    def draw(self):
        c = self.canv
        w = self.avail
        h = self.ART_H
        cx = w / 2
        cy = h / 2 + 8

        # Dark background strip
        c.setFillColor(BG_CODE)
        c.roundRect(0, 4, w, h + 8, 4, fill=1, stroke=0)

        dispatch = {
            1: self._draw_alert,
            2: self._draw_key,
            3: self._draw_lateral,
            4: self._draw_door,
            5: self._draw_ghosts,
            6: self._draw_perimeter,
        }
        fn = dispatch.get(self.chapter_num, self._draw_alert)
        fn(c, cx, cy, w, h)

    def _draw_alert(self, c, cx, cy, w, h):
        """Ch 1: Red dot with concentric fading rings — the quiet alert."""
        # Concentric rings fading outward
        for i in range(7, 0, -1):
            r = 4 + i * 5.5
            intensity = 0.12 + 0.08 * (7 - i) / 6
            c.setStrokeColor(Color(0.82, 0.11, 0.09))
            c.setLineWidth(0.3 + 0.15 * (7 - i) / 6)
            # Dashed rings for outer, solid for inner
            if i > 3:
                c.setDash(2, 4)
            else:
                c.setDash()
            c.circle(cx, cy, r, fill=0, stroke=1)
        c.setDash()
        # Solid red center dot
        c.setFillColor(RED_ACCENT)
        c.circle(cx, cy, 3.5, fill=1, stroke=0)

    def _draw_key(self, c, cx, cy, w, h):
        """Ch 2: Key fragmenting into scattered particles — credential handoff."""
        # Key shaft (left side)
        c.setStrokeColor(Color(0.55, 0.57, 0.65))
        c.setLineWidth(1.5)
        shaft_start = cx - 32
        shaft_end = cx - 4
        c.line(shaft_start, cy, shaft_end, cy)
        # Key teeth
        for tx in range(0, 3):
            x = shaft_start + 6 + tx * 8
            c.line(x, cy, x, cy - 6)
        # Key head circle
        c.setFillColor(BG_CODE)
        c.circle(cx - 36, cy, 6, fill=1, stroke=1)

        # Fragmentation: particles scattering right
        import random
        rng = random.Random(42)  # deterministic
        c.setFillColor(RED_ACCENT)
        for i in range(18):
            px = cx + 4 + i * 3.2 + rng.uniform(-2, 2)
            py = cy + rng.uniform(-14, 14)
            size = 1.8 - i * 0.07
            if size > 0.3:
                alpha_sim = max(0.15, 1.0 - i / 18)
                c.setFillColor(Color(0.82 * alpha_sim, 0.11 * alpha_sim, 0.09 * alpha_sim))
                c.rect(px, py, size, size, fill=1, stroke=0)

    def _draw_lateral(self, c, cx, cy, w, h):
        """Ch 3: Branching network nodes — cross-account lateral movement."""
        nodes = [
            (cx - 60, cy),       # origin
            (cx - 20, cy + 16),  # branch up
            (cx - 20, cy - 16),  # branch down
            (cx + 20, cy + 8),   # second hop
            (cx + 20, cy - 8),
            (cx + 20, cy - 24),
            (cx + 55, cy),       # far node
        ]
        # Connection lines
        edges = [(0, 1), (0, 2), (1, 3), (1, 4), (2, 5), (3, 6), (4, 6)]
        c.setStrokeColor(Color(0.35, 0.37, 0.45))
        c.setLineWidth(0.5)
        for a, b in edges:
            c.line(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1])

        # Nodes
        for i, (nx, ny) in enumerate(nodes):
            if i == 0:
                c.setFillColor(Color(0.55, 0.57, 0.65))
                c.circle(nx, ny, 4, fill=1, stroke=0)
            elif i == len(nodes) - 1:
                c.setFillColor(RED_ACCENT)
                c.circle(nx, ny, 4, fill=1, stroke=0)
            else:
                c.setFillColor(Color(0.30, 0.32, 0.40))
                c.circle(nx, ny, 3, fill=1, stroke=0)

    def _draw_door(self, c, cx, cy, w, h):
        """Ch 4: Vertical bars with one gap — the open door in the wall."""
        num_bars = 19
        bar_w = 2.2
        gap = 6.5
        total = num_bars * (bar_w + gap) - gap
        start_x = cx - total / 2
        door_idx = 9  # middle bar missing

        for i in range(num_bars):
            x = start_x + i * (bar_w + gap)
            if i == door_idx:
                # The gap — draw faint red glow
                c.setFillColor(Color(0.25, 0.04, 0.03))
                c.rect(x - 2, cy - 22, bar_w + 4, 44, fill=1, stroke=0)
                continue
            # Bars get dimmer further from the gap
            dist = abs(i - door_idx)
            v = max(0.15, 0.50 - dist * 0.035)
            c.setFillColor(Color(v * 0.7, v * 0.72, v * 0.82))
            c.rect(x, cy - 20, bar_w, 40, fill=1, stroke=0)

    def _draw_ghosts(self, c, cx, cy, w, h):
        """Ch 5: Overlapping rectangles with decreasing opacity — persistence layers."""
        rects = [
            (cx - 40, cy - 14, 48, 28),
            (cx - 26, cy - 10, 48, 28),
            (cx - 12, cy - 6, 48, 28),
            (cx + 2, cy - 2, 48, 28),
        ]
        for i, (rx, ry, rw, rh) in enumerate(rects):
            t = (i + 1) / len(rects)
            if i == len(rects) - 1:
                # Last one: red outline
                c.setStrokeColor(RED_ACCENT)
                c.setLineWidth(0.8)
                c.setFillColor(Color(0.10, 0.02, 0.02))
                c.rect(rx, ry, rw, rh, fill=1, stroke=1)
            else:
                v = 0.10 + t * 0.12
                c.setStrokeColor(Color(v + 0.1, v + 0.12, v + 0.18))
                c.setLineWidth(0.4)
                c.setFillColor(Color(v * 0.6, v * 0.62, v * 0.7))
                c.rect(rx, ry, rw, rh, fill=1, stroke=1)

    def _draw_perimeter(self, c, cx, cy, w, h):
        """Ch 6: Broken circle reforming — the new perimeter."""
        r = 24
        # Broken arcs (the old perimeter — gaps)
        c.setStrokeColor(Color(0.30, 0.32, 0.40))
        c.setLineWidth(0.6)
        segments = [(20, 80), (100, 170), (200, 310), (330, 370)]
        for start, end in segments:
            p = c.beginPath()
            p.arc(cx - r, cy - r, cx + r, cy + r, start, end - start)
            c.drawPath(p, fill=0, stroke=1)

        # Solid reforming arcs (new perimeter — red)
        c.setStrokeColor(RED_ACCENT)
        c.setLineWidth(1.2)
        new_segments = [(80, 100), (170, 200), (310, 330)]
        for start, end in new_segments:
            p = c.beginPath()
            p.arc(cx - r, cy - r, cx + r, cy + r, start, end - start)
            c.drawPath(p, fill=0, stroke=1)

        # Center dot — solid
        c.setFillColor(Color(0.55, 0.57, 0.65))
        c.circle(cx, cy, 2.5, fill=1, stroke=0)


# --- Markdown parser ---
def parse_markdown(filepath):
    """Parse a markdown file into reportlab flowables."""
    with open(filepath, 'r') as f:
        content = f.read()

    flowables = []
    lines = content.split('\n')
    i = 0
    first_para = True

    while i < len(lines):
        line = lines[i]

        # Chapter title (# heading)
        if line.startswith('# '):
            title_text = line[2:].strip()
            # Split "Chapter N: Title" into number and title
            match = re.match(r'Chapter (\d+): (.+)', title_text)
            if match:
                num, title = match.groups()
                flowables.append(ChapterArt(int(num)))
                flowables.append(Spacer(1, 12))
                flowables.append(Paragraph(
                    f"Chapter {num}", styles["chapter_subtitle"]
                ))
                flowables.append(Spacer(1, 2))
                flowables.append(Paragraph(title, styles["chapter_title"]))
            else:
                flowables.append(Paragraph(title_text, styles["chapter_title"]))
            flowables.append(Spacer(1, 20))
            first_para = True
            i += 1
            continue

        # Section heading (## or ### heading)
        if line.startswith('## ') or line.startswith('### '):
            heading = re.sub(r'^#{2,3}\s+', '', line).strip()
            heading = format_inline(heading)
            flowables.append(Paragraph(heading, styles["section_heading"]))
            first_para = True
            i += 1
            continue

        # Horizontal rule (scene break)
        if line.strip() == '---':
            flowables.append(SceneBreak())
            first_para = True
            i += 1
            continue

        # Code block
        if line.strip().startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_text = '\n'.join(code_lines)
            if code_text.strip():
                flowables.append(CodeBlock(code_text, styles["code"]))
            continue

        # Empty line
        if line.strip() == '':
            i += 1
            continue

        # List item (- text)
        if line.strip().startswith('- '):
            item_text = line.strip()[2:]
            item_text = format_inline(item_text)
            flowables.append(Paragraph(
                f"\u2022  {item_text}", styles["list_item"]
            ))
            i += 1
            continue

        # Table rows (| ... |) — render as plain text
        if line.strip().startswith('|'):
            # Skip separator rows (|---|---|)
            if re.match(r'^\|[\s\-:|]+\|$', line.strip()):
                i += 1
                continue
            # Strip pipes and render cells
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            row_text = '    '.join(cells)
            row_text = format_inline(row_text)
            flowables.append(Paragraph(
                f'<font name="JetBrains" size="8" color="#b8bcc8">{row_text}</font>',
                styles["body"]
            ))
            i += 1
            continue

        # Regular paragraph — collect continuous lines
        para_lines = []
        while i < len(lines) and lines[i].strip() != '' and \
              not lines[i].startswith('#') and not lines[i].startswith('```') and \
              lines[i].strip() != '---':
            para_lines.append(lines[i])
            i += 1

        if para_lines:
            text = ' '.join(para_lines)
            text = format_inline(text)
            style = styles["body"] if first_para else styles["body_indent"]
            flowables.append(Paragraph(text, style))
            first_para = False

    return flowables


def format_inline(text):
    """Convert markdown inline formatting to reportlab XML tags."""
    # Escape XML special chars first
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;').replace('>', '&gt;')

    # Markdown links [text](url) -> just text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # Inline code (`text`) — do before bold/italic to protect backtick content
    text = re.sub(
        r'`([^`]+)`',
        r'<font name="JetBrains" size="8" color="#9ba3b5">\1</font>',
        text
    )

    # Bold (**text**) — simple non-greedy, no lookahead
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

    # Italic (*text*) — only match single * around non-* content
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)

    # Em dash
    text = text.replace(' — ', ' \u2014 ')
    text = text.replace('— ', '\u2014 ')
    text = text.replace(' —', ' \u2014')

    return text


# --- Page template ---
def page_background(canvas, doc):
    """Dark background + page number."""
    canvas.saveState()
    # Dark page background
    canvas.setFillColor(BG_PAGE)
    canvas.rect(0, 0, W, H, fill=1, stroke=0)
    # Page number
    canvas.setFont("JuraLight", 7.5)
    canvas.setFillColor(TEXT_DIM)
    page_num = canvas.getPageNumber()
    if page_num > 2:
        canvas.drawCentredString(W / 2, MARGIN_BOT - 20, str(page_num - 2))
    canvas.restoreState()


# --- Build document ---
def build():
    doc = SimpleDocTemplate(
        OUTPUT,
        pagesize=(W, H),
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOT,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
    )

    story = []

    # --- Page 1: Cover placeholder (we'll merge the real cover later) ---
    # For now, simple title page
    story.append(Spacer(1, 140))
    story.append(Paragraph("ASSUMED  ROLE", ParagraphStyle(
        "cover_title", fontName="Italiana", fontSize=42, leading=48,
        textColor=TEXT_BRIGHT, alignment=TA_CENTER,
    )))
    story.append(Spacer(1, 8))
    story.append(Paragraph("A Cloud Security Thriller", ParagraphStyle(
        "cover_sub", fontName="JuraLight", fontSize=12, leading=16,
        textColor=TEXT_DIM, alignment=TA_CENTER,
    )))
    story.append(Spacer(1, 30))
    story.append(Paragraph("rK", ParagraphStyle(
        "cover_author", fontName="JuraMedium", fontSize=11, leading=14,
        textColor=TEXT_DIM, alignment=TA_CENTER,
    )))
    story.append(PageBreak())

    # --- Page 2: Disclaimer ---
    story.append(Paragraph(
        "This is fiction. The techniques are real. Every CloudTrail event, "
        "SQL query, CLI command, and IAM policy in this book is executable. "
        "Use them to defend things.",
        styles["disclaimer"]
    ))
    story.append(PageBreak())

    # --- Chapters ---
    chapter_files = [
        "chapter-1-the-quiet-alert.md",
        "chapter-2-the-way-in.md",
        "chapter-3-lateral.md",
        "chapter-4-the-open-door.md",
        "chapter-5-ghosts-in-the-machine.md",
        "chapter-6-new-perimeter.md",
    ]

    for ch_file in chapter_files:
        filepath = os.path.join(BASE, ch_file)
        flowables = parse_markdown(filepath)
        story.extend(flowables)
        story.append(PageBreak())

    # --- Author's Note ---
    story.append(Paragraph("Author\u2019s Note", styles["chapter_title"]))
    story.append(Spacer(1, 24))

    note_paras = [
        "Every attack in this book happened somewhere. The credential that was never "
        "revoked. The IMDSv1 instance nobody patched. The security group opened for "
        "five seconds. The S3 replication rule nobody monitored. Different companies, "
        "different years, same patterns.",

        "Maya is fictional. Her situation isn\u2019t. Most companies her size have one "
        "person doing what should be a team\u2019s job. They enable GuardDuty and call it "
        "security. They pass audits while attackers move through their infrastructure. "
        "The tools work. The gap is always human \u2014 not enough people, not enough time, "
        "not enough authority to fix what they can see.",

        "If you recognized the techniques in this book, you\u2019re probably that person. "
        "Build the detections. Automate the responses. Push for temporary access. And "
        "hire a second engineer before you need one.",

        "The tools Maya built exist. Search for them.",
    ]

    for i, para in enumerate(note_paras):
        s = styles["author_note_body"] if i == 0 else styles["body_indent"]
        story.append(Paragraph(para, s))

    story.append(PageBreak())

    # --- Appendix ---
    story.append(Paragraph("Appendix", styles["chapter_title"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Techniques, Detections &amp; Real-World References",
        styles["chapter_subtitle"]
    ))
    story.append(Spacer(1, 12))

    appendix_flowables = parse_markdown(os.path.join(BASE, "appendix-techniques.md"))
    # Skip the first element if it's the title (already added above)
    skip_first_heading = True
    for f in appendix_flowables:
        if skip_first_heading and isinstance(f, Paragraph) and 'chapter_title' in str(getattr(f, 'style', '')):
            skip_first_heading = False
            continue
        story.extend([f] if not isinstance(f, list) else f)

    # End after appendix — no about page

    # --- Build ---
    doc.build(story, onFirstPage=page_background, onLaterPages=page_background)
    print(f"Manuscript saved to {OUTPUT}")

    # --- Merge with cover ---
    merge_cover()


def merge_cover():
    """Prepend the cover PDF to the manuscript."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("Install pypdf to merge cover: pip3 install pypdf")
        return

    if not os.path.exists(COVER_PDF):
        print(f"Cover not found at {COVER_PDF}, skipping merge")
        return

    writer = PdfWriter()

    # Add cover
    cover = PdfReader(COVER_PDF)
    writer.add_page(cover.pages[0])

    # Add manuscript (skip the placeholder title page)
    manuscript = PdfReader(OUTPUT)
    for i, page in enumerate(manuscript.pages):
        if i == 0:  # Skip placeholder title page
            continue
        writer.add_page(page)

    final_path = os.path.join(BASE, "assumed-role-final.pdf")
    with open(final_path, 'wb') as f:
        writer.write(f)

    print(f"Final manuscript with cover saved to {final_path}")


if __name__ == "__main__":
    build()
