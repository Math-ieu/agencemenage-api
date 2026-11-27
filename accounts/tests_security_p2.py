import inspect

import django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from accounts.views import UserViewSet


class SecurityP2GovernanceAndRuntimeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin-p2@agencemenage.ma',
            password='VeryStrongPassword99!',
            first_name='Admin',
            last_name='P2',
            role=User.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.audited_admin = User.objects.create_user(
            email='audit-admin-p2@example.com',
            password='VeryStrongPassword99!',
            first_name='Audit',
            last_name='Visible',
            role=User.ADMIN,
            is_staff=True,
        )

    def test_django_52_lts_active(self):
        self.assertGreaterEqual(django.VERSION[:2], (5, 2))

    def test_user_viewset_does_not_hide_hardcoded_email(self):
        source = inspect.getsource(UserViewSet.get_queryset)
        self.assertNotIn('exclude(email', source)

        client = APIClient()
        client.force_authenticate(user=self.admin)
        response = client.get('/api/users/?page_size=100')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data.get('results', response.data)
        emails = {u['email'].lower() for u in payload}
        self.assertIn('audit-admin-p2@example.com', emails)

    def test_seed_finance_demo_blocked_when_debug_false(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                call_command('seed_finance_demo')
