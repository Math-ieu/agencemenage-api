from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Agent
from .serializers import AgentSerializer, AgentListSerializer


class AgentViewSet(viewsets.ModelViewSet):
    queryset = Agent.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['statut', 'poste', 'city']
    search_fields = ['first_name', 'last_name', 'phone']
    ordering_fields = ['created_at', 'last_name']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return AgentListSerializer
        return AgentSerializer
