import datetime
import io
import os
import tempfile
from decimal import Decimal
from unittest.mock import patch

from PIL import Image
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient, APITestCase

from accounts.emails import send_account_creation_email, send_holiday_suspension_email
from accounts.models import RolePermission, User
from accounts.serializers import (
    ChangePasswordSerializer,
    ResetPasswordSerializer,
    UserCreateSerializer,
)
from agencemenage.utils import sanitize_csv_cell
from agencemenage.validators import validate_uploaded_document
from agents.models import Agent, AgentExperience
from agents.serializers import AgentSerializer, PublicAgentProfileSerializer
from airbnb.models import Bien, CommandeAirbnb
from airbnb.serializers import BienDetailSerializer
from airbnb.services.billing_engine import _create_facture_for_commandes
from airbnb.services.notification_service import notify_facture_emise
from blog.models import Category, Post
from clients.models import Client
from clients.serializers import ClientSerializer
from demandes.models import Demande, ProfilShare
from demandes.serializers import DocumentSerializer
from demandes.utils.document_generators import generate_devis_pdf
from demandes.utils.invoice_generator import InvoiceData, InvoiceItem, generate_invoice
from finance.models import EntreeCaisse, Facture
from finance.serializers import EntreeCaisseSerializer, FactureSerializer, PaiementSerializer
from marketing.models import PromoCode
from marketing.serializers import CommercialGestureSerializer
from marketing.validators import validate_promo_for_booking


def _make_png_bytes(width=8, height=8) -> bytes:
    buf = io.BytesIO()
    img = Image.new('RGB', (width, height), color=(15, 138, 125))
    img.save(buf, format='PNG')
    return buf.getvalue()


class SecurityP1SessionsAndPasswordsTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email='user-p1@agencemenage.ma',
            password='VeryStrongPassword99!',
            first_name='Nadia',
            last_name='Test',
            role='commercial',
        )

    def tearDown(self):
        cache.clear()

    def test_jwt_cookies_have_numeric_max_age_and_blacklist_on_rotation_and_logout(self):
        c = APIClient(enforce_csrf_checks=True)
        login_resp = c.post(
            '/api/auth/login/',
            {'email': self.user.email, 'password': 'VeryStrongPassword99!'},
            format='json',
        )
        self.assertEqual(login_resp.status_code, 200)
        access_cookie = login_resp.cookies['access_token']
        refresh_cookie = login_resp.cookies['refresh_token']
        self.assertTrue(str(access_cookie['max-age']).isdigit())
        self.assertGreater(int(access_cookie['max-age']), 0)
        self.assertEqual(access_cookie['path'], '/')
        self.assertTrue(str(refresh_cookie['max-age']).isdigit())
        self.assertEqual(refresh_cookie['path'], '/')

        old_refresh = refresh_cookie.value
        csrf_tok = login_resp.data['csrf_token']

        # Refresh rotates token and blacklists old refresh token
        ref_resp = c.post('/api/auth/refresh/', {}, format='json', HTTP_X_CSRFTOKEN=csrf_tok)
        self.assertEqual(ref_resp.status_code, 200)
        new_refresh = ref_resp.cookies['refresh_token'].value
        self.assertNotEqual(old_refresh, new_refresh)

        # Replaying old rotated refresh token must fail with 401
        replay_client = APIClient(enforce_csrf_checks=True)
        replay_csrf = replay_client.get('/api/auth/csrf/').data['csrfToken']
        replay_client.cookies['refresh_token'] = old_refresh
        replay_resp = replay_client.post('/api/auth/refresh/', {}, format='json', HTTP_X_CSRFTOKEN=replay_csrf)
        self.assertEqual(replay_resp.status_code, 401)

        # Logout blacklists current refresh token too
        csrf_tok = ref_resp.data['csrf_token']
        logout_resp = c.post('/api/auth/logout/', {}, format='json', HTTP_X_CSRFTOKEN=csrf_tok)
        self.assertEqual(logout_resp.status_code, 200)

        replay_client.cookies['refresh_token'] = new_refresh
        post_logout_ref = replay_client.post('/api/auth/refresh/', {}, format='json', HTTP_X_CSRFTOKEN=replay_csrf)
        self.assertEqual(post_logout_ref.status_code, 401)

    def test_change_password_revokes_existing_refresh_tokens(self):
        c = APIClient(enforce_csrf_checks=True)
        login_resp = c.post(
            '/api/auth/login/',
            {'email': self.user.email, 'password': 'VeryStrongPassword99!'},
            format='json',
        )
        self.assertEqual(login_resp.status_code, 200)
        refresh_before = login_resp.cookies['refresh_token'].value
        csrf_tok = login_resp.data['csrf_token']

        cp_resp = c.post(
            '/api/auth/change-password/',
            {
                'old_password': 'VeryStrongPassword99!',
                'new_password': 'AnotherUltraStrong99!',
            },
            format='json',
            HTTP_X_CSRFTOKEN=csrf_tok,
        )
        self.assertEqual(cp_resp.status_code, 200)

        # Previous refresh token must now be blacklisted
        c.cookies['refresh_token'] = refresh_before
        ref_after = c.post('/api/auth/refresh/', {}, format='json', HTTP_X_CSRFTOKEN=csrf_tok)
        self.assertEqual(ref_after.status_code, 401)

    def test_password_validators_enforced_across_auth_serializers(self):
        create_ser = UserCreateSerializer(
            data={
                'email': 'weakuser@agencemenage.ma',
                'password': 'password',
                'first_name': 'Weak',
                'last_name': 'User',
                'role': 'commercial',
            }
        )
        self.assertFalse(create_ser.is_valid())
        self.assertIn('password', create_ser.errors)

        req = type('Req', (), {'user': self.user})()
        change_ser = ChangePasswordSerializer(
            data={'old_password': 'VeryStrongPassword99!', 'new_password': '12345678'},
            context={'request': req},
        )
        self.assertFalse(change_ser.is_valid())
        self.assertIn('new_password', change_ser.errors)

        reset_ser = ResetPasswordSerializer(
            data={'login': self.user.email, 'code': '123456', 'new_password': 'password123'}
        )
        self.assertFalse(reset_ser.is_valid())
        self.assertIn('new_password', reset_ser.errors)


