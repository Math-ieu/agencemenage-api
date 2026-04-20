from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from django.db.models import Model
from django.db.models import Q
from .models import Demande, NRPLog, Document, AuditLog
from .utils.document_generators import generate_devis_pdf, generate_recap_png
import datetime
import mimetypes
import os
from decimal import Decimal
from django.conf import settings
from .utils.whatsapp import WhatsAppService
from .serializers import (
    DemandeSerializer, DemandeListSerializer,
    NRPLogSerializer, DocumentSerializer,
    PublicDemandeCreateSerializer, AuditLogSerializer, DemandeHistoriqueSerializer
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

    def perform_update(self, serializer):
        instance = serializer.instance
        validated_data = serializer.validated_data

        changes = {}
        for field_name, new_value in validated_data.items():
            old_value = getattr(instance, field_name, None)
            old_log_value = self._to_log_value(old_value)
            new_log_value = self._to_log_value(new_value)
            if old_log_value != new_log_value:
                changes[field_name] = {
                    'old': old_log_value,
                    'new': new_log_value,
                }

        demande = serializer.save()

        if changes:
            self._log_action(
                self.request.user,
                'update',
                demande,
                extra_data={'changes': changes}
            )

    @action(detail=False, methods=['get'])
    def historique(self, request):
        queryset = Demande.objects.select_related('client').prefetch_related('profils_envoyes').order_by('-created_at')

        search = (request.query_params.get('search') or '').strip()
        if search:
            query = (
                Q(client__first_name__icontains=search)
                | Q(client__last_name__icontains=search)
                | Q(client__entity_name__icontains=search)
                | Q(service__icontains=search)
            )

            search_ref = search.lstrip('#').strip()
            if search_ref.isdigit():
                query |= Q(id=int(search_ref))

            queryset = queryset.filter(query)

        date_value = (request.query_params.get('date') or '').strip()
        if date_value:
            queryset = queryset.filter(created_at__date=date_value)

        page = self.paginate_queryset(queryset)
        serializer = DemandeHistoriqueSerializer(page if page is not None else queryset, many=True)

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

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
        self._log_action(request.user, 'affecter', demande, extra_data={'commercial_id': commercial_id, 'commercial_name': commercial.full_name})
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
            from .utils.document_helpers import generate_demande_document
            doc = generate_demande_document(demande, doc_type, user=request.user)
            self._log_action(request.user, f'generate_{doc_type}', demande)
            return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=True, methods=['post'])
    def send_whatsapp(self, request, pk=None):
        """Action manuelle pour envoyer un document spécifique via WhatsApp."""
        demande = self.get_object()
        doc_type = request.data.get('type')  # 'devis' ou 'png'
        
        if not doc_type:
            return Response({'error': 'Le type de document est requis.'}, status=400)
            
        # Trouver le dernier document de ce type
        doc = demande.documents.filter(type_document=doc_type).first()
        if not doc:
            return Response({'error': f'Aucun document de type {doc_type} trouvé pour cette demande.'}, status=404)
            
        client_phone = demande.client.phone if demande.client else None
        if not client_phone:
            return Response({'error': 'Numéro de téléphone du client manquant.'}, status=400)
            
        # Construction de l'URL absolue
        media_url = f"{settings.API_BASE_URL}/api/media/{doc.fichier.name}"
        client_name = demande.client.display_name if demande.client else "Client"
        
        # Variables du template
        if doc_type == 'devis':
            template = 'envoi_devis_client'
            vars = [client_name, f"D-{demande.id:05d}", demande.service, f"{demande.prix}"]
            wa_media_type = 'document'
        else:
            template = 'envoi_resume_client'
            vars = [
                client_name, 
                demande.service, 
                demande.date_intervention.strftime('%d/%m/%Y') if demande.date_intervention else "Non définie",
                demande.heure_intervention or "—",
                f"{demande.prix}"
            ]
            wa_media_type = 'image'
            
        res = WhatsAppService.send_template_message(
            to=client_phone,
            template_name=template,
            media_url=media_url,
            media_type=wa_media_type,
            variables=vars
        )
        
        if res:
            self._log_action(request.user, f'send_wa_{doc_type}', demande)
            return Response({'success': True, 'wa_response': res})
        else:
            return Response({'error': "Échec de l'envoi WhatsApp via l'API."}, status=500)

    @action(detail=True, methods=['post'])
    def envoyer_profil(self, request, pk=None):
        """Affecter/envoyer un profil agent à cette demande."""
        demande = self.get_object()
        agent_id = request.data.get('agent_id')
        if not agent_id:
            return Response({'error': 'agent_id requis'}, status=400)
        from agents.models import Agent
        try:
            agent = Agent.objects.get(pk=agent_id)
        except Agent.DoesNotExist:
            return Response({'error': 'Profil introuvable'}, status=404)
        
        if demande.profils_envoyes.filter(pk=agent.pk).exists():
            return Response({'error': 'Ce profil est déjà affecté à cette demande.'}, status=400)
            
        demande.profils_envoyes.add(agent)
        self._log_action(request.user, 'envoyer_profil', demande, extra_data={
            'agent_id': agent.pk,
            'agent_name': agent.full_name,
            'client_name': demande.client.display_name if demande.client else 'Inconnu'
        })
        return Response({'success': True, 'agent_id': agent.pk, 'demande_id': demande.pk})

    def _log_action(self, user, action, demande, extra_data=None):
        data = {'statut': demande.statut}
        if extra_data:
            data.update(extra_data)
            
        AuditLog.objects.create(
            user=user,
            action=action,
            model_name='Demande',
            object_id=demande.pk,
            extra_data=data
        )

    def _to_log_value(self, value):
        if isinstance(value, Model):
            return value.pk
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: self._to_log_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._to_log_value(item) for item in value]
        return value

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
