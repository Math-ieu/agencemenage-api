import hmac
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

MEDIA_SIGNER_SALT = 'agencemenage-media-file-v1'
DEFAULT_MEDIA_SIG_MAX_AGE = 60 * 60 * 72  # 72 heures pour délivrance WhatsApp


def sign_media_path(file_path: str) -> str:
    """Génère une signature horodatée pour un chemin de média privé."""
    cleaned = (file_path or '').strip('/')
    signer = TimestampSigner(salt=MEDIA_SIGNER_SALT)
    return signer.sign(cleaned)


def verify_media_signature(file_path: str, sig: str, max_age: int = DEFAULT_MEDIA_SIG_MAX_AGE) -> bool:
    """Vérifie une signature horodatée de média en temps constant."""
    if not file_path or not sig:
        return False
    cleaned = file_path.strip('/')
    signer = TimestampSigner(salt=MEDIA_SIGNER_SALT)
    try:
        unsigned = signer.unsign(sig, max_age=max_age)
        return hmac.compare_digest(str(unsigned), cleaned)
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return False


def sign_media_url(url: str) -> str:
    """Ajoute ?sig=<token> aux URLs pointant vers /api/media/<path> pour les fetchs externes (ex: 360dialog)."""
    if not url or not isinstance(url, str):
        return url
    parsed = urlsplit(url)
    path = parsed.path or ''
    marker = '/api/media/'
    if marker not in path:
        return url
    rel_path = path.split(marker, 1)[1].strip('/')
    if not rel_path:
        return url
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if 'sig' in query_items:
        return url
    query_items['sig'] = sign_media_path(rel_path)
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query_items),
        parsed.fragment,
    ))
