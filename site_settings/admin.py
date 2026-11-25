from django.contrib import admin
from .models import SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'phone_mobile_1',
        'email_contact',
        'marrakech_status',
        'promo_banner_enabled',
        'promo_banner_code',
        'updated_at',
    )
