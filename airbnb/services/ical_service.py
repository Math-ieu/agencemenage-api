import re
import urllib.request
from datetime import date, time
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..models import Bien, CommandeAirbnb, FiletLinge, JournalAuditAirbnb
from .pricing_engine import (
    calculate_commande_pricing,
    check_cutoff_constraint,
    get_airbnb_config,
    validate_rabat_rules,
)


def parse_ical_date(date_str: str):
    """Parse une date de type '20260825' ou '20260825T110000Z' en objet date Python."""
    clean = re.sub(r'[^0-9]', '', date_str or '')
    if len(clean) >= 8:
        year = int(clean[:4])
        month = int(clean[4:6])
        day = int(clean[6:8])
        return date(year, month, day)
    return None


def parse_ical_content(content: str) -> list:
    """Parse le texte brut d'un flux .ics (RFC 5545, lignes repliées incluses)."""
    unfolded = re.sub(r'\r?\n[ \t]', '', content or '')
    events = []
    current_event = {}
    in_vevent = False

    for line in unfolded.splitlines():
        line = line.strip()
        if line == 'BEGIN:VEVENT':
            in_vevent = True
            current_event = {}
        elif line == 'END:VEVENT':
            if in_vevent and current_event.get('dtend'):
                events.append(current_event)
            in_vevent = False
        elif in_vevent:
            if line.startswith('DTSTART'):
                val = line.split(':', 1)[-1]
                current_event['dtstart'] = parse_ical_date(val)
            elif line.startswith('DTEND'):
                val = line.split(':', 1)[-1]
                current_event['dtend'] = parse_ical_date(val)
            elif line.startswith('SUMMARY'):
                val = line.split(':', 1)[-1]
                current_event['summary'] = val
            elif line.startswith('UID'):
                val = line.split(':', 1)[-1]
                current_event['uid'] = val.strip()

    return events


