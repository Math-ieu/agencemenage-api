import html as html_lib
import logging
from django.conf import settings
from django.utils import timezone

from accounts.emails import get_base_html_template, send_resend_email
from demandes.models import AppNotification
from demandes.utils.whatsapp import WhatsAppService

logger = logging.getLogger(__name__)

# Noms canoniques des templates WhatsApp 360Dialog (Section 11)
WHATSAPP_TEMPLATES = {
    'depart_ical': 'airbnb_depart_ical_detecte',
    'commande_confirmee': 'airbnb_commande_confirmee',
    'tdb_18h': 'airbnb_tdb_j1_18h',
    'mission_intervenante': 'airbnb_mission_intervenante_20h',
    'mission_runner': 'airbnb_mission_runner_20h',
    'mission_modifiee': 'airbnb_mission_modifiee',
    'mission_annulee': 'airbnb_mission_annulee',
    'cloture_client': 'airbnb_cloture_client',
    'signalement_client': 'airbnb_signalement_client',
    'remise_etat_client': 'airbnb_remise_etat_client',
    'linge_abime_client': 'airbnb_linge_abime_client',
    'objet_trouve_client': 'airbnb_objet_trouve_client',
    'objet_trouve_signale': 'airbnb_objet_trouve_signale',
    'objet_trouve_relance': 'airbnb_objet_trouve_relance',
    'photos_manquantes': 'airbnb_photos_manquantes',
    'facture_emise': 'airbnb_facture_emise',
    'rappel_paiement': 'airbnb_rappel_paiement',
    'suspension_client': 'airbnb_suspension_client',
    'reactivation_client': 'airbnb_reactivation_client',
    'reclassement_preavis': 'airbnb_reclassement_preavis',
    'hors_delai_commercial': 'airbnb_hors_delai_commercial',
}


def _create_app_notification(
    notif_type: str,
    title: str,
    message: str,
    target_user=None,
    target_roles: list = None,
    commande_airbnb=None,
    lien_url: str = '',
):
    try:
        return AppNotification.objects.create(
            type=notif_type,
            title=title[:255],
            message=message,
            target_user=target_user,
            target_roles=list(target_roles or []),
            commande_airbnb=commande_airbnb,
            lien_url=lien_url[:255],
        )
    except Exception as exc:
        logger.warning("Échec création AppNotification (%s): %s", notif_type, exc)
        return None


def _resolve_public_media_url(url: str = None):
    if not url:
        return None
    raw = str(url).strip()
    if raw.startswith(('http://', 'https://')):
        return raw
    if raw.startswith('/'):
        api_base = str(getattr(settings, 'API_BASE_URL', '') or '').rstrip('/')
        if api_base.startswith(('http://localhost', 'http://127.0.0.1')):
            api_base = ''
        public_base = (
            getattr(settings, 'BACKEND_PUBLIC_URL', '')
            or getattr(settings, 'SITE_URL', '')
            or api_base
            or ''
        ).rstrip('/')
        if public_base:
            return f"{public_base}{raw}"
    return raw


def _send_whatsapp(phone: str, template_key: str, variables: list = None, media_url: str = None, media_type: str = 'document'):
    if not phone or not str(phone).strip():
        return None
    if not getattr(settings, 'D360_API_KEY', ''):
        return None
    template_name = WHATSAPP_TEMPLATES.get(template_key, template_key)
    resolved_media = _resolve_public_media_url(media_url) if media_url else None
    try:
        return WhatsAppService.send_template_message(
            to=str(phone).strip(),
            template_name=template_name,
            media_url=resolved_media,
            media_type=media_type,
            variables=variables or [],
        )
    except Exception as exc:
        logger.warning("Échec envoi WhatsApp (%s -> %s): %s", template_name, phone, exc)
        return None


