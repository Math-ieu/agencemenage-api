from rest_framework import serializers
from .models import Mission
from agents.serializers import AgentListSerializer
from demandes.serializers import DemandeListSerializer


class MissionSerializer(serializers.ModelSerializer):
    agent_detail = AgentListSerializer(source='agent', read_only=True)
    demande_detail = DemandeListSerializer(source='demande', read_only=True)
    delegue_detail = AgentListSerializer(source='delegue', read_only=True)
    intervenants_detail = AgentListSerializer(source='intervenants', many=True, read_only=True)

    class Meta:
        model = Mission
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'created_by']
