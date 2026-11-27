from django.conf import settings
from django.utils import timezone
from rest_framework import permissions


def map_role_to_db_key(role):
    if not role:
        return ''
    r = role.lower().strip()
    if r == 'admin':
        return 'Admin'
    if r in ['moderateur', 'modérateur']:
        return 'Moderateur'
    if r in ['responsable commercial', 'responsable_commercial']:
        return 'Responsable commercial'
    if r == 'commercial':
        return 'commercial'
    if r in ['responsable des opérations', 'responsable_operations']:
        return 'Responsable des Opérations'
    if r in ['chargée des opérations', 'charge_operations']:
        return 'Chargée des Opérations'
    if r in ['opérationnel', 'operationnel']:
        return 'Opérationnel'
    if r in ['responsable facturation', 'responsable_facturation']:
        return 'Responsable Facturation'
    if r == 'runner':
        return 'Runner'
    if r in ['responsable linge', 'responsable_linge']:
        return 'Responsable Linge'
    if r in ['client conciergerie', 'client_conciergerie']:
        return 'Client Conciergerie'
    return role


def is_exempt_from_ownership(user):
    if not user or not user.is_authenticated:
        return False
    return user.role in ['admin', 'moderateur', 'responsable_commercial', 'responsable_operations', 'charge_operations']


AIRBNB_VIEWSETS = {
    'AirbnbConfigViewSet',
    'GrilleTarifaireVersionViewSet',
    'BienViewSet',
    'CommandeAirbnbViewSet',
    'FiletLingeViewSet',
    'ObservationLingeViewSet',
    'SignalementCommandeViewSet',
    'ObjetTrouveViewSet',
    'JournalAuditAirbnbViewSet',
    'FacturationAirbnbViewSet',
    'AirbnbPhotoUploadView',
}

_AIRBNB_CONFIG_READ_ROLES = {
    'moderateur', 'responsable_commercial', 'commercial',
    'responsable_facturation', 'responsable_operations',
    'charge_operations',
}

_AIRBNB_PHOTO_ROLES = {
    'moderateur', 'responsable_commercial', 'commercial',
    'responsable_facturation', 'responsable_operations',
    'charge_operations', 'runner', 'responsable_linge',
    'client_conciergerie',
}

_AIRBNB_AUDIT_READ_ROLES = {
    'moderateur', 'responsable_commercial',
    'responsable_facturation', 'responsable_operations',
}

AIRBNB_ONLY_ROLES = {
    'client_conciergerie', 'runner', 'responsable_linge', 'responsable_facturation',
}