def _send_email(to_email: str, subject: str, html_body: str):
    if not to_email or not str(to_email).strip():
        return False
    if not getattr(settings, 'RESEND_API_KEY', None):
        return False
    clean_subject = ' '.join(str(subject or '').replace('\r', ' ').replace('\n', ' ').split())
    try:
        html_doc = get_base_html_template(clean_subject, html_body)
        return send_resend_email(to_email.strip(), clean_subject, html_doc)
    except Exception as exc:
        logger.warning("Échec envoi email Resend (%s -> %s): %s", clean_subject, to_email, exc)
        return False


def _safe_client_email_html(client, msg: str, extra_paragraph: str = '') -> str:
    safe_name = html_lib.escape(str(client.display_name or ''))
    safe_msg = html_lib.escape(str(msg or '')).replace('\n', '<br>')
    extra = f"<p>{html_lib.escape(extra_paragraph)}</p>" if extra_paragraph else ""
    return f"<p>Bonjour {safe_name},</p><p>{safe_msg}</p>{extra}"


def _notify_client_portal_users(client, notif_type: str, title: str, message: str, commande_airbnb=None, lien_url: str = ''):
    if not client:
        return
    portal_users = list(client.portail_users.filter(is_active=True))
    for u in portal_users:
        _create_app_notification(
            notif_type=notif_type,
            title=title,
            message=message,
            target_user=u,
            target_roles=[],
            commande_airbnb=commande_airbnb,
            lien_url=lien_url,
        )


def _client_whatsapp_phone(client) -> str:
    if not client:
        return ''
    return (client.whatsapp or client.phone or '').strip()


# ─── 1. Départ détecté sur calendrier iCal ────────────────────────────────
def notify_depart_ical_detecte(bien, commandes: list):
    client = bien.client
    nb = len(commandes)
    dates_str = ', '.join(c.date_prestation.strftime('%d/%m/%Y') for c in commandes[:5])
    title = f"Départ(s) iCal détecté(s) — {bien.code}"
    msg = f"{nb} proposition(s) de turnover créée(s) pour {bien.code} ({dates_str}). Confirmation requise."
    _notify_client_portal_users(
        client, 'airbnb_commande', title, msg,
        commande_airbnb=commandes[0] if commandes else None,
        lien_url='/airbnb/portail',
    )
    if client and client.email:
        _send_email(
            client.email,
            title,
            _safe_client_email_html(
                client,
                msg,
                "Connectez-vous à votre espace conciergerie pour confirmer.",
            ),
        )


# ─── 2. Commande confirmée -> Commercial du compte ─────────────────────────
def notify_commande_confirmee(commande):
    client = commande.bien.client if commande.bien else None
    commercial = client.assigned_commercial if client else None
    title = f"Commande confirmée — {commande.numero}"
    msg = f"Bien {commande.bien.code} le {commande.date_prestation.strftime('%d/%m/%Y')} à {str(commande.heure_prestation)[:5]}."
    if commercial:
        _create_app_notification(
            'airbnb_commande', title, msg,
            target_user=commercial, commande_airbnb=commande, lien_url=f'/airbnb/commandes/{commande.id}',
        )
    else:
        _create_app_notification(
            'airbnb_commande', title, msg,
            target_roles=['commercial', 'responsable_commercial'],
            commande_airbnb=commande, lien_url=f'/airbnb/commandes/{commande.id}',
        )


# ─── 3. Remontée au TDB J-1 18h ───────────────────────────────────────────
def notify_remontee_tdb(commandes_list: list, unassigned_list: list = None):
    if commandes_list:
        _create_app_notification(
            'airbnb_tdb',
            f"Remontée TDB 18h : {len(commandes_list)} intervention(s) pour demain",
            "Les commandes Airbnb de demain sont disponibles au tableau de bord pour assignation.",
            target_roles=['operations'],
            commande_airbnb=commandes_list[0],
            lien_url='/dashboard',
        )
    for cmd in (unassigned_list or []):
        commercial = cmd.bien.client.assigned_commercial if (cmd.bien and cmd.bien.client) else None
        if commercial:
            _create_app_notification(
                'airbnb_tdb',
                f"Commande J-1 sans intervenante — {cmd.numero}",
                f"Le turnover {cmd.numero} ({cmd.bien.code}) pour demain {cmd.date_prestation} n'a pas encore d'intervenante.",
                target_user=commercial,
                commande_airbnb=cmd,
                lien_url=f'/airbnb/commandes/{cmd.id}',
            )


