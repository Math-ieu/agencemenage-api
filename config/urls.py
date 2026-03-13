"""
URL Configuration for agencemenage-api.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# Import views
from accounts.views import CustomTokenObtainPairView, CookieTokenRefreshView, LogoutView, UserViewSet, MeView, ChangePasswordView
from clients.views import ClientViewSet
from agents.views import AgentViewSet
from demandes.views import DemandeViewSet, PublicDemandeCreateView, AuditLogViewSet
from missions.views import MissionViewSet
from finance.views import FactureViewSet, PaiementViewSet, EntreeCaisseViewSet
from feedback.views import FeedbackViewSet

# Router
router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'agents', AgentViewSet, basename='agent')
router.register(r'demandes', DemandeViewSet, basename='demande')
router.register(r'missions', MissionViewSet, basename='mission')
router.register(r'finance/factures', FactureViewSet, basename='facture')
router.register(r'finance/paiements', PaiementViewSet, basename='paiement')
router.register(r'finance/caisse', EntreeCaisseViewSet, basename='caisse')
router.register(r'feedback', FeedbackViewSet, basename='feedback')
router.register(r'audit', AuditLogViewSet, basename='audit')

urlpatterns = [
    path('admin/', admin.site.urls),

    # API routes
    path('api/', include(router.urls)),

    # Auth endpoints
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/me/', MeView.as_view(), name='me'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),

    # Public endpoint (no auth required — from website)
    path('api/public/demandes/', PublicDemandeCreateView.as_view({'post': 'create'}), name='public_demande_create'),

    # OpenAPI docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
