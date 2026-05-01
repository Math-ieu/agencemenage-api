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

    def to_internal_value(self, data):
        import json
        from django.db import models
        
        # Make data mutable if it's a QueryDict
        mutable_data = data.copy() if hasattr(data, 'copy') else data
        
        # 1. Handle JSON strings from FormData (languages)
        languages_json = mutable_data.get('languages')
        if languages_json and isinstance(languages_json, str):
            try:
                mutable_data['languages'] = json.loads(languages_json)
            except json.JSONDecodeError:
                pass
            
        # 2. Handle Boolean strings from FormData ("true"/"false")
        for field in Agent._meta.get_fields():
            if isinstance(field, models.BooleanField):
                val = mutable_data.get(field.name)
                if val is not None and isinstance(val, str):
                    mutable_data[field.name] = val.lower() == 'true'

        # 3. Handle empty strings for Date fields and Integer fields
        for field in Agent._meta.get_fields():
            if isinstance(field, (models.DateField, models.IntegerField, models.PositiveIntegerField)):
                val = mutable_data.get(field.name)
                if val == '':
                    mutable_data[field.name] = None
                    
        return super().to_internal_value(mutable_data)

    def _get_experiences_data(self, request):
        import json
        experiences_json = request.data.get('experiences_json')
        if experiences_json:
            try:
                return json.loads(experiences_json)
            except json.JSONDecodeError:
                pass
        return []

    def create(self, validated_data):
        request = self.context.get('request')
        experiences_data = self._get_experiences_data(request) if request else []
            
        agent = Agent.objects.create(**validated_data)
        
        for exp_data in experiences_data:
            AgentExperience.objects.create(agent=agent, **exp_data)
            
        return agent

    def update(self, instance, validated_data):
        request = self.context.get('request')
        experiences_data = self._get_experiences_data(request) if request else None
        
        instance = super().update(instance, validated_data)
        
        # If experiences_json was passed (even empty list), we sync them.
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