def fetch_and_parse_ical(ical_url: str) -> list:
    """Télécharge et extrait les événements VEVENT d'un flux iCal."""
    req = urllib.request.Request(
        ical_url,
        headers={'User-Agent': 'AgenceMenage-iCal-Sync/1.0'}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raise ValueError(f"Erreur de connexion au flux iCal : {str(e)}")
    return parse_ical_content(content)


def _generate_commande_numero(target_year: int) -> str:
    prefix = f"CMD-{target_year}-"
    existing = CommandeAirbnb.objects.filter(numero__startswith=prefix).values_list('numero', flat=True)
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
    while CommandeAirbnb.objects.filter(numero=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}"
    return candidate


def sync_bien_ical_turnovers(bien: Bien, ical_content: str = None) -> dict:
    """
    Synchronise le flux iCal d'un bien et crée des PROPOSITIONS de turnover (statut='proposition'),
    jamais des commandes fermes, sans doublons (Brief §8.2 & §12.5).
    """
    if not bien.ical_url and not ical_content:
        return {'success': False, 'message': "Aucune URL iCal configurée pour ce bien."}

    try:
        events = parse_ical_content(ical_content) if ical_content is not None else fetch_and_parse_ical(bien.ical_url)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    cfg = get_airbnb_config()
    today = timezone.localdate()
    raw_heure = cfg.ical_heure_defaut or time(11, 0)
    if isinstance(raw_heure, str):
        parts = raw_heure.strip().split(':')
        default_heure = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    else:
        default_heure = raw_heure
    creneau = 'matin' if default_heure.hour < 12 else 'apres_midi'

    is_rabat = (bien.ville or '').strip().lower() == 'rabat'
    has_prior_linen = FiletLinge.objects.filter(bien=bien).exists()
    default_nature_linge = 'sans_linge' if is_rabat else ('depot_ramassage' if has_prior_linen else 'ramassage_seul')

    created_count = 0
    existing_count = 0
    created_commandes = []

    for ev in events:
        checkout_date = ev.get('dtend')
        if not checkout_date or checkout_date < today:
            continue

        uid = (ev.get('uid') or '').strip()
        if uid and CommandeAirbnb.objects.filter(bien=bien, ical_event_uid=uid).exclude(statut='annulee').exists():
            existing_count += 1
            continue

        if CommandeAirbnb.objects.filter(bien=bien, date_prestation=checkout_date).exclude(statut='annulee').exists():
            existing_count += 1
            continue

        pricing = calculate_commande_pricing(bien, date_prestation=checkout_date)
        num_cmd = _generate_commande_numero(checkout_date.year)

        cmd = CommandeAirbnb.objects.create(
            numero=num_cmd,
            bien=bien,
            date_prestation=checkout_date,
            heure_prestation=default_heure,
            creneau=creneau,
            nature_linge=default_nature_linge,
            grille_version=pricing['grille_version'],
            prix_menage=Decimal(str(pricing['prix_menage'])),
            supplement_zone=Decimal(str(pricing['supplement_zone'])),
            prix_options=Decimal(str(pricing['prix_options'])),
            total_ttc=Decimal(str(pricing['total_ttc_hors_linge'])),
            statut='proposition',
            source='ical_auto',
            ical_event_uid=uid,
            rapport_notes=f"Proposition iCal détectée (Départ voyageur : {ev.get('summary', 'Réservation')})",
        )
        created_count += 1
        created_commandes.append(cmd)

    bien.ical_derniere_lecture = timezone.now()
    bien.save(update_fields=['ical_derniere_lecture'])

    if created_commandes:
        from .notification_service import notify_depart_ical_detecte
        notify_depart_ical_detecte(bien, created_commandes)

    return {
        'success': True,
        'events_found': len(events),
        'created_turnovers': created_count,
        'existing_turnovers': existing_count,
        'propositions_ids': [str(c.id) for c in created_commandes],
        'last_synced': bien.ical_derniere_lecture.isoformat(),
    }


def confirmer_proposition(commande: CommandeAirbnb, overrides: dict = None, user=None) -> CommandeAirbnb:
    """
    Confirme une proposition iCal en commande ferme (Brief §8.1 & §8.2).
    Vérifie suspension client, règle Rabat, et cut-off (sauf dérogation backoffice).
    """
    if commande.statut != 'proposition':
        raise ValidationError("Seule une proposition iCal peut être confirmée par cette action.")

    bien = commande.bien
    if bien.client and bien.client.statut_airbnb == 'suspendu':
        raise ValidationError("Compte client suspendu pour impayé. Régularisation requise avant confirmation.")

    data = overrides or {}
    if data.get('heure_prestation'):
        hp = data['heure_prestation']
        if isinstance(hp, str):
            parts = hp.split(':')
            commande.heure_prestation = time(int(parts[0]), int(parts[1]))
        else:
            commande.heure_prestation = hp
        commande.creneau = 'matin' if commande.heure_prestation.hour < 12 else 'apres_midi'

    if data.get('nature_linge'):
        commande.nature_linge = data['nature_linge']
    if 'consigne_ponctuelle' in data:
        commande.consigne_ponctuelle = data['consigne_ponctuelle'] or ''

    validate_rabat_rules(bien=bien, nature_linge=commande.nature_linge)

    role = getattr(user, 'role', None) if user else None
    cutoff = check_cutoff_constraint(
        date_prestation=commande.date_prestation,
        heure_prestation=commande.heure_prestation,
        creneau=commande.creneau,
    )
    if not cutoff['is_valid']:
        if role not in ('admin', 'responsable_commercial') or not data.get('forcer_hors_delai'):
            raise ValidationError(cutoff['message'])
        commande.hors_delai_derogation = True
        JournalAuditAirbnb.objects.create(
            entite='CommandeAirbnb',
            entite_id=str(commande.id),
            action='derogation_hors_delai_confirmation_ical',
            user=user,
            motif=data.get('motif_derogation') or 'Confirmation proposition iCal hors délai',
            valeur_avant={'statut': 'proposition', 'hors_delai_derogation': False},
            valeur_apres={'statut': 'confirmee', 'hors_delai_derogation': True},
        )

    pricing = calculate_commande_pricing(
        bien=bien,
        options=data.get('options', commande.options),
        reassort=data.get('reassort'),
        video=data.get('video'),
        materiel=data.get('materiel'),
        date_prestation=commande.date_prestation,
    )
    commande.options = pricing['options']
    commande.grille_version = pricing['grille_version']
    commande.prix_menage = Decimal(str(pricing['prix_menage']))
    commande.supplement_zone = Decimal(str(pricing['supplement_zone']))
    commande.prix_options = Decimal(str(pricing['prix_options']))
    commande.total_ttc = Decimal(str(pricing['total_ttc_hors_linge'])) + (commande.montant_linge or Decimal('0.00'))
    commande.statut = 'confirmee'
    commande.save()

    from .notification_service import notify_commande_confirmee
    notify_commande_confirmee(commande)
    return commande


def rejeter_proposition(commande: CommandeAirbnb, motif: str = '', user=None) -> CommandeAirbnb:
    """Rejette une proposition iCal (passe en statut 'annulee')."""
    if commande.statut != 'proposition':
        raise ValidationError("Seule une proposition iCal peut être rejetée par cette action.")
    commande.statut = 'annulee'
    commande.annulee_le = timezone.now()
    commande.annulation_motif = motif or "Proposition iCal déclinée"
    commande.save(update_fields=['statut', 'annulee_le', 'annulation_motif', 'updated_at'])
    return commande