# ─── 4 & 5. Assignation, Dispatch 20h & Fiche modifiée ─────────────────────
def notify_affectation_mission(commande, modified_after_dispatch: bool = False):
    if commande.runner:
        _create_app_notification(
            'airbnb_commande',
            f"Tournée linge assignée — {commande.numero}",
            f"Bien {commande.bien.code} ({commande.bien.quartier}) prévu le {commande.date_prestation.strftime('%d/%m/%Y')}.",
            target_user=commande.runner,
            commande_airbnb=commande,
            lien_url='/airbnb/linge',
        )

    if modified_after_dispatch or commande.fiche_envoyee_le:
        pdf_url = commande.fiche_mission_pdf_url or None
        try:
            from .pdf_service import save_fiche_mission_pdf
            pdf_url = save_fiche_mission_pdf(commande) or pdf_url
        except Exception:
            pass
        for agent in [commande.intervenante, commande.intervenante_2]:
            if agent:
                _send_whatsapp(
                    agent.whatsapp or agent.phone,
                    'mission_modifiee',
                    variables=[agent.first_name, commande.numero, commande.bien.code, str(commande.date_prestation), str(commande.heure_prestation)[:5]],
                    media_url=pdf_url,
                )
        if commande.runner and commande.runner.phone:
            _send_whatsapp(
                commande.runner.phone,
                'mission_modifiee',
                variables=[commande.runner.first_name or 'Runner', commande.numero, commande.bien.code, str(commande.date_prestation), str(commande.heure_prestation)[:5]],
                media_url=pdf_url,
            )


def notify_dispatch_20h(commande, pdf_url: str = None):
    target_pdf = pdf_url or commande.fiche_mission_pdf_url or None
    for agent in [commande.intervenante, commande.intervenante_2]:
        if agent:
            _send_whatsapp(
                agent.whatsapp or agent.phone,
                'mission_intervenante',
                variables=[
                    agent.first_name,
                    commande.numero,
                    commande.bien.code,
                    commande.bien.quartier,
                    commande.date_prestation.strftime('%d/%m/%Y'),
                    str(commande.heure_prestation)[:5],
                ],
                media_url=target_pdf,
            )
    if commande.runner:
        _create_app_notification(
            'airbnb_commande',
            f"Feuille de route demain — {commande.numero}",
            f"Passage linge ({commande.get_nature_linge_display()}) pour {commande.bien.code} à {str(commande.heure_prestation)[:5]}.",
            target_user=commande.runner,
            commande_airbnb=commande,
            lien_url='/airbnb/linge',
        )
        _send_whatsapp(
            commande.runner.phone,
            'mission_runner',
            variables=[
                commande.runner.first_name or 'Runner',
                commande.numero,
                commande.bien.code,
                commande.bien.quartier,
                commande.get_nature_linge_display(),
            ],
            media_url=target_pdf,
        )


# ─── 6. Annulation commande ───────────────────────────────────────────────
def notify_commande_annulee(commande, is_tardive: bool = False):
    suffix = " (annulation tardive)" if is_tardive else ""
    title = f"Commande annulée{suffix} — {commande.numero}"
    msg = f"La commande {commande.numero} ({commande.bien.code}) du {commande.date_prestation.strftime('%d/%m/%Y')} a été annulée."
    _create_app_notification('airbnb_commande', title, msg, target_roles=['operations'], commande_airbnb=commande, lien_url='/airbnb/commandes')
    if commande.runner:
        _create_app_notification('airbnb_commande', title, msg, target_user=commande.runner, commande_airbnb=commande, lien_url='/airbnb/linge')
    for agent in [commande.intervenante, commande.intervenante_2]:
        if agent:
            _send_whatsapp(agent.whatsapp or agent.phone, 'mission_annulee', variables=[agent.first_name, commande.numero, commande.bien.code])


