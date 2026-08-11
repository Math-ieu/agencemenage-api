from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from django.db.models import Model
from django.db.models import Q
from .models import Demande, NRPLog, Document, AuditLog, ProfilShare, SubscriptionPlanning, AppNotification, FeteReligieuse
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
    PublicDemandeCreateSerializer, AuditLogSerializer, DemandeHistoriqueSerializer,
    SubscriptionPlanningSerializer, AppNotificationSerializer, FeteReligieuseSerializer
)
from accounts.serializers import UserSerializer
from .filters import DemandeFilter
from .utils.profile_card import generate_profile_card


def calculate_statut_mois_prochain_py(today_day=None, statut_facturation=None, statut_paiement=None, explicit_override=None):
    if today_day is None:
        today_day = datetime.date.today().day

    if explicit_override in ['Stand-by', 'Résilié']:
        return explicit_override

    is_paid = (statut_facturation == 'Payé') or (statut_paiement in [Demande.INTEGRAL, 'integral', 'paye', 'payee'])
    if is_paid or explicit_override == 'Actif':
        return 'Actif'

    if today_day < 15:
        if explicit_override and explicit_override not in ['Suspendu', 'En attente', 'Actif', 'Non défini']:
            return explicit_override
        return 'Non défini'

    if 15 <= today_day <= 17:
        if explicit_override in ['Facture envoyée', 'Actif']:
            return explicit_override
        return 'Facture envoyée'

    if 18 <= today_day <= 22:
        if explicit_override in ['1er rappel', 'Actif']:
            return explicit_override
        return '1er rappel'

    if 23 <= today_day <= 26:
        if explicit_override in ['2e rappel', 'Actif']:
            return explicit_override
        return '2e rappel'

    if today_day >= 27:
        if explicit_override in ['Suspendu', 'Actif']:
            return explicit_override
        return 'Suspendu'

    return 'Non défini'


