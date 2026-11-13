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

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        from accounts.permissions import is_exempt_from_ownership, map_role_to_db_key
        if not user or not user.is_authenticated or user.role == 'admin':
            return qs

        if user.role == 'responsable_facturation':
            return qs.filter(source=Facture.SOURCE_AIRBNB)
        if user.role == 'client_conciergerie':
            if user.client_id:
                return qs.filter(source=Facture.SOURCE_AIRBNB, client_id=user.client_id)
            return qs.none()
        if user.role in ['runner', 'responsable_linge', 'operationnel']:
            return qs.none()
        if user.role in ['responsable_operations', 'charge_operations']:
            return qs.exclude(source=Facture.SOURCE_AIRBNB)

        if not is_exempt_from_ownership(user):
            from accounts.models import RolePermission
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []

            has_consulter_factures = any(p in permissions_list for p in [
                'consulter_factures', 'voir_la_caisse', 'mouvements_caisse',
                'consulter_tresorerie', 'consulter_dus_agences_profils'
            ])
            if not has_consulter_factures:
                qs = qs.filter(
                    Q(demande__created_by=user) |
                    Q(demande__assigned_to=user) |
                    Q(demande__assigned_to_operations=user) |
                    Q(source=Facture.SOURCE_AIRBNB, client__assigned_commercial=user)
                )
            elif user.role == 'commercial':
                qs = qs.filter(~Q(source=Facture.SOURCE_AIRBNB) | Q(client__assigned_commercial=user))
        return qs
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['statut', 'client', 'source']
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

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        from accounts.permissions import is_exempt_from_ownership, map_role_to_db_key
        if not user or not user.is_authenticated or user.role == 'admin':
            return qs

        if user.role == 'responsable_facturation':
            return qs.filter(facture__source=Facture.SOURCE_AIRBNB)
        if user.role == 'client_conciergerie':
            if user.client_id:
                return qs.filter(facture__source=Facture.SOURCE_AIRBNB, facture__client_id=user.client_id)
            return qs.none()
        if user.role in ['runner', 'responsable_linge', 'operationnel']:
            return qs.none()
        if user.role in ['responsable_operations', 'charge_operations']:
            return qs.exclude(facture__source=Facture.SOURCE_AIRBNB)

        if not is_exempt_from_ownership(user):
            from accounts.models import RolePermission
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []

            has_consulter_factures = any(p in permissions_list for p in [
                'consulter_factures', 'voir_la_caisse', 'mouvements_caisse',
                'consulter_tresorerie', 'consulter_dus_agences_profils'
            ])
            if not has_consulter_factures:
                qs = qs.filter(
                    Q(facture__demande__created_by=user) |
                    Q(facture__demande__assigned_to=user) |
                    Q(facture__demande__assigned_to_operations=user) |
                    Q(facture__source=Facture.SOURCE_AIRBNB, facture__client__assigned_commercial=user)
                )
            elif user.role == 'commercial':
                qs = qs.filter(~Q(facture__source=Facture.SOURCE_AIRBNB) | Q(facture__client__assigned_commercial=user))
        return qs
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

        if facture.source == Facture.SOURCE_AIRBNB:
            self._sync_airbnb_caisse_and_suspension(paiement, facture)

    def _sync_airbnb_caisse_and_suspension(self, paiement, facture):
        if not getattr(paiement, '_skip_caisse_hook', False) and not EntreeCaisse.objects.filter(paiement=paiement).exists():
            is_especes = (paiement.mode == Paiement.ESPECES)
            caisse_type = EntreeCaisse.CAISSE if is_especes else EntreeCaisse.TRESORERIE
            categorie = 'Virement client reçu' if paiement.mode == Paiement.VIREMENT else 'Encaissement client (auto)'
            mode_map = {
                Paiement.ESPECES: EntreeCaisse.ESPECES,
                Paiement.VIREMENT: EntreeCaisse.VIREMENT,
                Paiement.CHEQUE: EntreeCaisse.CHEQUE,
                Paiement.CARTE: EntreeCaisse.VIREMENT,
            }
            user_display = ''
            if self.request.user and self.request.user.is_authenticated:
                user_display = self.request.user.full_name or self.request.user.username or self.request.user.email
            EntreeCaisse.objects.create(
                type_mouvement=EntreeCaisse.ENTREE,
                categorie=categorie,
                caisse_type=caisse_type,
                montant=paiement.montant,
                description=f"Encaissement facture Airbnb {facture.numero}",
                date=paiement.date,
                mode_paiement=mode_map.get(paiement.mode, EntreeCaisse.VIREMENT),
                client=facture.client,
                client_nom=facture.client.display_name if facture.client else '',
                utilisateur=user_display,
                notes=paiement.notes or (f"Réf: {paiement.reference}" if paiement.reference else ''),
                paiement=paiement,
                created_by=self.request.user if self.request.user.is_authenticated else None,
            )

        if facture.client:
            try:
                from airbnb.services.suspension_helper import check_and_lift_client_suspension
                check_and_lift_client_suspension(
                    facture.client,
                    user=self.request.user if self.request.user.is_authenticated else None,
                )
            except Exception:
                pass


