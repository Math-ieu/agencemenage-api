import django_filters
from django.db import models
from .models import Agent

class AgentFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="created_at", lookup_expr='gte')
    date_fin = django_filters.DateFilter(field_name="created_at", lookup_expr='lte')
    
    # Custom filters
    disponibilite_type = django_filters.CharFilter(method='filter_disponibilite_type')
    segment = django_filters.CharFilter(method='filter_segment')
    jour_dispo = django_filters.CharFilter(method='filter_jour_dispo')
    is_smoking = django_filters.BooleanFilter()

    class Meta:
        model = Agent
        fields = ['statut', 'disponibilite_intervention', 'poste', 'city', 'type_profil']

    def filter_disponibilite_type(self, queryset, name, value):
        if value == 'urgences':
            return queryset.filter(avail_emergencies=True)
        elif value == 'soiree':
            return queryset.filter(avail_evening=True)
        elif value == 'feries':
            return queryset.filter(avail_holidays=True)
        return queryset

    def filter_segment(self, queryset, name, value):
        if value == 'particulier':
            return queryset.filter(
                models.Q(experiences__isnull=True) |
                models.Q(experiences__work_locations__icontains='Villa') |
                models.Q(experiences__work_locations__icontains='Appartement') |
                models.Q(experiences__work_locations__icontains='Duplex')
            ).distinct()
        elif value == 'entreprise':
            return queryset.filter(
                models.Q(experiences__isnull=True) |
                models.Q(experiences__work_locations__icontains='Entreprise') |
                models.Q(experiences__work_locations__icontains='Hôtel') |
                models.Q(experiences__work_locations__icontains='Riad')
            ).distinct()
        return queryset

    def filter_jour_dispo(self, queryset, name, value):
        value = value.lower()
        if value in ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']:
            lookup = f"availability_calendar__{value}__active"
            return queryset.filter(**{lookup: True})
        return queryset
