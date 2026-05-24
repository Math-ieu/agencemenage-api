from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django.http import HttpResponse
import csv
from .models import Facture, Paiement, EntreeCaisse
from .serializers import FactureSerializer, PaiementSerializer, EntreeCaisseSerializer
from django.db.models import Sum, Q
from django.utils import timezone


class FactureViewSet(viewsets.ModelViewSet):
    from rest_framework.permissions import IsAuthenticated
    from accounts.permissions import RoleBasedPermission
    permission_classes = [IsAuthenticated, RoleBasedPermission]

    queryset = Facture.objects.select_related('client', 'demande').prefetch_related('paiements')
    serializer_class = FactureSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['statut', 'client']
    search_fields = ['numero', 'client__first_name', 'client__last_name', 'client__entity_name']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PaiementViewSet(viewsets.ModelViewSet):
    from rest_framework.permissions import IsAuthenticated
    from accounts.permissions import RoleBasedPermission
    permission_classes = [IsAuthenticated, RoleBasedPermission]

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
    from rest_framework.permissions import IsAuthenticated
    from accounts.permissions import RoleBasedPermission
    permission_classes = [IsAuthenticated, RoleBasedPermission]

    queryset = EntreeCaisse.objects.all()
    serializer_class = EntreeCaisseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['type_mouvement', 'mode_paiement', 'date', 'client']
    ordering = ['-date']
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = super().get_queryset().select_related('client', 'created_by')

        search = self.request.query_params.get('search')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if search:
            queryset = queryset.filter(
                Q(description__icontains=search)
                | Q(client_nom__icontains=search)
                | Q(utilisateur__icontains=search)
                | Q(client__first_name__icontains=search)
                | Q(client__last_name__icontains=search)
                | Q(client__entity_name__icontains=search)
            )

        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def solde(self, request):
        """Calcule le solde total de la caisse."""
        entrees = EntreeCaisse.objects.filter(type_mouvement='entree').aggregate(t=Sum('montant'))['t'] or 0
        sorties = EntreeCaisse.objects.filter(type_mouvement='sortie').aggregate(t=Sum('montant'))['t'] or 0
        alimentations = EntreeCaisse.objects.filter(type_mouvement='alimentation').aggregate(t=Sum('montant'))['t'] or 0
        
        return Response({
            'total_entrees': entrees,
            'total_sorties': sorties,
            'solde': entrees - sorties + alimentations,
            'solde_jour': entrees - sorties - alimentations,
            'operations_count': EntreeCaisse.objects.count()
        })

    @action(detail=False, methods=['get'])
    def export_csv(self, request):
        """Exporte les mouvements de caisse en CSV en respectant les filtres courants."""
        queryset = self.filter_queryset(self.get_queryset())

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="mouvements_caisse.csv"'
        response.write('\ufeff')

        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'Date',
            'Type',
            'Libelle',
            'Client',
            'Mode paiement',
            'Montant (MAD)',
            'Utilisateur',
            'Document',
            'Notes',
        ])

        for item in queryset:
            writer.writerow([
                item.date.strftime('%d/%m/%Y') if item.date else '',
                item.get_type_mouvement_display(),
                item.description,
                item.client_display,
                item.get_mode_paiement_display(),
                str(item.montant),
                item.utilisateur,
                item.document_file.url if item.document_file else '',
                item.notes,
            ])

        return response
