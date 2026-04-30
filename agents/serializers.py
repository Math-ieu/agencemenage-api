from django.db import models
from rest_framework import serializers
from .models import Agent, AgentExperience
from demandes.models import Demande


class AgentExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentExperience
        fields = [
            'id', 'position', 'company', 'duration', 'duration_text', 
            'work_locations', 'tasks', 'has_allergies', 'description'
        ]


class AgentSerializer(serializers.ModelSerializer):
    experiences = AgentExperienceSerializer(many=True, required=False)
    average_rating = serializers.ReadOnlyField()
    is_assigned_active = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = '__all__'

    def get_is_assigned_active(self, obj):
        """True si l'agent est affecté (via profils_envoyes) à une demande active."""
        active_statuts = [Demande.EN_ATTENTE, Demande.ENCOURS, Demande.PRES_EN_COURS]
        return Demande.objects.filter(
            profils_envoyes=obj,
            statut__in=active_statuts
        ).exists()

    def _cleanup_form_data(self, request, validated_data):
        import json
        from django.db import models
        
        # 1. Handle JSON strings from FormData (languages)
        languages_json = request.data.get('languages')
        if languages_json and isinstance(languages_json, str):
            try:
                validated_data['languages'] = json.loads(languages_json)
            except json.JSONDecodeError:
                pass
            
        # 2. Handle Boolean strings from FormData ("true"/"false")
        for field in Agent._meta.get_fields():
            if isinstance(field, models.BooleanField):
                val = request.data.get(field.name)
                if val is not None and isinstance(val, str):
                    validated_data[field.name] = val.lower() == 'true'

        # 3. Handle empty strings for Date fields and Integer fields
        for field in Agent._meta.get_fields():
            if isinstance(field, (models.DateField, models.IntegerField, models.PositiveIntegerField)):
                val = validated_data.get(field.name)
                if val == '':
                    validated_data[field.name] = None

        # 4. Handle experiences_json
        experiences_json = request.data.get('experiences_json')
        experiences_data = validated_data.pop('experiences', [])
        
        if not experiences_data and experiences_json:
            try:
                experiences_data = json.loads(experiences_json)
            except json.JSONDecodeError:
                pass
        
        return experiences_data

    def create(self, validated_data):
        request = self.context.get('request')
        experiences_data = []
        if request:
            experiences_data = self._cleanup_form_data(request, validated_data)
            
        agent = Agent.objects.create(**validated_data)
        
        for exp_data in experiences_data:
            AgentExperience.objects.create(agent=agent, **exp_data)
            
        return agent

    def update(self, instance, validated_data):
        request = self.context.get('request')
        experiences_data = None
        if request:
            experiences_data = self._cleanup_form_data(request, validated_data)
        
        # If 'experiences' was NOT in the payload (None), we don't touch them.
        # But if it was passed (even empty list), we sync them.
        # Note: _cleanup_form_data pops 'experiences' from validated_data.
        
        instance = super().update(instance, validated_data)
        
        if experiences_data is not None:
            instance.experiences.all().delete()
            for exp_data in experiences_data:
                AgentExperience.objects.create(agent=instance, **exp_data)
        
        return instance


class AgentListSerializer(serializers.ModelSerializer):
    average_rating = serializers.ReadOnlyField()
    class Meta:
        model = Agent
        fields = [
            'id', 'uuid', 'first_name', 'last_name', 'full_name', 'phone', 'whatsapp',
            'poste', 'statut', 'city', 'neighborhood', 'experience', 
            'languages', 'nationality', 'cin', 'situation', 'photo', 'created_at', 'average_rating'
        ]
