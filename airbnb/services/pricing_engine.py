import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from ..models import AirbnbConfig, Bien, CommandeAirbnb, GrilleTarifaireVersion, JournalAuditAirbnb


def _norm_text(val: str) -> str:
    if not val:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(val))
    return nfkd.encode('ascii', 'ignore').decode('ascii').strip().lower()


def _parse_time(val) -> time:
    if isinstance(val, time):
        return val
    if isinstance(val, str) and val.strip():
        parts = val.strip().split(':')
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    return time(11, 0)


def get_airbnb_config() -> AirbnbConfig:
    """Récupère la configuration tarifaire ou crée les valeurs par défaut (Maquette p.25)."""
    config = AirbnbConfig.objects.first()
    if not config:
        config = AirbnbConfig.objects.create()
    return config


def build_config_snapshot(config: AirbnbConfig) -> dict:
    return {
        'prix_studio': str(config.prix_studio),
        'prix_1ch': str(config.prix_1ch),
        'prix_2ch': str(config.prix_2ch),
        'prix_3ch': str(config.prix_3ch),
        'prix_4ch': str(config.prix_4ch),
        'prix_5ch': str(config.prix_5ch),
        'prix_villa_riad': str(config.prix_villa_riad),
        'seuil_biens_conciergerie': config.seuil_biens_conciergerie,
        'tarif_repli_standard': str(config.tarif_repli_standard),
        'supplement_zone_eloignee': str(config.supplement_zone_eloignee),
        'zones_eloignees_list': list(config.zones_eloignees_list or []),
        'prix_reassort_essentiel': str(config.prix_reassort_essentiel),
        'prix_reassort_confort': str(config.prix_reassort_confort),
        'prix_video': str(config.prix_video),
        'prix_materiel': str(config.prix_materiel),
        'tarif_remise_en_etat_heure': str(config.tarif_remise_en_etat_heure),
        'prix_set_linge_standard': str(config.prix_set_linge_standard),
        'prix_piece_supp_linge': str(config.prix_piece_supp_linge),
        'forfait_min_linge': str(config.forfait_min_linge),
        'set_composition_standard': dict(config.set_composition_standard or {}),
    }


def build_tarifs_json(config: AirbnbConfig) -> dict:
    return {
        'studio': float(config.prix_studio),
        '1ch': float(config.prix_1ch),
        '2ch': float(config.prix_2ch),
        '3ch': float(config.prix_3ch),
        '4ch': float(config.prix_4ch),
        '5ch': float(config.prix_5ch),
        'villa_riad': float(config.prix_villa_riad),
    }


def ensure_initial_grille_version() -> GrilleTarifaireVersion:
    """Crée une version v1 initiale à partir d'AirbnbConfig si aucune grille versionnée n'existe."""
    existing = GrilleTarifaireVersion.objects.first()
    if existing:
        return existing
    config = get_airbnb_config()
    today = timezone.localdate()
    return GrilleTarifaireVersion.objects.create(
        version_label=today.strftime('%Y-%m-%d'),
        date_entree_vigueur=today,
        is_active=True,
        tarifs_json=build_tarifs_json(config),
        intervenantes_json=dict(config.intervenantes_par_typologie or {}),
        config_snapshot=build_config_snapshot(config),
    )


def get_active_grille_version(target_date: date = None):
    """
    Retourne la version de grille tarifaire applicable à `target_date` (ou aujourd'hui).
    Retourne None si aucune version n'a été créée explicitement (usage de AirbnbConfig direct).
    """
    if not GrilleTarifaireVersion.objects.exists():
        return None
    ref_date = target_date or timezone.localdate()
    version = (
        GrilleTarifaireVersion.objects.filter(date_entree_vigueur__lte=ref_date)
        .order_by('-date_entree_vigueur', '-created_at')
        .first()
    )
    if version:
        return version
    return GrilleTarifaireVersion.objects.filter(is_active=True).first() or GrilleTarifaireVersion.objects.first()


