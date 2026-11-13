import calendar
from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from clients.models import Client
from finance.models import EntreeCaisse, Facture, Paiement
from ..models import CommandeAirbnb, FactureLigneAirbnb, JournalAuditAirbnb
from .pricing_engine import get_airbnb_config
from .suspension_helper import check_and_lift_client_suspension


def add_months(d: date, months: int) -> date:
    """Additionne un nombre exact de mois calendrier en bornant au dernier jour du mois cible."""
    month_idx = d.month - 1 + months
    year = d.year + month_idx // 12
    month = month_idx % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _prev_month(year: int, month: int) -> tuple:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year: int, month: int) -> tuple:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _generer_numero_facture_airbnb(ref_date: date = None) -> str:
    year = (ref_date or timezone.localdate()).year
    prefix = f"FAC-AIR-{year}-"
    existing = Facture.objects.filter(numero__startswith=prefix).values_list('numero', flat=True)
    max_seq = 0
    for num in existing:
        try:
            seq = int(num.replace(prefix, ''))
            if seq > max_seq:
                max_seq = seq
        except (ValueError, TypeError):
            continue
    next_seq = max_seq + 1
    candidate = f"{prefix}{next_seq:04d}"
    while Facture.objects.filter(numero=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}"
    return candidate


def is_commande_facturable(commande: CommandeAirbnb) -> tuple:
    """
    Vérifie les 3 conditions de clôture / facturabilité (Brief §6.7) :
    1. Photos reçues == photos attendues (min 4)
    2. Pas de ramassage OU tous les filets ramassés ont un comptage figé sans écart non arbitré
    3. Aucun signalement en attente (tous arbitrés ou clos)
    """
    reasons = []
    cfg = get_airbnb_config()
    expected_photos = len(cfg.photos_attendues or ['Salon', 'Cuisine', 'Salle de bain', 'Chambres'])
    required_count = max(4, expected_photos)

    if commande.statut == 'annulee':
        reasons.append("La commande est annulée.")
    elif commande.statut not in ['cloturee', 'facturable']:
        reasons.append(f"Statut '{commande.statut}' non clôturé.")

    if len(commande.photos_cloture or []) < required_count:
        reasons.append(f"Photos insuffisantes ({len(commande.photos_cloture or [])}/{required_count}).")

    if commande.nature_linge in ['depot_ramassage', 'ramassage_seul']:
        filets = list(commande.filets_ramasses.all())
        if not filets:
            reasons.append("Aucun filet de ramassage enregistré/compté.")
        else:
            for f in filets:
                if f.montant_fige_le is None:
                    reasons.append(f"Filet {f.code_filet or f.id} non figé en laverie.")
                if f.ecart != 0 and not f.ecart_arbitre:
                    reasons.append(f"Écart linge non arbitré sur filet {f.code_filet or f.id}.")

    if commande.signalements.exclude(statut__in=['arbitre', 'clos']).exists():
        reasons.append("Signalement(s) encore en attente d'arbitrage.")

    if commande.remise_en_etat_statut in ('signalee', 'validee_ops', 'envoyee_client'):
        reasons.append("Remise en état en attente d'accord écrit ou de refus client.")

    if commande.facture_id is not None and commande.facture and commande.facture.statut != Facture.ANNULE:
        reasons.append(f"Déjà rattachée à la facture active {commande.facture.numero}.")

    return (len(reasons) == 0), reasons


def update_commande_facturable_status(commande: CommandeAirbnb) -> bool:
    """Passe automatiquement une commande clôturée au statut 'facturable' dès que toutes les conditions sont réunies."""
    ok, _ = is_commande_facturable(commande)
    if ok and commande.statut == 'cloturee':
        commande.statut = 'facturable'
        commande.save(update_fields=['statut', 'updated_at'])
    return ok


def get_client_probatoire_end(client: Client) -> date:
    if client.probatoire_jusqu_au:
        return client.probatoire_jusqu_au
    cfg = get_airbnb_config()
    start = client.date_demarrage_airbnb or timezone.localdate()
    return add_months(start, cfg.duree_probatoire_mois or 2)


def is_client_in_probatoire(client: Client, ref_date: date = None) -> bool:
    if client.mode_paiement_airbnb != 'mensuel' or client.probatoire_bascule_annulee:
        return False
    check_date = ref_date or timezone.localdate()
    prob_end = get_client_probatoire_end(client)
    return check_date < prob_end


