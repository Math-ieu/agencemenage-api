import re
import datetime
import logging
from django.utils import timezone
from django.conf import settings
from accounts.models import User
from demandes.models import Demande
from demandes.utils.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)


def parse_intervention_start_time(demande):
    """
    Extrait l'heure de début d'une demande sous forme de datetime.time.
    Prend en compte demande.heure_intervention, formulaire_data['heure'], etc.
    """
    fd = demande.formulaire_data if isinstance(demande.formulaire_data, dict) else {}
    raw = (
        demande.heure_intervention or
        fd.get('heure') or
        fd.get('heure_intervention') or
        fd.get('schedulingTime') or
        ''
    )
    raw = str(raw).strip()
    if not raw or raw in ['—', '-', 'null', 'undefined']:
        # Si aucune heure n'est spécifiée, repli sur 09:00 par défaut
        return datetime.time(9, 0)

    match = re.match(r'^(\d{1,2})(?:[:hH](\d{2}))?', raw)
    if match:
        h = int(match.group(1)) % 24
        m = int(match.group(2) or 0) % 60
        return datetime.time(h, m)

    return datetime.time(9, 0)


def get_intervention_overtime(demande):
    """
    Extrait le nombre d'heures supplémentaires définies pour l'intervention.
    Prend en compte 'heures_supplementaires' et 'supplement_heures_nombre'.
    """
    fd = demande.formulaire_data if isinstance(demande.formulaire_data, dict) else {}
    fact = fd.get('facturation', {}) if isinstance(fd.get('facturation'), dict) else {}
    raw_sup = (
        fd.get('heures_supplementaires') or
        fd.get('supplement_heures_nombre') or
        fact.get('supplement_heures_nombre') or
        getattr(demande, 'heures_supplementaires', 0) or
        0
    )
    try:
        return max(0.0, float(raw_sup))
    except (ValueError, TypeError):
        return 0.0


def get_intervention_duration(demande):
    """
    Extrait le nombre total d'heures de la prestation (durée de base + heures supplémentaires).
    Priorise duree_heures et nb_heures pour éviter la confusion avec duree en mois des abonnements.
    Par défaut : 4h si non renseigné.
    """
    fd = demande.formulaire_data if isinstance(demande.formulaire_data, dict) else {}
    parent_fd = {}
    if demande.parent_demande and isinstance(demande.parent_demande.formulaire_data, dict):
        parent_fd = demande.parent_demande.formulaire_data

    val = (
        fd.get('duree_heures') or
        fd.get('nb_heures') or
        parent_fd.get('duree_heures') or
        parent_fd.get('nb_heures') or
        getattr(demande, 'nb_heures', None) or
        (getattr(demande.parent_demande, 'nb_heures', None) if demande.parent_demande else None) or
        fd.get('heures') or
        fd.get('duration') or
        fd.get('duree') or
        parent_fd.get('duree') or
        4
    )
    try:
        val_float = float(val)
        base = max(val_float, 0.5)
    except (ValueError, TypeError):
        base = 4.0

    # Prise en compte des heures supplémentaires
    sup = get_intervention_overtime(demande)
    return base + sup


def calculate_start_end_datetimes(demande, target_date=None):
    """
    Retourne un tuple (start_dt, end_dt, start_time, duration_hours) localisé pour la demande.
    """
    tz = timezone.get_current_timezone()
    date_val = target_date or demande.date_intervention
    if not date_val:
        date_val = timezone.localtime(timezone.now()).date()

    start_time = parse_intervention_start_time(demande)
    start_dt = timezone.make_aware(datetime.datetime.combine(date_val, start_time), tz)
    duration_hours = get_intervention_duration(demande)
    end_dt = start_dt + datetime.timedelta(hours=duration_hours)
    return start_dt, end_dt, start_time, duration_hours


