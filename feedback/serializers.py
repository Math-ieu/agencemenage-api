from rest_framework import serializers
from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    agent_name = serializers.SerializerMethodField()
    agent_id = serializers.SerializerMethodField()
    service = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    neighborhood = serializers.SerializerMethodField()
    segment = serializers.SerializerMethodField()
    date_prestation = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = [
            'id', 'demande', 'client', 'note_intervenant', 'note_agence', 
            'commentaire', 'opt_out', 'date', 'source',
            'client_name', 'agent_name', 'agent_id', 'service', 
            'city', 'neighborhood', 'segment', 'date_prestation'
        ]
        read_only_fields = ['date']

    def get_client_name(self, obj):
        if obj.client:
            return obj.client.display_name
        if obj.demande:
            return obj.demande.client_name or obj.demande.formulaire_data.get('nom', 'Client')
        return "Client"

    def _get_agent(self, obj):
        if obj.demande:
            return obj.demande.profils_envoyes.last()
        return None

    def get_agent_name(self, obj):
        agent = self._get_agent(obj)
        return f"{agent.first_name} {agent.last_name}" if agent else "—"

    def get_agent_id(self, obj):
        agent = self._get_agent(obj)
        return agent.pk if agent else None

    def get_service(self, obj):
        return obj.demande.service if obj.demande else "—"

    def get_segment(self, obj):
        return obj.demande.segment if obj.demande else "particulier"

    def get_city(self, obj):
        return obj.demande.neighborhood_city.split(',')[-1].strip() if obj.demande and obj.demande.neighborhood_city else "—"

    def get_neighborhood(self, obj):
        return obj.demande.neighborhood_city.split(',')[0].strip() if obj.demande and obj.demande.neighborhood_city else "—"

    def get_date_prestation(self, obj):
        if obj.demande:
            return obj.demande.date_intervention
        return None
