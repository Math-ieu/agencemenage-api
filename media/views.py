import mimetypes

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


class MediaFileView(APIView):
    """
    Public endpoint to serve files stored in the configured storage backend
    (S3 / Railway bucket in production, local filesystem in development).

    GET /api/media/<path:file_path>/
    No authentication required.
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # Skip auth entirely — public endpoint

    def get(self, request, file_path):
        if not default_storage.exists(file_path):
            raise Http404(f"File '{file_path}' not found.")

        file_obj = default_storage.open(file_path, "rb")

        content_type, encoding = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

        response = FileResponse(file_obj, content_type=content_type)

        if encoding:
            response["Content-Encoding"] = encoding

        return response
