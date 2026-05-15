"""
generate_profile_card.py
------------------------
Génère une fiche profil (image PNG) au format WhatsApp
pour Agence Ménage — Groupe Agence Premium.
"""

import math
import os
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Support for HEIC/HEIF (common on iPhone)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass



# ── Constantes visuelles ────────────────────────────────────────────────────

W, H = 1004, 650                      # Dimensions du canvas (px)

# Palette (extraite du template)
BG_COLOR        = (250, 246, 240)     # crème clair
TEAL            = (0, 139, 139)       # vert-canard principal
DARK_OLIVE      = (85, 107, 47)       # vert olive foncé (cercle bas-gauche)
GOLD            = (212, 175, 55)      # doré (formes décoratives)
TEXT_DARK       = (40, 40, 40)        # quasi-noir pour le texte

# Tentative de localisation des polices (Linux standard)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _get_font(bold=True, size=28):
    font_name = 'Roboto-Bold.ttf' if bold else 'Roboto-Regular.ttf'
    custom_font_path = os.path.join(BASE_DIR, 'assets', 'fonts', font_name)
    
    if os.path.exists(custom_font_path):
        return ImageFont.truetype(custom_font_path, size)
        
    FONT_PATHS = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    for path in FONT_PATHS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _circle_mask(size: int) -> Image.Image:
    """Retourne un masque blanc circulaire (L mode)."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    return mask


def _draw_filled_circle(draw: ImageDraw.ImageDraw,
                         cx: int, cy: int, r: int, color: tuple) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


# ── Dessin des formes décoratives ────────────────────────────────────────────

def _draw_background_shapes(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)

    # ── Coin supérieur droit : grand quart de cercle teal ──
    r_top = 230
    cx_top, cy_top = W, 0
    draw.ellipse(
        (cx_top - r_top, cy_top - r_top, cx_top + r_top, cy_top + r_top),
        fill=TEAL,
    )

    # ── Coin supérieur droit : petit quart de cercle doré ──
    r_gold_top = 110
    draw.ellipse(
        (W - r_gold_top, -r_gold_top, W + r_gold_top, r_gold_top),
        fill=GOLD,
    )

    # ── Coin inférieur gauche : grand quart de cercle vert olive ──
    r_bot = 180
    draw.ellipse(
        (-r_bot, H - r_bot, r_bot, H + r_bot),
        fill=DARK_OLIVE,
    )

    # ── Coin inférieur droit : petit demi-cercle doré ──
    r_gold_bot = 70
    draw.ellipse(
        (W - r_gold_bot, H - r_gold_bot, W + r_gold_bot, H + r_gold_bot),
        fill=GOLD,
    )


# ── Composition de la photo de profil (cercle avec fond cyan) ───────────────

def _paste_profile_photo(img: Image.Image,
                          profile_photo_input) -> None:
    # Fond cyan (grand cercle)
    CIRCLE_BG   = (100, 200, 210)   # cyan clair
    OUTER_R     = 195               # rayon du fond
    PHOTO_R     = 170               # rayon de la photo découpée
    CX          = 710               # centre X du cercle
    CY          = 310               # centre Y du cercle

    draw = ImageDraw.Draw(img)
    _draw_filled_circle(draw, CX, CY, OUTER_R, CIRCLE_BG)

    # Photo découpée en cercle
    if not profile_photo_input:
        photo = Image.new("RGBA", (PHOTO_R * 2, PHOTO_R * 2), (180, 180, 180, 255))
    else:
        try:
            # If it's a file-like object, read it into BytesIO to ensure it's seekable
            if hasattr(profile_photo_input, 'read'):
                content = profile_photo_input.read()
                profile_photo_input = io.BytesIO(content)

            photo = Image.open(profile_photo_input).convert("RGBA")
            # Recadrage carré centré (portrait)
            pw, ph = photo.size
            side = min(pw, ph)
            left = (pw - side) // 2
            top  = max(0, int(ph * 0.05))          # légèrement vers le haut pour centrer le visage
            top  = min(top, ph - side)
            photo = photo.crop((left, top, left + side, top + side))
        except Exception as e:
            print(f"Error opening profile photo: {e}")
            # Robust fallback: grey circle
            photo = Image.new("RGBA", (PHOTO_R * 2, PHOTO_R * 2), (180, 180, 180, 255))

    try:
        photo = photo.resize((PHOTO_R * 2, PHOTO_R * 2), Image.LANCZOS)
        mask  = _circle_mask(PHOTO_R * 2)
        photo.putalpha(mask)
        img.paste(photo, (CX - PHOTO_R, CY - PHOTO_R), photo)
    except Exception as e:
        print(f"Error processing profile photo: {e}")


# ── Logo ─────────────────────────────────────────────────────────────────────

def _remove_bg(img_rgba: Image.Image,
               bg_color=(0, 0, 0), threshold: int = 40) -> Image.Image:
    import numpy as np
    data = np.array(img_rgba, dtype=np.int32)
    br, bg, bb = bg_color
    dist = np.sqrt(
        (data[:,:,0] - br)**2 +
        (data[:,:,1] - bg)**2 +
        (data[:,:,2] - bb)**2
    )
    alpha = np.where(dist < threshold, 0, 255).astype(np.uint8)
    data[:,:,3] = alpha
    return Image.fromarray(data.astype(np.uint8), "RGBA")


def _paste_logo(img: Image.Image, logo_input) -> None:
    if not logo_input:
        return
    try:
        logo = Image.open(logo_input).convert("RGBA")
    except Exception as e:
        print(f"Error opening logo: {e}")
        return

    target_w = 160
    ratio    = target_w / logo.width
    logo     = logo.resize(
        (target_w, int(logo.height * ratio)), Image.LANCZOS
    )
    img.paste(logo, (25, 25), logo)


# ── Texte ─────────────────────────────────────────────────────────────────────

def _draw_text(img: Image.Image,
               nom: str, prenom: str,
               age: int, adresse: str) -> None:
    draw = ImageDraw.Draw(img)

    font_name_large = _get_font(bold=True, size=68)
    font_sub        = _get_font(bold=True, size=28)

    full_name = f"{prenom.upper()} {nom.upper()}"
    draw.text((60, 230), full_name, font=font_name_large, fill=TEAL)

    draw.text((60, 325), f"{prenom} {nom.capitalize()}, {age} ans",
              font=font_sub, fill=TEXT_DARK)
    draw.text((60, 368), adresse, font=font_sub, fill=TEXT_DARK)


# ── Fonction principale ───────────────────────────────────────────────────────

def generate_profile_card(
    nom: str,
    prenom: str,
    age: int,
    adresse: str,
    logo_path,
    profile_photo_path,
    output_path = None,
) -> any:
    """
    Génère la fiche profil. 
    Si `output_path` est un chemin, enregistre l'image.
    Si `output_path` est None, retourne l'objet Image.
    """
    # Canvas de base
    img = Image.new("RGB", (W, H), BG_COLOR)

    # 1. Formes décoratives de fond
    _draw_background_shapes(img)

    # 2. Photo de profil
    _paste_profile_photo(img, profile_photo_path)

    # 3. Logo
    _paste_logo(img, logo_path)

    # 4. Texte
    _draw_text(img, nom, prenom, age, adresse)

    if output_path:
        img.save(output_path, "PNG", optimize=True)
        return output_path
    
    return img