# ─── 7. Signalements & Remise en état ─────────────────────────────────────
def notify_signalement_operations(signalement):
    cmd = signalement.commande
    client = cmd.bien.client if cmd.bien else None
    commercial = client.assigned_commercial if client else None
    motif_lbl = signalement.get_motif_display()

    title = f"Signalement ({motif_lbl}) — {cmd.numero}"
    msg = f"Bien {cmd.bien.code} : {signalement.description or motif_lbl}."
    _create_app_notification('airbnb_incident', title, msg, target_roles=['operations'], commande_airbnb=cmd, lien_url=f'/airbnb/commandes/{cmd.id}')
    if commercial:
        _create_app_notification('airbnb_incident', title, msg, target_user=commercial, commande_airbnb=cmd, lien_url=f'/airbnb/commandes/{cmd.id}')
        if commercial.phone:
            _send_whatsapp(commercial.phone, 'signalement_client', variables=[cmd.numero, cmd.bien.code, motif_lbl])


def notify_signalement_client(signalement):
    cmd = signalement.commande
    client = cmd.bien.client if cmd.bien else None
    if not client:
        return
    title = f"Incident signalé sur {cmd.bien.code} ({cmd.numero})"
    msg = f"Motif : {signalement.get_motif_display()}. {signalement.description}"
    _notify_client_portal_users(client, 'airbnb_incident', title, msg, commande_airbnb=cmd, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'signalement_client', variables=[cmd.numero, cmd.bien.code, signalement.get_motif_display()])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))


def notify_remise_en_etat_client(commande, heures_estimees=0):
    client = commande.bien.client if commande.bien else None
    if not client:
        return
    title = f"Demande d'accord remise en état — {commande.numero}"
    msg = (
        f"Le logement {commande.bien.code} nécessite une remise en état estimée à {heures_estimees}h "
        f"(60 DH/h). Merci de confirmer votre accord par écrit."
    )
    _notify_client_portal_users(client, 'airbnb_incident', title, msg, commande_airbnb=commande, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'remise_etat_client', variables=[commande.numero, commande.bien.code, str(heures_estimees)])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))


# ─── 8, 9, 10. Relances exécution (2h, fin de journée, J+1) ─────────────────
def notify_retard_2h_sans_demarrage(commande):
    _create_app_notification(
        'airbnb_tdb',
        f"Retard démarrage (+2h) — {commande.numero}",
        f"La mission {commande.numero} ({commande.bien.code}) prévue à {str(commande.heure_prestation)[:5]} n'a pas démarré.",
        target_roles=['operations'],
        commande_airbnb=commande,
        lien_url=f'/airbnb/commandes/{commande.id}',
    )


def notify_photos_manquantes_soir(commande):
    for agent in [commande.intervenante, commande.intervenante_2]:
        if agent:
            _send_whatsapp(
                agent.whatsapp or agent.phone,
                'photos_manquantes',
                variables=[agent.first_name, commande.numero, commande.bien.code],
            )


def notify_photos_manquantes_lendemain(commande):
    _create_app_notification(
        'airbnb_tdb',
        f"Escalade photos manquantes — {commande.numero}",
        f"Les 4 photos obligatoires pour {commande.numero} ({commande.bien.code}) manquent toujours à J+1.",
        target_roles=['responsable_operations', 'operations'],
        commande_airbnb=commande,
        lien_url=f'/airbnb/commandes/{commande.id}',
    )


