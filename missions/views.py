from rest_framework import viewsets, filters
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from .models import Mission
from .serializers import MissionSerializer
from .filters import MissionFilter
from demandes.models import AuditLog


class MissionViewSet(viewsets.ModelViewSet):
    queryset = Mission.objects.select_related('demande', 'agent').all()
    serializer_class = MissionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = MissionFilter
    ordering = ['-created_at']
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def perform_create(self, serializer):
        mission = serializer.save(created_by=self.request.user)
        # Log for the agent
        AuditLog.objects.create(
            user=self.request.user,
            action='Mission créée',
            model_name='Mission',
            object_id=mission.pk,
            extra_data={
                'agent_id': mission.agent.pk,
                'demande_id': mission.demande.pk,
                'client_name': mission.demande.client.display_name if mission.demande.client else 'Client'
            }
        )
