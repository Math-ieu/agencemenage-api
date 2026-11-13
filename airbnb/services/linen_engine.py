from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..models import AirbnbConfig, CommandeAirbnb, FiletLinge, JournalAuditAirbnb, ObservationLinge

_ITEM_ALIASES = {
    'housse': 'housses',
    'housses': 'housses',
    'housses_couette': 'housses',
    'drap': 'draps',
    'draps': 'draps',
    'draps_plats': 'draps',
    'taie': 'taies',
    'taies': 'taies',
    'taies_oreiller': 'taies',
    'grande_serviette': 'grandes_serviettes',
    'grandes_serviettes': 'grandes_serviettes',
    'serviette_grande': 'grandes_serviettes',
    'serviettes_grandes': 'grandes_serviettes',
    'serviettes_gdes': 'grandes_serviettes',
    'gdes_serviettes': 'grandes_serviettes',
    'petite_serviette': 'petites_serviettes',
    'petites_serviettes': 'petites_serviettes',
    'serviette_petite': 'petites_serviettes',
    'serviettes_petites': 'petites_serviettes',
    'serviettes_ptes': 'petites_serviettes',
    'ptes_serviettes': 'petites_serviettes',
    'tapis': 'tapis_bain',
    'tapis_bain': 'tapis_bain',
    'torchon': 'torchons',
    'torchons': 'torchons',
    'peignoir': 'peignoirs',
    'peignoirs': 'peignoirs',
    'drap_housse': 'drap_housse',
    'draps_housse': 'drap_housse',
    'couverture': 'couvertures',
    'couvertures': 'couvertures',
    'autre': 'autres',
    'autres': 'autres',
}
_META_KEYS = {
    'total', 'note', 'commentaire', 'hors_set_libelle', 'libelle_autre',
    'remplissage_pct', 'necessite_second_filet', 'photo_ramassage',
    'motif_ecart', 'notes', 'filet_id', 'commande_id',
    'comptage_runner', 'comptage_laverie', 'base_retenue',
}

KNOWN_ARTICLE_KEYS = set(_ITEM_ALIASES.values())


def get_airbnb_config() -> AirbnbConfig:
    config = AirbnbConfig.objects.first()
    if not config:
        config = AirbnbConfig.objects.create()
    return config


def normalize_comptage(comptage: dict, strict_known_only: bool = False) -> dict:
    """Normalise les clés d'un dictionnaire de comptage d'articles en clés canoniques."""
    if not comptage or not isinstance(comptage, dict):
        return {}
    normalized = {}
    for raw_key, raw_val in comptage.items():
        if isinstance(raw_val, bool):
            continue
        key_lower = str(raw_key).strip().lower()
        if key_lower in _META_KEYS:
            continue
        canon = _ITEM_ALIASES.get(key_lower, key_lower)
        if strict_known_only and canon not in KNOWN_ARTICLE_KEYS:
            continue
        try:
            qty = int(raw_val or 0)
        except (ValueError, TypeError):
            continue
        if qty < 0:
            raise ValidationError(f"La quantité de l'article '{raw_key}' ne peut pas être négative.")
        if qty > 0:
            normalized[canon] = normalized.get(canon, 0) + qty
    return normalized