def sync_config_from_grille(version: GrilleTarifaireVersion):
    """Synchronise AirbnbConfig lorsque la nouvelle grille devient active."""
    config = get_airbnb_config()
    tarifs = version.tarifs_json or {}
    field_map = {
        'studio': 'prix_studio',
        '1ch': 'prix_1ch',
        '2ch': 'prix_2ch',
        '3ch': 'prix_3ch',
        '4ch': 'prix_4ch',
        '5ch': 'prix_5ch',
        'villa_riad': 'prix_villa_riad',
    }
    for key, attr in field_map.items():
        if key in tarifs and tarifs[key] is not None:
            setattr(config, attr, Decimal(str(tarifs[key])))
    if version.intervenantes_json:
        config.intervenantes_par_typologie = version.intervenantes_json

    snap = version.config_snapshot or {}
    decimal_snap_fields = [
        'tarif_repli_standard', 'supplement_zone_eloignee', 'prix_reassort_essentiel',
        'prix_reassort_confort', 'prix_video', 'prix_materiel', 'tarif_remise_en_etat_heure',
        'prix_set_linge_standard', 'prix_piece_supp_linge', 'forfait_min_linge',
    ]
    for f in decimal_snap_fields:
        if f in snap and snap[f] is not None:
            setattr(config, f, Decimal(str(snap[f])))
    if 'seuil_biens_conciergerie' in snap and snap['seuil_biens_conciergerie'] is not None:
        config.seuil_biens_conciergerie = int(snap['seuil_biens_conciergerie'])
    if 'zones_eloignees_list' in snap and isinstance(snap['zones_eloignees_list'], list):
        config.zones_eloignees_list = snap['zones_eloignees_list']
    if 'set_composition_standard' in snap and isinstance(snap['set_composition_standard'], dict):
        config.set_composition_standard = snap['set_composition_standard']
    config.save()
    return config


def create_grille_tarifaire_version(
    version_label: str = None,
    date_entree_vigueur: date = None,
    tarifs_json: dict = None,
    intervenantes_json: dict = None,
    config_snapshot: dict = None,
    user=None,
) -> GrilleTarifaireVersion:
    """Crée une nouvelle version datée de la grille tarifaire sans jamais écraser l'historique."""
    config = get_airbnb_config()
    eff_date = date_entree_vigueur or timezone.localdate()
    label = version_label or eff_date.strftime('%Y-%m-%d')

    merged_tarifs = build_tarifs_json(config)
    if tarifs_json:
        for k, v in tarifs_json.items():
            if v is not None:
                merged_tarifs[k] = float(v)

    merged_interv = dict(config.intervenantes_par_typologie or {})
    if intervenantes_json:
        merged_interv.update(intervenantes_json)

    merged_snap = build_config_snapshot(config)
    if config_snapshot:
        merged_snap.update(config_snapshot)

    is_now_active = eff_date <= timezone.localdate()
    if is_now_active:
        GrilleTarifaireVersion.objects.filter(is_active=True).update(is_active=False)

    version = GrilleTarifaireVersion.objects.create(
        version_label=label,
        date_entree_vigueur=eff_date,
        is_active=is_now_active,
        tarifs_json=merged_tarifs,
        intervenantes_json=merged_interv,
        config_snapshot=merged_snap,
        created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
    )
    if is_now_active:
        sync_config_from_grille(version)

    JournalAuditAirbnb.objects.create(
        entite='GrilleTarifaireVersion',
        entite_id=str(version.id),
        action='creation_version_grille',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        motif=f"Nouvelle grille {label} effective au {eff_date}",
        valeur_apres={
            'version_label': label,
            'date_entree_vigueur': str(eff_date),
            'tarifs': merged_tarifs,
            'is_active': is_now_active,
        },
    )

    from .notification_service import notify_changement_grille_tarifaire
    notify_changement_grille_tarifaire(version)

    return version


def activate_due_grille_versions(today: date = None) -> dict:
    """Active les versions dont la date d'entrée en vigueur est atteinte et notifie à J-1."""
    ref_date = today or timezone.localdate()
    due = (
        GrilleTarifaireVersion.objects.filter(date_entree_vigueur__lte=ref_date)
        .order_by('-date_entree_vigueur', '-created_at')
        .first()
    )
    activated = None
    if due and not due.is_active:
        GrilleTarifaireVersion.objects.filter(is_active=True).update(is_active=False)
        due.is_active = True
        due.save(update_fields=['is_active'])
        sync_config_from_grille(due)
        activated = due.version_label

    tomorrow = ref_date + timedelta(days=1)
    to_notify = GrilleTarifaireVersion.objects.filter(
        date_entree_vigueur=tomorrow,
        notified_veille=False,
    )
    notified_count = 0
    if to_notify.exists():
        from .notification_service import notify_changement_grille_tarifaire
        for v in to_notify:
            notify_changement_grille_tarifaire(v, veille=True)
            v.notified_veille = True
            v.save(update_fields=['notified_veille'])
            notified_count += 1

    return {'activated': activated, 'notified_veille': notified_count}


