#!/usr/bin/env python3
"""Generate book cover for 'Assumed Role' — Terminal Noir aesthetic."""

from reportlab.lib.pagesizes import inch
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# --- Configuration ---
OUTPUT = "/Users/rk/Vault/code/assumed-role/assumed-role-cover.pdf"
FONTS_DIR = "/Users/rk/.claude/skills/canvas-design/canvas-fonts"

# Page: 6x9 inches (standard trade paperback)
W, H = 6 * inch, 9 * inch

# Colors — Terminal Noir palette
BG = Color(0.022, 0.024, 0.055)        # Deep blue-black
RED = Color(0.82, 0.11, 0.09)          # Arterial red
RED_DIM = Color(0.35, 0.06, 0.05)      # Muted red for glow
WHITE = Color(0.90, 0.91, 0.94)        # Screen-light white
WHITE_DIM = Color(0.45, 0.48, 0.55)    # Faded label white
RULE_CLR = Color(0.25, 0.27, 0.33)     # Thin rules

# Register fonts
pdfmetrics.registerFont(TTFont("Italiana", os.path.join(FONTS_DIR, "Italiana-Regular.ttf")))
pdfmetrics.registerFont(TTFont("JetBrains", os.path.join(FONTS_DIR, "JetBrainsMono-Regular.ttf")))
pdfmetrics.registerFont(TTFont("JetBrainsBold", os.path.join(FONTS_DIR, "JetBrainsMono-Bold.ttf")))
pdfmetrics.registerFont(TTFont("JuraLight", os.path.join(FONTS_DIR, "Jura-Light.ttf")))
pdfmetrics.registerFont(TTFont("JuraMedium", os.path.join(FONTS_DIR, "Jura-Medium.ttf")))

c = canvas.Canvas(OUTPUT, pagesize=(W, H))

# --- Background ---
c.setFillColor(BG)
c.rect(0, 0, W, H, fill=1, stroke=0)

# --- CloudTrail JSON event — the real artifact ---
json_lines = [
    '{',
    '  "eventVersion": "1.09",',
    '  "userIdentity": {',
    '    "type": "IAMUser",',
    '    "principalId": "AIDAIOSFODNN7EXAMPLE",',
    '    "arn": "arn:aws:iam::487291035561:user/svc-payment-processor",',
    '    "accountId": "487291035561",',
    '    "accessKeyId": "AKIAIOSFODNN7EXAMPLE"',
    '  },',
    '  "eventTime": "2025-03-13T06:14:00Z",',
    '  "eventSource": "cloudtrail.amazonaws.com",',
    '  "eventName": "StopLogging",',              # index 11
    '  "awsRegion": "us-east-1",',
    '  "sourceIPAddress": "98.47.216.103",',
    '  "userAgent": "aws-cli/2.15.0",',
    '  "requestParameters": {',
    '    "name": "arn:aws:cloudtrail:us-east-1:487291035561:trail/prod-payments"',
    '  },',
    '  "responseElements": {',
    '    "StopLoggingResponse": ""',
    '  },',
    '  "eventID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",',
    '  "readOnly": false,',
    '  "eventType": "AwsApiCall",',
    '  "managementEvent": true,',
    '  "recipientAccountId": "487291035561",',
    '  "eventCategory": "Management"',
    '}',
]

HIGHLIGHT_IDX = 11  # "eventName": "StopLogging"

# --- Render JSON texture ---
fsize = 5.2
lh = 7.8
lm = 30  # left margin
start_y = H - 44
highlight_y = None  # track for red accent

c.setFont("JetBrains", fsize)
y = start_y

for block in range(4):
    for i, line in enumerate(json_lines):
        if y < 72:
            break

        abs_idx = block * len(json_lines) + i
        is_hl_block = (block == 1)
        dist = abs(i - HIGHLIGHT_IDX)

        if is_hl_block and i == HIGHLIGHT_IDX:
            # --- THE line. The break in the pattern. ---
            highlight_y = y
            # Red glow bar
            c.setFillColor(Color(0.15, 0.03, 0.03))
            c.rect(lm - 8, y - 2, W - 2 * lm + 16, lh + 0.5, fill=1, stroke=0)
            # Red text
            c.setFillColor(RED)
            c.setFont("JetBrainsBold", fsize + 0.2)
            c.drawString(lm, y, line)
            c.setFont("JetBrains", fsize)
        elif is_hl_block and dist <= 5:
            # Gradient fade: brighter near highlight
            t = 1.0 - (dist / 6.0)
            v = 0.08 + t * 0.18
            c.setFillColor(Color(v, v + 0.01, v + 0.04))
            c.drawString(lm, y, line)
        else:
            # Background texture — barely visible, slight variation
            v = 0.065 + 0.015 * ((abs_idx * 7) % 5) / 4.0
            c.setFillColor(Color(v, v + 0.008, v + 0.025))
            c.drawString(lm, y, line)

        y -= lh
    y -= lh * 0.3  # slight gap between blocks

# --- Red accent mark in left margin next to highlighted line ---
if highlight_y:
    c.setStrokeColor(RED)
    c.setLineWidth(2.0)
    c.line(17, highlight_y - 1.5, 17, highlight_y + lh + 0.5)

# --- Title zone ---
# Dark strip to ensure title reads cleanly over any code texture
title_base = H * 0.37
strip_h = 100
c.setFillColor(BG)
c.rect(0, title_base - 10, W, strip_h, fill=1, stroke=0)
# Soft transition strips above and below
for i in range(12):
    t = i / 12.0
    edge_v = 0.065 * (1.0 - t)
    c.setFillColor(Color(0.022 + edge_v * 0.3, 0.024 + edge_v * 0.3, 0.055 + edge_v * 0.3))
    c.rect(0, title_base + strip_h + i * 2, W, 2, fill=1, stroke=0)
    c.rect(0, title_base - 10 - (i + 1) * 2, W, 2, fill=1, stroke=0)

# Title: ASSUMED ROLE
c.setFillColor(WHITE)
c.setFont("Italiana", 50)
title = "ASSUMED  ROLE"
tw = c.stringWidth(title, "Italiana", 50)
c.drawString((W - tw) / 2, title_base + 48, title)

# Thin rule
c.setStrokeColor(RULE_CLR)
c.setLineWidth(0.35)
rule_in = 110
c.line(rule_in, title_base + 38, W - rule_in, title_base + 38)

# Subtitle
c.setFillColor(WHITE_DIM)
c.setFont("JuraLight", 10.5)
sub = "A  CLOUD  SECURITY  THRILLER"
sw = c.stringWidth(sub, "JuraLight", 10.5)
c.drawString((W - sw) / 2, title_base + 18, sub)

# --- Author ---
c.setFillColor(WHITE_DIM)
c.setFont("JuraMedium", 9.5)
author = "rK"
aw = c.stringWidth(author, "JuraMedium", 9.5)
c.drawString((W - aw) / 2, 34, author)

# Thin rule above author
c.setStrokeColor(Color(0.18, 0.20, 0.26))
c.setLineWidth(0.25)
c.line(180, 50, W - 180, 50)

# --- Subtle top/bottom fade to pure background (narrow strips only) ---
# Only fade the very edge — 8px at top, don't cover the JSON field
for i in range(4):
    c.setFillColor(BG)
    c.rect(0, H - 1 - i, W, 1, fill=1, stroke=0)
    c.rect(0, i, W, 1, fill=1, stroke=0)

# --- Save ---
c.save()
print(f"Cover saved to {OUTPUT}")
