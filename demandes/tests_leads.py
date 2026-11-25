from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import RolePermission
from clients.models import Client
from .models import AppNotification, AuditLog, ContactLead, Demande


class ContactLeadWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            username="admin_leads",
            email="admin_leads@agencemenage.ma",
            password="StrongPassword123!",
            role="admin",
            is_staff=True,
            is_superuser=True,
        )
        self.commercial_user = user_model.objects.create_user(
            username="comm_leads",
            email="comm_leads@agencemenage.ma",
            password="StrongPassword123!",
            role="commercial",
        )
        RolePermission.objects.update_or_create(
            role="commercial",
            defaults={
                "permissions": [
                    "consulter_demandes",
                    "traiter_demandes_affectees",
                    "creer_demande",
                ]
            },
        )
        self.conciergerie_user = user_model.objects.create_user(
            username="conc_leads",
            email="conc_leads@agencemenage.ma",
            password="StrongPassword123!",
            role="client_conciergerie",
        )
        self.runner_user = user_model.objects.create_user(
            username="runner_leads",
            email="runner_leads@agencemenage.ma",
            password="StrongPassword123!",
            role="runner",
        )

    def test_public_create_creates_lead_not_demande_and_notifies(self):
        payload = {
            "segment": "entreprise",
            "channel": "b2b_quote_modal",
            "entity_name": "Atlas Bureaux SARL",
            "contact_name": "Atlas Bureaux SARL",
            "phone": "+212661112233",
            "city": "Casablanca",
            "service": "Gestion 360°",
            "notes": "450 m2 open space",
            "source_page": "home_v32_b2b_modal",
            "landing_url": "/?utm_source=google&gclid=test123",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "b2b_casa",
            "gclid": "test123",
            # Privileged fields that must be ignored on the public endpoint
            "statut": "converti",
            "commercial_notes": "Injected internal note",
            "assigned_to": self.admin_user.id,
        }
        resp = self.client.post("/api/public/leads/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        body = resp.json()
        self.assertIn("id", body)
        self.assertEqual(body["statut"], ContactLead.NOUVEAU)

        # Must NOT create a Demande row directly
        self.assertEqual(Demande.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(ContactLead.objects.count(), 1)

        lead = ContactLead.objects.get(pk=body["id"])
        self.assertEqual(lead.entity_name, "Atlas Bureaux SARL")
        self.assertEqual(lead.statut, ContactLead.NOUVEAU)
        self.assertEqual(lead.commercial_notes, "")
        self.assertIsNone(lead.assigned_to)
        self.assertEqual(lead.utm_source, "google")
        self.assertEqual(lead.gclid, "test123")

        notif = AppNotification.objects.filter(lien_url="/leads").first()
        self.assertIsNotNone(notif)
        self.assertIn("Atlas Bureaux SARL", notif.title)

    def test_public_create_validation_and_long_tracking_urls(self):
        # Reject blank entity_name / phone / city on b2b_quote_modal
        r_missing = self.client.post(
            "/api/public/leads/",
            {"entity_name": "   ", "phone": "+212661000000", "city": "Rabat"},
            format="json",
        )
        self.assertEqual(r_missing.status_code, 400)

        r_no_city = self.client.post(
            "/api/public/leads/",
            {
                "channel": "b2b_quote_modal",
                "entity_name": "Société Test",
                "phone": "+212661000000",
                "city": " ",
            },
            format="json",
        )
        self.assertEqual(r_no_city.status_code, 400)

        # Very long landing_url must be safely truncated, not rejected
        long_url = "/?" + ("a=" + "x" * 600)
        r_ok = self.client.post(
            "/api/public/leads/",
            {
                "entity_name": "Société Long URL",
                "phone": "+212661998877",
                "city": "Rabat",
                "landing_url": long_url,
            },
            format="json",
        )
        self.assertEqual(r_ok.status_code, 201, r_ok.json())
        lead = ContactLead.objects.get(pk=r_ok.json()["id"])
        self.assertEqual(len(lead.landing_url), 500)

    def test_rbac_enforcement_across_roles(self):
        lead = ContactLead.objects.create(
            entity_name="RBAC Corp",
            phone="+212662223344",
            city="Casablanca",
            service="Entretien de bureaux",
        )

        # Unauthenticated -> 401
        self.assertEqual(self.client.get("/api/leads/").status_code, 401)
        self.assertEqual(self.client.post(f"/api/leads/{lead.id}/convert/").status_code, 401)

        # Airbnb-only roles -> 403
        for user in (self.conciergerie_user, self.runner_user):
            self.client.force_authenticate(user=user)
            self.assertEqual(self.client.get("/api/leads/").status_code, 403)
            self.assertEqual(
                self.client.patch(f"/api/leads/{lead.id}/", {"statut": "contacte"}, format="json").status_code,
                403,
            )
            self.assertEqual(self.client.post(f"/api/leads/{lead.id}/convert/").status_code, 403)
            self.assertEqual(self.client.delete(f"/api/leads/{lead.id}/").status_code, 403)

        # Commercial -> can list & patch & convert, denied destroy
        self.client.force_authenticate(user=self.commercial_user)
        self.assertEqual(self.client.get("/api/leads/").status_code, 200)
        self.assertEqual(
            self.client.patch(
                f"/api/leads/{lead.id}/",
                {"statut": "contacte", "commercial_notes": "Rappelé à 10h"},
                format="json",
            ).status_code,
            200,
        )
        # Cannot manually force 'converti' without convert action
        bad_patch = self.client.patch(
            f"/api/leads/{lead.id}/",
            {"statut": "converti"},
            format="json",
        )
        self.assertEqual(bad_patch.status_code, 400)
        # Commercial lacks supprimer_demande_dashboard -> 403 on DELETE
        self.assertEqual(self.client.delete(f"/api/leads/{lead.id}/").status_code, 403)

        # Admin -> can delete & AuditLog recorded
        self.client.force_authenticate(user=self.admin_user)
        self.assertEqual(self.client.delete(f"/api/leads/{lead.id}/").status_code, 204)
        self.assertTrue(
            AuditLog.objects.filter(
                action="delete_contact_lead",
                model_name="ContactLead",
                object_id=lead.id,
            ).exists()
        )

    def test_convert_lead_to_demande_and_idempotency_guard(self):
        lead = ContactLead.objects.create(
            segment="entreprise",
            channel="b2b_quote_modal",
            entity_name="Technopark Logistics",
            contact_name="Meryem B.",
            phone="+212663334455",
            city="Casablanca",
            service="Gestion RH",
            notes="Besoin 3 agents matin",
            commercial_notes="Visite prévue jeudi",
            source_page="home_v32_b2b_modal",
            landing_url="/?utm_source=linkedin&utm_campaign=rh_b2b",
            utm_source="linkedin",
            utm_campaign="rh_b2b",
            gclid="GCLID-999",
        )

        self.client.force_authenticate(user=self.commercial_user)
        resp = self.client.post(
            f"/api/leads/{lead.id}/convert/",
            {"service": "Gestion intégrale 360°"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.json())
        payload = resp.json()
        demande_id = payload["demande_id"]
        self.assertEqual(payload["lead"]["statut"], ContactLead.CONVERTI)
        self.assertEqual(payload["lead"]["converted_demande"], demande_id)

        demande = Demande.objects.get(pk=demande_id)
        self.assertTrue(demande.is_devis)
        self.assertEqual(demande.segment, Demande.ENTREPRISE)
        self.assertEqual(demande.service, "Gestion intégrale 360°")
        self.assertEqual(demande.statut, Demande.EN_ATTENTE)
        self.assertEqual(demande.formulaire_data["lead_id"], lead.id)
        self.assertEqual(demande.formulaire_data["utm_source"], "linkedin")
        self.assertEqual(demande.formulaire_data["utm_campaign"], "rh_b2b")
        self.assertEqual(demande.formulaire_data["gclid"], "GCLID-999")
        self.assertEqual(demande.formulaire_data["additionalNotes"], "Besoin 3 agents matin")

        client_obj = demande.client
        self.assertEqual(client_obj.phone, "+212663334455")
        self.assertEqual(client_obj.entity_name, "Technopark Logistics")

        self.assertTrue(
            AuditLog.objects.filter(
                action="convert_contact_lead",
                model_name="ContactLead",
                object_id=lead.id,
            ).exists()
        )

        # Second convert call must be rejected cleanly with 400 and never create a duplicate Demande
        second = self.client.post(f"/api/leads/{lead.id}/convert/", format="json")
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["demande_id"], demande_id)
        self.assertEqual(Demande.objects.count(), 1)