def preview_calendrier_facturation(client: Client, n: int = 5, ref_date: date = None) -> list:
    """
    Calcule les N prochaines échéances du calendrier de facturation d'un client (Brief §7.2).
    Inclut la période probatoire à la quinzaine (26->10 émis le 11 éch 15 ; 11->25 émis le 26 éch 30),
    le prorata éventuel sur le 1er cycle, puis la bascule mensuelle (26->25 émis le 26 éch +4j).
    """
    cfg = get_airbnb_config()
    delai = cfg.delai_paiement_jours or 4

    if client.mode_paiement_airbnb == 'passage' or client.probatoire_bascule_annulee:
        return [{
            'cycle': 1,
            'mode': 'passage',
            'periode_debut': None,
            'periode_fin': None,
            'date_emission': None,
            'date_echeance': None,
            'est_prorata': False,
            'note': f"Facturation après chaque passage clôturé — échéance à J+{delai}.",
        }]

    start = client.date_demarrage_airbnb or ref_date or timezone.localdate()
    prob_end = get_client_probatoire_end(client)
    cursor_base = ref_date or start

    # Génère la séquence chronologique à partir du mois de démarrage
    schedule = []
    cur_y, cur_m = start.year, start.month
    first_cycle_emitted = False

    # Balayer suffisamment de mois pour obtenir N cycles à partir de cursor_base
    for _ in range(36):
        py, pm = _prev_month(cur_y, cur_m)

        # Jalon 11 du mois (Quinzaine 1 : 26 M-1 -> 10 M)
        emit_11 = date(cur_y, cur_m, 11)
        if emit_11 >= start and emit_11 < prob_end:
            nom_debut = date(py, pm, 26)
            nom_fin = date(cur_y, cur_m, 10)
            eff_debut = max(nom_debut, start) if not first_cycle_emitted else nom_debut
            is_prorata = eff_debut > nom_debut
            first_cycle_emitted = True
            if emit_11 >= cursor_base:
                schedule.append({
                    'cycle': len(schedule) + 1,
                    'mode': 'quinzaine',
                    'periode_debut': str(eff_debut),
                    'periode_fin': str(nom_fin),
                    'date_emission': str(emit_11),
                    'date_echeance': str(emit_11 + timedelta(days=delai)),
                    'est_prorata': is_prorata,
                    'probatoire': True,
                })
            if len(schedule) >= n:
                break

        # Jalon 26 du mois (Quinzaine 2 si probatoire : 11 M -> 25 M, sinon Mensuel : 26 M-1 -> 25 M ou 11 M -> 25 M si probatoire finie après le 11)
        emit_26 = date(cur_y, cur_m, 26)
        if emit_26 >= start:
            in_prob = emit_26 < prob_end
            just_exited_after_11 = (not in_prob) and (emit_11 < prob_end) and (emit_11 >= start)
            nom_debut = date(cur_y, cur_m, 11) if (in_prob or just_exited_after_11) else date(py, pm, 26)
            nom_fin = date(cur_y, cur_m, 25)
            eff_debut = max(nom_debut, start) if not first_cycle_emitted else nom_debut
            is_prorata = eff_debut > nom_debut
            first_cycle_emitted = True
            if emit_26 >= cursor_base:
                schedule.append({
                    'cycle': len(schedule) + 1,
                    'mode': 'quinzaine' if in_prob else 'mensuel',
                    'periode_debut': str(eff_debut),
                    'periode_fin': str(nom_fin),
                    'date_emission': str(emit_26),
                    'date_echeance': str(emit_26 + timedelta(days=delai)),
                    'est_prorata': is_prorata,
                    'probatoire': in_prob,
                })
            if len(schedule) >= n:
                break

        cur_y, cur_m = _next_month(cur_y, cur_m)

    return schedule


