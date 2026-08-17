from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from airbnb.models import CommandeAirbnb

class Command(BaseCommand):
    help = "Fait remonter automatiquement à 18h00 J-1 toutes les commandes du lendemain au Tableau de Bord."

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        cmds = CommandeAirbnb.objects.filter(
            date_prestation=tomorrow,
            statut='saisie'
        )

        count = cmds.update(statut='remontee_tdb')
        self.stdout.write(self.style.SUCCESS(f"{count} commande(s) du {tomorrow} passée(s) au statut 'remontee_tdb' pour assignation."))

        # Vérification des commandes non pourvues
        unassigned = CommandeAirbnb.objects.filter(
            date_prestation=tomorrow,
            intervenante__isnull=True
        ).exclude(statut='annulee')

        if unassigned.exists():
            self.stdout.write(self.style.WARNING(f"⚠️ Alerte : {unassigned.count()} commande(s) pour demain n'ont pas encore d'intervenante assignée !"))
