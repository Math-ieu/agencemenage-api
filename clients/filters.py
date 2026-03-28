import django_filters
from .models import Client

class ClientFilter(django_filters.FilterSet):
    date_debut = django_filters.DateFilter(field_name="created_at", lookup_expr='gte')
    date_fin = django_filters.DateFilter(field_name="created_at", lookup_expr='lte')
    commercial = django_filters.CharFilter(field_name="demandes__assigned_to__id", distinct=True)
    service = django_filters.CharFilter(field_name="demandes__service", lookup_expr='iexact', distinct=True)
    
    # Allows filtering clients based on the status of their demands
    statut = django_filters.CharFilter(method='filter_by_statut_or_paiement')

    class Meta:
        model = Client
        fields = ['segment', 'city']

    def filter_by_statut_or_paiement(self, queryset, name, value):
        if value in ['confirme', 'en_cours', 'termine']:
            # 'confirme' might map to en_cours in frontend terminology, or we can just exact match
            # "confirme" isn't a strict DB status, usually it's "en_cours" or "termine"
            # In Clients.tsx tabs: 'tout', 'confirme', 'annule', 'paye', 'facturation_encours', 'facturation_partielle', 'facturation'
            if value == 'confirme':
                return queryset.filter(demandes__statut__in=['en_cours', 'termine']).distinct()
            return queryset.filter(demandes__statut=value).distinct()
        
        elif value == 'annule':
            return queryset.filter(demandes__statut='annule').distinct()
            
        elif value == 'paye':
            return queryset.filter(demandes__statut_paiement='integral').distinct()
            
        elif value == 'facturation_encours':
            return queryset.filter(demandes__statut_paiement='acompte').distinct()
            
        elif value == 'facturation_partielle':
            return queryset.filter(demandes__statut_paiement='partiel').distinct()
            
        elif value == 'facturation':
            return queryset.filter(demandes__statut_paiement__in=['acompte', 'partiel']).distinct()

        return queryset