def verifier_seuil_client(client, today: date = None, apply_downgrade: bool = False, user=None) -> dict:
    """
    Applique les règles du seuil des 3 biens (Brief §3.3) :
    - Passage à >= 3 biens actifs : passage immédiat à Client Conciergerie et tarif préférentiel.
    - Passage de >= 3 à < 3 biens : conserve le tarif préférentiel pour le mois en cours M,
      enregistre le préavis de 15 jours + alerte R.C. & Client.
    - À M+1 (ou apply_downgrade=True après préavis) : repli vers 240 DH / 4h si toujours < 3 biens.
    """
    if not client:
        return {'nb_biens_actifs': 0, 'eligible_conciergerie': False, 'action': 'none'}

    config = get_airbnb_config()
    seuil = config.seuil_biens_conciergerie or 3
    ref_date = today or timezone.localdate()

    nb_actifs = client.biens_airbnb.filter(is_active=True, statut_activation='actif').count()
    action_taken = 'unchanged'

    if nb_actifs >= seuil:
        was_eligible = client.eligible_conciergerie
        changed = False
        if not client.eligible_conciergerie:
            client.eligible_conciergerie = True
            changed = True
        if client.type_client_airbnb == 'particulier':
            client.type_client_airbnb = 'conciergerie'
            changed = True
        if client.reclassement_preavis_envoye_le is not None:
            client.reclassement_preavis_envoye_le = None
            changed = True
        client.derniere_verification_conciergerie = ref_date
        client.save(update_fields=[
            'eligible_conciergerie',
            'type_client_airbnb',
            'reclassement_preavis_envoye_le',
            'derniere_verification_conciergerie',
        ])
        if not was_eligible or changed:
            action_taken = 'upgrade_conciergerie'
            JournalAuditAirbnb.objects.create(
                entite='Client',
                entite_id=str(client.id),
                action='seuil_conciergerie_atteint',
                user=user if (user and getattr(user, 'is_authenticated', False)) else None,
                motif=f"{nb_actifs} biens actifs (>= {seuil}) : tarif préférentiel conciergerie activé immédiatement.",
                valeur_apres={'nb_biens_actifs': nb_actifs, 'eligible_conciergerie': True},
            )
    else:
        # < 3 biens actifs
        if client.eligible_conciergerie:
            # Le client était en tarif conciergerie (ex: 3 -> 2 biens)
            if client.reclassement_preavis_envoye_le is None:
                client.reclassement_preavis_envoye_le = ref_date
                client.derniere_verification_conciergerie = ref_date
                client.save(update_fields=['reclassement_preavis_envoye_le', 'derniere_verification_conciergerie'])
                action_taken = 'preavis_reclassement_envoye'
                JournalAuditAirbnb.objects.create(
                    entite='Client',
                    entite_id=str(client.id),
                    action='preavis_reclassement_seuil',
                    user=user if (user and getattr(user, 'is_authenticated', False)) else None,
                    motif=(
                        f"Client passé sous le seuil ({nb_actifs}/{seuil} biens). "
                        f"Tarif préférentiel maintenu pour le mois en cours ; préavis de {config.preavis_reclassement_jours} jours envoyé."
                    ),
                    valeur_apres={
                        'nb_biens_actifs': nb_actifs,
                        'reclassement_preavis_envoye_le': str(ref_date),
                    },
                )
                from .notification_service import notify_reclassement_preavis
                notify_reclassement_preavis(client)
            else:
                preavis_date = client.reclassement_preavis_envoye_le
                new_month = (ref_date.year, ref_date.month) > (preavis_date.year, preavis_date.month)
                days_elapsed = (ref_date - preavis_date).days
                if apply_downgrade or (new_month and days_elapsed >= (config.preavis_reclassement_jours or 15)):
                    client.eligible_conciergerie = False
                    client.type_client_airbnb = 'particulier'
                    client.derniere_verification_conciergerie = ref_date
                    client.save(update_fields=[
                        'eligible_conciergerie',
                        'type_client_airbnb',
                        'derniere_verification_conciergerie',
                    ])
                    action_taken = 'reclassement_tarif_standard'
                    JournalAuditAirbnb.objects.create(
                        entite='Client',
                        entite_id=str(client.id),
                        action='reclassement_tarif_standard',
                        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
                        motif=f"Bascule M+1 vers tarif standard ({config.tarif_repli_standard} DH / 4h) : {nb_actifs} bien(s) actif(s) < {seuil}.",
                        valeur_apres={'nb_biens_actifs': nb_actifs, 'eligible_conciergerie': False},
                    )
        else:
            # Vérification M+1 pour un client qui n'a jamais atteint les 3 biens
            client.derniere_verification_conciergerie = ref_date
            client.save(update_fields=['derniere_verification_conciergerie'])
            if apply_downgrade or (
                client.date_demarrage_airbnb
                and (ref_date - client.date_demarrage_airbnb).days >= 30 * (config.delai_verif_seuil_mois or 1)
            ):
                client.eligible_conciergerie = False
                client.save(update_fields=['eligible_conciergerie'])
                action_taken = 'verification_m1_sous_seuil'
            else:
                action_taken = 'verifie_sous_seuil'

    return {
        'nb_biens_actifs': nb_actifs,
        'seuil': seuil,
        'eligible_conciergerie': client.eligible_conciergerie,
        'reclassement_preavis_envoye_le': str(client.reclassement_preavis_envoye_le) if client.reclassement_preavis_envoye_le else None,
        'action': action_taken,
    }


