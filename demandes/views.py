from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from django.db.models import Model
from django.db.models import Q
from .models import Demande, NRPLog, Document, AuditLog, ProfilShare
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
from .utils.profile_card import generate_profile_card


class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.select_related('client', 'assigned_to').prefetch_related('nrp_logs', 'documents')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DemandeFilter
    search_fields = ['client__first_name', 'client__last_name', 'client__phone',
                     'client__entity_name', 'service']
    ordering_fields = ['created_at', 'date_intervention', 'statut']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_authenticated and user.role == 'commercial' and not user.is_staff:
            return queryset.filter(assigned_to=user)
        return queryset

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

        # AUTOMATION: Trigger feedback and update payment status if status changed to PRES_TERMINEE
        is_finished = changes.get('statut', {}).get('new') == Demande.PRES_TERMINEE
        if is_finished:
            # Paiement en attente
            demande.statut_paiement = Demande.EN_ATTENTE
            demande.save(update_fields=['statut_paiement'])
            self._trigger_automatic_feedback(demande)


        if changes:
            self._log_action(
                self.request.user,
                'update',
                demande,
                extra_data={'changes': changes}
            )

    def _trigger_automatic_feedback(self, demande):
        """Internal helper to send automatic feedback WhatsApp message."""
        client = demande.client
        if client and client.opt_out_feedback:
            # Client has unsubscribed
            self._log_action(None, 'feedback_skip_optout', demande)
            return

        # Prepare variables for template 'demande_feedback_client_v1'
        client_phone = client.phone if client else demande.formulaire_data.get('whatsapp_phone')
        client_name = client.display_name if client else demande.formulaire_data.get('nom', 'Client')
        
        if not client_phone:
            return

        from agencemenage.utils import encode_id
        encoded_id = encode_id(demande.id)
        feedback_link = f"https://feedback.agencemenage.ma/feedback/{encoded_id}"
        vars = [client_name, feedback_link]

        try:
            from .utils.whatsapp import WhatsAppService
            WhatsAppService.send_template_message(
                to=client_phone,
                template_name='demande_feedback_client_v1',
                variables=vars
            )
            self._log_action(None, 'auto_send_wa_feedback', demande)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error sending auto feedback WA: {str(e)}")

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

    @action(detail=False, methods=['get'])
    def notifications_urgentes(self, request):
        from django.utils import timezone
        import datetime
        limit_date = timezone.now() - datetime.timedelta(hours=20)
        
        urgentes = Demande.objects.select_related('client').filter(
            statut=Demande.EN_ATTENTE, 
            created_at__lte=limit_date
        ).order_by('created_at')
        
        data = []
        for d in urgentes:
            diff = timezone.now() - d.created_at
            hours = int(diff.total_seconds() // 3600)
            client_name = d.client.display_name if d.client else d.formulaire_data.get('nom', 'Client')
            data.append({
                'id': d.id,
                'client': client_name,
                'service': d.service,
                'hours_pending': hours,
                'created_at': d.created_at.isoformat()
            })
            
        return Response(data)

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
        # On utilise une requête directe pour éviter le cache du prefetch_related
        count = NRPLog.objects.filter(demande=demande).count()
        return Response({'nrp_count': count})

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
    def confirmer_client(self, request, pk=None):
        """Confirme que le client suspect est bien le même que potential_duplicate_client."""
        demande = self.get_object()
        if not demande.potential_duplicate_client:
            return Response({'error': 'Aucun doublon potentiel détecté.'}, status=400)
        
        old_client = demande.client
        target_client = demande.potential_duplicate_client
        
        # Link demand to existing client
        demande.client = target_client
        demande.identification_statut = Demande.ID_EXISTANT
        demande.potential_duplicate_client = None
        demande.save()
        
        # Delete temporary client if no other demands
        if old_client and old_client != target_client:
            if old_client.demandes.count() == 0:
                old_client.delete()
        
        self._log_action(request.user, 'confirmer_client_existant', demande, extra_data={'client_id': target_client.id})
        return Response(DemandeSerializer(demande).data)

    @action(detail=True, methods=['post'])
    def nouveau_client(self, request, pk=None):
        """Confirme qu'il s'agit d'un nouveau client (numéro réattribué)."""
        demande = self.get_object()
        if not demande.potential_duplicate_client:
            return Response({'error': 'Aucun doublon potentiel détecté.'}, status=400)
        
        old_client = demande.potential_duplicate_client
        current_client = demande.client
        
        # Dissociate phone from old client
        if old_client.phone == current_client.phone:
            if not old_client.phone_history:
                old_client.phone_history = []
            old_client.phone_history.append({
                'phone': old_client.phone,
                'date_end': datetime.datetime.now().isoformat(),
                'status': 'inactive'
            })
            # Clear or prefix old phone
            old_client.phone = f"OLD_{old_client.id}_{old_client.phone}"
            old_client.save()
            
        demande.identification_statut = Demande.ID_NOUVELLE
        demande.potential_duplicate_client = None
        demande.save()
        
        self._log_action(request.user, 'confirmer_nouveau_client_reattribue', demande)
        return Response(DemandeSerializer(demande).data)

    @action(detail=True, methods=['post'])
    def generate_document(self, request, pk=None):
        """Génère un document (PDF ou PNG) pour cette demande."""
        demande = self.get_object()
        doc_type = request.data.get('type')  # 'devis', 'png' or 'facture'
        
        if doc_type not in ['devis', 'png', 'facture']:
            return Response({'error': 'Type de document invalide (devis, png ou facture requis)'}, status=400)
            
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
        doc_type = request.data.get('type')  # 'devis', 'png', 'cao_profil', 'feedback'
        profile_agent_id = request.data.get('profile_agent_id')
        # Le frontend peut fournir directement l'URL publique du document uploadé
        frontend_media_url = request.data.get('media_url')
        
        if not doc_type:
            return Response({'error': 'Le type de document est requis.'}, status=400)
            
        client_phone = demande.client.phone if demande.client else None
        if not client_phone:
            # Essayer de récupérer le numéro depuis les données de formulaire
            client_phone = demande.formulaire_data.get('whatsapp_phone') or demande.formulaire_data.get('phone')
            if not client_phone:
                return Response({'error': 'Numéro de téléphone du client manquant.'}, status=400)
                
        client_name = demande.client.display_name if demande.client else demande.client_name or demande.formulaire_data.get('nom', 'Client')
        
        import logging
        logger = logging.getLogger(__name__)
        
        # Initialisation
        media_url = None
        wa_media_type = None

        # Feature flag "Bypass" : Ne pas envoyer réellement les nouveaux templates s'ils sont instables ou non validés
        BYPASS_NEW_TEMPLATES = getattr(settings, 'BYPASS_NEW_WA_TEMPLATES', False)

        # Pour les types utilisant un document (devis, png, facture)
        if doc_type in ['devis', 'png', 'facture']:
            # Priorité 1 : URL fournie par le frontend (document fraîchement uploadé)
            if frontend_media_url:
                media_url = frontend_media_url
                logger.info(f"WhatsApp: Using frontend-provided media_url: {media_url}")
            else:
                # Priorité 2 : Construire l'URL depuis le dernier document en base
                doc = demande.documents.filter(type_document=doc_type).order_by('-created_at').first()

                if not doc:
                    return Response({'error': f'Aucun document de type "{doc_type}" trouvé. Veuillez d\'abord générer le document.'}, status=404)
                
                if not doc.fichier or not doc.fichier.name:
                    return Response({'error': f'Le document existe mais n\'a pas de fichier attaché. Veuillez le re-générer.'}, status=404)
                
                media_path = doc.fichier.name.lstrip('/')
                media_url = f"{settings.API_BASE_URL}/api/media/{media_path}"
                logger.info(f"WhatsApp: Constructed media_url from DB: {media_url}")
            
            wa_media_type = 'document' if doc_type in ['devis', 'facture'] else 'image'
            logger.info(f"WhatsApp: Final media_url={media_url}, type={wa_media_type}, phone={client_phone}")

        # Définition des templates et variables
        template = None
        vars = []

        if doc_type == 'devis':
            template = 'envoi_devis_client'
            vars = [client_name, f"D-{demande.id:05d}", demande.service, f"{demande.prix}"]
            
        elif doc_type == 'png':
            template = 'envoi_resume_client'
            vars = [
                client_name, 
                demande.service, 
                demande.date_intervention.strftime('%d/%m/%Y') if demande.date_intervention else "Non définie",
                demande.heure_intervention or "—",
                f"{demande.prix}"
            ]
            
        elif doc_type == 'facture':
            template = 'facture_client'
            # Format price with thousands separator
            formatted_total = f"{demande.prix:,.2f}".replace(",", " ") if demande.prix else "0.00"
            invoice_num = f"AM/F{demande.id:03d}/{datetime.datetime.now().year}"
            
            vars = [
                client_name,
                invoice_num,
                datetime.date.today().strftime('%d/%m/%Y'),
                demande.service,
                formatted_total
            ]
            
        elif doc_type == 'cao_profil':
            template = 'envoi_profil_candidate_v1'
            profiles = demande.profils_envoyes.order_by('id')

            if profile_agent_id:
                profiles = profiles.filter(pk=profile_agent_id)

            if not profiles.exists():
                return Response({'error': 'Aucun profil assigné pour cet envoi.'}, status=400)

            results = []
            success_count = 0

            for agent in profiles:
                share, _ = ProfilShare.objects.get_or_create(demande=demande, agent=agent)
                profile_link = f"https://profil.agencemenage.ma/view/{share.uuid}"
                vars = [client_name, profile_link]

                res = WhatsAppService.send_template_message(
                    to=client_phone,
                    template_name=template,
                    media_url=None,
                    media_type=None,
                    variables=vars
                )

                sent = bool(res)
                if sent:
                    success_count += 1
                    self._log_action(
                        request.user,
                        f'send_wa_{doc_type}',
                        demande,
                        extra_data={
                            'agent_id': agent.id,
                            'agent_name': getattr(agent, 'full_name', '') or f"{agent.first_name} {agent.last_name}".strip(),
                        }
                    )

                results.append({
                    'agent_id': agent.id,
                    'agent_name': getattr(agent, 'full_name', '') or f"{agent.first_name} {agent.last_name}".strip(),
                    'success': sent,
                })

            if success_count > 0:
                return Response({
                    'success': True,
                    'sent_count': success_count,
                    'total': profiles.count(),
                    'results': results,
                })

            return Response({'error': "Échec de l'envoi WhatsApp via l'API (Service tiers indisponible ou bloqué).", 'results': results}, status=502)
            
        elif doc_type == 'feedback':
            template = 'demande_feedback_client_v1'
            from agencemenage.utils import encode_id
            encoded_id = encode_id(demande.id)
            feedback_link = f"https://feedback.agencemenage.ma/feedback/{encoded_id}"
            vars = [client_name, feedback_link]
        else:
            return Response({'error': f"Type non supporté : {doc_type}"}, status=400)
            
        if not template:
            return Response({'error': f"Template non défini pour le type {doc_type}"}, status=500)
            
        # Appel API réel
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
            return Response({'error': "Échec de l'envoi WhatsApp via l'API (Service tiers indisponible ou bloqué)."}, status=502)

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
            # Return existing share if any, or create one
            share = ProfilShare.objects.filter(demande=demande, agent=agent).first()
            if not share:
                share = ProfilShare.objects.create(demande=demande, agent=agent)
            return Response({'success': True, 'message': 'Profil déjà envoyé.', 'share_id': share.uuid})
            
        demande.profils_envoyes.add(agent)
        share = ProfilShare.objects.create(demande=demande, agent=agent)
        
        # --- GÉNÉRATION FICHE PROFIL PNG ---
        try:
            # Calcul de l'âge
            age = "—"
            if agent.birth_date:
                today = datetime.date.today()
                age = today.year - agent.birth_date.year - ((today.month, today.day) < (agent.birth_date.month, agent.birth_date.day))
            
            # Chemins
            logo_path = os.path.join(settings.BASE_DIR, 'assets', 'logo.png')
            photo_path = agent.photo.path if agent.photo else None
            
            # On génère un nom de fichier unique
            filename = f"FICHE_{agent.first_name}_{agent.last_name}_{demande.id}.png".replace(' ', '_')
            output_dir = os.path.join(settings.MEDIA_ROOT, 'documents', datetime.datetime.now().strftime("%Y/%m"))
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, filename)
            
            # On génère la fiche systématiquement (le générateur gère l'absence de photo)
            generate_profile_card(
                nom=agent.last_name,
                prenom=agent.first_name,
                age=age if isinstance(age, int) else 30,
                adresse=f"{agent.neighborhood} - {agent.city}",
                logo_path=logo_path,
                profile_photo_path=photo_path if photo_path and os.path.exists(photo_path) else "",
                output_path=output_path
            )
            
            # Enregistrement en tant que Document
            relative_path = os.path.relpath(output_path, settings.MEDIA_ROOT)
            Document.objects.create(
                demande=demande,
                type_document='png',
                nom=f"Fiche Profil {agent.full_name}",
                fichier=relative_path,
                created_by=request.user
            )
        except Exception as e:
            # On log l'erreur sans bloquer le reste (le partage de lien est prioritaire)
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erreur lors de la génération de la fiche profil : {str(e)}")

        self._log_action(request.user, 'envoyer_profil', demande, extra_data={
            'agent_id': agent.pk,
            'agent_name': agent.full_name,
            'share_id': str(share.uuid),
            'client_name': demande.client.display_name if demande.client else 'Inconnu'
        })
        return Response({'success': True, 'agent_id': agent.pk, 'demande_id': demande.pk, 'share_id': share.uuid})

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
