"""
Agence Ménage — Document Generator
Generates Devis (PDF) and Récapitulatif (PNG) from client data.
"""
 
import io
import os
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

couleur_principale = "#0F8A7D"
 
# ─── Brand colors ───────────────────────────────────────────────────────────
TEAL        = colors.HexColor(couleur_principale)
DARK_TEXT   = colors.HexColor("#2d3748")
LIGHT_BG    = colors.HexColor("#f7f7f7")
WHITE       = colors.white
 
TEAL_PIL    = (26, 158, 143)
DARK_PIL    = (45, 55, 72)
LIGHT_PIL   = (247, 247, 247)
WHITE_PIL   = (255, 255, 255)
GRAY_PIL    = (120, 120, 120)
BORDER_PIL  = (220, 220, 220)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# PDF — DEVIS
# ══════════════════════════════════════════════════════════════════════════════
 
def generate_devis_pdf(data: dict) -> bytes:
    """
    Generate a Devis PDF matching the Agence Ménage template.
 
    data keys:
        numero          str   e.g. "28"
        date            str   e.g. "23 mars 2026"
        client_nom      str
        client_telephone str
        client_adresse  str
        service_type    str   e.g. "Ménage fin de chantier"
        segment         str   e.g. "Entreprise" | "Particulier"
        intervenants    int|str
        frequence       str   e.g. "Ponctuel"
        total           str|int  e.g. "13000" or 13000
    """
    buffer = io.BytesIO()
    page_w, page_h = A4
    c = canvas.Canvas(buffer, pagesize=A4)
 
    # ── helpers ──────────────────────────────────────────────────────────────
    def teal_rect(x, y, w, h):
        c.setFillColor(TEAL)
        c.rect(x, y, w, h, fill=1, stroke=0)
 
    def light_rect(x, y, w, h):
        c.setFillColor(LIGHT_BG)
        c.rect(x, y, w, h, fill=1, stroke=0)
 
    margin = 20 * mm
    content_w = page_w - 2 * margin
 
    # ── HEADER band ──────────────────────────────────────────────────────────
    header_h = 28 * mm
    teal_rect(0, page_h - header_h, page_w, header_h)
 
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(margin, page_h - 16 * mm, "Agence Ménage")
 
    c.setFont("Helvetica", 10)
    c.drawString(margin, page_h - 23 * mm, "Casablanca, Maroc")
 
    # right side
    c.setFont("Helvetica", 9)
    c.drawRightString(page_w - margin, page_h - 14 * mm,
                      "Tél: +212 522-200177 | contact@agencemenage.ma")
 
    # ── DEVIS title ───────────────────────────────────────────────────────────
    y = page_h - header_h - 12 * mm
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(margin, y, "DEVIS")
 
    c.setFont("Helvetica", 10)
    c.setFillColor(DARK_TEXT)
    c.drawString(margin, y - 7 * mm,
                 f"N° {data.get('numero', '')}  —  Date: {data.get('date', '')}")
 
    # ── CLIENT section ────────────────────────────────────────────────────────
    y -= 22 * mm
    section_h = 28 * mm
    light_rect(margin, y - section_h, content_w, section_h)
 
    c.setFillColor(DARK_TEXT)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 4 * mm, y - 6 * mm, "Informations client")
 
    c.setFont("Helvetica", 10)
    c.setFillColor(DARK_TEXT)
 
    left_col  = margin + 4 * mm
    right_col = margin + content_w / 2
 
    c.drawString(left_col,  y - 13 * mm, f"Nom: {data.get('client_nom', '')}")
    c.drawString(right_col, y - 13 * mm, f"Adresse: {data.get('client_adresse', '')}")
    c.drawString(left_col,  y - 19 * mm, f"Téléphone: {data.get('client_telephone', '')}")
 
    # ── DETAILS table ─────────────────────────────────────────────────────────
    y -= section_h + 10 * mm
 
    # table header
    teal_rect(margin, y - 8 * mm, content_w, 8 * mm)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin + 4 * mm, y - 5.5 * mm, "Désignation")
    c.drawString(margin + content_w / 2, y - 5.5 * mm, "Détails")
 
    rows = [
        ("Type de service",       str(data.get("service_type", ""))),
        ("Segment",               str(data.get("segment", ""))),
        ("Nombre d'intervenants", str(data.get("intervenants", ""))),
        ("Fréquence",             str(data.get("frequence", ""))),
    ]
 
    row_h = 9 * mm
    for i, (label, value) in enumerate(rows):
        ry = y - 8 * mm - (i + 1) * row_h
        if i % 2 == 0:
            light_rect(margin, ry, content_w, row_h)
        c.setFillColor(DARK_TEXT)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin + 4 * mm, ry + 3 * mm, label)
        c.setFont("Helvetica", 10)
        c.drawString(margin + content_w / 2, ry + 3 * mm, value)
 
    # ── TOTAL ─────────────────────────────────────────────────────────────────
    total_y = y - 8 * mm - len(rows) * row_h - 10 * mm
    total_w = content_w / 2
    total_x = margin + content_w / 2
 
    teal_rect(total_x, total_y - 12 * mm, total_w, 12 * mm)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 14)
    total_str = f"Total: {data.get('total', '')} MAD"
    c.drawCentredString(total_x + total_w / 2, total_y - 8 * mm, total_str)
 
    # ── FOOTER ────────────────────────────────────────────────────────────────
    footer_y = 15 * mm
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.line(margin, footer_y + 6 * mm, page_w - margin, footer_y + 6 * mm)
 
    c.setFillColor(colors.HexColor("#888888"))
    c.setFont("Helvetica", 8)
    c.drawString(margin, footer_y + 2 * mm,
                 "Agence Ménage — ICE: 00XXXXXXXXXX    www.agencemenage.ma")
    c.drawString(margin, footer_y - 2 * mm,
                 "Ce devis est valable 30 jours à compter de sa date d'émission.")
 
    c.save()
    buffer.seek(0)
    return buffer.read()
 
 