def validate_rabat_rules(
    bien: Bien = None,
    ville: str = None,
    nature_linge: str = 'sans_linge',
    services_souscrits: list = None,
    ramassage_specifique: bool = False,
):
    """
    Règle géographique Rabat (Brief §3.4) :
    À Rabat, ménage uniquement (pas de module linge / pas de ramassage à ce stade).
    """
    city = _norm_text(ville or (bien.ville if bien else ''))
    if city == 'rabat':
        if services_souscrits and any(_norm_text(s) == 'linge' for s in services_souscrits):
            raise ValidationError("À Rabat, le module linge et le ramassage sont indisponibles (ménage uniquement).")
        if nature_linge and nature_linge != 'sans_linge':
            raise ValidationError("À Rabat, seul le ménage sans gestion de linge est disponible à ce stade.")
        if ramassage_specifique:
            raise ValidationError("À Rabat, le ramassage spécifique de linge n'est pas disponible.")


def normalize_commande_options(
    options=None,
    config: AirbnbConfig = None,
    reassort: str = None,
    video: bool = None,
    materiel: bool = None,
    ramassage_specifique: bool = False,
    grille_snapshot: dict = None,
    allow_custom_options: bool = False,
):
    """
    Normalise les options de commande et garantit l'exclusivité des packs Réassort (Essentiel vs Confort).
    Si Essentiel puis Confort sont envoyés, le second remplace le premier (jamais de cumul).
    """
    cfg = config or get_airbnb_config()
    snap = grille_snapshot or {}

    def _dec(key, default_val):
        raw = snap.get(key, default_val)
        return Decimal(str(raw))

    prix_essentiel = _dec('prix_reassort_essentiel', cfg.prix_reassort_essentiel)
    prix_confort = _dec('prix_reassort_confort', cfg.prix_reassort_confort)
    prix_video = _dec('prix_video', cfg.prix_video)
    prix_materiel = _dec('prix_materiel', cfg.prix_materiel)
    prix_ramassage = Decimal('50.00')

    normalized = []
    reassort_idx = None
    seen_codes = set()

    def _set_reassort(kind):
        nonlocal reassort_idx
        if kind == 'aucun':
            if reassort_idx is not None:
                normalized.pop(reassort_idx)
                reassort_idx = None
            return
        item = (
            {'code': 'reassort_essentiel', 'label': 'Réassort Essentiel', 'prix': float(prix_essentiel)}
            if kind == 'essentiel'
            else {'code': 'reassort_confort', 'label': 'Réassort Confort', 'prix': float(prix_confort)}
        )
        if reassort_idx is not None:
            normalized[reassort_idx] = item
        else:
            reassort_idx = len(normalized)
            normalized.append(item)

    if options and isinstance(options, list):
        for opt in options:
            if isinstance(opt, str):
                code_raw = opt.strip().lower()
                opt_dict = {'code': code_raw}
            elif isinstance(opt, dict):
                opt_dict = dict(opt)
                code_raw = str(opt_dict.get('code') or opt_dict.get('id') or '').strip().lower()
                if opt_dict.get('prix') not in (None, ''):
                    try:
                        if Decimal(str(opt_dict['prix'])) < 0:
                            raise ValidationError(f"Le prix d'une option ne peut pas être négatif ({code_raw or 'option'}).")
                    except ValidationError:
                        raise
                    except Exception:
                        raise ValidationError(f"Prix d'option invalide pour '{code_raw or 'option'}'.")
            else:
                continue

            if code_raw in ['reassort_essentiel', 'essentiel']:
                _set_reassort('essentiel')
            elif code_raw in ['reassort_confort', 'confort']:
                _set_reassort('confort')
            elif code_raw in ['video', 'video_avant_apres']:
                if 'video' not in seen_codes:
                    seen_codes.add('video')
                    normalized.append({'code': 'video', 'label': 'Vidéo avant / après', 'prix': float(prix_video)})
            elif code_raw in ['materiel', 'materiel_fourni']:
                if 'materiel' not in seen_codes:
                    seen_codes.add('materiel')
                    normalized.append({'code': 'materiel', 'label': 'Matériel fourni', 'prix': float(prix_materiel)})
            elif code_raw in ['ramassage_specifique', 'ramassage_seul']:
                if 'ramassage_specifique' not in seen_codes:
                    seen_codes.add('ramassage_specifique')
                    normalized.append({
                        'code': 'ramassage_specifique',
                        'label': 'Ramassage spécifique linge',
                        'prix': float(prix_ramassage),
                    })
            else:
                try:
                    prix_val = Decimal(str(opt_dict.get('prix') or 0))
                except Exception:
                    raise ValidationError(f"Prix d'option invalide pour '{code_raw or 'option'}'.")
                if prix_val < 0:
                    raise ValidationError(f"Le prix d'une option ne peut pas être négatif ({code_raw or 'option'}).")
                if not allow_custom_options:
                    raise ValidationError(
                        f"Option non reconnue ou tarification libre interdite ({code_raw or 'custom'}). "
                        "Seuls Responsable Commercial et Admin peuvent saisir un supplément personnalisé."
                    )
                normalized.append({
                    'code': code_raw or 'custom',
                    'label': opt_dict.get('label') or code_raw or 'Option',
                    'prix': float(prix_val),
                })

    if reassort is not None:
        r_clean = str(reassort).strip().lower()
        if r_clean in ['essentiel', 'reassort_essentiel']:
            _set_reassort('essentiel')
        elif r_clean in ['confort', 'reassort_confort']:
            _set_reassort('confort')
        elif r_clean in ['aucun', 'none', '']:
            _set_reassort('aucun')
        else:
            raise ValidationError(f"Type de réassort invalide : {reassort}")

    if video is True and 'video' not in seen_codes:
        seen_codes.add('video')
        normalized.append({'code': 'video', 'label': 'Vidéo avant / après', 'prix': float(prix_video)})
    elif video is False:
        normalized = [o for o in normalized if o.get('code') != 'video']

    if materiel is True and 'materiel' not in seen_codes:
        seen_codes.add('materiel')
        normalized.append({'code': 'materiel', 'label': 'Matériel fourni', 'prix': float(prix_materiel)})
    elif materiel is False:
        normalized = [o for o in normalized if o.get('code') != 'materiel']

    if ramassage_specifique and 'ramassage_specifique' not in seen_codes:
        seen_codes.add('ramassage_specifique')
        normalized.append({
            'code': 'ramassage_specifique',
            'label': 'Ramassage spécifique linge',
            'prix': float(prix_ramassage),
        })

    prix_options = sum((Decimal(str(o.get('prix', 0))) for o in normalized), Decimal('0.00'))
    return normalized, prix_options