# ─── 11, 12, 13, 14. Linge : écart, contestation, abîmé, filet non prêt ───
def notify_ecart_linge(filet):
    cmd = filet.commande_ramassage
    client = filet.bien.client if filet.bien else None
    commercial = client.assigned_commercial if client else None
    title = f"Écart de comptage linge ({filet.ecart:+d} pcs) — {filet.bien.code}"
    msg = f"Filet {filet.code_filet or filet.id} : écart détecté au recomptage laverie. Facturation bloquée jusqu'à arbitrage."
    _create_app_notification(
        'airbnb_ecart_linge', title, msg,
        target_roles=['responsable_linge', 'operations'],
        commande_airbnb=cmd, lien_url='/airbnb/linge',
    )
    if commercial:
        _create_app_notification('airbnb_ecart_linge', title, msg, target_user=commercial, commande_airbnb=cmd, lien_url='/airbnb/linge')
    else:
        _create_app_notification('airbnb_ecart_linge', title, msg, target_roles=['commercial', 'responsable_commercial'], commande_airbnb=cmd, lien_url='/airbnb/linge')


def notify_contestation_bureau(filet, motif: str):
    _create_app_notification(
        'airbnb_ecart_linge',
        f"Contestation retrait bureau — {filet.code_filet or filet.bien.code}",
        f"Le runner a contesté le retrait du filet {filet.code_filet} : {motif}",
        target_roles=['responsable_linge', 'operations'],
        commande_airbnb=filet.commande_depot,
        lien_url='/airbnb/linge',
    )


def notify_observation_linge_commercial(observation):
    filet = observation.filet
    client = filet.bien.client if filet.bien else None
    commercial = client.assigned_commercial if client else None
    title = f"Observation linge abîmé — {filet.bien.code}"
    msg = f"{observation.article} x{observation.quantite} : {observation.get_motif_display()}."
    if commercial:
        _create_app_notification('airbnb_ecart_linge', title, msg, target_user=commercial, commande_airbnb=filet.commande_ramassage, lien_url='/airbnb/linge')
    else:
        _create_app_notification('airbnb_ecart_linge', title, msg, target_roles=['commercial', 'responsable_commercial'], commande_airbnb=filet.commande_ramassage, lien_url='/airbnb/linge')


def notify_linge_abime_client(observation, custom_message: str = ''):
    filet = observation.filet
    client = filet.bien.client if filet.bien else None
    if not client:
        return
    title = f"Information linge — {filet.bien.code}"
    msg = custom_message or f"Constat sur {observation.article} x{observation.quantite} ({observation.get_motif_display()}). La pièce vous est restituée dans le filet."
    _notify_client_portal_users(client, 'airbnb_ecart_linge', title, msg, commande_airbnb=filet.commande_ramassage, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'linge_abime_client', variables=[filet.bien.code, observation.article, msg])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))


def notify_filet_non_pret(filet, commande_depot=None):
    _create_app_notification(
        'airbnb_ecart_linge',
        f"Alerte filet non prêt — {filet.bien.code}",
        f"Le filet {filet.code_filet or filet.id} n'est pas encore prêt pour la tournée de dépôt.",
        target_roles=['responsable_linge'],
        commande_airbnb=commande_depot,
        lien_url='/airbnb/linge',
    )


# ─── 15. Clôture commande ──────────────────────────────────────────────────
def notify_cloture_commande(commande):
    client = commande.bien.client if commande.bien else None
    commercial = client.assigned_commercial if client else None
    title = f"Prestation clôturée — {commande.numero}"
    msg = f"Le turnover {commande.numero} ({commande.bien.code}) a été clôturé avec {len(commande.photos_cloture or [])} photos."
    if client:
        _notify_client_portal_users(client, 'airbnb_commande', title, msg, commande_airbnb=commande, lien_url='/airbnb/portail')
        _send_whatsapp(_client_whatsapp_phone(client), 'cloture_client', variables=[commande.numero, commande.bien.code])
        if client.email:
            _send_email(client.email, title, _safe_client_email_html(client, msg))
    if commercial:
        _create_app_notification('airbnb_commande', title, msg, target_user=commercial, commande_airbnb=commande, lien_url=f'/airbnb/commandes/{commande.id}')


