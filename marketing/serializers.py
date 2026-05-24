from rest_framework import serializers
from .models import PromoCode, CommercialGesture, Campaign

class PromoCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromoCode
        fields = '__all__'

class CommercialGestureSerializer(serializers.ModelSerializer):
    commercial_name = serializers.CharField(source='cree_par.full_name', read_only=True)
    client_name = serializers.CharField(source='client.display_name', read_only=True)
    
    class Meta:
        model = CommercialGesture
        fields = '__all__'

class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = '__all__'
