from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from demandes.models import Demande
from .models import PromoCode
from .serializers import PromoCodeSerializer


class PublicPromoCodeValidateV32Tests(TestCase):
    URL = "/api/public/promos/validate/"
    BOOKING_URL = "/api/public/demandes/"

    def setUp(self):
        self.client = APIClient()
        self.today = timezone.localdate()

    def _create_promo(self, **overrides):
        defaults = {
            "name": "Offre Test V3.2",
            "promo_type": "simple",
            "code": "PROMO15",
            "reduction": Decimal("15.00"),
            "reduction_type": "pourcentage",
            "segment": "tous",
            "valid_from": self.today - timedelta(days=1),
            "valid_until": self.today + timedelta(days=10),
            "status": "active",
            "customer_status": "Tous les clients",
            "services": [],
            "villes": [],
            "modes_reservation": [],
            "minimum_commande": None,
            "plafond_reduction": None,
            "cumulable": False,
        }
        defaults.update(overrides)
        return PromoCode.objects.create(**defaults)

    def test_valid_code_returns_v32_and_legacy_fields(self):
        promo = self._create_promo(
            code="CASA20",
            reduction=Decimal("20.00"),
            minimum_commande=Decimal("300.00"),
            plafond_reduction=Decimal("150.00"),
            cumulable=True,
        )

        resp = self.client.post(
            self.URL,
            {"code": "casa20", "order_amount": "450"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["id"], promo.id)
        self.assertEqual(data["code"], "CASA20")
        self.assertEqual(data["name"], promo.name)
        self.assertEqual(data["reduction"], 20.0)
        self.assertEqual(data["reduction_type"], "pourcentage")
        self.assertEqual(data["promo_type"], "simple")
        self.assertEqual(data["plafond_reduction"], 150.0)
        self.assertEqual(data["minimum_commande"], 300.0)
        self.assertTrue(data["cumulable"])

    def test_non_dict_payload_rejected_with_400(self):
        resp = self.client.post(self.URL, ["PROMO15"], format="json")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body["valid"])
        self.assertEqual(body["reason_code"], "invalid_payload")

    def test_non_finite_and_negative_order_amount_rejected(self):
        # Promo WITHOUT minimum_commande still rejects invalid order_amount
        self._create_promo(code="ANYAMT10", minimum_commande=None)

        for bad_amount in ("NaN", "Infinity", "-Infinity", -50, "-0.01", "abc", True):
            resp = self.client.post(
                self.URL,
                {"code": "ANYAMT10", "order_amount": bad_amount},
                format="json",
            )
            self.assertEqual(resp.status_code, 400, f"Expected 400 for order_amount={bad_amount!r}")
            body = resp.json()
            self.assertFalse(body["valid"])
            self.assertEqual(body["reason_code"], "invalid_order_amount")

    def test_demo_codes_rejected_immediately_even_if_present_in_db(self):
        # 1. Absent from DB -> still 400 with demo_code (not 404)
        for code in ("DEMO-BF26", "demo-bf26", "DEMO-NY27", " Demo-Ny27 "):
            resp = self.client.post(self.URL, {"code": code}, format="json")
            self.assertEqual(resp.status_code, 400)
            data = resp.json()
            self.assertFalse(data["valid"])
            self.assertEqual(data["reason_code"], "demo_code")
            self.assertEqual(
                data["message"],
                "Ce code de démonstration n'est pas valable pour une réservation.",
            )

        # 2. Even if forced into DB via ORM -> still strictly rejected with 400 demo_code
        orm_demo = self._create_promo(code="DEMO-BF26")
        resp = self.client.post(self.URL, {"code": "DEMO-BF26"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["reason_code"], "demo_code")

        # 3. Serializer prevents creating demo promo codes via API
        serializer = PromoCodeSerializer(
            data={
                "name": "Demo",
                "code": "DEMO-NY27",
                "reduction": "10.00",
                "reduction_type": "pourcentage",
                "segment": "tous",
                "valid_from": str(self.today),
                "status": "active",
                "customer_status": "Tous les clients",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("code", serializer.errors)

        # 4. Serializer prevents PATCHing an existing ORM-seeded demo code without resending code
        patch_ser = PromoCodeSerializer(
            instance=orm_demo,
            data={"status": "active"},
            partial=True,
        )
        self.assertFalse(patch_ser.is_valid())
        self.assertIn("code", patch_ser.errors)

    def test_promo_serializer_hardening_lists_and_non_negative_decimals(self):
        base = {
            "name": "Promo Hardening",
            "code": "HARDEN10",
            "reduction": "10.00",
            "reduction_type": "pourcentage",
            "segment": "tous",
            "valid_from": str(self.today),
            "status": "active",
            "customer_status": "Tous les clients",
        }

        s_villes = PromoCodeSerializer(data={**base, "villes": "Casablanca"})
        self.assertFalse(s_villes.is_valid())
        self.assertIn("villes", s_villes.errors)

        s_modes = PromoCodeSerializer(data={**base, "modes_reservation": "oneshot"})
        self.assertFalse(s_modes.is_valid())
        self.assertIn("modes_reservation", s_modes.errors)

        s_min = PromoCodeSerializer(data={**base, "minimum_commande": "-100.00"})
        self.assertFalse(s_min.is_valid())
        self.assertIn("minimum_commande", s_min.errors)

        s_plafond = PromoCodeSerializer(data={**base, "plafond_reduction": "-20.00"})
        self.assertFalse(s_plafond.is_valid())
        self.assertIn("plafond_reduction", s_plafond.errors)

    def test_city_filter_case_and_accent_insensitive(self):
        self._create_promo(
            code="VILLE10",
            villes=["Casablanca", "Rabat", "Fès"],
        )

        # Matching cities (various case / accents / spaces)
        for valid_city in ("Casablanca", "casablanca", " RABAT ", "Fes", "fès"):
            resp = self.client.post(
                self.URL,
                {"code": "VILLE10", "city": valid_city},
                format="json",
            )
            self.assertEqual(resp.status_code, 200, f"Expected 200 for city={valid_city}")
            self.assertTrue(resp.json()["valid"])

        # Ineligible city -> 400 city_ineligible
        resp_marrakech = self.client.post(
            self.URL,
            {"code": "VILLE10", "city": "Marrakech"},
            format="json",
        )
        self.assertEqual(resp_marrakech.status_code, 400)
        body = resp_marrakech.json()
        self.assertFalse(body["valid"])
        self.assertEqual(body["reason_code"], "city_ineligible")
        self.assertEqual(body["message"], "Ce code promo n'est pas valable pour cette ville.")

        # Missing city when promo restricts villes -> 400 city_ineligible
        resp_missing = self.client.post(
            self.URL,
            {"code": "VILLE10"},
            format="json",
        )
        self.assertEqual(resp_missing.status_code, 400)
        self.assertEqual(resp_missing.json()["reason_code"], "city_ineligible")

    def test_booking_mode_filter_and_normalization(self):
        self._create_promo(
            code="PONCTUEL10",
            modes_reservation=["oneshot"],
        )
        self._create_promo(
            code="ABO15",
            modes_reservation=["abonnement"],
        )

        # oneshot / once / ponctuel accepted for PONCTUEL10
        for mode in ("oneshot", "once", "ponctuel"):
            resp = self.client.post(
                self.URL,
                {"code": "PONCTUEL10", "booking_mode": mode},
                format="json",
            )
            self.assertEqual(resp.status_code, 200, f"Expected 200 for booking_mode={mode}")

        # subscription / abonnement rejected for PONCTUEL10
        for mode in ("subscription", "abonnement"):
            resp = self.client.post(
                self.URL,
                {"code": "PONCTUEL10", "booking_mode": mode},
                format="json",
            )
            self.assertEqual(resp.status_code, 400)
            body = resp.json()
            self.assertFalse(body["valid"])
            self.assertEqual(body["reason_code"], "mode_ineligible")
            self.assertEqual(
                body["message"],
                "Ce code promo n'est pas compatible avec ce mode de réservation.",
            )

        # subscription normalized to abonnement for ABO15
        resp_sub = self.client.post(
            self.URL,
            {"code": "ABO15", "booking_mode": "subscription"},
            format="json",
        )
        self.assertEqual(resp_sub.status_code, 200)

        resp_once = self.client.post(
            self.URL,
            {"code": "ABO15", "booking_mode": "once"},
            format="json",
        )
        self.assertEqual(resp_once.status_code, 400)
        self.assertEqual(resp_once.json()["reason_code"], "mode_ineligible")

    def test_minimum_commande_validation(self):
        self._create_promo(
            code="MIN400",
            minimum_commande=Decimal("400.00"),
            plafond_reduction=Decimal("100.00"),
        )

        # Below minimum -> 400
        resp_low = self.client.post(
            self.URL,
            {"code": "MIN400", "order_amount": 350},
            format="json",
        )
        self.assertEqual(resp_low.status_code, 400)
        body_low = resp_low.json()
        self.assertFalse(body_low["valid"])
        self.assertEqual(body_low["reason_code"], "minimum_order_not_met")
        self.assertIn("400 MAD", body_low["message"])

        # Exact minimum -> 200
        resp_eq = self.client.post(
            self.URL,
            {"code": "MIN400", "order_amount": 400},
            format="json",
        )
        self.assertEqual(resp_eq.status_code, 200)
        self.assertEqual(resp_eq.json()["minimum_commande"], 400.0)
        self.assertEqual(resp_eq.json()["plafond_reduction"], 100.0)

        # Omitted order_amount -> 200 (still returns minimum_commande for client display)
        resp_no_amt = self.client.post(
            self.URL,
            {"code": "MIN400"},
            format="json",
        )
        self.assertEqual(resp_no_amt.status_code, 200)
        self.assertEqual(resp_no_amt.json()["minimum_commande"], 400.0)

        # Non-numeric order_amount -> 400
        resp_invalid = self.client.post(
            self.URL,
            {"code": "MIN400", "order_amount": "abc"},
            format="json",
        )
        self.assertEqual(resp_invalid.status_code, 400)
        self.assertEqual(resp_invalid.json()["reason_code"], "invalid_order_amount")

    def test_expired_and_future_dates(self):
        self._create_promo(
            code="EXPIRE10",
            valid_from=self.today - timedelta(days=10),
            valid_until=self.today - timedelta(days=1),
        )
        self._create_promo(
            code="FUTUR10",
            valid_from=self.today + timedelta(days=2),
            valid_until=self.today + timedelta(days=20),
        )

        resp_expired = self.client.post(self.URL, {"code": "EXPIRE10"}, format="json")
        self.assertEqual(resp_expired.status_code, 400)
        self.assertEqual(resp_expired.json()["reason_code"], "expired")
        self.assertEqual(resp_expired.json()["message"], "Ce code promo a expiré.")

        resp_future = self.client.post(self.URL, {"code": "FUTUR10"}, format="json")
        self.assertEqual(resp_future.status_code, 400)
        self.assertEqual(resp_future.json()["reason_code"], "not_started")
        self.assertEqual(resp_future.json()["message"], "Ce code promo n'est pas encore valide.")

    def test_final_booking_creation_enforces_shared_promo_validation(self):
        casa_only_promo = self._create_promo(
            code="CASAONLY15",
            villes=["Casablanca"],
            modes_reservation=["oneshot"],
            minimum_commande=Decimal("300.00"),
        )
        base_booking = {
            "service": "Ménage standard",
            "segment": "particulier",
            "frequency": "oneshot",
            "prix": 400,
            "client_nom": "El Amrani",
            "client_prenom": "Salma",
            "client_phone": "+212611223344",
            "client_ville": "Marrakech",
            "formulaire_data": {},
        }

        # 1. Final booking rejects DEMO-BF26 via formulaire_data.promoCodeInput (and rolls back Client)
        resp_demo_fd = self.client.post(
            self.BOOKING_URL,
            {**base_booking, "formulaire_data": {"promoCodeInput": "DEMO-BF26"}},
            format="json",
        )
        self.assertEqual(resp_demo_fd.status_code, 400)
        self.assertIn("promo_code", resp_demo_fd.json())
        self.assertIn("démonstration", str(resp_demo_fd.json()["promo_code"]).lower())
        self.assertEqual(Demande.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 0)

        # 2. Final booking rejects DEMO-NY27 passed directly in promo_code string
        resp_demo_str = self.client.post(
            self.BOOKING_URL,
            {**base_booking, "promo_code": "DEMO-NY27"},
            format="json",
        )
        self.assertEqual(resp_demo_str.status_code, 400)
        self.assertIn("promo_code", resp_demo_str.json())
        self.assertEqual(Demande.objects.count(), 0)

        # 3. Final booking rejects city-ineligible promo passed by FK ID
        resp_city_fk = self.client.post(
            self.BOOKING_URL,
            {**base_booking, "promo_code": casa_only_promo.id, "client_ville": "Marrakech"},
            format="json",
        )
        self.assertEqual(resp_city_fk.status_code, 400)
        self.assertIn("promo_code", resp_city_fk.json())
        self.assertIn("ville", str(resp_city_fk.json()["promo_code"]).lower())
        self.assertEqual(Demande.objects.count(), 0)

        # 4. Final booking rejects booking_mode-ineligible promo
        resp_mode = self.client.post(
            self.BOOKING_URL,
            {
                **base_booking,
                "promo_code": casa_only_promo.id,
                "client_ville": "Casablanca",
                "frequency": "subscription",
            },
            format="json",
        )
        self.assertEqual(resp_mode.status_code, 400)
        self.assertIn("promo_code", resp_mode.json())
        self.assertEqual(Demande.objects.count(), 0)

        # 5. Final booking rejects below minimum_commande
        resp_min = self.client.post(
            self.BOOKING_URL,
            {
                **base_booking,
                "promo_code": casa_only_promo.id,
                "client_ville": "Casablanca",
                "prix": 200,
            },
            format="json",
        )
        self.assertEqual(resp_min.status_code, 400)
        self.assertIn("promo_code", resp_min.json())
        self.assertEqual(Demande.objects.count(), 0)

        # 6. Final booking SUCCEEDS when all eligibility rules match
        resp_ok = self.client.post(
            self.BOOKING_URL,
            {
                **base_booking,
                "promo_code": casa_only_promo.id,
                "client_ville": "Casablanca",
                "prix": 400,
            },
            format="json",
        )
        self.assertEqual(resp_ok.status_code, 201, resp_ok.json())
        self.assertEqual(Demande.objects.count(), 1)
        created_demande = Demande.objects.first()
        self.assertEqual(created_demande.promo_code_id, casa_only_promo.id)