@transaction.atomic
def _create_facture_for_commandes(
    client: Client,
    commandes: list,
    mode_facturation: str,
    periode_debut: date = None,
    periode_fin: date = None,
    est_prorata: bool = False,
    emit_date: date = None,
    user=None,
) -> Facture:
    if not commandes:
        raise ValidationError("Aucune commande facturable à facturer.")

    cfg = get_airbnb_config()
    emission = emit_date or timezone.localdate()
    echeance = emission + timedelta(days=cfg.delai_paiement_jours or 4)
    numero = _generer_numero_facture_airbnb(emission)

    montant_total = sum((Decimal(str(c.total_ttc or 0)) for c in commandes), Decimal('0.00'))

    facture = Facture.objects.create(
        client=client,
        source=Facture.SOURCE_AIRBNB,
        mode_facturation=mode_facturation,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        est_prorata=est_prorata,
        numero=numero,
        montant_total=montant_total,
        montant_paye=Decimal('0.00'),
        statut=Facture.EN_ATTENTE,
        date_echeance=echeance,
        created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
    )
    if emit_date and facture.date_emission != emit_date:
        Facture.objects.filter(pk=facture.pk).update(date_emission=emit_date)
        facture.refresh_from_db()

    for cmd in commandes:
        designation = f"{cmd.numero} — {cmd.bien.code} ({cmd.date_prestation.strftime('%d/%m/%Y')})"
        FactureLigneAirbnb.objects.create(
            facture=facture,
            commande=cmd,
            type_ligne='prestation',
            designation=designation,
            montant=Decimal(str(cmd.total_ttc or 0)),
            created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
        )
        cmd.facture = facture
        cmd.statut = 'facturee'
        cmd.save(update_fields=['facture', 'statut', 'updated_at'])

    JournalAuditAirbnb.objects.create(
        entite='Facture',
        entite_id=str(facture.id),
        action='emission_facture',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        valeur_apres={
            'numero': facture.numero,
            'mode': mode_facturation,
            'montant_total': str(facture.montant_total),
            'date_echeance': str(facture.date_echeance),
            'nb_commandes': len(commandes),
        },
    )

    try:
        from .pdf_service import generate_and_save_facture_pdf
        generate_and_save_facture_pdf(facture)
    except Exception:
        pass

    from .notification_service import notify_facture_emise
    notify_facture_emise(facture)
    return facture


def generer_facture_passage(commande: CommandeAirbnb, user=None, emit_date: date = None) -> Facture:
    """Émet une facture individuelle pour une commande facturable (mode 'passage' ou ponctuel)."""
    ok, reasons = is_commande_facturable(commande)
    if not ok:
        raise ValidationError("Commande non facturable : " + " ".join(reasons))
    return _create_facture_for_commandes(
        client=commande.bien.client,
        commandes=[commande],
        mode_facturation='passage',
        periode_debut=commande.date_prestation,
        periode_fin=commande.date_prestation,
        est_prorata=False,
        emit_date=emit_date,
        user=user,
    )


def verifier_bascule_probatoire_clients(ref_date: date = None, user=None) -> list:
    """
    Vérifie les clients arrivés au terme de leur période probatoire de 2 mois
    et journalise leur passage en mensuel groupé (Brief §7.4).
    """
    today = ref_date or timezone.localdate()
    switched = []
    clients = Client.objects.filter(
        mode_paiement_airbnb='mensuel',
        probatoire_bascule_annulee=False,
        probatoire_jusqu_au__isnull=False,
        probatoire_jusqu_au__lte=today,
    )
    for client in clients:
        already_logged = JournalAuditAirbnb.objects.filter(
            entite='Client',
            entite_id=str(client.id),
            action='bascule_mensuelle_automatique',
        ).exists()
        if not already_logged:
            JournalAuditAirbnb.objects.create(
                entite='Client',
                entite_id=str(client.id),
                action='bascule_mensuelle_automatique',
                user=user if (user and getattr(user, 'is_authenticated', False)) else None,
                motif="Fin de période probatoire (2 mois) : bascule automatique en facturation mensuelle.",
                valeur_apres={'mode_paiement_airbnb': 'mensuel', 'probatoire_jusqu_au': str(client.probatoire_jusqu_au)},
            )
            switched.append(client.id)
    return switched