# ══════════════════════════════════════════════════════════════════════════════
# PNG — RÉCAPITULATIF DE RÉSERVATION
# ══════════════════════════════════════════════════════════════════════════════
 
def generate_recap_png(data: dict) -> bytes:
    """
    Generate a Récapitulatif PNG matching the Agence Ménage template.
 
    data keys: same as generate_devis_pdf (date is used in footer)
    """
    # Canvas dimensions (A4-ish at 96 dpi)
    W, H = 794, 1123
    img  = Image.new("RGB", (W, H), WHITE_PIL)
    draw = ImageDraw.Draw(img)
 
    # ── font helpers (fallback to default PIL fonts) ──────────────────────────
    def font(size, bold=False):
        try:
            # Check common paths for Linux
            paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"
            ]
            for p in paths:
                if os.path.exists(p):
                    return ImageFont.truetype(p, size)
            return ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()
 
    # ── HEADER ────────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, W, 90], fill=TEAL_PIL)
    draw.text((30, 18), "Agence Ménage",    fill=WHITE_PIL,  font=font(26, bold=True))
    draw.text((30, 58), "Récapitulatif de réservation", fill=(200, 240, 235), font=font(14))
 
    # ── CLIENT card ────────────────────────────────────────────────────────────
    cx, cy, cw, ch = 30, 120, W - 60, 90
    draw.rectangle([cx, cy, cx + cw, cy + ch], fill=LIGHT_PIL)
    draw.text((cx + 15, cy + 12), "Client",           fill=DARK_PIL, font=font(13, bold=True))
    draw.text((cx + 15, cy + 35), f"Nom: {data.get('client_nom','')}",
              fill=DARK_PIL, font=font(12))
    draw.text((cx + 15, cy + 55), f"Téléphone: {data.get('client_telephone','')}",
              fill=DARK_PIL, font=font(12))
    draw.text((cx + cw // 2, cy + 35), f"Adresse: {data.get('client_adresse','')}",
              fill=DARK_PIL, font=font(12))
 
    # ── DETAILS table header ──────────────────────────────────────────────────
    ty = 250
    draw.rectangle([30, ty, W - 30, ty + 36], fill=TEAL_PIL)
    draw.text((45, ty + 10), "Détails de la prestation",
              fill=WHITE_PIL, font=font(12, bold=True))
 
    rows = [
        ("Service",       str(data.get("service_type", ""))),
        ("Segment",       str(data.get("segment", ""))),
        ("Intervenants",  str(data.get("intervenants", ""))),
        ("Fréquence",     str(data.get("frequence", ""))),
    ]
 
    row_h   = 42
    col_val = W // 2
 
    for i, (label, value) in enumerate(rows):
        ry = ty + 36 + i * row_h
        bg = LIGHT_PIL if i % 2 == 0 else WHITE_PIL
        draw.rectangle([30, ry, W - 30, ry + row_h], fill=bg)
        # separator line
        draw.line([30, ry, W - 30, ry], fill=BORDER_PIL)
        draw.text((45,        ry + 13), label, fill=DARK_PIL, font=font(12, bold=True))
        draw.text((col_val,   ry + 13), value, fill=DARK_PIL, font=font(12))
 
    # border around table
    table_bottom = ty + 36 + len(rows) * row_h
    draw.rectangle([30, ty, W - 30, table_bottom], outline=BORDER_PIL)
 
    # ── TOTAL badge ────────────────────────────────────────────────────────────
    tot_x = col_val
    tot_y = table_bottom + 25
    tot_w = W - 30 - tot_x
    tot_h = 52
    draw.rectangle([tot_x, tot_y, tot_x + tot_w, tot_y + tot_h], fill=TEAL_PIL)
 
    total_str = f"Total: {data.get('total', '')} MAD"
    # center text
    bbox = draw.textbbox((0, 0), total_str, font=font(18, bold=True))
    tw   = bbox[2] - bbox[0]
    draw.text((tot_x + (tot_w - tw) // 2, tot_y + 14),
              total_str, fill=WHITE_PIL, font=font(18, bold=True))
 
    # ── FOOTER ────────────────────────────────────────────────────────────────
    draw.line([30, H - 50, W - 30, H - 50], fill=BORDER_PIL)
    footer = (
        f"Agence Ménage  —  {data.get('date', '')}  —  www.agencemenage.ma"
    )
    bbox2 = draw.textbbox((0, 0), footer, font=font(10))
    fw = bbox2[2] - bbox2[0]
    draw.text(((W - fw) // 2, H - 38), footer, fill=GRAY_PIL, font=font(10))
 
    # ── export ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(150, 150))
    buf.seek(0)
    return buf.read()