def send_whatsapp_alert_to_backoffice(demande, start_time, end_dt, duration_hours):
    """
    Envoie le template WhatsApp 'alerte_prestation_terminee' à tous les utilisateurs backoffice actifs.
    """
    backoffice_users = User.objects.filter(
        is_active=True
    ).exclude(
        role=User.CLIENT_CONCIERGERIE
    ).exclude(
        phone__isnull=True
    ).exclude(
        phone=''
    )

    if not backoffice_users.exists():
        logger.warning(f"Aucun utilisateur backoffice avec téléphone pour la demande #{demande.id}")
        return 0

    # Préparation des 5 variables
    # {{1}} Type de ménage
    type_menage = str(demande.service or (demande.parent_demande.service if demande.parent_demande else '') or 'Prestation de ménage')
    # {{2}} Nom du client
    client_name = 'Client'
    if demande.client:
        client_name = demande.client.display_name
    elif demande.parent_demande and demande.parent_demande.client:
        client_name = demande.parent_demande.client.display_name
    elif isinstance(demande.formulaire_data, dict) and demande.formulaire_data.get('nom'):
        client_name = demande.formulaire_data['nom']
    elif demande.parent_demande and isinstance(demande.parent_demande.formulaire_data, dict) and demande.parent_demande.formulaire_data.get('nom'):
        client_name = demande.parent_demande.formulaire_data['nom']

    # {{3}} Date
    date_str = demande.date_intervention.strftime('%d/%m/%Y') if demande.date_intervention else datetime.date.today().strftime('%d/%m/%Y')
    # {{4}} Nombre d'heures
    dur_str = f"{int(duration_hours)}h" if duration_hours.is_integer() else f"{duration_hours}h"
    # {{5}} Tranche horaire
    heure_fin = end_dt.strftime('%Hh%M')
    heure_deb = start_time.strftime('%Hh%M')
    tranche_horaire = f"{heure_deb} - {heure_fin}"

    variables = [
        type_menage,
        client_name,
        date_str,
        dur_str,
        tranche_horaire,
    ]

    sent_count = 0
    for u in backoffice_users:
        phone = u.phone.strip()
        if not phone:
            continue
        try:
            res = WhatsAppService.send_template_message(
                to=phone,
                template_name='alerte_prestation_terminee',
                variables=variables
            )
            if res:
                sent_count += 1
        except Exception as e:
            logger.error(f"Erreur envoi WhatsApp alerte fin prestation à {phone}: {e}")

    logger.info(f"Alerte fin de prestation pour Demande #{demande.id} envoyée à {sent_count} utilisateurs backoffice.")
    return sent_count


def sync_child_status_to_parent(demande):
    """
    Synchronise le statut d'une intervention enfant vers date_overrides du contrat parent.
    """
    if demande.parent_demande and demande.date_intervention:
        try:
            parent = demande.parent_demande
            child_iso = demande.date_intervention.isoformat()
            if not isinstance(parent.formulaire_data, dict):
                parent.formulaire_data = {}
            overrides = parent.formulaire_data.setdefault('date_overrides', {})
            existing_ov = overrides.get(child_iso) or {}
            if existing_ov.get('statut') != demande.statut:
                overrides[child_iso] = {**existing_ov, 'statut': demande.statut}
                parent.save(update_fields=['formulaire_data'])
        except Exception as e:
            logger.error(f"Erreur sync_child_status_to_parent pour demande #{demande.id}: {e}")