def calculate_linen_pieces_and_amount(comptage: dict, config: AirbnbConfig = None) -> dict:
    """
    Conversion exacte pièces -> sets (Brief §5.3–§5.5) :
    - sets = min(floor(quantité[article] / requis[article])) sur les 5 articles du set
    - pièces_supp = total_pièces - sets * taille_set (8 par défaut)
    - montant = sets * 50 DH + pièces_supp * 5 DH
    - minimum = 50 DH si total_pièces > 0 et montant < 50 DH ; 0 DH si total_pièces == 0
    - Retourne également l'article limitant pour l'interface runner.
    """
    cfg = config or get_airbnb_config()
    set_comp = cfg.set_composition_standard or {
        'housses': 1,
        'draps': 1,
        'taies': 2,
        'grandes_serviettes': 2,
        'petites_serviettes': 2,
    }
    set_size = sum(int(v) for v in set_comp.values() if int(v) > 0) or 8

    if not comptage or not isinstance(comptage, dict):
        return {
            'total_pieces': 0,
            'sets_calcules': 0,
            'nb_sets_complets': 0,
            'pieces_supp': 0,
            'nb_pieces_hors_set': 0,
            'montant': 0.0,
            'montant_total': 0.0,
            'montant_brut': 0.0,
            'minimum_applique': False,
            'forfait_minimum_applique': False,
            'article_limitant': None,
            'articles_limitants': [],
            'manque_prochain_set': {},
            'details_articles': {},
        }

    items = normalize_comptage(comptage)

    prix_set = Decimal(str(cfg.prix_set_linge_standard))
    prix_piece = Decimal(str(cfg.prix_piece_supp_linge))
    forfait_min = Decimal(str(cfg.forfait_min_linge))

    # Repli legacy si seul 'total' est fourni sans détail par article
    if not items and isinstance(comptage.get('total'), (int, float)) and comptage['total'] > 0:
        total_pieces = int(comptage['total'])
        sets = total_pieces // set_size
        pieces_supp = total_pieces % set_size
        montant_brut = (Decimal(sets) * prix_set) + (Decimal(pieces_supp) * prix_piece)
        montant_final = max(forfait_min, montant_brut)
        min_app = montant_brut < forfait_min
        return {
            'total_pieces': total_pieces,
            'sets_calcules': sets,
            'nb_sets_complets': sets,
            'pieces_supp': pieces_supp,
            'nb_pieces_hors_set': pieces_supp,
            'montant': float(montant_final),
            'montant_total': float(montant_final),
            'montant_brut': float(montant_brut),
            'minimum_applique': min_app,
            'forfait_minimum_applique': min_app,
            'article_limitant': None,
            'articles_limitants': [],
            'manque_prochain_set': {},
            'details_articles': {'total': total_pieces},
        }

    total_pieces = sum(items.values())
    if total_pieces == 0:
        return {
            'total_pieces': 0,
            'sets_calcules': 0,
            'nb_sets_complets': 0,
            'pieces_supp': 0,
            'nb_pieces_hors_set': 0,
            'montant': 0.0,
            'montant_total': 0.0,
            'montant_brut': 0.0,
            'minimum_applique': False,
            'forfait_minimum_applique': False,
            'article_limitant': None,
            'articles_limitants': [],
            'manque_prochain_set': {},
            'details_articles': {},
        }

    ratios = {}
    for article, req in set_comp.items():
        req_int = int(req or 0)
        if req_int > 0:
            ratios[article] = items.get(article, 0) // req_int

    sets = min(ratios.values()) if ratios else 0
    articles_limitants = [art for art, r in ratios.items() if r == sets]
    manque_prochain_set = {}
    next_set_target = sets + 1
    for art in articles_limitants:
        req_int = int(set_comp[art])
        manque_prochain_set[art] = max(0, next_set_target * req_int - items.get(art, 0))

    pieces_supp = max(0, total_pieces - (sets * set_size))
    montant_brut = (Decimal(sets) * prix_set) + (Decimal(pieces_supp) * prix_piece)
    minimum_applique = montant_brut < forfait_min
    montant_final = max(forfait_min, montant_brut)

    return {
        'total_pieces': total_pieces,
        'sets_calcules': sets,
        'nb_sets_complets': sets,
        'pieces_supp': pieces_supp,
        'nb_pieces_hors_set': pieces_supp,
        'montant': float(montant_final),
        'montant_total': float(montant_final),
        'montant_brut': float(montant_brut),
        'minimum_applique': minimum_applique,
        'forfait_minimum_applique': minimum_applique,
        'article_limitant': articles_limitants[0] if articles_limitants else None,
        'articles_limitants': articles_limitants,
        'manque_prochain_set': manque_prochain_set,
        'details_articles': items,
    }


def _recompute_commande_linge(commande: CommandeAirbnb):
    """Recalcule montant_linge et total_ttc sur la commande de ramassage uniquement."""
    if not commande:
        return
    filets = commande.filets_ramasses.all()
    total_filets = sum((f.montant or Decimal('0.00')) for f in filets)
    total_obs = sum(
        (obs.montant_facture or Decimal('0.00'))
        for f in filets
        for obs in f.observations.filter(facturee=True)
    )
    commande.montant_linge = total_filets + total_obs
    commande.total_ttc = (
        (commande.prix_menage or Decimal('0.00'))
        + (commande.supplement_zone or Decimal('0.00'))
        + (commande.prix_options or Decimal('0.00'))
        + (commande.remise_en_etat or Decimal('0.00'))
        + commande.montant_linge
    )
    commande.save(update_fields=['montant_linge', 'total_ttc', 'updated_at'])


