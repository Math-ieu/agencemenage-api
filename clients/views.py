from rest_framework import viewsets, filters
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from .models import Client, ClientActionLog
from .serializers import ClientSerializer, ClientListSerializer, ClientActionLogSerializer
from .filters import ClientFilter


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.prefetch_related('demandes').filter(is_archived=False)
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ClientFilter
    search_fields = ['first_name', 'last_name', 'entity_name', 'phone', 'email', 'neighborhood', 'city']
    ordering_fields = ['created_at', 'last_name', 'entity_name']
    ordering = ['-created_at']

    def get_permissions(self):
        from accounts.permissions import RoleBasedPermission
        from rest_framework.permissions import IsAuthenticated
        return [IsAuthenticated(), RoleBasedPermission()]

    def get_serializer_class(self):
        if self.action == 'list':
            return ClientListSerializer
        return ClientSerializer

    def perform_destroy(self, instance):
        instance.demandes.all().delete()
        instance.is_archived = True
        instance.save(update_fields=['is_archived'])

    @action(detail=True, methods=['get'])
    def action_logs(self, request, pk=None):
        client = self.get_object()
        logs = getattr(client, 'action_logs', ClientActionLog.objects.none()).all()
        serializer = ClientActionLogSerializer(logs, many=True)
        return Response(serializer.data)
