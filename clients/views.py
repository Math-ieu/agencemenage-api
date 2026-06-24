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

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and user.role != 'admin':
            from accounts.models import RolePermission
            from accounts.permissions import map_role_to_db_key
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []
                
            if 'consulter_clients' not in permissions_list:
                from django.db.models import Q
                qs = qs.filter(
                    Q(assigned_commercial=user) |
                    Q(demandes__created_by=user) |
                    Q(demandes__assigned_to=user) |
                    Q(demandes__assigned_to_operations=user)
                ).distinct()
        return qs
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

    @action(detail=True, methods=['post'])
    def affecter(self, request, pk=None):
        """Affecter le client à un commercial."""
        client = self.get_object()
        commercial_id = request.data.get('commercial_id')
        if not commercial_id:
            return Response({'error': 'commercial_id requis'}, status=400)
        from accounts.models import User
        try:
            commercial = User.objects.get(pk=commercial_id, is_active=True)
        except User.DoesNotExist:
            return Response({'error': 'Commercial introuvable'}, status=404)
        client.assigned_commercial = commercial
        client.save()
        return Response(ClientSerializer(client).data)