def confirmer_retrait_bureau(filet: FiletLinge, user) -> FiletLinge:
    """Moment 1 : Le runner confirme le retrait du filet au bureau avant sa tournée."""
    filet.retire_bureau_confirme_par = user if (user and getattr(user, 'is_authenticated', False)) else None
    filet.retire_bureau_confirme_le = timezone.now()
    filet.retire_bureau_conteste = False
    filet.statut = 'remis_runner'
    filet.save()

    JournalAuditAirbnb.objects.create(
        entite='FiletLinge',
        entite_id=str(filet.id),
        action='confirmation_retrait_bureau',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        valeur_apres={'statut': filet.statut, 'retire_bureau_confirme_le': filet.retire_bureau_confirme_le.isoformat()},
    )
    return filet


def contester_retrait_bureau(filet: FiletLinge, nb_conteste: int, motif: str, user) -> FiletLinge:
    """Moment 1 : Le runner conteste le nombre annoncé au retrait au bureau -> arbitrage."""
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif de contestation est obligatoire.")
    filet.retire_bureau_conteste = True
    filet.retire_bureau_nb_conteste = nb_conteste
    filet.motif_ecart = str(motif).strip()
    filet.ecart_arbitre = False
    filet.save()

    JournalAuditAirbnb.objects.create(
        entite='FiletLinge',
        entite_id=str(filet.id),
        action='contestation_retrait_bureau',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        motif=str(motif).strip(),
        valeur_apres={'nb_conteste': nb_conteste, 'retire_bureau_conteste': True},
    )

    from .notification_service import notify_contestation_bureau
    notify_contestation_bureau(filet, str(motif).strip())
    return filet


def compter_runner(
    filet: FiletLinge,
    comptage_runner: dict,
    user=None,
    photo_ramassage: str = '',
    remplissage_pct: int = 50,
    necessite_second_filet: bool = False,
) -> dict:
    """
    Moment 2 : Saisie du comptage article par article par le runner chez le client.
    Annonce le montant prévisionnel et vérifie le seuil de remplissage 60%.
    """
    if filet.montant_fige_le is not None:
        raise ValidationError("Impossible de modifier le comptage : le montant de ce filet est déjà figé.")

    cfg = get_airbnb_config()
    normalized = normalize_comptage(comptage_runner)
    calc = calculate_linen_pieces_and_amount(normalized or comptage_runner, config=cfg)

    filet.comptage_runner = normalized or comptage_runner
    if photo_ramassage:
        filet.photo_ramassage = photo_ramassage
    filet.remplissage_pct = int(remplissage_pct or 50)
    filet.necessite_second_filet = bool(necessite_second_filet or filet.remplissage_pct > (cfg.remplissage_max_filet_pct or 60))
    filet.total_pieces = calc['total_pieces']
    filet.sets_calcules = calc['sets_calcules']
    filet.pieces_supp_calculees = calc['pieces_supp']
    filet.montant = Decimal(str(calc['montant']))
    filet.statut = 'compte_runner'
    if not filet.code_filet and filet.bien:
        existing_cnt = FiletLinge.objects.filter(bien=filet.bien).exclude(pk=filet.pk).count() + 1
        filet.code_filet = f"SAC-{filet.bien.code}-{existing_cnt:02d}"
    filet.save()

    is_first_passage = not FiletLinge.objects.filter(bien=filet.bien).exclude(pk=filet.pk).exists()
    return {
        'filet': filet,
        'calcul': calc,
        'total_runner': calc['total_pieces'],
        'premier_passage_bien': is_first_passage,
        'alerte_second_filet': filet.necessite_second_filet,
        'necessite_second_filet': filet.necessite_second_filet,
    }


def _detect_discrepancy(runner_dict: dict, laverie_dict: dict, tolerance: int = 0) -> dict:
    """Compare comptage runner et comptage laverie (tolérance 0 par défaut)."""
    r_norm = normalize_comptage(runner_dict)
    l_norm = normalize_comptage(laverie_dict)

    r_total = sum(r_norm.values()) if r_norm else int((runner_dict or {}).get('total', 0) or 0)
    l_total = sum(l_norm.values()) if l_norm else int((laverie_dict or {}).get('total', 0) or 0)
    ecart_total = l_total - r_total

    diffs = {}
    if r_norm and l_norm:
        all_keys = sorted(set(r_norm.keys()) | set(l_norm.keys()))
        for k in all_keys:
            d = l_norm.get(k, 0) - r_norm.get(k, 0)
            if d != 0:
                diffs[k] = {'runner': r_norm.get(k, 0), 'laverie': l_norm.get(k, 0), 'ecart': d}

    has_discrepancy = abs(ecart_total) > tolerance or (bool(diffs) and tolerance == 0)
    return {
        'runner_total': r_total,
        'laverie_total': l_total,
        'ecart_total': ecart_total,
        'article_diffs': diffs,
        'has_discrepancy': has_discrepancy,
    }


