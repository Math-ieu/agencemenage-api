from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from .models import Mission
from .serializers import MissionSerializer
from .filters import MissionFilter


class MissionViewSet(viewsets.ModelViewSet):
    queryset = Mission.objects.select_related('demande', 'agent').all()
    serializer_class = MissionSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = MissionFilter
    ordering = ['-created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
