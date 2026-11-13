from datetime import date, timedelta
from django.utils import timezone
from ..models import CommandeAirbnb
from .notification_service import notify_dispatch_20h
from .pdf_service import save_fiche_mission_pdf


def generate_mission_pdf_data(commande: CommandeAirbnb) -> dict:
    """
    Génère la structure de données pour la Fiche de Mission destinée aux intervenantes et runners.
    RÈGLE ABSOLUE : ZÉRO MONTANT FINANCIER APPARENT.
    """
    bien = commande.bien
    intervenantes = []
    if commande.intervenante:
        intervenantes.append(f"{commande.intervenante.first_name} {commande.intervenante.last_name}")
    if commande.intervenante_2:
        intervenantes.append(f"{commande.intervenante_2.first_name} {commande.intervenante_2.last_name} (Renfort Villa)")

    return {
        'numero_commande': commande.numero,
        'date_prestation': str(commande.date_prestation),
        'heure_souhaitee': str(commande.heure_prestation)[:5],
        'creneau': commande.get_creneau_display(),
        'bien': {
            'code': bien.code,
            'nom': bien.nom_bien,
            'ville': bien.ville,
            'quartier': bien.quartier,
            'adresse': bien.adresse,
            'complement': bien.complement_adresse,
            'etage_porte': bien.etage_porte,
            'typologie': bien.get_typologie_display(),
            'chambres': bien.chambres,
            'salles_de_bain': bien.salles_de_bain,
            'couchages': bien.couchages,
            'acces_type': bien.get_acces_type_display(),
            'acces_detail': bien.acces_detail or "Consulter la responsable opérationnelle",
            'consignes': bien.consignes or [],
        },
        'intervenantes': intervenantes,
        'runner': f"{commande.runner.first_name} {commande.runner.last_name}" if commande.runner else "Non assigné",
        'nature_linge': commande.get_nature_linge_display(),
        'options': [opt.get('label') for opt in (commande.options or []) if isinstance(opt, dict)],
        'instructions_cloture': [
            "1. Prendre 4 photos obligatoires (Salon, Chambre, SDB, Cuisine)",
            "2. Vérifier la présence d'objets oubliés et les signaler",
            "3. Laisser les clés dans la boîte sécurisée ou selon les consignes",
            "4. Remettre le sac de linge sale fermé au Runner",
        ],
    }


def dispatch_missions_for_date(target_date: date = None) -> dict:
    """
    Exécute l'envoi des fiches de mission PDF à 20h00 J-1 aux intervenantes et runners.
    """
    if not target_date:
        target_date = timezone.localdate() + timedelta(days=1)

    commandes = CommandeAirbnb.objects.filter(
        date_prestation=target_date,
        statut__in=['remontee_tdb', 'assignee', 'en_cours'],
        fiche_envoyee_le__isnull=True,
    ).select_related('bien', 'intervenante', 'intervenante_2', 'runner')

    dispatched = []
    for cmd in commandes:
        pdf_url = save_fiche_mission_pdf(cmd)
        mission_data = generate_mission_pdf_data(cmd)
        notify_dispatch_20h(cmd, pdf_url=pdf_url)
        cmd.fiche_envoyee_le = timezone.now()
        cmd.save(update_fields=['fiche_envoyee_le', 'updated_at'])
        dispatched.append({
            'commande_id': str(cmd.id),
            'numero': cmd.numero,
            'intervenantes': mission_data['intervenantes'],
            'bien_code': cmd.bien.code,
            'fiche_mission_pdf_url': pdf_url,
            'status': 'dispatched',
        })

    return {
        'date_cible': str(target_date),
        'total_missions': len(dispatched),
        'dispatched_missions': dispatched,
    }