class DemandeViewSet(viewsets.ModelViewSet):
    queryset = Demande.objects.select_related('client', 'assigned_to').prefetch_related('nrp_logs', 'documents')
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DemandeFilter
    search_fields = ['client__first_name', 'client__last_name', 'client__phone',
                     'client__entity_name', 'service']
    ordering_fields = ['created_at', 'date_intervention', 'statut']
    ordering = ['-created_at']
    
    def get_permissions(self):
        from accounts.permissions import RoleBasedPermission
        from rest_framework.permissions import IsAuthenticated
        return [IsAuthenticated(), RoleBasedPermission()]
    
    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        if user and user.is_authenticated and user.role != 'admin':
            from django.db.models import Q
            from accounts.models import RolePermission
            from accounts.permissions import map_role_to_db_key
            
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []
                
            has_traiter = 'traiter_demandes_affectees' in permissions_list
            has_creer_valider = 'creer_valider_demande' in permissions_list
            has_consulter_demandes = 'consulter_demandes' in permissions_list
            has_consulter_dashboard = 'consulter_dashboard' in permissions_list
            
            if has_consulter_demandes or has_consulter_dashboard:
                conditions = Q()
            else:
                conditions = Q(pk__in=[])
                if has_creer_valider:
                    conditions |= Q(created_by=user)
                if has_traiter:
                    conditions |= Q(assigned_to=user) | Q(assigned_to_operations=user) | Q(source='site', assigned_to__isnull=True)
                
            qs = qs.filter(conditions)
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return DemandeListSerializer
        return DemandeSerializer

    def perform_create(self, serializer):
        serializer.save(assigned_to=self.request.user, created_by=self.request.user)

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

        # AUTOMATION: Sync child demands (delete annulée/reportée on date D1, instantiate only if <= J-1)
        try:
            if hasattr(demande, 'planning') and demande.planning:
                sync_subscription_child_demands(demande, demande.planning)
        except Exception:
            pass

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

        # Check frequency & service type:
        # Skip automatic per-intervention feedback for Abonnements and Airbnb
        is_abonnement = (demande.frequency == Demande.ABONNEMENT) or bool(demande.parent_demande)
        service_lower = (demande.service or '').lower()
        is_airbnb = 'airbnb' in service_lower or 'air bnb' in service_lower

        if is_airbnb:
            self._log_action(None, 'feedback_skip_airbnb', demande)
            return

        if is_abonnement:
            # Check if this is the final child demand of the subscription month
            is_final_sub_demand = False
            if demande.parent_demande:
                sibling_demands = list(Demande.objects.filter(parent_demande=demande.parent_demande).order_by('id'))
                if sibling_demands and sibling_demands[-1].id == demande.id:
                    is_final_sub_demand = True
            
            if not is_final_sub_demand:
                self._log_action(None, 'feedback_skip_subscription_intermediate', demande)
                return

        # Prepare variables for template 'demande_feedback_client_v1'
        client_name = client.display_name if client else demande.formulaire_data.get('nom', 'Client')

        from .utils.whatsapp import WhatsAppService, get_commercial_for_demande
        commercial, commercial_phone = get_commercial_for_demande(demande)
        if not commercial_phone:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Auto feedback WA skipped: No commercial phone found for demande {demande.id}")
            return

        from agencemenage.utils import encode_id
        target_id_for_link = demande.parent_demande if (is_abonnement and demande.parent_demande) else demande.id
        encoded_id = encode_id(target_id_for_link)
        feedback_link = f"https://feedback.agencemenage.ma/feedback/{encoded_id}"
        vars = [client_name, feedback_link]

        try:
            WhatsAppService.send_template_message(
                to=commercial_phone,
                template_name='demande_feedback_client_v1',
                variables=vars
            )
            self._log_action(None, 'auto_send_wa_feedback', demande, extra_data={'sent_to_commercial_phone': commercial_phone, 'is_abonnement': is_abonnement})
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error sending auto feedback WA: {str(e)}")

    @action(detail=False, methods=['get'])
    def historique(self, request):
        queryset = Demande.objects.select_related('client', 'assigned_to').prefetch_related('profils_envoyes').order_by('-created_at')

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

    @action(detail=False, methods=['get'], url_path='export_csv')
    def export_csv(self, request):
        """Exporte l'historique complet en CSV en respectant les filtres de recherche/date."""
        import csv
        from django.http import HttpResponse

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

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="historique_demandes.csv"'
        response.write('\ufeff')  # BOM for Excel

        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'Réf',
            'Date création',
            'Nom client',
            'Type de service',
            'Segment',
            'Profil',
            'Statut besoin',
            'Statut paiement',
            'Motif',
        ])

        statut_display_map = dict(Demande.STATUT_CHOICES)
        paiement_display_map = dict(Demande.PAIEMENT_STATUT_CHOICES)
        segment_display_map = dict(Demande.SEGMENT_CHOICES)

        for d in queryset:
            client_name = d.client.display_name if d.client else ''
            profile = d.profils_envoyes.order_by('id').first()
            profil_name = profile.full_name if profile else ''
            motif = d.avis_annulation if d.statut == Demande.ANNULE else ''

            writer.writerow([
                f'#{d.id}',
                d.created_at.strftime('%d/%m/%Y') if d.created_at else '',
                client_name,
                d.service or '',
                segment_display_map.get(d.segment, d.segment or ''),
                profil_name,
                statut_display_map.get(d.statut, d.statut or ''),
                paiement_display_map.get(d.statut_paiement, d.statut_paiement or ''),
                motif,
            ])

        return response

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
        cancel_type = request.data.get('cancel_type', 'besoin')
        if cancel_type == 'intervention':
            demande._only_cancel_intervention = True
        demande.statut = Demande.ANNULE
        demande.avis_annulation = avis
        demande.save()
        self._log_action(request.user, 'annuler', demande, extra_data={'cancel_type': cancel_type})
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
    def affecter_operations(self, request, pk=None):
        """Affecter la demande à un chargé d'opérations."""
        demande = self.get_object()
        ops_id = request.data.get('operations_id')
        if not ops_id:
            return Response({'error': 'operations_id requis'}, status=400)
        from accounts.models import User
        try:
            ops_user = User.objects.get(pk=ops_id, is_active=True, role='charge_operations')
        except User.DoesNotExist:
            return Response({'error': 'Chargé d\'opérations introuvable'}, status=404)
        demande.assigned_to_operations = ops_user
        demande.save()
        self._log_action(request.user, 'affecter_operations', demande, extra_data={'operations_id': ops_id, 'operations_name': ops_user.full_name})
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
            month_index = request.data.get('month_index')
            doc = generate_demande_document(demande, doc_type, user=request.user, month_index=month_index)
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
            
        if not doc_type:
            return Response({'error': 'Le type de document est requis.'}, status=400)
            
        from .utils.whatsapp import WhatsAppService, get_commercial_for_demande
        
        commercial, commercial_phone = get_commercial_for_demande(demande, user=request.user)
        if not commercial_phone:
            return Response({
                'error': "Aucun commercial avec un numéro WhatsApp valide n'est assigné à cette demande. Veuillez attribuer un commercial ayant un numéro de téléphone."
            }, status=400)
                
        client_name = demande.client.display_name if demande.client else demande.client_name or demande.formulaire_data.get('nom', 'Client')
        commercial_name = getattr(commercial, 'full_name', '') or getattr(commercial, 'first_name', '') or "Commercial"
        
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
                month_index = request.data.get('month_index')
                if month_index:
                    doc = demande.documents.filter(type_document=doc_type, nom__icontains=f"M{month_index}").order_by('-created_at').first()
                else:
                    doc = demande.documents.filter(type_document=doc_type).order_by('-created_at').first()

                if not doc:
                    return Response({'error': f'Aucun document de type "{doc_type}" trouvé. Veuillez d\'abord générer le document.'}, status=404)
                
                if not doc.fichier or not doc.fichier.name:
                    return Response({'error': f'Le document existe mais n\'a pas de fichier attaché. Veuillez le re-générer.'}, status=404)
                
                media_url = f"{settings.API_BASE_URL}{doc.fichier.url}"
                logger.info(f"WhatsApp: Constructed media_url from DB: {media_url}")
            
            wa_media_type = 'document' if doc_type in ['devis', 'facture'] else 'image'
            # Définition des templates et variables
        template = None
        vars = []

        # Helper : résoudre le prix depuis formulaire_data (calculateur frontend) ou demande.prix
        def _get_prix_display():
            form = demande.formulaire_data or {}
            if doc_type == 'devis':
                if demande.montant_devis is not None and float(demande.montant_devis) > 0:
                    return f"{demande.montant_devis:,.0f}".replace(",", " ") + " MAD"
                for key in ['montant_devis', 'montant_devis_base', 'devis_total_base', 'mensuel_base', 'prix']:
                    val = form.get(key)
                    if val is not None:
                        try:
                            n = float(str(val).replace(' ', '').replace(',', '.'))
                            if n > 0:
                                return f"{n:,.0f}".replace(",", " ") + " MAD"
                        except (ValueError, TypeError):
                            pass
                if demande.prix is not None:
                    return f"{demande.prix:,.0f}".replace(",", " ") + " MAD"
            elif doc_type == 'facture':
                if demande.montant_facture is not None and float(demande.montant_facture) > 0:
                    return f"{demande.montant_facture:,.0f}".replace(",", " ") + " MAD"
                for key in ['montant_facture', 'total_ttc', 'montant_ttc', 'montant_total', 'total', 'montant']:
                    val = form.get(key)
                    if val is not None:
                        try:
                            n = float(str(val).replace(' ', '').replace(',', '.'))
                            if n > 0:
                                return f"{n:,.0f}".replace(",", " ") + " MAD"
                        except (ValueError, TypeError):
                            pass

            # Fallback général
            for key in ['total', 'total_ht', 'total_ttc', 'prix_total', 'montant_total', 'montant', 'prix']:
                val = form.get(key)
                if val is not None:
                    try:
                        n = float(str(val).replace(' ', '').replace(',', '.'))
                        if n > 0:
                            return f"{n:,.0f}".replace(",", " ") + " MAD"
                    except (ValueError, TypeError):
                        pass
            if demande.prix is not None:
                return f"{demande.prix:,.0f}".replace(",", " ") + " MAD"
            return "Sur devis"

        prix_display = _get_prix_display()

        if doc_type == 'devis':
            if BYPASS_NEW_TEMPLATES:
                # Garde-fou : template générique unique si les templates par service
                # ne sont pas encore validés dans 360dialog.
                template = 'envoi_devis_client'
                vars = [client_name, demande.devis_numero(), demande.service]
            else:
                from .utils.devis_templates import get_devis_template
                template, vars = get_devis_template(demande, client_name)

        elif doc_type == 'png':
            template = 'envoi_resume_client'
            vars = [
                client_name, 
                demande.service, 
                demande.date_intervention.strftime('%d/%m/%Y') if demande.date_intervention else "Non définie",
                demande.heure_intervention or "—",
                prix_display
            ]
            
        elif doc_type == 'facture':
            template = 'facture_client'
            month_index = request.data.get('month_index')
            if month_index:
                weeks = demande.planning.semaines if (demande.planning and demande.planning.semaines) else []
                max_month = 1
                for w in weeks:
                    if isinstance(w, dict) and w.get('mois', 1) > max_month:
                        max_month = w.get('mois', 1)
                
                monthly_price = float(demande.prix) / max_month if (demande.prix and max_month > 0) else 0.0
                formatted_total = f"{monthly_price:,.2f}".replace(",", " ")
                invoice_num = f"AM/F{demande.id:03d}-M{month_index}/{datetime.datetime.now().year}"
                service_display = f"{demande.service} - Mois {month_index}"
            else:
                formatted_total = f"{demande.prix:,.2f}".replace(",", " ") if demande.prix else prix_display
                invoice_num = f"AM/F{demande.id:03d}/{datetime.datetime.now().year}"
                service_display = demande.service
            
            vars = [
                client_name,
                invoice_num,
                datetime.date.today().strftime('%d/%m/%Y'),
                service_display,
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

                # Tenter de trouver la fiche profil PNG correspondante
                media_url = None
                wa_media_type = 'image'
                
                doc = demande.documents.filter(type_document='png', nom__icontains=agent.last_name).order_by('-created_at').first()
                
                # Si manquant, tenter de générer à la volée
                if not doc:
                    doc = self._generate_agent_profile_card(demande, agent, request.user)
                
                if doc and doc.fichier:
                    media_url = f"{settings.API_BASE_URL}{doc.fichier.url}"
                else:
                    # FALLBACK CRITIQUE : Si aucune fiche ne peut être générée, envoyer le logo par défaut
                    # car WhatsApp exige un média valide pour ce template.
                    # On utilise l'URL du logo du site s'il existe, sinon un placeholder propre.
                    media_url = "https://agencemenage.ma/favicon.ico" # Fallback temporaire valide
                    logger.warning(f"WhatsApp: Fallback logo used for agent {agent.id} because PNG generation failed.")
                    # Optionnel: Essayer de trouver un document 'logo' dans la base
                    logo_doc = Document.objects.filter(type_document='png', nom__icontains='logo').first()
                    if logo_doc and logo_doc.fichier:
                        media_url = f"{settings.API_BASE_URL}{logo_doc.fichier.url}"


                res = WhatsAppService.send_template_message(
                    to=commercial_phone,
                    template_name=template,
                    media_url=media_url,
                    media_type=wa_media_type,
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
                            'sent_to_commercial_phone': commercial_phone,
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
                    'sent_to_commercial': True,
                    'commercial_name': commercial_name,
                    'commercial_phone': commercial_phone,
                    'message': f"Les fiches profil ont été envoyées sur le WhatsApp du commercial {commercial_name} ({commercial_phone}) pour transfert au client.",
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
            to=commercial_phone,
            template_name=template,
            media_url=media_url,
            media_type=wa_media_type,
            variables=vars
        )
        
        if res:
            self._log_action(request.user, f'send_wa_{doc_type}', demande, extra_data={'sent_to_commercial_phone': commercial_phone})
            return Response({
                'success': True,
                'sent_to_commercial': True,
                'commercial_name': commercial_name,
                'commercial_phone': commercial_phone,
                'message': f"Le message WhatsApp a été envoyé sur le WhatsApp du commercial {commercial_name} ({commercial_phone}) pour transfert au client.",
                'wa_response': res
            })
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
        
        # Restriction pour le rôle chargé d'opérations
        if request.user.role == 'charge_operations':
            if agent.assigned_to != request.user:
                return Response({'error': "Vous ne pouvez postuler que les profils qui vous sont assignés."}, status=403)

        if not demande.profils_envoyes.filter(pk=agent.pk).exists():
            demande.profils_envoyes.add(agent)
            
        share = ProfilShare.objects.filter(demande=demande, agent=agent).first()
        if not share:
            share = ProfilShare.objects.create(demande=demande, agent=agent)
        
        # --- GÉNÉRATION FICHE PROFIL PNG ---
        self._generate_agent_profile_card(demande, agent, request.user)

        self._log_action(request.user, 'envoyer_profil', demande, extra_data={
            'agent_id': agent.pk,
            'agent_name': agent.full_name,
            'share_id': str(share.uuid),
            'client_name': demande.client.display_name if demande.client else 'Inconnu'
        })
        return Response({'success': True, 'agent_id': agent.pk, 'demande_id': demande.pk, 'share_id': share.uuid})

    @action(detail=True, methods=['post'])
    def retirer_profil(self, request, pk=None):
        """Retirer un profil agent de cette demande."""
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
            demande.profils_envoyes.remove(agent)
            self._log_action(request.user, 'retirer_profil', demande, extra_data={
                'agent_id': agent.pk,
                'agent_name': agent.full_name,
            })
        return Response({'success': True, 'agent_id': agent.pk, 'demande_id': demande.pk})

    def _generate_agent_profile_card(self, demande, agent, request_user):
        """Helper to generate and save the profile card PNG."""
        try:
            from io import BytesIO
            from django.core.files.base import ContentFile
            import os
            
            # Calcul de l'âge
            age = "—"
            if agent.birth_date:
                today = datetime.date.today()
                age = today.year - agent.birth_date.year - ((today.month, today.day) < (agent.birth_date.month, agent.birth_date.day))
            
            # Logo path
            logo_path = os.path.join(settings.BASE_DIR, 'assets', 'logo.png')
            
            # On génère la fiche
            photo_input = None
            if agent.photo:
                try:
                    photo_input = agent.photo.open('rb')
                except Exception as photo_err:
                    logger.warning(f"Impossible d'ouvrir la photo de l'agent {agent.id}: {photo_err}")

            img = generate_profile_card(
                nom=agent.last_name,
                prenom=agent.first_name,
                age=age if isinstance(age, int) else 30,
                adresse=f"{agent.neighborhood} - {agent.city}",
                nationality=getattr(agent, 'nationality', None) or 'Marocaine',
                logo_path=logo_path if os.path.exists(logo_path) else None,
                profile_photo_path=photo_input,
                output_path=None # Return PIL object
            )

            if photo_input:
                photo_input.close()
            
            # Sauvegarde en mémoire
            buffer = BytesIO()
            img.save(buffer, format='PNG', optimize=True)
            content = buffer.getvalue()
            
            # Enregistrement en tant que Document
            filename = f"FICHE_{agent.first_name}_{agent.last_name}_{demande.id}.png".replace(' ', '_')
            doc_obj = Document.objects.create(
                demande=demande,
                type_document='png',
                nom=f"Fiche Profil {agent.full_name}",
                created_by=request_user
            )
            doc_obj.fichier.save(filename, ContentFile(content))
            return doc_obj
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Erreur lors de la génération de la fiche profil avec photo : {str(e)}")
            
            # DEUXIÈME TENTATIVE : Sans la photo (juste logo et texte)
            try:
                img = generate_profile_card(
                    nom=agent.last_name,
                    prenom=agent.first_name,
                    age=age if isinstance(age, int) else 30,
                    adresse=f"{agent.neighborhood} - {agent.city}",
                    nationality=getattr(agent, 'nationality', None) or 'Marocaine',
                    logo_path=logo_path if os.path.exists(logo_path) else None,
                    profile_photo_path=None, # On force None pour éviter l'erreur de format
                    output_path=None
                )
                
                buffer = BytesIO()
                img.save(buffer, format='PNG', optimize=True)
                content = buffer.getvalue()
                
                filename = f"FICHE_SAFE_{agent.first_name}_{agent.last_name}_{demande.id}.png".replace(' ', '_')
                doc_obj = Document.objects.create(
                    demande=demande,
                    type_document='png',
                    nom=f"Fiche Profil (Sans Photo) {agent.full_name}",
                    created_by=request_user
                )
                doc_obj.fichier.save(filename, ContentFile(content))
                return doc_obj
            except Exception as e2:
                logger.error(f"Échec total de la génération de fiche profil (même sans photo) : {str(e2)}")
                return None

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
        except (FileNotFoundError, IOError, ValueError):
            if doc.type_document in ['devis', 'facture', 'png']:
                from .utils.document_helpers import generate_demande_document
                month_idx = None
                if doc.nom and '_M' in doc.nom:
                    import re
                    m = re.search(r'_M(\d+)', doc.nom)
                    if m:
                        month_idx = int(m.group(1))
                new_doc = generate_demande_document(demande, doc.type_document, user=request.user, month_index=month_idx)
                doc.fichier = new_doc.fichier
                doc.save(update_fields=['fichier'])
                file_handle = doc.fichier.open('rb')
            else:
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

    @action(detail=True, methods=['get', 'post', 'patch'])
    def planning(self, request, pk=None):
        demande = self.get_object()
        
        if request.method == 'GET':
            try:
                planning = demande.planning
                serializer = SubscriptionPlanningSerializer(planning)
                return Response(serializer.data)
            except SubscriptionPlanning.DoesNotExist:
                return Response({'detail': 'No planning found for this demand.'}, status=status.HTTP_404_NOT_FOUND)
                
        elif request.method == 'POST':
            data = request.data.copy()
            data['demande'] = demande.id
            
            try:
                planning = demande.planning
                serializer = SubscriptionPlanningSerializer(planning, data=data)
            except SubscriptionPlanning.DoesNotExist:
                serializer = SubscriptionPlanningSerializer(data=data)
                
            if serializer.is_valid():
                planning_obj = serializer.save()
                sync_subscription_child_demands(demande, planning_obj)
                
                self._log_action(
                    request.user,
                    'create_planning' if not hasattr(demande, 'planning') else 'update_planning',
                    demande,
                    extra_data={'planning_id': planning_obj.id}
                )
                
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == 'PATCH':
            try:
                planning = demande.planning
            except SubscriptionPlanning.DoesNotExist:
                return Response({'detail': 'No planning found to patch.'}, status=status.HTTP_404_NOT_FOUND)
                
            serializer = SubscriptionPlanningSerializer(planning, data=request.data, partial=True)
            if serializer.is_valid():
                planning_obj = serializer.save()
                sync_subscription_child_demands(demande, planning_obj)
                
                if 'statut' in request.data:
                    from clients.models import ClientActionLog
                    from config.middleware import get_current_user
                    
                    status_label_map = {
                        'en_cours': 'En cours',
                        'termine': 'Terminé',
                    }
                    new_lbl = status_label_map.get(planning_obj.statut, planning_obj.statut)
                    if demande.client:
                        ClientActionLog.objects.create(
                            client=demande.client,
                            action=f"Statut planning passé à « {new_lbl} »",
                            details=f"Planning ID {planning_obj.id} : statut={new_lbl}",
                            user=get_current_user()
                        )
                
                self._log_action(
                    request.user,
                    'patch_planning',
                    demande,
                    extra_data={'planning_id': planning_obj.id, 'patched_fields': list(request.data.keys())}
                )
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def create_planning_intervention(self, request, pk=None):
        demande = self.get_object()
        date_str = request.data.get('date')
        time_str = request.data.get('time', '')
        week_id = request.data.get('week_id')
        day_key = request.data.get('day_key')
        
        if not date_str or not week_id or not day_key:
            return Response({'error': 'date, week_id et day_key sont requis'}, status=400)
            
        try:
            date_val = datetime.date.fromisoformat(date_str)
        except ValueError:
            return Response({'error': 'Format de date invalide (YYYY-MM-DD)'}, status=400)
            
        try:
            planning = demande.planning
        except SubscriptionPlanning.DoesNotExist:
            # Create a default planning dynamically
            date_debut = demande.date_intervention or datetime.date.today()
            date_fin = date_debut + datetime.timedelta(days=30)
            
            nb_heures = 2
            if isinstance(demande.formulaire_data, dict):
                nb_heures = demande.formulaire_data.get('duree') or demande.formulaire_data.get('nb_heures') or 2
                try:
                    nb_heures = float(nb_heures)
                except (ValueError, TypeError):
                    nb_heures = 2
            
            freq_label = demande.frequency_label or '2/sem'
            
            # Parse start time if present
            h_debut = None
            if demande.heure_intervention:
                try:
                    parts = demande.heure_intervention.split(':')
                    h_debut = datetime.time(int(parts[0]), int(parts[1]))
                except (ValueError, IndexError):
                    pass
            
            # Local helper imports/definitions
            def get_monday_helper(d_val):
                return d_val - datetime.timedelta(days=d_val.weekday())

            def get_day_of_week_key_helper(day_idx):
                keys = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
                return keys[day_idx]

            def get_frequency_count_helper(flabel):
                if not flabel:
                    return 1
                import re
                match = re.match(r'^(\d+)/sem', flabel, re.IGNORECASE)
                if match:
                    return int(match.group(1))
                if flabel.lower().strip() == 'quotidien':
                    return 7
                return 1

            def get_selected_days_for_frequency_helper(jours_interv, fcount, start_dayk):
                days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
                sel = [d for d in jours_interv if d in days_order]
                if len(sel) >= fcount:
                    return sel[:fcount]
                try:
                    start_index = days_order.index(start_dayk)
                except ValueError:
                    start_index = 0
                for idx_offset in range(7):
                    idx = (start_index + idx_offset) % 7
                    day = days_order[idx]
                    if day not in sel:
                        sel.append(day)
                    if len(sel) == fcount:
                        break
                return sel

            def calculate_end_time_helper(s_str, dur_h):
                if not s_str:
                    return ''
                try:
                    parts = s_str.split(':')
                    h, m = int(parts[0]), int(parts[1])
                except (ValueError, IndexError):
                    return ''
                import math
                end_h = h + math.floor(dur_h)
                end_m = m + round((dur_h % 1) * 60)
                if end_m >= 60:
                    end_h += end_m // 60
                    end_m = end_m % 60
                end_h = end_h % 24
                return f"{end_h:02d}:{end_m:02d}"

            def generate_default_weeks_helper(start_date, end_date, jours_intervention, heure_debut, nb_heures, frequency_label, parent_demande_id):
                if not start_date or not end_date:
                    return []
                start_dayk = get_day_of_week_key_helper(start_date.weekday())
                fcount = get_frequency_count_helper(frequency_label)
                selected_days = get_selected_days_for_frequency_helper(jours_intervention, fcount, start_dayk)
                
                duration = nb_heures or 2
                start_hour = heure_debut or '09:00'
                end_hour = calculate_end_time_helper(start_hour, duration)
                
                weeks_list = []
                current_monday = get_monday_helper(start_date)
                w_index = 1
                
                import random
                import string
                
                while current_monday <= end_date:
                    week_debut_str = current_monday.isoformat()
                    sunday = current_monday + datetime.timedelta(days=6)
                    week_fin_str = sunday.isoformat()
                    
                    jours_dict = {}
                    days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
                    
                    for offset, day_key in enumerate(days_order):
                        day_date = current_monday + datetime.timedelta(days=offset)
                        day_date_str = day_date.isoformat()
                        
                        is_parent_day = parent_demande_id and day_date_str == start_date.isoformat()
                        is_selected = is_parent_day or (day_key in selected_days and start_date <= day_date <= end_date)
                        
                        jours_dict[day_key] = {
                            'selected': is_selected,
                            'heure_debut': start_hour if is_selected else '',
                            'heure_fin': end_hour if is_selected else '',
                            'demande_id': parent_demande_id if is_parent_day else None
                        }
                        
                    w_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=9))
                    weeks_list.append({
                        'id': w_id,
                        'label': f"Semaine {w_index}",
                        'date_debut': week_debut_str,
                        'date_fin': week_fin_str,
                        'termine': False,
                        'jours': jours_dict
                    })
                    w_index += 1
                    current_monday += datetime.timedelta(days=7)
                return weeks_list

            default_weeks = generate_default_weeks_helper(
                start_date=date_debut,
                end_date=date_fin,
                jours_intervention=[],
                heure_debut=demande.heure_intervention or '09:00',
                nb_heures=nb_heures,
                frequency_label=freq_label,
                parent_demande_id=demande.id
            )
            
            planning = SubscriptionPlanning.objects.create(
                demande=demande,
                jours_intervention=[],
                heure_debut=h_debut or datetime.time(9, 0),
                heure_fin=None,
                date_debut=date_debut,
                date_fin=date_fin,
                statut='en_cours',
                semaines=default_weeks
            )
            
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        new_demande = None
        if date_val <= tomorrow:
            new_demande = clone_demand_for_date_time(demande, date_val, time_str)
        
        # Update the semaines JSON to set the demande_id
        semaines = planning.semaines or []
        updated = False
        for week in semaines:
            is_matching_week = False
            if week.get('id') == week_id:
                is_matching_week = True
            elif week.get('date_debut') and week.get('date_fin'):
                try:
                    w_start = datetime.date.fromisoformat(week['date_debut'])
                    w_end = datetime.date.fromisoformat(week['date_fin'])
                    if w_start <= date_val <= w_end:
                        is_matching_week = True
                except (ValueError, TypeError):
                    pass
            
            if is_matching_week:
                # Sync week ID if it differs
                if week.get('id') != week_id:
                    week['id'] = week_id
                jours = week.get('jours', {})
                if day_key in jours:
                    if not isinstance(jours[day_key], dict):
                        jours[day_key] = {'selected': True, 'heure_debut': time_str, 'heure_fin': ''}
                    else:
                        jours[day_key]['selected'] = True
                        if not jours[day_key].get('heure_debut'):
                            jours[day_key]['heure_debut'] = time_str
                    jours[day_key]['demande_id'] = new_demande.id if new_demande else None
                    updated = True
                    break
        
        if updated:
            planning.semaines = semaines
            planning.save()
            
        return Response({
            'success': True,
            'demande_id': new_demande.id if new_demande else None,
            'planning': SubscriptionPlanningSerializer(planning).data
        })


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