def recevoir_laverie(filet: FiletLinge, comptage_laverie: dict, user=None, motif_ecart: str = '') -> dict:
    """
    Moment 3 (Réception & Recomptage à la laverie) :
    Contrôle à tolérance 0 par rapport au comptage runner.
    Si écart détecté, bloque la facturation et déclenche une alerte.
    """
    if filet.montant_fige_le is not None:
        raise ValidationError("Le montant de ce filet est déjà figé et ne peut plus être modifié.")

    cfg = get_airbnb_config()
    normalized = normalize_comptage(comptage_laverie)
    filet.comptage_laverie = normalized or comptage_laverie
    filet.statut = 'en_laverie'

    discrepancy = _detect_discrepancy(
        filet.comptage_runner or {},
        filet.comptage_laverie or {},
        tolerance=cfg.ecart_tolere_pieces,
    )
    filet.ecart = discrepancy['ecart_total']
    if discrepancy['has_discrepancy']:
        filet.ecart_arbitre = False
        if motif_ecart:
            filet.motif_ecart = motif_ecart
        elif discrepancy['article_diffs']:
            filet.motif_ecart = f"Écart détecté au recomptage : {discrepancy['article_diffs']}"
        else:
            filet.motif_ecart = f"Écart de {discrepancy['ecart_total']} pièce(s) entre runner et laverie."
        filet.save()

        if filet.commande_ramassage:
            filet.commande_ramassage.statut = 'ecart_linge'
            filet.commande_ramassage.save(update_fields=['statut', 'updated_at'])

        JournalAuditAirbnb.objects.create(
            entite='FiletLinge',
            entite_id=str(filet.id),
            action='ecart_linge_detecte',
            user=user if (user and getattr(user, 'is_authenticated', False)) else None,
            motif=filet.motif_ecart,
            valeur_avant={'comptage_runner': filet.comptage_runner},
            valeur_apres={'comptage_laverie': filet.comptage_laverie, 'ecart': filet.ecart},
        )
        from .notification_service import notify_ecart_linge
        notify_ecart_linge(filet)
    else:
        filet.save()

    return {
        'filet': filet,
        'discrepancy': discrepancy,
        'ecart_detecte': discrepancy['has_discrepancy'],
        'ecart': discrepancy['ecart_total'],
    }


def freeze_laundry_filet(filet: FiletLinge, user=None, comptage_laverie_final: dict = None) -> FiletLinge:
    """
    Fige le montant du linge une seule fois lors du recomptage contradictoire en laverie.
    - Interdit tout re-figeage si montant_fige_le est déjà renseigné.
    - Bloque le figeage si un écart existe et n'a pas encore été arbitré.
    - Facture uniquement sur commande_ramassage (jamais sur commande_depot).
    """
    if filet.montant_fige_le is not None:
        raise ValidationError("Le montant de ce filet est déjà figé et ne peut plus être recalculé.")

    cfg = get_airbnb_config()
    if comptage_laverie_final:
        normalized = normalize_comptage(comptage_laverie_final)
        filet.comptage_laverie = normalized or comptage_laverie_final

    source_comptage = filet.comptage_laverie or filet.comptage_runner or {}
    if filet.comptage_runner and filet.comptage_laverie:
        discrepancy = _detect_discrepancy(
            filet.comptage_runner,
            filet.comptage_laverie,
            tolerance=cfg.ecart_tolere_pieces,
        )
        filet.ecart = discrepancy['ecart_total']
        if discrepancy['has_discrepancy'] and not filet.ecart_arbitre:
            filet.statut = 'en_laverie'
            filet.motif_ecart = filet.motif_ecart or f"Écart de {filet.ecart} pièce(s) bloquant le figeage."
            filet.save()
            if filet.commande_ramassage:
                filet.commande_ramassage.statut = 'ecart_linge'
                filet.commande_ramassage.save(update_fields=['statut', 'updated_at'])
            from .notification_service import notify_ecart_linge
            notify_ecart_linge(filet)
            raise ValidationError(
                f"Écart de {filet.ecart} pièce(s) détecté entre le runner et la laverie. "
                "Arbitrage requis avant de figer le montant."
            )

    calc = calculate_linen_pieces_and_amount(source_comptage, config=cfg)
    filet.total_pieces = calc['total_pieces']
    filet.sets_calcules = calc['sets_calcules']
    filet.pieces_supp_calculees = calc['pieces_supp']
    filet.montant = Decimal(str(calc['montant']))
    filet.montant_fige_le = timezone.now()
    if user and getattr(user, 'is_authenticated', False):
        filet.fige_par = user
    if filet.statut == 'compte_runner':
        filet.statut = 'en_laverie'
    filet.save()

    JournalAuditAirbnb.objects.create(
        entite='FiletLinge',
        entite_id=str(filet.id),
        action='figeage_montant_linge',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        valeur_apres={
            'total_pieces': filet.total_pieces,
            'sets_calcules': filet.sets_calcules,
            'pieces_supp_calculees': filet.pieces_supp_calculees,
            'montant': str(filet.montant),
        },
    )

    if filet.commande_ramassage:
        _recompute_commande_linge(filet.commande_ramassage)

    return filet


