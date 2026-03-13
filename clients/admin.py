from django.contrib import admin
from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'segment', 'phone', 'email', 'city', 'created_at']
    list_filter = ['segment', 'city']
    search_fields = ['first_name', 'last_name', 'entity_name', 'phone', 'email']
    ordering = ['-created_at']
