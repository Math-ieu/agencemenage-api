from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from airbnb.models import CommandeAirbnb, FiletLinge
from airbnb.services.whatsapp_service import dispatch_missions_for_date
from airbnb.services.notification_service import notify_filet_non_pret


class Command(BaseCommand):
    help = "Envoie à 20h00 J-1 les fiches de mission PDF (sans montant) via WhatsApp et signale les filets non prêts."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date de prestation cible (YYYY-MM-DD, défaut: demain).")

    def handle(self, *args, **options):
        target_date = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else timezone.localdate() + timedelta(days=1)
        )

        res = dispatch_missions_for_date(target_date=target_date)

        # Vérifier les filets non prêts pour les commandes de dépôt demain
        depot_cmds = CommandeAirbnb.objects.filter(
            date_prestation=target_date,
            nature_linge__in=['depot_ramassage', 'depot_seul'],
            statut__in=['remontee_tdb', 'assignee', 'en_cours'],
        ).select_related('bien')

        alerts = 0
        for cmd in depot_cmds:
            unready = FiletLinge.objects.filter(
                bien=cmd.bien,
                statut__in=['compte_runner', 'en_laverie', 'en_traitement'],
            ).first()
            ready_exists = FiletLinge.objects.filter(
                bien=cmd.bien,
                statut__in=['pret', 'remis_runner'],
            ).exists()
            if unready and not ready_exists:
                notify_filet_non_pret(unready, commande_depot=cmd)
                alerts += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{res['total_missions']} fiche(s) dispatchée(s) pour {target_date} ({alerts} alerte(s) filet non prêt)."
            )
        )
