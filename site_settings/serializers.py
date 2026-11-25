from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from .models import SiteConfig, DEFAULT_MARRAKECH_SERVICES, default_marrakech_services


FORBIDDEN_DEMO_PROMO_CODES = {"DEMO-BF26", "DEMO-NY27"}
CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
ALLOWED_TARGET_HOSTS = {"agencemenage.ma", "www.agencemenage.ma"}


def _ensure_aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, CASABLANCA_TZ)
    return dt


def _normalize_marrakech_services_dict(raw):
    merged = default_marrakech_services()
    if isinstance(raw, dict):
        for key in DEFAULT_MARRAKECH_SERVICES:
            if key in raw:
                merged[key] = bool(raw[key])
    # Service linge Airbnb reste strictement Casablanca-only jusqu'à validation dédiée
    merged["airbnb_linge"] = False
    return merged


def _compute_active_promo_banner(obj):
    if not obj.promo_banner_enabled:
        return None

    code = (obj.promo_banner_code or "").strip()
    if not code or code.upper() in FORBIDDEN_DEMO_PROMO_CODES:
        return None

    now = timezone.now()
    start_at = _ensure_aware(obj.promo_banner_start_at)
    end_at = _ensure_aware(obj.promo_banner_end_at)

    if start_at is not None and now < start_at:
        return None
    if end_at is not None and now > end_at:
        return None

    return {
        "campaign_id": (obj.promo_banner_campaign_id or "").strip(),
        "label": (obj.promo_banner_label or "").strip(),
        "text": (obj.promo_banner_text or "").strip(),
        "code": code,
        "cta_label": (obj.promo_banner_cta_label or "").strip(),
        "target_url": (obj.promo_banner_target_url or "").strip(),
        "audience": obj.promo_banner_audience or "all",
        "cities": obj.promo_banner_cities if isinstance(obj.promo_banner_cities, list) else [],
        "services": obj.promo_banner_services if isinstance(obj.promo_banner_services, list) else [],
    }


class PublicSiteConfigSerializer(serializers.ModelSerializer):
    """
    Serializer strictement public pour le site web.
    N'expose jamais whatsapp_notification_numbers, email_notifications ni les champs promo_banner_* bruts.
    """
    active_promo_banner = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SiteConfig
        fields = [
            "id",
            "phone_mobile_1",
            "phone_mobile_1_intl",
            "phone_mobile_2",
            "phone_mobile_2_intl",
            "phone_fixe",
            "phone_fixe_intl",
            "whatsapp_number",
            "email_contact",
            "bureau_casa_label",
            "bureau_casa_address",
            "bureau_casa_maps_url",
            "bureau_rabat_label",
            "bureau_rabat_address",
            "bureau_rabat_maps_url",
            "facebook_url",
            "instagram_url",
            "tiktok_url",
            "marrakech_status",
            "marrakech_services",
            "active_promo_banner",
            "updated_at",
        ]
        read_only_fields = fields

    def get_active_promo_banner(self, obj):
        return _compute_active_promo_banner(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["marrakech_services"] = _normalize_marrakech_services_dict(
            data.get("marrakech_services")
        )
        return data


class SiteConfigSerializer(serializers.ModelSerializer):
    active_promo_banner = serializers.SerializerMethodField(read_only=True)
    promo_banner_start_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default_timezone=CASABLANCA_TZ,
    )
    promo_banner_end_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default_timezone=CASABLANCA_TZ,
    )

    class Meta:
        model = SiteConfig
        fields = '__all__'

    def get_active_promo_banner(self, obj):
        return _compute_active_promo_banner(obj)

    def validate_marrakech_services(self, value):
        if value is None:
            return default_marrakech_services()
        if not isinstance(value, dict):
            raise serializers.ValidationError("marrakech_services doit être un objet JSON.")
        unknown_keys = set(value.keys()) - set(DEFAULT_MARRAKECH_SERVICES.keys())
        if unknown_keys:
            raise serializers.ValidationError(
                f"Clés de services Marrakech non autorisées : {', '.join(sorted(unknown_keys))}."
            )
        return _normalize_marrakech_services_dict(value)

    def validate_promo_banner_target_url(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        if any(ch in cleaned for ch in ("\r", "\n", "\t", " ")):
            raise serializers.ValidationError(
                "L'URL de destination ne doit pas contenir d'espaces ni de caractères de contrôle."
            )
        # Allow relative internal paths starting with single '/'
        if cleaned.startswith("/"):
            if cleaned.startswith("//"):
                raise serializers.ValidationError(
                    "Les URLs relatives de protocole (//) ne sont pas autorisées."
                )
            return cleaned
        # Otherwise only allow https://(www.)?agencemenage.ma/...
        parsed = urlsplit(cleaned)
        if parsed.scheme.lower() == "https" and parsed.netloc.lower() in ALLOWED_TARGET_HOSTS:
            return cleaned
        raise serializers.ValidationError(
            "L'URL de destination doit être un chemin interne commençant par '/' "
            "ou une URL https://agencemenage.ma/."
        )

    def validate_promo_banner_cities(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("promo_banner_cities doit être une liste.")
        return value

    def validate_promo_banner_services(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("promo_banner_services doit être une liste.")
        return value

    def validate(self, attrs):
        enabled = attrs.get(
            "promo_banner_enabled",
            getattr(self.instance, "promo_banner_enabled", False),
        )
        code = attrs.get(
            "promo_banner_code",
            getattr(self.instance, "promo_banner_code", ""),
        )
        code_clean = (code or "").strip()

        if code_clean.upper() in FORBIDDEN_DEMO_PROMO_CODES:
            if enabled or "promo_banner_code" in attrs:
                raise serializers.ValidationError({
                    "promo_banner_code": (
                        "Les codes de démonstration (DEMO-BF26, DEMO-NY27) sont interdits "
                        "et ne peuvent pas être activés en production."
                    )
                })

        start_at = attrs.get(
            "promo_banner_start_at",
            getattr(self.instance, "promo_banner_start_at", None),
        )
        end_at = attrs.get(
            "promo_banner_end_at",
            getattr(self.instance, "promo_banner_end_at", None),
        )
        if start_at is not None and end_at is not None:
            if _ensure_aware(end_at) <= _ensure_aware(start_at):
                raise serializers.ValidationError({
                    "promo_banner_end_at": (
                        "La date de fin doit être strictement postérieure à la date de début."
                    )
                })

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["marrakech_services"] = _normalize_marrakech_services_dict(
            data.get("marrakech_services")
        )
        return data
