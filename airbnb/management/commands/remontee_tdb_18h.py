from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from airbnb.models import CommandeAirbnb, GrilleTarifaireVersion
from airbnb.services.notification_service import notify_remontee_tdb, notify_changement_grille_tarifaire
from airbnb.services.pricing_engine import activate_due_grille_versions


class Command(BaseCommand):
    help = "Fait remonter à 18h00 J-1 toutes les commandes du lendemain au Tableau de Bord et vérifie les grilles tarifaires."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date de référence (YYYY-MM-DD, défaut: aujourd'hui).")

    def handle(self, *args, **options):
        ref_date = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else timezone.localdate()
        )
        tomorrow = ref_date + timedelta(days=1)

        cmds = list(
            CommandeAirbnb.objects.filter(
                date_prestation=tomorrow,
                statut__in=['saisie', 'confirmee'],
            ).select_related('bien', 'bien__client')
        )
        now = timezone.now()
        for cmd in cmds:
            cmd.statut = 'remontee_tdb'
            cmd.remontee_tdb_le = now
            cmd.save(update_fields=['statut', 'remontee_tdb_le', 'updated_at'])

        unassigned = list(
            CommandeAirbnb.objects.filter(
                date_prestation=tomorrow,
                intervenante__isnull=True,
                statut='remontee_tdb',
            ).select_related('bien')
        )
        if cmds or unassigned:
            notify_remontee_tdb(cmds, unassigned_list=unassigned)

        # Activation des grilles dont la date d'effet est atteinte + notif veille J-1
        activate_due_grille_versions(today=ref_date)
        for grille in GrilleTarifaireVersion.objects.filter(date_entree_vigueur=tomorrow, notified_veille=False):
            notify_changement_grille_tarifaire(grille, veille=True)
            grille.notified_veille = True
            grille.save(update_fields=['notified_veille'])

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(cmds)} commande(s) du {tomorrow} remontée(s) au TDB ({len(unassigned)} non assignée(s))."
            )
        )
