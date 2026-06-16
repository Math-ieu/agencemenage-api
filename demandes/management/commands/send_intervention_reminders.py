import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from demandes.models import SubscriptionPlanning, AppNotification, Demande
from demandes.utils.whatsapp import WhatsAppService

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
