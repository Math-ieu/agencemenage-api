from storages.backends.s3boto3 import S3Boto3Storage
from django.conf import settings

class ProxyS3Boto3Storage(S3Boto3Storage):
    """
    Custom S3 storage backend that generates URLs pointing to our API proxy
    instead of directly to the S3 bucket.
    
    URL pattern: /api/media/path/to/file
    """
    
    def _clean_name(self, name):
        """
        Normalize the name for S3 storage.
        """
        return name.replace('\\', '/')

    def url(self, name, parameters=None, expire=None, http_method=None):
        """
        Return the proxy URL for the given file name.
        """
        # We ensure name is clean for URLs
        name = self._clean_name(name)
        
        # We append name to MEDIA_URL (which should be '/api/media/')
        return f"{settings.MEDIA_URL}{name}"
