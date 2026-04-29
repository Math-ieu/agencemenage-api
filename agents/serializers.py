from django.db import models
from rest_framework import serializers
from .models import Agent, AgentExperience


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

    class Meta:
        model = Agent
        fields = '__all__'

    def create(self, validated_data):
        request = self.context.get('request')
        if not request:
            return super().create(validated_data)
            
        # Handle JSON strings from FormData
        experiences_json = request.data.get('experiences_json')
        languages_json = request.data.get('languages')
        
        if languages_json and isinstance(languages_json, str):
            import json
            try:
                validated_data['languages'] = json.loads(languages_json)
            except json.JSONDecodeError:
                pass
            
        # Handle Boolean strings from FormData
        for field in Agent._meta.get_fields():
            if isinstance(field, models.BooleanField):
                val = request.data.get(field.name)
                if val is not None and isinstance(val, str):
                    validated_data[field.name] = val.lower() == 'true'

        experiences_data = validated_data.pop('experiences', [])
        if not experiences_data and experiences_json:
            import json
            try:
                experiences_data = json.loads(experiences_json)
            except json.JSONDecodeError:
                pass
            
        # Files are automatically in request.FILES and should be in validated_data 
        # because the views use the default parsers (MultiPartParser).
        agent = Agent.objects.create(**validated_data)
        
        for exp_data in experiences_data:
            AgentExperience.objects.create(agent=agent, **exp_data)
            
        return agent

    def update(self, instance, validated_data):
        experiences_data = validated_data.pop('experiences', None)
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
