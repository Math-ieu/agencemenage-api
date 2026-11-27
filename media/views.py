import logging
import mimetypes
import os

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CookieJWTAuthentication
from accounts.permissions import AIRBNB_ONLY_ROLES
from agencemenage.media_signing import verify_media_signature

logger = logging.getLogger(__name__)

PUBLIC_MEDIA_PREFIXES = ('blog/', 'agents/photos/')

DANGEROUS_INLINE_MIMES = {
    'text/html',
    'image/svg+xml',
    'application/javascript',
    'text/javascript',
    'application/xhtml+xml',
    'text/xml',
    'application/xml',
}

DANGEROUS_EXTENSIONS = {'.svg', '.svgz', '.html', '.htm', '.xhtml', '.js', '.mjs', '.xml'}


class MediaFileView(APIView):
    """
    Sert les fichiers stockés dans le backend de stockage (S3 / local).
    - Préfixes publics (`blog/`, `agents/photos/`) accessibles sans auth.
    - Préfixes privés (`factures/`, `agents/cin/`, `documents/`, `airbnb/`, etc.) protégés
      par authentification JWT (cookie/Bearer) + contrôle RBAC ou signature HMAC temporaire (`?sig=`).
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def _is_public_path(self, file_path: str) -> bool:
        return file_path.startswith(PUBLIC_MEDIA_PREFIXES)

    def _authorize_private_access(self, request, file_path: str):
        sig = request.query_params.get('sig', '')
        if sig and verify_media_signature(file_path, sig):
            return None

        auth_result = CookieJWTAuthentication().authenticate(request)
        if not auth_result:
            return Response(
                {'detail': 'Authentification requise pour accéder à ce document.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user, _ = auth_result
        role = getattr(user, 'role', None)
        if role == 'admin':
            return None

        if file_path.startswith((
            'agents/cin/',
            'agents/fiches_antropometriques/',
            'agents/attestations/',
            'documents/',
            'finance/',
            'missions/',
        )):
            if role in AIRBNB_ONLY_ROLES:
                return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
            return None

        if file_path.startswith('factures/'):
            if role in ('runner', 'responsable_linge'):
                return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
            if role == 'client_conciergerie':
                from finance.models import Facture
                if not user.client_id or not Facture.objects.filter(client_id=user.client_id, pdf_file=file_path).exists():
                    return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
            return None

        if file_path.startswith('airbnb/fiches_mission/'):
            if role in ('client_conciergerie', 'responsable_linge'):
                return Response({'detail': 'Accès refusé.'}, status=status.HTTP_403_FORBIDDEN)
            return None

        return None

    def get(self, request, file_path):
        # Clean path (remove leading and trailing slash)
        file_path = file_path.strip('/')

        is_public = self._is_public_path(file_path)
        if not is_public:
            denied = self._authorize_private_access(request, file_path)
            if denied is not None:
                return denied

        try:
            if not default_storage.exists(file_path):
                raise Http404(f"File '{file_path}' not found.")
        except Http404:
            raise
        except Exception as e:
            logger.warning(f"Storage access error for '{file_path}': {e}")
            raise Http404(f"File '{file_path}' not found or inaccessible.")

        # Get file size for Content-Length
        try:
            file_size = default_storage.size(file_path)
        except Exception:
            file_size = None

        try:
            file_obj = default_storage.open(file_path, "rb")
        except Exception as e:
            logger.error(f"Error opening file '{file_path}': {e}")
            raise Http404(f"File '{file_path}' could not be opened.")

        content_type, encoding = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

        ext = os.path.splitext(file_path)[1].lower()
        force_attachment = (content_type.lower() in DANGEROUS_INLINE_MIMES) or (ext in DANGEROUS_EXTENSIONS)
        if force_attachment:
            content_type = "application/octet-stream"

        response = FileResponse(file_obj, content_type=content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        if force_attachment:
            safe_filename = os.path.basename(file_path).replace('"', '_')
            response["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
        if not is_public:
            response["Cache-Control"] = "private, no-store"

        if file_size is not None:
            response["Content-Length"] = file_size

        if encoding:
            response["Content-Encoding"] = encoding

        return response
