import django_filters
from django.db.models import Q, OuterRef, Subquery
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
        from demandes.models import Demande
        
        # Subquery to fetch the latest demand for each client
        latest_demande_subquery = Demande.objects.filter(client=OuterRef('pk')).order_by('-created_at')
        
        # Annotate each client with the fields of their latest demand
        queryset = queryset.annotate(
            latest_demande_statut=Subquery(latest_demande_subquery.values('statut')[:1]),
            latest_demande_cao=Subquery(latest_demande_subquery.values('cao')[:1]),
            latest_demande_statut_paiement=Subquery(latest_demande_subquery.values('statut_paiement')[:1]),
            latest_demande_facturation_annulee=Subquery(latest_demande_subquery.values('formulaire_data__facturation__facturation_annulee')[:1])
        )

        if value == 'en_attente':
            return queryset.filter(latest_demande_statut='en_attente')
            
        elif value == 'nouveau_besoin':
            return queryset.filter(latest_demande_statut='en_cours', latest_demande_cao=False)
            
        elif value == 'confirme':
            return queryset.filter(Q(latest_demande_statut='en_cours', latest_demande_cao=True) | Q(latest_demande_statut='termine'))
            
        elif value == 'pres_en_cours':
            return queryset.filter(latest_demande_statut='pres_en_cours')
            
        elif value == 'pres_terminee':
            return queryset.filter(latest_demande_statut='pres_terminee')
            
        elif value == 'annule':
            return queryset.filter(latest_demande_statut='annule')
            
        elif value == 'paye':
            return queryset.filter(latest_demande_statut_paiement='integral').exclude(latest_demande_facturation_annulee=True)
            
        elif value == 'facturation_encours':
            return queryset.filter(latest_demande_statut_paiement='acompte').exclude(latest_demande_facturation_annulee=True)
            
        elif value == 'facturation_partielle':
            return queryset.filter(latest_demande_statut_paiement='partiel').exclude(latest_demande_facturation_annulee=True)
            
        elif value == 'facturation_annulee':
            return queryset.filter(Q(latest_demande_statut_paiement='facturation_annulee') | Q(latest_demande_facturation_annulee=True))

        return queryset


