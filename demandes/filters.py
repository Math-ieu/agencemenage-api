import django_filters
from .models import Demande

class DemandeFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="created_at", lookup_expr='gte')
    date_fin = django_filters.DateFilter(field_name="created_at", lookup_expr='lte')
    commercial = django_filters.CharFilter(field_name="assigned_to__id")
    exclude_statut = django_filters.CharFilter(field_name='statut', exclude=True)

    class Meta:
        model = Demande
        fields = ['statut', 'segment', 'source', 'service', 'assigned_to', 'statut_paiement', 'commercial', 'client']