# ─── 16. Objets trouvés (+ relances J+1 / J+7) ──────────────────────────────
def notify_objet_trouve(objet):
    from django.contrib.auth import get_user_model
    cmd = objet.commande
    client = objet.bien.client if objet.bien else None
    commercial = client.assigned_commercial if client else None
    title = f"Objet trouvé signalé — {objet.bien.code}"
    msg = f"{objet.description} (Pièce : {objet.piece or 'non précisée'}) sur commande {cmd.numero}."
    _create_app_notification('airbnb_incident', title, msg, target_roles=['operations'], commande_airbnb=cmd, lien_url='/airbnb/objets-trouves')
    if commercial:
        _create_app_notification('airbnb_incident', title, msg, target_user=commercial, commande_airbnb=cmd, lien_url='/airbnb/objets-trouves')
        if commercial.phone:
            _send_whatsapp(
                commercial.phone,
                'objet_trouve_signale',
                variables=[objet.bien.code, cmd.numero, objet.description],
                media_url=objet.photo_url or None,
                media_type='image',
            )
    User = get_user_model()
    for ops_user in User.objects.filter(role__in=['responsable_operations', 'charge_operations'], is_active=True).exclude(phone=''):
        _send_whatsapp(
            ops_user.phone,
            'objet_trouve_signale',
            variables=[objet.bien.code, cmd.numero, objet.description],
            media_url=objet.photo_url or None,
            media_type='image',
        )


def notify_objet_trouve_client(objet):
    client = objet.bien.client if objet.bien else None
    if not client:
        return
    title = f"Objet oublié retrouvé — {objet.bien.code}"
    msg = f"Nos équipes ont retrouvé et mis en sécurité : {objet.description}. Merci d'indiquer vos instructions de restitution."
    _notify_client_portal_users(client, 'airbnb_incident', title, msg, commande_airbnb=objet.commande, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'objet_trouve_client', variables=[objet.bien.code, objet.description], media_url=objet.photo_url or None, media_type='image')
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))


def notify_objet_trouve_relance(objet, jalon: str):
    client = objet.bien.client if objet.bien else None
    title = f"Relance {jalon} objet non restitué — {objet.bien.code}"
    msg = f"L'objet '{objet.description}' attend toujours une restitution au client."
    _create_app_notification('airbnb_incident', title, msg, target_roles=['operations', 'commercial', 'responsable_commercial'], commande_airbnb=objet.commande, lien_url='/airbnb/objets-trouves')
    if client:
        _send_whatsapp(_client_whatsapp_phone(client), 'objet_trouve_relance', variables=[objet.bien.code, objet.description, jalon])


# ─── 17 & 18. Facturation, Rappels, Virement, Suspension & Réactivation ─────
def notify_facture_emise(facture):
    client = facture.client
    if not client:
        return
    title = f"Nouvelle facture Airbnb {facture.numero}"
    msg = f"Facture {facture.numero} de {facture.montant_total} MAD émise. Échéance : {facture.date_echeance}."
    _notify_client_portal_users(client, 'airbnb_facture', title, msg, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'facture_emise', variables=[facture.numero, str(facture.montant_total), str(facture.date_echeance)])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))


def notify_rappel_impaye(facture):
    client = facture.client
    if not client:
        return
    title = f"Rappel échéance J-1 — {facture.numero}"
    msg = f"La facture {facture.numero} ({facture.reste_a_payer} MAD) arrive à échéance demain ({facture.date_echeance})."
    _notify_client_portal_users(client, 'airbnb_facture', title, msg, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'rappel_paiement', variables=[facture.numero, str(facture.reste_a_payer), str(facture.date_echeance)])
    if client.assigned_commercial:
        _create_app_notification('airbnb_facture', title, msg, target_user=client.assigned_commercial, lien_url='/airbnb/facturation')


def notify_virement_declare(facture):
    client_name = facture.client.display_name if facture.client else 'Client'
    _create_app_notification(
        'airbnb_facture',
        f"Virement déclaré — {facture.numero}",
        f"{client_name} a déclaré un virement (réf: {facture.virement_reference}) pour la facture {facture.numero}.",
        target_roles=['responsable_facturation'],
        lien_url='/airbnb/facturation',
    )


