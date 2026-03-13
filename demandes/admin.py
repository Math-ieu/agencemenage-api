from django.contrib import admin
from .models import Demande, NRPLog, Document, AuditLog


class NRPLogInline(admin.TabularInline):
    model = NRPLog
    extra = 0
    readonly_fields = ['commercial', 'date']


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0
    readonly_fields = ['created_at', 'created_by']


@admin.register(Demande)
class DemandeAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'service', 'segment', 'statut', 'source', 'assigned_to', 'created_at']
    list_filter = ['statut', 'segment', 'source', 'service']
    search_fields = ['client__first_name', 'client__last_name', 'client__entity_name', 'service']
    ordering = ['-created_at']
    inlines = [NRPLogInline, DocumentInline]
    raw_id_fields = ['client', 'assigned_to']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'model_name', 'object_id', 'user', 'timestamp']
    list_filter = ['model_name', 'action']
    ordering = ['-timestamp']
    readonly_fields = ['user', 'action', 'model_name', 'object_id', 'extra_data', 'timestamp']