def generer_factures_cycle(target_date: date = None, user=None, client_id: int = None) -> dict:
    """
    Moteur unifié d'émission des factures périodiques (Quinzaine probatoire + Mensuel groupé) :
    - Le 11 du mois : quinzaine 1 (26 M-1 -> 10 M) pour les clients en période probatoire.
    - Le 26 du mois : quinzaine 2 (11 M -> 25 M) pour les clients en probatoire,
                      ET cycle mensuel (26 M-1 -> 25 M) pour les clients sortis de probatoire.
    - Pour les clients en mode 'passage' : génère une facture par commande facturable non facturée.
    """
    ref_date = target_date or timezone.localdate()
    switched = verifier_bascule_probatoire_clients(ref_date=ref_date, user=user)
    created_factures = []

    clients_qs = Client.objects.filter(is_archived=False)
    if client_id:
        clients_qs = clients_qs.filter(pk=client_id)

    for client in clients_qs:
        unbilled_qs = (
            CommandeAirbnb.objects.filter(
                bien__client=client,
                statut__in=['cloturee', 'facturable'],
                facture__isnull=True,
            )
            .select_related('bien')
            .prefetch_related('filets_ramasses', 'signalements')
            .order_by('date_prestation')
        )

        # Vérifier aussi les commandes rattachées à une facture annulée (détachées)
        ready_cmds = []
        for cmd in unbilled_qs:
            ok, _ = is_commande_facturable(cmd)
            if ok:
                update_commande_facturable_status(cmd)
                ready_cmds.append(cmd)

        if not ready_cmds:
            continue

        if client.mode_paiement_airbnb == 'passage' or client.probatoire_bascule_annulee:
            for cmd in ready_cmds:
                fac = generer_facture_passage(cmd, user=user, emit_date=ref_date)
                created_factures.append(fac)
            continue

        # Mode mensuel (avec probatoire 2 mois à la quinzaine)
        in_prob = is_client_in_probatoire(client, ref_date=ref_date)
        prob_end = get_client_probatoire_end(client)
        py, pm = _prev_month(ref_date.year, ref_date.month)

        if ref_date.day == 11 and in_prob:
            nom_debut = date(py, pm, 26)
            nom_fin = date(ref_date.year, ref_date.month, 10)
            mode_str = 'quinzaine'
        elif ref_date.day == 26:
            emit_11 = date(ref_date.year, ref_date.month, 11)
            just_exited_after_11 = (not in_prob) and (emit_11 < prob_end)
            last_cycle_inv = (
                Facture.objects.filter(
                    client=client,
                    source=Facture.SOURCE_AIRBNB,
                    periode_fin__gte=date(py, pm, 26),
                    periode_fin__lt=date(ref_date.year, ref_date.month, 25),
                )
                .exclude(statut=Facture.ANNULE)
                .order_by('-periode_fin')
                .first()
            )
            if in_prob or just_exited_after_11:
                nom_debut = date(ref_date.year, ref_date.month, 11)
            elif last_cycle_inv and last_cycle_inv.periode_fin:
                nom_debut = max(date(py, pm, 26), last_cycle_inv.periode_fin + timedelta(days=1))
            else:
                nom_debut = date(py, pm, 26)
            nom_fin = date(ref_date.year, ref_date.month, 25)
            mode_str = 'quinzaine' if in_prob else 'mensuel'
        else:
            continue

        start_date = client.date_demarrage_airbnb or nom_debut
        has_previous_invoice = Facture.objects.filter(client=client, source=Facture.SOURCE_AIRBNB).exclude(statut=Facture.ANNULE).exists()
        eff_debut = max(nom_debut, start_date) if (not has_previous_invoice and start_date > nom_debut) else nom_debut
        est_prorata = eff_debut > nom_debut

        cycle_cmds = [c for c in ready_cmds if c.date_prestation <= nom_fin]
        if not cycle_cmds:
            continue

        fac = _create_facture_for_commandes(
            client=client,
            commandes=cycle_cmds,
            mode_facturation=mode_str,
            periode_debut=eff_debut,
            periode_fin=nom_fin,
            est_prorata=est_prorata,
            emit_date=ref_date,
            user=user,
        )
        created_factures.append(fac)

    return {
        'date': str(ref_date),
        'bascules': switched,
        'bascule_mensuelle_clients': switched,
        'factures': created_factures,
        'factures_creees': [f.numero for f in created_factures],
        'total_creees': len(created_factures),
    }


