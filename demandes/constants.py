from .models import Demande

SERVICES_PARTICULIERS = [
    "ménage standard",
    "grand ménage",
    "ménage air bnb",
    "ménage airbnb",
    "ménage fin de chantier",
    "auxiliaire de vie",
    "ménage post-sinistre"
]

def get_segment_from_service(service_name):
    """
    Détermine le segment basé sur le nom du service.
    Plus robuste aux espaces et à la casse.
    """
    if not service_name:
        return Demande.PARTICULIER
        
    normalized = service_name.lower().strip()
    
    if normalized in SERVICES_PARTICULIERS:
        return Demande.PARTICULIER
        
    return Demande.ENTREPRISE
