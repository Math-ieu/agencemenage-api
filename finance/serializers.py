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

    class Meta:
        model = Facture
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']


class EntreeCaisseSerializer(serializers.ModelSerializer):
    class Meta:
        model = EntreeCaisse
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']
