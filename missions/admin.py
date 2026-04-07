from django.contrib import admin
from .models import Mission


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ['agent', 'demande', 'statut', 'date_debut', 'created_at']
    list_filter = ['statut', 'date_debut']
    search_fields = ['agent__first_name', 'agent__last_name', 'demande__service']
    raw_id_fields = ['demande', 'agent', 'created_by']
    readonly_fields = ['created_at', 'updated_at']
