from rest_framework import serializers
from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = '__all__'

    def get_demandes_count(self, obj):
        return obj.demandes.filter(parent_demande__isnull=True).count()


class ClientListSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.SerializerMethodField()
    latest_demande = serializers.SerializerMethodField()
    assigned_commercial_name = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'display_name', 'first_name', 'last_name', 'entity_name',
            'phone', 'email', 'segment', 'city', 'neighborhood', 'address', 
            'created_at', 'demandes_count', 'latest_demande',
            'avis_commercial', 'avis_operationnel', 'is_blacklisted',
            'assigned_commercial', 'assigned_commercial_name'
        ]

    def get_assigned_commercial_name(self, obj):
        return obj.assigned_commercial.full_name if obj.assigned_commercial else None

    def get_demandes_count(self, obj):
        return obj.demandes.filter(parent_demande__isnull=True).count()

    def get_latest_demande(self, obj):
        latest = obj.demandes.order_by('-created_at').first()
        if latest:
            fact = latest.formulaire_data.get('facturation', {}) if isinstance(latest.formulaire_data, dict) else {}
            statut_paiement_ui = fact.get('statut_paiement_ui')
            facturation_annulee = fact.get('facturation_annulee', False)
            return {
                'id': latest.id,
                'statut': latest.statut,
                'statut_paiement': latest.statut_paiement,
                'statut_paiement_ui': statut_paiement_ui,
                'facturation_annulee': facturation_annulee,
                'commercial': latest.assigned_to.full_name if latest.assigned_to else None,
                'created_at': latest.created_at,
                'cao': True if latest.cao == 'oui' else (False if latest.cao == 'non' else latest.cao),
                'frequency': latest.frequency
            }
        return None

from .models import ClientActionLog, ClientCommercialAssignment

class ClientActionLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = ClientActionLog
        fields = ['id', 'action', 'details', 'user', 'user_name', 'created_at']


class ClientCommercialAssignmentSerializer(serializers.ModelSerializer):
    commercial_name = serializers.ReadOnlyField(source='commercial.full_name', default='Non affecté')
    assigned_by_name_display = serializers.SerializerMethodField()

    class Meta:
        model = ClientCommercialAssignment
        fields = ['id', 'commercial', 'commercial_name', 'assigned_by', 'assigned_by_name_display', 'notes', 'created_at']

    def get_assigned_by_name_display(self, obj):
        if obj.assigned_by_name:
            return obj.assigned_by_name
        return obj.assigned_by.full_name if obj.assigned_by else '—'

