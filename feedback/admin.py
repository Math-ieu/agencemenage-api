from django.contrib import admin
from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['mission', 'client', 'note', 'date', 'source']
    list_filter = ['note', 'source', 'date']
    search_fields = ['commentaire', 'mission__service', 'client__first_name', 'client__last_name']
    readonly_fields = ['date']
    raw_id_fields = ['mission', 'client']