def enregistrer_paiement(
    facture: Facture,
    montant,
    mode: str,
    payment_date: date = None,
    reference: str = '',
    notes: str = '',
    user=None,
) -> dict:
    """
    Enregistre un paiement sur une facture Airbnb, crée automatiquement le mouvement
    EntreeCaisse (Caisse si espèces, Trésorerie si virement/chèque/carte) et lève la suspension
    si toutes les factures échues du client sont soldées.
    """
    if facture.statut == Facture.ANNULE:
        raise ValidationError("Impossible d'enregistrer un paiement sur une facture annulée.")

    amt = Decimal(str(montant))
    if amt <= 0:
        raise ValidationError("Le montant du paiement doit être strictement positif.")

    p_date = payment_date or timezone.localdate()
    paiement = Paiement.objects.create(
        facture=facture,
        montant=amt,
        mode=mode,
        date=p_date,
        reference=reference or '',
        notes=notes or '',
        created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
    )

    total_paye = facture.paiements.aggregate(t=Sum('montant'))['t'] or Decimal('0.00')
    facture.montant_paye = total_paye
    if total_paye >= facture.montant_total:
        facture.statut = Facture.PAYE
    elif total_paye > 0:
        facture.statut = Facture.PARTIEL
    facture.save(update_fields=['montant_paye', 'statut'])

    # Création EntreeCaisse si non existante
    if not EntreeCaisse.objects.filter(paiement=paiement).exists():
        is_especes = (mode == Paiement.ESPECES)
        caisse_type = EntreeCaisse.CAISSE if is_especes else EntreeCaisse.TRESORERIE
        categorie = 'Virement client reçu' if mode == Paiement.VIREMENT else 'Encaissement client (auto)'
        mode_map = {
            Paiement.ESPECES: EntreeCaisse.ESPECES,
            Paiement.VIREMENT: EntreeCaisse.VIREMENT,
            Paiement.CHEQUE: EntreeCaisse.CHEQUE,
            Paiement.CARTE: EntreeCaisse.VIREMENT,
        }
        user_display = ''
        if user and getattr(user, 'is_authenticated', False):
            user_display = getattr(user, 'full_name', '') or user.username or user.email
        EntreeCaisse.objects.create(
            type_mouvement=EntreeCaisse.ENTREE,
            categorie=categorie,
            caisse_type=caisse_type,
            montant=amt,
            description=f"Encaissement facture Airbnb {facture.numero}",
            date=p_date,
            mode_paiement=mode_map.get(mode, EntreeCaisse.VIREMENT),
            client=facture.client,
            client_nom=facture.client.display_name if facture.client else '',
            utilisateur=user_display,
            notes=notes or (f"Réf: {reference}" if reference else ''),
            paiement=paiement,
            created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
        )

    suspension_res = check_and_lift_client_suspension(
        facture.client,
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
    )
    if suspension_res.get('lifted'):
        from .notification_service import notify_reactivation_client
        notify_reactivation_client(
            facture.client,
            reactivable_count=suspension_res.get('reactivable_count', 0),
        )

    caisse_obj = EntreeCaisse.objects.filter(paiement=paiement).first()
    return {
        'paiement': paiement,
        'facture': facture,
        'entree_caisse': caisse_obj,
        'reactived_client': bool(suspension_res.get('lifted')),
        'suspension': suspension_res,
    }


def declarer_virement(
    facture: Facture,
    reference: str,
    justificatif_url: str = '',
    montant_declare=None,
    user=None,
) -> Facture:
    """Permet à la conciergerie de déclarer un virement effectué en attente de rapprochement R.F."""
    if facture.statut == Facture.ANNULE:
        raise ValidationError("Facture annulée.")
    facture.virement_declare_le = timezone.now()
    facture.virement_reference = reference or ''
    facture.virement_justificatif_url = justificatif_url or ''
    if montant_declare is not None:
        facture.virement_montant_declare = Decimal(str(montant_declare))
    facture.save(update_fields=[
        'virement_declare_le',
        'virement_reference',
        'virement_justificatif_url',
        'virement_montant_declare',
    ])

    JournalAuditAirbnb.objects.create(
        entite='Facture',
        entite_id=str(facture.id),
        action='declaration_virement_client',
        user=user if (user and getattr(user, 'is_authenticated', False)) else None,
        valeur_apres={
            'reference': facture.virement_reference,
            'montant_declare': str(facture.virement_montant_declare or ''),
        },
    )

    from .notification_service import notify_virement_declare
    notify_virement_declare(facture)
    return facture