def sync_prestation_workflow():
    """
    Moteur principal de synchronisation :
    1. 'pres_confirmee' -> 'pres_en_cours' si heure de début atteinte
    2. 'pres_en_cours' -> 'pres_a_confirmer' si heure de fin atteinte
    3. Alerte WhatsApp toutes les 30 minutes tant que la demande est au statut 'pres_a_confirmer'
    """
    now = timezone.localtime(timezone.now())
    today = now.date()

    eligible_demandes = Demande.objects.filter(
        statut__in=[
            Demande.PRES_CONFIRMEE,
            Demande.PRES_EN_COURS,
            Demande.PRES_A_CONFIRMER,
            Demande.ENCOURS,
        ]
    ).exclude(
        statut__in=[Demande.PRES_TERMINEE, Demande.TERMINE, Demande.ANNULE, Demande.EN_ATTENTE]
    )

    stats = {
        'to_en_cours': 0,
        'to_a_confirmer': 0,
        'alerts_sent': 0,
        'reverted_to_en_cours': 0,
    }

    for d in eligible_demandes:
        # Exclure le contrat mère d'un abonnement (seules les demandes enfants sont des interventions unitaires)
        if d.parent_demande is None and d.frequency == Demande.ABONNEMENT:
            continue

        # Si statut est en_cours mais CAO est validé ('oui' ou True), aligner sur pres_confirmee
        if d.statut == Demande.ENCOURS and d.cao in ['oui', True, 'true', 'confirmed']:
            d.statut = Demande.PRES_CONFIRMEE
            d.save(update_fields=['statut'])
            sync_child_status_to_parent(d)

        # Ne traiter que les demandes ayant une date d'intervention
        d_date = d.date_intervention or today
        # Si l'intervention est dans le futur (au-delà d'aujourd'hui), rien à déclencher
        if d_date > today:
            continue

        start_dt, end_dt, start_time, duration_hours = calculate_start_end_datetimes(d, target_date=d_date)

        # ─── Étape 1 : Passage en 'pres_en_cours' ───
        if d.statut == Demande.PRES_CONFIRMEE:
            if now >= start_dt:
                d.statut = Demande.PRES_EN_COURS
                d.save(update_fields=['statut'])
                sync_child_status_to_parent(d)
                stats['to_en_cours'] += 1
                logger.info(f"Demande #{d.id} passée automatiquement en 'pres_en_cours'")

        # ─── Étape 2 : Passage en 'pres_a_confirmer' ───
        if d.statut == Demande.PRES_EN_COURS:
            if now >= end_dt:
                d.statut = Demande.PRES_A_CONFIRMER
                d.save(update_fields=['statut'])
                sync_child_status_to_parent(d)
                stats['to_a_confirmer'] += 1
                logger.info(f"Demande #{d.id} passée automatiquement en 'pres_a_confirmer'")

        # ─── Étape 2b : Désactivation de l'alerte si heures sup définies (now < end_dt) ───
        if d.statut == Demande.PRES_A_CONFIRMER and now < end_dt:
            d.statut = Demande.PRES_EN_COURS
            if not isinstance(d.formulaire_data, dict):
                d.formulaire_data = {}
            # Désactiver l'alerte initiale et annuler le cycle des notifications WhatsApp
            d.formulaire_data['derniere_alerte_fin_prestation_at'] = None
            d.formulaire_data['alerte_fin_prestation_count'] = 0
            d.formulaire_data['alerte_annulee_pour_heures_sup'] = True
            d.formulaire_data['derniere_annulation_alerte_at'] = now.isoformat()
            d.save(update_fields=['statut', 'formulaire_data'])
            sync_child_status_to_parent(d)
            stats['reverted_to_en_cours'] += 1
            logger.info(f"Demande #{d.id} repassée en 'pres_en_cours' suite à heures sup (alerte désactivée, nouvelle fin : {end_dt})")
            continue

        # ─── Étape 3 : Alerte WhatsApp récurrente (toutes les 30 min) ───
        if d.statut == Demande.PRES_A_CONFIRMER:
            fd = d.formulaire_data if isinstance(d.formulaire_data, dict) else {}
            last_alert_iso = fd.get('derniere_alerte_fin_prestation_at')
            should_send_alert = False

            if not last_alert_iso:
                # Première alerte
                should_send_alert = True
            else:
                try:
                    last_alert_dt = datetime.datetime.fromisoformat(last_alert_iso)
                    if timezone.is_naive(last_alert_dt):
                        last_alert_dt = timezone.make_aware(last_alert_dt, timezone.get_current_timezone())
                    delta_seconds = (now - last_alert_dt).total_seconds()
                    # Répétition toutes les 30 minutes (1800 secondes)
                    if delta_seconds >= 1800:
                        should_send_alert = True
                except Exception as ex:
                    logger.error(f"Erreur parsing last_alert_iso #{d.id}: {ex}")
                    should_send_alert = True

            if should_send_alert:
                sent = send_whatsapp_alert_to_backoffice(d, start_time, end_dt, duration_hours)
                stats['alerts_sent'] += sent
                if not isinstance(d.formulaire_data, dict):
                    d.formulaire_data = {}
                d.formulaire_data['derniere_alerte_fin_prestation_at'] = now.isoformat()
                d.formulaire_data['alerte_fin_prestation_count'] = d.formulaire_data.get('alerte_fin_prestation_count', 0) + 1
                d.save(update_fields=['formulaire_data'])

    return stats
