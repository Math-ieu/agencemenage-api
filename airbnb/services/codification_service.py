import re
from ..models import Bien


def generate_trigramme(client) -> str:
    """
    Génère un trigramme de 3 lettres majuscules à partir du client :
    1. Si entity_name (conciergerie / société) : prend les 3 premières lettres significatives
    2. Sinon (particulier) : prend les 3 premières lettres du nom de famille ou combinaison prénom/nom
    """
    base_text = ""
    if hasattr(client, 'entity_name') and client.entity_name:
        base_text = client.entity_name
    elif hasattr(client, 'last_name') and client.last_name:
        base_text = f"{client.last_name}{client.first_name or ''}"
    elif hasattr(client, 'first_name') and client.first_name:
        base_text = client.first_name
    else:
        base_text = "BNB"

    # Nettoyer les caractères spéciaux et accents
    clean_text = re.sub(r'[^A-Za-z]', '', base_text).upper()
    if len(clean_text) < 3:
        clean_text = (clean_text + "BNB")[:3]
    else:
        clean_text = clean_text[:3]
        
    return clean_text


def generate_bien_code(client) -> str:
    """
    Génère un code de bien unique et pérenne de type TRIGRAMME + 3 CHIFFRES (ex: GBE001).
    Le code n'est jamais réassigné même si un bien est supprimé/archivé.
    """
    trigramme = generate_trigramme(client)
    
    # Chercher les codes existants commençant par ce trigramme
    existing_codes = Bien.objects.filter(code__startswith=trigramme).values_list('code', flat=True)
    
    max_num = 0
    for c in existing_codes:
        try:
            num_part = int(c[len(trigramme):])
            if num_part > max_num:
                max_num = num_part
        except (ValueError, IndexError):
            continue

    next_num = max_num + 1
    new_code = f"{trigramme}{next_num:03d}"
    
    # Double sécurité d'unicité
    while Bien.objects.filter(code=new_code).exists():
        next_num += 1
        new_code = f"{trigramme}{next_num:03d}"
        
    return new_code
