from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PromoCodeViewSet, CommercialGestureViewSet, CampaignViewSet

router = DefaultRouter()
router.register(r'promos', PromoCodeViewSet, basename='promo')
router.register(r'gestes', CommercialGestureViewSet, basename='geste')
router.register(r'campagnes', CampaignViewSet, basename='campagne')

urlpatterns = [
    path('', include(router.urls)),
]
