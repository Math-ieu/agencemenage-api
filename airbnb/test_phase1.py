from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.emails import get_base_html_template
from accounts.models import RolePermission, User
from accounts.permissions import RoleBasedPermission
from accounts.serializers import UserSerializer
from agents.models import Agent
from airbnb.models import (
    AirbnbConfig,
    Bien,
    CommandeAirbnb,
    FactureLigneAirbnb,
    FiletLinge,
    GrilleTarifaireVersion,
    JournalAuditAirbnb,
    ObjetTrouve,
    ObservationLinge,
    SignalementCommande,
)
from airbnb.services.pricing_engine import calculate_commande_pricing
from clients.models import Client
from clients.serializers import ClientListSerializer, ClientSerializer
from demandes.models import AppNotification, Demande
from finance.models import EntreeCaisse, Facture, Paiement
from finance.views import PaiementViewSet


class Phase1ModelsAndDefaultsTests(TestCase):
    def test_airbnb_config_maquette_p25_defaults(self):
        cfg = AirbnbConfig.objects.create()
        self.assertEqual(cfg.prix_studio, Decimal('130.00'))
        self.assertEqual(cfg.prix_1ch, Decimal('130.00'))
        self.assertEqual(cfg.prix_2ch, Decimal('160.00'))
        self.assertEqual(cfg.prix_3ch, Decimal('190.00'))
        self.assertEqual(cfg.prix_4ch, Decimal('220.00'))
        self.assertEqual(cfg.prix_5ch, Decimal('250.00'))
        self.assertEqual(cfg.prix_villa_riad, Decimal('300.00'))
        self.assertEqual(cfg.intervenantes_par_typologie.get('villa_riad'), 2)
        self.assertEqual(cfg.seuil_biens_conciergerie, 3)
        self.assertEqual(cfg.tarif_repli_standard, Decimal('240.00'))
        self.assertEqual(cfg.delai_paiement_jours, 4)
        self.assertEqual(cfg.duree_probatoire_mois, 2)
        self.assertEqual(cfg.remplissage_max_filet_pct, 60)
        self.assertIn('Bouskoura', cfg.zones_eloignees_list)
        self.assertIn('Sidi Rahal', cfg.zones_eloignees_list)
        self.assertEqual(
            cfg.set_composition_standard,
            {'housses': 1, 'draps': 1, 'taies': 2, 'grandes_serviettes': 2, 'petites_serviettes': 2},
        )

    def test_1ch_pricing_and_observation_linge_defaults(self):
        client = Client.objects.create(first_name='Ghali', last_name='Bensouda', phone='0600000001')
        bien = Bien.objects.create(
            code='GBE001',
            client=client,
            nom_bien='Appart 1CH',
            quartier='Maarif',
            adresse='12 rue Test',
            typologie='1ch',
        )
        pricing = calculate_commande_pricing(bien)
        self.assertEqual(pricing['prix_menage'], 130.0)

        cmd = CommandeAirbnb.objects.create(
            numero='CMD-TEST-001',
            bien=bien,
            date_prestation=timezone.localdate(),
            prix_menage=Decimal('130.00'),
            total_ttc=Decimal('130.00'),
        )
        filet = FiletLinge.objects.create(
            code_filet='SAC-GBE001-01',
            bien=bien,
            commande_ramassage=cmd,
            total_pieces=8,
            sets_calcules=1,
            montant=Decimal('50.00'),
        )
        obs = ObservationLinge.objects.create(
            filet=filet,
            article='Tapis de bain',
            quantite=1,
            motif='taches_persistantes',
        )
        self.assertFalse(obs.facturee)
        self.assertEqual(obs.montant_facture, Decimal('0'))
        # La pièce signalée n'est jamais retirée du filet
        filet.refresh_from_db()
        self.assertEqual(filet.total_pieces, 8)

    def test_new_phase1_models_and_blank_trigramme_normalization(self):
        c1 = Client.objects.create(first_name='A', last_name='One', phone='0600000002', trigramme='')
        c2 = Client.objects.create(first_name='B', last_name='Two', phone='0600000003', trigramme='')
        self.assertIsNone(c1.trigramme)
        self.assertIsNone(c2.trigramme)

        grille = GrilleTarifaireVersion.objects.create(
            version_label='2026-06-01',
            date_entree_vigueur=date(2026, 6, 1),
            is_active=True,
            tarifs_json={'studio': 130, '1ch': 130},
        )
        self.assertTrue(grille.is_active)

        bien = Bien.objects.create(
            code='AON001',
            client=c1,
            quartier='Anfa',
            adresse='1 bd Anfa',
            typologie='studio',
        )
        cmd = CommandeAirbnb.objects.create(
            numero='CMD-TEST-002',
            bien=bien,
            date_prestation=timezone.localdate(),
        )
        sig = SignalementCommande.objects.create(
            commande=cmd,
            motif='bien_sale',
            heures_estimees=Decimal('2.00'),
        )
        self.assertEqual(sig.accord_client, 'en_attente')

        facture = Facture.objects.create(
            client=c1,
            source=Facture.SOURCE_AIRBNB,
            numero='FAC-AB-001',
            montant_total=Decimal('130.00'),
        )
        ligne = FactureLigneAirbnb.objects.create(
            facture=facture,
            commande=cmd,
            type_ligne='prestation',
            designation='Ménage Studio',
            montant=Decimal('130.00'),
        )
        self.assertEqual(ligne.montant, Decimal('130.00'))

        audit = JournalAuditAirbnb.objects.create(
            entite='Facture',
            entite_id=str(facture.id),
            action='emission',
        )
        self.assertEqual(audit.entite, 'Facture')

    def test_role_permission_migration_seeded_safely(self):
        for role_key in ['Responsable Facturation', 'Runner', 'Responsable Linge', 'Client Conciergerie']:
            rp = RolePermission.objects.filter(role=role_key).first()
            self.assertIsNotNone(rp, f"RolePermission manquant pour {role_key}")

        admin_rp = RolePermission.objects.get(role='Admin')
        self.assertIn('consulter_clients', admin_rp.permissions)
        self.assertIn('gerer_config_airbnb', admin_rp.permissions)

        com_rp = RolePermission.objects.get(role='commercial')
        self.assertIn('consulter_clients', com_rp.permissions)
        self.assertIn('creer_commande_airbnb', com_rp.permissions)

        ops_rp = RolePermission.objects.get(role='Chargée des Opérations')
        self.assertIn('consulter_demandes', ops_rp.permissions)
        self.assertIn('assigner_commande_airbnb', ops_rp.permissions)

    def test_user_serializer_exposes_client_and_client_name(self):
        client = Client.objects.create(
            segment=Client.ENTREPRISE,
            entity_name='StayCasa Conciergerie',
            phone='0600000010',
        )
        user = User.objects.create_user(
            email='portal@staycasa.ma',
            password='Password123!',
            role=User.CLIENT_CONCIERGERIE,
            client=client,
        )
        data = UserSerializer(user).data
        self.assertEqual(data['client'], client.id)
        self.assertEqual(data['client_name'], 'StayCasa Conciergerie')

    def test_email_template_footer_uses_numeric_year(self):
        html = get_base_html_template('Réinitialisation', '<p>Code: 123456</p>')
        year_str = str(timezone.now().year)
        self.assertIn(f"&copy; {year_str} Agence Ménage", html)


