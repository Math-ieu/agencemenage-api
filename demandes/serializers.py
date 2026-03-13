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
    client_detail = ClientListSerializer(source='client', read_only=True)
    assigned_to_detail = UserSerializer(source='assigned_to', read_only=True)
    nrp_count = serializers.SerializerMethodField()
    nrp_logs = NRPLogSerializer(many=True, read_only=True)
    documents = DocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Demande
        fields = '__all__'

    def get_nrp_count(self, obj):
        return obj.nrp_logs.count()


class DemandeListSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    nrp_count = serializers.SerializerMethodField()

    class Meta:
        model = Demande
        fields = [
            'id', 'service', 'segment', 'source', 'statut', 'frequency',
            'date_intervention', 'heure_intervention', 'prix', 'is_devis',
            'mode_paiement', 'statut_paiement', 'cao', 'created_at',
            'client_name', 'client_phone', 'assigned_to_name', 'nrp_count'
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
