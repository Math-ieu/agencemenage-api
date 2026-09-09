from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import SiteConfig
from .serializers import SiteConfigSerializer


def get_site_config() -> SiteConfig:
    """Récupère la configuration unique du site ou l'initialise avec les valeurs par défaut."""
    config = SiteConfig.objects.first()
    if not config:
        config = SiteConfig.objects.create(
            whatsapp_notification_numbers=[
                "+212664331463",
                "+212664267811",
                "+212664226790",
                "+212619900923"
            ]
        )
    return config


class SiteConfigViewSet(viewsets.ModelViewSet):
    """
    API pour la gestion des paramètres du site côté administration.
    Authentification requise.
    """
    queryset = SiteConfig.objects.all()
    serializer_class = SiteConfigSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        config = get_site_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)


class SiteConfigPublicView(APIView):
    """
    API publique en lecture seule pour le site web agencemenage.
    Aucune authentification requise.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        config = get_site_config()
        serializer = SiteConfigSerializer(config)
        return Response(serializer.data)