def verifier_suspensions_et_relances(today: date = None, user=None) -> dict:
    """
    Job quotidien Facturation (Brief §7.3 & §7.5) :
    - À J-1 de l'échéance : envoie une relance de paiement.
    - À J+1 après échéance non honorée (date_echeance < today) :
      suspend le compte client, annule ses commandes planifiées futures,
      libère intervenantes & runners, notifie client/commercial/R.F./opérations/runners.
    """
    ref_date = today or timezone.localdate()
    from .notification_service import notify_rappel_impaye, notify_suspension_client

    # 1. Relances J-1
    tomorrow = ref_date + timedelta(days=1)
    due_tomorrow = Facture.objects.filter(
        source=Facture.SOURCE_AIRBNB,
        statut__in=[Facture.EN_ATTENTE, Facture.PARTIEL],
        date_echeance=tomorrow,
    ).select_related('client')
    reminders_sent = 0
    for fac in due_tomorrow:
        notify_rappel_impaye(fac)
        reminders_sent += 1

    # 2. Suspensions dès J+1 de retard (date_echeance < ref_date)
    # Compte à rebours basé sur la facture impayée LA PLUS ANCIENNE
    overdue_factures = (
        Facture.objects.filter(
            source=Facture.SOURCE_AIRBNB,
            statut__in=[Facture.EN_ATTENTE, Facture.PARTIEL],
            date_echeance__lt=ref_date,
        )
        .select_related('client')
        .order_by('date_echeance')
    )

    suspended_clients = []
    cancelled_orders_total = 0
    seen_clients = set()

    for fac in overdue_factures:
        client = fac.client
        if not client or client.id in seen_clients:
            continue
        seen_clients.add(client.id)

        was_active = client.statut_airbnb != 'suspendu'
        if was_active:
            client.statut_airbnb = 'suspendu'
            client.save(update_fields=['statut_airbnb'])

        # Annuler toutes les commandes planifiées futures pour libérer intervenantes & runners
        future_cmds = list(
            CommandeAirbnb.objects.filter(
                bien__client=client,
                date_prestation__gte=ref_date,
                statut__in=['proposition', 'brouillon', 'confirmee', 'saisie', 'remontee_tdb', 'assignee'],
            ).select_related('bien', 'runner', 'intervenante', 'intervenante_2')
        )
        for cmd in future_cmds:
            cmd.statut = 'annulee'
            cmd.annulee_par_suspension = True
            cmd.reactivable_apres_suspension = True
            cmd.annulee_le = timezone.now()
            cmd.annulation_motif = f"Suspension client pour impayé (Facture {fac.numero} échue le {fac.date_echeance})"
            old_runner = cmd.runner
            cmd.intervenante = None
            cmd.intervenante_2 = None
            cmd.runner = None
            cmd.save()
            cmd._freed_runner = old_runner
            cancelled_orders_total += 1

        if was_active or future_cmds:
            JournalAuditAirbnb.objects.create(
                entite='Client',
                entite_id=str(client.id),
                action='suspension_impaye',
                user=user if (user and getattr(user, 'is_authenticated', False)) else None,
                motif=f"Facture {fac.numero} impayée depuis échéance {fac.date_echeance}",
                valeur_avant={'statut_airbnb': 'actif'},
                valeur_apres={
                    'statut_airbnb': 'suspendu',
                    'commandes_annulees': [c.numero for c in future_cmds],
                },
            )
            notify_suspension_client(client, fac, cancelled_orders=future_cmds)
            suspended_clients.append(client.id)

    return {
        'date': str(ref_date),
        'reminders': reminders_sent,
        'relances_j1': reminders_sent,
        'suspended': len(suspended_clients),
        'clients_suspendus': suspended_clients,
        'commandes_annulees': cancelled_orders_total,
    }


def _assert_rf_or_admin(user):
    role = getattr(user, 'role', None)
    if role not in ['responsable_facturation', 'admin']:
        raise PermissionDenied("Action réservée exclusivement au Responsable Facturation ou à l'Administrateur.")


def _ensure_baseline_lignes(facture: Facture, user=None):
    """Matérialise les lignes prestation initiales si la facture n'en contient pas encore."""
    if facture.lignes_airbnb.exists():
        return
    cmds = list(facture.commandes_airbnb.select_related('bien').all())
    if cmds:
        cmds_sum = sum((Decimal(str(c.total_ttc or 0)) for c in cmds), Decimal('0.00'))
        if cmds_sum == Decimal(str(facture.montant_total or 0)):
            for cmd in cmds:
                FactureLigneAirbnb.objects.create(
                    facture=facture,
                    commande=cmd,
                    type_ligne='prestation',
                    designation=f"{cmd.numero} — {cmd.bien.code} ({cmd.date_prestation.strftime('%d/%m/%Y')})",
                    montant=Decimal(str(cmd.total_ttc or 0)),
                    created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
                )
            return
    if (facture.montant_total or Decimal('0.00')) > 0:
        FactureLigneAirbnb.objects.create(
            facture=facture,
            type_ligne='prestation',
            designation=f"Prestations facture {facture.numero}",
            montant=Decimal(str(facture.montant_total)),
            created_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
        )


