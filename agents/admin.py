from django.contrib import admin
from .models import Agent, AgentExperience


class AgentExperienceInline(admin.TabularInline):
    model = AgentExperience
    extra = 0
    fields = ['position', 'company', 'duration']


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'poste', 'statut', 'phone', 'city', 'created_at']
    list_filter = ['statut', 'poste', 'city']
    search_fields = ['first_name', 'last_name', 'phone']
    ordering = ['last_name', 'first_name']
    inlines = [AgentExperienceInline]
