from django.contrib import admin
from .models import AirbnbConfig, Bien, CommandeAirbnb, FiletLinge, ObjetTrouve


@admin.register(AirbnbConfig)
class AirbnbConfigAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'prix_studio', 'prix_2ch', 'prix_3ch', 'supplement_zone_eloignee', 'prix_set_linge_standard', 'updated_at']


@admin.register(Bien)
class BienAdmin(admin.ModelAdmin):
    list_display = ['code', 'nom_bien', 'client', 'ville', 'quartier', 'typologie', 'zone_eloignee', 'is_active', 'created_at']
    list_filter = ['typologie', 'zone_eloignee', 'is_active', 'ville']
    search_fields = ['code', 'nom_bien', 'quartier', 'adresse', 'client__first_name', 'client__last_name', 'client__entity_name']


@admin.register(CommandeAirbnb)
class CommandeAirbnbAdmin(admin.ModelAdmin):
    list_display = ['numero', 'bien', 'date_prestation', 'heure_prestation', 'creneau', 'statut', 'total_ttc', 'intervenante', 'created_at']
    list_filter = ['statut', 'creneau', 'nature_linge', 'source', 'date_prestation']
    search_fields = ['numero', 'bien__code', 'bien__nom_bien', 'bien__client__first_name', 'bien__client__last_name']
    date_hierarchy = 'date_prestation'


@admin.register(FiletLinge)
class FiletLingeAdmin(admin.ModelAdmin):
    list_display = ['code_filet', 'bien', 'statut', 'total_pieces', 'sets_calcules', 'pieces_supp_calculees', 'montant', 'montant_fige_le', 'created_at']
    list_filter = ['statut', 'ecart_arbitre']
    search_fields = ['code_filet', 'bien__code']


@admin.register(ObjetTrouve)
class ObjetTrouveAdmin(admin.ModelAdmin):
    list_display = ['description', 'bien', 'commande', 'piece', 'statut', 'created_at', 'remis_a']
    list_filter = ['statut', 'created_at']
    search_fields = ['description', 'piece', 'bien__code', 'remis_a']
