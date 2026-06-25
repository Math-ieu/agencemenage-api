from rest_framework import serializers
from .models import Demande, NRPLog, Document, AuditLog, ProfilShare, SubscriptionPlanning, AppNotification, FeteReligieuse
from django.conf import settings
from .utils.whatsapp import WhatsAppService
from .utils.document_helpers import generate_demande_document
from .constants import get_segment_from_service
from clients.serializers import ClientListSerializer
from accounts.serializers import UserSerializer
from agents.serializers import AgentListSerializer


class CAOField(serializers.Field):
    def to_representation(self, value):
        if value in [True, 'True', 'oui']:
            return True
        if value in [False, 'False', 'non']:
            return False
        return value

    def to_internal_value(self, data):
        if data is True or data == 'true' or data == True:
            return 'oui'
        if data is False or data == 'false' or data == False:
            return 'non'
        return data


class DocumentSerializer(serializers.ModelSerializer):
    # URL sécurisée qui n'expose JAMAIS le chemin réel du fichier
    download_url = serializers.SerializerMethodField()
    # URL publique accessible sans auth (pour WhatsApp, partage externe)
    public_media_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ['id', 'demande', 'type_document', 'fichier', 'nom', 'created_at', 'created_by', 'download_url', 'public_media_url']
        read_only_fields = ['created_at', 'created_by', 'download_url', 'public_media_url']

    def get_download_url(self, obj):
        """Retourne l'URL de téléchargement sécurisé sans exposer le chemin physique."""
        if not obj.fichier:
            return None
        return f'/api/demandes/{obj.demande_id}/download/{obj.id}/'

    def get_public_media_url(self, obj):
        """Retourne l'URL publique via /api/media/ pour les partages externes (WhatsApp, etc.)."""
        if not obj.fichier or not obj.fichier.name:
            return None
        media_path = obj.fichier.name.lstrip('/')
        return f'{settings.API_BASE_URL}/api/media/{media_path}'


class NRPLogSerializer(serializers.ModelSerializer):
    commercial_name = serializers.CharField(source='commercial.full_name', read_only=True)

    class Meta:
        model = NRPLog
        fields = ['id', 'commercial_name', 'date', 'notes']


class SubscriptionPlanningSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlanning
        fields = '__all__'


class AppNotificationSerializer(serializers.ModelSerializer):
    demande_service = serializers.CharField(source='demande.service', read_only=True)
    demande_client_name = serializers.CharField(source='demande.client.display_name', read_only=True)

    class Meta:
        model = AppNotification
        fields = '__all__'


class DemandeSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_whatsapp = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_detail = ClientListSerializer(source='client', read_only=True)
    potential_duplicate_detail = ClientListSerializer(source='potential_duplicate_client', read_only=True)
    assigned_to_detail = UserSerializer(source='assigned_to', read_only=True)
    assigned_to_operations_name = serializers.CharField(source='assigned_to_operations.full_name', read_only=True)
    assigned_to_operations_detail = UserSerializer(source='assigned_to_operations', read_only=True)
    nrp_count = serializers.SerializerMethodField()
    nrp_logs = NRPLogSerializer(many=True, read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)
    regenerer_devis = serializers.BooleanField(write_only=True, required=False, default=False)
    envoyer_whatsapp = serializers.BooleanField(write_only=True, required=False, default=False)
    profils_envoyes = AgentListSerializer(many=True, read_only=True)
    geste_commercial = serializers.SerializerMethodField()
    planning = SubscriptionPlanningSerializer(read_only=True)
    nb_heures = serializers.SerializerMethodField()
    nb_intervenants = serializers.SerializerMethodField()
    cao = CAOField(required=False)

    class Meta:
        model = Demande
        fields = '__all__'
        extra_fields = ['reste_a_payer', 'geste_commercial', 'nb_heures', 'nb_intervenants']

    def get_nb_heures(self, obj):
        return (obj.formulaire_data or {}).get('duree') or (obj.formulaire_data or {}).get('nb_heures') or (obj.formulaire_data or {}).get('duration') or 0

    def get_nb_intervenants(self, obj):
        return (obj.formulaire_data or {}).get('nb_intervenants') or (obj.formulaire_data or {}).get('nb_personnel') or (obj.formulaire_data or {}).get('numberOfPeople') or 1

    def _stamp_parts_repartition(self, instance, validated_data):
        from django.utils import timezone
        
        request = self.context.get('request')
        user = request.user if request else None
        user_name = 'Système'
        if user:
            if user.first_name:
                user_name = user.first_name
            elif hasattr(user, 'full_name') and user.full_name:
                user_name = user.full_name.split(' ')[0]
            else:
                user_name = user.username

        current_time = timezone.localtime(timezone.now())
        formatted_date = current_time.strftime("%d/%m/%Y à %H:%M")
        
        new_parts = validated_data.get('parts_repartition')
        form_data = validated_data.get('formulaire_data')
        
        if not new_parts and isinstance(form_data, dict):
            new_parts = form_data.get('facturation', {}).get('parts_repartition')
            
        if new_parts is None:
            return
            
        old_parts = instance.parts_repartition if instance else []
        if not old_parts and instance and isinstance(instance.formulaire_data, dict):
            old_parts = instance.formulaire_data.get('facturation', {}).get('parts_repartition', [])
            
        if not isinstance(old_parts, list):
            old_parts = []
            
        old_parts_by_profile = {}
        for part in old_parts:
            p_id = part.get('profile_id')
            if p_id:
                old_parts_by_profile[str(p_id)] = part
                
        updated_parts = []
        for part in new_parts:
            if not isinstance(part, dict):
                continue
            
            p_id = part.get('profile_id')
            p_id_str = str(p_id) if p_id else None
            
            old_part = old_parts_by_profile.get(p_id_str) if p_id_str else None
            
            changed = True
            if old_part:
                # Helper to safely compare float values
                def to_f(v):
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return 0.0
                
                changed = (
                    to_f(part.get('amount')) != to_f(old_part.get('amount')) or
                    part.get('hours') != old_part.get('hours') or
                    part.get('days') != old_part.get('days') or
                    part.get('rate_value') != old_part.get('rate_value') or
                    part.get('rate_type') != old_part.get('rate_type') or
                    part.get('is_delegate') != old_part.get('is_delegate')
                )
                
            if old_part:
                part['created_at'] = old_part.get('created_at') or formatted_date
                if changed:
                    part['created_by_name'] = user_name
                else:
                    part['created_by_name'] = old_part.get('created_by_name') or user_name
            else:
                part['created_at'] = formatted_date
                part['created_by_name'] = user_name
                
            updated_parts.append(part)
            
        validated_data['parts_repartition'] = updated_parts
        if 'formulaire_data' in validated_data and isinstance(validated_data['formulaire_data'], dict):
            if 'facturation' not in validated_data['formulaire_data']:
                validated_data['formulaire_data']['facturation'] = {}
            if isinstance(validated_data['formulaire_data']['facturation'], dict):
                validated_data['formulaire_data']['facturation']['parts_repartition'] = updated_parts

    def validate(self, attrs):
        statut = attrs.get('statut')
        if not statut and self.instance:
            statut = self.instance.statut

        statut_paiement = attrs.get('statut_paiement')
        if not statut_paiement and self.instance:
            statut_paiement = self.instance.statut_paiement

        form_data = attrs.get('formulaire_data')
        if form_data is None and self.instance:
            form_data = self.instance.formulaire_data or {}

        facturation = form_data.get('facturation', {}) if isinstance(form_data, dict) else {}
        statut_paiement_ui = facturation.get('statut_paiement_ui')

        is_paying = (statut_paiement == Demande.INTEGRAL) or (statut_paiement_ui == 'paye')

        if is_paying and statut not in [Demande.PRES_TERMINEE, Demande.TERMINE]:
            raise serializers.ValidationError(
                "Le statut 'Payé' ne doit être accessible que si le besoin est préalablement passé au statut 'Prestation terminée'."
            )

        return attrs

    def get_field_names(self, declared_fields, info):
        expanded_fields = super(DemandeSerializer, self).get_field_names(declared_fields, info)
        if getattr(self.Meta, 'extra_fields', None):
            # Ajouter les extra_fields qui ne sont pas déjà inclus
            for field in self.Meta.extra_fields:
                if field not in expanded_fields:
                    expanded_fields.append(field)
        return expanded_fields

    def get_nrp_count(self, obj):
        return obj.nrp_logs.count()

    def get_geste_commercial(self, obj):
        geste = obj.gestes_commerciaux.filter(archived=False).first()
        if geste:
            return {
                'id': geste.id,
                'gesture_type': geste.gesture_type,
                'status': geste.status,
                'reduction_type': geste.reduction_type,
                'reduction_value': float(geste.reduction_value),
            }
        return None

    def create(self, validated_data):
        self._stamp_parts_repartition(None, validated_data)
        
        # Synchronize cleaner/personnel count and duration fields inside formulaire_data
        form_data = validated_data.get('formulaire_data')
        if isinstance(form_data, dict):
            cleaner_count = None
            for key in ['nb_intervenants', 'nb_personnel', 'numberOfPeople', 'nb_intervenantes']:
                val = form_data.get(key)
                if val is not None:
                    try:
                        cleaner_count = int(val)
                        break
                    except (ValueError, TypeError):
                        continue
            if cleaner_count is not None:
                form_data['nb_intervenants'] = cleaner_count
                form_data['nb_personnel'] = cleaner_count
                form_data['numberOfPeople'] = cleaner_count
                form_data['nb_intervenantes'] = cleaner_count

            duration_count = None
            for key in ['duree', 'nb_heures', 'duration', 'heures']:
                val = form_data.get(key)
                if val is not None:
                    try:
                        duration_count = int(val)
                        break
                    except (ValueError, TypeError):
                        continue
            if duration_count is not None:
                form_data['duree'] = duration_count
                form_data['nb_heures'] = duration_count
                form_data['duration'] = duration_count
                form_data['heures'] = duration_count

        client_name = validated_data.pop('client_name', '').strip()
        client_phone = validated_data.pop('client_phone', '').strip()
        client_whatsapp = validated_data.pop('client_whatsapp', '').strip()
        
        # Identification Logic
        id_statut = Demande.ID_NOUVELLE
        potential_duplicate = None
        client = None
        
        # Pop non-model fields
        regenerer_devis = validated_data.pop('regenerer_devis', False)
        envoyer_whatsapp = validated_data.pop('envoyer_whatsapp', False)

        if client_phone or client_name:
            from clients.models import Client
            
            defaults = {
                'last_name': client_name if validated_data.get('segment') == Client.PARTICULIER else '',
                'entity_name': client_name if validated_data.get('segment') == Client.ENTREPRISE else '',
            }
            form_data = validated_data.get('formulaire_data', {})
            whatsapp = client_whatsapp or form_data.get('whatsapp_phone', '')
            if whatsapp:
                defaults['whatsapp'] = whatsapp
            email = form_data.get('email', '')
            if email:
                defaults['email'] = email
            if form_data.get('ville'):
                defaults['city'] = form_data.get('ville')
            if form_data.get('quartier'):
                defaults['neighborhood'] = form_data.get('quartier')
            if form_data.get('adresse'):
                defaults['address'] = form_data.get('adresse')
            
            contact_person = form_data.get('contact_person') or form_data.get('contactPerson')
            if contact_person:
                defaults['contact_person'] = contact_person
            entity_name = form_data.get('entity_name') or form_data.get('entityName')
            if entity_name:
                defaults['entity_name'] = entity_name

            if client_phone:
                # 1. Search for existing client by phone
                existing_client = Client.objects.filter(phone=client_phone, is_archived=False).order_by('-created_at').first()
                
                if existing_client:
                    # 2. Check for name consistency
                    existing_name = existing_client.display_name.lower()
                    provided_name = client_name.lower()
                    
                    # Fuzzy match: name contains or is contained in existing name
                    # We also handle case where provided name is empty (site web might send empty if only phone provided)
                    if not provided_name or provided_name in existing_name or existing_name in provided_name:
                        # Confirmed match
                        client = existing_client
                        id_statut = Demande.ID_EXISTANT
                        
                        # Update existing client with new info
                        if client_name:
                            if validated_data.get('segment') == Client.PARTICULIER:
                                client.last_name = client_name
                            else:
                                client.entity_name = client_name
                        if client_whatsapp:
                            client.whatsapp = client_whatsapp
                        if email:
                            client.email = email
                        if form_data.get('ville'):
                            client.city = form_data.get('ville')
                        if form_data.get('quartier'):
                            client.neighborhood = form_data.get('quartier')
                        if form_data.get('adresse'):
                            client.address = form_data.get('adresse')
                        if contact_person:
                            client.contact_person = contact_person
                        if entity_name:
                            client.entity_name = entity_name
                        client.save()
                        
                        # Automatic Ownership / Assignment
                        if existing_client.assigned_commercial:
                            validated_data['assigned_to'] = existing_client.assigned_commercial
                    else:
                        # Potential duplicate / Reassigned number
                        id_statut = Demande.ID_VERIF_REQUISE
                        potential_duplicate = existing_client
                        
                        # We create a new "suspect" client record to store the provided info
                        client = Client.objects.create(phone=client_phone, **defaults)
                else:
                    # Truly new client
                    client = Client.objects.create(phone=client_phone, **defaults)
            else:
                # No phone, just create by name
                client = Client.objects.create(**defaults)
        
        if client:
            validated_data['client'] = client
            
        # Set identification fields
        validated_data['identification_statut'] = id_statut
        validated_data['potential_duplicate_client'] = potential_duplicate

        # Automate segmentation
        service = validated_data.get('service')
        segment_provided = 'segment' in self.initial_data
        
        if service and not segment_provided:
            segment = get_segment_from_service(service)
            validated_data['segment'] = segment
        
        # Always sync client segment with the demand's segment
        if client and 'segment' in validated_data:
            client.segment = validated_data['segment']
            # If no commercial assigned to client yet, assign the one from the demand
            if not client.assigned_commercial and validated_data.get('assigned_to'):
                client.assigned_commercial = validated_data['assigned_to']
            client.save()
            
        # Sync preference_horaire from formulaire_data if present
        form_data = validated_data.get('formulaire_data', {})
        if 'preference_horaire' in form_data:
            validated_data['preference_horaire'] = form_data['preference_horaire']

        instance = super().create(validated_data)

        # Auto-escalade du statut devis vers « en attente validation » sur cas complexes (brief)
        if instance.apply_devis_auto_validation():
            instance.save(update_fields=['devis_statut'])

        return instance

    def update(self, instance, validated_data):
        self._stamp_parts_repartition(instance, validated_data)
        
        # Synchronize cleaner/personnel count and duration fields inside formulaire_data
        form_data = validated_data.get('formulaire_data')
        if isinstance(form_data, dict):
            cleaner_count = None
            for key in ['nb_intervenants', 'nb_personnel', 'numberOfPeople', 'nb_intervenantes']:
                val = form_data.get(key)
                if val is not None:
                    try:
                        cleaner_count = int(val)
                        break
                    except (ValueError, TypeError):
                        continue
            if cleaner_count is not None:
                form_data['nb_intervenants'] = cleaner_count
                form_data['nb_personnel'] = cleaner_count
                form_data['numberOfPeople'] = cleaner_count
                form_data['nb_intervenantes'] = cleaner_count

            duration_count = None
            for key in ['duree', 'nb_heures', 'duration', 'heures']:
                val = form_data.get(key)
                if val is not None:
                    try:
                        duration_count = int(val)
                        break
                    except (ValueError, TypeError):
                        continue
            if duration_count is not None:
                form_data['duree'] = duration_count
                form_data['nb_heures'] = duration_count
                form_data['duration'] = duration_count
                form_data['heures'] = duration_count

        client_name = validated_data.pop('client_name', None)
        client_phone = validated_data.pop('client_phone', None)
        client_whatsapp = validated_data.pop('client_whatsapp', None)
        
        # Pop non-model fields
        regenerer_devis = validated_data.pop('regenerer_devis', False)
        envoyer_whatsapp = validated_data.pop('envoyer_whatsapp', False)
        
        if client_phone is not None or client_name is not None or client_whatsapp is not None:
            if not instance.client:
                from clients.models import Client
                if client_phone:
                    instance.client, _ = Client.objects.get_or_create(phone=client_phone)
                else:
                    instance.client = Client.objects.create()
            
            # Now we are guaranteed to have instance.client
            if client_name is not None:
                instance.client.last_name = client_name
                instance.client.first_name = ""  # Prevent duplication when BO provides full name
            if client_phone is not None:
                instance.client.phone = client_phone
            if client_whatsapp is not None:
                instance.client.whatsapp = client_whatsapp
            
            form_data = validated_data.get('formulaire_data', {})
            email = form_data.get('email', '')
            if email is not None:
                instance.client.email = email
            
            if form_data.get('ville'):
                instance.client.city = form_data.get('ville')
            if form_data.get('quartier'):
                instance.client.neighborhood = form_data.get('quartier')
            if form_data.get('adresse'):
                instance.client.address = form_data.get('adresse')
                
            contact_person = form_data.get('contact_person') or form_data.get('contactPerson')
            if contact_person:
                instance.client.contact_person = contact_person
            entity_name = form_data.get('entity_name') or form_data.get('entityName')
            if entity_name:
                instance.client.entity_name = entity_name
                
            instance.client.save()
        
        if 'formulaire_data' in validated_data:
            if 'preference_horaire' in validated_data['formulaire_data']:
                instance.preference_horaire = validated_data['formulaire_data']['preference_horaire']
        
        # Automate segmentation on update
        service = validated_data.get('service', instance.service)
        segment_provided = 'segment' in self.initial_data
        
        if service and not segment_provided:
            segment = get_segment_from_service(service)
            validated_data['segment'] = segment
            
        # Sync client segment if demand's segment changed or was explicitly set
        target_client = instance.client
        if target_client and 'segment' in validated_data:
            target_client.segment = validated_data['segment']
            target_client.save()
                    
        instance = super().update(instance, validated_data)

        # Auto-escalade du statut devis vers « en attente validation » sur cas complexes (brief)
        if instance.apply_devis_auto_validation():
            instance.save(update_fields=['devis_statut'])

        # ─── WhatsApp / Document Integration ───
        if regenerer_devis or envoyer_whatsapp:
            doc_type = 'devis' if (instance.segment == 'entreprise' or instance.is_devis) else 'png'
            
            # Step 1: Handle Document Generation (if requested or needed for WA)
            doc = None
            if regenerer_devis:
                doc = generate_demande_document(instance, doc_type)
            else:
                # Get latest document of that type
                doc = instance.documents.filter(type_document=doc_type).first()
            
            # Step 2: Send WhatsApp (if requested)
            if envoyer_whatsapp:
                client_phone = instance.client.phone if instance.client else None
                if client_phone:
                    # Construct absolute media URL
                    media_url = f"{settings.API_BASE_URL}/api/media/{doc.fichier.name}" if doc and doc.fichier and doc.fichier.name else None
                    
                    if media_url:
                        client_name = instance.client.display_name if instance.client else "Client"
                        
                        # Résoudre le prix depuis formulaire_data ou instance.prix
                        form = instance.formulaire_data or {}
                        prix_display = "Sur devis"
                        for key in ['total', 'total_ht', 'total_ttc', 'prix_total', 'montant_total', 'montant', 'prix']:
                            val = form.get(key)
                            if val is not None:
                                try:
                                    n = float(str(val).replace(' ', '').replace(',', '.'))
                                    if n > 0:
                                        prix_display = f"{n:,.0f}".replace(",", " ") + " MAD"
                                        break
                                except (ValueError, TypeError):
                                    pass
                        if prix_display == "Sur devis" and instance.prix is not None:
                            prix_display = f"{instance.prix:,.0f}".replace(",", " ") + " MAD"
                        
                        # Variables based on the proposed templates
                        if doc_type == 'devis':
                            if getattr(settings, 'BYPASS_NEW_WA_TEMPLATES', False):
                                template = 'envoi_devis_client'
                                vars = [client_name, instance.devis_numero(), instance.service]
                            else:
                                from .utils.devis_templates import get_devis_template
                                template, vars = get_devis_template(instance, client_name)
                            wa_media_type = 'document'
                        else:
                            template = 'envoi_resume_client'
                            vars = [
                                client_name, 
                                instance.service, 
                                instance.date_intervention.strftime('%d/%m/%Y') if instance.date_intervention else "Non définie",
                                instance.heure_intervention or "—",
                                prix_display
                            ]
                            wa_media_type = 'image'
                        
                        WhatsAppService.send_template_message(
                            to=client_phone,
                            template_name=template,
                            media_url=media_url,
                            media_type=wa_media_type,
                            variables=vars
                        )

        return instance


class DemandeListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_whatsapp = serializers.CharField(source='client.whatsapp', read_only=True)
    client_email = serializers.CharField(source='client.email', read_only=True)
    client_entity = serializers.CharField(source='client.entity_name', read_only=True)
    client_contact = serializers.CharField(source='client.contact_person', read_only=True)
    client_city = serializers.CharField(source='client.city', read_only=True)
    client_neighborhood = serializers.CharField(source='client.neighborhood', read_only=True)
    client_address = serializers.CharField(source='client.address', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    assigned_to_operations_name = serializers.CharField(source='assigned_to_operations.full_name', read_only=True)
    mode_paiement_label = serializers.CharField(source='get_mode_paiement_display', read_only=True)
    statut_paiement_label = serializers.CharField(source='get_statut_paiement_display', read_only=True)
    nrp_count = serializers.SerializerMethodField()
    profil_share_link = serializers.SerializerMethodField()
    profil_share_links = serializers.SerializerMethodField()
    documents = DocumentSerializer(many=True, read_only=True)
    profils_envoyes = AgentListSerializer(many=True, read_only=True)
    statut_paiement_ui = serializers.SerializerMethodField()
    montant_ht = serializers.SerializerMethodField()
    montant_ttc = serializers.SerializerMethodField()
    montant_verse = serializers.SerializerMethodField()
    montant_agence_doit_profil = serializers.SerializerMethodField()
    montant_profil_doit_agence = serializers.SerializerMethodField()
    annulation_raison = serializers.SerializerMethodField()
    profil_sera_paye = serializers.SerializerMethodField()
    montant_profil_annulation = serializers.SerializerMethodField()
    geste_commercial = serializers.SerializerMethodField()
    planning = SubscriptionPlanningSerializer(read_only=True)
    nb_heures = serializers.SerializerMethodField()
    nb_intervenants = serializers.SerializerMethodField()
    cao = CAOField(required=False)

    class Meta:
        model = Demande
        fields = [
            'id', 'client', 'service', 'segment', 'source', 'statut', 'frequency',
            'frequency_label', 'date_intervention', 'heure_intervention',
            'prix', 'is_devis', 'devis_statut', 'mode_paiement', 'statut_paiement',
            'mode_paiement_label', 'statut_paiement_label', 'reste_a_payer', 'cao',
            'part_agence', 'parts_repartition',
            'statut_paiement_ui', 'montant_ht', 'montant_ttc', 'montant_verse',
            'montant_agence_doit_profil', 'montant_profil_doit_agence',
            'annulation_raison', 'profil_sera_paye', 'montant_profil_annulation',
            'formulaire_data', 'created_at', 'preference_horaire',
            'client_name', 'client_phone', 'client_whatsapp', 'client_email', 'client_entity', 'client_contact',
            'client_city', 'client_neighborhood', 'client_address',
            'assigned_to', 'assigned_to_name', 'assigned_to_operations', 'assigned_to_operations_name', 'created_by', 'nrp_count', 'profil_share_link', 'profil_share_links', 'documents', 'profils_envoyes',
            'note_commercial', 'note_operationnel', 'geste_commercial', 'planning', 'parent_demande',
            'nb_heures', 'nb_intervenants'
        ]

    def get_nb_heures(self, obj):
        return (obj.formulaire_data or {}).get('duree') or (obj.formulaire_data or {}).get('nb_heures') or (obj.formulaire_data or {}).get('duration') or 0

    def get_nb_intervenants(self, obj):
        return (obj.formulaire_data or {}).get('nb_intervenants') or (obj.formulaire_data or {}).get('nb_personnel') or (obj.formulaire_data or {}).get('numberOfPeople') or 1

    def _get_facturation_field(self, obj, field, default=None):
        return (obj.formulaire_data or {}).get('facturation', {}).get(field, default)

    def get_statut_paiement_ui(self, obj):
        return self._get_facturation_field(obj, 'statut_paiement_ui')

    def get_montant_ht(self, obj):
        return self._get_facturation_field(obj, 'montant_ht', 0)

    def get_montant_ttc(self, obj):
        return self._get_facturation_field(obj, 'montant_ttc', obj.prix)

    def get_montant_verse(self, obj):
        return self._get_facturation_field(obj, 'montant_verse', 0)

    def get_montant_agence_doit_profil(self, obj):
        return self._get_facturation_field(obj, 'montant_agence_doit_profil', 0)

    def get_montant_profil_doit_agence(self, obj):
        return self._get_facturation_field(obj, 'montant_profil_doit_agence', 0)

    def get_annulation_raison(self, obj):
        return self._get_facturation_field(obj, 'annulation_raison', '')

    def get_profil_sera_paye(self, obj):
        return self._get_facturation_field(obj, 'profil_sera_paye', False)

    def get_montant_profil_annulation(self, obj):
        return self._get_facturation_field(obj, 'montant_profil_annulation', 0)

    def get_nrp_count(self, obj):
        return obj.nrp_logs.count()

    def get_profil_share_link(self, obj):
        agent = obj.profils_envoyes.order_by('id').last()
        if not agent:
            return ''

        share, _ = ProfilShare.objects.get_or_create(demande=obj, agent=agent)
        return f"https://profil.agencemenage.ma/view/{share.uuid}"

    def get_profil_share_links(self, obj):
        agents = obj.profils_envoyes.order_by('id')
        links = []

        for agent in agents:
            share, _ = ProfilShare.objects.get_or_create(demande=obj, agent=agent)
            links.append({
                'agent_id': agent.id,
                'agent_name': getattr(agent, 'full_name', '') or f"{agent.first_name} {agent.last_name}".strip(),
                'link': f"https://profil.agencemenage.ma/view/{share.uuid}",
            })

        return links

    def get_geste_commercial(self, obj):
        geste = obj.gestes_commerciaux.filter(archived=False).first()
        if geste:
            return {
                'id': geste.id,
                'gesture_type': geste.gesture_type,
                'status': geste.status,
                'reduction_type': geste.reduction_type,
                'reduction_value': float(geste.reduction_value),
            }
        return None


class DemandeHistoriqueSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_whatsapp = serializers.CharField(source='client.whatsapp', read_only=True)
    client_city = serializers.CharField(source='client.city', read_only=True)
    client_neighborhood = serializers.CharField(source='client.neighborhood', read_only=True)
    client_address = serializers.CharField(source='client.address', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    profil_name = serializers.SerializerMethodField()
    profil_id = serializers.SerializerMethodField()
    statut_besoin_label = serializers.SerializerMethodField()
    statut_paiement_label = serializers.SerializerMethodField()
    statut_paiement_ui = serializers.SerializerMethodField()
    motif = serializers.SerializerMethodField()
    cao = CAOField(required=False)

    class Meta:
        model = Demande
        fields = [
            'id',
            'client',
            'client_name',
            'client_phone',
            'client_whatsapp',
            'client_city',
            'client_neighborhood',
            'client_address',
            'assigned_to',
            'assigned_to_name',
            'service',
            'segment',
            'statut',
            'statut_besoin_label',
            'statut_paiement',
            'statut_paiement_label',
            'statut_paiement_ui',
            'created_at',
            'profil_name',
            'profil_id',
            'motif',
            'formulaire_data',
            'date_intervention',
            'prix',
            'mode_paiement',
            'part_agence',
            'parts_repartition',
            'cao',
            'parent_demande',
            'frequency',
            'frequency_label',
        ]

    def get_profil_name(self, obj):
        profile = obj.profils_envoyes.order_by('id').first()
        return profile.full_name if profile else ''

    def get_profil_id(self, obj):
        profile = obj.profils_envoyes.order_by('id').first()
        return profile.id if profile else None

    def get_statut_besoin_label(self, obj):
        if obj.statut == Demande.EN_ATTENTE:
            return 'Nouveau besoin'
        if obj.statut == Demande.ENCOURS:
            return 'Confirmé' if obj.cao else 'En attente'
        if obj.statut == Demande.TERMINE:
            return 'Paye'
        if obj.statut == Demande.ANNULE:
            return 'Annule'
        return obj.get_statut_display()

    def get_statut_paiement_label(self, obj):
        ui_value = self.get_statut_paiement_ui(obj)
        ui_map = {
            'non_confirme': 'Non confirmé',
            'paiement_en_attente': 'Paiement en attente',
            'agence_payee_client': 'Agence payé / Client',
            'profil_paye_client': 'Profil payé / Client',
            'commercial_paye_client': 'Commercial payé / client',
            'paye': 'Payé',
            'paiement_partiel': 'Paiement partiel',
            'facturation_annulee': 'Annulé',
        }
        if ui_value in ui_map:
            return ui_map[ui_value]
        return obj.get_statut_paiement_display()

    def get_statut_paiement_ui(self, obj):
        facturation = (obj.formulaire_data or {}).get('facturation', {})
        ui_value = facturation.get('statut_paiement_ui')
        if ui_value:
            return ui_value

        if facturation.get('facturation_annulee'):
            return 'facturation_annulee'
        if obj.statut_paiement == Demande.INTEGRAL:
            return 'paye'
        if obj.statut_paiement == Demande.ACOMPTE:
            return 'paiement_en_attente'
        if obj.statut_paiement == Demande.PARTIEL:
            return 'paiement_partiel'
        return 'non_confirme'

    def get_motif(self, obj):
        if obj.statut == Demande.ANNULE:
            return obj.avis_annulation or ''
        return ''


class PublicDemandeCreateSerializer(serializers.ModelSerializer):
    """Serializer public (sans auth) pour créer une demande depuis le site web."""
    client_nom = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_prenom = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_phone = serializers.CharField(write_only=True)
    client_email = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_whatsapp = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_ville = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_quartier = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_address = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)
    client_entity = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Demande
        fields = [
            'service', 'segment', 'frequency', 'frequency_label',
            'date_intervention', 'heure_intervention', 'preference_horaire', 'prix', 'is_devis',
            'formulaire_data',
            'client_nom', 'client_prenom', 'client_phone', 'client_email',
            'client_whatsapp', 'client_ville', 'client_quartier', 'client_address', 'client_entity',
        ]

    def create(self, validated_data):
        from clients.models import Client

        # Extract client fields
        client_data = {
            'last_name': validated_data.pop('client_nom', ''),
            'first_name': validated_data.pop('client_prenom', ''),
            'phone': validated_data.pop('client_phone'),
            'email': validated_data.pop('client_email', '') or '',
            'whatsapp': validated_data.pop('client_whatsapp', '') or '',
            'city': validated_data.pop('client_ville', '') or '',
            'neighborhood': validated_data.pop('client_quartier', '') or '',
            'address': validated_data.pop('client_address', '') or '',
            'entity_name': validated_data.pop('client_entity', '') or '',
            'segment': validated_data.get('segment', Client.PARTICULIER),
        }

        phone = client_data.pop('phone').strip()
        client_name = (client_data['entity_name'] or f"{client_data['first_name']} {client_data['last_name']}").strip()

        # Identification Logic
        id_statut = Demande.ID_NOUVELLE
        potential_duplicate = None
        client = None

        # 1. Search for existing client by phone
        existing_client = Client.objects.filter(phone=phone, is_archived=False).order_by('-created_at').first()

        if existing_client:
            # 2. Check for name consistency
            existing_name = existing_client.display_name.lower()
            provided_name = client_name.lower()
            
            if not provided_name or provided_name in existing_name or existing_name in provided_name:
                # Confirmed match
                client = existing_client
                id_statut = Demande.ID_EXISTANT
                
                # Update existing client info
                if client_data['last_name']:
                    client.last_name = client_data['last_name']
                if client_data['first_name']:
                    client.first_name = client_data['first_name']
                if client_data['whatsapp']:
                    client.whatsapp = client_data['whatsapp']
                if client_data['email']:
                    client.email = client_data['email']
                if client_data['city']:
                    client.city = client_data['city']
                if client_data['neighborhood']:
                    client.neighborhood = client_data['neighborhood']
                if client_data['address']:
                    client.address = client_data['address']
                if client_data['entity_name']:
                    client.entity_name = client_data['entity_name']
                if client_data.get('contact_person'):
                    client.contact_person = client_data['contact_person']
                client.save()
                
                # Auto-assign to existing commercial
                if existing_client.assigned_commercial:
                    validated_data['assigned_to'] = existing_client.assigned_commercial
            else:
                # Potential duplicate
                id_statut = Demande.ID_VERIF_REQUISE
                potential_duplicate = existing_client
                client = Client.objects.create(phone=phone, **client_data)
        else:
            # New client
            client = Client.objects.create(phone=phone, **client_data)

        # Automate segmentation
        service = validated_data.get('service')
        segment_provided = 'segment' in self.initial_data
        
        if service and not segment_provided:
            segment = get_segment_from_service(service)
            validated_data['segment'] = segment

        # Sync client segment & Ownership
        if client:
            if 'segment' in validated_data:
                client.segment = validated_data['segment']
            if not client.assigned_commercial and validated_data.get('assigned_to'):
                client.assigned_commercial = validated_data['assigned_to']
            client.save()

        demande = Demande.objects.create(
            client=client,
            source=Demande.SITE,
            mode_paiement=Demande.VIREMENT,
            statut=Demande.EN_ATTENTE,
            identification_statut=id_statut,
            potential_duplicate_client=potential_duplicate,
            **validated_data
        )
        return demande


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'


class FeteReligieuseSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    debut_suspension = serializers.DateField(read_only=True)
    fin_suspension = serializers.DateField(read_only=True)

    class Meta:
        model = FeteReligieuse
        fields = [
            'id', 'type', 'type_display', 'date', 'annee',
            'jours_avant', 'jours_apres', 'actif',
            'debut_suspension', 'fin_suspension',
        ]
