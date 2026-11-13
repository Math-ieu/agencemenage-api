from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from clients.models import Client
from airbnb.services.pricing_engine import verifier_seuil_client


class Command(BaseCommand):
    help = "Contrôle mensuel du seuil de 3 biens actifs : préavis 15j et reclassement M+1 vers 240 DH/4h si < 3 biens."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date de contrôle (YYYY-MM-DD, défaut: aujourd'hui).")
        parser.add_argument('--apply-downgrade', action='store_true', help="Forcer la bascule tarif standard après préavis.")

    def handle(self, *args, **options):
        today = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else timezone.localdate()
        )
        apply_downgrade = bool(options.get('apply_downgrade', False))

        clients = Client.objects.filter(biens_airbnb__isnull=False).distinct()
        stats = {'upgrade_conciergerie': 0, 'preavis_reclassement_envoye': 0, 'reclassement_tarif_standard': 0}

        for client in clients:
            res = verifier_seuil_client(client, today=today, apply_downgrade=apply_downgrade)
            act = res.get('action')
            if act in stats:
                stats[act] += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Contrôle seuil {today} : upgrades={stats['upgrade_conciergerie']}, "
                f"préavis={stats['preavis_reclassement_envoye']}, reclassements={stats['reclassement_tarif_standard']}."
            )
        )
