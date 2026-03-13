from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Facture, Paiement, EntreeCaisse
from .serializers import FactureSerializer, PaiementSerializer, EntreeCaisseSerializer
from django.db.models import Sum


class FactureViewSet(viewsets.ModelViewSet):
    queryset = Facture.objects.select_related('client', 'demande').prefetch_related('paiements')
    serializer_class = FactureSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['statut', 'client']
    search_fields = ['numero', 'client__first_name', 'client__last_name', 'client__entity_name']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PaiementViewSet(viewsets.ModelViewSet):
    queryset = Paiement.objects.select_related('facture').all()
    serializer_class = PaiementSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['mode', 'facture']
    ordering = ['-date']

    def perform_create(self, serializer):
        paiement = serializer.save(created_by=self.request.user)
        # Update facture statut and montant_paye
        facture = paiement.facture
        total_paye = facture.paiements.aggregate(t=Sum('montant'))['t'] or 0
        facture.montant_paye = total_paye
        if total_paye >= facture.montant_total:
            facture.statut = Facture.PAYE
        elif total_paye > 0:
            facture.statut = Facture.PARTIEL
        facture.save()


class EntreeCaisseViewSet(viewsets.ModelViewSet):
    queryset = EntreeCaisse.objects.all()
    serializer_class = EntreeCaisseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['type_mouvement', 'date']
    ordering = ['-date']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def solde(self, request):
        """Calcule le solde total de la caisse."""
        from django.db.models import Sum, Q
        entrees = EntreeCaisse.objects.filter(type_mouvement='entree').aggregate(t=Sum('montant'))['t'] or 0
        sorties = EntreeCaisse.objects.filter(type_mouvement='sortie').aggregate(t=Sum('montant'))['t'] or 0
        return Response({
            'total_entrees': entrees,
            'total_sorties': sorties,
            'solde': entrees - sorties
        })
