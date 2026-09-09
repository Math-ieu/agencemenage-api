from django.core.management.base import BaseCommand
from demandes.utils.workflow_engine import sync_prestation_workflow


class Command(BaseCommand):
    help = "Synchronise les statuts des prestations de ménage selon les horaires (début/fin) et envoie les alertes WhatsApp"

    def handle(self, *args, **options):
        self.stdout.write("Exécution de sync_prestation_workflow...")
        stats = sync_prestation_workflow()
        self.stdout.write(self.style.SUCCESS(
            f"Terminé avec succès : "
            f"{stats['to_en_cours']} passée(s) en cours, "
            f"{stats['to_a_confirmer']} passée(s) à confirmer, "
            f"{stats.get('reverted_to_en_cours', 0)} alerte(s) désactivée(s) / prolongée(s), "
            f"{stats['alerts_sent']} alerte(s) WhatsApp envoyée(s)."
        ))
