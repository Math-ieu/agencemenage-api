import re
import urllib.request
from datetime import datetime, date, timedelta
from django.utils import timezone
from ..models import Bien, CommandeAirbnb
from .pricing_engine import calculate_commande_pricing


def parse_ical_date(date_str: str) -> date:
    """Parse une date de type '20260825' ou '20260825T110000Z' en objet date Python."""
    clean = re.sub(r'[^0-9]', '', date_str)
    if len(clean) >= 8:
        year = int(clean[:4])
        month = int(clean[4:6])
        day = int(clean[6:8])
        return date(year, month, day)
    return None


def fetch_and_parse_ical(ical_url: str) -> list:
    """
    Télécharge et extrait les événements VEVENT (Check-in, Check-out, Résumé) d'un flux iCal.
    """
    req = urllib.request.Request(
        ical_url,
        headers={'User-Agent': 'AgenceMenage-iCal-Sync/1.0'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raise ValueError(f"Erreur de connexion au flux iCal : {str(e)}")

    events = []
    current_event = {}
    in_vevent = False

    for line in content.splitlines():
        line = line.strip()
        if line == 'BEGIN:VEVENT':
            in_vevent = True
            current_event = {}
        elif line == 'END:VEVENT':
            if in_vevent and 'dtend' in current_event:
                events.append(current_event)
            in_vevent = False
        elif in_vevent:
            if line.startswith('DTSTART'):
                val = line.split(':')[-1]
                current_event['dtstart'] = parse_ical_date(val)
            elif line.startswith('DTEND'):
                val = line.split(':')[-1]
                current_event['dtend'] = parse_ical_date(val)
            elif line.startswith('SUMMARY'):
                val = line.split(':', 1)[-1]
                current_event['summary'] = val
            elif line.startswith('UID'):
                val = line.split(':', 1)[-1]
                current_event['uid'] = val

    return events


def sync_bien_ical_turnovers(bien: Bien) -> dict:
    """
    Synchronise le flux iCal d'un bien et génère automatiquement les turnovers (commandes Airbnb)
    pour chaque date de départ (DTEND / Check-out) détectée dans le futur.
    """
    if not bien.ical_url:
        return {'success': False, 'message': "Aucune URL iCal configurée pour ce bien."}

    try:
        events = fetch_and_parse_ical(bien.ical_url)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    today = timezone.now().date()
    created_count = 0
    existing_count = 0

    for ev in events:
        checkout_date = ev.get('dtend')
        if not checkout_date or checkout_date < today:
            continue

        # Vérifier si une commande existe déjà pour ce bien à cette date
        cmd_exists = CommandeAirbnb.objects.filter(bien=bien, date_prestation=checkout_date).exists()
        if cmd_exists:
            existing_count += 1
            continue

        # Calculer le tarif prévisionnel
        pricing = calculate_commande_pricing(bien)
        
        # Générer un numéro unique
        cmd_count = CommandeAirbnb.objects.filter(date_prestation__year=checkout_date.year).count() + 1
        num_cmd = f"CMD-{checkout_date.year}-{cmd_count:04d}"

        # Créer la commande automatique issue de la synchro iCal
        CommandeAirbnb.objects.create(
            numero=num_cmd,
            bien=bien,
            date_prestation=checkout_date,
            heure_prestation="11:00",
            creneau='matin',
            nature_linge='depot_ramassage',
            prix_menage=pricing['prix_menage'],
            supplement_zone=pricing['supplement_zone'],
            total_ttc=pricing['total_ttc_hors_linge'],
            statut='saisie',
            source='ical_auto',
            rapport_notes=f"Turnover iCal détecté (Départ voyageur : {ev.get('summary', 'Réservation')})"
        )
        created_count += 1

    bien.ical_derniere_lecture = timezone.now()
    bien.save(update_fields=['ical_derniere_lecture'])

    return {
        'success': True,
        'events_found': len(events),
        'created_turnovers': created_count,
        'existing_turnovers': existing_count,
        'last_synced': bien.ical_derniere_lecture.isoformat()
    }
