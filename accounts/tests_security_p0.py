import datetime
import io
import os
import shutil
import socket
import tempfile
from decimal import Decimal
from unittest.mock import patch

from PIL import Image
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import PasswordResetCode, RolePermission, User
from agencemenage.media_signing import sign_media_url
from agencemenage.utils import generate_feedback_token
from agencemenage.validators import validate_uploaded_image
from agents.models import Agent
from airbnb.models import Bien, CommandeAirbnb, SignalementCommande
from airbnb.services.ical_service import validate_ical_url
from blog.models import Category, Post
from blog.sanitizer import sanitize_blog_html
from clients.models import Client
from demandes.models import AppNotification, AuditLog, Demande, ProfilShare
from feedback.models import Feedback
from finance.models import Facture
from marketing.models import Campaign


def _make_png_bytes(width=10, height=10) -> bytes:
    buf = io.BytesIO()
    img = Image.new('RGB', (width, height), color=(12, 120, 200))
    img.save(buf, format='PNG')
    return buf.getvalue()


class SecurityP0AuthAndPrivilegeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(
            email='admin-p0@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Admin',
            last_name='Root',
            role='admin',
            is_staff=True,
        )
        self.commercial = User.objects.create_user(
            email='com-p0@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Sara',
            last_name='Com',
            role='commercial',
        )
        self.client_obj = Client.objects.create(
            first_name='Atlas',
            last_name='Conciergerie',
            entity_name='Conciergerie Atlas',
            phone='0611111111',
            email='atlas@example.com',
            segment=Client.ENTREPRISE,
            type_client_airbnb='conciergerie',
            trigramme='ATL',
        )
        self.conciergerie_user = User.objects.create_user(
            email='conciergerie-p0@example.com',
            password='StrongPassword123!',
            first_name='Atlas',
            last_name='Owner',
            role='client_conciergerie',
            client=self.client_obj,
        )
        RolePermission.objects.update_or_create(
            role='commercial',
            defaults={
                'permissions': [
                    'demandes_voir',
                    'demandes_voir_tout',
                    'demandes_modifier',
                    'clients_voir',
                ]
            },
        )
        RolePermission.objects.update_or_create(
            role='Client Conciergerie',
            defaults={'permissions': ['airbnb_biens_voir', 'airbnb_commandes_voir']},
        )
        RolePermission.objects.update_or_create(
            role='Admin',
            defaults={'permissions': ['all']},
        )

    def tearDown(self):
        cache.clear()

    def test_me_patch_cannot_escalate_privileges(self):
        client = APIClient()
        client.force_authenticate(user=self.commercial)
        resp = client.patch(
            '/api/auth/me/',
            {
                'first_name': 'UpdatedSara',
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
                'client': self.client_obj.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.commercial.refresh_from_db()
        self.assertEqual(self.commercial.first_name, 'UpdatedSara')
        self.assertEqual(self.commercial.role, 'commercial')
        self.assertFalse(self.commercial.is_staff)
        self.assertFalse(self.commercial.is_superuser)
        self.assertIsNone(self.commercial.client)

    def test_non_admin_cannot_create_admin_or_edit_admin_user_or_admin_role(self):
        RolePermission.objects.update_or_create(
            role='commercial',
            defaults={
                'permissions': [
                    'utilisateurs_voir',
                    'utilisateurs_creer',
                    'utilisateurs_modifier',
                    'roles_voir',
                    'roles_modifier',
                ]
            },
        )
        client = APIClient()
        client.force_authenticate(user=self.commercial)

        resp_create = client.post(
            '/api/users/',
            {
                'email': 'fakeadmin@agencemenage.ma',
                'password': 'StrongPassword123!',
                'first_name': 'Fake',
                'last_name': 'Admin',
                'role': 'admin',
            },
            format='json',
        )
        self.assertIn(resp_create.status_code, (400, 403))
        self.assertFalse(User.objects.filter(email='fakeadmin@agencemenage.ma').exists())

        resp_edit_admin = client.patch(
            f'/api/users/{self.admin.id}/',
            {'first_name': 'Hacked'},
            format='json',
        )
        self.assertEqual(resp_edit_admin.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, 'Admin')

        resp_role = client.post(
            '/api/auth/roles-permissions/',
            {'role': 'Admin', 'permissions': ['none']},
            format='json',
        )
        self.assertEqual(resp_role.status_code, 403)

    def test_airbnb_only_role_only_sees_own_permissions(self):
        client = APIClient()
        client.force_authenticate(user=self.conciergerie_user)
        resp = client.get('/api/auth/roles-permissions/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.data.keys()), ['Client Conciergerie'])

    def test_cookie_jwt_csrf_enforcement_and_bearer_exemption(self):
        csrf_client = APIClient(enforce_csrf_checks=True)
        login_resp = csrf_client.post(
            '/api/auth/login/',
            {'email': self.commercial.email, 'password': 'StrongPassword123!'},
            format='json',
        )
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn('access_token', login_resp.cookies)
        self.assertIn('refresh_token', login_resp.cookies)
        self.assertNotIn('access', login_resp.data)
        self.assertNotIn('refresh', login_resp.data)

        # Mutating cookie-authenticated endpoint without X-CSRFToken must fail with 403
        resp_no_csrf = csrf_client.patch(
            '/api/auth/me/',
            {'first_name': 'NoCsrf'},
            format='json',
        )
        self.assertEqual(resp_no_csrf.status_code, 403)

        resp_refresh_no_csrf = csrf_client.post('/api/auth/refresh/', {}, format='json')
        self.assertEqual(resp_refresh_no_csrf.status_code, 403)

        resp_logout_no_csrf = csrf_client.post('/api/auth/logout/', {}, format='json')
        self.assertEqual(resp_logout_no_csrf.status_code, 403)

        # Fetch CSRF token via endpoint and send header
        csrf_init = csrf_client.get('/api/auth/csrf/')
        self.assertEqual(csrf_init.status_code, 200)
        csrf_token = csrf_init.data.get('csrfToken') or csrf_init.data.get('csrf_token')
        if not csrf_token and 'csrftoken' in csrf_init.cookies:
            csrf_token = csrf_init.cookies['csrftoken'].value
        self.assertTrue(csrf_token)

        resp_with_csrf = csrf_client.patch(
            '/api/auth/me/',
            {'first_name': 'WithCsrf'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp_with_csrf.status_code, 200)
        self.commercial.refresh_from_db()
        self.assertEqual(self.commercial.first_name, 'WithCsrf')

        resp_refresh_ok = csrf_client.post(
            '/api/auth/refresh/',
            {},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp_refresh_ok.status_code, 200)
        self.assertIn('access_token', resp_refresh_ok.cookies)

        csrf_token = resp_refresh_ok.data.get('csrf_token') or csrf_token
        resp_logout_ok = csrf_client.post(
            '/api/auth/logout/',
            {},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp_logout_ok.status_code, 200)

        # Bearer token client works without CSRF header even when enforce_csrf_checks=True
        bearer_token = str(RefreshToken.for_user(self.commercial).access_token)
        bearer_client = APIClient(enforce_csrf_checks=True)
        bearer_client.credentials(HTTP_AUTHORIZATION=f'Bearer {bearer_token}')
        resp_bearer = bearer_client.patch(
            '/api/auth/me/',
            {'first_name': 'BearerOk'},
            format='json',
        )
        self.assertEqual(resp_bearer.status_code, 200)

    def test_otp_password_reset_lockout_after_5_failed_attempts(self):
        client = APIClient()
        forgot_resp = client.post(
            '/api/auth/forgot-password/',
            {'login': self.commercial.email},
            format='json',
        )
        self.assertEqual(forgot_resp.status_code, 200)
        otp = PasswordResetCode.objects.filter(user=self.commercial, is_used=False).latest('created_at')
        self.assertEqual(len(otp.code), 6)

        wrong_code = '000000' if otp.code != '000000' else '999999'
        for _ in range(5):
            bad_resp = client.post(
                '/api/auth/reset-password/',
                {
                    'login': self.commercial.email,
                    'code': wrong_code,
                    'new_password': 'NewStrongPassword123!',
                },
                format='json',
            )
            self.assertEqual(bad_resp.status_code, 400)

        otp.refresh_from_db()
        self.assertGreaterEqual(otp.attempts, 5)
        self.assertFalse(otp.is_valid())

        # Even the genuine code is now rejected after lockout
        locked_resp = client.post(
            '/api/auth/reset-password/',
            {
                'login': self.commercial.email,
                'code': otp.code,
                'new_password': 'NewStrongPassword123!',
            },
            format='json',
        )
        self.assertEqual(locked_resp.status_code, 400)


class SecurityP0RbacMediaPublicAirbnbTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.media_dir = tempfile.mkdtemp(prefix='agm_p0_media_')
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir)
        self.media_override.enable()

        self.admin = User.objects.create_user(
            email='admin-rbac@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Admin',
            last_name='RBAC',
            role='admin',
            is_staff=True,
        )
        self.com_a = User.objects.create_user(
            email='com-a@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Com',
            last_name='A',
            role='commercial',
        )
        self.com_b = User.objects.create_user(
            email='com-b@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Com',
            last_name='B',
            role='commercial',
        )
        self.resp_fact = User.objects.create_user(
            email='fact@agencemenage.ma',
            password='StrongPassword123!',
            first_name='Fact',
            last_name='User',
            role='responsable_facturation',
        )

        self.airbnb_client = Client.objects.create(
            first_name='Oasis',
            last_name='Conciergerie',
            entity_name='Riad Oasis',
            phone='0622222222',
            email='oasis@example.com',
            segment=Client.ENTREPRISE,
            type_client_airbnb='conciergerie',
            trigramme='OAS',
        )
        self.other_airbnb_client = Client.objects.create(
            first_name='Sol',
            last_name='Conciergerie',
            entity_name='Riad Sol',
            phone='0633333333',
            email='sol@example.com',
            segment=Client.ENTREPRISE,
            type_client_airbnb='conciergerie',
            trigramme='SOL',
        )
        self.regular_client = Client.objects.create(
            first_name='Client',
            last_name='Standard',
            phone='0644444444',
            email='std@example.com',
            city='Rabat',
            address='10 Rue Atlas',
            segment=Client.PARTICULIER,
        )
        self.conciergerie_user = User.objects.create_user(
            email='owner-oasis@example.com',
            password='StrongPassword123!',
            first_name='Oasis',
            last_name='Host',
            role='client_conciergerie',
            client=self.airbnb_client,
        )
        self.other_conciergerie_user = User.objects.create_user(
            email='owner-sol@example.com',
            password='StrongPassword123!',
            first_name='Sol',
            last_name='Host',
            role='client_conciergerie',
            client=self.other_airbnb_client,
        )

        RolePermission.objects.update_or_create(
            role='commercial',
            defaults={'permissions': ['demandes_voir', 'demandes_modifier', 'clients_voir']},
        )
        RolePermission.objects.update_or_create(
            role='responsable_facturation',
            defaults={'permissions': ['clients_voir', 'factures_voir']},
        )
        RolePermission.objects.update_or_create(
            role='Client Conciergerie',
            defaults={
                'permissions': [
                    'airbnb_biens_voir',
                    'airbnb_commandes_voir',
                    'airbnb_commandes_modifier',
                    'airbnb_facturation_voir',
                    'airbnb_signalements_voir',
                ]
            },
        )

    def tearDown(self):
        cache.clear()
        self.media_override.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_demande_idor_notification_and_audit_fail_closed(self):
        demande_b = Demande.objects.create(
            client=self.regular_client,
            service='Grand Ménage',
            assigned_to=self.com_b,
            created_by=self.com_b,
            source=Demande.BACKOFFICE,
        )
        notif = AppNotification.objects.create(
            type='info',
            title='Original Title',
            message='Original Message',
            target_roles=['commercial'],
            is_read=False,
        )
        AuditLog.objects.create(action='TEST', model_name='Demande', object_id=demande_b.id)
        campagne = Campaign.objects.create(title='Promo', message='Msg', target='client')

        c = APIClient()
        c.force_authenticate(user=self.com_a)

        # Commercial A cannot view or modify Demande owned exclusively by Commercial B
        self.assertEqual(c.get(f'/api/demandes/{demande_b.id}/').status_code, 403)
        self.assertEqual(
            c.patch(f'/api/demandes/{demande_b.id}/', {'service': 'Hacked'}, format='json').status_code,
            403,
        )

        # Non-admin can only mark notification as read, not alter title/target_roles
        notif_resp = c.patch(
            f'/api/notifications/{notif.id}/',
            {'is_read': True, 'title': 'Hacked', 'target_roles': ['admin']},
            format='json',
        )
        self.assertEqual(notif_resp.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertEqual(notif.title, 'Original Title')
        self.assertEqual(notif.target_roles, ['commercial'])

        # Audit logs & Campaign send & Finance delete fail closed for unauthorized commercial
        self.assertEqual(c.get('/api/audit/').status_code, 403)
        self.assertEqual(c.post(f'/api/marketing/campagnes/{campagne.id}/send/', {}, format='json').status_code, 403)

        facture = Facture.objects.create(
            client=self.airbnb_client,
            numero='FAC-DEL-001',
            montant_total=Decimal('300.00'),
        )
        self.assertEqual(c.delete(f'/api/finance/factures/{facture.id}/').status_code, 403)

    def test_responsable_facturation_only_lists_airbnb_clients(self):
        c = APIClient()
        c.force_authenticate(user=self.resp_fact)
        resp = c.get('/api/clients/')
        self.assertEqual(resp.status_code, 200)
        items = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        returned_ids = {item['id'] for item in items}
        self.assertIn(self.airbnb_client.id, returned_ids)
        self.assertNotIn(self.regular_client.id, returned_ids)

    def test_media_access_control_signed_urls_and_headers(self):
        public_dir = os.path.join(self.media_dir, 'agents', 'photos')
        private_cin_dir = os.path.join(self.media_dir, 'agents', 'cin')
        factures_dir = os.path.join(self.media_dir, 'factures')
        os.makedirs(public_dir, exist_ok=True)
        os.makedirs(private_cin_dir, exist_ok=True)
        os.makedirs(factures_dir, exist_ok=True)

        png_bytes = _make_png_bytes()
        with open(os.path.join(public_dir, 'avatar.png'), 'wb') as f:
            f.write(png_bytes)
        with open(os.path.join(public_dir, 'bad.svg'), 'wb') as f:
            f.write(b'<svg onload="alert(1)"></svg>')
        with open(os.path.join(private_cin_dir, 'cin.png'), 'wb') as f:
            f.write(png_bytes)
        with open(os.path.join(factures_dir, 'FAC-SOL-1.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 sample sol')
        with open(os.path.join(factures_dir, 'FAC-OASIS-1.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 sample oasis')

        Facture.objects.create(
            client=self.other_airbnb_client,
            numero='FAC-SOL-1',
            montant_total=Decimal('250.00'),
            source=Facture.SOURCE_AIRBNB,
            pdf_file='factures/FAC-SOL-1.pdf',
        )
        Facture.objects.create(
            client=self.airbnb_client,
            numero='FAC-OASIS-1',
            montant_total=Decimal('180.00'),
            source=Facture.SOURCE_AIRBNB,
            pdf_file='factures/FAC-OASIS-1.pdf',
        )

        anon = APIClient()
        # Public prefix allowed without auth + security headers
        pub_resp = anon.get('/api/media/agents/photos/avatar.png')
        self.assertEqual(pub_resp.status_code, 200)
        self.assertEqual(pub_resp['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', pub_resp['Content-Security-Policy'])

        # SVG served as attachment
        svg_resp = anon.get('/api/media/agents/photos/bad.svg')
        self.assertEqual(svg_resp.status_code, 200)
        self.assertTrue(svg_resp['Content-Disposition'].startswith('attachment'))

        # Private paths blocked without auth / sig
        self.assertIn(anon.get('/api/media/agents/cin/cin.png').status_code, (401, 403))
        self.assertIn(anon.get('/api/media/factures/FAC-SOL-1.pdf').status_code, (401, 403))
        self.assertIn(anon.get('/api/media/agents/cin/cin.png?sig=tampered').status_code, (401, 403))

        # Other client conciergerie authenticated with real JWT cannot read another client's PDF or CIN
        oasis_token = str(RefreshToken.for_user(self.conciergerie_user).access_token)
        oasis_client = APIClient()
        oasis_client.credentials(HTTP_AUTHORIZATION=f'Bearer {oasis_token}')
        self.assertEqual(oasis_client.get('/api/media/factures/FAC-SOL-1.pdf').status_code, 403)
        self.assertEqual(oasis_client.get('/api/media/agents/cin/cin.png').status_code, 403)
        self.assertEqual(oasis_client.get('/api/media/factures/FAC-OASIS-1.pdf').status_code, 200)

        # Valid signed URL works for WhatsApp external fetch
        signed_url = sign_media_url('https://api.example.com/api/media/agents/cin/cin.png')
        self.assertIn('sig=', signed_url)
        sig_value = signed_url.split('sig=', 1)[1]
        signed_resp = anon.get(f'/api/media/agents/cin/cin.png?sig={sig_value}')
        self.assertEqual(signed_resp.status_code, 200)

    def test_agent_public_endpoints_and_by_share_scrubbing(self):
        agent = Agent.objects.create(
            first_name='Amina',
            last_name='SecretLastName',
            phone='0655555555',
            whatsapp='0655555555',
            email='amina@example.com',
            birth_date=datetime.date(1995, 5, 1),
            cin='AB123456',
            cin_file='agents/cin/cin_f.png',
            cin_verso_file='agents/cin/cin_b.png',
            attestation_file='agents/attestations/att.pdf',
            fiche_antropometrique='agents/fiches_antropometriques/casier.pdf',
            health_issues='Asthme confidentiel',
            recruiter_notes='Notes recruteur internes',
            operator_notes='Sérieuse et ponctuelle',
        )
        demande = Demande.objects.create(client=self.regular_client, service='Ménage')
        share = ProfilShare.objects.create(demande=demande, agent=agent)

        anon = APIClient()
        # Direct UUID lookup requires auth now
        self.assertIn(anon.get(f'/api/agents/{agent.uuid}/').status_code, (401, 403))

        # Shared link returns only non-sensitive public profile fields (CIN masked)
        share_resp = anon.get(f'/api/agents/by-share/{share.uuid}/')
        self.assertEqual(share_resp.status_code, 200)
        self.assertEqual(share_resp.data['first_name'], 'Amina')
        self.assertEqual(share_resp.data['cin'], 'AB****56')
        self.assertIsInstance(share_resp.data['age'], int)
        for forbidden_key in (
            'phone',
            'whatsapp',
            'email',
            'birth_date',
            'cin_file',
            'cin_verso_file',
            'attestation_file',
            'fiche_antropometrique',
            'health_issues',
            'recruiter_notes',
            'last_name',
            'uuid',
        ):
            self.assertNotIn(forbidden_key, share_resp.data)

    def test_public_demande_does_not_overwrite_client_or_accept_negative_price(self):
        anon = APIClient()
        bad_price = anon.post(
            '/api/public/demandes/',
            {
                'service': 'Ménage standard',
                'prix': '-50',
                'client_nom': 'Hacker',
                'client_phone': self.regular_client.phone,
            },
            format='json',
        )
        self.assertEqual(bad_price.status_code, 400)

        ok_resp = anon.post(
            '/api/public/demandes/',
            {
                'service': 'Ménage standard',
                'prix': '250',
                'client_prenom': 'Attacker',
                'client_nom': 'Name',
                'client_email': 'attacker@evil.example',
                'client_phone': self.regular_client.phone,
                'client_ville': 'Tanger',
                'client_address': 'Fake Street',
            },
            format='json',
        )
        self.assertEqual(ok_resp.status_code, 201)
        self.regular_client.refresh_from_db()
        # Existing non-empty client details remain protected
        self.assertEqual(self.regular_client.first_name, 'Client')
        self.assertEqual(self.regular_client.last_name, 'Standard')
        self.assertEqual(self.regular_client.email, 'std@example.com')
        self.assertEqual(self.regular_client.city, 'Rabat')
        self.assertEqual(self.regular_client.address, '10 Rue Atlas')

    def test_feedback_public_submission_locked_and_minimal(self):
        demande = Demande.objects.create(client=self.regular_client, service='Ménage')
        anon = APIClient()

        # Unauthenticated read blocked
        self.assertIn(anon.get('/api/feedback/').status_code, (401, 403))

        # Raw integer demande rejected without signed token
        raw_resp = anon.post(
            '/api/feedback/',
            {'demande': demande.id, 'note_intervenant': 5, 'note_agence': 5},
            format='json',
        )
        self.assertEqual(raw_resp.status_code, 400)

        # Invalid or legacy base64 tokens fail validate-token
        bad_val = anon.get('/api/feedback/validate-token/?token=invalid-token')
        self.assertEqual(bad_val.status_code, 200)
        self.assertFalse(bad_val.data['valid'])

        # Valid signed token validates cleanly without leaking PII
        token = generate_feedback_token(demande.id)
        ok_val = anon.get(f'/api/feedback/validate-token/?token={token}')
        self.assertEqual(ok_val.status_code, 200)
        self.assertEqual(ok_val.data, {'valid': True, 'already_submitted': False})

        # Unauthenticated create returns minimal response and ignores spoofed client
        create_resp = anon.post(
            '/api/feedback/',
            {
                'token': token,
                'client': self.airbnb_client.id,
                'note_intervenant': 5,
                'note_agence': 5,
                'commentaire': 'Très bon service',
            },
            format='json',
        )
        self.assertEqual(create_resp.status_code, 201)
        self.assertEqual(set(create_resp.data.keys()), {'status', 'id'})
        fb = Feedback.objects.get(id=create_resp.data['id'])
        self.assertEqual(fb.client_id, self.regular_client.id)

        # Token reports already_submitted and duplicate submission is blocked
        recheck = anon.get(f'/api/feedback/validate-token/?token={token}')
        self.assertEqual(recheck.data, {'valid': False, 'already_submitted': True})

        dup_resp = anon.post(
            '/api/feedback/',
            {'token': token, 'note_intervenant': 4, 'note_agence': 4, 'commentaire': 'Deuxième'},
            format='json',
        )
        self.assertEqual(dup_resp.status_code, 400)

    def test_blog_sanitizer_rbac_and_image_validator(self):
        cleaned = sanitize_blog_html(
            '<p onclick="alert(1)">Texte <b>gras</b></p>'
            '<script>alert(1)</script>'
            '<a href="javascript:alert(1)">bad</a>'
            '<a href="https://agencemenage.ma">ok</a>'
        )
        self.assertNotIn('<script', cleaned.lower())
        self.assertNotIn('onclick', cleaned.lower())
        self.assertNotIn('javascript:', cleaned.lower())
        self.assertIn('https://agencemenage.ma', cleaned)

        svg_upload = SimpleUploadedFile('evil.svg', b'<svg onload="alert(1)"></svg>', content_type='image/svg+xml')
        with self.assertRaises(drf_serializers.ValidationError):
            validate_uploaded_image(svg_upload)

        png_upload = SimpleUploadedFile('good.png', _make_png_bytes(), content_type='image/png')
        self.assertEqual(validate_uploaded_image(png_upload).name, 'good.png')

        c = APIClient()
        c.force_authenticate(user=self.com_a)
        cat = Category.objects.create(name='Guides')
        post = Post.objects.create(
            title='Draft',
            slug='draft-post',
            content='Contenu',
            category=cat,
            status=getattr(Post, 'DRAFT', 'draft'),
        )
        self.assertEqual(
            c.post('/api/blog/posts/', {'title': 'X', 'content': 'Y'}, format='json').status_code,
            403,
        )
        anon = APIClient()
        self.assertEqual(anon.get('/api/public/blog/posts/draft-post/').status_code, 404)
        post.status = Post.PUBLISHED
        post.save(update_fields=['status'])
        self.assertEqual(anon.get('/api/public/blog/posts/draft-post/').status_code, 200)

    def test_airbnb_ical_ssrf_and_pricing_tampering_protection(self):
        for bad_url in (
            'http://127.0.0.1/cal.ics',
            'http://localhost:8000/cal.ics',
            'http://169.254.169.254/latest/meta-data/',
            'http://10.0.0.5/cal.ics',
            'file:///etc/passwd',
        ):
            with self.assertRaises((ValidationError, ValueError)):
                validate_ical_url(bad_url)

        with patch(
            'airbnb.services.ical_service.socket.getaddrinfo',
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))],
        ):
            self.assertEqual(
                validate_ical_url('https://www.airbnb.com/calendar/ical/12345.ics'),
                'https://www.airbnb.com/calendar/ical/12345.ics',
            )

        bien = Bien.objects.create(
            code='OAS001',
            client=self.airbnb_client,
            ville='Casablanca',
            quartier='Maarif',
            adresse='1 Rue Oasis',
            typologie='2ch',
        )
        commande = CommandeAirbnb.objects.create(
            numero='CMD-P0-1',
            bien=bien,
            date_prestation=timezone.now().date(),
            statut='cloturee',
            remise_en_etat_statut='validee_ops',
            remise_en_etat=Decimal('120.00'),
            prix_menage=Decimal('160.00'),
            total_ttc=Decimal('160.00'),
            photos_cloture=['1', '2', '3', '4'],
        )

        host_client = APIClient()
        host_client.force_authenticate(user=self.conciergerie_user)

        # Client conciergerie cannot tamper with server-calculated remise_en_etat amount
        remise_resp = host_client.post(
            f'/api/airbnb/commandes/{commande.id}/accord_remise_en_etat/',
            {'decision': 'accepte', 'accord_preuve': 'Accord WhatsApp', 'montant': '0.00'},
            format='json',
        )
        self.assertEqual(remise_resp.status_code, 200)
        commande.refresh_from_db()
        self.assertEqual(commande.remise_en_etat, Decimal('120.00'))
        self.assertEqual(commande.total_ttc, Decimal('280.00'))

        # Signalement accord_client rejects javascript: proof URLs for conciergerie & negative montant for admin
        sig = SignalementCommande.objects.create(
            commande=commande,
            motif='bien_sale',
            description='Bien très sale',
            statut='transmis_client',
            accord_client='en_attente',
            heures_estimees=Decimal('2.00'),
        )
        sig_bad_proof = host_client.post(
            f'/api/airbnb/signalements/{sig.id}/accord_client/',
            {'decision': 'accepte', 'accord_preuve': 'javascript:alert(1)'},
            format='json',
        )
        self.assertEqual(sig_bad_proof.status_code, 400)

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        sig_bad_amt = admin_client.post(
            f'/api/airbnb/signalements/{sig.id}/accord_client/',
            {'decision': 'accepte', 'accord_preuve': 'Accord client', 'montant': '-999'},
            format='json',
        )
        self.assertEqual(sig_bad_amt.status_code, 400)

    def test_schema_not_public_when_debug_false(self):
        anon = APIClient()
        with override_settings(DEBUG=False):
            self.assertIn(anon.get('/api/schema/').status_code, (401, 403))
            self.assertIn(anon.get('/api/docs/').status_code, (401, 403))

            admin_client = APIClient()
            admin_client.force_authenticate(user=self.admin)
            self.assertEqual(admin_client.get('/api/schema/').status_code, 200)
            self.assertEqual(admin_client.get('/api/docs/').status_code, 200)
