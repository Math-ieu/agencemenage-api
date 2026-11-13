from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from airbnb.services.billing_engine import generer_factures_cycle


class Command(BaseCommand):
    help = "Génère automatiquement les factures Airbnb (quinzaine 11/26 ou mensuel 26) et exécute les bascules probatoires."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date du cycle de facturation (YYYY-MM-DD, défaut: aujourd'hui).")
        parser.add_argument('--client', type=int, help="ID client spécifique (optionnel).")

    def handle(self, *args, **options):
        target_date = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else timezone.localdate()
        )
        res = generer_factures_cycle(target_date=target_date, client_id=options.get('client'))
        self.stdout.write(
            self.style.SUCCESS(
                f"Cycle {res['date']} : {len(res['factures'])} facture(s) générée(s), "
                f"{len(res['bascules'])} client(s) basculé(s) en mensuel."
            )
        )
