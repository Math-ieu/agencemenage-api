import datetime
from django.core.management.base import BaseCommand
from demandes.models import SubscriptionPlanning, AppNotification, FeteReligieuse
from demandes.utils.whatsapp import WhatsAppService

DAYS_MAP = {0: 'lundi', 1: 'mardi', 2: 'mercredi', 3: 'jeudi', 4: 'vendredi', 5: 'samedi', 6: 'dimanche'}


class Command(BaseCommand):
    help = (
        "Notifie le client (WhatsApp) et la chargée de clientèle (in-app) lorsqu'un passage "
        "d'abonnement tombe dans une période de suspension liée à une fête religieuse (Section 4.2 du brief)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--horizon', type=int, default=7, help="Nombre de jours scannés en avant (défaut 7)")

    def handle(self, *args, **options):
        horizon = options['horizon']
        today = datetime.date.today()

        plannings = SubscriptionPlanning.objects.filter(statut='en_cours').select_related('demande', 'demande__client')
        self.stdout.write(f"Scan de {plannings.count()} planning(s) sur {horizon} jours...")

        sent = 0
        for planning in plannings:
            demande = planning.demande
            client = demande.client if demande else None
            jours = [str(j).lower() for j in (planning.jours_intervention or [])]
            if not jours:
                continue

            sent_dates = list(planning.notification_sent_dates or [])
            modified = False

            for offset in range(0, horizon + 1):
                d = today + datetime.timedelta(days=offset)

                # Hors période du planning ?
                if planning.date_debut and d < planning.date_debut:
                    continue
                if planning.date_fin and d > planning.date_fin:
                    continue
                # Jour d'intervention ?
                if DAYS_MAP[d.weekday()] not in jours:
                    continue
                # Tombe dans une période de suspension ?
                fete = FeteReligieuse.suspension_pour(d)
                if not fete:
                    continue

                key = f"ferie:{d.isoformat()}"
                if key in sent_dates:
                    continue

                client_name = client.display_name if client else (getattr(demande, 'client_name', None) or 'Client')
                fete_label = fete.get_type_display()
                debut = fete.debut_suspension.strftime('%d/%m/%Y')
                fin = fete.fin_suspension.strftime('%d/%m/%Y')
                passage = d.strftime('%d/%m/%Y')

                # 1. Notification interne (chargée de clientèle / opérations)
                AppNotification.objects.create(
                    type='info',
                    title=f"Passage suspendu ({fete_label}) — {client_name}",
                    message=(
                        f"Le passage du {passage} pour « {demande.service} » est suspendu "
                        f"({fete_label}, période du {debut} au {fin}). À reporter ou annuler avec le client."
                    ),
                    demande=demande,
                    target_roles=['operations', 'admin'],
                )

                # 2. WhatsApp client
                client_phone = (client.phone if client else None) or (demande.formulaire_data or {}).get('whatsapp_phone')
                if client_phone:
                    variables = [client_name, fete_label, debut, fin, passage]
                    res = WhatsAppService.send_template_message(
                        to=client_phone,
                        template_name='notif_suspension_ferie_client',
                        variables=variables,
                    )
                    if res:
                        self.stdout.write(f"WhatsApp suspension envoyé à {client_phone} (passage {passage})")
                    else:
                        self.stderr.write(f"Échec WhatsApp suspension {client_phone} (passage {passage})")
                else:
                    self.stderr.write(f"Client sans téléphone — notification interne seule (passage {passage})")

                sent_dates.append(key)
                modified = True
                sent += 1

            if modified:
                planning.notification_sent_dates = sent_dates
                planning.save(update_fields=['notification_sent_dates'])

        self.stdout.write(self.style.SUCCESS(f"Terminé — {sent} notification(s) de suspension."))