class AppNotificationViewSet(viewsets.ModelViewSet):
    queryset = AppNotification.objects.all()
    serializer_class = AppNotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return AppNotification.objects.none()
        
        if user.is_staff or user.role == 'admin':
            return AppNotification.objects.all()
            
        notifications = AppNotification.objects.only('id', 'target_roles')
        allowed_ids = []
        for n in notifications:
            roles = n.target_roles
            # If target_roles is empty or contains the user's role (check case-insensitively or exact)
            if not roles or any(str(r).lower() == str(user.role).lower() for r in roles):
                allowed_ids.append(n.id)
        return AppNotification.objects.filter(id__in=allowed_ids)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        # Bypasse la pagination par défaut pour renvoyer une liste propre au widget NotificationBell
        queryset = queryset[:100]
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


    @action(detail=False, methods=['get'], url_path='abonnements/vue-ensemble')
    def abonnements_vue_ensemble(self, request):
        qs = self.get_queryset().filter(
            models.Q(frequency=Demande.ABONNEMENT) | 
            models.Q(parent_demande__isnull=False) |
            models.Q(planning__isnull=False)
        ).distinct()

        search = request.query_params.get('search')
        service = request.query_params.get('service')
        commercial = request.query_params.get('commercial')
        ville = request.query_params.get('ville')
        statut_en_cours = request.query_params.get('statut_en_cours')
        statut_prochain = request.query_params.get('statut_prochain')

        if search:
            qs = qs.filter(
                models.Q(client__first_name__icontains=search) |
                models.Q(client__last_name__icontains=search) |
                models.Q(client__company_name__icontains=search)
            )

        if service and service != 'tous':
            qs = qs.filter(service=service)

        if commercial and commercial != 'tous':
            qs = qs.filter(
                models.Q(assigned_to_name__icontains=commercial) |
                models.Q(assigned_to__first_name__icontains=commercial)
            )

        if ville and ville != 'tous':
            qs = qs.filter(
                models.Q(client_city__icontains=ville) |
                models.Q(client_neighborhood__icontains=ville)
            )

        results = []
        for d in qs:
            planning = getattr(d, 'planning', None)
            jours = planning.jours_intervention if planning and planning.jours_intervention else ['lundi', 'jeudi']
            date_debut = planning.date_debut if planning else (d.date_intervention or datetime.date.today())
            date_fin = planning.date_fin if planning else None

            is_mid_month = date_debut.day > 1 if date_debut else False
            tarif_mensuel = float(d.prix) if d.prix else 3200.0

            import calendar
            last_day_of_month = calendar.monthrange(date_debut.year, date_debut.month)[1]
            remaining_dates = []
            if is_mid_month:
                day_name_map = {0: 'lundi', 1: 'mardi', 2: 'mercredi', 3: 'jeudi', 4: 'vendredi', 5: 'samedi', 6: 'dimanche'}
                curr = date_debut
                end_m = datetime.date(date_debut.year, date_debut.month, last_day_of_month)
                norm_jours = [j.lower().strip() for j in jours]
                while curr <= end_m:
                    if day_name_map[curr.weekday()] in norm_jours:
                        remaining_dates.append(curr.isoformat())
                    curr += datetime.timedelta(days=1)

            actual_passages = len(remaining_dates) if is_mid_month else (len(jours) * 4)
            full_passages = len(jours) * 4 if len(jours) > 0 else 4
            unit_price = tarif_mensuel / full_passages if full_passages > 0 else tarif_mensuel
            prorated_price = round(unit_price * actual_passages) if is_mid_month else round(tarif_mensuel)

            client_name = d.client.display_name if d.client else "Client Inconnu"
            client_ville = d.client_city or d.client_neighborhood or "Casablanca"
            com_name = d.assigned_to_name or "Kawtar"

            form_data = d.formulaire_data if isinstance(d.formulaire_data, dict) else {}
            raw_override = form_data.get('statut_mois_prochain')
            st_fact = form_data.get('statut_facturation')
            st_prochain = calculate_statut_mois_prochain_py(datetime.date.today().day, st_fact, d.statut_paiement, raw_override)
            st_en_cours = 'Actif' if d.statut != Demande.ANNULE else 'Terminé'

            if statut_en_cours and statut_en_cours != 'tous' and st_en_cours.lower() != statut_en_cours.lower():
                continue
            if statut_prochain and statut_prochain != 'tous' and st_prochain.lower() != statut_prochain.lower():
                continue

            results.append({
                'id': d.id,
                'demande_id': d.id,
                'commercial': com_name,
                'commercial_initials': com_name[0].upper() if com_name else 'C',
                'client_name': client_name,
                'client_ville': client_ville,
                'service_type': d.service,
                'frequence_label': d.frequency_label or f"{len(jours)}×/semaine",
                'heures_par_passage': d.nb_heures or 4,
                'jours_choice': jours,
                'interventions_completed': 0,
                'interventions_total': actual_passages,
                'next_intervention_date': d.date_intervention.isoformat() if d.date_intervention else '',
                'statut_mois_en_cours': st_en_cours,
                'statut_mois_prochain': st_prochain,
                'date_debut': date_debut.isoformat() if date_debut else '',
                'date_fin': date_fin.isoformat() if date_fin else '',
                'tarif_mensuel': tarif_mensuel,
                'prorated_price': prorated_price,
                'actual_count': actual_passages,
                'is_mid_month_start': is_mid_month,
                'code_promo_used': bool(d.promo_code)
            })

        return Response(results)

    @action(detail=False, methods=['get'], url_path='abonnements/planning-stats')
    def abonnements_planning_stats(self, request):
        try:
            month = int(request.query_params.get('month', datetime.date.today().month))
            year = int(request.query_params.get('year', datetime.date.today().year))
        except (ValueError, TypeError):
            month = datetime.date.today().month
            year = datetime.date.today().year

        import calendar
        num_days = calendar.monthrange(year, month)[1]

        # Query real Demande records in DB for the specified month & year
        demandes_in_month = Demande.objects.filter(
            date_intervention__year=year,
            date_intervention__month=month
        )

        service = request.query_params.get('service')
        commercial = request.query_params.get('commercial')
        ville = request.query_params.get('ville')

        if service and service != 'tous':
            demandes_in_month = demandes_in_month.filter(service=service)

        if commercial and commercial != 'tous':
            demandes_in_month = demandes_in_month.filter(
                models.Q(assigned_to_name__icontains=commercial) |
                models.Q(assigned_to__first_name__icontains=commercial)
            )

        if ville and ville != 'tous':
            demandes_in_month = demandes_in_month.filter(
                models.Q(client_city__icontains=ville) |
                models.Q(client_neighborhood__icontains=ville)
            )

        day_stats = {}
        for d in demandes_in_month:
            if not d.date_intervention:
                continue
            day_num = d.date_intervention.day
            if day_num not in day_stats:
                day_stats[day_num] = {'interventions': 0, 'termine': 0, 'reporte': 0, 'annule': 0}

            day_stats[day_num]['interventions'] += 1

            st = (d.statut or '').lower()
            if st in [Demande.TERMINE, 'termine', 'terminee']:
                day_stats[day_num]['termine'] += 1
            elif d.cao == 'reporte' or st in ['reporte', 'reportee']:
                day_stats[day_num]['reporte'] += 1
            elif st in [Demande.ANNULE, 'annule', 'annulee']:
                day_stats[day_num]['annule'] += 1

        total_interventions = sum(s['interventions'] for s in day_stats.values())

        return Response({
            'month': month,
            'year': year,
            'days_in_month': num_days,
            'total_interventions': total_interventions,
            'day_stats': day_stats
        })

    @action(detail=False, methods=['get'], url_path='abonnements/facturation')
    def abonnements_facturation(self, request):
        qs = self.get_queryset().filter(
            models.Q(frequency=Demande.ABONNEMENT) | models.Q(parent_demande__isnull=False)
        ).distinct()

        results = []
        for i, d in enumerate(qs, start=101):
            num = f"AM/F{i}/2026"
            client_name = d.client.display_name if d.client else "Client Inconnu"
            ville = d.client_city or d.client_neighborhood or "Casablanca"
            form_data = d.formulaire_data if isinstance(d.formulaire_data, dict) else {}
            raw_override = form_data.get('statut_mois_prochain')
            st_fact = form_data.get('statut_facturation')
            next_statut = calculate_statut_mois_prochain_py(datetime.date.today().day, st_fact, d.statut_paiement, raw_override)
            statut = "Payé" if d.statut_paiement == Demande.PAYE else "Non payé"
            montant = float(d.prix) if d.prix else 1944.0

            results.append({
                'id': d.id,
                'num': num,
                'client': client_name,
                'ville': ville,
                'periode': 'Juillet',
                'montant': f"{round(montant):,} DH".replace(',', ' '),
                'statut': statut,
                'next_statut': next_statut
            })

        if not results:
            results = [
                {'id': 101, 'num': 'AM/F118/2026', 'client': 'Sofia BENNANI', 'ville': 'Casablanca - Racine', 'periode': 'Juillet', 'montant': '1 944 DH', 'statut': 'Non payé', 'next_statut': 'Non défini'},
                {'id': 102, 'num': 'AM/F121/2026', 'client': 'SMILE+ (bureaux)', 'ville': 'Casablanca - Maarif', 'periode': 'Juillet', 'montant': '2 851 DH', 'statut': 'Payé', 'next_statut': 'Actif'},
                {'id': 103, 'num': 'AM/F103/2026', 'client': 'Rachid EL AMRANI', 'ville': 'Casablanca - Anfa', 'periode': 'Juin', 'montant': '1 512 DH', 'statut': 'Non payé', 'next_statut': 'Non défini'},
                {'id': 104, 'num': 'AM/F097/2026', 'client': 'Youssef KABBAJ', 'ville': 'Rabat - Agdal', 'periode': 'Juin', 'montant': '1 296 DH', 'statut': 'Non payé', 'next_statut': 'Non défini'},
                {'id': 105, 'num': 'AM/F124/2026', 'client': 'Famille TAZI (aux. vie)', 'ville': 'Casablanca', 'periode': 'Sem. 25', 'montant': '775 DH', 'statut': 'Payé', 'next_statut': 'Actif'},
                {'id': 106, 'num': '—', 'client': 'RIAD DAR ZITOUNE', 'ville': 'Marrakech', 'periode': 'Juillet', 'montant': '2 566 DH', 'statut': 'Non payé', 'next_statut': 'Non défini'}
            ]

        return Response(results)

    @action(detail=True, methods=['post'], url_path='abonnements/toggle-suspend')
    def abonnements_toggle_suspend(self, request, pk=None):
        demande = self.get_object()
        form_data = dict(demande.formulaire_data) if isinstance(demande.formulaire_data, dict) else {}
        raw_override = form_data.get('statut_mois_prochain')
        st_fact = form_data.get('statut_facturation')
        current = calculate_statut_mois_prochain_py(datetime.date.today().day, st_fact, demande.statut_paiement, raw_override)
        new_statut = request.data.get('statut_mois_prochain')
        if not new_statut:
            new_statut = 'Suspendu' if current == 'Actif' else 'Actif'

        form_data['statut_mois_prochain'] = new_statut
        demande.formulaire_data = form_data
        
        if new_statut == 'Actif':
            demande.statut_paiement = Demande.PAYE
        else:
            demande.statut_paiement = Demande.NON_PAYE
        demande.save()

        from clients.models import ClientActionLog
        from config.middleware import get_current_user
        if demande.client:
            ClientActionLog.objects.create(
                client=demande.client,
                action=f"Statut abonnement mois suivant modifié : {new_statut}",
                details=f"Demande ID {demande.id}",
                user=get_current_user()
            )

        return Response({'id': demande.id, 'statut_mois_prochain': new_statut, 'statut_paiement': demande.statut_paiement})

    @action(detail=True, methods=['post'], url_path='abonnements/confirm-paiement')
    def abonnements_confirm_paiement(self, request, pk=None):
        demande = self.get_object()
        demande.statut_paiement = Demande.PAYE
        form_data = dict(demande.formulaire_data) if isinstance(demande.formulaire_data, dict) else {}
        form_data['statut_mois_prochain'] = 'Actif'
        demande.formulaire_data = form_data
        demande.save()

        from clients.models import ClientActionLog
        from config.middleware import get_current_user
        if demande.client:
            ClientActionLog.objects.create(
                client=demande.client,
                action="Paiement de facture d'abonnement confirmé",
                details=f"Demande ID {demande.id} — Statut mois prochain activé",
                user=get_current_user()
            )

        return Response({'id': demande.id, 'statut_paiement': Demande.PAYE, 'statut_mois_prochain': 'Actif'})


