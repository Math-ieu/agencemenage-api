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

    class Meta:
        model = Client
        fields = ['id', 'display_name', 'first_name', 'last_name', 'entity_name',
                  'phone', 'email', 'segment', 'city', 'neighborhood', 'created_at']
