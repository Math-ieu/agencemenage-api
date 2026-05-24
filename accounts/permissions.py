from rest_framework import permissions

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
            
        action = view.action
        view_name = view.__class__.__name__

        # 2. Gestion des utilisateurs (UserViewSet)
        if view_name == 'UserViewSet':
            # Seul l'admin et le modérateur (création uniquement) ont accès
            if role == 'moderateur' and action == 'create':
                return True
            self.message = "Accès refusé. Seul un administrateur peut gérer les comptes utilisateurs (Modérateur peut créer)."
            return False

        # 3. Gestion des clients (ClientViewSet)
        if view_name == 'ClientViewSet':
            # Supprimer/Blacklister
            if action in ['destroy', 'blacklist']:
                self.message = "Action non autorisée. Seul un administrateur est autorisé à supprimer ou blacklister un client."
                return False
                
            # Modifier / Créer
            if action in ['create', 'update', 'partial_update']:
                if role in ['commercial', 'charge_operations']:
                    # Le commercial peut uniquement éditer ses propres clients (vérifié au niveau de l'objet)
                    if role == 'commercial' and action in ['update', 'partial_update']:
                        return True
                    self.message = f"Les utilisateurs avec le rôle '{role}' n'ont pas l'autorisation de créer ou modifier les fiches clients génériques."
                    return False
                    
            # Affectation à un commercial (Custom actions on clients/demands)
            if action == 'affecter':
                if role not in ['responsable_commercial', 'responsable_operations']:
                    self.message = "Seul un responsable commercial ou responsable des opérations peut affecter un client."
                    return False

        # 4. Gestion des profils candidats (AgentViewSet)
        if view_name == 'AgentViewSet':
            # Supprimer un profil
            if action == 'destroy':
                self.message = "Action non autorisée. Seul un administrateur peut supprimer un profil candidat."
                return False
                
            # Blacklister un profil candidate (Admin et Responsable des opérations)
            if action == 'blacklist':
                if role not in ['responsable_operations']:
                    self.message = "Action non autorisée. Seul un administrateur ou responsable des opérations peut blacklister un profil."
                    return False

            # Créer / Modifier
            if action in ['create', 'update', 'partial_update']:
                if role == 'commercial':
                    self.message = "Les commerciaux ont un accès en lecture seule aux fiches candidats."
                    return False

        # 5. Gestion des demandes (DemandeViewSet)
        if view_name == 'DemandeViewSet':
            # Annuler la facturation / Geste commercial (Remise/Remboursement/Annulation)
            if action in ['annuler_facturation', 'appliquer_geste', 'geste_commercial']:
                if role not in ['responsable_commercial', 'responsable_operations']:
                    self.message = "Seul un administrateur, responsable commercial ou responsable des opérations peut annuler une facturation, effectuer un remboursement ou accorder un geste commercial."
                    return False

            # Valider / Planifier (CAO)
            if action in ['valider', 'confirmer_cao']:
                if role not in ['responsable_operations', 'charge_operations', 'responsable_commercial']:
                    self.message = "Seul un administrateur, un responsable ou une chargée des opérations peut valider ou planifier une demande (CAO)."
                    return False

            # Modifier demande
            if action in ['update', 'partial_update']:
                if role == 'charge_operations':
                    self.message = "Les chargées des opérations ont un accès en lecture seule aux détails des clients et demandes."
                    return False

        # 6. Gestion financière (FactureViewSet, PaiementViewSet, EntreeCaisseViewSet)
        if view_name in ['FactureViewSet', 'PaiementViewSet', 'EntreeCaisseViewSet']:
            # Responsable commercial, Commercial, Responsable des Opérations ont accès
            if role not in ['responsable_commercial', 'commercial', 'responsable_operations']:
                self.message = "Accès refusé. Vous n'avez pas l'autorisation d'accéder ou de modifier la gestion financière."
                return False
            # Les remises, remboursements et annulations
            if action in ['refund', 'cancel', 'annuler', 'remise']:
                if role == 'commercial':
                    self.message = "Les commerciaux ne peuvent pas initier de remises, remboursements ou annulations financières."
                    return False

        # 7. Retours clients / Feedback (FeedbackViewSet)
        if view_name == 'FeedbackViewSet':
            # Responsable des opérations a accès à tout
            if role == 'charge_operations':
                # La chargée d'opérations a uniquement accès à ses propres feedbacks (filtré dans get_queryset)
                return True
            if role not in ['responsable_operations', 'responsable_commercial']:
                self.message = "Accès refusé aux retours clients."
                return False

        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        role = user.role
        
        if role == 'admin':
            return True

        action = view.action
        view_name = view.__class__.__name__

        # 1. Commercial - modifier uniquement ses propres clients
        if view_name == 'ClientViewSet':
            if action in ['update', 'partial_update']:
                if role == 'commercial':
                    # vérifie si une demande du client est affectée à ce commercial
                    has_assigned = obj.demandes.filter(assigned_to=user).exists()
                    if not has_assigned:
                        self.message = "Action non autorisée. Vous pouvez uniquement éditer vos propres clients attribués."
                        return False

        # 2. Commercial - modifier uniquement ses propres demandes
        if view_name == 'DemandeViewSet':
            if action in ['update', 'partial_update']:
                if role == 'commercial':
                    if obj.assigned_to != user:
                        self.message = "Action non autorisée. Vous pouvez uniquement modifier vos propres demandes."
                        return False

        # 3. Chargée des opérations - retour qualité de ses propres clients
        if view_name == 'FeedbackViewSet':
            if role == 'charge_operations':
                # vérifie si la demande associée est attribuée ou liée à ses clients
                if obj.demande and obj.demande.assigned_to != user:
                    self.message = "Accès refusé. Vous pouvez uniquement consulter les feedbacks de vos propres dossiers clients."
                    return False

        return True
