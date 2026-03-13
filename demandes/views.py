from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from .models import Demande, NRPLog, Document, AuditLog
from .serializers import (
    DemandeSerializer, DemandeListSerializer,
    NRPLogSerializer, DocumentSerializer,
    PublicDemandeCreateSerializer, AuditLogSerializer
)
from accounts.serializers import UserSerializer


class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.select_related('client', 'assigned_to').prefetch_related('nrp_logs', 'documents')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['statut', 'segment', 'source', 'service', 'assigned_to', 'statut_paiement']
    search_fields = ['client__first_name', 'client__last_name', 'client__phone',
                     'client__entity_name', 'service']
    ordering_fields = ['created_at', 'date_intervention', 'statut']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return DemandeListSerializer
        return DemandeSerializer

    def perform_create(self, serializer):
        serializer.save(assigned_to=self.request.user)

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        """Valider une demande → statut EN_COURS"""
        demande = self.get_object()
        if demande.statut != Demande.EN_ATTENTE:
            return Response({'error': 'Seules les demandes en attente peuvent être validées.'}, status=400)
        demande.statut = Demande.ENCOURS
        demande.save()
        self._log_action(request.user, 'valider', demande)
        return Response(DemandeSerializer(demande).data)

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        """Annuler une demande."""
        demande = self.get_object()
        avis = request.data.get('avis_annulation', '')
        demande.statut = Demande.ANNULE
        demande.avis_annulation = avis
        demande.save()
        self._log_action(request.user, 'annuler', demande)
        return Response(DemandeSerializer(demande).data)

    @action(detail=True, methods=['post'])
    def nrp(self, request, pk=None):
        """Marquer un appel sans réponse (NRP)."""
        demande = self.get_object()
        notes = request.data.get('notes', '')
        NRPLog.objects.create(demande=demande, commercial=request.user, notes=notes)
        return Response({'nrp_count': demande.nrp_logs.count()})

    @action(detail=True, methods=['post'])
    def affecter(self, request, pk=None):
        """Affecter la demande à un commercial."""
        demande = self.get_object()
        commercial_id = request.data.get('commercial_id')
        if not commercial_id:
            return Response({'error': 'commercial_id requis'}, status=400)
        from accounts.models import User
        try:
            commercial = User.objects.get(pk=commercial_id, is_active=True)
        except User.DoesNotExist:
            return Response({'error': 'Commercial introuvable'}, status=404)
        demande.assigned_to = commercial
        demande.save()
        self._log_action(request.user, 'affecter', demande)
        return Response(DemandeSerializer(demande).data)

    @action(detail=True, methods=['post'])
    def confirmer_cao(self, request, pk=None):
        """Confirmer avant opération (CAO)."""
        demande = self.get_object()
        demande.cao = True
        demande.save()
        return Response({'cao': True})

    def _log_action(self, user, action, demande):
        AuditLog.objects.create(
            user=user,
            action=action,
            model_name='Demande',
            object_id=demande.pk,
            extra_data={'statut': demande.statut}
        )


class PublicDemandeCreateView(viewsets.GenericViewSet):
    """Endpoint public pour créer une demande depuis le site web."""
    permission_classes = [AllowAny]
    serializer_class = PublicDemandeCreateSerializer

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        demande = serializer.save()
        return Response({'id': demande.pk, 'statut': demande.statut}, status=status.HTTP_201_CREATED)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['model_name', 'action', 'object_id']
    ordering = ['-timestamp']
