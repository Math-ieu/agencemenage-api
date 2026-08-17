from decimal import Decimal
from django.utils import timezone
from ..models import AirbnbConfig, FiletLinge, CommandeAirbnb


def get_airbnb_config() -> AirbnbConfig:
    config = AirbnbConfig.objects.first()
    if not config:
        config = AirbnbConfig.objects.create()
    return config


def calculate_linen_pieces_and_amount(comptage: dict) -> dict:
    """
    Calcule le nombre total de pièces, le nombre de sets (8 pièces),
    les pièces supplémentaires et le montant total en MAD selon la règle métier :
    - 1 Set = 8 pièces = 50 MAD
    - Pièces supplémentaires = 5 MAD / pièce
    - Forfait minimum si présence de linge (total > 0) = 50 MAD
    """
    config = get_airbnb_config()
    
    if not comptage or not isinstance(comptage, dict):
        return {
            'total_pieces': 0,
            'sets_calcules': 0,
            'pieces_supp': 0,
            'montant': 0.0,
        }

    # Somme des pièces de linge
    piece_keys = ['housses', 'draps', 'taies', 'grandes_serviettes', 'petites_serviettes', 'tapis_bain', 'torchons', 'autres']
    total_pieces = 0
    
    # Si total est explicitement renseigné
    if 'total' in comptage and isinstance(comptage['total'], (int, float)) and comptage['total'] > 0:
        total_pieces = int(comptage['total'])
    else:
        for k in piece_keys:
            val = comptage.get(k, 0)
            try:
                total_pieces += int(val or 0)
            except (ValueError, TypeError):
                pass

    if total_pieces == 0:
        return {
            'total_pieces': 0,
            'sets_calcules': 0,
            'pieces_supp': 0,
            'montant': 0.0,
        }

    # Calcul des sets et des pièces supplémentaires
    sets = total_pieces // 8
    pieces_supp = total_pieces % 8
    
    # Calcul du montant brut
    montant_brut = (Decimal(sets) * config.prix_set_linge_standard) + (Decimal(pieces_supp) * config.prix_piece_supp_linge)
    
    # Règle du forfait minimum (50 DH si total_pieces > 0)
    montant_final = max(config.forfait_min_linge, montant_brut)

    return {
        'total_pieces': total_pieces,
        'sets_calcules': sets,
        'pieces_supp': pieces_supp,
        'montant': float(montant_final),
    }


def freeze_laundry_filet(filet: FiletLinge, user=None, comptage_laverie_final: dict = None) -> FiletLinge:
    """
    Fige le montant du linge lors du comptage contradictoire en laverie.
    1. Met à jour le comptage laverie.
    2. Calcule l'écart (Comptage Laverie - Comptage Runner).
    3. Calcule le montant final et fige l'enregistrement.
    4. Répercute le montant sur la commande de ramassage (N-1) et met à jour son total TTC.
    """
    if comptage_laverie_final:
        filet.comptage_laverie = comptage_laverie_final

    calc = calculate_linen_pieces_and_amount(filet.comptage_laverie or filet.comptage_runner)
    filet.total_pieces = calc['total_pieces']
    filet.sets_calcules = calc['sets_calcules']
    filet.pieces_supp_calculees = calc['pieces_supp']
    filet.montant = Decimal(str(calc['montant']))
    
    # Calcul de l'écart
    runner_total = calculate_linen_pieces_and_amount(filet.comptage_runner)['total_pieces']
    filet.ecart = filet.total_pieces - runner_total
    
    filet.montant_fige_le = timezone.now()
    if user and user.is_authenticated:
        filet.fige_par = user
        
    filet.statut = 'pret'
    filet.save()

    # Rapprochement avec la commande de ramassage (N-1)
    if filet.commande_ramassage:
        cmd = filet.commande_ramassage
        cmd.montant_linge = filet.montant
        cmd.total_ttc = (cmd.prix_menage or Decimal(0)) + \
                        (cmd.supplement_zone or Decimal(0)) + \
                        (cmd.prix_options or Decimal(0)) + \
                        (cmd.remise_en_etat or Decimal(0)) + \
                        cmd.montant_linge
        
        # Si un écart non arbitré existe, passer en statut 'ecart_linge'
        if filet.ecart != 0 and not filet.ecart_arbitre:
            cmd.statut = 'ecart_linge'
            
        cmd.save()

    return filet
