from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

_HTTP_URL_VALIDATOR = URLValidator(schemes=['http', 'https'])


def validate_safe_media_url(url: str, field_name: str = 'url') -> str:
    """Valide une URL de média/justificatif (chemins relatifs '/' ou http/https uniquement)."""
    if url is None:
        return ''
    cleaned = str(url).strip()
    if not cleaned:
        return ''
    if any(ch in cleaned for ch in ('\r', '\n', '\t', '<', '>')):
        raise ValidationError(f"URL invalide pour {field_name}.")
    if cleaned.startswith('/'):
        if cleaned.startswith('//'):
            raise ValidationError(f"URL relative de protocole non autorisée pour {field_name}.")
        return cleaned
    try:
        _HTTP_URL_VALIDATOR(cleaned)
    except ValidationError:
        raise ValidationError(f"Seules les URLs http(s) ou chemins relatifs sont autorisés pour {field_name}.")
    return cleaned


def validate_safe_proof_text_or_url(value: str, field_name: str = 'accord_preuve') -> str:
    """Valide une preuve d'accord (texte libre ou URL http/https/relative) tout en bloquant javascript:/data:/vbscript:."""
    if value is None:
        return ''
    cleaned = str(value).strip()
    if not cleaned:
        return ''
    compact = ''.join(ch for ch in cleaned.lower() if ord(ch) >= 32 and not ch.isspace())
    if compact.startswith(('javascript:', 'vbscript:', 'data:')):
        raise ValidationError(f"Schéma URI non autorisé pour {field_name}.")
    return cleaned
