from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from airbnb.models import CommandeAirbnb, ObjetTrouve
from airbnb.services.notification_service import (
    notify_retard_2h_sans_demarrage,
    notify_photos_manquantes_soir,
    notify_photos_manquantes_lendemain,
    notify_objet_trouve_relance,
)


class Command(BaseCommand):
    help = "Exécute les relances automatiques : retard démarrage +2h, photos manquantes soir/lendemain, et relances objets trouvés J+1/J+7."

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help="Date de référence (YYYY-MM-DD, défaut: aujourd'hui).")
        parser.add_argument('--hour', type=int, help="Heure simulée (0-23) pour le contrôle des retards/fin de journée.")

    def handle(self, *args, **options):
        local_now = timezone.localtime()
        ref_date = (
            datetime.strptime(options['date'], '%Y-%m-%d').date()
            if options.get('date')
            else local_now.date()
        )
        ref_hour = options['hour'] if options.get('hour') is not None else local_now.hour
        ref_now = timezone.make_aware(datetime.combine(ref_date, local_now.time().replace(hour=max(0, min(23, ref_hour)), minute=0)))

        # 1. Retard +2h sans démarrage
        retard_2h_count = 0
        for cmd in CommandeAirbnb.objects.filter(
            date_prestation=ref_date,
            statut='assignee',
            demarrage_reel_le__isnull=True,
            relance_2h_envoyee=False,
        ).select_related('bien', 'intervenante'):
            sched_dt = timezone.make_aware(datetime.combine(cmd.date_prestation, cmd.heure_prestation))
            if ref_now >= sched_dt + timedelta(hours=2):
                notify_retard_2h_sans_demarrage(cmd)
                cmd.relance_2h_envoyee = True
                cmd.save(update_fields=['relance_2h_envoyee', 'updated_at'])
                retard_2h_count += 1

        # 2. Photos manquantes fin de journée (>= 19h)
        photos_soir_count = 0
        if ref_hour >= 19:
            for cmd in CommandeAirbnb.objects.filter(
                date_prestation=ref_date,
                statut='en_cours',
                relance_fin_journee_envoyee=False,
            ).select_related('bien'):
                if len(cmd.photos_cloture or []) < 4:
                    notify_photos_manquantes_soir(cmd)
                    cmd.relance_fin_journee_envoyee = True
                    cmd.save(update_fields=['relance_fin_journee_envoyee', 'updated_at'])
                    photos_soir_count += 1

        # 3. Photos manquantes le lendemain
        yesterday = ref_date - timedelta(days=1)
        photos_lendemain_count = 0
        for cmd in CommandeAirbnb.objects.filter(
            date_prestation=yesterday,
            statut='en_cours',
            relance_lendemain_envoyee=False,
        ).select_related('bien'):
            if len(cmd.photos_cloture or []) < 4:
                notify_photos_manquantes_lendemain(cmd)
                cmd.relance_lendemain_envoyee = True
                cmd.save(update_fields=['relance_lendemain_envoyee', 'updated_at'])
                photos_lendemain_count += 1

        # 4. Objets trouvés : relances J+1 et J+7 si aucune instruction client
        obj_j1_count = 0
        obj_j7_count = 0
        active_objs = ObjetTrouve.objects.filter(
            statut__in=['trouve', 'mis_en_securite', 'signale_client'],
            instruction_client='',
        ).select_related('bien', 'bien__client')

        for obj in active_objs:
            base_dt = obj.signale_le or obj.created_at
            base_date = base_dt.date() if hasattr(base_dt, 'date') else ref_date
            age_days = (ref_date - base_date).days
            if age_days >= 1 and obj.relance_j1_le is None:
                notify_objet_trouve_relance(obj, 'J+1')
                obj.relance_j1_le = timezone.now()
                obj.save(update_fields=['relance_j1_le', 'updated_at'])
                obj_j1_count += 1
            if age_days >= 7 and obj.relance_j7_le is None:
                notify_objet_trouve_relance(obj, 'J+7')
                obj.relance_j7_le = timezone.now()
                obj.save(update_fields=['relance_j7_le', 'updated_at'])
                obj_j7_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Relances {ref_date} : retard+2h={retard_2h_count}, photos_soir={photos_soir_count}, "
                f"photos_lendemain={photos_lendemain_count}, objets_J+1={obj_j1_count}, objets_J+7={obj_j7_count}."
            )
        )