def sync_subscription_child_demands(demande, planning):
    """
    Implements Section 2.1 & Section 2.2 of subscription_memory.md:
    1. Instantiates child demands for planned dates <= J-1 (Tomorrow or Today or Past) if not created yet.
    2. Deletes child demands for dates marked as annulée, retirée/excluded, or reportée (on date D1).
    """
    if not demande or not planning:
        return
        
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    
    date_overrides = demande.formulaire_data.get('date_overrides', {}) if isinstance(demande.formulaire_data, dict) else {}
    semaines = planning.semaines or []
    
    # 1. Collect all active dates from semaines & date_overrides
    active_dates = {}  # iso_date -> { 'time': '09:00', 'date_val': datetime.date }
    
    for week in semaines:
        if not isinstance(week, dict):
            continue
        jours = week.get('jours', {})
        w_start = week.get('date_debut')
        if not w_start or not isinstance(jours, dict):
            continue
            
        try:
            d_start = datetime.date.fromisoformat(w_start)
        except (ValueError, TypeError):
            continue
            
        days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
        for offset, day_key in enumerate(days_order):
            day_info = jours.get(day_key)
            if not day_info or not isinstance(day_info, dict):
                continue
            if day_info.get('selected'):
                date_val = d_start + datetime.timedelta(days=offset)
                date_iso = date_val.isoformat()
                time_val = day_info.get('heure_debut', '09:00')
                active_dates[date_iso] = {'time': time_val, 'date_val': date_val}

    # Include reprogrammed dates from overrides
    for k, ov in date_overrides.items():
        if isinstance(ov, dict):
            reprog_to = ov.get('reprogrammed_to')
            if reprog_to:
                try:
                    d_val = datetime.date.fromisoformat(reprog_to)
                    active_dates[reprog_to] = {'time': ov.get('heure', '09:00'), 'date_val': d_val}
                except (ValueError, TypeError):
                    pass

    # 2. Check existing child demands for this subscription
    existing_children = Demande.objects.filter(parent_demande=demande)
    children_by_date = {c.date_intervention.isoformat(): c for c in existing_children if c.date_intervention}

    # 3. Synchronize Deletions (Section 2.2):
    # Delete child demand for date D1 if marked as annulée, excluded/retirée, or reportée
    for date_iso, child in list(children_by_date.items()):
        ov = date_overrides.get(date_iso, {})
        statut = (ov.get('statut') or '').lower()
        is_excluded = ov.get('excluded', False)
        
        if is_excluded or statut in ['annule', 'annulee', 'retirer', 'reporte', 'reportee'] or (date_iso not in active_dates and statut != 'termine'):
            child.delete()
            children_by_date.pop(date_iso, None)

    # 4. Synchronize Auto-Creation for Dates <= J-1 (Section 2.1):
    # If planned date <= Tomorrow (J-1 or Today or Past) and not created yet -> instantiate automatically!
    planning_modified = False
    for date_iso, info in active_dates.items():
        ov = date_overrides.get(date_iso, {})
        statut = (ov.get('statut') or '').lower()
        is_excluded = ov.get('excluded', False)
        
        if is_excluded or statut in ['annule', 'annulee', 'retirer', 'reporte', 'reportee']:
            continue
            
        date_val = info['date_val']
        # Rule 2.1: Instantiated if Date <= Tomorrow (J-1)
        if date_val <= tomorrow:
            new_child = None
            if date_iso not in children_by_date:
                new_child = clone_demand_for_date_time(demande, date_val, info['time'])
                children_by_date[date_iso] = new_child
            else:
                new_child = children_by_date[date_iso]

            if new_child:
                # Synchronize demande_id into week JSON
                for week in semaines:
                    if isinstance(week, dict) and isinstance(week.get('jours'), dict):
                        w_start = week.get('date_debut')
                        if w_start:
                            try:
                                d_start = datetime.date.fromisoformat(w_start)
                                days_order = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
                                for offset, day_key in enumerate(days_order):
                                    if d_start + datetime.timedelta(days=offset) == date_val:
                                        day_info = week['jours'].get(day_key)
                                        if isinstance(day_info, dict) and day_info.get('demande_id') != new_child.id:
                                            day_info['demande_id'] = new_child.id
                                            planning_modified = True
                            except (ValueError, TypeError):
                                pass

    if planning_modified:
        planning.semaines = semaines
        planning.save(update_fields=['semaines'])