def _should_apply_standard_repli(bien: Bien, config: AirbnbConfig, enforce_threshold: bool = False) -> bool:
    """
    Détermine si le tarif de repli standard (240 DH / 4h) s'applique à la place de la grille conciergerie.
    """
    if not bien or not getattr(bien, 'client', None):
        return False
    client = bien.client
    seuil = config.seuil_biens_conciergerie or 3
    nb_actifs = client.biens_airbnb.filter(is_active=True, statut_activation='actif').count()

    if nb_actifs >= seuil or client.eligible_conciergerie:
        return False

    if client.type_client_airbnb == 'particulier':
        return True
    if client.derniere_verification_conciergerie is not None and not client.eligible_conciergerie:
        return True
    if enforce_threshold:
        return True
    return False


def calculate_commande_pricing(
    bien: Bien,
    typologie: str = None,
    options: list = None,
    remise_en_etat: float = 0.0,
    date_prestation: date = None,
    reassort: str = None,
    video: bool = None,
    materiel: bool = None,
    ramassage_specifique: bool = False,
    menage_inclus: bool = True,
    enforce_threshold: bool = False,
    allow_custom_options: bool = False,
) -> dict:
    """
    Calcule la décomposition du prix d'une commande / turnover Airbnb à partir de la version
    de grille tarifaire active à la date de prestation.
    """
    config = get_airbnb_config()
    version = get_active_grille_version(date_prestation)
    snap = version.config_snapshot if version and version.config_snapshot else {}
    tarifs_map = version.tarifs_json if version and version.tarifs_json else {}

    target_typologie = typologie or bien.typologie

    base_price_map = {
        'studio': Decimal(str(tarifs_map.get('studio', config.prix_studio))),
        '1ch': Decimal(str(tarifs_map.get('1ch', config.prix_1ch))),
        '2ch': Decimal(str(tarifs_map.get('2ch', config.prix_2ch))),
        '3ch': Decimal(str(tarifs_map.get('3ch', config.prix_3ch))),
        '4ch': Decimal(str(tarifs_map.get('4ch', config.prix_4ch))),
        '5ch': Decimal(str(tarifs_map.get('5ch', config.prix_5ch))),
        'villa_riad': Decimal(str(tarifs_map.get('villa_riad', config.prix_villa_riad))),
    }

    tarif_repli_applique = False
    if not menage_inclus:
        prix_menage = Decimal('0.00')
    elif _should_apply_standard_repli(bien, config, enforce_threshold=enforce_threshold):
        tarif_repli_val = snap.get('tarif_repli_standard', config.tarif_repli_standard)
        prix_menage = Decimal(str(tarif_repli_val))
        tarif_repli_applique = True
    else:
        prix_menage = base_price_map.get(target_typologie, Decimal(str(config.prix_studio)))

    # Zone éloignée (+50 DH par défaut si ménage inclus)
    zones_list = snap.get('zones_eloignees_list', config.zones_eloignees_list) or []
    matching_zones = {_norm_text(z) for z in zones_list if z}
    is_zone_eloignee = bool(bien.zone_eloignee)
    if not is_zone_eloignee and bien.quartier:
        if _norm_text(bien.quartier) in matching_zones:
            is_zone_eloignee = True

    supp_zone_val = Decimal(str(snap.get('supplement_zone_eloignee', config.supplement_zone_eloignee)))
    supplement_zone = supp_zone_val if (is_zone_eloignee and menage_inclus) else Decimal('0.00')

    # Options normalisées (exclusivité Réassort)
    normalized_options, prix_options = normalize_commande_options(
        options=options,
        config=config,
        reassort=reassort,
        video=video,
        materiel=materiel,
        ramassage_specifique=ramassage_specifique,
        grille_snapshot=snap,
        allow_custom_options=allow_custom_options,
    )

    try:
        remise_en_etat_dec = Decimal(str(remise_en_etat or 0))
    except Exception:
        raise ValidationError("Montant de remise en état invalide.")
    if remise_en_etat_dec < 0:
        raise ValidationError("La remise en état ne peut pas être négative.")

    total_ttc_hors_linge = prix_menage + supplement_zone + prix_options + remise_en_etat_dec

    return {
        'typologie': target_typologie,
        'grille_version': version.version_label if version else 'config',
        'tarif_repli_applique': tarif_repli_applique,
        'prix_menage': float(prix_menage),
        'is_zone_eloignee': is_zone_eloignee,
        'supplement_zone': float(supplement_zone),
        'options': normalized_options,
        'prix_options': float(prix_options),
        'remise_en_etat': float(remise_en_etat_dec),
        'total_ttc_hors_linge': float(total_ttc_hors_linge),
    }


