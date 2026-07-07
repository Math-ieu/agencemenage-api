import datetime
import re
import random
import string
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from demandes.models import SubscriptionPlanning, AppNotification, Demande
from demandes.utils.whatsapp import WhatsAppService

def get_monday_py(d):
    return d - datetime.timedelta(days=d.weekday())

def calculate_end_time_py(start_time_str, dur_h):
    if not start_time_str:
        return ''
    try:
        parts = start_time_str.split(':')
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return ''
    import math
    end_h = h + math.floor(dur_h)
    end_m = m + round((dur_h % 1) * 60)
    if end_m >= 60:
        end_h += end_m // 60
        end_m = end_m % 60
    end_h = end_h % 24
    return f"{end_h:02d}:{end_m:02d}"

def get_frequency_count_py(flabel):
    if not flabel:
        return 1
    match = re.match(r'^(\d+)/sem', flabel, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if flabel.lower().strip() == 'quotidien':
        return 7
    return 1

def get_selected_days_for_frequency_py(jours_interv, fcount, start_dayk):
    days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
    sel = [d for d in jours_interv if d in days_order]
    if len(sel) >= fcount:
        return sel[:fcount]
    try:
        start_index = days_order.index(start_dayk)
    except ValueError:
        start_index = 0
    for idx_offset in range(7):
        idx = (start_index + idx_offset) % 7
        day = days_order[idx]
        if day not in sel:
            sel.append(day)
        if len(sel) == fcount:
            break
    return sel

def generate_weeks_for_month_py(start_date, end_date, jours_intervention, heure_debut_str, nb_heures, frequency_label, month_index, start_week_index):
    days_map = {0: 'lundi', 1: 'mardi', 2: 'mercredi', 3: 'jeudi', 4: 'vendredi', 5: 'samedi', 6: 'dimanche'}
    start_day_key = days_map[start_date.weekday()]
    fcount = get_frequency_count_py(frequency_label)
    selected_days = get_selected_days_for_frequency_py(jours_intervention, fcount, start_day_key)
    
    duration = nb_heures or 2
    start_hour = heure_debut_str or '09:00'
    end_hour = calculate_end_time_py(start_hour, duration)
    
    weeks_list = []
    current_monday = get_monday_py(start_date)
    w_index = start_week_index
    
    while current_monday <= end_date:
        week_debut_str = current_monday.isoformat()
        sunday = current_monday + datetime.timedelta(days=6)
        week_fin_str = sunday.isoformat()
        
        jours_dict = {}
        days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
        
        for offset, day_key in enumerate(days_order):
            day_date = current_monday + datetime.timedelta(days=offset)
            day_date_str = day_date.isoformat()
            
            is_selected = (day_key in selected_days and start_date <= day_date <= end_date)
            
            jours_dict[day_key] = {
                'selected': is_selected,
                'heure_debut': start_hour if is_selected else '',
                'heure_fin': end_hour if is_selected else '',
                'demande_id': None
            }
            
        w_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
        weeks_list.append({
            'id': w_id,
            'label': f"Semaine {w_index}",
            'date_debut': week_debut_str,
            'date_fin': week_fin_str,
            'termine': False,
            'jours': jours_dict,
            'mois': month_index
        })
        w_index += 1
        current_monday += datetime.timedelta(days=7)
    return weeks_list

class Command(BaseCommand):
    help = "Envoie des rappels automatiques d'intervention 24h avant aux clients (WhatsApp) et à l'équipe Opérations (in-app)"

    def handle(self, *args, **options):
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        tomorrow_str = tomorrow.isoformat()
        
        days_map = {
            0: 'lundi',
            1: 'mardi',
            2: 'mercredi',
            3: 'jeudi',
            4: 'vendredi',
            5: 'samedi',
            6: 'dimanche'
        }
        tomorrow_day_name = days_map[tomorrow.weekday()]
        
        plannings = SubscriptionPlanning.objects.filter(statut='en_cours')
        self.stdout.write(f"Scannage de {plannings.count()} plannings d'abonnement en cours...")
        
        count = 0
        for planning in plannings:
            # 0. Normalization of weeks & Auto-renewal check
            semaines = planning.semaines or []
            if isinstance(semaines, list):
                # Backwards compatibility: add 'mois' if missing
                for w in semaines:
                    if 'mois' not in w:
                        w['mois'] = 1
                planning.semaines = semaines

            if isinstance(semaines, list) and len(semaines) > 0:
                max_month = 1
                max_date_fin = None
                max_week_label_index = 0
                
                for w in semaines:
                    m = w.get('mois', 1)
                    if m > max_month:
                        max_month = m
                    
                    w_fin = w.get('date_fin')
                    if w_fin:
                        try:
                            d_fin = datetime.date.fromisoformat(w_fin)
                            if max_date_fin is None or d_fin > max_date_fin:
                                max_date_fin = d_fin
                        except ValueError:
                            pass
                    
                    match = re.match(r'Semaine\s+(\d+)', w.get('label', ''), re.IGNORECASE)
                    if match:
                        idx = int(match.group(1))
                        if idx > max_week_label_index:
                            max_week_label_index = idx
                            
                weeks_of_max_month = [w for w in semaines if w.get('mois', 1) == max_month]
                all_weeks_completed = len(weeks_of_max_month) > 0 and all(w.get('termine', False) for w in weeks_of_max_month)
                time_has_passed = max_date_fin and today > max_date_fin
                
                if all_weeks_completed or time_has_passed:
                    next_month_index = max_month + 1
                    start_week_label_index = max_week_label_index + 1
                    
                    if max_date_fin:
                        new_start_date = max_date_fin + datetime.timedelta(days=1)
                    else:
                        new_start_date = planning.date_debut
                        
                    new_end_date = new_start_date + datetime.timedelta(days=29)
                    
                    demande = planning.demande
                    jours_intervention = [j.lower().strip() for j in (planning.jours_intervention or [])]
                    frequency_label = demande.frequency_label or '2/sem'
                    heure_debut_str = planning.heure_debut.strftime('%H:%M') if planning.heure_debut else (demande.heure_intervention or '09:00')
                    if len(heure_debut_str) > 5:
                        heure_debut_str = heure_debut_str[:5]
                        
                    nb_heures = 2
                    if isinstance(demande.formulaire_data, dict):
                        nb_heures = demande.formulaire_data.get('duree') or demande.formulaire_data.get('nb_heures') or 2
                        try:
                            nb_heures = float(nb_heures)
                        except (ValueError, TypeError):
                            nb_heures = 2
                            
                    new_weeks = generate_weeks_for_month_py(
                        start_date=new_start_date,
                        end_date=new_end_date,
                        jours_intervention=jours_intervention,
                        heure_debut_str=heure_debut_str,
                        nb_heures=nb_heures,
                        frequency_label=frequency_label,
                        month_index=next_month_index,
                        start_week_index=start_week_label_index
                    )
                    
                    semaines.extend(new_weeks)
                    planning.semaines = semaines
                    
                    if len(new_weeks) > 0 and new_weeks[-1].get('date_fin'):
                        try:
                            planning.date_fin = datetime.date.fromisoformat(new_weeks[-1].get('date_fin'))
                        except ValueError:
                            planning.date_fin = new_end_date
                    else:
                        planning.date_fin = new_end_date
                        
                    planning.save()
                    
                    # 1. Update the price of the parent demand
                    max_month = next_month_index
                    prev_max_month = max_month - 1 if max_month > 1 else 1
                    
                    original_monthly_price = float(demande.prix) / prev_max_month if demande.prix else 0.0
                    new_prix = original_monthly_price * max_month
                    
                    demande.prix = new_prix
                    if isinstance(demande.formulaire_data, dict):
                        facturation = demande.formulaire_data.get('facturation', {})
                        tva_active = facturation.get('tva_active', False)
                        
                        montant_ttc = new_prix
                        montant_ht = round(montant_ttc / 1.2, 2) if tva_active else montant_ttc
                        
                        facturation['montant_ttc'] = montant_ttc
                        facturation['montant_ht'] = montant_ht
                        facturation['montant'] = montant_ttc
                        demande.formulaire_data['facturation'] = facturation
                    demande.save(update_fields=['prix', 'formulaire_data'])

                    # 2. Generate the invoice document for this new month
                    try:
                        from demandes.utils.document_helpers import generate_demande_document
                        doc = generate_demande_document(demande, 'facture', month_index=next_month_index)
                        
                        # 3. Send the invoice via WhatsApp automatically
                        client_phone = demande.client.phone if demande.client else None
                        if not client_phone and isinstance(demande.formulaire_data, dict):
                            client_phone = demande.formulaire_data.get('whatsapp_phone') or demande.formulaire_data.get('phone')
                            
                        if client_phone:
                            client_name = demande.client.display_name if demande.client else demande.client_name or (demande.formulaire_data.get('nom', 'Client') if isinstance(demande.formulaire_data, dict) else 'Client')
                            from demandes.utils.whatsapp import WhatsAppService
                            
                            formatted_total = f"{original_monthly_price:,.2f}".replace(",", " ")
                            invoice_num = f"AM/F{demande.id:03d}-M{next_month_index}/{datetime.datetime.now().year}"
                            service_display = f"{demande.service} - Mois {next_month_index}"
                            
                            media_url = f"{settings.API_BASE_URL}{doc.fichier.url}" if doc.fichier else None
                            
                            vars = [
                                client_name,
                                invoice_num,
                                datetime.date.today().strftime('%d/%m/%Y'),
                                service_display,
                                formatted_total
                            ]
                            
                            WhatsAppService.send_template_message(
                                to=client_phone,
                                template_name='facture_client',
                                media_url=media_url,
                                media_type='document',
                                variables=vars
                            )
                            self.stdout.write(f"WhatsApp envoyé pour planning ID {planning.id} (Mois {next_month_index})")
                    except Exception as ex:
                        self.stderr.write(f"Erreur lors de la génération/envoi auto du document pour planning ID {planning.id}: {ex}")
                    
                    self.stdout.write(f"Planning ID {planning.id} (Client {demande.client.display_name if demande.client else 'Sans client'}): renouvellement automatique du Mois {next_month_index} (du {new_start_date.isoformat()} au {planning.date_fin.isoformat()})")

            # Check if tomorrow is one of the intervention days
            is_active_for_tomorrow = False
            heure_debut_obj = None
            heure_fin_obj = None
            target_week = None
            target_day_info = None
            
            if planning.semaines and isinstance(planning.semaines, list) and len(planning.semaines) > 0:
                # Search for a matching week in semaines
                for week in planning.semaines:
                    if not isinstance(week, dict):
                        continue
                    # Check if week is completed / not active
                    if week.get('termine', False) or not week.get('en_cours', True):
                        continue
                        
                    w_debut = week.get('date_debut')
                    w_fin = week.get('date_fin')
                    
                    if not w_debut:
                        continue
                        
                    try:
                        d_debut = datetime.date.fromisoformat(w_debut)
                        d_fin = datetime.date.fromisoformat(w_fin) if w_fin else None
                    except (ValueError, TypeError):
                        continue
                        
                    if d_debut > tomorrow:
                        continue
                    if d_fin:
                        if d_fin < tomorrow:
                            continue
                        if d_fin == tomorrow and d_fin > d_debut:
                            continue
                        
                    # This week covers tomorrow! Check the day selection
                    jours_dict = week.get('jours', {})
                    day_info = jours_dict.get(tomorrow_day_name, {})
                    if day_info and day_info.get('selected'):
                        is_active_for_tomorrow = True
                        active_heure_debut = day_info.get('heure_debut')
                        active_heure_fin = day_info.get('heure_fin')
                        target_week = week
                        target_day_info = day_info
                        
                        def parse_time_str(t_str):
                            if not t_str:
                                return None
                            try:
                                parts = t_str.split(':')
                                return datetime.time(int(parts[0]), int(parts[1]))
                            except (ValueError, IndexError, TypeError):
                                return None
                        heure_debut_obj = parse_time_str(active_heure_debut)
                        heure_fin_obj = parse_time_str(active_heure_fin)
                        break
                if not is_active_for_tomorrow:
                    continue
            else:
                # Fallback to the flat structure
                # Check dates bounds of the main planning
                if planning.date_debut > tomorrow:
                    continue
                if planning.date_fin and planning.date_fin < tomorrow:
                    continue
                    
                jours = [j.lower().strip() for j in planning.jours_intervention]
                if tomorrow_day_name not in jours:
                    continue
                
                # Use flat times
                heure_debut_obj = planning.heure_debut
                heure_fin_obj = planning.heure_fin
                
            # Check if notification already sent for tomorrow
            sent_dates = planning.notification_sent_dates or []
            if tomorrow_str in sent_dates:
                continue
                
            # We need to send notification!
            demande = planning.demande
            client = demande.client
            if not client:
                self.stderr.write(f"Planning ID {planning.id} n'a pas de client associé.")
                continue
                
            client_name = client.display_name
            client_phone = client.phone
            service_name = demande.service
            
            heure_debut_str = heure_debut_obj.strftime('%H:%M') if heure_debut_obj else "Non spécifiée"
            heure_fin_str = heure_fin_obj.strftime('%H:%M') if heure_fin_obj else ""
            heure_str = f"{heure_debut_str} à {heure_fin_str}" if heure_fin_str else heure_debut_str
            
            with transaction.atomic():
                existing_demande_id = target_day_info.get('demande_id') if target_day_info else None
                new_demande = None
                
                if existing_demande_id:
                    try:
                        new_demande = Demande.objects.get(pk=existing_demande_id)
                        self.stdout.write(f"Rappel pour demande existante #{new_demande.id} pour demain.")
                    except Demande.DoesNotExist:
                        new_demande = None
                        
                if not new_demande:
                    # Calculate session price
                    total_price = float(demande.prix) if demande.prix else 0
                    session_price = total_price
                    
                    from decimal import Decimal
                    tva_active = demande.formulaire_data.get('facturation', {}).get('tva_active', False) if isinstance(demande.formulaire_data, dict) else False
                    parent_facturation = demande.formulaire_data.get('facturation', {}) if isinstance(demande.formulaire_data, dict) else {}
                    session_price_ht = float(parent_facturation.get('montant_ht', session_price))
                    if tva_active and session_price_ht == session_price:
                        session_price_ht = round(session_price / 1.2, 2)
                    
                    new_formulaire_data = dict(demande.formulaire_data) if isinstance(demande.formulaire_data, dict) else {}
                    new_formulaire_data['subscription_month'] = target_week.get('mois', 1) if target_week else 1
                    new_formulaire_data['frequence'] = demande.frequency_label or 'Abonnement'
                    new_formulaire_data['frequency'] = 'abonnement'
                    new_formulaire_data['date'] = tomorrow_str
                    new_formulaire_data['heure'] = heure_debut_obj.strftime('%H:%M') if heure_debut_obj else ''
                    new_formulaire_data['montant'] = session_price
                    new_formulaire_data['total'] = session_price
                    new_formulaire_data['facturation'] = {
                        'montant_ht': session_price_ht,
                        'tva_active': tva_active,
                        'montant_ttc': session_price,
                        'montant_verse': 0,
                        'facturation_annulee': False,
                        'statut_paiement_ui': 'non_confirme',
                        'mode_paiement': demande.mode_paiement,
                        'part_agence': 0,
                        'parts_repartition': [],
                    }
                    
                    # Create the new Demande
                    new_demande = Demande.objects.create(
                        client=demande.client,
                        service=demande.service,
                        segment=demande.segment,
                        source=Demande.BACKOFFICE,
                        statut=Demande.ENCOURS,
                        frequency=Demande.ABONNEMENT,
                        frequency_label=demande.frequency_label or "Abonnement",
                        date_intervention=tomorrow,
                        heure_intervention=heure_debut_obj.strftime('%H:%M') if heure_debut_obj else '',
                        prix=Decimal(str(session_price)),
                        part_agence=Decimal('0'),
                        mode_paiement=demande.mode_paiement,
                        statut_paiement=Demande.NON_PAYE,
                        note_commercial=demande.note_commercial,
                        note_operationnel=demande.note_operationnel,
                        preference_horaire=demande.preference_horaire,
                        formulaire_data=new_formulaire_data,
                        assigned_to=demande.assigned_to,
                        created_by=demande.created_by,
                        parent_demande=demande,
                    )
                    
                    # Update target_day_info and planning JSON
                    if target_day_info:
                        target_day_info['demande_id'] = new_demande.id
                        planning.semaines = list(planning.semaines)
                        planning.save()

                # 1. Create In-App Notification pointing to the new/existing Demande
                app_notif = AppNotification.objects.create(
                    type='rappel_intervention',
                    title=f"Rappel intervention demain chez {client_name}",
                    message=f"Une intervention est prévue demain ({tomorrow.strftime('%d/%m/%Y')}) de {heure_str} chez {client_name} pour le service '{service_name}'.",
                    demande=new_demande,
                    target_roles=["operations", "admin"]
                )
                
                # 2. Send WhatsApp notification
                if client_phone:
                    # Var 1: client name, Var 2: service, Var 3: date, Var 4: heure
                    variables = [
                        client_name,
                        service_name,
                        tomorrow.strftime('%d/%m/%Y'),
                        heure_str
                    ]
                    
                    # Call WhatsApp API
                    res = WhatsAppService.send_template_message(
                        to=client_phone,
                        template_name='rappel_intervention_24h',
                        variables=variables
                    )
                    if res:
                        self.stdout.write(f"WhatsApp envoyé avec succès au {client_phone}")
                    else:
                        self.stderr.write(f"Échec de l'envoi WhatsApp au {client_phone}")
                else:
                    self.stderr.write(f"Le client {client_name} n'a pas de numéro de téléphone.")
                
                # 3. Update planning sent dates
                sent_dates.append(tomorrow_str)
                planning.notification_sent_dates = sent_dates
                planning.save()
                
                count += 1
                self.stdout.write(f"Notification et Demande #{new_demande.id} liées pour le client {client_name} (Planning ID {planning.id})")
                
        self.stdout.write(f"Terminé. {count} interventions notifiées.")
