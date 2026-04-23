import base64

# Même sel que le frontend pour la cohérence
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
