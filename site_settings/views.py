from rest_framework import viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import RoleBasedPermission
from .models import SiteConfig
from .serializers import SiteConfigSerializer, PublicSiteConfigSerializer


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
    Authentification et rôle autorisé (admin / parametres_globaux) requis.
    Modèle singleton : création (POST) et suppression (DELETE) interdites.
    """
    queryset = SiteConfig.objects.all()
    serializer_class = SiteConfigSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]
    http_method_names = ['get', 'put', 'patch', 'head', 'options']

    def list(self, request, *args, **kwargs):
        config = get_site_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)

    def perform_update(self, serializer):
        changed_fields = sorted(serializer.validated_data.keys())
        instance = serializer.save()
        from demandes.models import AuditLog
        AuditLog.objects.create(
            user=self.request.user if self.request.user.is_authenticated else None,
            action='update_site_config',
            model_name='SiteConfig',
            object_id=None,
            extra_data={
                'site_config_id': str(instance.pk),
                'changed_fields': changed_fields,
                'marrakech_status': instance.marrakech_status,
                'promo_banner_enabled': instance.promo_banner_enabled,
                'promo_banner_code': instance.promo_banner_code,
            },
        )


class SiteConfigPublicView(APIView):
    """
    API publique en lecture seule pour le site web agencemenage.
    N'expose strictement que les champs publics via PublicSiteConfigSerializer.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        config = get_site_config()
        serializer = PublicSiteConfigSerializer(config)
        return Response(serializer.data)
