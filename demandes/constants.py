from .models import Demande

SERVICES_PARTICULIERS = [
    "ménage standard",
    "grand ménage",
    "ménage air bnb",
    "ménage airbnb",
    "ménage fin de chantier",
    "nettoyage fin de chantier",
    "auxiliaire de vie",
    "auxiliaire de vie / garde malade",
    "garde malade",
    "ménage post-sinistre",
    "ménage post-déménagement",
    "post-déménagement",
    "déménagement",
]

def get_segment_from_service(service_name):
    """
    Détermine le segment basé sur le nom du service.
    Plus robuste aux espaces, accents et à la casse.
    """
    if not service_name:
        return Demande.PARTICULIER
        
    normalized = service_name.lower().strip()
    
    # Check for explicit entreprise markers
    if "(entreprise)" in normalized or "entreprise" in normalized or "bureaux" in normalized or "placement" in normalized:
        return Demande.ENTREPRISE
    
    if normalized in SERVICES_PARTICULIERS:
        return Demande.PARTICULIER
    
    for s in SERVICES_PARTICULIERS:
        if s in normalized or normalized in s:
            return Demande.PARTICULIER
        
    return Demande.ENTREPRISE

