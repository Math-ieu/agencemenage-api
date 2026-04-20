from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Agent
from .serializers import AgentSerializer, AgentListSerializer
from .filters import AgentFilter
from demandes.models import AuditLog
from rest_framework.decorators import action
from rest_framework.response import Response


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.filter(is_archived=False)
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AgentFilter
    search_fields = ['first_name', 'last_name', 'phone', 'neighborhood', 'city', 'cin']
    ordering_fields = ['created_at', 'last_name']
    ordering = ['-created_at']

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