@transaction.atomic
def annuler_facture(facture: Facture, motif: str, user, commande_id=None, ligne_ids=None) -> Facture:
    """
    Levier 1 R.F. (§7.6) : Annule une facture entière ou une partie de facture (commande / lignes),
    efface la créance correspondante, conserve les prestations intactes en les repassant au statut
    'facturable' pour le prochain cycle, et vérifie la levée de suspension.
    """
    _assert_rf_or_admin(user)
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif d'annulation est obligatoire.")
    if facture.statut == Facture.ANNULE:
        raise ValidationError("Cette facture est déjà annulée.")

    avant = {'statut': facture.statut, 'montant_total': str(facture.montant_total)}
    clean_motif = str(motif).strip()

    if commande_id or ligne_ids:
        _ensure_baseline_lignes(facture, user=user)
        lignes_qs = facture.lignes_airbnb.all()
        if commande_id and ligne_ids:
            lignes_qs = lignes_qs.filter(id__in=ligne_ids) | lignes_qs.filter(commande_id=commande_id)
        elif ligne_ids:
            lignes_qs = lignes_qs.filter(id__in=ligne_ids)
        elif commande_id:
            lignes_qs = lignes_qs.filter(commande_id=commande_id)
        lignes_to_remove = list(lignes_qs.distinct())
        if not lignes_to_remove:
            raise ValidationError("Aucune ligne ou commande correspondante trouvée sur cette facture.")

        remove_ids = [l.id for l in lignes_to_remove]
        remaining_exists = facture.lignes_airbnb.exclude(id__in=remove_ids).exists()
        if remaining_exists:
            detached_cmds = []
            cmd_ids_to_detach = {l.commande_id for l in lignes_to_remove if l.commande_id}
            if commande_id:
                cmd_ids_to_detach.add(commande_id)
            for cmd in facture.commandes_airbnb.filter(id__in=cmd_ids_to_detach):
                cmd.facture = None
                cmd.statut = 'facturable'
                cmd.save(update_fields=['facture', 'statut', 'updated_at'])
                detached_cmds.append(cmd.numero)

            removed_summary = [{'id': str(l.id), 'designation': l.designation, 'montant': str(l.montant)} for l in lignes_to_remove]
            facture.lignes_airbnb.filter(id__in=remove_ids).delete()
            _recalculate_facture_from_lignes(facture, user=user)
            try:
                from .pdf_service import generate_and_save_facture_pdf
                generate_and_save_facture_pdf(facture)
            except Exception:
                pass
            JournalAuditAirbnb.objects.create(
                entite='Facture',
                entite_id=str(facture.id),
                action='annulation_partielle_facture',
                user=user,
                motif=clean_motif,
                valeur_avant=avant,
                valeur_apres={
                    'statut': facture.statut,
                    'montant_total': str(facture.montant_total),
                    'lignes_annulees': removed_summary,
                    'commandes_remises_facturables': detached_cmds,
                },
            )
            return facture

    facture.statut = Facture.ANNULE
    facture.motif_annulation = clean_motif
    facture.annulee_le = timezone.now()
    facture.annulee_par = user
    facture.save(update_fields=['statut', 'motif_annulation', 'annulee_le', 'annulee_par'])

    # Les prestations restent intactes et repartent au cycle suivant
    detached_cmds = list(facture.commandes_airbnb.all())
    for cmd in detached_cmds:
        cmd.facture = None
        cmd.statut = 'facturable'
        cmd.save(update_fields=['facture', 'statut', 'updated_at'])

    JournalAuditAirbnb.objects.create(
        entite='Facture',
        entite_id=str(facture.id),
        action='annulation_facture',
        user=user,
        motif=facture.motif_annulation,
        valeur_avant=avant,
        valeur_apres={
            'statut': facture.statut,
            'commandes_remises_facturables': [c.numero for c in detached_cmds],
        },
    )

    if facture.client:
        res = check_and_lift_client_suspension(facture.client, user=user)
        if res.get('lifted'):
            from .notification_service import notify_reactivation_client
            notify_reactivation_client(facture.client, reactivable_count=res.get('reactivable_count', 0))

    return facture


def _recalculate_facture_from_lignes(facture: Facture, user=None):
    total = facture.lignes_airbnb.aggregate(t=Sum('montant'))['t']
    if total is not None:
        facture.montant_total = max(Decimal('0.00'), total)
    if facture.montant_paye >= facture.montant_total:
        facture.statut = Facture.PAYE
    elif facture.montant_paye > 0:
        facture.statut = Facture.PARTIEL
    else:
        facture.statut = Facture.EN_ATTENTE
    facture.save(update_fields=['montant_total', 'statut'])

    if facture.statut == Facture.PAYE and facture.client:
        res = check_and_lift_client_suspension(facture.client, user=user)
        if res.get('lifted'):
            from .notification_service import notify_reactivation_client
            notify_reactivation_client(facture.client, reactivable_count=res.get('reactivable_count', 0))