def notify_suspension_client(client, facture, cancelled_orders: list = None):
    title = f"Compte Airbnb suspendu pour impayé — {client.display_name}"
    msg = f"Échéance dépassée sur la facture {facture.numero}. Les commandes futures planifiées ont été annulées."
    _notify_client_portal_users(client, 'airbnb_suspension', title, msg, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'suspension_client', variables=[client.display_name, facture.numero])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))

    if client.assigned_commercial:
        _create_app_notification('airbnb_suspension', title, msg, target_user=client.assigned_commercial, lien_url='/airbnb/facturation')
    _create_app_notification('airbnb_suspension', title, msg, target_roles=['responsable_facturation'], lien_url='/airbnb/facturation')

    if cancelled_orders:
        _create_app_notification(
            'airbnb_suspension',
            f"{len(cancelled_orders)} commande(s) annulée(s) par suspension ({client.display_name})",
            "Intervenantes et runners libérés suite à la suspension client.",
            target_roles=['operations'],
            commande_airbnb=cancelled_orders[0],
            lien_url='/airbnb/commandes',
        )
        seen_runners = set()
        for cmd in cancelled_orders:
            freed_runner = getattr(cmd, '_freed_runner', None)
            if freed_runner and freed_runner.id not in seen_runners:
                seen_runners.add(freed_runner.id)
                _create_app_notification(
                    'airbnb_suspension',
                    f"Arrêt retiré de la tournée — {cmd.numero}",
                    f"Passage chez {cmd.bien.code} annulé suite à suspension client.",
                    target_user=freed_runner,
                    commande_airbnb=cmd,
                    lien_url='/airbnb/linge',
                )


def notify_reactivation_client(client, reactivable_count: int = 0):
    title = f"Compte Airbnb réactivé — {client.display_name}"
    msg = f"Toutes les factures échues sont soldées. {reactivable_count} commande(s) future(s) sont réactivables."
    _notify_client_portal_users(client, 'airbnb_suspension', title, msg, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'reactivation_client', variables=[client.display_name, str(reactivable_count)])
    if client.assigned_commercial:
        _create_app_notification('airbnb_suspension', title, msg, target_user=client.assigned_commercial, lien_url='/airbnb/commandes')
    if reactivable_count > 0:
        _create_app_notification('airbnb_suspension', title, msg, target_roles=['operations', 'responsable_commercial'], lien_url='/airbnb/commandes')


# ─── 19. Seuil 3 biens & Grille tarifaire ──────────────────────────────────
def notify_reclassement_preavis(client):
    title = f"Préavis de reclassement (< 3 biens) — {client.display_name}"
    msg = (
        "Votre compte est passé sous le seuil des 3 biens confiés. "
        "Le tarif préférentiel reste maintenu jusqu'à la fin du mois en cours avec un préavis écrit de 15 jours."
    )
    _notify_client_portal_users(client, 'airbnb_seuil', title, msg, lien_url='/airbnb/portail')
    _send_whatsapp(_client_whatsapp_phone(client), 'reclassement_preavis', variables=[client.display_name])
    if client.email:
        _send_email(client.email, title, _safe_client_email_html(client, msg))
    if client.assigned_commercial:
        _create_app_notification('airbnb_seuil', title, msg, target_user=client.assigned_commercial, lien_url='/airbnb/biens')
    _create_app_notification('airbnb_seuil', title, msg, target_roles=['responsable_commercial'], lien_url='/airbnb/biens')


def notify_changement_grille_tarifaire(version, veille: bool = False):
    prefix = "Entrée en vigueur demain" if veille else "Nouvelle grille tarifaire"
    _create_app_notification(
        'airbnb_tarif',
        f"{prefix} — Grille {version.version_label}",
        f"La version de grille tarifaire {version.version_label} prend effet le {version.date_entree_vigueur.strftime('%d/%m/%Y')}.",
        target_roles=['commercial', 'responsable_commercial', 'responsable_facturation'],
        lien_url='/airbnb/parametres',
    )