def arbitrer_ecart_filet(filet: FiletLinge, commentaire: str, user, base_retenue: str = 'laverie') -> FiletLinge:
    """
    Arbitre un écart de comptage linge (erreur comptage runner vs perte en transport).
    Débloque la commande si elle était en 'ecart_linge'.
    """
    if not commentaire or not str(commentaire).strip():
        raise ValidationError("Le commentaire d'arbitrage est obligatoire.")

    filet.ecart_arbitre = True
    filet.ecart_commentaire = str(commentaire).strip()
    if base_retenue == 'runner' and filet.comptage_runner and filet.montant_fige_le is None:
        filet.comptage_laverie = dict(filet.comptage_runner)
        filet.ecart = 0
    filet.save()

    JournalAuditAirbnb.objects.create(
        entite='FiletLinge',
        entite_id=str(filet.id),
        action='arbitrage_ecart_linge',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        motif=filet.ecart_commentaire,
        valeur_apres={'base_retenue': base_retenue, 'ecart': filet.ecart, 'ecart_arbitre': True},
    )

    if filet.commande_ramassage and filet.commande_ramassage.statut == 'ecart_linge':
        filet.commande_ramassage.statut = 'cloturee'
        filet.commande_ramassage.save(update_fields=['statut', 'updated_at'])

    return filet


def toggle_observation_facturation(
    observation: ObservationLinge,
    facturee: bool,
    montant_facture=None,
    user=None,
) -> ObservationLinge:
    """
    Active ou désactive pièce par pièce la facturation d'une observation de linge abîmé/taché.
    Règle : la pièce n'est JAMAIS retirée du filet.
    """
    observation.facturee = bool(facturee)
    if observation.facturee:
        if montant_facture is not None:
            observation.montant_facture = Decimal(str(montant_facture))
        elif observation.montant_facture and Decimal(str(observation.montant_facture)) > 0:
            observation.montant_facture = Decimal(str(observation.montant_facture))
        else:
            cfg = get_airbnb_config()
            unit_tarif = Decimal(str(cfg.prix_piece_supp_linge or Decimal('5.00')))
            observation.montant_facture = unit_tarif * Decimal(str(observation.quantite or 1))
    else:
        observation.montant_facture = Decimal('0.00')
    observation.save(update_fields=['facturee', 'montant_facture'])

    JournalAuditAirbnb.objects.create(
        entite='ObservationLinge',
        entite_id=str(observation.id),
        action='toggle_facturation_observation',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        valeur_apres={'facturee': observation.facturee, 'montant_facture': str(observation.montant_facture)},
    )

    if observation.filet and observation.filet.commande_ramassage:
        cmd = observation.filet.commande_ramassage
        if cmd.statut != 'facturee':
            _recompute_commande_linge(cmd)

    return observation


def transmettre_observation_client(
    observation: ObservationLinge,
    message_commercial: str = '',
    user=None,
) -> ObservationLinge:
    """Transmet l'observation sur le linge au client (avec message commercial éditable)."""
    if message_commercial:
        observation.message_commercial = message_commercial
    observation.notifie_client_le = timezone.now()
    observation.save(update_fields=['message_commercial', 'notifie_client_le'])

    from .notification_service import notify_linge_abime_client
    notify_linge_abime_client(observation, custom_message=observation.message_commercial)
    return observation
