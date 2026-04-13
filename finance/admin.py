from django.contrib import admin
from .models import Facture, Paiement, EntreeCaisse


class PaiementInline(admin.TabularInline):
    model = Paiement
    extra = 0
    readonly_fields = ['created_at', 'created_by']


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ['numero', 'client', 'montant_total', 'montant_paye', 'statut', 'date_emission']
    list_filter = ['statut', 'date_emission']
    search_fields = ['numero', 'client__first_name', 'client__last_name', 'client__entity_name']
    inlines = [PaiementInline]
    raw_id_fields = ['client', 'demande', 'created_by']
    readonly_fields = ['created_at']


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ['facture', 'montant', 'mode', 'date', 'reference']
    list_filter = ['mode', 'date']
    search_fields = ['reference', 'facture__numero', 'notes']
    raw_id_fields = ['facture', 'created_by']
    readonly_fields = ['created_at']


@admin.register(EntreeCaisse)
class EntreeCaisseAdmin(admin.ModelAdmin):
    list_display = ['date', 'type_mouvement', 'montant', 'mode_paiement', 'client_nom', 'description', 'created_by']
    list_filter = ['type_mouvement', 'mode_paiement', 'date']
    search_fields = ['description', 'client_nom', 'utilisateur']
    raw_id_fields = ['client', 'paiement', 'created_by']
    readonly_fields = ['created_at']