class EntreeCaisseViewSet(viewsets.ModelViewSet):
    from rest_framework.permissions import IsAuthenticated
    from accounts.permissions import RoleBasedPermission
    permission_classes = [IsAuthenticated, RoleBasedPermission]

    queryset = EntreeCaisse.objects.all()
    serializer_class = EntreeCaisseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['type_mouvement', 'mode_paiement', 'date', 'client', 'categorie', 'utilisateur', 'caisse_type']
    ordering = ['-date', '-id']
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().select_related('client', 'created_by')
        from accounts.permissions import is_exempt_from_ownership
        if user and user.is_authenticated and not is_exempt_from_ownership(user):
            from accounts.models import RolePermission
            from accounts.permissions import map_role_to_db_key
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []
                
            has_consulter_caisse = any(p in permissions_list for p in [
                'mouvements_caisse', 'consulter_tresorerie', 'consulter_solde_caisse', 'sorties_caisse'
            ])
            if not has_consulter_caisse:
                from django.db.models import Q
                queryset = queryset.filter(
                    Q(paiement__facture__demande__created_by=user) |
                    Q(paiement__facture__demande__assigned_to=user) |
                    Q(paiement__facture__demande__assigned_to_operations=user) |
                    Q(client__assigned_commercial=user) |
                    Q(client__demandes__created_by=user) |
                    Q(client__demandes__assigned_to=user) |
                    Q(client__demandes__assigned_to_operations=user)
                ).distinct()

        if self.action not in ['retrieve', 'update', 'partial_update', 'destroy']:
            caisse_type = self.request.query_params.get('caisse_type', 'caisse')
            queryset = queryset.filter(caisse_type=caisse_type)

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
                | Q(categorie__icontains=search)
                | Q(notes__icontains=search)
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
        """Calcule le solde total de la caisse/trésorerie."""
        caisse_type = request.query_params.get('caisse_type', 'caisse')
        qs = self.get_queryset().filter(caisse_type=caisse_type)
        entrees = qs.filter(type_mouvement='entree').aggregate(t=Sum('montant'))['t'] or 0
        sorties = qs.filter(type_mouvement='sortie').aggregate(t=Sum('montant'))['t'] or 0
        alimentations = qs.filter(type_mouvement='alimentation').aggregate(t=Sum('montant'))['t'] or 0
        
        return Response({
            'total_entrees': entrees,
            'total_sorties': sorties,
            'solde': entrees - sorties + alimentations,
            'solde_jour': entrees - sorties - alimentations,
            'operations_count': qs.count()
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
            'Catégorie',
            'Libelle',
            'Client',
            'Mode paiement',
            'Montant (MAD)',
            'Saisi par',
            'Document',
            'Notes',
        ])

        for item in queryset:
            writer.writerow([
                item.date.strftime('%d/%m/%Y') if item.date else '',
                item.get_type_mouvement_display(),
                item.categorie,
                item.description,
                item.client_display,
                item.get_mode_paiement_display(),
                str(item.montant),
                item.utilisateur,
                item.document_file.url if item.document_file else '',
                item.notes,
            ])

        return response
