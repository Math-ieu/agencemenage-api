from rest_framework import serializers
from django.utils import timezone
from .models import Client


class ClientSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.SerializerMethodField()
    is_airbnb = serializers.SerializerMethodField()
    nb_biens_actifs_airbnb = serializers.SerializerMethodField()
    sous_seuil_alerte = serializers.SerializerMethodField()
    en_periode_probatoire = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = '__all__'

    def to_internal_value(self, data):
        if hasattr(data, 'get') and data.get('trigramme') == '':
            data = data.copy()
            data['trigramme'] = None
        return super().to_internal_value(data)

    def get_demandes_count(self, obj):
        return obj.demandes.filter(parent_demande__isnull=True).count()

    def get_is_airbnb(self, obj):
        return obj.is_airbnb_client()

    def get_nb_biens_actifs_airbnb(self, obj):
        if not hasattr(obj, 'biens_airbnb'):
            return 0
        return obj.biens_airbnb.filter(is_active=True, statut_activation='actif').count()

    def get_sous_seuil_alerte(self, obj):
        nb = self.get_nb_biens_actifs_airbnb(obj)
        if nb == 0 and not self.get_is_airbnb(obj):
            return False
        try:
            from airbnb.models import AirbnbConfig
            seuil = AirbnbConfig.objects.values_list('seuil_biens_conciergerie', flat=True).first()
            seuil = seuil if seuil is not None else 3
        except Exception:
            seuil = 3
        return nb < seuil

    def get_en_periode_probatoire(self, obj):
        if obj.mode_paiement_airbnb != 'mensuel' or obj.probatoire_bascule_annulee:
            return False
        if not obj.probatoire_jusqu_au:
            return False
        return timezone.localdate() <= obj.probatoire_jusqu_au


class ClientListSerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    demandes_count = serializers.SerializerMethodField()
    latest_demande = serializers.SerializerMethodField()
    assigned_commercial_name = serializers.SerializerMethodField()
    is_airbnb = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'display_name', 'first_name', 'last_name', 'entity_name',
            'phone', 'email', 'segment', 'city', 'neighborhood', 'address', 
            'created_at', 'demandes_count', 'latest_demande',
            'avis_commercial', 'avis_operationnel', 'is_blacklisted',
            'assigned_commercial', 'assigned_commercial_name', 'is_airbnb',
            'trigramme', 'mode_paiement_airbnb', 'statut_airbnb', 'eligible_conciergerie'
        ]

    def get_is_airbnb(self, obj):
        return obj.is_airbnb_client()

    def get_assigned_commercial_name(self, obj):
        return obj.assigned_commercial.full_name if obj.assigned_commercial else None

    def get_demandes_count(self, obj):
        return obj.demandes.filter(parent_demande__isnull=True).count()

    def get_latest_demande(self, obj):
        latest = obj.demandes.order_by('-created_at').first()
        if latest:
            fact = latest.formulaire_data.get('facturation', {}) if isinstance(latest.formulaire_data, dict) else {}
            facturation_annulee = fact.get('facturation_annulee', False)
            statut_paiement_ui = fact.get('statut_paiement_ui')
            
            if facturation_annulee and latest.statut == 'annule' and not fact.get('annulation_raison'):
                facturation_annulee = False
                if statut_paiement_ui == 'facturation_annulee':
                    statut_paiement_ui = 'annule'

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

