from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers
from agencemenage.validators import validate_uploaded_document
from .models import Facture, Paiement, EntreeCaisse


class PaiementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paiement
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']

    def validate_montant(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Le montant du paiement doit être strictement positif.")
        return value


class FactureSerializer(serializers.ModelSerializer):
    paiements = PaiementSerializer(many=True, read_only=True)
    reste_a_payer = serializers.ReadOnlyField()
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    annulee_par_name = serializers.SerializerMethodField()

    class Meta:
        model = Facture
        fields = '__all__'
        read_only_fields = ['created_at', 'created_by']

    def validate_montant_total(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Le montant total ne peut pas être négatif.")
        return value

    def validate_montant_paye(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Le montant payé ne peut pas être négatif.")
        return value

    def validate_pdf_file(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_document(value)
        return value

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

    def validate_montant(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Le montant du mouvement doit être strictement positif.")
        return value

    def validate_document_file(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_document(value)
        return value
