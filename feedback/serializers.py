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
            return obj.demande.client.display_name if obj.demande.client else obj.demande.formulaire_data.get('nom', 'Client')
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
        if obj.client and obj.client.city:
            return obj.client.city
        if obj.demande:
            if obj.demande.client and obj.demande.client.city:
                return obj.demande.client.city
            return obj.demande.formulaire_data.get('ville', '—')
        return "—"

    def get_neighborhood(self, obj):
        if obj.client and obj.client.neighborhood:
            return obj.client.neighborhood
        if obj.demande:
            if obj.demande.client and obj.demande.client.neighborhood:
                return obj.demande.client.neighborhood
            return obj.demande.formulaire_data.get('quartier', '—')
        return "—"

    def get_date_prestation(self, obj):
        if obj.demande:
            return obj.demande.date_intervention
        return None


class PublicFeedbackCreateSerializer(serializers.ModelSerializer):
    """Serializer public restreint pour la soumission d'avis client via jeton signé."""
    token = serializers.CharField(write_only=True, required=True)
    note_intervenant = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    note_agence = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    commentaire = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')

    class Meta:
        model = Feedback
        fields = ['token', 'note_intervenant', 'note_agence', 'commentaire', 'opt_out']

    def validate(self, attrs):
        from agencemenage.utils import verify_feedback_token
        from demandes.models import Demande

        token = attrs.pop('token', None)
        demande_id = verify_feedback_token(token)
        if not demande_id:
            raise serializers.ValidationError({'token': "Lien de feedback invalide ou expiré."})

        demande = Demande.objects.select_related('client').filter(pk=demande_id).first()
        if not demande:
            raise serializers.ValidationError({'token': "Lien de feedback invalide ou expiré."})

        if Feedback.objects.filter(demande=demande, source='client').exists():
            raise serializers.ValidationError({'demande': "Un avis a déjà été soumis pour cette prestation."})

        attrs['demande'] = demande
        return attrs