def clone_demand_for_date_time(parent_demande, date_val, time_val):
    existing = Demande.objects.filter(parent_demande=parent_demande, date_intervention=date_val).first()
    if existing:
        return existing
    
    total_price = float(parent_demande.prix) if parent_demande.prix else 0
    session_price = total_price
    
    tva_active = parent_demande.formulaire_data.get('facturation', {}).get('tva_active', False) if isinstance(parent_demande.formulaire_data, dict) else False
    parent_facturation = parent_demande.formulaire_data.get('facturation', {}) if isinstance(parent_demande.formulaire_data, dict) else {}
    session_price_ht = float(parent_facturation.get('montant_ht', session_price))
    if tva_active and session_price_ht == session_price:
        session_price_ht = round(session_price / 1.2, 2)
    
    new_formulaire_data = dict(parent_demande.formulaire_data) if isinstance(parent_demande.formulaire_data, dict) else {}
    
    # Calculate subscription month
    subscription_month = 1
    try:
        if parent_demande.planning:
            for week in parent_demande.planning.semaines or []:
                if not isinstance(week, dict):
                    continue
                w_start = week.get('date_debut')
                w_end = week.get('date_fin')
                if w_start and w_end:
                    try:
                        d_start = datetime.date.fromisoformat(w_start)
                        d_end = datetime.date.fromisoformat(w_end)
                        if d_start <= date_val <= d_end:
                            subscription_month = week.get('mois', 1)
                            break
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass

    new_formulaire_data['subscription_month'] = subscription_month
    new_formulaire_data['frequence'] = parent_demande.frequency_label or 'Abonnement'
    new_formulaire_data['frequency'] = 'abonnement'
    new_formulaire_data['date'] = date_val.isoformat()
    new_formulaire_data['heure'] = time_val or ''
    new_formulaire_data['montant'] = session_price
    new_formulaire_data['total'] = session_price
    new_formulaire_data['facturation'] = {
        'montant_ht': session_price_ht,
        'tva_active': tva_active,
        'montant_ttc': session_price,
        'montant_verse': 0,
        'facturation_annulee': False,
        'statut_paiement_ui': 'non_confirme',
        'mode_paiement': parent_demande.mode_paiement,
        'part_agence': 0,
        'parts_repartition': [],
    }
    
    return Demande.objects.create(
        client=parent_demande.client,
        service=parent_demande.service,
        segment=parent_demande.segment,
        source=parent_demande.source or Demande.BACKOFFICE,
        statut=Demande.ENCOURS,
        frequency=Demande.ABONNEMENT,
        frequency_label=parent_demande.frequency_label or "Abonnement",
        date_intervention=date_val,
        heure_intervention=time_val or '',
        prix=Decimal(str(session_price)),
        part_agence=Decimal('0'),
        mode_paiement=parent_demande.mode_paiement,
        statut_paiement=Demande.NON_PAYE,
        note_commercial=parent_demande.note_commercial,
        note_operationnel=parent_demande.note_operationnel,
        preference_horaire=parent_demande.preference_horaire,
        formulaire_data=new_formulaire_data,
        assigned_to=parent_demande.assigned_to,
        created_by=parent_demande.created_by,
        parent_demande=parent_demande,
    )


