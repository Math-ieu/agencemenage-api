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
    return role

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
            if action == 'destroy':
                return has_perm('delete_client')
            
            if action in ['update', 'partial_update']:
                is_blacklisting = 'is_blacklisted' in request.data
                if is_blacklisting:
                    return has_perm('blacklister_clients')
                return has_perm('modifier_clients')
                
            if action == 'create':
                return has_perm('modifier_clients')
                
            if action == 'affecter':
                return has_perm('affectation_client') or has_perm('affecter_commercial')
                
            if action in ['list', 'retrieve']:
                return has_perm('consulter_clients')

        # 4. Gestion des profils candidats (AgentViewSet)
        if view_name == 'AgentViewSet':
            if action == 'destroy':
                return has_perm('supprimer_profil')
                
            if action in ['update', 'partial_update']:
                is_blacklisting = 'is_blacklisted' in request.data
                if is_blacklisting:
                    return has_perm('blacklister_agents')
                return has_perm('modifier_agents')
                
            if action == 'create':
                return has_perm('creer_agents')
                
            if action in ['list', 'retrieve']:
                return has_perm('consulter_agents')

        # 5. Gestion des demandes (DemandeViewSet)
        if view_name == 'DemandeViewSet':
            if action == 'destroy':
                return has_perm('supprimer_demande_dashboard')
                
            if action in ['valider', 'confirmer_cao']:
                return has_perm('valider_demandes')
                
            if action == 'annuler':
                return has_perm('refuser_demande') or has_perm('annulation_demande')
                
            if action == 'nrp':
                return has_perm('consulter_demandes') or has_perm('modifier_demande')
                
            if action == 'affecter':
                return has_perm('affecter_commercial')
                
            if action == 'annuler_facturation':
                return has_perm('facturation_annulee')
                
            if action in ['appliquer_geste', 'geste_commercial']:
                return has_perm('creer_geste_commercial') or has_perm('geste_commercial')
                
            if action == 'create':
                return has_perm('creer_demande')
                
            if action in ['update', 'partial_update']:
                return has_perm('modifier_demande')
                
            if action in ['list', 'retrieve']:
                return has_perm('consulter_demandes') or has_perm('consulter_dashboard')

        # 6. Gestion financière (FactureViewSet, PaiementViewSet, EntreeCaisseViewSet)
        if view_name in ['FactureViewSet', 'PaiementViewSet', 'EntreeCaisseViewSet']:
            if action in ['refund', 'cancel', 'annuler', 'remise']:
                return has_perm('mouvements_caisse')
            if action in ['create', 'update', 'partial_update']:
                return has_perm('modifier_facture') or has_perm('editer_facture') or has_perm('mouvements_caisse')
            if action in ['list', 'retrieve']:
                return has_perm('consulter_factures') or has_perm('voir_la_caisse') or has_perm('mouvements_caisse')

        # 7. Retours clients / Feedback (FeedbackViewSet)
        if view_name == 'FeedbackViewSet':
            if action in ['list', 'retrieve']:
                return has_perm('consulter_retours_qualite')
            return has_perm('repondre_avis_clients') or has_perm('moderer_masquer_avis')

        # 8. Marketing (PromoCodeViewSet, CommercialGestureViewSet, CampaignViewSet)
        if view_name == 'PromoCodeViewSet':
            if action == 'create':
                return has_perm('creer_code_promo')
            elif action in ['update', 'partial_update', 'destroy']:
                return has_perm('creer_code_promo')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')
                
        if view_name == 'CommercialGestureViewSet':
            if action == 'create':
                return has_perm('creer_geste_commercial')
            elif action in ['update', 'partial_update', 'destroy']:
                return has_perm('creer_geste_commercial')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')
                
        if view_name == 'CampaignViewSet':
            if action == 'create':
                return has_perm('creer_campagne')
            elif action in ['update', 'partial_update', 'destroy']:
                return has_perm('creer_campagne')
            elif action in ['list', 'retrieve']:
                return has_perm('consulter_marketing')

        return True

    def has_object_permission(self, request, view, obj):
        return True
