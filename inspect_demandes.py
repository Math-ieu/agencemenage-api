import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS.append('testserver')

from demandes.models import Demande
from demandes.serializers import DemandeListSerializer

# Fetch child demand #31 or #34
from rest_framework.test import APIRequestFactory, force_authenticate
from accounts.models import User
from demandes.views import DemandeViewSet
from demandes.serializers import DemandeListSerializer

factory = APIRequestFactory()
request = factory.get('/api/demandes/', {'no_page': 'true'})

admin_user = User.objects.filter(role='admin').first()
if not admin_user:
    admin_user = User.objects.first()

force_authenticate(request, user=admin_user)

# Instantiate view to get queryset and context
view = DemandeViewSet()
view.request = request
view.format_kwarg = None

# Get queryset
queryset = view.get_queryset()

# Serialize manually
serializer = DemandeListSerializer(queryset, many=True, context={'request': request})
data = serializer.data

print(f"Total demands returned by serializer: {len(data)}")
# Check for Demand #20 and #30
found_20 = [x for x in data if x.get('id') == 20]
found_30 = [x for x in data if x.get('id') == 30]

print(f"Found Demand #20 in serializer output: {len(found_20) > 0}")
if found_20:
    print(f"  Demand #20: {found_20[0]}")

print(f"Found Demand #30 in serializer output: {len(found_30) > 0}")
if found_30:
    print(f"  Demand #30: {found_30[0]}")



