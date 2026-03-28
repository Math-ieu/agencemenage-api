from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from .models import Demande, NRPLog, Document, AuditLog
from .utils.document_generators import generate_devis_pdf, generate_recap_png
import datetime
import mimetypes
import os
from .serializers import (
    DemandeSerializer, DemandeListSerializer,
    NRPLogSerializer, DocumentSerializer,
    PublicDemandeCreateSerializer, AuditLogSerializer
)
from accounts.serializers import UserSerializer
from .filters import DemandeFilter


class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.select_related('client', 'assigned_to').prefetch_related('nrp_logs', 'documents')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DemandeFilter
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

    @action(detail=True, methods=['post'])
    def generate_document(self, request, pk=None):
        """Génère un document (PDF ou PNG) pour cette demande."""
        demande = self.get_object()
        doc_type = request.data.get('type')  # 'devis' or 'png'
        
        if doc_type not in ['devis', 'png']:
            return Response({'error': 'Type de document invalide (devis ou png requis)'}, status=400)
            
        client = demande.client
        client_nom = client.display_name if client else "Client"
        client_phone = client.phone if client else ""
        client_adresse = demande.formulaire_data.get('adresse', client.neighborhood if client else "")
        
        # Préparation des données pour le générateur
        data = {
            'numero': str(demande.pk),
            'date': datetime.datetime.now().strftime("%d %B %Y"),
            'client_nom': client_nom,
            'client_telephone': client_phone,
            'client_adresse': client_adresse,
            'service_type': demande.service,
            'segment': demande.get_segment_display(),
            'intervenants': demande.formulaire_data.get('nb_intervenants', demande.formulaire_data.get('nb_personnel', 1)),
            'frequence': demande.frequency_label or demande.get_frequency_display(),
            'total': f"{demande.prix}" if demande.prix else "À définir"
        }
        
        try:
            if doc_type == 'devis':
                pdf_bytes = generate_devis_pdf(data)
                filename = f"DEVIS_{client_nom.replace(' ', '_')}_{demande.pk}.pdf"
                content_type = Document.DEVIS
            else:
                pdf_bytes = generate_recap_png(data)
                filename = f"RECAP_{client_nom.replace(' ', '_')}_{demande.pk}.png"
                content_type = Document.PNG
                
            # Création du Document
            doc = Document.objects.create(
                demande=demande,
                type_document=content_type,
                nom=filename,
                created_by=request.user
            )
            # Sauvegarde du fichier physique
            doc.fichier.save(filename, ContentFile(pdf_bytes))
            
            self._log_action(request.user, f'generate_{doc_type}', demande)
            return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    def _log_action(self, user, action, demande):
        AuditLog.objects.create(
            user=user,
            action=action,
            model_name='Demande',
            object_id=demande.pk,
            extra_data={'statut': demande.statut}
        )

    @action(detail=True, methods=['get'], url_path=r'download/(?P<doc_id>\d+)')
    def download_document(self, request, pk=None, doc_id=None):
        """Endpoint sécurisé qui streame un document via l'authentification JWT.
        Ne révèle jamais le chemin réel du fichier sur le serveur."""
        demande = self.get_object()  # vérifie que l'utilisateur a accès
        try:
            doc = Document.objects.get(pk=doc_id, demande=demande)
        except Document.DoesNotExist:
            raise Http404('Document introuvable.')

        if not doc.fichier or not doc.fichier.name:
            raise Http404('Fichier non disponible.')

        try:
            file_handle = doc.fichier.open('rb')
        except FileNotFoundError:
            raise Http404('Fichier introuvable sur le serveur.')

        mime_type, _ = mimetypes.guess_type(doc.fichier.name)
        mime_type = mime_type or 'application/octet-stream'
        filename = os.path.basename(doc.fichier.name)
        safe_name = doc.nom or filename

        response = FileResponse(file_handle, content_type=mime_type)
        response['Content-Disposition'] = f'attachment; filename="{safe_name}"'
        response['X-Content-Type-Options'] = 'nosniff'
        # Empêche tout cache et cache de proxy pour les fichiers privés
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        return response


class PublicDemandeCreateView(viewsets.GenericViewSet):
    """Endpoint public pour créer une demande depuis le site web."""
    permission_classes = [AllowAny]
    serializer_class = PublicDemandeCreateSerializer

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        demande = serializer.save()
        return Response({'id': demande.pk, 'statut': demande.statut}, status=status.HTTP_201_CREATED)


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['model_name', 'action', 'object_id']
    ordering = ['-timestamp']