class Phase1ClientViewSetTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin_clients@test.ma', password='Password123!', role=User.ADMIN, is_staff=True
        )
        self.c1 = Client.objects.create(
            segment=Client.ENTREPRISE,
            entity_name='Atlas Hosts',
            phone='0611111111',
            trigramme='ATH',
            mode_paiement_airbnb='mensuel',
            probatoire_jusqu_au=timezone.localdate() + timedelta(days=30),
        )
        self.c2 = Client.objects.create(
            first_name='Sami',
            last_name='Classic',
            phone='0622222222',
        )
        self.bien1 = Bien.objects.create(
            code='ATH001', client=self.c1, quartier='Anfa', adresse='1 rue A', is_active=True
        )
        self.bien2 = Bien.objects.create(
            code='ATH002', client=self.c1, quartier='Anfa', adresse='2 rue A', is_active=False
        )
        self.portal_user = User.objects.create_user(
            email='atlas@conciergerie.ma',
            password='Password123!',
            role=User.CLIENT_CONCIERGERIE,
            client=self.c1,
        )
        self.rf_user = User.objects.create_user(
            email='rf@agence.ma',
            password='Password123!',
            role=User.RESPONSABLE_FACTURATION,
        )

    def test_client_serializers_computed_and_list_fields(self):
        detail_data = ClientSerializer(self.c1).data
        self.assertEqual(detail_data['nb_biens_actifs_airbnb'], 1)
        self.assertTrue(detail_data['sous_seuil_alerte'])
        self.assertTrue(detail_data['en_periode_probatoire'])

        list_data = ClientListSerializer(self.c1).data
        self.assertEqual(list_data['trigramme'], 'ATH')
        self.assertEqual(list_data['mode_paiement_airbnb'], 'mensuel')
        self.assertEqual(list_data['statut_airbnb'], 'actif')
        self.assertFalse(list_data['eligible_conciergerie'])

    def test_client_scoping_conciergerie_and_rf(self):
        self.client.force_authenticate(user=self.portal_user)
        resp = self.client.get('/api/clients/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in resp.data['results']]
        self.assertEqual(ids, [self.c1.id])

        resp_other = self.client.get(f'/api/clients/{self.c2.id}/')
        self.assertIn(resp_other.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        self.client.force_authenticate(user=self.rf_user)
        self.assertEqual(self.client.get('/api/clients/').status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post('/api/clients/', {'first_name': 'X', 'phone': '0600'}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_perform_destroy_preserves_demandes_for_airbnb_or_invoiced_client(self):
        demande_c1 = Demande.objects.create(client=self.c1, service='Grand Ménage')
        demande_c2 = Demande.objects.create(client=self.c2, service='Ménage')

        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.delete(f'/api/clients/{self.c1.id}/').status_code, status.HTTP_204_NO_CONTENT)
        self.c1.refresh_from_db()
        self.assertTrue(self.c1.is_archived)
        self.assertTrue(Demande.objects.filter(id=demande_c1.id).exists())
        self.assertTrue(Bien.objects.filter(id=self.bien1.id).exists())

        self.assertEqual(self.client.delete(f'/api/clients/{self.c2.id}/').status_code, status.HTTP_204_NO_CONTENT)
        self.c2.refresh_from_db()
        self.assertTrue(self.c2.is_archived)
        self.assertFalse(Demande.objects.filter(id=demande_c2.id).exists())


class Phase1PermissionsAndCloisonnementTests(APITestCase):
    def setUp(self):
        today = timezone.localdate()
        self.admin = User.objects.create_user(
            email='adm@t.ma', password='Password123!', role=User.ADMIN, is_staff=True
        )
        self.rc = User.objects.create_user(
            email='rc@t.ma', password='Password123!', role=User.RESPONSABLE_COMMERCIAL
        )
        self.com1 = User.objects.create_user(
            email='com1@t.ma', password='Password123!', role=User.COMMERCIAL
        )
        self.com2 = User.objects.create_user(
            email='com2@t.ma', password='Password123!', role=User.COMMERCIAL
        )
        self.rf = User.objects.create_user(
            email='rf@t.ma', password='Password123!', role=User.RESPONSABLE_FACTURATION
        )
        self.ops = User.objects.create_user(
            email='ops@t.ma', password='Password123!', role=User.CHARGE_OPERATIONS
        )
        self.resp_ops = User.objects.create_user(
            email='rops@t.ma', password='Password123!', role=User.RESPONSABLE_OPERATIONS
        )
        self.runner1 = User.objects.create_user(
            email='run1@t.ma', password='Password123!', role=User.RUNNER, first_name='Ali', last_name='Runner'
        )
        self.runner2 = User.objects.create_user(
            email='run2@t.ma', password='Password123!', role=User.RUNNER, first_name='Badr', last_name='Runner'
        )
        self.rl = User.objects.create_user(
            email='rl@t.ma', password='Password123!', role=User.RESPONSABLE_LINGE
        )

        self.client_a = Client.objects.create(
            first_name='Client', last_name='Alpha', phone='0610000001',
            email='alpha@host.ma', assigned_commercial=self.com1, trigramme='CAL',
        )
        self.client_b = Client.objects.create(
            first_name='Client', last_name='Beta', phone='0610000002',
            email='beta@host.ma', assigned_commercial=self.com2, trigramme='CBE',
        )
        self.portal_a = User.objects.create_user(
            email='portal_a@t.ma', password='Password123!', role=User.CLIENT_CONCIERGERIE, client=self.client_a
        )

        self.bien_a = Bien.objects.create(
            code='CAL001',
            client=self.client_a,
            nom_bien='Loft Alpha',
            quartier='Gauthier',
            adresse='15 Rue Jean Jaurès',
            acces_detail='Digicode 4589#',
            gardien_nom='M. Hassan',
            typologie='2ch',
        )
        self.bien_b = Bien.objects.create(
            code='CBE001',
            client=self.client_b,
            nom_bien='Studio Beta',
            quartier='Bourgogne',
            adresse='99 Rue Beta',
            acces_detail='Boite 9999',
            gardien_nom='M. Omar',
            typologie='studio',
        )
        self.agent = Agent.objects.create(first_name='Fatima', last_name='Zahra', phone='0655555555')

        self.cmd_today_r1 = CommandeAirbnb.objects.create(
            numero='CMD-2026-0101',
            bien=self.bien_a,
            date_prestation=today,
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
            nature_linge='depot_ramassage',
            intervenante=self.agent,
            runner=self.runner1,
            statut='assignee',
        )
        self.cmd_tomorrow_r1 = CommandeAirbnb.objects.create(
            numero='CMD-2026-0102',
            bien=self.bien_a,
            date_prestation=today + timedelta(days=1),
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
            nature_linge='depot_ramassage',
            intervenante=self.agent,
            runner=self.runner1,
            statut='assignee',
        )
        self.cmd_today_r2 = CommandeAirbnb.objects.create(
            numero='CMD-2026-0103',
            bien=self.bien_b,
            date_prestation=today,
            prix_menage=Decimal('130.00'),
            total_ttc=Decimal('130.00'),
            nature_linge='depot_ramassage',
            intervenante=self.agent,
            runner=self.runner2,
            statut='assignee',
        )
        self.filet_r1 = FiletLinge.objects.create(
            code_filet='SAC-CAL001-01',
            bien=self.bien_a,
            commande_ramassage=self.cmd_today_r1,
            montant=Decimal('90.00'),
            total_pieces=16,
            sets_calcules=1,
            pieces_supp_calculees=8,
        )
        self.filet_r2 = FiletLinge.objects.create(
            code_filet='SAC-CBE001-01',
            bien=self.bien_b,
            commande_ramassage=self.cmd_today_r2,
            montant=Decimal('50.00'),
        )
        self.objet_a = ObjetTrouve.objects.create(
            commande=self.cmd_today_r1,
            bien=self.bien_a,
            description='Chargeur iPhone',
        )
        self.facture_airbnb_a = Facture.objects.create(
            client=self.client_a,
            source=Facture.SOURCE_AIRBNB,
            numero='FAC-AB-101',
            montant_total=Decimal('160.00'),
            date_echeance=today + timedelta(days=4),
        )
        self.facture_airbnb_b = Facture.objects.create(
            client=self.client_b,
            source=Facture.SOURCE_AIRBNB,
            numero='FAC-AB-102',
            montant_total=Decimal('130.00'),
            date_echeance=today + timedelta(days=4),
        )
        demande_classic = Demande.objects.create(client=self.client_a, service='Ménage Classique')
        self.facture_classique = Facture.objects.create(
            client=self.client_a,
            demande=demande_classic,
            source=Facture.SOURCE_CLASSIQUE,
            numero='FAC-CL-001',
            montant_total=Decimal('250.00'),
        )

    def test_config_permissions_admin_only_write(self):
        cfg = AirbnbConfig.objects.create()
        for u in [self.rc, self.com1, self.rf, self.ops]:
            self.client.force_authenticate(user=u)
            self.assertEqual(self.client.get('/api/airbnb/config/').status_code, status.HTTP_200_OK)
            self.assertEqual(
                self.client.patch(f'/api/airbnb/config/{cfg.id}/', {'prix_studio': 150}).status_code,
                status.HTTP_403_FORBIDDEN,
            )

        for u in [self.runner1, self.rl, self.portal_a]:
            self.client.force_authenticate(user=u)
            self.assertEqual(self.client.get('/api/airbnb/config/').status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.patch(f'/api/airbnb/config/{cfg.id}/', {'prix_studio': '130.00'}).status_code,
            status.HTTP_200_OK,
        )

    def test_responsable_linge_strict_cloisonnement(self):
        self.client.force_authenticate(user=self.rl)
        self.assertEqual(self.client.get('/api/airbnb/biens/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(f'/api/airbnb/biens/{self.bien_a.id}/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/airbnb/commandes/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/airbnb/objets-trouves/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/finance/factures/').status_code, status.HTTP_403_FORBIDDEN)

        # Mais la responsable linge peut gérer les filets et figer le montant
        self.assertEqual(self.client.get('/api/airbnb/filets/').status_code, status.HTTP_200_OK)

        # Even if serializer is invoked with responsable_linge context, sensitive Bien/Commande fields are stripped
        from airbnb.serializers import BienDetailSerializer, CommandeAirbnbDetailSerializer

        class DummyReq:
            def __init__(self, user):
                self.user = user

        rl_cmd = CommandeAirbnbDetailSerializer(
            self.cmd_today_r1, context={'request': DummyReq(self.rl)}
        ).data
        for k in ['prix_menage', 'total_ttc', 'prix_options']:
            self.assertNotIn(k, rl_cmd)
        for k in ['adresse', 'acces_detail', 'gardien_nom']:
            self.assertNotIn(k, rl_cmd['bien_details'])
        rl_bien = BienDetailSerializer(self.bien_a, context={'request': DummyReq(self.rl)}).data
        self.assertNotIn('acces_detail', rl_bien)

    def test_runner_strict_cloisonnement_scope_and_fields(self):
        self.client.force_authenticate(user=self.runner1)

        # Commandes : uniquement ses commandes du jour, sans prix ni intervenantes
        resp_cmds = self.client.get('/api/airbnb/commandes/')
        self.assertEqual(resp_cmds.status_code, status.HTTP_200_OK)
        cmds = resp_cmds.data['results']
        self.assertEqual([c['numero'] for c in cmds], ['CMD-2026-0101'])
        for hidden_key in ['prix_menage', 'total_ttc', 'intervenante', 'intervenante_name', 'facture', 'montant_linge']:
            self.assertNotIn(hidden_key, cmds[0])

        # Détail de SA commande du jour : prix, intervenante et montant du filet imbriqué masqués
        resp_detail = self.client.get(f'/api/airbnb/commandes/{self.cmd_today_r1.id}/')
        self.assertEqual(resp_detail.status_code, status.HTTP_200_OK)
        for hidden_key in ['prix_menage', 'total_ttc', 'intervenante', 'facture', 'montant_linge']:
            self.assertNotIn(hidden_key, resp_detail.data)
        self.assertNotIn('client_phone', resp_detail.data['bien_details'])
        self.assertNotIn('montant', resp_detail.data['filets_ramasses'][0])

        # Détail commande autre jour ou autre runner bloqué (404 via get_queryset)
        self.assertEqual(
            self.client.get(f'/api/airbnb/commandes/{self.cmd_tomorrow_r1.id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(f'/api/airbnb/commandes/{self.cmd_today_r2.id}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )

        # PDF data : intervenantes masquées pour runner
        pdf_resp = self.client.get(f'/api/airbnb/commandes/{self.cmd_today_r1.id}/mission_pdf_data/')
        self.assertEqual(pdf_resp.status_code, status.HTTP_200_OK)
        self.assertNotIn('intervenantes', pdf_resp.data)

        # Filets : uniquement ses filets, sans montant
        resp_filets = self.client.get('/api/airbnb/filets/')
        self.assertEqual(resp_filets.status_code, status.HTTP_200_OK)
        filets = resp_filets.data['results']
        self.assertEqual(len(filets), 1)
        self.assertEqual(filets[0]['code_filet'], 'SAC-CAL001-01')
        self.assertNotIn('montant', filets[0])

        # Tournée runner : ne permet pas de voir demain ou autre runner même avec ?date=
        tomorrow_str = str(timezone.localdate() + timedelta(days=1))
        tournee_resp = self.client.get(f'/api/airbnb/filets/tournee_runner/?date={tomorrow_str}')
        self.assertEqual(tournee_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(tournee_resp.data['date'], str(timezone.localdate()))
        self.assertEqual(len(tournee_resp.data['missions_runner']), 1)
        self.assertNotIn('prix_menage', tournee_resp.data['missions_runner'][0])

        # Biens : pas de téléphone/email client dans le détail
        resp_bien = self.client.get(f'/api/airbnb/biens/{self.bien_a.id}/')
        self.assertEqual(resp_bien.status_code, status.HTTP_200_OK)
        self.assertNotIn('client_phone', resp_bien.data)
        self.assertNotIn('client_email', resp_bien.data)

    def test_client_conciergerie_scope_and_masked_identities(self):
        self.client.force_authenticate(user=self.portal_a)

        # Biens : uniquement ceux de client_a
        resp_biens = self.client.get('/api/airbnb/biens/')
        self.assertEqual(resp_biens.status_code, status.HTTP_200_OK)
        self.assertEqual([b['code'] for b in resp_biens.data['results']], ['CAL001'])

        # Interdiction de créer un bien pour client_b
        create_bien = self.client.post('/api/airbnb/biens/', {
            'code': 'CBE999',
            'client': self.client_b.id,
            'quartier': 'Anfa',
            'adresse': 'Autre',
            'typologie': 'studio',
        }, format='json')
        self.assertEqual(create_bien.status_code, status.HTTP_403_FORBIDDEN)

        # Commandes : identité intervenante et runner masquée
        resp_cmds = self.client.get('/api/airbnb/commandes/')
        self.assertEqual(resp_cmds.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_cmds.data['results']), 2)
        for hidden_key in ['intervenante', 'intervenante_name', 'runner', 'runner_name']:
            self.assertNotIn(hidden_key, resp_cmds.data['results'][0])

        # Actions backoffice interdites
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{self.cmd_today_r1.id}/assigner/', {'intervenante_id': self.agent.id}).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{self.cmd_today_r1.id}/cloturer/', {'photos': ['1', '2', '3', '4']}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_commercial_vs_rc_vs_rf_permissions_matrix(self):
        # Commercial assigné voit uniquement client_a
        self.client.force_authenticate(user=self.com1)
        resp_biens = self.client.get('/api/airbnb/biens/')
        self.assertEqual([b['code'] for b in resp_biens.data['results']], ['CAL001'])
        self.assertEqual(
            self.client.post(f'/api/airbnb/commandes/{self.cmd_today_r1.id}/assigner/', {'intervenante_id': self.agent.id}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # FacturationAirbnbViewSet & GrilleTarifaire permissions check via RoleBasedPermission
        perm = RoleBasedPermission()

        class DummyView:
            def __init__(self, name, action):
                self.__class__.__name__ = name
                self.action = action

        class DummyReq:
            def __init__(self, user, method='POST', data=None):
                self.user = user
                self.method = method
                self.data = data or {}

        for role_user, expected in [(self.com1, False), (self.rc, True), (self.admin, True), (self.ops, False)]:
            v = type('CommandeAirbnbViewSet', (), {'action': 'forcer_prix'})()
            self.assertEqual(perm.has_permission(DummyReq(role_user, 'POST'), v), expected)

        for role_user, expected in [(self.com1, False), (self.rc, True), (self.rf, True), (self.admin, True)]:
            v = type('FacturationAirbnbViewSet', (), {'action': 'annuler_bascule_mensuelle'})()
            self.assertEqual(perm.has_permission(DummyReq(role_user, 'POST'), v), expected)

        for role_user, expected in [(self.com1, False), (self.rc, False), (self.rf, True), (self.admin, True)]:
            v = type('FacturationAirbnbViewSet', (), {'action': 'lever_suspension'})()
            self.assertEqual(perm.has_permission(DummyReq(role_user, 'POST'), v), expected)

    def test_facture_and_paiement_source_airbnb_permissions(self):
        # Responsable Facturation voit uniquement Airbnb, peut créer facture Airbnb
        self.client.force_authenticate(user=self.rf)
        resp_rf = self.client.get('/api/finance/factures/')
        self.assertEqual(resp_rf.status_code, status.HTTP_200_OK)
        nums = {f['numero'] for f in resp_rf.data['results']}
        self.assertEqual(nums, {'FAC-AB-101', 'FAC-AB-102'})

        # RF ne peut pas supprimer de facture ni créer de facture classique
        self.assertEqual(
            self.client.delete(f'/api/finance/factures/{self.facture_airbnb_a.id}/').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post('/api/finance/factures/', {
                'client': self.client_a.id,
                'source': 'classique',
                'numero': 'FAC-CL-999',
                'montant_total': '100.00',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Client Conciergerie : uniquement ses propres factures Airbnb, lecture seule
        self.client.force_authenticate(user=self.portal_a)
        resp_portal = self.client.get('/api/finance/factures/')
        self.assertEqual(resp_portal.status_code, status.HTTP_200_OK)
        self.assertEqual([f['numero'] for f in resp_portal.data['results']], ['FAC-AB-101'])
        self.assertEqual(
            self.client.post('/api/finance/factures/', {'numero': 'X'}).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Commercial : lecture seule sur Airbnb de son client, bloqué en création Airbnb
        self.client.force_authenticate(user=self.com1)
        resp_com = self.client.get('/api/finance/factures/?source=airbnb')
        self.assertEqual(resp_com.status_code, status.HTTP_200_OK)
        self.assertEqual([f['numero'] for f in resp_com.data['results']], ['FAC-AB-101'])
        self.assertEqual(
            self.client.post('/api/finance/factures/', {
                'client': self.client_a.id,
                'source': 'airbnb',
                'numero': 'FAC-AB-999',
                'montant_total': '100.00',
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post('/api/finance/paiements/', {
                'facture': self.facture_airbnb_a.id,
                'montant': '160.00',
                'mode': 'virement',
                'date': str(timezone.localdate()),
            }).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # Chargée Ops : pas d'accès factures ; Responsable Ops : uniquement classiques, pas Airbnb
        self.client.force_authenticate(user=self.ops)
        self.assertEqual(self.client.get('/api/finance/factures/').status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.resp_ops)
        resp_rops = self.client.get('/api/finance/factures/')
        self.assertEqual(resp_rops.status_code, status.HTTP_200_OK)
        rops_nums = [f['numero'] for f in resp_rops.data['results']]
        self.assertIn('FAC-CL-001', rops_nums)
        self.assertNotIn('FAC-AB-101', rops_nums)


class Phase1FinanceHooksAndSuspensionTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.rf = User.objects.create_user(
            email='rf_hook@t.ma', password='Password123!', role=User.RESPONSABLE_FACTURATION
        )
        self.client_susp = Client.objects.create(
            entity_name='Conciergerie Suspendue',
            segment=Client.ENTREPRISE,
            phone='0677777777',
            statut_airbnb='suspendu',
            trigramme='CSU',
        )
        self.bien = Bien.objects.create(
            code='CSU001',
            client=self.client_susp,
            quartier='Anfa',
            adresse='5 rue S',
            typologie='studio',
        )
        self.cmd_future_cancelled = CommandeAirbnb.objects.create(
            numero='CMD-FUT-001',
            bien=self.bien,
            date_prestation=self.today + timedelta(days=3),
            statut='annulee',
            annulee_par_suspension=True,
        )
        self.cmd_past_cancelled = CommandeAirbnb.objects.create(
            numero='CMD-PAS-001',
            bien=self.bien,
            date_prestation=self.today - timedelta(days=1),
            statut='annulee',
            annulee_par_suspension=True,
        )
        self.overdue_1 = Facture.objects.create(
            client=self.client_susp,
            source=Facture.SOURCE_AIRBNB,
            numero='FAC-OVER-01',
            montant_total=Decimal('130.00'),
            date_echeance=self.today - timedelta(days=2),
        )
        self.overdue_2 = Facture.objects.create(
            client=self.client_susp,
            source=Facture.SOURCE_AIRBNB,
            numero='FAC-OVER-02',
            montant_total=Decimal('130.00'),
            date_echeance=self.today - timedelta(days=1),
        )

    def test_payment_creates_caisse_and_lifts_suspension_when_last_overdue_paid(self):
        self.client.force_authenticate(user=self.rf)

        # Paiement 1 : virement -> EntreeCaisse trésorerie, client reste suspendu car overdue_2 reste due
        r1 = self.client.post('/api/finance/paiements/', {
            'facture': self.overdue_1.id,
            'montant': '130.00',
            'mode': Paiement.VIREMENT,
            'date': str(self.today),
            'reference': 'VIR-001',
        }, format='json')
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)

        ec1 = EntreeCaisse.objects.get(paiement_id=r1.data['id'])
        self.assertEqual(ec1.type_mouvement, EntreeCaisse.ENTREE)
        self.assertEqual(ec1.caisse_type, EntreeCaisse.TRESORERIE)
        self.assertEqual(ec1.categorie, 'Virement client reçu')
        self.assertEqual(ec1.client_id, self.client_susp.id)

        self.client_susp.refresh_from_db()
        self.assertEqual(self.client_susp.statut_airbnb, 'suspendu')

        # Paiement 2 : espèces -> EntreeCaisse caisse, lève la suspension et rend cmd_future réactivable
        r2 = self.client.post('/api/finance/paiements/', {
            'facture': self.overdue_2.id,
            'montant': '130.00',
            'mode': Paiement.ESPECES,
            'date': str(self.today),
        }, format='json')
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

        ec2 = EntreeCaisse.objects.get(paiement_id=r2.data['id'])
        self.assertEqual(ec2.caisse_type, EntreeCaisse.CAISSE)
        self.assertEqual(ec2.categorie, 'Encaissement client (auto)')

        self.client_susp.refresh_from_db()
        self.assertEqual(self.client_susp.statut_airbnb, 'actif')

        self.cmd_future_cancelled.refresh_from_db()
        self.cmd_past_cancelled.refresh_from_db()
        self.assertTrue(self.cmd_future_cancelled.reactivable_apres_suspension)
        self.assertFalse(self.cmd_past_cancelled.reactivable_apres_suspension)

        self.assertTrue(
            JournalAuditAirbnb.objects.filter(
                entite='Client',
                entite_id=str(self.client_susp.id),
                action='suspension_levee_automatique',
            ).exists()
        )

    def test_skip_caisse_hook_prevents_duplicate_caisse_entry(self):
        paiement = Paiement.objects.create(
            facture=self.overdue_1,
            montant=Decimal('130.00'),
            mode=Paiement.VIREMENT,
            date=self.today,
            created_by=self.rf,
        )
        paiement._skip_caisse_hook = True
        view = PaiementViewSet()

        class DummyReq:
            def __init__(self, user):
                self.user = user

        view.request = DummyReq(self.rf)
        view._sync_airbnb_caisse_and_suspension(paiement, self.overdue_1)
        self.assertFalse(EntreeCaisse.objects.filter(paiement=paiement).exists())


class Phase1AppNotificationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='n_adm@t.ma', password='Password123!', role=User.ADMIN)
        self.charge_ops = User.objects.create_user(
            email='n_cops@t.ma', password='Password123!', role=User.CHARGE_OPERATIONS
        )
        self.resp_ops = User.objects.create_user(
            email='n_rops@t.ma', password='Password123!', role=User.RESPONSABLE_OPERATIONS
        )
        self.commercial = User.objects.create_user(
            email='n_com@t.ma', password='Password123!', role=User.COMMERCIAL
        )
        self.conciergerie = User.objects.create_user(
            email='n_cli@t.ma', password='Password123!', role=User.CLIENT_CONCIERGERIE
        )

        self.n_ops = AppNotification.objects.create(
            type='airbnb_tdb',
            title='Remontée TDB 18h',
            message='Commandes prêtes',
            target_roles=['operations'],
            lien_url='/airbnb/commandes',
        )
        self.n_user = AppNotification.objects.create(
            type='airbnb_commande',
            title='Commande ciblée',
            message='Uniquement pour ce commercial',
            target_user=self.commercial,
            target_roles=[],
        )
        self.n_broadcast = AppNotification.objects.create(
            type='info',
            title='Broadcast interne',
            message='Interne agence',
            target_roles=[],
        )

    def test_notification_queryset_target_user_and_operations_mapping(self):
        # charge_operations & responsable_operations voient target_roles=['operations'] mais pas n_user
        for u in [self.charge_ops, self.resp_ops]:
            self.client.force_authenticate(user=u)
            resp = self.client.get('/api/notifications/')
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            titles = {n['title'] for n in resp.data}
            self.assertIn('Remontée TDB 18h', titles)
            self.assertIn('Broadcast interne', titles)
            self.assertNotIn('Commande ciblée', titles)

        # commercial ciblé voit n_user, ne voit pas n_ops
        self.client.force_authenticate(user=self.commercial)
        titles_com = {n['title'] for n in self.client.get('/api/notifications/').data}
        self.assertIn('Commande ciblée', titles_com)
        self.assertNotIn('Remontée TDB 18h', titles_com)

        # client_conciergerie ne voit ni broadcast interne ni ops ni n_user
        self.client.force_authenticate(user=self.conciergerie)
        self.assertEqual(self.client.get('/api/notifications/').data, [])
