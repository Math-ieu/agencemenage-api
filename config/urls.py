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
from accounts.views import (
    CustomTokenObtainPairView, CookieTokenRefreshView, LogoutView, UserViewSet,
    MeView, ChangePasswordView, RolePermissionView, ForgotPasswordView, ResetPasswordView
)
from clients.views import ClientViewSet
from agents.views import AgentViewSet
from demandes.views import DemandeViewSet, PublicDemandeCreateView, AuditLogViewSet, DocumentViewSet, AppNotificationViewSet
from missions.views import MissionViewSet
from finance.views import FactureViewSet, PaiementViewSet, EntreeCaisseViewSet
from feedback.views import FeedbackViewSet
from blog.views import CategoryViewSet, PostViewSet
from media.views import MediaFileView

# Router
router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'agents', AgentViewSet, basename='agent')
router.register(r'demandes', DemandeViewSet, basename='demande')
router.register(r'documents', DocumentViewSet, basename='document')
router.register(r'missions', MissionViewSet, basename='mission')
router.register(r'finance/factures', FactureViewSet, basename='facture')
router.register(r'finance/paiements', PaiementViewSet, basename='paiement')
router.register(r'finance/caisse', EntreeCaisseViewSet, basename='caisse')
router.register(r'feedback', FeedbackViewSet, basename='feedback')
router.register(r'audit', AuditLogViewSet, basename='audit')
router.register(r'notifications', AppNotificationViewSet, basename='notification')
router.register(r'blog/categories', CategoryViewSet, basename='blog-category')
router.register(r'blog/posts', PostViewSet, basename='blog-post')

urlpatterns = [
    path('admin/', admin.site.urls),

    # API routes
    path('api/', include(router.urls)),
    path('api/marketing/', include('marketing.urls')),

    # Auth endpoints
    path('api/auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),
    path('api/auth/me/', MeView.as_view(), name='me'),
    path('api/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('api/auth/roles-permissions/', RolePermissionView.as_view(), name='roles_permissions'),
    path('api/auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('api/auth/reset-password/', ResetPasswordView.as_view(), name='reset_password'),

    # Public media endpoint — serves files from S3 / Railway bucket
    path('api/media/<path:file_path>/', MediaFileView.as_view(), name='media_file'),

    # Public endpoint (no auth required — from website)
    path('api/public/demandes/', PublicDemandeCreateView.as_view({'post': 'create'}), name='public_demande_create'),
    path('api/public/blog/posts/', PostViewSet.as_view({'get': 'list'}), name='public-blog-list'),
    path('api/public/blog/posts/<slug:slug>/', PostViewSet.as_view({'get': 'retrieve'}), name='public-blog-detail'),

    # OpenAPI docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
