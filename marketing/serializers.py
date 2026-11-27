from rest_framework import serializers
from .models import PromoCode, CommercialGesture, Campaign

FORBIDDEN_DEMO_PROMO_CODES = {"DEMO-BF26", "DEMO-NY27"}


class PromoCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromoCode
        fields = '__all__'

    def validate_code(self, value):
        cleaned = (value or "").strip()
        if cleaned.upper() in FORBIDDEN_DEMO_PROMO_CODES:
            raise serializers.ValidationError(
                "Les codes de démonstration (DEMO-BF26, DEMO-NY27) sont interdits et ne peuvent pas être utilisés en production."
            )
        return cleaned

    def validate_villes(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Le champ villes doit être une liste.")
        return value

    def validate_modes_reservation(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Le champ modes_reservation doit être une liste.")
        return value

    def validate_minimum_commande(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "Le montant minimum de commande ne peut pas être négatif."
            )
        return value

    def validate_plafond_reduction(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "Le plafond de réduction ne peut pas être négatif."
            )
        return value

    def validate(self, attrs):
        code = attrs.get("code", getattr(self.instance, "code", ""))
        cleaned_code = (code or "").strip()
        if cleaned_code.upper() in FORBIDDEN_DEMO_PROMO_CODES:
            raise serializers.ValidationError({
                "code": (
                    "Les codes de démonstration (DEMO-BF26, DEMO-NY27) sont interdits "
                    "et ne peuvent pas être utilisés en production."
                )
            })
        return attrs


class CommercialGestureSerializer(serializers.ModelSerializer):
    commercial_name = serializers.CharField(source='cree_par.full_name', read_only=True)
    client_name = serializers.CharField(source='client.display_name', read_only=True)

    class Meta:
        model = CommercialGesture
        fields = '__all__'
        read_only_fields = ['cree_par']

    def validate_part_profil(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("La part profil ne peut pas être négative.")
        return value

    def validate(self, attrs):
        reduction_type = attrs.get('reduction_type', getattr(self.instance, 'reduction_type', None))
        reduction_value = attrs.get('reduction_value', getattr(self.instance, 'reduction_value', None))
        if reduction_value is not None:
            if reduction_value < 0:
                raise serializers.ValidationError({'reduction_value': "La réduction ne peut pas être négative."})
            if reduction_type == 'pourcentage' and reduction_value > 100:
                raise serializers.ValidationError({'reduction_value': "Une réduction en pourcentage ne peut pas dépasser 100 %."})
        return attrs


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = '__all__'
