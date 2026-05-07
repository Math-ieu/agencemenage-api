from rest_framework import serializers
from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = '__all__'

    def get_demandes_count(self, obj):
        return obj.demandes.count()


class ClientListSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.IntegerField(source='demandes.count', read_only=True)
    latest_demande = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'display_name', 'first_name', 'last_name', 'entity_name',
            'phone', 'email', 'segment', 'city', 'neighborhood', 'address', 
            'created_at', 'demandes_count', 'latest_demande',
            'avis_commercial', 'avis_operationnel'
        ]

    def get_latest_demande(self, obj):
        latest = obj.demandes.order_by('-created_at').first()
        if latest:
            return {
                'id': latest.id,
                'statut': latest.statut,
                'statut_paiement': latest.statut_paiement,
                'commercial': latest.assigned_to.full_name if latest.assigned_to else None,
                'created_at': latest.created_at
            }
        return None

from .models import ClientActionLog

class ClientActionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientActionLog
        fields = ['id', 'action', 'details', 'created_at']
