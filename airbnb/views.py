import os
import uuid
import mimetypes
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Q
from django.core.files.storage import default_storage
from django.conf import settings
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import AirbnbConfig, Bien, CommandeAirbnb, FiletLinge, ObjetTrouve
from .serializers import (
    AirbnbConfigSerializer,
    BienListSerializer, BienDetailSerializer,
    CommandeAirbnbListSerializer, CommandeAirbnbDetailSerializer,
    FiletLingeSerializer, ObjetTrouveSerializer,
    PricingCalculateSerializer, AssignationSerializer, ClotureCommandeSerializer
)
from .services.codification_service import generate_bien_code
from .services.pricing_engine import calculate_commande_pricing, check_cutoff_constraint, get_airbnb_config
from .services.linen_engine import calculate_linen_pieces_and_amount, freeze_laundry_filet
from .services.ical_service import sync_bien_ical_turnovers
from .services.whatsapp_service import generate_mission_pdf_data, dispatch_missions_for_date
from agents.models import Agent
from accounts.models import User


class AirbnbConfigViewSet(viewsets.ModelViewSet):
    queryset = AirbnbConfig.objects.all()
    serializer_class = AirbnbConfigSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        config = get_airbnb_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)


class BienViewSet(viewsets.ModelViewSet):
    queryset = Bien.objects.select_related('client').prefetch_related('commandes', 'filets').all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['list']:
            return BienListSerializer
        return BienDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        client_id = self.request.query_params.get('client')
        typologie = self.request.query_params.get('typologie')
        zone_eloignee = self.request.query_params.get('zone_eloignee')
        is_active = self.request.query_params.get('is_active')
        search = self.request.query_params.get('search')

        if client_id:
            qs = qs.filter(client_id=client_id)
        if typologie:
            qs = qs.filter(typologie=typologie)
        if zone_eloignee in ['true', '1']:
            qs = qs.filter(zone_eloignee=True)
        if is_active in ['true', '1']:
            qs = qs.filter(is_active=True)
        elif is_active in ['false', '0']:
            qs = qs.filter(is_active=False)
        if search:
            qs = qs.filter(
                Q(code__icontains=search) |
                Q(nom_bien__icontains=search) |
                Q(quartier__icontains=search) |
                Q(client__first_name__icontains=search) |
                Q(client__last_name__icontains=search) |
                Q(client__entity_name__icontains=search)
            )
        return qs

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """KPIs pour l'Écran 01 (Clients & Biens)."""
        total_biens = Bien.objects.count()
        biens_actifs = Bien.objects.filter(is_active=True).count()
        
        # Clients avec biens airbnb
        clients_conciergerie = Bien.objects.values('client').distinct().count()
        
        # Biens en zone éloignée
        biens_zone_eloignee = Bien.objects.filter(zone_eloignee=True).count()
        
        # Alerte seuil < 3 biens
        clients_sous_seuil = (
            Bien.objects.values('client')
            .annotate(nb_biens=Count('id'))
            .filter(nb_biens__lt=3)
            .count()
        )

        return Response({
            'total_biens': total_biens,
            'biens_actifs': biens_actifs,
            'clients_conciergerie': clients_conciergerie,
            'biens_zone_eloignee': biens_zone_eloignee,
            'clients_sous_seuil_alerte': clients_sous_seuil,
        })

    @action(detail=False, methods=['get'])
    def generate_code_preview(self, request):
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response({'error': "client_id requis"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from clients.models import Client
            client = Client.objects.get(id=client_id)
            code = generate_bien_code(client)
            return Response({'code': code})
        except Client.DoesNotExist:
            return Response({'error': "Client introuvable"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def sync_ical(self, request, pk=None):
        bien = self.get_object()
        result = sync_bien_ical_turnovers(bien)
        return Response(result)


class CommandeAirbnbViewSet(viewsets.ModelViewSet):
    queryset = CommandeAirbnb.objects.select_related('bien', 'bien__client', 'intervenante', 'intervenante_2', 'runner').all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['list']:
            return CommandeAirbnbListSerializer
        return CommandeAirbnbDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        date_prestation = self.request.query_params.get('date')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        statut = self.request.query_params.get('statut')
        bien_id = self.request.query_params.get('bien')
        client_id = self.request.query_params.get('client')
        intervenante_id = self.request.query_params.get('intervenante')
        creneau = self.request.query_params.get('creneau')
        search = self.request.query_params.get('search')

        if date_prestation:
            qs = qs.filter(date_prestation=date_prestation)
        if date_from:
            qs = qs.filter(date_prestation__gte=date_from)
        if date_to:
            qs = qs.filter(date_prestation__lte=date_to)
        if statut:
            qs = qs.filter(statut=statut)
        if bien_id:
            qs = qs.filter(bien_id=bien_id)
        if client_id:
            qs = qs.filter(bien__client_id=client_id)
        if intervenante_id:
            qs = qs.filter(Q(intervenante_id=intervenante_id) | Q(intervenante_2_id=intervenante_id))
        if creneau:
            qs = qs.filter(creneau=creneau)
        if search:
            qs = qs.filter(
                Q(numero__icontains=search) |
                Q(bien__code__icontains=search) |
                Q(bien__nom_bien__icontains=search) |
                Q(bien__client__first_name__icontains=search) |
                Q(bien__client__last_name__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        # Auto-génération numéro si absent
        year = timezone.now().year
        count = CommandeAirbnb.objects.filter(created_at__year=year).count() + 1
        numero = f"CMD-{year}-{count:04d}"
        
        # Calcul auto du prix initial
        bien = serializer.validated_data.get('bien')
        options = serializer.validated_data.get('options', [])
        remise_en_etat = serializer.validated_data.get('remise_en_etat', Decimal('0.00'))
        pricing = calculate_commande_pricing(bien, options=options, remise_en_etat=remise_en_etat)
        
        serializer.save(
            numero=numero,
            created_by=self.request.user if self.request.user.is_authenticated else None,
            prix_menage=Decimal(str(pricing['prix_menage'])),
            supplement_zone=Decimal(str(pricing['supplement_zone'])),
            prix_options=Decimal(str(pricing['prix_options'])),
            total_ttc=Decimal(str(pricing['total_ttc_hors_linge']))
        )

    @action(detail=False, methods=['post'])
    def calculate_price(self, request):
        serializer = PricingCalculateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            bien = Bien.objects.get(id=serializer.validated_data['bien_id'])
        except Bien.DoesNotExist:
            return Response({'error': "Bien introuvable"}, status=status.HTTP_404_NOT_FOUND)

        pricing = calculate_commande_pricing(
            bien=bien,
            typologie=serializer.validated_data.get('typologie'),
            options=serializer.validated_data.get('options'),
            remise_en_etat=serializer.validated_data.get('remise_en_etat')
        )

        cutoff = {}
        if serializer.validated_data.get('date_prestation'):
            cutoff = check_cutoff_constraint(
                date_prestation=serializer.validated_data['date_prestation'],
                heure_prestation=serializer.validated_data.get('heure_prestation'),
                creneau=serializer.validated_data.get('creneau', 'matin')
            )

        return Response({
            'pricing': pricing,
            'cutoff': cutoff
        })

    @action(detail=True, methods=['post'])
    def assigner(self, request, pk=None):
        commande = self.get_object()
        serializer = AssignationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        intervenante_id = serializer.validated_data.get('intervenante_id')
        intervenante_2_id = serializer.validated_data.get('intervenante_2_id')
        runner_id = serializer.validated_data.get('runner_id')

        # RÈGLE MÉTIER OBLIGATOIRE : Si Villa / Riad -> 2 intervenantes requises
        if commande.bien.typologie == 'villa_riad' and not intervenante_2_id:
            return Response({
                'error': "Règle Villa/Riad : Cette typologie requiert strictement 2 femmes de ménage assignées."
            }, status=status.HTTP_400_BAD_REQUEST)

        commande.intervenante_id = intervenante_id
        commande.intervenante_2_id = intervenante_2_id
        if runner_id:
            commande.runner_id = runner_id
            
        commande.statut = 'assignee'
        commande.save()
        
        return Response({
            'success': True,
            'message': "Mission assignée avec succès.",
            'statut': commande.statut
        })

    @action(detail=True, methods=['post'])
    def cloturer(self, request, pk=None):
        commande = self.get_object()
        serializer = ClotureCommandeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        photos = serializer.validated_data.get('photos', [])
        # RÈGLE MÉTIER OBLIGATOIRE : Min 4 photos (Salon, Chambre, SDB, Cuisine)
        if len(photos) < 4:
            return Response({
                'error': "Clôture impossible : Minimum 4 photos obligatoires (Salon, Chambre, SDB, Cuisine)."
            }, status=status.HTTP_400_BAD_REQUEST)

        commande.photos_cloture = photos
        commande.rapport_notes = serializer.validated_data.get('rapport_notes', commande.rapport_notes)
        commande.statut = 'cloturee'
        commande.save()

        return Response({
            'success': True,
            'message': "Commande clôturée avec succès.",
            'statut': commande.statut
        })

    @action(detail=True, methods=['get'])
    def mission_pdf_data(self, request, pk=None):
        commande = self.get_object()
        data = generate_mission_pdf_data(commande)
        return Response(data)

    @action(detail=False, methods=['get'])
    def planning_grid(self, request):
        date_start = request.query_params.get('start', str(timezone.now().date()))
        days_count = int(request.query_params.get('days', 7))
        
        start = datetime.strptime(date_start, '%Y-%m-%d').date()
        end = start + timedelta(days=days_count)

        commandes = CommandeAirbnb.objects.filter(
            date_prestation__gte=start,
            date_prestation__lt=end
        ).select_related('bien', 'intervenante', 'intervenante_2', 'runner')

        serializer = CommandeAirbnbListSerializer(commandes, many=True)
        return Response({
            'start': str(start),
            'end': str(end),
            'commandes': serializer.data
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        today = timezone.now().date()
        total_mois = CommandeAirbnb.objects.filter(date_prestation__month=today.month, date_prestation__year=today.year).count()
        today_count = CommandeAirbnb.objects.filter(date_prestation=today).count()
        a_assigner_18h = CommandeAirbnb.objects.filter(
            date_prestation=today + timedelta(days=1),
            statut__in=['saisie', 'remontee_tdb']
        ).count()
        ecarts_linge = CommandeAirbnb.objects.filter(statut='ecart_linge').count()

        return Response({
            'total_mois': total_mois,
            'today_count': today_count,
            'a_assigner_demain_18h': a_assigner_18h,
            'ecarts_linge_en_cours': ecarts_linge
        })


class FiletLingeViewSet(viewsets.ModelViewSet):
    queryset = FiletLinge.objects.select_related('bien', 'commande_ramassage', 'commande_depot', 'fige_par').all()
    serializer_class = FiletLingeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        bien_id = self.request.query_params.get('bien')
        statut = self.request.query_params.get('statut')
        if bien_id:
            qs = qs.filter(bien_id=bien_id)
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    @action(detail=True, methods=['post'])
    def figer_montant(self, request, pk=None):
        filet = self.get_object()
        comptage_laverie = request.data.get('comptage_laverie')
        updated_filet = freeze_laundry_filet(
            filet=filet,
            user=request.user,
            comptage_laverie_final=comptage_laverie
        )
        serializer = self.get_serializer(updated_filet)
        return Response({
            'success': True,
            'message': f"Montant du linge figé à {updated_filet.montant} DH.",
            'filet': serializer.data
        })

    @action(detail=True, methods=['post'])
    def arbitrer_ecart(self, request, pk=None):
        filet = self.get_object()
        commentaire = request.data.get('commentaire', '')
        filet.ecart_arbitre = True
        filet.ecart_commentaire = commentaire
        filet.save()
        
        # Si la commande de ramassage était bloquée en 'ecart_linge', la débloquer
        if filet.commande_ramassage and filet.commande_ramassage.statut == 'ecart_linge':
            filet.commande_ramassage.statut = 'cloturee'
            filet.commande_ramassage.save()

        return Response({
            'success': True,
            'message': "Écart arbitré et validé."
        })

    @action(detail=False, methods=['get'])
    def tournee_runner(self, request):
        today = timezone.now().date()
        date_param = request.query_params.get('date', str(today))
        
        # Commandes avec passage linge pour cette date
        commandes = CommandeAirbnb.objects.filter(
            date_prestation=date_param,
            nature_linge__in=['depot_ramassage', 'depot_seul', 'ramassage_seul']
        ).select_related('bien', 'runner')

        serializer = CommandeAirbnbListSerializer(commandes, many=True)
        return Response({
            'date': date_param,
            'missions_runner': serializer.data
        })


class ObjetTrouveViewSet(viewsets.ModelViewSet):
    queryset = ObjetTrouve.objects.select_related('bien', 'commande').all()
    serializer_class = ObjetTrouveSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['post'])
    def restituer(self, request, pk=None):
        objet = self.get_object()
        remis_a = request.data.get('remis_a', '')
        objet.statut = 'restitue'
        objet.remis_a = remis_a
        objet.date_restitution = timezone.now()
        objet.save()
        return Response({
            'success': True,
            'message': f"Objet marqué comme restitué à {remis_a}."
        })


class AirbnbPhotoUploadView(APIView):
    """
    Endpoint pour le téléversement physique de photos du module Airbnb
    (photos de clôture 4/4, objets trouvés, photos de logements, accès/boîtes à clés, linge).
    
    Stocke physiquement le fichier dans le bucket Railway (ProxyS3Boto3Storage)
    ou en local selon la configuration de default_storage.
    
    URL: POST /api/airbnb/upload-photo/
    Body: multipart/form-data avec 'photo' (ou 'file') et optionnellement 'category'.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.pdf'}
    MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('photo') or request.FILES.get('file')
        if not file_obj:
            return Response(
                {'error': "Aucun fichier photo fourni dans la requête (clé attendue : 'photo' ou 'file')."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation de la taille
        if file_obj.size > self.MAX_FILE_SIZE:
            return Response(
                {'error': f"Le fichier est trop volumineux ({round(file_obj.size / (1024 * 1024), 2)} Mo). Limite maximale : 15 Mo."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validation de l'extension
        _, ext = os.path.splitext(file_obj.name)
        ext = ext.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return Response(
                {'error': f"Extension non supportée ({ext}). Formats autorisés : JPG, JPEG, PNG, WEBP, HEIC, PDF."},
                status=status.HTTP_400_BAD_REQUEST
            )

        category = request.data.get('category', 'general')
        # Nettoyage de la catégorie pour éviter tout path traversal
        safe_category = "".join(c for c in category if c.isalnum() or c in ('_', '-')) or 'general'
        
        # Génération d'un nom de fichier unique et sécurisé
        unique_id = uuid.uuid4().hex[:12]
        raw_name = os.path.basename(file_obj.name).replace(' ', '_')
        clean_filename = f"{unique_id}_{raw_name}"
        storage_path = f"airbnb/{safe_category}/{clean_filename}"

        try:
            saved_name = default_storage.save(storage_path, file_obj)
            # URL accessible via le proxy /api/media/
            clean_saved_name = saved_name.lstrip('/')
            media_prefix = getattr(settings, 'MEDIA_URL', '/api/media/').rstrip('/')
            media_url = f"{media_prefix}/{clean_saved_name}"
            
            content_type = file_obj.content_type or mimetypes.guess_type(saved_name)[0] or 'image/jpeg'

            return Response({
                'success': True,
                'url': media_url,
                'filename': clean_filename,
                'path': saved_name,
                'size': file_obj.size,
                'content_type': content_type,
                'category': safe_category
            }, status=status.HTTP_201_CREATED)
        except Exception as err:
            return Response(
                {'error': f"Erreur lors de l'enregistrement dans le bucket de stockage : {str(err)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

