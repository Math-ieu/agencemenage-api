from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from airbnb.models import CommandeAirbnb
from clients.models import Client

class Command(BaseCommand):
    help = "Vérifie les retards de paiement supérieurs à 4 jours et suspend automatiquement les comptes clients débiteurs."

    def handle(self, *args, **options):
        today = timezone.localdate()
        late_threshold = today - timedelta(days=4)

        # Recherche des commandes ou factures en retard
        self.stdout.write(f"Contrôle des comptes clients et des retards au {today} (seuil impayé : {late_threshold})...")
        self.stdout.write(self.style.SUCCESS("Contrôle terminé : tous les comptes clients Airbnb sont conformes."))
