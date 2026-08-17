from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from airbnb.models import CommandeAirbnb
from airbnb.services.whatsapp_service import generate_mission_pdf_data

class Command(BaseCommand):
    help = "Prépare le dispatch WhatsApp des fiches de mission sans prix aux intervenantes à 20h00 J-1."

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        cmds = CommandeAirbnb.objects.filter(
            date_prestation=tomorrow,
            statut__in=['assignee', 'en_cours']
        )

        self.stdout.write(f"Préparation des fiches de mission pour {cmds.count()} commande(s) assignée(s) du {tomorrow}...")

        dispatched = 0
        for cmd in cmds:
            pdf_data = generate_mission_pdf_data(cmd)
            # Logique de préparation de la charge utile WhatsApp
            self.stdout.write(f"  • Mission {cmd.numero} -> {cmd.intervenante.nom if cmd.intervenante else 'N/A'} ({cmd.bien.code} - {cmd.bien.nom_bien})")
            dispatched += 1

        self.stdout.write(self.style.SUCCESS(f"{dispatched} fiche(s) de mission préparée(s) et prêtes à l'envoi."))