@transaction.atomic
def appliquer_geste_commercial(facture: Facture, montant, designation: str, motif: str, user) -> FactureLigneAirbnb:
    """
    Levier 2 R.F. (§7.6) : Ajoute une ligne négative visible du client sur la facture.
    """
    _assert_rf_or_admin(user)
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif du geste commercial est obligatoire.")
    if facture.statut == Facture.ANNULE:
        raise ValidationError("Impossible d'appliquer un geste commercial sur une facture annulée.")

    amt = abs(Decimal(str(montant)))
    if amt <= 0:
        raise ValidationError("Le montant du geste commercial doit être strictement positif.")

    _ensure_baseline_lignes(facture, user=user)
    avant = {'montant_total': str(facture.montant_total)}
    ligne = FactureLigneAirbnb.objects.create(
        facture=facture,
        type_ligne='geste_commercial',
        designation=designation or "Geste commercial",
        montant=-amt,
        motif=str(motif).strip(),
        created_by=user,
    )
    _recalculate_facture_from_lignes(facture, user=user)

    JournalAuditAirbnb.objects.create(
        entite='Facture',
        entite_id=str(facture.id),
        action='geste_commercial',
        user=user,
        motif=str(motif).strip(),
        valeur_avant=avant,
        valeur_apres={'montant_total': str(facture.montant_total), 'ligne_id': str(ligne.id), 'reduction': str(-amt)},
    )
    return ligne


@transaction.atomic
def appliquer_reduction_partielle(
    facture: Facture,
    montant_reduction,
    motif: str,
    commande_id=None,
    designation: str = '',
    user=None,
) -> FactureLigneAirbnb:
    """
    Levier 3 R.F. (§7.6) : Applique une réduction partielle sur une prestation ou option précise.
    """
    _assert_rf_or_admin(user)
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif de la réduction partielle est obligatoire.")
    if facture.statut == Facture.ANNULE:
        raise ValidationError("Impossible d'appliquer une réduction sur une facture annulée.")

    amt = abs(Decimal(str(montant_reduction)))
    if amt <= 0:
        raise ValidationError("Le montant de réduction doit être strictement positif.")

    _ensure_baseline_lignes(facture, user=user)
    avant = {'montant_total': str(facture.montant_total)}
    ligne = FactureLigneAirbnb.objects.create(
        facture=facture,
        commande_id=commande_id,
        type_ligne='reduction_partielle',
        designation=designation or "Réduction partielle",
        montant=-amt,
        motif=str(motif).strip(),
        created_by=user,
    )
    _recalculate_facture_from_lignes(facture, user=user)

    JournalAuditAirbnb.objects.create(
        entite='Facture',
        entite_id=str(facture.id),
        action='reduction_partielle',
        user=user,
        motif=str(motif).strip(),
        valeur_avant=avant,
        valeur_apres={
            'montant_total': str(facture.montant_total),
            'ligne_id': str(ligne.id),
            'commande_id': str(commande_id) if commande_id else None,
            'reduction': str(-amt),
        },
    )
    return ligne


def annuler_bascule_mensuelle(client: Client, motif: str, user) -> Client:
    """
    Sortie de la période probatoire (Brief §7.4) :
    Le Responsable Commercial (ou R.F./Admin) annule la bascule mensuelle automatique.
    Le compte repasse alors par défaut en facturation après chaque passage.
    """
    role = getattr(user, 'role', None)
    if role not in ['responsable_commercial', 'responsable_facturation', 'admin']:
        raise PermissionDenied("Action réservée au Responsable Commercial, Responsable Facturation ou Admin.")
    if not motif or not str(motif).strip():
        raise ValidationError("Le motif est obligatoire.")

    avant = {
        'mode_paiement_airbnb': client.mode_paiement_airbnb,
        'probatoire_bascule_annulee': client.probatoire_bascule_annulee,
    }
    client.probatoire_bascule_annulee = True
    client.mode_paiement_airbnb = 'passage'
    client.save(update_fields=['probatoire_bascule_annulee', 'mode_paiement_airbnb'])

    JournalAuditAirbnb.objects.create(
        entite='Client',
        entite_id=str(client.id),
        action='annulation_bascule_mensuelle',
        user=user,
        motif=str(motif).strip(),
        valeur_avant=avant,
        valeur_apres={
            'mode_paiement_airbnb': client.mode_paiement_airbnb,
            'probatoire_bascule_annulee': client.probatoire_bascule_annulee,
        },
    )
    return client