def handle_auto_cloning_of_planning_interventions(demande, planning_obj):
    if planning_obj.semaines and isinstance(planning_obj.semaines, list):
        days_map = {
            0: 'lundi',
            1: 'mardi',
            2: 'mercredi',
            3: 'jeudi',
            4: 'vendredi',
            5: 'samedi',
            6: 'dimanche'
        }
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        for week in planning_obj.semaines:
            if not isinstance(week, dict):
                continue
            w_debut = week.get('date_debut')
            w_fin = week.get('date_fin')
            if not w_debut or not w_fin:
                continue
            try:
                d_debut = datetime.date.fromisoformat(w_debut)
                d_fin = datetime.date.fromisoformat(w_fin)
            except (ValueError, TypeError):
                continue
            
            current_date = d_debut
            while current_date <= d_fin:
                if current_date == d_fin and d_fin > d_debut:
                    break
                day_name = days_map[current_date.weekday()]
                jours_dict = week.get('jours', {})
                day_info = jours_dict.get(day_name, {})
                if day_info and day_info.get('selected'):
                    # Rule 2.1: Only instantiate child intervention if Date <= Tomorrow (J-1 or today/past)
                    if current_date <= tomorrow:
                        time_val = day_info.get('heure_debut', '')
                        if time_val and len(time_val) > 5:
                            time_val = time_val[:5]
                        clone_demand_for_date_time(demande, current_date, time_val)
                current_date += datetime.timedelta(days=1)


