from decimal import Decimal
from datetime import datetime, date, time
from django.utils import timezone
from ..models import AirbnbConfig, Bien


def get_airbnb_config() -> AirbnbConfig:
    """Récupère la configuration tarifaire ou crée les valeurs par défaut."""
    config = AirbnbConfig.objects.first()
    if not config:
        config = AirbnbConfig.objects.create()
    return config


def calculate_commande_pricing(bien: Bien, typologie: str = None, options: list = None, remise_en_etat: float = 0.0) -> dict:
    """
    Calcule la décomposition du prix d'une commande / turnover Airbnb.
    
    Règles :
    1. Prix ménage de base selon typologie :
       - Studio / 1ch : 130 MAD
       - 2ch : 160 MAD
       - 3ch : 200 MAD
       - 4ch : 250 MAD
       - 5ch : 300 MAD
       - Villa / Riad : 350 MAD
    2. Supplément Zone Éloignée : +50 MAD si le bien est en zone éloignée.
    3. Options de réassort / consommables souscrites.
    4. Remise en état exceptionnelle.
    """
    config = get_airbnb_config()
    target_typologie = typologie or bien.typologie
    
    # 1. Base ménage
    base_price_map = {
        'studio': config.prix_studio,
        '2ch': config.prix_2ch,
        '3ch': config.prix_3ch,
        '4ch': config.prix_4ch,
        '5ch': config.prix_5ch,
        'villa_riad': config.prix_villa_riad,
    }
    prix_menage = base_price_map.get(target_typologie, config.prix_studio)
    
    # 2. Zone éloignée (+50 DH)
    is_zone_eloignee = bien.zone_eloignee
    if not is_zone_eloignee and bien.quartier:
        # Vérification si le nom du quartier correspond à la liste des zones éloignées
        matching_zones = [z.lower().strip() for z in (config.zones_eloignees_list or [])]
        if bien.quartier.lower().strip() in matching_zones:
            is_zone_eloignee = True

    supplement_zone = config.supplement_zone_eloignee if is_zone_eloignee else Decimal('0.00')
    
    # 3. Total options
    prix_options = Decimal('0.00')
    if options and isinstance(options, list):
        for opt in options:
            if isinstance(opt, dict) and 'prix' in opt:
                try:
                    prix_options += Decimal(str(opt['prix']))
                except Exception:
                    pass
                    
    # 4. Remise en état
    try:
        remise_en_etat_dec = Decimal(str(remise_en_etat or 0))
    except Exception:
        remise_en_etat_dec = Decimal('0.00')
        
    total_ttc_hors_linge = prix_menage + supplement_zone + prix_options + remise_en_etat_dec
    
    return {
        'typologie': target_typologie,
        'prix_menage': float(prix_menage),
        'is_zone_eloignee': is_zone_eloignee,
        'supplement_zone': float(supplement_zone),
        'prix_options': float(prix_options),
        'remise_en_etat': float(remise_en_etat_dec),
        'total_ttc_hors_linge': float(total_ttc_hors_linge),
    }


def check_cutoff_constraint(date_prestation: date, heure_prestation: time = None, creneau: str = 'matin') -> dict:
    """
    Contrôle le respect des créneaux de coupure (Cut-off) :
    - Intervention Matin (avant 12h) : Saisie autorisée jusqu'à 21h00 la veille (J-1).
    - Intervention Après-midi (après 12h) : Saisie autorisée jusqu'à 22h00 la veille (J-1).
    """
    config = get_airbnb_config()
    now = timezone.now()
    today = now.date()
    
    is_matin = creneau == 'matin' or (heure_prestation and heure_prestation.hour < 12)
    cutoff_time = config.cutoff_matin if is_matin else config.cutoff_apres_midi
    
    # Si la prestation est pour aujourd'hui ou dans le passé
    if date_prestation < today:
        return {
            'is_valid': False,
            'is_late': True,
            'message': 'La date demandée est déjà passée.',
            'cutoff_time': str(cutoff_time)
        }
        
    if date_prestation == today:
        return {
            'is_valid': False,
            'is_late': True,
            'message': f"Commande le jour même hors délai cut-off ({cutoff_time.strftime('%H:%M')} J-1). Soumise à validation manuelle de l'exploitation.",
            'cutoff_time': str(cutoff_time)
        }
        
    # Si la prestation est pour demain (J+1)
    if (date_prestation - today).days == 1:
        current_time = now.time()
        if current_time > cutoff_time:
            return {
                'is_valid': False,
                'is_late': True,
                'message': f"Heure limite dépassée ({cutoff_time.strftime('%H:%M')} la veille pour les interventions {creneau}). Commande tardive soumise à dérogation.",
                'cutoff_time': str(cutoff_time)
            }

    return {
        'is_valid': True,
        'is_late': False,
        'message': 'Créneau d\'intervention conforme aux règles de cut-off.',
        'cutoff_time': str(cutoff_time)
    }
