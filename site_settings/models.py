import uuid
from django.db import models


MARRAKECH_STATUS_CHOICES = [
    ('coming_soon', 'Ouverture en préparation'),
    ('active', 'Service ouvert'),
    ('hidden', 'Masqué'),
]

PROMO_BANNER_AUDIENCE_CHOICES = [
    ('all', 'Tous'),
    ('particulier', 'Particuliers'),
    ('entreprise', 'Entreprises'),
]

DEFAULT_MARRAKECH_SERVICES = {
    'menage_standard': False,
    'grand_menage': False,
    'menage_airbnb': False,
    'fin_chantier': False,
    'garde_malade': False,
    'post_sinistre': False,
    'entreprises': False,
    'airbnb_linge': False,
}


def default_marrakech_services():
    return dict(DEFAULT_MARRAKECH_SERVICES)


class SiteConfig(models.Model):
    """
    Configuration globale des coordonnées et informations affichées sur le site web.
    Modèle singleton.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Téléphones
    phone_mobile_1 = models.CharField(
        max_length=50,
        default="06 64 22 67 90",
        blank=True,
        verbose_name="Téléphone mobile 1 (affichage)"
    )
    phone_mobile_1_intl = models.CharField(
        max_length=50,
        default="+212664226790",
        blank=True,
        verbose_name="Téléphone mobile 1 (format appel tel:+212...)"
    )
    phone_mobile_2 = models.CharField(
        max_length=50,
        default="06 64 33 14 63",
        blank=True,
        verbose_name="Téléphone mobile 2 (affichage)"
    )
    phone_mobile_2_intl = models.CharField(
        max_length=50,
        default="+212664331463",
        blank=True,
        verbose_name="Téléphone mobile 2 (format appel tel:+212...)"
    )
    phone_fixe = models.CharField(
        max_length=50,
        default="05 22 20 02 39",
        blank=True,
        verbose_name="Téléphone fixe (affichage)"
    )
    phone_fixe_intl = models.CharField(
        max_length=50,
        default="+212522200177",
        blank=True,
        verbose_name="Téléphone fixe (format appel tel:+212...)"
    )

    # WhatsApp
    whatsapp_number = models.CharField(
        max_length=50,
        default="+212664331463",
        blank=True,
        verbose_name="Numéro WhatsApp principal (+212...)"
    )

    # Email
    email_contact = models.EmailField(
        default="contact@agencemenage.ma",
        blank=True,
        verbose_name="Email de contact public"
    )
    email_notifications = models.EmailField(
        default="notification@agencemenage.ma",
        blank=True,
        verbose_name="Email de réception des notifications"
    )

    # Bureaux
    bureau_casa_label = models.CharField(
        max_length=150,
        default="Bureau Casablanca",
        blank=True,
        verbose_name="Libellé Bureau Casablanca"
    )
    bureau_casa_address = models.TextField(
        default="36 boulevard d’anfa, résidence Anafe A, etage 7",
        blank=True,
        verbose_name="Adresse Bureau Casablanca"
    )
    bureau_casa_maps_url = models.TextField(
        default="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3323.4846067727145!2d-7.6324838!3d33.5932599!2m3!1f0!2f0!3f0!3m2!1i1024!2i768!4f13.1!3m3!1m2!1s0x0%3A0x0!2zMzPCsDM1JzM1LjciTiA3wrAzNyc1Ni45Ilc!5e0!3m2!1sfr!2sma!4v1635848529285!5m2!1sfr!2sma",
        blank=True,
        verbose_name="URL Google Maps Embed Casablanca"
    )

    bureau_rabat_label = models.CharField(
        max_length=150,
        default="Bureau Rabat",
        blank=True,
        verbose_name="Libellé Bureau Rabat"
    )
    bureau_rabat_address = models.TextField(
        default="Avenue Hassan II, centre commercial Reda, porte G, appt. 49",
        blank=True,
        verbose_name="Adresse Bureau Rabat"
    )
    bureau_rabat_maps_url = models.TextField(
        default="https://maps.google.com/maps?q=34.020882,-6.836218(Agence%20M%C3%A9nage%20Rabat)&z=15&output=embed",
        blank=True,
        verbose_name="URL Google Maps Embed Rabat"
    )

    # Réseaux sociaux
    facebook_url = models.URLField(
        max_length=500,
        default="https://www.facebook.com/profile.php?id=61586972460164",
        blank=True,
        verbose_name="Lien Facebook"
    )
    instagram_url = models.URLField(
        max_length=500,
        default="https://www.instagram.com/agencemenage?igsh=MXBtNmxzNmNwcmdiYg==&utm_source=ig_contact_invite",
        blank=True,
        verbose_name="Lien Instagram"
    )
    tiktok_url = models.CharField(
        max_length=500,
        default="",
        blank=True,
        verbose_name="Lien TikTok"
    )

    # Notifications internes WhatsApp
    whatsapp_notification_numbers = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Numéros WhatsApp de notification interne"
    )

    # Déploiement Marrakech (3e ville — sans bureau physique)
    marrakech_status = models.CharField(
        max_length=20,
        choices=MARRAKECH_STATUS_CHOICES,
        default='coming_soon',
        verbose_name="Statut déploiement Marrakech"
    )
    marrakech_services = models.JSONField(
        default=default_marrakech_services,
        blank=True,
        verbose_name="Services ouverts à Marrakech"
    )

    # Bandeau Promotionnel CMS (Site Web)
    promo_banner_enabled = models.BooleanField(
        default=False,
        verbose_name="Activer le bandeau promotionnel"
    )
    promo_banner_campaign_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Identifiant de campagne promo"
    )
    promo_banner_label = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="Libellé de campagne (ex. BLACK FRIDAY)"
    )
    promo_banner_text = models.CharField(
        max_length=200,
        blank=True,
        default="Votre code promotionnel :",
        verbose_name="Texte d'accroche du bandeau"
    )
    promo_banner_code = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="Code promotionnel affiché"
    )
    promo_banner_cta_label = models.CharField(
        max_length=60,
        blank=True,
        default="En profiter",
        verbose_name="Libellé du CTA"
    )
    promo_banner_target_url = models.CharField(
        max_length=255,
        blank=True,
        default="/services/particulier/menage-standard",
        verbose_name="URL de destination du CTA"
    )
    promo_banner_start_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date/heure de début (Africa/Casablanca)"
    )
    promo_banner_end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date/heure de fin (Africa/Casablanca)"
    )
    promo_banner_audience = models.CharField(
        max_length=20,
        choices=PROMO_BANNER_AUDIENCE_CHOICES,
        default='all',
        verbose_name="Public ciblé"
    )
    promo_banner_cities = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Villes ciblées"
    )
    promo_banner_services = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Services ciblés"
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paramètres du Site"
        verbose_name_plural = "Paramètres du Site"

    def __str__(self):
        return f"Paramètres du Site (MAJ: {self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else 'Initial'})"
