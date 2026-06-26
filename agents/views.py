from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import Agent, AgentAssignment
from .serializers import AgentSerializer, AgentListSerializer, AgentAssignmentSerializer
from .filters import AgentFilter
from demandes.models import AuditLog, ProfilShare
from rest_framework.decorators import action
from rest_framework.response import Response


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.filter(is_archived=False)
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AgentFilter
    search_fields = ['first_name', 'last_name', 'phone', 'neighborhood', 'city', 'cin']
    ordering_fields = ['created_at', 'last_name']
    ordering = ['-created_at']

    def get_permissions(self):
        from accounts.permissions import RoleBasedPermission
        if self.action == 'retrieve':
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            lookup_value = self.kwargs.get(lookup_url_kwarg)
            
            # Allow public access ONLY for UUID lookups
            import uuid
            try:
                if lookup_value:
                    uuid.UUID(str(lookup_value))
                    return [AllowAny()]
            except ValueError:
                # If it's an integer ID, require authentication
                return [IsAuthenticated(), RoleBasedPermission()]
                
        if self.action == 'by_share':
            return [AllowAny()]
        return [IsAuthenticated(), RoleBasedPermission()]

    def get_object(self):
        """Allow lookup by ID or UUID."""
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]

        # Check if lookup_value is a valid UUID
        import uuid
        try:
            uuid_obj = uuid.UUID(lookup_value)
            return queryset.get(uuid=uuid_obj)
        except (ValueError, Agent.DoesNotExist):
            return super().get_object()

    def get_serializer_class(self):
        if self.action == 'list':
            return AgentListSerializer
        return AgentSerializer

    def perform_create(self, serializer):
        agent = serializer.save()
        self._log_action(self.request.user, 'Profil créé', agent)

    def perform_update(self, serializer):
        agent = serializer.save()
        self._log_action(self.request.user, 'Profil modifié', agent)

    def perform_destroy(self, instance):
        instance.is_archived = True
        instance.save(update_fields=['is_archived'])
        self._log_action(self.request.user, 'Profil archivé', instance)

    def _log_action(self, user, action, agent):
        AuditLog.objects.create(
            user=user,
            action=action,
            model_name='Agent',
            object_id=agent.pk,
            extra_data={'agent_name': agent.full_name}
        )

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        agent = self.get_object()
        
        # 1. Logs directly related to the Agent model
        agent_logs = AuditLog.objects.filter(model_name='Agent', object_id=agent.pk)
        
        # 2. Logs from Demande model where this agent was involved (envoyer_profil)
        # We use a trick: search in extra_data for agent_id
        demande_status_logs = AuditLog.objects.filter(
            model_name='Demande',
            action='envoyer_profil',
            extra_data__agent_id=agent.pk
        )
        
        # Merge and sort
        from django.db.models import Q
        combined_logs = AuditLog.objects.filter(
            Q(model_name='Agent', object_id=agent.pk) |
            Q(model_name='Demande', action='envoyer_profil', extra_data__agent_id=agent.pk) |
            Q(model_name='Demande', action=f'envoyer_profil:{agent.pk}') |
            Q(model_name='Mission', extra_data__agent_id=agent.pk) |
            Q(model_name='Feedback', extra_data__agent_id=agent.pk)
        ).select_related('user').order_by('-timestamp')
        
        from demandes.serializers import AuditLogSerializer
        serializer = AuditLogSerializer(combined_logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def affecter(self, request, pk=None):
        """Affecter l'agent à un chargé des opérations."""
        agent = self.get_object()
        assigned_to_id = request.data.get('assigned_to_id')
        assigned_to = None
        if assigned_to_id:
            from accounts.models import User
            try:
                assigned_to = User.objects.get(pk=assigned_to_id, is_active=True)
            except User.DoesNotExist:
                return Response({'error': 'Utilisateur introuvable'}, status=404)
        agent.assigned_to = assigned_to
        agent.save()

        AgentAssignment.objects.create(
            agent=agent,
            assigned_to=assigned_to,
            assigned_by=request.user if request.user.is_authenticated else None,
            assigned_by_name=request.data.get('assigned_by_name', ''),
            notes=request.data.get('notes', '')
        )
        return Response(AgentSerializer(agent).data)

    @action(detail=True, methods=['get'])
    def assignments(self, request, pk=None):
        """Retourner l'historique des affectations pour ce profil."""
        agent = self.get_object()
        assignments = agent.assignments.all().order_by('-created_at')
        serializer = AgentAssignmentSerializer(assignments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='by-share/(?P<share_uuid>[^/.]+)')
    def by_share(self, request, share_uuid=None):
        """Récupérer un profil via son lien de partage unique."""
        try:
            share = ProfilShare.objects.select_related(
                'agent', 'demande', 'demande__client', 'demande__client__assigned_commercial'
            ).get(uuid=share_uuid)
        except (ProfilShare.DoesNotExist, ValueError):
            return Response({'error': 'Lien invalide ou expiré'}, status=404)
        
        serializer = AgentSerializer(share.agent)
        data = serializer.data
        data['demande_context'] = {
            'service': share.demande.service,
            'client_name': share.demande.client.display_name if share.demande.client else 'Inconnu'
        }
        
        # Get the commercial's phone number
        commercial_phone = None
        if share.demande and share.demande.client and share.demande.client.assigned_commercial:
            commercial_phone = share.demande.client.assigned_commercial.phone
            
        data['commercial_phone'] = commercial_phone
        return Response(data)
