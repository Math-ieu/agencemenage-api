from django.core.management.base import BaseCommand
from airbnb.models import Bien
from airbnb.services.ical_service import sync_bien_ical_turnovers


class Command(BaseCommand):
    help = "Synchronise les calendriers iCal de tous les biens Airbnb actifs et crée des propositions de turnover."

    def handle(self, *args, **options):
        biens = Bien.objects.filter(is_active=True).exclude(ical_url="").exclude(ical_url__isnull=True)
        total_created = 0
        for bien in biens:
            try:
                res = sync_bien_ical_turnovers(bien)
                if res.get('success'):
                    total_created += res.get('created_turnovers', 0)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[{bien.code}] Synchro OK — {res.get('created_turnovers', 0)} proposition(s)"
                        )
                    )
                else:
                    self.stdout.write(self.style.WARNING(f"[{bien.code}] {res.get('error')}"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"[{bien.code}] Erreur : {exc}"))

        self.stdout.write(self.style.SUCCESS(f"Synchronisation iCal terminée ({total_created} propositions créées)."))
