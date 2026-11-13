from rest_framework import serializers
from .models import Facture, Paiement, EntreeCaisse


class PaiementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paiement
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']


class FactureSerializer(serializers.ModelSerializer):
    paiements = PaiementSerializer(many=True, read_only=True)
    reste_a_payer = serializers.ReadOnlyField()
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    annulee_par_name = serializers.SerializerMethodField()

    class Meta:
        model = Facture
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']

    def get_annulee_par_name(self, obj):
        return obj.annulee_par.full_name if obj.annulee_par else None


class EntreeCaisseSerializer(serializers.ModelSerializer):
    client_display = serializers.ReadOnlyField()
    mode_paiement_display = serializers.CharField(source='get_mode_paiement_display', read_only=True)
    type_mouvement_display = serializers.CharField(source='get_type_mouvement_display', read_only=True)

    class Meta:
        model = EntreeCaisse
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']
