from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta
from clients.models import Client
from airbnb.models import AirbnbConfig, Bien, CommandeAirbnb, FiletLinge, ObjetTrouve
from airbnb.services.codification_service import generate_bien_code
from airbnb.services.linen_engine import calculate_linen_pieces_and_amount
from airbnb.services.pricing_engine import calculate_commande_pricing, check_cutoff_constraint

User = get_user_model()

class AirbnbModuleTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(
            username="admin_test",
            email="admin@agencemenage.ma",
            password="adminpassword123"
        )
        self.client.force_authenticate(user=self.user)

        self.config = AirbnbConfig.objects.create(
            prix_studio=130,
            prix_2ch=160,
            prix_3ch=190,
            prix_4ch=220,
            prix_5ch=250,
            prix_villa_riad=300,
            supplement_zone_eloignee=50,
            zones_eloignees_list=["Bouskoura", "Dar Bouazza"],
            prix_set_linge_standard=50,
            prix_piece_supp_linge=5,
            forfait_min_linge=50,
        )
        self.db_client = Client.objects.create(
            first_name="Ghali",
            last_name="Bensouda",
            phone="+212600000001",
        )
        self.bien = Bien.objects.create(
            code="BEN001",
            client=self.db_client,
            nom_bien="Appartement Marina",
            ville="Casablanca",
            quartier="Gauthier",
            adresse="12 Bd d'Anfa",
            typologie="studio",
            chambres=1,
            salles_de_bain=1,
            acces_type="boite_cle",
            acces_detail="Code 4821",
        )

    def test_codification_service(self):
        code = generate_bien_code(self.db_client)
        # last_name = Bensouda -> BEN002 (since BEN001 exists)
        self.assertEqual(code, "BEN002")

    def test_linen_calculation_rule(self):
        # 0 pcs -> 0 DH
        res = calculate_linen_pieces_and_amount({})
        self.assertEqual(res["montant"], 0)

        # 8 pcs -> 50 DH
        res = calculate_linen_pieces_and_amount({"housses": 2, "draps": 2, "taies": 4})
        self.assertEqual(res["total_pieces"], 8)
        self.assertEqual(res["montant"], 50)

        # 14 pcs -> 80 DH (1 set 50 + 6 supp * 5)
        res = calculate_linen_pieces_and_amount({"housses": 4, "draps": 4, "taies": 6})
        self.assertEqual(res["total_pieces"], 14)
        self.assertEqual(res["montant"], 80)

        # 18 pcs -> 110 DH (2 sets 100 + 2 supp * 5)
        res = calculate_linen_pieces_and_amount({"housses": 4, "draps": 4, "taies": 10})
        self.assertEqual(res["total_pieces"], 18)
        self.assertEqual(res["montant"], 110)

    def test_pricing_calculation(self):
        pricing = calculate_commande_pricing(
            bien=self.bien,
            options=[{"code": "cafe", "prix": 30}],
            remise_en_etat=0
        )
        self.assertEqual(pricing["prix_menage"], 130)
        self.assertEqual(pricing["supplement_zone"], 0)
        self.assertEqual(pricing["prix_options"], 30)
        self.assertEqual(pricing["total_ttc_hors_linge"], 160)

    def test_api_endpoints(self):
        # Test GET Biens
        res = self.client.get('/api/airbnb/biens/')
        self.assertEqual(res.status_code, 200)

        # Test POST Commande
        tomorrow = timezone.localdate() + timedelta(days=1)
        res = self.client.post('/api/airbnb/commandes/', {
            "bien": str(self.bien.id),
            "date_prestation": str(tomorrow),
            "heure_prestation": "11:00:00",
            "creneau": "matin",
            "nature_linge": "depot_ramassage",
            "options": [{"code": "cafe", "label": "Café", "prix": 30}],
        }, format='json')
        self.assertEqual(res.status_code, 201)

        # Test Calculate Price endpoint
        res = self.client.post('/api/airbnb/commandes/calculate_price/', {
            "bien_id": str(self.bien.id),
            "options": [],
            "date_prestation": str(tomorrow),
            "heure_prestation": "11:00",
            "creneau": "matin"
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["pricing"]["prix_menage"], 130)

        # Test Stats endpoint
        res = self.client.get('/api/airbnb/biens/stats/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["total_biens"], 1)
