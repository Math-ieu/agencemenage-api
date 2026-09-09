from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SiteConfigViewSet, SiteConfigPublicView

router = DefaultRouter()
router.register(r'config', SiteConfigViewSet, basename='site-config')

urlpatterns = [
    path('public/config/', SiteConfigPublicView.as_view(), name='public-site-config'),
    path('', include(router.urls)),
]
