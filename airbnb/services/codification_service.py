import re
import string
import unicodedata
from django.db import transaction
from clients.models import Client
from ..models import Bien

VILLE_TRIGRAMMES = {
    'casablanca': 'CAS',
    'rabat': 'RAB',
    'marrakech': 'MAR',
    'tanger': 'TAN',
    'agadir': 'AGA',
}


def _clean_ascii_upper(value: str) -> str:
    """Normalise en ASCII majuscule sans accents ni espaces/caractères spéciaux."""
    if not value:
        return ''
    normalized = unicodedata.normalize('NFKD', str(value))
    ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z]', '', ascii_only).upper()


def get_ville_trigramme(ville: str) -> str:
    """Retourne le code ville sur 3 lettres (CAS, RAB, MAR, TAN, AGA ou repli 3 lettres)."""
    if not ville:
        return 'CAS'
    key = unicodedata.normalize('NFKD', str(ville)).encode('ascii', 'ignore').decode('ascii').strip().lower()
    if key in VILLE_TRIGRAMMES:
        return VILLE_TRIGRAMMES[key]
    cleaned = _clean_ascii_upper(ville)
    return (cleaned + 'XXX')[:3]


def _trigramme_collides(candidate: str, client=None) -> bool:
    """Vérifie si le trigramme est déjà utilisé par un autre client ou ses biens."""
    client_qs = Client.objects.filter(trigramme=candidate)
    if client is not None and getattr(client, 'pk', None):
        client_qs = client_qs.exclude(pk=client.pk)
    if client_qs.exists():
        return True

    bien_qs = Bien.objects.filter(code__regex=rf'^{re.escape(candidate)}[0-9]+$')
    if client is not None and getattr(client, 'pk', None):
        bien_qs = bien_qs.exclude(client=client)
    return bien_qs.exists()


def _candidate_trigrammes(client):
    """Génère les trigrammes candidats dans l'ordre exact du Brief §3.1."""
    fn = _clean_ascii_upper(getattr(client, 'first_name', '') or '')
    ln = _clean_ascii_upper(getattr(client, 'last_name', '') or '')
    entity_raw = getattr(client, 'entity_name', '') or ''
    entity_words = [_clean_ascii_upper(w) for w in re.split(r'\s+', entity_raw) if _clean_ascii_upper(w)]
    en = ''.join(entity_words)

    candidates = []

    def _add(c):
        if c and len(c) == 3 and c not in candidates:
            candidates.append(c)

    if fn and ln:
        # Règle principale Brief §3.1 : 1ère lettre Prénom + 2 premières lettres Nom
        if len(ln) >= 2:
            _add(fn[0] + ln[:2])
        else:
            _add((fn[0] + ln + fn[1:] + 'X')[:3])

        # Repli collision Brief §3.1 : 1ère lettre Prénom + 1ère et 3ème lettres Nom
        if len(ln) >= 3:
            _add(fn[0] + ln[0] + ln[2])

        # Replis déterministes additionnels en cas de collisions multiples
        for idx in range(3, len(ln)):
            _add(fn[0] + ln[0] + ln[idx])
        for idx in range(2, len(ln)):
            _add(fn[0] + ln[1] + ln[idx])
        if len(fn) >= 2:
            _add(fn[:2] + ln[0])
        for ch in string.ascii_uppercase + string.digits:
            _add(fn[0] + ln[0] + ch)

    elif en:
        if len(entity_words) >= 2:
            _add((entity_words[0][0] + entity_words[1][:2]).ljust(3, 'X')[:3])
        _add((en + 'BNB')[:3])
        for idx in range(2, len(en)):
            _add(en[0] + en[1] + en[idx])
        for ch in string.ascii_uppercase + string.digits:
            _add((en[:2] if len(en) >= 2 else (en + 'B')) + ch)
    elif fn:
        _add((fn + 'BNB')[:3])
        for ch in string.ascii_uppercase + string.digits:
            _add((fn[:2] if len(fn) >= 2 else (fn + 'B')) + ch)
    else:
        _add('BNB')
        for ch in string.ascii_uppercase + string.digits:
            _add('BN' + ch)

    return candidates


def compute_client_trigramme(client, persist: bool = True) -> str:
    """
    Calcule (et persiste si absent et persist=True) le trigramme immuable du client.
    - Règle standard : 1ère lettre Prénom + 2 premières lettres Nom (ex: Ghali Bensouda -> GBE)
    - En cas de collision : 1ère lettre Prénom + 1ère et 3ème lettres Nom (ex: Ghita Benjelloun -> GBN)
    """
    if client is not None and getattr(client, 'trigramme', None):
        existing = client.trigramme.strip().upper()
        if existing:
            return existing

    candidates = _candidate_trigrammes(client)
    chosen = candidates[0]
    for cand in candidates:
        if not _trigramme_collides(cand, client=client):
            chosen = cand
            break

    if persist and client is not None and getattr(client, 'pk', None) and not client.trigramme:
        with transaction.atomic():
            locked = Client.objects.select_for_update().get(pk=client.pk)
            if locked.trigramme:
                client.trigramme = locked.trigramme
                return locked.trigramme
            locked.trigramme = chosen
            locked.save(update_fields=['trigramme'])
            client.trigramme = chosen

    return chosen


def _next_bien_sequence(client, trigramme: str) -> int:
    """Retourne max(numéro existant) + 1 pour ne jamais réattribuer un code supprimé."""
    max_num = 0

    codes = list(Bien.objects.filter(code__startswith=trigramme).values_list('code', flat=True))
    if client is not None and getattr(client, 'pk', None):
        codes.extend(Bien.objects.filter(client=client).values_list('code', flat=True))

    for code in codes:
        if not code:
            continue
        match = re.search(r'(\d+)$', code)
        if not match:
            continue
        prefix = code[:match.start()]
        if prefix == trigramme or (client is not None and getattr(client, 'pk', None)):
            try:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
            except ValueError:
                continue

    next_num = max_num + 1
    while Bien.objects.filter(code=f"{trigramme}{next_num:03d}").exists():
        next_num += 1
    return next_num


def preview_bien_code(client, ville: str = None) -> str:
    """Prévisualise le prochain code Bien sans muter la base de données."""
    trigramme = compute_client_trigramme(client, persist=False)
    next_num = _next_bien_sequence(client, trigramme)
    return f"{trigramme}{next_num:03d}"


def generate_bien_code(client, ville: str = None) -> str:
    """
    Génère un code de bien unique et pérenne de type TRIGRAMME + 3 CHIFFRES (ex: GBE001).
    Persiste le trigramme immuable sur le client s'il n'est pas encore défini.
    """
    trigramme = compute_client_trigramme(client, persist=True)
    next_num = _next_bien_sequence(client, trigramme)
    return f"{trigramme}{next_num:03d}"