def check_cutoff_constraint(
    date_prestation: date,
    heure_prestation=None,
    creneau: str = 'matin',
    now: datetime = None,
) -> dict:
    """
    Contrôle les délais de saisie et d'annulation (Brief §4.4 & §12.3) :
    - Intervention Matin (avant 12h) : jusqu'à 21h00 la veille (J-1).
    - Intervention Après-midi (>= 12h) : à tout moment la veille (J-1, jusqu'à 23h59:59 si illimité).
    """
    config = get_airbnb_config()
    ref_now = timezone.localtime(now) if now and timezone.is_aware(now) else (now or timezone.localtime())
    today = ref_now.date()

    parsed_heure = _parse_time(heure_prestation) if heure_prestation is not None else None
    if parsed_heure is not None:
        is_matin = parsed_heure.hour < 12
    else:
        is_matin = (creneau == 'matin')

    if is_matin:
        cutoff_time = _parse_time(config.cutoff_matin) or time(21, 0)
        cutoff_label = cutoff_time.strftime('%H:%M')
    elif config.cutoff_apres_midi_illimite:
        cutoff_time = time(23, 59, 59)
        cutoff_label = '23:59 (veille)'
    else:
        cutoff_time = _parse_time(config.cutoff_apres_midi) or time(22, 0)
        cutoff_label = cutoff_time.strftime('%H:%M')

    if date_prestation < today:
        return {
            'allowed': False,
            'is_valid': False,
            'is_late': True,
            'message': 'La date demandée est déjà passée.',
            'cutoff_time': cutoff_label,
        }

    if date_prestation == today:
        return {
            'allowed': False,
            'is_valid': False,
            'is_late': True,
            'message': (
                f"Commande ou annulation le jour même hors délai cut-off ({cutoff_label} J-1). "
                "Veuillez contacter votre commercial."
            ),
            'cutoff_time': cutoff_label,
        }

    if (date_prestation - today).days == 1:
        current_time = ref_now.time()
        if current_time > cutoff_time:
            return {
                'allowed': False,
                'is_valid': False,
                'is_late': True,
                'message': (
                    f"Heure limite dépassée ({cutoff_label} la veille pour une intervention "
                    f"{'matin' if is_matin else 'après-midi'}). Veuillez contacter votre commercial."
                ),
                'cutoff_time': cutoff_label,
            }

    return {
        'allowed': True,
        'is_valid': True,
        'is_late': False,
        'message': "Créneau d'intervention conforme aux règles de cut-off.",
        'cutoff_time': cutoff_label,
    }


