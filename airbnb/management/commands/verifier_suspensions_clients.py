from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from airbnb.services.billing_engine import verifier_suspensions_et_relances


class Command(BaseCommand):
    help = "Envoie les rappels d'échéance (J-1) et suspend à J+1 les clients impayés (annulant leurs commandes planifiées)."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date de contrôle (YYYY-MM-DD, défaut: aujourd'hui).")

    def handle(self, *args, **options):
        today = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else timezone.localdate()
        )
        res = verifier_suspensions_et_relances(today=today)
        self.stdout.write(
            self.style.SUCCESS(
                f"Contrôle au {today} : {res['reminders']} rappel(s) J-1, {res['suspended']} client(s) suspendu(s)."
            )
        )
