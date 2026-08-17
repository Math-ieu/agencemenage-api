import logging
from django.core.management.base import BaseCommand
from airbnb.models import Bien
from airbnb.services.ical_service import sync_bien_ical_turnovers

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Synchronise les calendriers iCal de tous les biens Airbnb actifs et crée les propositions de turnover."

    def handle(self, *args, **options):
        biens = Bien.objects.filter(is_active=True).exclude(ical_url="").exclude(ical_url__isnull=True)
        self.stdout.write(f"Début de synchronisation iCal pour {biens.count()} biens...")

        total_created = 0
        for bien in biens:
            try:
                res = sync_bien_ical_turnovers(bien)
                if res.get('success'):
                    created = res.get('created_turnovers', 0)
                    total_created += created
                    self.stdout.write(self.style.SUCCESS(f"[{bien.code}] Synchro OK — {created} turnover(s) créés"))
                else:
                    self.stdout.write(self.style.WARNING(f"[{bien.code}] {res.get('error')}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[{bien.code}] Erreur : {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"Synchronisation terminée avec succès. Total créés : {total_created}"))