class RoleBasedPermission(permissions.BasePermission):
    message = "Vous n'avez pas l'autorisation d'effectuer cette action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
            
        role = user.role
        
        # 1. Admin a tous les accès
        if role == 'admin':
            return True
            
        action = getattr(view, 'action', None)
        if not action:
            method = request.method.upper()
            if method in ['GET', 'HEAD', 'OPTIONS']:
                action = 'list'
            elif method == 'POST':
                action = 'create'
            elif method in ['PUT', 'PATCH']:
                action = 'update'
            elif method == 'DELETE':
                action = 'destroy'
                
        view_name = view.__class__.__name__

        # 1b. Cloisonnement strict des rôles purement Airbnb (aucun accès aux ViewSets classiques)
        if role in AIRBNB_ONLY_ROLES:
            if view_name in AIRBNB_VIEWSETS:
                return self._has_airbnb_permission(request, view_name, action, role)
            if view_name == 'AppNotificationViewSet':
                return action in ['list', 'retrieve', 'update', 'partial_update']
            if view_name not in ['ClientViewSet', 'FactureViewSet', 'PaiementViewSet']:
                return False

        # Récupérer les permissions de la base de données
        from accounts.models import RolePermission
        db_role = map_role_to_db_key(role)
        try:
            rp = RolePermission.objects.filter(role=db_role).first()
            permissions_list = rp.permissions if rp else []
        except Exception:
            permissions_list = []

        def has_perm(perm_key):
            return perm_key in permissions_list

        # 2. Gestion des utilisateurs (UserViewSet)
        if view_name == 'UserViewSet':
            if action == 'create':
                return has_perm('creer_utilisateurs') or has_perm('parametres_globaux')
            elif action in ['list', 'retrieve']:
                return (
                    has_perm('consulter_utilisateurs') or
                    has_perm('parametres_globaux') or
                    has_perm('affecter_commercial') or
                    has_perm('creer_geste_commercial')
                )
            elif action in ['update', 'partial_update']:
                return has_perm('activer_desactiver_utilisateurs') or has_perm('parametres_globaux')
            elif action == 'destroy':
                return has_perm('parametres_globaux')
            return False

        # 3. Gestion des clients (ClientViewSet)
        if view_name == 'ClientViewSet':
            if role in ['runner', 'responsable_linge']:
                return False
            if role == 'client_conciergerie':
                return action in ['list', 'retrieve']
            if role == 'responsable_facturation':
                return action in ['list', 'retrieve', 'action_logs']
            if action == 'destroy':
                return has_perm('delete_client')
            
            if action in ['update', 'partial_update']:
                is_blacklisting = 'is_blacklisted' in request.data
                other_fields = [k for k in request.data.keys() if k != 'is_blacklisted']
                if is_blacklisting and not has_perm('blacklister_clients'):
                    return False
                if other_fields and not has_perm('modifier_clients'):
                    return False
                if not is_blacklisting and not other_fields:
                    return has_perm('modifier_clients') or has_perm('blacklister_clients')
                return True
                
            if action == 'create':
                return has_perm('modifier_clients')
                
            if action == 'affecter':
                return has_perm('affectation_client') or has_perm('affecter_commercial')
                
            if action in ['list', 'retrieve', 'action_logs', 'assignments']:
                return has_perm('consulter_clients') or has_perm('consulter_compte_client')

            return False

        # 4. Gestion des profils candidats (AgentViewSet)
        if view_name == 'AgentViewSet':
            if action == 'destroy':
                return has_perm('supprimer_profil')
                
            if action in ['update', 'partial_update']:
                is_blacklisting = 'is_blacklisted' in request.data
                is_assigning = 'assigned_to' in request.data
                
                has_modify = has_perm('modifier_agents')
                has_assign = has_perm('assigner_charge_profil')
                has_blacklist = has_perm('blacklister_agents')
                
                if is_blacklisting and not has_blacklist:
                    return False
                if is_assigning and not has_assign:
                    return False
                    
                other_fields = [k for k in request.data.keys() if k not in ['assigned_to', 'is_blacklisted']]
                if other_fields and not has_modify:
                    return False
                if not is_blacklisting and not is_assigning and not other_fields:
                    return has_modify
                return True
                
            if action == 'create':
                return has_perm('creer_agents')

            if action == 'affecter':
                return has_perm('assigner_charge_profil') or has_perm('modifier_agents')
                
            if action in ['list', 'retrieve', 'history', 'assignments']:
                return has_perm('consulter_agents')

            return False

        # 5. Gestion des demandes (DemandeViewSet)
        if view_name == 'DemandeViewSet':
            if action == 'destroy':
                return has_perm('supprimer_demande_dashboard')
                
            if action == 'envoyer_profil':
                return has_perm('postuler_demande')

            if action == 'retirer_profil':
                return has_perm('retirer_profil_demande')
                
            if action == 'valider':
                # Allowed at view level, will check ownership/assignment in has_object_permission
                return True

            if action == 'confirmer_cao':
                return has_perm('confirmation_avant_operation') or has_perm('traiter_demandes_affectees') or has_perm('creer_valider_demande')
                
            if action == 'annuler':
                return has_perm('refuser_demande') or has_perm('annulation_demande') or has_perm('traiter_demandes_affectees') or has_perm('creer_valider_demande')
                
            if action == 'nrp':
                return has_perm('consulter_demandes') or has_perm('modifier_demande') or has_perm('traiter_demandes_affectees') or has_perm('creer_valider_demande')
                
            if action == 'affecter':
                return has_perm('affecter_commercial') or has_perm('traiter_demandes_affectees')

            if action == 'affecter_operations':
                return has_perm('assigner_charge_operation')
                
            if action == 'annuler_facturation':
                return has_perm('facturation_annulee')
                
            if action in ['appliquer_geste', 'geste_commercial']:
                return has_perm('creer_geste_commercial') or has_perm('geste_commercial')
                
            if action == 'create':
                return has_perm('creer_valider_demande') or has_perm('creer_demande')
                
            if action in ['update', 'partial_update']:
                return (
                    has_perm('traiter_demandes_affectees') or
                    has_perm('creer_valider_demande') or
                    has_perm('modifier_demande') or 
                    has_perm('editer_besoin') or 
                    has_perm('editer_besoin_agence') or 
                    has_perm('editer_besoin_facture') or 
                    has_perm('modifier_facture')
                )
                
            if action in ['list', 'retrieve']:
                return (
                    has_perm('traiter_demandes_affectees') or
                    has_perm('creer_valider_demande') or
                    has_perm('consulter_demandes') or
                    has_perm('consulter_dashboard')
                )

            if action in ['historique', 'notifications_urgentes']:
                return (
                    has_perm('consulter_historique_global') or
                    has_perm('consulter_dashboard') or
                    has_perm('consulter_demandes') or
                    has_perm('traiter_demandes_affectees') or
                    has_perm('creer_valider_demande')
                )

            if action == 'export_csv':
                return has_perm('exporter_historique_csv') or has_perm('consulter_historique_global')

            if action == 'sync_workflow':
                return (
                    has_perm('consulter_dashboard') or
                    has_perm('consulter_demandes') or
                    has_perm('traiter_demandes_affectees') or
                    has_perm('modifier_demande') or
                    has_perm('editer_besoin')
                )

            if action in ['confirmer_fin', 'heures_supplementaires']:
                return (
                    has_perm('editer_besoin') or
                    has_perm('editer_besoin_agence') or
                    has_perm('modifier_demande') or
                    has_perm('traiter_demandes_affectees') or
                    has_perm('confirmation_avant_operation') or
                    has_perm('creer_valider_demande')
                )

            if action in ['confirmer_client', 'nouveau_client']:
                return (
                    has_perm('traiter_demandes_affectees') or
                    has_perm('creer_valider_demande') or
                    has_perm('modifier_demande') or
                    has_perm('modifier_clients')
                )

            if action == 'download_document':
                return (
                    has_perm('consulter_demandes') or
                    has_perm('consulter_dashboard') or
                    has_perm('consulter_factures') or
                    has_perm('creer_devis') or
                    has_perm('generer_facture') or
                    has_perm('traiter_demandes_affectees')
                )

            if action in ['planning', 'create_planning_intervention']:
                if request.method in permissions.SAFE_METHODS:
                    return (
                        has_perm('consulter_abonnements') or
                        has_perm('consulter_planning_abonnements') or
                        has_perm('consulter_demandes') or
                        has_perm('consulter_dashboard')
                    )
                return (
                    has_perm('creer_abonnement') or
                    has_perm('modifier_abonnement') or
                    has_perm('editer_besoin') or
                    has_perm('modifier_demande') or
                    has_perm('traiter_demandes_affectees') or
                    has_perm('creer_valider_demande')
                )

            if action in ['abonnements_vue_ensemble', 'abonnements_planning_stats', 'abonnements_facturation']:
                return (
                    has_perm('consulter_abonnements') or
                    has_perm('consulter_planning_abonnements') or
                    has_perm('consulter_facturation_abonnements') or
                    has_perm('consulter_dashboard') or
                    has_perm('consulter_demandes')
                )

            if action == 'abonnements_toggle_suspend':
                return (
                    has_perm('pause_standby_abonnement') or
                    has_perm('resilier_abonnement') or
                    has_perm('modifier_abonnement')
                )

            if action == 'abonnements_confirm_paiement':
                return (
                    has_perm('valider_facturation_abonnement') or
                    has_perm('valider_paiement_debit') or
                    has_perm('valider_paiement_credit') or
                    has_perm('mouvements_caisse') or
                    has_perm('modifier_facture')
                )

            if action == 'generate_document':
                doc_type = request.data.get('type')
                if doc_type == 'facture':
                    return has_perm('generer_facture')
                elif doc_type == 'devis':
                    return has_perm('creer_devis')
                return has_perm('consulter_demandes')

            if action == 'send_whatsapp':
                doc_type = request.data.get('type')
                if doc_type == 'facture':
                    return has_perm('envoi_facture_client')
                elif doc_type == 'feedback':
                    return has_perm('consulter_retours_qualite') or has_perm('repondre_avis_clients')
                elif doc_type == 'devis':
                    return has_perm('creer_devis')
                return has_perm('consulter_demandes')

            return False

        # 6. Gestion financière (FactureViewSet, PaiementViewSet, EntreeCaisseViewSet)
        if view_name in ['FactureViewSet', 'PaiementViewSet', 'EntreeCaisseViewSet']:
            if role == 'client_conciergerie':
                if view_name in ['FactureViewSet', 'PaiementViewSet']:
                    return action in ['list', 'retrieve']
                return False
            if role in ['runner', 'responsable_linge', 'operationnel']:
                return False
            if role == 'responsable_facturation':
                if view_name == 'FactureViewSet':
                    if action == 'create':
                        return request.data.get('source') == 'airbnb'
                    return action != 'destroy'
                if view_name == 'PaiementViewSet':
                    if action == 'create':
                        facture_id = request.data.get('facture')
                        if facture_id:
                            from finance.models import Facture
                            return Facture.objects.filter(pk=facture_id, source='airbnb').exists()
                        return True
                    return action != 'destroy'
            if view_name == 'FactureViewSet' and action == 'create' and request.data.get('source') == 'airbnb':
                return role == 'responsable_facturation'
            if view_name == 'PaiementViewSet' and action == 'create':
                facture_id = request.data.get('facture')
                if facture_id:
                    from finance.models import Facture
                    if Facture.objects.filter(pk=facture_id, source='airbnb').exists():
                        return role == 'responsable_facturation'
            if action == 'destroy':
                if view_name == 'EntreeCaisseViewSet':
                    return has_perm('mouvements_caisse') or has_perm('cloturer_caisse_journaliere')
                return False
            if view_name == 'EntreeCaisseViewSet' and action in ['solde', 'export_csv']:
                return (
                    has_perm('consulter_solde_caisse') or
                    has_perm('voir_la_caisse') or
                    has_perm('mouvements_caisse') or
                    has_perm('consulter_tresorerie') or
                    has_perm('sorties_caisse')
                )
            if action in ['refund', 'cancel', 'annuler', 'remise']:
                return has_perm('mouvements_caisse') or (role == 'responsable_facturation' and view_name in ['FactureViewSet', 'PaiementViewSet'])
            if action in ['create', 'update', 'partial_update']:
                return (
                    has_perm('modifier_facture') or 
                    has_perm('editer_facture') or 
                    has_perm('mouvements_caisse') or
                    has_perm('creer_mouvements_tresorerie')
                )
            if action in ['list', 'retrieve']:
                if view_name == 'EntreeCaisseViewSet':
                    return (
                        has_perm('mouvements_caisse') or
                        has_perm('consulter_tresorerie') or
                        has_perm('consulter_solde_caisse') or
                        has_perm('sorties_caisse')
                    )
                return (
                    has_perm('consulter_factures') or 
                    has_perm('voir_la_caisse') or 
                    has_perm('mouvements_caisse') or
                    has_perm('consulter_tresorerie') or
                    has_perm('consulter_dus_agences_profils')
                )
            return False

        # 7. Retours clients / Feedback (FeedbackViewSet)
        if view_name == 'FeedbackViewSet':
            if action == 'stats':
                return has_perm('generer_rapports_qualite')
            if action in ['list', 'retrieve']:
                return has_perm('consulter_retours_qualite')
            if action in ['update', 'partial_update', 'destroy']:
                return has_perm('repondre_avis_clients') or has_perm('moderer_masquer_avis')
            return False

        # 8. Marketing (PromoCodeViewSet, CommercialGestureViewSet, CampaignViewSet)
        if view_name == 'PromoCodeViewSet':
            if action in ['create', 'update', 'partial_update', 'destroy']:
                return has_perm('creer_code_promo')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')
            return False
                
        if view_name == 'CommercialGestureViewSet':
            if action in ['create', 'update', 'partial_update', 'destroy']:
                return has_perm('creer_geste_commercial')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')
            return False
                
        if view_name == 'CampaignViewSet':
            if action in ['create', 'update', 'partial_update', 'destroy', 'send']:
                return has_perm('creer_campagne')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')
            return False

        # 9. Module Airbnb / Conciergerie
        if view_name in AIRBNB_VIEWSETS:
            return self._has_airbnb_permission(request, view_name, action, role)

        # 10. Paramètres du site (SiteConfigViewSet)
        if view_name == 'SiteConfigViewSet':
            return has_perm('parametres_globaux')

        # 11. Leads & Contacts (ContactLeadViewSet)
        if view_name == 'ContactLeadViewSet':
            if action == 'destroy':
                return has_perm('supprimer_demande_dashboard') or has_perm('parametres_globaux')
            if action == 'convert':
                return (
                    has_perm('creer_demande')
                    or has_perm('creer_valider_demande')
                    or has_perm('traiter_demandes_affectees')
                )
            if action in ['create', 'update', 'partial_update']:
                return (
                    has_perm('traiter_demandes_affectees')
                    or has_perm('creer_valider_demande')
                    or has_perm('modifier_demande')
                    or has_perm('consulter_demandes')
                )
            if action in ['list', 'retrieve']:
                return (
                    has_perm('consulter_demandes')
                    or has_perm('traiter_demandes_affectees')
                    or has_perm('creer_valider_demande')
                    or has_perm('consulter_clients')
                )
            return False

        # 12. Missions (MissionViewSet)
        if view_name == 'MissionViewSet':
            if action in ['list', 'retrieve']:
                return (
                    has_perm('consulter_dashboard')
                    or has_perm('consulter_demandes')
                    or has_perm('consulter_factures')
                    or has_perm('consulter_comptes_profil')
                    or has_perm('consulter_dus_agences_profils')
                    or has_perm('consulter_debit')
                    or has_perm('consulter_credit')
                )
            if action in ['create', 'update', 'partial_update']:
                return (
                    has_perm('editer_besoin')
                    or has_perm('editer_besoin_agence')
                    or has_perm('modifier_demande')
                    or has_perm('traiter_demandes_affectees')
                    or has_perm('valider_paiement_debit')
                    or has_perm('valider_paiement_credit')
                    or has_perm('validation_paiements_dus')
                    or has_perm('modifier_facture')
                    or has_perm('editer_besoin_facture')
                )
            if action == 'destroy':
                return has_perm('supprimer_demande_dashboard')
            return False

        # 13. Documents (DocumentViewSet)
        if view_name == 'DocumentViewSet':
            if action in ['list', 'retrieve']:
                return (
                    has_perm('consulter_demandes')
                    or has_perm('consulter_dashboard')
                    or has_perm('consulter_factures')
                    or has_perm('creer_devis')
                    or has_perm('generer_facture')
                )
            if action == 'create':
                return (
                    has_perm('creer_devis')
                    or has_perm('generer_facture')
                    or has_perm('modifier_demande')
                    or has_perm('editer_besoin')
                    or has_perm('traiter_demandes_affectees')
                    or has_perm('creer_valider_demande')
                )
            if action in ['update', 'partial_update', 'destroy']:
                return (
                    has_perm('supprimer_demande_dashboard')
                    or has_perm('modifier_demande')
                    or has_perm('modifier_facture')
                )
            return False

        # 14. Journal d'audit (AuditLogViewSet)
        if view_name == 'AuditLogViewSet':
            if action in ['list', 'retrieve']:
                return (
                    has_perm('consulter_historique_global')
                    or has_perm('parametres_globaux')
                    or has_perm('consulter_dashboard')
                    or has_perm('consulter_demandes')
                )
            return False

        # 15. Notifications internes (AppNotificationViewSet)
        if view_name == 'AppNotificationViewSet':
            return action in ['list', 'retrieve', 'update', 'partial_update']

        return False

    def _has_airbnb_permission(self, request, view_name, action, role):
        """Contrôle strict des accès Airbnb selon la matrice Brief §2.1 & §2.2."""
        is_safe = request.method in permissions.SAFE_METHODS

        if view_name in ['AirbnbConfigViewSet', 'GrilleTarifaireVersionViewSet']:
            if not is_safe or action not in ['list', 'retrieve', 'current', 'active']:
                return False
            return role in _AIRBNB_CONFIG_READ_ROLES

        if view_name == 'AirbnbPhotoUploadView':
            return role in _AIRBNB_PHOTO_ROLES

        if view_name == 'JournalAuditAirbnbViewSet':
            return is_safe and action in ['list', 'retrieve'] and role in _AIRBNB_AUDIT_READ_ROLES

        if view_name == 'BienViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'runner':
                return action in ['list', 'retrieve']
            if role in ['client_conciergerie', 'commercial']:
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'desactiver', 'sync_ical', 'connecter_ical', 'retirer_ical', 'stats', 'generate_code_preview',
                ]
            if role in ['responsable_commercial', 'moderateur']:
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update', 'destroy',
                    'activer', 'desactiver', 'sync_ical', 'connecter_ical', 'retirer_ical', 'stats', 'generate_code_preview',
                ]
            if role in ['responsable_facturation', 'responsable_operations', 'charge_operations', 'operationnel']:
                return action in ['list', 'retrieve', 'stats']
            return False

        if view_name == 'CommandeAirbnbViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'runner':
                return action in ['list', 'retrieve', 'mission_pdf_data', 'exporter_fiche_mission_pdf']
            if role == 'client_conciergerie':
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'calculate_price', 'planning_grid', 'stats',
                    'confirmer', 'confirm', 'confirmer_proposition', 'rejeter_proposition',
                    'annuler', 'cancel',
                    'accord_remise_en_etat', 'accorder_remise_en_etat',
                ]
            if role == 'commercial':
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'calculate_price', 'planning_grid', 'stats', 'tdb_interventions',
                    'mission_pdf_data', 'exporter_fiche_mission_pdf',
                    'confirmer', 'confirm', 'confirmer_proposition', 'rejeter_proposition',
                    'annuler', 'cancel',
                    'transmettre_remise_en_etat', 'accord_remise_en_etat', 'accorder_remise_en_etat',
                ]
            if role in ['responsable_commercial', 'moderateur']:
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'calculate_price', 'planning_grid', 'stats', 'tdb_interventions',
                    'mission_pdf_data', 'exporter_fiche_mission_pdf',
                    'confirmer', 'confirm', 'confirmer_proposition', 'rejeter_proposition',
                    'annuler', 'cancel', 'reactiver',
                    'forcer_prix', 'force_price',
                    'transmettre_remise_en_etat', 'accord_remise_en_etat', 'accorder_remise_en_etat',
                ]
            if role == 'responsable_facturation':
                return action in ['list', 'retrieve', 'calculate_price', 'planning_grid', 'stats']
            if role in ['responsable_operations', 'charge_operations']:
                return action in [
                    'list', 'retrieve', 'planning_grid', 'stats', 'tdb_interventions',
                    'suggestions_intervenantes', 'mission_pdf_data', 'exporter_fiche_mission_pdf',
                    'assigner', 'cloturer', 'remonter_tdb', 'demarrer', 'reactiver',
                    'annuler', 'cancel', 'valider_remise_en_etat',
                ]
            if role == 'operationnel':
                return action in ['list', 'retrieve', 'planning_grid', 'stats', 'tdb_interventions', 'mission_pdf_data']
            return False

        if view_name == 'FiletLingeViewSet':
            if role == 'runner':
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'tournee_runner', 'compter_runner', 'confirmer_retrait_bureau',
                    'contester_retrait_bureau', 'deposer',
                ]
            if role == 'responsable_linge':
                return action in [
                    'list', 'retrieve', 'update', 'partial_update',
                    'figer_montant', 'recevoir_laverie', 'marquer_lavage',
                    'marquer_pret', 'remettre_runner', 'arbitrer_ecart',
                ]
            if role in ['client_conciergerie', 'responsable_facturation']:
                return action in ['list', 'retrieve']
            if role == 'commercial':
                return action in ['list', 'retrieve', 'arbitrer_ecart']
            if role in ['responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']:
                return action in ['list', 'retrieve', 'tournee_runner', 'arbitrer_ecart']
            return False

        if view_name == 'ObservationLingeViewSet':
            if role == 'responsable_linge':
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'activer_facturation', 'toggle_facturation',
                ]
            if role == 'responsable_facturation':
                return action in ['list', 'retrieve', 'activer_facturation', 'toggle_facturation']
            if role in ['commercial', 'responsable_commercial', 'moderateur']:
                return action in ['list', 'retrieve', 'notifier_client', 'transmettre_client']
            if role in ['responsable_operations', 'charge_operations', 'client_conciergerie', 'runner']:
                return action in ['list', 'retrieve']
            return False

        if view_name == 'SignalementCommandeViewSet':
            if role in ['responsable_operations', 'charge_operations']:
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'valider', 'arbitrer', 'clore',
                ]
            if role in ['commercial', 'responsable_commercial', 'moderateur']:
                return action in [
                    'list', 'retrieve', 'create', 'transmettre_client',
                    'accord_client', 'arbitrer',
                ]
            if role == 'client_conciergerie':
                return action in ['list', 'retrieve', 'repondre', 'accord', 'accord_client']
            if role in ['responsable_facturation', 'operationnel']:
                return action in ['list', 'retrieve']
            return False

        if view_name == 'ObjetTrouveViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'runner':
                return action in ['list', 'retrieve', 'create']
            if role == 'client_conciergerie':
                return action in ['list', 'retrieve', 'indiquer_instruction', 'instruction']
            if role == 'commercial':
                return action in ['list', 'retrieve', 'create', 'notifier_client', 'informer_client']
            if role in ['responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']:
                return action in [
                    'list', 'retrieve', 'create', 'update', 'partial_update',
                    'mettre_en_securite', 'notifier_client', 'informer_client', 'restituer',
                ]
            if role in ['responsable_facturation', 'operationnel']:
                return action in ['list', 'retrieve']
            return False

        if view_name == 'FacturationAirbnbViewSet':
            if role == 'responsable_facturation':
                return action != 'destroy'
            if role == 'responsable_commercial':
                return action in [
                    'list', 'retrieve', 'resume', 'stats', 'calendrier_facturation',
                    'exporter_facture_pdf', 'annuler_bascule_mensuelle', 'annuler_bascule',
                ]
            if role in ['responsable_operations', 'charge_operations']:
                return action in ['lancer_cron']
            if role in ['commercial', 'moderateur']:
                return action in ['list', 'retrieve', 'resume', 'stats', 'calendrier_facturation', 'exporter_facture_pdf']
            if role == 'client_conciergerie':
                return action in ['list', 'retrieve', 'resume', 'stats', 'calendrier_facturation', 'exporter_facture_pdf', 'declarer_virement']
            return False

        return False

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
            
        role = user.role
        if role == 'admin':
            return True
            
        view_name = view.__class__.__name__
        action = getattr(view, 'action', None)

        # Fetch user permissions
        from accounts.models import RolePermission
        db_role = map_role_to_db_key(user.role)
        try:
            rp = RolePermission.objects.filter(role=db_role).first()
            permissions_list = rp.permissions if rp else []
        except Exception:
            permissions_list = []
        
        is_exempt = is_exempt_from_ownership(user)

        # 1. DemandeViewSet
        if view_name == 'DemandeViewSet':
            action = getattr(view, 'action', None)
            has_traiter = 'traiter_demandes_affectees' in permissions_list
            has_creer_valider = 'creer_valider_demande' in permissions_list
            has_consulter_demandes = 'consulter_demandes' in permissions_list
            has_consulter_dashboard = 'consulter_dashboard' in permissions_list
            
            # If the request method is read-only (GET, HEAD, OPTIONS), allow if they have view permissions
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                if action == 'download_document':
                    return (
                        has_consulter_demandes or
                        has_consulter_dashboard or
                        has_traiter or
                        has_creer_valider or
                        'consulter_factures' in permissions_list or
                        'creer_devis' in permissions_list or
                        'generer_facture' in permissions_list
                    )
                if action == 'planning':
                    return (
                        has_consulter_demandes or
                        has_consulter_dashboard or
                        'consulter_abonnements' in permissions_list or
                        'consulter_planning_abonnements' in permissions_list
                    )
                if (has_consulter_demandes or 
                    has_consulter_dashboard or 
                    has_traiter or 
                    has_creer_valider):
                    return True

            is_concerned = (
                obj.created_by == user or
                obj.assigned_to == user or
                obj.assigned_to_operations == user or
                (obj.client_id is not None and getattr(obj.client, 'assigned_commercial_id', None) == user.id)
            )
            is_unassigned_incoming = (
                obj.created_by is None and
                obj.assigned_to is None and
                obj.assigned_to_operations is None
            )

            if request.method not in permissions.SAFE_METHODS and action not in ('affecter', 'affecter_operations'):
                if not is_exempt and not is_concerned and not is_unassigned_incoming:
                    return False

            if action == 'envoyer_profil':
                return 'postuler_demande' in permissions_list

            if action == 'retirer_profil':
                return 'retirer_profil_demande' in permissions_list

            if action in ['update', 'partial_update']:
                return (
                    'modifier_demande' in permissions_list or 
                    'editer_besoin' in permissions_list or 
                    'editer_besoin_agence' in permissions_list or 
                    'modifier_facture' in permissions_list or 
                    'editer_besoin_facture' in permissions_list or
                    has_traiter or
                    has_creer_valider
                )

            elif action == 'annuler':
                return (
                    'refuser_demande' in permissions_list or 
                    'annulation_demande' in permissions_list or 
                    has_traiter or 
                    has_creer_valider
                )

            elif action == 'confirmer_cao':
                return (
                    'confirmation_avant_operation' in permissions_list or 
                    has_traiter or 
                    has_creer_valider
                )

            elif action == 'valider':
                return has_traiter or has_creer_valider

            elif action == 'affecter':
                return 'affecter_commercial' in permissions_list or 'traiter_demandes_affectees' in permissions_list

            elif action == 'affecter_operations':
                return 'assigner_charge_operation' in permissions_list

            elif action == 'annuler_facturation':
                return 'facturation_annulee' in permissions_list

            elif action in ['appliquer_geste', 'geste_commercial']:
                return 'creer_geste_commercial' in permissions_list or 'geste_commercial' in permissions_list

            elif action in ['confirmer_fin', 'heures_supplementaires']:
                return (
                    'editer_besoin' in permissions_list or
                    'editer_besoin_agence' in permissions_list or
                    'modifier_demande' in permissions_list or
                    has_traiter or
                    'confirmation_avant_operation' in permissions_list or
                    has_creer_valider
                )

            elif action in ['confirmer_client', 'nouveau_client']:
                return has_traiter or has_creer_valider or 'modifier_demande' in permissions_list or 'modifier_clients' in permissions_list

            elif action in ['planning', 'create_planning_intervention']:
                return (
                    'creer_abonnement' in permissions_list or
                    'modifier_abonnement' in permissions_list or
                    'editer_besoin' in permissions_list or
                    'modifier_demande' in permissions_list or
                    has_traiter or
                    has_creer_valider
                )

            elif action == 'abonnements_toggle_suspend':
                return (
                    'pause_standby_abonnement' in permissions_list or
                    'resilier_abonnement' in permissions_list or
                    'modifier_abonnement' in permissions_list
                )

            elif action == 'abonnements_confirm_paiement':
                return (
                    'valider_facturation_abonnement' in permissions_list or
                    'valider_paiement_debit' in permissions_list or
                    'valider_paiement_credit' in permissions_list or
                    'mouvements_caisse' in permissions_list or
                    'modifier_facture' in permissions_list
                )

            elif action == 'nrp':
                return 'consulter_demandes' in permissions_list or 'modifier_demande' in permissions_list or has_traiter or has_creer_valider

            elif action == 'destroy':
                return 'supprimer_demande_dashboard' in permissions_list

            elif action == 'generate_document':
                doc_type = request.data.get('type')
                if doc_type == 'facture':
                    return 'generer_facture' in permissions_list
                elif doc_type == 'devis':
                    return 'creer_devis' in permissions_list
                return 'consulter_demandes' in permissions_list

            elif action == 'send_whatsapp':
                doc_type = request.data.get('type')
                if doc_type == 'facture':
                    return 'envoi_facture_client' in permissions_list
                elif doc_type == 'feedback':
                    return 'consulter_retours_qualite' in permissions_list or 'repondre_avis_clients' in permissions_list
                elif doc_type == 'devis':
                    return 'creer_devis' in permissions_list
                return 'consulter_demandes' in permissions_list
                
            # Fallback for retrieve or other operations
            return has_traiter or has_creer_valider or has_consulter_demandes or has_consulter_dashboard
            
        # 2. ClientViewSet
        if view_name == 'ClientViewSet':
            if role == 'client_conciergerie':
                return request.method in permissions.SAFE_METHODS and bool(user.client_id) and obj.id == user.client_id
            if role == 'responsable_facturation':
                return request.method in permissions.SAFE_METHODS
            if is_exempt:
                return True
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                if 'consulter_clients' in permissions_list:
                    return True
                from django.db.models import Q
                return (
                    obj.assigned_commercial == user or
                    obj.demandes.filter(
                        Q(created_by=user) |
                        Q(assigned_to=user) |
                        Q(assigned_to_operations=user)
                    ).exists()
                )
            return obj.assigned_commercial == user
            
        # 3. FeedbackViewSet
        if view_name == 'FeedbackViewSet':
            if is_exempt:
                return True
            demande = obj.demande or (obj.mission.demande if obj.mission else None)
            if not demande:
                return False
            is_concerned = (
                demande.created_by == user or
                demande.assigned_to == user or
                demande.assigned_to_operations == user
            )
            return is_concerned
            
        # 4. FactureViewSet
        if view_name == 'FactureViewSet':
            if getattr(obj, 'source', 'classique') == 'airbnb':
                if role == 'responsable_facturation':
                    return action != 'destroy' and request.method != 'DELETE'
                if role == 'client_conciergerie':
                    return request.method in permissions.SAFE_METHODS and bool(user.client_id) and obj.client_id == user.client_id
                if role == 'responsable_commercial':
                    return request.method in permissions.SAFE_METHODS
                if role == 'commercial':
                    return (
                        request.method in permissions.SAFE_METHODS
                        and bool(obj.client_id)
                        and obj.client.assigned_commercial_id == user.id
                    )
                return False
            if role == 'responsable_facturation':
                return False
            if is_exempt:
                return True
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                has_consulter_factures = any(p in permissions_list for p in [
                    'consulter_factures', 'voir_la_caisse', 'mouvements_caisse', 
                    'consulter_tresorerie', 'consulter_dus_agences_profils'
                ])
                if has_consulter_factures:
                    return True
            demande = obj.demande
            if not demande:
                return False
            is_concerned = (
                demande.created_by == user or
                demande.assigned_to == user or
                demande.assigned_to_operations == user
            )
            return is_concerned
 
        # 5. PaiementViewSet
        if view_name == 'PaiementViewSet':
            facture = getattr(obj, 'facture', None)
            if facture and getattr(facture, 'source', 'classique') == 'airbnb':
                if role == 'responsable_facturation':
                    return action != 'destroy' and request.method != 'DELETE'
                if role == 'client_conciergerie':
                    return request.method in permissions.SAFE_METHODS and bool(user.client_id) and facture.client_id == user.client_id
                if role == 'responsable_commercial':
                    return request.method in permissions.SAFE_METHODS
                if role == 'commercial':
                    return (
                        request.method in permissions.SAFE_METHODS
                        and bool(facture.client_id)
                        and facture.client.assigned_commercial_id == user.id
                    )
                return False
            if role == 'responsable_facturation':
                return False
            if is_exempt:
                return True
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                has_consulter_factures = any(p in permissions_list for p in [
                    'consulter_factures', 'voir_la_caisse', 'mouvements_caisse', 
                    'consulter_tresorerie', 'consulter_dus_agences_profils'
                ])
                if has_consulter_factures:
                    return True
            if not facture or not facture.demande:
                return False
            demande = facture.demande
            is_concerned = (
                demande.created_by == user or
                demande.assigned_to == user or
                demande.assigned_to_operations == user
            )
            return is_concerned
 
        # 6. EntreeCaisseViewSet
        if view_name == 'EntreeCaisseViewSet':
            if is_exempt:
                return True
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                has_consulter_caisse = any(p in permissions_list for p in [
                    'mouvements_caisse', 'consulter_tresorerie', 'consulter_solde_caisse', 'sorties_caisse'
                ])
                if has_consulter_caisse:
                    return True
            from django.db.models import Q
            paiement = obj.paiement
            client = obj.client
            
            if paiement and paiement.facture and paiement.facture.demande:
                demande = paiement.facture.demande
                if (demande.created_by == user or 
                    demande.assigned_to == user or 
                    demande.assigned_to_operations == user):
                    return True
                    
            if client:
                if (client.assigned_commercial == user or
                    client.demandes.filter(
                        Q(created_by=user) |
                        Q(assigned_to=user) |
                        Q(assigned_to_operations=user)
                    ).exists()):
                    return True
            return False
 
        # 7. Module Airbnb / Conciergerie
        if view_name in AIRBNB_VIEWSETS:
            return self._has_airbnb_object_permission(request, view_name, action, role, user, obj)

        if view_name == 'AppNotificationViewSet':
            if getattr(obj, 'target_user_id', None) is not None:
                return obj.target_user_id == user.id
            target_roles = [str(r).lower() for r in (getattr(obj, 'target_roles', None) or [])]
            if target_roles:
                user_role = str(role or '').lower()
                matching_roles = {user_role}
                if user_role in {'charge_operations', 'responsable_operations', 'operationnel'}:
                    matching_roles.add('operations')
                return any(r in matching_roles for r in target_roles)
            return role not in AIRBNB_ONLY_ROLES

        if role in AIRBNB_ONLY_ROLES and view_name not in ['ClientViewSet', 'FactureViewSet', 'PaiementViewSet']:
            return False

        if view_name in [
            'UserViewSet', 'AgentViewSet', 'MissionViewSet', 'DocumentViewSet',
            'AuditLogViewSet', 'PromoCodeViewSet', 'CommercialGestureViewSet',
            'CampaignViewSet', 'SiteConfigViewSet', 'ContactLeadViewSet',
        ]:
            return True

        return False

    def _has_airbnb_object_permission(self, request, view_name, action, role, user, obj):
        is_safe = request.method in permissions.SAFE_METHODS

        if view_name in ['AirbnbConfigViewSet', 'GrilleTarifaireVersionViewSet']:
            return is_safe and role in _AIRBNB_CONFIG_READ_ROLES

        if view_name == 'JournalAuditAirbnbViewSet':
            return is_safe and role in _AIRBNB_AUDIT_READ_ROLES

        if view_name == 'BienViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'client_conciergerie':
                return bool(user.client_id) and obj.client_id == user.client_id and action not in ['destroy', 'activer']
            if role == 'commercial':
                return bool(obj.client) and obj.client.assigned_commercial_id == user.id and action not in ['destroy', 'activer']
            if role == 'runner':
                return is_safe and obj.commandes.filter(runner=user, date_prestation=timezone.localdate()).exists()
            if role in ['responsable_facturation', 'responsable_operations', 'charge_operations', 'operationnel']:
                return is_safe
            return role in ['responsable_commercial', 'moderateur']

        if view_name == 'CommandeAirbnbViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'client_conciergerie':
                return bool(user.client_id) and obj.bien.client_id == user.client_id
            if role == 'commercial':
                return bool(obj.bien and obj.bien.client) and obj.bien.client.assigned_commercial_id == user.id
            if role == 'runner':
                return is_safe and obj.runner_id == user.id and obj.date_prestation == timezone.localdate()
            if role in ['responsable_facturation', 'operationnel']:
                return is_safe
            return role in ['responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']

        if view_name == 'FiletLingeViewSet':
            if role == 'client_conciergerie':
                return is_safe and bool(user.client_id) and obj.bien.client_id == user.client_id
            if role == 'commercial':
                return bool(obj.bien and obj.bien.client) and obj.bien.client.assigned_commercial_id == user.id
            if role == 'runner':
                return (
                    (obj.commande_ramassage and obj.commande_ramassage.runner_id == user.id)
                    or (obj.commande_depot and obj.commande_depot.runner_id == user.id)
                )
            if role == 'responsable_facturation':
                return is_safe
            return role in ['responsable_linge', 'responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']

        if view_name == 'ObservationLingeViewSet':
            if role == 'client_conciergerie':
                return is_safe and bool(user.client_id) and obj.filet.bien.client_id == user.client_id
            if role == 'commercial':
                return bool(obj.filet and obj.filet.bien and obj.filet.bien.client) and obj.filet.bien.client.assigned_commercial_id == user.id
            if role == 'runner':
                return is_safe and (
                    (obj.filet.commande_ramassage and obj.filet.commande_ramassage.runner_id == user.id)
                    or (obj.filet.commande_depot and obj.filet.commande_depot.runner_id == user.id)
                )
            return role in ['responsable_linge', 'responsable_facturation', 'responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']

        if view_name == 'SignalementCommandeViewSet':
            if role == 'client_conciergerie':
                return bool(user.client_id) and obj.commande.bien.client_id == user.client_id
            if role == 'commercial':
                return bool(obj.commande and obj.commande.bien and obj.commande.bien.client) and obj.commande.bien.client.assigned_commercial_id == user.id
            if role in ['responsable_facturation', 'operationnel']:
                return is_safe
            return role in ['responsable_operations', 'charge_operations', 'responsable_commercial', 'moderateur']

        if view_name == 'ObjetTrouveViewSet':
            if role == 'responsable_linge':
                return False
            if role == 'client_conciergerie':
                return bool(user.client_id) and obj.bien.client_id == user.client_id
            if role == 'commercial':
                return bool(obj.bien and obj.bien.client) and obj.bien.client.assigned_commercial_id == user.id
            if role == 'runner':
                return bool(obj.commande) and obj.commande.runner_id == user.id
            if role in ['responsable_facturation', 'operationnel']:
                return is_safe
            return role in ['responsable_commercial', 'moderateur', 'responsable_operations', 'charge_operations']

        if view_name == 'FacturationAirbnbViewSet':
            obj_client_id = obj.client_id if hasattr(obj, 'client_id') else getattr(obj, 'id', None)
            if role == 'client_conciergerie':
                return bool(user.client_id) and obj_client_id == user.client_id
            if role == 'commercial':
                assigned_id = (
                    obj.client.assigned_commercial_id
                    if hasattr(obj, 'client') and obj.client
                    else getattr(obj, 'assigned_commercial_id', None)
                )
                return is_safe and assigned_id == user.id
            if role == 'responsable_facturation':
                return action != 'destroy' and request.method != 'DELETE'
            if role == 'responsable_commercial':
                return is_safe or action in ['annuler_bascule_mensuelle', 'annuler_bascule']
            if role == 'moderateur':
                return is_safe
            return False

        return False


class IsAdminOrDebugOnly(permissions.BasePermission):
    """Autorise la documentation OpenAPI en DEBUG local ou aux administrateurs authentifiés."""
    def has_permission(self, request, view):
        if getattr(settings, 'DEBUG', False):
            return True
        user = getattr(request, 'user', None)
        return bool(
            user
            and user.is_authenticated
            and (user.is_staff or getattr(user, 'role', None) == 'admin')
        )
