import re
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from agencemenage.validators import validate_uploaded_document, validate_uploaded_image
from .models import Agent, AgentExperience, AgentAssignment
from demandes.models import Demande


EVAL_NOTE_LINE_RE = re.compile(r'^\[\d{2}/\d{2}/\d{4}\]\s*[EÉeé]valuation:', re.IGNORECASE)
ALLOWED_EXPERIENCE_KEYS = {
    'position', 'company', 'duration', 'duration_text',
    'work_locations', 'tasks', 'has_allergies', 'description',
}


def _mask_cin(value: str) -> str:
    cleaned = (value or '').strip()
    if not cleaned:
        return ''
    if len(cleaned) <= 4:
        return '*' * len(cleaned)
    return f"{cleaned[:2]}{'*' * (len(cleaned) - 4)}{cleaned[-2:]}"


class PublicAgentProfileSerializer(serializers.ModelSerializer):
    """Serializer strictement minimal pour l'affichage public via lien de partage."""
    cin = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()
    poste_display = serializers.CharField(source='get_poste_display', read_only=True)
    operator_notes = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = [
            'first_name', 'cin', 'nationality', 'age',
            'photo', 'poste_display', 'experience_years', 'operator_notes',
        ]
        read_only_fields = fields

    def get_cin(self, obj):
        return _mask_cin(getattr(obj, 'cin', ''))

    def get_age(self, obj):
        if not obj.birth_date:
            return 0
        today = timezone.localdate()
        age = today.year - obj.birth_date.year
        if (today.month, today.day) < (obj.birth_date.month, obj.birth_date.day):
            age -= 1
        return max(0, age)

    def get_photo(self, obj):
        field_name = obj.active_photo if obj.active_photo in ('photo', 'photo2') else 'photo'
        file_field = getattr(obj, field_name, None) or obj.photo
        if not file_field:
            return None
        try:
            url = file_field.url
        except Exception:
            return None
        request = self.context.get('request')
        if request and url and not url.startswith(('http://', 'https://')):
            return request.build_absolute_uri(url)
        return url

    def get_operator_notes(self, obj):
        if not obj.operator_notes:
            return ''
        lines = [
            line for line in obj.operator_notes.splitlines()
            if not EVAL_NOTE_LINE_RE.match(line.strip())
        ]
        return '\n'.join(lines).strip()


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
    assigned_to_name = serializers.ReadOnlyField(source='assigned_to.full_name', default=None)

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
        from rest_framework import serializers
        
        # Make data mutable
        if hasattr(data, 'dict'):
            mutable_data = data.dict()
        else:
            mutable_data = data.copy() if hasattr(data, 'copy') else data

        # 1. Handle JSON strings from FormData (languages, availability_calendar)
        languages_json = mutable_data.get('languages')
        if languages_json and isinstance(languages_json, str):
            try:
                mutable_data['languages'] = json.loads(languages_json)
            except json.JSONDecodeError:
                pass

        availability_calendar_json = mutable_data.get('availability_calendar')
        if availability_calendar_json and isinstance(availability_calendar_json, str):
            try:
                mutable_data['availability_calendar'] = json.loads(availability_calendar_json)
            except json.JSONDecodeError:
                pass
            
        # 2. Handle empty/null/undefined strings for Date and Integer fields
        for field in Agent._meta.fields:
            if field.name not in mutable_data:
                continue
                
            val = mutable_data.get(field.name)
            if isinstance(field, (models.DateField, models.IntegerField, models.PositiveIntegerField, models.FileField, models.ImageField)):
                if val in ('', 'null', 'undefined'):
                    mutable_data[field.name] = None
            elif isinstance(field, models.BooleanField):
                if val in ('', 'null', 'undefined'):
                    mutable_data[field.name] = False
                elif isinstance(val, str):
                    mutable_data[field.name] = val.lower() in ('true', '1', 'yes')

        # 3. Handle categorie safely to prevent choices validation 400 Bad Request
        if 'categorie' in mutable_data:
            cat = mutable_data.get('categorie')
            if cat in ('', 'null', 'undefined', None):
                mutable_data['categorie'] = 'externe'
            elif isinstance(cat, str):
                cat_clean = cat.strip().lower()
                mutable_data['categorie'] = cat_clean if cat_clean in ('interne', 'externe') else 'externe'

        # 4. Handle type_profil safely
        if 'type_profil' in mutable_data:
            tp = mutable_data.get('type_profil')
            if tp in ('null', 'undefined', None):
                mutable_data['type_profil'] = ''

        return super().to_internal_value(mutable_data)
    def _validate_image_upload(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_image(value)
        return value

    def _validate_doc_upload(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_document(value)
        return value

    def validate_photo(self, value):
        return self._validate_image_upload(value)

    def validate_photo2(self, value):
        return self._validate_image_upload(value)

    def validate_photo3(self, value):
        return self._validate_image_upload(value)

    def validate_cin_file(self, value):
        return self._validate_doc_upload(value)

    def validate_cin_verso_file(self, value):
        return self._validate_doc_upload(value)

    def validate_attestation_file(self, value):
        return self._validate_doc_upload(value)

    def validate_fiche_antropometrique(self, value):
        return self._validate_doc_upload(value)

    def validate(self, attrs):
        wants_blacklist = (
            attrs.get('is_blacklisted') is True
            or attrs.get('statut') == 'blacklist'
        )
        was_blacklisted = bool(
            self.instance and (self.instance.is_blacklisted or self.instance.statut == 'blacklist')
        )
        if wants_blacklist and not was_blacklisted:
            request = self.context.get('request') if self.context else None
            user = getattr(request, 'user', None)
            if user and getattr(user, 'is_authenticated', False) and getattr(user, 'role', None) != 'admin':
                from accounts.models import RolePermission
                from accounts.permissions import map_role_to_db_key
                db_role = map_role_to_db_key(user.role)
                rp = RolePermission.objects.filter(role=db_role).first()
                perms = rp.permissions if rp else []
                if 'blacklister_agents' not in perms:
                    raise PermissionDenied("Vous n'avez pas l'autorisation de blacklister un profil.")
        return attrs

    def _get_experiences_data(self, request):
        import json
        if not request or 'experiences_json' not in request.data:
            return None
        experiences_json = request.data.get('experiences_json')
        if experiences_json in (None, ''):
            return []
        try:
            parsed = json.loads(experiences_json)
            if not isinstance(parsed, list):
                return []
            return [
                {k: v for k, v in item.items() if k in ALLOWED_EXPERIENCE_KEYS}
                for item in parsed
                if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            return []

    def create(self, validated_data):
        request = self.context.get('request')
        experiences_data = self._get_experiences_data(request) or []
        
        if request and request.user and not validated_data.get('assigned_to'):
            validated_data['assigned_to'] = request.user
            
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
    assigned_to_name = serializers.ReadOnlyField(source='assigned_to.full_name', default=None)
    
    class Meta:
        model = Agent
        fields = [
            'id', 'uuid', 'first_name', 'last_name', 'full_name', 'phone', 'whatsapp',
            'poste', 'statut', 'disponibilite_intervention', 'city', 'neighborhood', 'experience', 
            'languages', 'nationality', 'cin', 'situation', 'photo', 'created_at', 'average_rating', 'is_blacklisted',
            'type_profil', 'categorie',
            'assigned_to', 'assigned_to_name'
        ]


class AgentAssignmentSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.ReadOnlyField(source='assigned_to.full_name', default='Non affecté')
    assigned_by_name_display = serializers.SerializerMethodField()

    class Meta:
        model = AgentAssignment
        fields = [
            'id', 'assigned_to', 'assigned_to_name', 'assigned_by', 
            'assigned_by_name_display', 'notes', 'created_at'
        ]

    def get_assigned_by_name_display(self, obj):
        if obj.assigned_by_name:
            return obj.assigned_by_name
        return obj.assigned_by.full_name if obj.assigned_by else '—'

