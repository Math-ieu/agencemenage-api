from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SiteConfigViewSet, SiteConfigPublicView

router = DefaultRouter()
router.register(r'config', SiteConfigViewSet, basename='site-config')

urlpatterns = [
    path('public/config/', SiteConfigPublicView.as_view(), name='public-site-config'),
    path('public/config', SiteConfigPublicView.as_view(), name='public-site-config-no-slash'),
    path('public/site-config/', SiteConfigPublicView.as_view(), name='public-site-config-alias'),
    path('public/site-config', SiteConfigPublicView.as_view(), name='public-site-config-alias-no-slash'),
    path('site-config/', SiteConfigPublicView.as_view(), name='public-site-config-direct'),
    path('site-config', SiteConfigPublicView.as_view(), name='public-site-config-direct-no-slash'),
    path('', include(router.urls)),
]
