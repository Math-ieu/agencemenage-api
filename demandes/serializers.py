from rest_framework import serializers
from .models import Demande, NRPLog, Document, AuditLog
from django.conf import settings
from .utils.whatsapp import WhatsAppService
from .utils.document_helpers import generate_demande_document
from .constants import get_segment_from_service
from clients.serializers import ClientListSerializer
from accounts.serializers import UserSerializer
from agents.serializers import AgentListSerializer


class DocumentSerializer(serializers.ModelSerializer):
    # URL sécurisée qui n'expose JAMAIS le chemin réel du fichier
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ['id', 'demande', 'type_document', 'nom', 'created_at', 'created_by', 'download_url']
        read_only_fields = ['created_at', 'created_by', 'download_url']

    def get_download_url(self, obj):
        """Retourne l'URL de téléchargement sécurisé sans exposer le chemin physique."""
        if not obj.fichier:
            return None
        return f'/api/demandes/{obj.demande_id}/download/{obj.id}/'


class NRPLogSerializer(serializers.ModelSerializer):
    commercial_name = serializers.CharField(source='commercial.full_name', read_only=True)

    class Meta:
        model = NRPLog
        fields = ['id', 'commercial_name', 'date', 'notes']


class DemandeSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_detail = ClientListSerializer(source='client', read_only=True)
    assigned_to_detail = UserSerializer(source='assigned_to', read_only=True)
    nrp_count = serializers.SerializerMethodField()
    nrp_logs = NRPLogSerializer(many=True, read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)
    regenerer_devis = serializers.BooleanField(write_only=True, required=False, default=False)
    envoyer_whatsapp = serializers.BooleanField(write_only=True, required=False, default=False)
    profils_envoyes = AgentListSerializer(many=True, read_only=True)

    class Meta:
        model = Demande
        fields = '__all__'
        extra_fields = ['reste_a_payer']

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

    def create(self, validated_data):
        client_name = validated_data.pop('client_name', '')
        client_phone = validated_data.pop('client_phone', '')
        
        # Pop non-model fields
        regenerer_devis = validated_data.pop('regenerer_devis', False)
        envoyer_whatsapp = validated_data.pop('envoyer_whatsapp', False)
        
        client = None
        if client_phone or client_name:
            from clients.models import Client
            defaults = {'last_name': client_name}
            form_data = validated_data.get('formulaire_data', {})
            whatsapp = form_data.get('whatsapp_phone', '')
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

            if client_phone:
                client, _ = Client.objects.get_or_create(phone=client_phone, defaults=defaults)
            else:
                client = Client.objects.create(**defaults)
        
        if client:
            validated_data['client'] = client
            
        # Automate segmentation
        service = validated_data.get('service')
        segment_provided = 'segment' in self.initial_data
        
        if service and not segment_provided:
            segment = get_segment_from_service(service)
            validated_data['segment'] = segment
        
        # Always sync client segment with the demand's segment
        if client and 'segment' in validated_data:
            client.segment = validated_data['segment']
            client.save()
            
        # Sync preference_horaire from formulaire_data if present
        form_data = validated_data.get('formulaire_data', {})
        if 'preference_horaire' in form_data and not validated_data.get('preference_horaire'):
            validated_data['preference_horaire'] = form_data['preference_horaire']

        return super().create(validated_data)

    def update(self, instance, validated_data):
        client_name = validated_data.pop('client_name', None)
        client_phone = validated_data.pop('client_phone', None)
        
        # Pop non-model fields
        regenerer_devis = validated_data.pop('regenerer_devis', False)
        envoyer_whatsapp = validated_data.pop('envoyer_whatsapp', False)
        
        if client_phone is not None or client_name is not None:
            if instance.client:
                if client_name is not None:
                    instance.client.last_name = client_name
                    instance.client.first_name = ""  # Prevent duplication when BO provides full name
                if client_phone is not None:
                    instance.client.phone = client_phone
                
                form_data = validated_data.get('formulaire_data', {})
                whatsapp = form_data.get('whatsapp_phone', '')
                if whatsapp:
                    instance.client.whatsapp = whatsapp
                email = form_data.get('email', '')
                if email:
                    instance.client.email = email
                
                if form_data.get('ville'):
                    instance.client.city = form_data.get('ville')
                if form_data.get('quartier'):
                    instance.client.neighborhood = form_data.get('quartier')
                if form_data.get('adresse'):
                    instance.client.address = form_data.get('adresse')
                    
                instance.client.save()
            else:
                from clients.models import Client
                defaults = {'last_name': client_name or ''}
                if client_phone:
                    instance.client, _ = Client.objects.get_or_create(phone=client_phone, defaults=defaults)
                else:
                    instance.client = Client.objects.create(**defaults)
        
        if 'formulaire_data' in validated_data:
            pref = validated_data['formulaire_data'].get('preference_horaire')
            if pref:
                instance.preference_horaire = pref
        
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
                    media_url = f"{settings.API_BASE_URL}/api/media/{doc.fichier.name}" if doc else None
                    
                    if media_url:
                        client_name = instance.client.display_name if instance.client else "Client"
                        # Variables based on the proposed templates
                        if doc_type == 'devis':
                            template = 'envoi_devis_client'
                            vars = [client_name, f"D-{instance.id:05d}", instance.service, f"{instance.prix}"]
                            wa_media_type = 'document'
                        else:
                            template = 'envoi_resume_client'
                            vars = [
                                client_name, 
                                instance.service, 
                                instance.date_intervention.strftime('%d/%m/%Y') if instance.date_intervention else "Non définie",
                                instance.heure_intervention or "—",
                                f"{instance.prix}"
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
    client_city = serializers.CharField(source='client.city', read_only=True)
    client_neighborhood = serializers.CharField(source='client.neighborhood', read_only=True)
    client_address = serializers.CharField(source='client.address', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    mode_paiement_label = serializers.CharField(source='get_mode_paiement_display', read_only=True)
    statut_paiement_label = serializers.CharField(source='get_statut_paiement_display', read_only=True)
    nrp_count = serializers.SerializerMethodField()
    documents = DocumentSerializer(many=True, read_only=True)
    profils_envoyes = AgentListSerializer(many=True, read_only=True)

    class Meta:
        model = Demande
        fields = [
            'id', 'client', 'service', 'segment', 'source', 'statut', 'frequency',
            'frequency_label', 'date_intervention', 'heure_intervention',
            'prix', 'is_devis', 'mode_paiement', 'statut_paiement', 
            'mode_paiement_label', 'statut_paiement_label', 'reste_a_payer', 'cao',
            'formulaire_data', 'created_at', 'preference_horaire',
            'client_name', 'client_phone', 'client_whatsapp',
            'client_city', 'client_neighborhood', 'client_address',
            'assigned_to_name', 'nrp_count', 'documents', 'profils_envoyes'
        ]

    def get_nrp_count(self, obj):
        return obj.nrp_logs.count()


class DemandeHistoriqueSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    profil_name = serializers.SerializerMethodField()
    profil_id = serializers.SerializerMethodField()
    statut_besoin_label = serializers.SerializerMethodField()
    statut_paiement_label = serializers.SerializerMethodField()
    statut_paiement_ui = serializers.SerializerMethodField()
    motif = serializers.SerializerMethodField()

    class Meta:
        model = Demande
        fields = [
            'id',
            'client',
            'client_name',
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
            return 'En attente'
        if obj.statut == Demande.TERMINE:
            return 'Paye'
        if obj.statut == Demande.ANNULE:
            return 'Annule'
        return obj.get_statut_display()

    def get_statut_paiement_label(self, obj):
        ui_value = self.get_statut_paiement_ui(obj)
        ui_map = {
            'non_confirme': 'Non confirme',
            'paiement_en_attente': 'Paiement en attente',
            'agence_payee_client': 'Agence payee / Client',
            'profil_paye_client': 'profil_paye_client',
            'paye': 'Paye',
            'paiement_partiel': 'Paiement partiel',
            'facturation_annulee': 'Facturation annulee',
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

        phone = client_data.pop('phone')

        # Find or create client by phone, then update fields if they exist
        client, created = Client.objects.get_or_create(
            phone=phone,
            defaults={'phone': phone, **client_data}
        )

        # If client already existed, update non-empty fields
        if not created:
            for field, value in client_data.items():
                if value:  # Only update with non-empty values
                    setattr(client, field, value)
            client.phone = phone
            client.save()

        # Automate segmentation
        service = validated_data.get('service')
        segment_provided = 'segment' in self.initial_data
        
        if service and not segment_provided:
            segment = get_segment_from_service(service)
            validated_data['segment'] = segment

        # Sync client segment
        if 'segment' in validated_data:
            client.segment = validated_data['segment']
            client.save()

        demande = Demande.objects.create(
            client=client,
            source=Demande.SITE,
            statut=Demande.EN_ATTENTE,
            **validated_data
        )
        return demande


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = AuditLog
        fields = '__all__'
