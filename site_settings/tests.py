from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from demandes.models import AuditLog
from .models import SiteConfig
from .serializers import SiteConfigSerializer, PublicSiteConfigSerializer

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")


class SiteConfigV32Tests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_marrakech_defaults_and_serialization(self):
        config = SiteConfig.objects.create()
        self.assertEqual(config.marrakech_status, "coming_soon")
        self.assertIsInstance(config.marrakech_services, dict)
        self.assertFalse(config.marrakech_services.get("airbnb_linge"))
        self.assertFalse(config.marrakech_services.get("menage_standard"))

        data = SiteConfigSerializer(config).data
        self.assertEqual(data["marrakech_status"], "coming_soon")
        self.assertIsNone(data["active_promo_banner"])
        expected_keys = {
            "menage_standard",
            "grand_menage",
            "menage_airbnb",
            "fin_chantier",
            "garde_malade",
            "post_sinistre",
            "entreprises",
            "airbnb_linge",
        }
        self.assertEqual(set(data["marrakech_services"].keys()), expected_keys)
        self.assertFalse(data["marrakech_services"]["airbnb_linge"])

    def test_public_endpoint_returns_only_public_fields_and_active_banner(self):
        SiteConfig.objects.create(
            whatsapp_notification_numbers=["+212600000001"],
            email_notifications="secret-ops@agencemenage.ma",
            marrakech_status="active",
            marrakech_services={"menage_standard": True, "grand_menage": True, "airbnb_linge": True},
            promo_banner_enabled=True,
            promo_banner_campaign_id="autumn-live",
            promo_banner_label="OFFRE AUTOMNE",
            promo_banner_text="Profitez de -10% avec le code :",
            promo_banner_code="AUTOMNE10",
            promo_banner_cta_label="Réserver",
            promo_banner_target_url="/services/particulier/menage-standard",
            promo_banner_audience="particulier",
            promo_banner_cities=["Casablanca", "Rabat"],
            promo_banner_services=["menage_standard"],
        )

        response = self.client.get("/api/public/site-config/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        # Verify ONLY public fields are exposed (no internal numbers, notification email, or raw promo_banner_*)
        forbidden_private_fields = [
            "whatsapp_notification_numbers",
            "email_notifications",
            "promo_banner_enabled",
            "promo_banner_campaign_id",
            "promo_banner_label",
            "promo_banner_text",
            "promo_banner_code",
            "promo_banner_cta_label",
            "promo_banner_target_url",
            "promo_banner_start_at",
            "promo_banner_end_at",
            "promo_banner_audience",
            "promo_banner_cities",
            "promo_banner_services",
        ]
        for private_key in forbidden_private_fields:
            self.assertNotIn(private_key, payload, f"Private field {private_key} leaked in public API!")

        self.assertEqual(set(payload.keys()), set(PublicSiteConfigSerializer.Meta.fields))
        self.assertEqual(payload["marrakech_status"], "active")
        self.assertTrue(payload["marrakech_services"]["menage_standard"])
        # airbnb_linge must always stay False even if forced True in DB
        self.assertFalse(payload["marrakech_services"]["airbnb_linge"])
        self.assertEqual(
            payload["active_promo_banner"],
            {
                "campaign_id": "autumn-live",
                "label": "OFFRE AUTOMNE",
                "text": "Profitez de -10% avec le code :",
                "code": "AUTOMNE10",
                "cta_label": "Réserver",
                "target_url": "/services/particulier/menage-standard",
                "audience": "particulier",
                "cities": ["Casablanca", "Rabat"],
                "services": ["menage_standard"],
            },
        )

    def test_active_promo_banner_disabled_or_blank_code(self):
        cfg_disabled = SiteConfig.objects.create(
            promo_banner_enabled=False,
            promo_banner_code="REALCODE10",
        )
        self.assertIsNone(SiteConfigSerializer(cfg_disabled).data["active_promo_banner"])
        self.assertIsNone(PublicSiteConfigSerializer(cfg_disabled).data["active_promo_banner"])

        cfg_blank = SiteConfig.objects.create(
            promo_banner_enabled=True,
            promo_banner_code="   ",
        )
        self.assertIsNone(SiteConfigSerializer(cfg_blank).data["active_promo_banner"])

    def test_active_promo_banner_schedule_africa_casablanca_relative(self):
        base_now = timezone.now().astimezone(CASABLANCA_TZ).replace(microsecond=0)
        start_at = base_now + timedelta(hours=2)
        end_at = base_now + timedelta(days=2)

        cfg = SiteConfig.objects.create(
            promo_banner_enabled=True,
            promo_banner_campaign_id="bf-live",
            promo_banner_label="OFFRE SPECIALE",
            promo_banner_code="CASA15",
            promo_banner_start_at=start_at,
            promo_banner_end_at=end_at,
        )

        # Before start_at -> None
        with patch("site_settings.serializers.timezone.now", return_value=base_now):
            self.assertIsNone(SiteConfigSerializer(cfg).data["active_promo_banner"])

        # Inside schedule window -> active
        inside_now = start_at + timedelta(hours=1)
        with patch("site_settings.serializers.timezone.now", return_value=inside_now):
            banner = SiteConfigSerializer(cfg).data["active_promo_banner"]
            self.assertIsNotNone(banner)
            self.assertEqual(banner["code"], "CASA15")
            self.assertEqual(banner["campaign_id"], "bf-live")

        # After end_at -> None
        expired_now = end_at + timedelta(minutes=1)
        with patch("site_settings.serializers.timezone.now", return_value=expired_now):
            self.assertIsNone(SiteConfigSerializer(cfg).data["active_promo_banner"])

    def test_demo_promo_codes_strictly_blocked_in_banner_and_serializer(self):
        for demo_code in ("DEMO-BF26", "demo-bf26", "DEMO-NY27", " demo-ny27 "):
            cfg = SiteConfig.objects.create(
                promo_banner_enabled=True,
                promo_banner_label="DEMO",
                promo_banner_code=demo_code,
            )
            self.assertIsNone(
                SiteConfigSerializer(cfg).data["active_promo_banner"],
                f"Demo code {demo_code} must never appear in active_promo_banner",
            )
            self.assertIsNone(
                PublicSiteConfigSerializer(cfg).data["active_promo_banner"],
                f"Demo code {demo_code} must never appear in public active_promo_banner",
            )

            serializer = SiteConfigSerializer(
                instance=cfg,
                data={
                    "promo_banner_enabled": True,
                    "promo_banner_code": demo_code,
                },
                partial=True,
            )
            self.assertFalse(serializer.is_valid())
            self.assertIn("promo_banner_code", serializer.errors)

    def test_serializer_hardening_dates_target_url_and_marrakech_services(self):
        cfg = SiteConfig.objects.create()
        now = timezone.now()

        # end_at < start_at rejected
        ser_before = SiteConfigSerializer(
            instance=cfg,
            data={
                "promo_banner_enabled": True,
                "promo_banner_code": "VALID20",
                "promo_banner_start_at": (now + timedelta(days=2)).isoformat(),
                "promo_banner_end_at": (now + timedelta(days=1)).isoformat(),
            },
            partial=True,
        )
        self.assertFalse(ser_before.is_valid())
        self.assertIn("promo_banner_end_at", ser_before.errors)

        # end_at == start_at rejected
        same_dt = (now + timedelta(days=1)).isoformat()
        ser_equal = SiteConfigSerializer(
            instance=cfg,
            data={
                "promo_banner_start_at": same_dt,
                "promo_banner_end_at": same_dt,
            },
            partial=True,
        )
        self.assertFalse(ser_equal.is_valid())
        self.assertIn("promo_banner_end_at", ser_equal.errors)

        # Malicious / external promo_banner_target_url rejected
        for bad_url in (
            "//evil.example.com/phish",
            "https://evil.example.com/promo",
            "http://agencemenage.ma/services",
            "javascript:alert(1)",
        ):
            ser_url = SiteConfigSerializer(
                instance=cfg,
                data={"promo_banner_target_url": bad_url},
                partial=True,
            )
            self.assertFalse(ser_url.is_valid(), f"URL should be rejected: {bad_url}")
            self.assertIn("promo_banner_target_url", ser_url.errors)

        # Allowed target URLs accepted
        for good_url in (
            "",
            "/services/particulier/menage-standard",
            "https://agencemenage.ma/services/menage-airbnb",
            "https://www.agencemenage.ma/entreprise",
        ):
            ser_url = SiteConfigSerializer(
                instance=cfg,
                data={"promo_banner_target_url": good_url},
                partial=True,
            )
            self.assertTrue(ser_url.is_valid(), f"URL should be accepted: {good_url} ({ser_url.errors})")

        # Unknown marrakech_services key rejected
        ser_bad_srv = SiteConfigSerializer(
            instance=cfg,
            data={"marrakech_services": {"unknown_service": True}},
            partial=True,
        )
        self.assertFalse(ser_bad_srv.is_valid())
        self.assertIn("marrakech_services", ser_bad_srv.errors)

        # airbnb_linge forced to False server-side
        ser_linge = SiteConfigSerializer(
            instance=cfg,
            data={"marrakech_services": {"menage_standard": True, "airbnb_linge": True}},
            partial=True,
        )
        self.assertTrue(ser_linge.is_valid(), ser_linge.errors)
        updated = ser_linge.save()
        self.assertTrue(updated.marrakech_services["menage_standard"])
        self.assertFalse(updated.marrakech_services["airbnb_linge"])

    def test_admin_permissions_singleton_methods_and_audit_log(self):
        user_model = get_user_model()
        admin_user = user_model.objects.create_user(
            username="admin_v32",
            email="admin_v32@agencemenage.ma",
            password="StrongPassword123!",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        commercial_user = user_model.objects.create_user(
            username="commercial_v32",
            email="commercial_v32@agencemenage.ma",
            password="StrongPassword123!",
            role="commercial",
        )
        cfg = SiteConfig.objects.create()

        # Unauthorized role (commercial) gets 403 on GET and PATCH
        self.client.force_authenticate(user=commercial_user)
        self.assertEqual(self.client.get("/api/site/config/").status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/site/config/{cfg.id}/",
                {"marrakech_status": "active"},
                format="json",
            ).status_code,
            403,
        )

        # Admin is authorized
        self.client.force_authenticate(user=admin_user)

        # Singleton protection: POST and DELETE disallowed (405)
        self.assertEqual(
            self.client.post("/api/site/config/", {"marrakech_status": "active"}, format="json").status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(f"/api/site/config/{cfg.id}/").status_code,
            405,
        )

        # Reject demo code via API PATCH
        bad_resp = self.client.patch(
            f"/api/site/config/{cfg.id}/",
            {"promo_banner_enabled": True, "promo_banner_code": "DEMO-BF26"},
            format="json",
        )
        self.assertEqual(bad_resp.status_code, 400)
        self.assertIn("promo_banner_code", bad_resp.json())

        # Accept valid code + relative Casablanca naive datetimes + Marrakech config
        now_casa = timezone.now().astimezone(CASABLANCA_TZ).replace(microsecond=0)
        start_naive = (now_casa - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        end_naive = (now_casa + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")

        ok_resp = self.client.patch(
            f"/api/site/config/{cfg.id}/",
            {
                "marrakech_status": "coming_soon",
                "marrakech_services": {"menage_standard": True, "airbnb_linge": True},
                "promo_banner_enabled": True,
                "promo_banner_code": "LANCEMENT10",
                "promo_banner_start_at": start_naive,
                "promo_banner_end_at": end_naive,
            },
            format="json",
        )
        self.assertEqual(ok_resp.status_code, 200)
        body = ok_resp.json()
        self.assertEqual(body["marrakech_status"], "coming_soon")
        self.assertTrue(body["marrakech_services"]["menage_standard"])
        self.assertFalse(body["marrakech_services"]["airbnb_linge"])
        self.assertIsNotNone(body["active_promo_banner"])
        self.assertEqual(body["active_promo_banner"]["code"], "LANCEMENT10")

        # AuditLog entry recorded for perform_update
        log = AuditLog.objects.filter(
            action="update_site_config",
            model_name="SiteConfig",
            user=admin_user,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.extra_data["site_config_id"], str(cfg.id))
        self.assertIn("promo_banner_code", log.extra_data["changed_fields"])