class SecurityP1EscapingUploadsPaginationIntegrityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.media_dir = tempfile.mkdtemp(prefix='agm_p1_media_')
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir)
        self.media_override.enable()

        self.admin = User.objects.create_user(
            email='admin-p1@agencemenage.ma',
            password='VeryStrongPassword99!',
            first_name='Admin',
            last_name='P1',
            role='admin',
            is_staff=True,
        )
        self.commercial = User.objects.create_user(
            email='com-p1@agencemenage.ma',
            password='VeryStrongPassword99!',
            first_name='Com',
            last_name='P1',
            role='commercial',
        )
        self.airbnb_client = Client.objects.create(
            first_name='<b>Oasis & Co</b>',
            last_name='Host',
            entity_name='<script>alert(1)</script> & Co',
            phone='0677777777',
            email='oasis-p1@example.com',
            segment=Client.ENTREPRISE,
            type_client_airbnb='conciergerie',
            trigramme='OAP',
        )
        self.conciergerie_user = User.objects.create_user(
            email='host-p1@example.com',
            password='VeryStrongPassword99!',
            first_name='Host',
            last_name='Concierge',
            role='client_conciergerie',
            client=self.airbnb_client,
        )

        RolePermission.objects.update_or_create(
            role='commercial',
            defaults={
                'permissions': [
                    'demandes_voir',
                    'consulter_clients',
                    'modifier_clients',
                    'consulter_agents',
                    'modifier_agents',
                    'creer_geste_commercial',
                    'caisse_voir',
                ]
            },
        )
        RolePermission.objects.update_or_create(
            role='Client Conciergerie',
            defaults={
                'permissions': [
                    'airbnb_biens_voir',
                    'airbnb_biens_creer',
                    'airbnb_biens_modifier',
                    'airbnb_commandes_voir',
                    'airbnb_upload_photo',
                ]
            },
        )

    def tearDown(self):
        cache.clear()
        self.media_override.disable()
        import shutil
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_reportlab_pdfs_handle_xml_html_payloads_safely(self):
        inv_bytes = generate_invoice(
            InvoiceData(
                invoice_number='FAC & <1>',
                invoice_date=timezone.localdate(),
                client_name='<script>alert(1)</script> & SARL',
                client_ice='001 & <ICE>',
                client_address='10 Rue <img src="x"/> Casa',
                service_type='Ménage & <Bureaux>',
                frequency='1x/sem & <ok>',
                items=[InvoiceItem(designation='<para>Bad</para> & nettoyage', amount=500.0)],
                reduction_label='<font color="red">VIP</font>',
                reduction_amount=50.0,
            )
        ).getvalue()
        self.assertTrue(inv_bytes.startswith(b'%PDF-'))

        devis_bytes = generate_devis_pdf({
            'numero': 'DEV-1',
            'date': '27/11/2026',
            'client_nom': '<b>Client & Co</b>',
            'client_telephone': '0600000000',
            'client_adresse': 'Rue 1',
            'service_type': 'Ménage',
            'segment': 'Particulier',
            'intervenants': 2,
            'frequence': 'Ponctuel',
            'total': '300',
            'description': 'Ligne 1 & <script>alert(1)</script>\nLigne 2 <img src="evil"/>',
        })
        self.assertTrue(devis_bytes.startswith(b'%PDF-'))

    def test_email_templates_escape_html_and_sanitize_subjects(self):
        captured = []

        def fake_resend(to_email, subject, html_content):
            captured.append((to_email, subject, html_content))
            return True

        evil_user = User(
            email='evil@example.com',
            username='<img src=x>',
            first_name='<script>alert(1)</script>',
            last_name="Test\r\nBcc: evil@attacker.com",
        )
        with patch('accounts.emails.send_resend_email', side_effect=fake_resend):
            send_account_creation_email(evil_user)
            send_holiday_suspension_email(
                evil_user,
                client_name='<script>xss</script>',
                fete_label="Aid\r\nHeader: inject",
                debut='01/01',
                fin='02/01',
                passage='01/01',
            )

        self.assertEqual(len(captured), 2)
        for _, subject, html_doc in captured:
            self.assertNotIn('\r', subject)
            self.assertNotIn('\n', subject)
            self.assertNotIn('<script>alert(1)</script>', html_doc)
            self.assertNotIn('<script>xss</script>', html_doc)
            self.assertIn('&lt;script&gt;', html_doc)

        fact = Facture(
            client=self.airbnb_client,
            numero='FAC-ESC-1',
            montant_total=Decimal('100.00'),
            date_echeance=timezone.localdate(),
        )
        with override_settings(RESEND_API_KEY='test-key'), patch(
            'airbnb.services.notification_service.send_resend_email',
            side_effect=fake_resend,
        ), patch('airbnb.services.notification_service.WhatsAppService.send_template_message'):
            notify_facture_emise(fact)

        self.assertEqual(len(captured), 3)
        self.assertNotIn('<script>alert(1)</script>', captured[2][2])
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', captured[2][2])

    def test_csv_formula_neutralization_helper_and_exports(self):
        self.assertEqual(sanitize_csv_cell('=CMD|calc!A0'), "'=CMD|calc!A0")
        self.assertEqual(sanitize_csv_cell('+SUM(A1:A2)'), "'+SUM(A1:A2)")
        self.assertEqual(sanitize_csv_cell('-1+1'), "'-1+1")
        self.assertEqual(sanitize_csv_cell('@SUM(1,1)'), "'@SUM(1,1)")
        self.assertEqual(sanitize_csv_cell('-120.50'), '-120.50')
        self.assertEqual(sanitize_csv_cell('42'), '42')

        Demande.objects.create(client=self.airbnb_client, service='=HYPERLINK("http://evil","x")')
        EntreeCaisse.objects.create(
            type_mouvement='entree',
            montant=Decimal('100.00'),
            description='+cmd|test',
            date=timezone.localdate(),
        )

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)

        dem_csv = admin_client.get('/api/demandes/export_csv/').content.decode('utf-8')
        self.assertIn("'=HYPERLINK", dem_csv)

        caisse_csv = admin_client.get('/api/finance/caisse/export_csv/').content.decode('utf-8')
        self.assertIn("'+cmd|test", caisse_csv)

    def test_upload_validators_and_airbnb_photo_upload_view(self):
        fake_pdf = SimpleUploadedFile('evil.pdf', b'<script>alert(1)</script>', content_type='application/pdf')
        with self.assertRaises(drf_serializers.ValidationError):
            validate_uploaded_document(fake_pdf)

        real_pdf = SimpleUploadedFile('ok.pdf', b'%PDF-1.4\n%test', content_type='application/pdf')
        self.assertEqual(validate_uploaded_document(real_pdf).name, 'ok.pdf')

        host_client = APIClient()
        host_client.force_authenticate(user=self.conciergerie_user)

        bad_upload = host_client.post(
            '/api/airbnb/upload-photo/',
            {'file': SimpleUploadedFile('xss.svg', b'<svg onload="alert(1)"/>', content_type='image/svg+xml')},
            format='multipart',
        )
        self.assertEqual(bad_upload.status_code, 400)

        bad_pdf_upload = host_client.post(
            '/api/airbnb/upload-photo/',
            {'file': SimpleUploadedFile('fake.pdf', b'not-a-pdf', content_type='application/pdf')},
            format='multipart',
        )
        self.assertEqual(bad_pdf_upload.status_code, 400)

        good_png = SimpleUploadedFile('room.png', _make_png_bytes(), content_type='image/png')
        with patch('django.core.files.storage.default_storage.save', side_effect=RuntimeError('S3 credential leaked')):
            err_resp = host_client.post('/api/airbnb/upload-photo/', {'file': good_png}, format='multipart')
        self.assertEqual(err_resp.status_code, 500)
        self.assertNotIn('S3 credential leaked', err_resp.data['error'])

        # DocumentSerializer rejects disguised HTML document
        dem = Demande.objects.create(client=self.airbnb_client, service='Ménage')
        doc_ser = DocumentSerializer(data={
            'demande': dem.id,
            'type_document': 'devis',
            'nom': 'evil.html',
            'fichier': SimpleUploadedFile('evil.html', b'<html></html>', content_type='text/html'),
        })
        self.assertFalse(doc_ser.is_valid())
        self.assertIn('fichier', doc_ser.errors)

    def test_pagination_no_page_restricted_to_internal_staff(self):
        cat = Category.objects.create(name='CatP1')
        for idx in range(25):
            Post.objects.create(
                title=f'Post {idx}',
                slug=f'post-p1-{idx}',
                content='Texte',
                category=cat,
                status=Post.PUBLISHED,
            )

        anon = APIClient()
        anon_resp = anon.get('/api/public/blog/posts/?no_page=true&page_size=500')
        self.assertEqual(anon_resp.status_code, 200)
        self.assertIsInstance(anon_resp.data, dict)
        self.assertIn('results', anon_resp.data)

        for idx in range(22):
            Bien.objects.create(
                code=f'P1B{idx:02d}',
                client=self.airbnb_client,
                ville='Casablanca',
                quartier='Maarif',
                adresse=f'Rue {idx}',
                typologie='1ch',
            )

        conc = APIClient()
        conc.force_authenticate(user=self.conciergerie_user)
        conc_resp = conc.get('/api/airbnb/biens/?no_page=true')
        self.assertEqual(conc_resp.status_code, 200)
        self.assertIsInstance(conc_resp.data, dict)
        self.assertIn('results', conc_resp.data)
        self.assertEqual(len(conc_resp.data['results']), 20)

        staff = APIClient()
        staff.force_authenticate(user=self.admin)
        staff_resp = staff.get('/api/airbnb/biens/?no_page=true')
        self.assertEqual(staff_resp.status_code, 200)
        self.assertIsInstance(staff_resp.data, list)
        self.assertGreaterEqual(len(staff_resp.data), 22)

    def test_mass_assignment_experiences_blacklist_and_integrity_guards(self):
        # 1. AgentSerializer PATCH without experiences_json preserves experiences; blocks unauthorized blacklist
        agent = Agent.objects.create(
            first_name='Khadija',
            last_name='A',
            phone='0688888888',
            cin='XX998877',
            assigned_to=self.commercial,
        )
        AgentExperience.objects.create(agent=agent, position='Gouvernante', company='Hotel X')

        pub_data = PublicAgentProfileSerializer(agent).data
        self.assertEqual(pub_data['cin'], 'XX****77')

        patch_ser = AgentSerializer(
            instance=agent,
            data={'first_name': 'KhadijaUpdated'},
            partial=True,
            context={'request': type('Req', (), {'user': self.commercial, 'data': {'first_name': 'KhadijaUpdated'}})()},
        )
        self.assertTrue(patch_ser.is_valid(), patch_ser.errors)
        patch_ser.save()
        self.assertEqual(agent.experiences.count(), 1)

        com_client = APIClient()
        com_client.force_authenticate(user=self.commercial)
        bl_resp = com_client.patch(f'/api/agents/{agent.id}/', {'statut': 'blacklist'}, format='json')
        self.assertEqual(bl_resp.status_code, 403)

        # 2. ClientSerializer prevents assigned commercial from self-lifting statut_airbnb (unassigned gets 403)
        unassigned_resp = com_client.patch(
            f'/api/clients/{self.airbnb_client.id}/',
            {'statut_airbnb': 'suspendu'},
            format='json',
        )
        self.assertEqual(unassigned_resp.status_code, 403)

        self.airbnb_client.assigned_commercial = self.commercial
        self.airbnb_client.save(update_fields=['assigned_commercial'])
        cl_resp = com_client.patch(
            f'/api/clients/{self.airbnb_client.id}/',
            {'statut_airbnb': 'suspendu'},
            format='json',
        )
        self.assertEqual(cl_resp.status_code, 400)

        # 3. BienDetailSerializer protects zone_eloignee from client_conciergerie
        bien = Bien.objects.create(
            code='ZNP01',
            client=self.airbnb_client,
            ville='Casablanca',
            quartier='Bouskoura',
            adresse='Villa 1',
            typologie='villa_riad',
            zone_eloignee=True,
        )
        conc_req = type('Req', (), {'user': self.conciergerie_user})()
        bien_ser = BienDetailSerializer(
            instance=bien,
            data={'zone_eloignee': False, 'nom_bien': 'Villa Renommée'},
            partial=True,
            context={'request': conc_req},
        )
        self.assertTrue(bien_ser.is_valid(), bien_ser.errors)
        updated_bien = bien_ser.save()
        self.assertTrue(updated_bien.zone_eloignee)

        # 4. Finance serializers reject invalid non-positive amounts
        fact = Facture.objects.create(client=self.airbnb_client, numero='FAC-P1-NEG', montant_total=Decimal('200.00'))
        self.assertFalse(PaiementSerializer(data={'facture': fact.id, 'montant': '0.00', 'mode': 'virement', 'date': str(timezone.localdate())}).is_valid())
        self.assertFalse(FactureSerializer(data={'client': self.airbnb_client.id, 'numero': 'F-NEG', 'montant_total': '-10.00'}).is_valid())
        self.assertFalse(EntreeCaisseSerializer(data={'type_mouvement': 'entree', 'montant': '-5.00', 'description': 'X', 'date': str(timezone.localdate())}).is_valid())

        # 5. Marketing CommercialGesture clamping & validation + PromoCode segment rule
        dem = Demande.objects.create(client=self.airbnb_client, service='Ménage', prix=Decimal('200.00'))
        bad_gest = CommercialGestureSerializer(data={
            'demande': dem.id,
            'date': str(timezone.localdate()),
            'gesture_type': 'reduction_tarif',
            'reduction_type': 'pourcentage',
            'reduction_value': '150.00',
        })
        self.assertFalse(bad_gest.is_valid())

        gest_resp = com_client.post(
            '/api/marketing/gestes/',
            {
                'demande': dem.id,
                'date': str(timezone.localdate()),
                'gesture_type': 'reduction_tarif',
                'reduction_type': 'montant',
                'reduction_value': '500.00',
                'cree_par': self.admin.id,
            },
            format='json',
        )
        self.assertEqual(gest_resp.status_code, 201)
        dem.refresh_from_db()
        self.assertEqual(dem.prix, Decimal('0.00'))
        self.assertEqual(gest_resp.data['cree_par'], self.commercial.id)

        promo_ent = PromoCode.objects.create(
            name='EntOnly',
            code='ENTONLY10',
            reduction=Decimal('10.00'),
            reduction_type='pourcentage',
            segment='entreprise',
            valid_from=timezone.localdate() - datetime.timedelta(days=1),
            status='active',
            customer_status='Tous les clients',
        )
        res_empty_seg = validate_promo_for_booking('ENTONLY10', segment='')
        self.assertFalse(res_empty_seg['valid'])
        self.assertEqual(res_empty_seg['reason_code'], 'segment_ineligible')

        # 6. Double invoicing guard & lancer_cron date validation
        cmd = CommandeAirbnb.objects.create(
            numero='CMD-DBL-1',
            bien=bien,
            date_prestation=timezone.localdate() - datetime.timedelta(days=1),
            statut='facturable',
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
            photos_cloture=['1', '2', '3', '4'],
        )
        _create_facture_for_commandes(self.airbnb_client, [cmd], 'passage', user=self.admin)
        cmd.refresh_from_db()
        with self.assertRaises(DjangoValidationError):
            _create_facture_for_commandes(self.airbnb_client, [cmd], 'passage', user=self.admin)

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        cron_bad = admin_client.post(
            '/api/airbnb/facturation/lancer_cron/',
            {'job': 'generer_factures_airbnb', 'date': '2026-99-99'},
            format='json',
        )
        self.assertEqual(cron_bad.status_code, 400)
