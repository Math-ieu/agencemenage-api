import base64
import re
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

FEEDBACK_TOKEN_SALT = 'agencemenage-feedback-v2'
FEEDBACK_TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours
_PURE_NUMERIC_RE = re.compile(r'^-?\d+(?:[.,]\d+)?$')


def sanitize_csv_cell(value) -> str:
    """Neutralise les formules Excel/LibreOffice (=, +, -, @, tab, CR) tout en préservant les nombres purs."""
    text = str(value if value is not None else '')
    if not text:
        return text
    stripped = text.strip()
    if stripped and text[0] in ('=', '+', '-', '@', '\t', '\r'):
        if not _PURE_NUMERIC_RE.fullmatch(stripped):
            return "'" + text
    return text


def generate_feedback_token(demande_id: int) -> str:
    """Génère un jeton signé horodaté pour soumettre un avis client sans exposer l'ID entier."""
    signer = TimestampSigner(salt=FEEDBACK_TOKEN_SALT)
    return signer.sign(str(int(demande_id)))


def verify_feedback_token(token: str, max_age: int = FEEDBACK_TOKEN_MAX_AGE):
    """Vérifie et décode un jeton de feedback signé ; retourne l'ID de demande ou None."""
    if not token or not isinstance(token, str):
        return None
    signer = TimestampSigner(salt=FEEDBACK_TOKEN_SALT)
    try:
        unsigned = signer.unsign(token.strip(), max_age=max_age)
        return int(unsigned)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


# Conservés pour les URLs internes du back-office uniquement (ne plus utiliser sur des endpoints publics)
SALT = "am_secure_2026"

def encode_id(id_val):
    """Encode un ID numérique en chaîne obfusquée (compatible avec le frontend)."""
    if id_val is None:
        return ""
    s = f"{id_val}:{SALT}"
    # Base64 standard
    encoded = base64.b64encode(s.encode()).decode()
    # Remplacement pour rendre l'URL sûre (comme btoa en JS)
    return encoded.replace('=', '').replace('/', '_').replace('+', '-')

def decode_id(code):
    """Décode une chaîne obfusquée en ID numérique."""
    if not code:
        return None
    try:
        # Rétablissement du format Base64 standard
        normalized = code.replace('_', '/').replace('-', '+')
        normalized += "=" * ((4 - len(normalized) % 4) % 4)
        decoded = base64.b64decode(normalized.encode()).decode()
        
        parts = decoded.split(':')
        if len(parts) == 2:
            id_str, salt = parts
            if salt == SALT:
                return int(id_str)
    except Exception:
        pass
    return None
