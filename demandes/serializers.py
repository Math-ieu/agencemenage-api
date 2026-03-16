from rest_framework import serializers
from .models import Demande, NRPLog, Document, AuditLog
from clients.serializers import ClientListSerializer
from accounts.serializers import UserSerializer


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']


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
        
        client = None
        if client_phone or client_name:
            from clients.models import Client
            defaults = {'last_name': client_name}
            form_data = validated_data.get('formulaire_data', {})
            whatsapp = form_data.get('whatsapp_phone', '')
            if whatsapp:
                defaults['whatsapp'] = whatsapp
            if form_data.get('ville'):
                defaults['city'] = form_data.get('ville')
            if form_data.get('quartier'):
                defaults['neighborhood'] = form_data.get('quartier')

            if client_phone:
                client, _ = Client.objects.get_or_create(phone=client_phone, defaults=defaults)
            else:
                client = Client.objects.create(**defaults)
        
        if client:
            validated_data['client'] = client
            
        return super().create(validated_data)

    def update(self, instance, validated_data):
        client_name = validated_data.pop('client_name', None)
        client_phone = validated_data.pop('client_phone', None)
        
        if client_phone is not None or client_name is not None:
            if instance.client:
                if client_name is not None:
                    instance.client.last_name = client_name
                if client_phone is not None:
                    instance.client.phone = client_phone
                
                form_data = validated_data.get('formulaire_data', {})
                whatsapp = form_data.get('whatsapp_phone', '')
                if whatsapp:
                    instance.client.whatsapp = whatsapp
                instance.client.save()
            else:
                from clients.models import Client
                defaults = {'last_name': client_name or ''}
                if client_phone:
                    instance.client, _ = Client.objects.get_or_create(phone=client_phone, defaults=defaults)
                else:
                    instance.client = Client.objects.create(**defaults)
                    
        return super().update(instance, validated_data)


class DemandeListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_whatsapp = serializers.CharField(source='client.whatsapp', read_only=True)
    client_city = serializers.CharField(source='client.city', read_only=True)
    client_neighborhood = serializers.CharField(source='client.neighborhood', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    mode_paiement_label = serializers.CharField(source='get_mode_paiement_display', read_only=True)
    statut_paiement_label = serializers.CharField(source='get_statut_paiement_display', read_only=True)
    nrp_count = serializers.SerializerMethodField()

    class Meta:
        model = Demande
        fields = [
            'id', 'service', 'segment', 'source', 'statut', 'frequency',
            'frequency_label', 'date_intervention', 'heure_intervention',
            'prix', 'is_devis', 'mode_paiement', 'statut_paiement', 
            'mode_paiement_label', 'statut_paiement_label', 'reste_a_payer', 'cao',
            'formulaire_data', 'created_at',
            'client_name', 'client_phone', 'client_whatsapp',
            'client_city', 'client_neighborhood',
            'assigned_to_name', 'nrp_count'
        ]

    def get_nrp_count(self, obj):
        return obj.nrp_logs.count()


class PublicDemandeCreateSerializer(serializers.ModelSerializer):
    """Serializer public (sans auth) pour créer une demande depuis le site web."""
    client_nom = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_prenom = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_phone = serializers.CharField(write_only=True)
    client_email = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_whatsapp = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_ville = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_quartier = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_entity = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Demande
        fields = [
            'service', 'segment', 'frequency', 'frequency_label',
            'date_intervention', 'heure_intervention', 'prix', 'is_devis',
            'formulaire_data',
            'client_nom', 'client_prenom', 'client_phone', 'client_email',
            'client_whatsapp', 'client_ville', 'client_quartier', 'client_entity',
        ]

    def create(self, validated_data):
        from clients.models import Client

        # Extract client fields
        client_data = {
            'last_name': validated_data.pop('client_nom', ''),
            'first_name': validated_data.pop('client_prenom', ''),
            'phone': validated_data.pop('client_phone'),
            'email': validated_data.pop('client_email', ''),
            'whatsapp': validated_data.pop('client_whatsapp', ''),
            'city': validated_data.pop('client_ville', ''),
            'neighborhood': validated_data.pop('client_quartier', ''),
            'entity_name': validated_data.pop('client_entity', ''),
            'segment': validated_data.get('segment', Client.PARTICULIER),
        }

        # Find or create client by phone
        client, _ = Client.objects.get_or_create(
            phone=client_data['phone'],
            defaults=client_data
        )

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
