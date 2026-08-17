from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AirbnbConfigViewSet,
    BienViewSet,
    CommandeAirbnbViewSet,
    FiletLingeViewSet,
    ObjetTrouveViewSet
)

router = DefaultRouter()
router.register(r'config', AirbnbConfigViewSet, basename='airbnb-config')
router.register(r'biens', BienViewSet, basename='airbnb-biens')
router.register(r'commandes', CommandeAirbnbViewSet, basename='airbnb-commandes')
router.register(r'filets', FiletLingeViewSet, basename='airbnb-filets')
router.register(r'objets-trouves', ObjetTrouveViewSet, basename='airbnb-objets-trouves')

urlpatterns = [
    path('', include(router.urls)),
]