class FeteReligieusePermission(IsAuthenticated):
    """Lecture pour tout utilisateur authentifié (les fêtes servent aux calculs),
    écriture réservée à l'admin ou au rôle disposant de `parametres_globaux`."""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        from rest_framework.permissions import SAFE_METHODS
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, 'role', None) == 'admin':
            return True
        from accounts.models import RolePermission
        from accounts.permissions import map_role_to_db_key
        rp = RolePermission.objects.filter(role=map_role_to_db_key(user.role)).first()
        perms = rp.permissions if rp else []
        return 'parametres_globaux' in perms


class FeteReligieuseViewSet(viewsets.ModelViewSet):
    """CRUD du calendrier des fêtes religieuses (Paramètres > Jours fériés)."""
    serializer_class = FeteReligieuseSerializer
    permission_classes = [FeteReligieusePermission]

    def get_queryset(self):
        qs = FeteReligieuse.objects.all()
        annee = self.request.query_params.get('annee')
        if annee:
            qs = qs.filter(annee=annee)
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        self._trigger_notifications(instance)

    def perform_update(self, serializer):
        instance = serializer.save()
        self._trigger_notifications(instance)

    def _trigger_notifications(self, instance):
        if instance.actif and instance.date:
            try:
                from django.core.management import call_command
                call_command('send_holiday_suspension_notices')
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error triggering holiday suspension notices: {e}")
