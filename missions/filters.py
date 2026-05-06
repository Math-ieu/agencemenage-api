import django_filters
from .models import Mission

class MissionFilter(django_filters.FilterSet):
    client = django_filters.NumberFilter(field_name="demande__client")

    class Meta:
        model = Mission
        fields = ['statut', 'agent', 'delegue', 'intervenants', 'demande', 'client']