def forcer_prix_commande(
    commande: CommandeAirbnb,
    nouveau_prix_menage,
    motif: str,
    user,
    nouveau_supplement_zone=None,
) -> CommandeAirbnb:
    """
    Forçage manuel du tarif ménage sur une commande (Brief §2.1 & §4.3).
    Réservé strictement au Responsable Commercial, Modérateur et Admin.
    """
    role = getattr(user, 'role', None)
    if role not in ['responsable_commercial', 'moderateur', 'admin']:
        raise PermissionDenied("Seul le Responsable Commercial ou l'Admin peut forcer un prix.")
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif du forçage de prix est obligatoire.")

    avant = {
        'prix_menage': str(commande.prix_menage),
        'supplement_zone': str(commande.supplement_zone),
        'total_ttc': str(commande.total_ttc),
    }

    commande.prix_menage = Decimal(str(nouveau_prix_menage))
    if nouveau_supplement_zone is not None:
        commande.supplement_zone = Decimal(str(nouveau_supplement_zone))
    commande.total_ttc = (
        commande.prix_menage
        + (commande.supplement_zone or Decimal('0.00'))
        + (commande.prix_options or Decimal('0.00'))
        + (commande.montant_linge or Decimal('0.00'))
        + (commande.remise_en_etat or Decimal('0.00'))
    )
    commande.prix_force_par = user
    commande.prix_force_motif = str(motif).strip()
    commande.save()

    JournalAuditAirbnb.objects.create(
        entite='CommandeAirbnb',
        entite_id=str(commande.id),
        action='forcage_prix',
        user=user,
        motif=str(motif).strip(),
        valeur_avant=avant,
        valeur_apres={
            'prix_menage': str(commande.prix_menage),
            'supplement_zone': str(commande.supplement_zone),
            'total_ttc': str(commande.total_ttc),
        },
    )
    return commande
