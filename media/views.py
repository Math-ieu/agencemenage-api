import logging
import mimetypes

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class MediaFileView(APIView):
    """
    Public endpoint to serve files stored in the configured storage backend
    (S3 / Railway bucket in production, local filesystem in development).

    GET /api/media/<path:file_path>
    No authentication required.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Skip auth entirely — public endpoint

    def get(self, request, file_path):
        # Clean path (remove leading and trailing slash)
        file_path = file_path.strip('/')

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

        response = FileResponse(file_obj, content_type=content_type)
        
        if file_size is not None:
            response["Content-Length"] = file_size

        if encoding:
            response["Content-Encoding"] = encoding

        return response
