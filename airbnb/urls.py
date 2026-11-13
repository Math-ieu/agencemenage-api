from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AirbnbConfigViewSet,
    GrilleTarifaireVersionViewSet,
    BienViewSet,
    CommandeAirbnbViewSet,
    FiletLingeViewSet,
    ObservationLingeViewSet,
    SignalementCommandeViewSet,
    ObjetTrouveViewSet,
    FacturationAirbnbViewSet,
    JournalAuditAirbnbViewSet,
    AirbnbPhotoUploadView,
)

router = DefaultRouter()
router.register(r'config', AirbnbConfigViewSet, basename='airbnb-config')
router.register(r'grilles-tarifaires', GrilleTarifaireVersionViewSet, basename='airbnb-grilles-tarifaires')
router.register(r'biens', BienViewSet, basename='airbnb-biens')
router.register(r'commandes', CommandeAirbnbViewSet, basename='airbnb-commandes')
router.register(r'filets', FiletLingeViewSet, basename='airbnb-filets')
router.register(r'observations-linge', ObservationLingeViewSet, basename='airbnb-observations-linge')
router.register(r'signalements', SignalementCommandeViewSet, basename='airbnb-signalements')
router.register(r'objets-trouves', ObjetTrouveViewSet, basename='airbnb-objets-trouves')
router.register(r'facturation', FacturationAirbnbViewSet, basename='airbnb-facturation')
router.register(r'journal-audit', JournalAuditAirbnbViewSet, basename='airbnb-journal-audit')

urlpatterns = [
    path('upload-photo/', AirbnbPhotoUploadView.as_view(), name='airbnb-upload-photo'),
    path('', include(router.urls)),
]
