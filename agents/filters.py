import django_filters
from .models import Agent

class AgentFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="created_at", lookup_expr='gte')
    date_fin = django_filters.DateFilter(field_name="created_at", lookup_expr='lte')

    class Meta:
        model = Agent
        fields = ['statut', 'poste', 'city']
