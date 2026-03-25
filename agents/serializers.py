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

    class Meta:
        model = Agent
        fields = '__all__'

    def create(self, validated_data):
        experiences_json = self.context['request'].data.get('experiences_json')
        languages_json = self.context['request'].data.get('languages')
        
        if languages_json and isinstance(languages_json, str):
            import json
            validated_data['languages'] = json.loads(languages_json)
            
        experiences_data = validated_data.pop('experiences', [])
        if not experiences_data and experiences_json:
            import json
            experiences_data = json.loads(experiences_json)
            
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
    class Meta:
        model = Agent
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'phone', 'whatsapp',
            'poste', 'statut', 'city', 'neighborhood', 'experience', 
            'languages', 'nationality', 'cin', 'situation', 'photo', 'created_at'
        ]
