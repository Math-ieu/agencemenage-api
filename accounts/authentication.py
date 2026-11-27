from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication
from config.middleware import set_current_user


def _dummy_get_response(request):
    return None


def enforce_csrf(request):
    """Vérifie le jeton CSRF pour les requêtes authentifiées par cookies."""
    raw_request = getattr(request, '_request', request)
    if getattr(raw_request, '_dont_enforce_csrf_checks', False):
        return
    check = CsrfViewMiddleware(_dummy_get_response)
    check.process_request(raw_request)
    reason = check.process_view(raw_request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f'CSRF Failed: {reason}')


class ThreadSafeJWTAuthentication(JWTAuthentication):
    """
    Subclass JWTAuthentication to set thread-local context variable on successful authentication.
    """
    def authenticate(self, request):
        result = super().authenticate(request)
        if result:
            user, token = result
            set_current_user(user)
        return result


class CookieJWTAuthentication(ThreadSafeJWTAuthentication):
    """
    Authentification JWT customisée qui cherche le token dans les cookies HttpOnly
    si le header Authorization n'est pas présent, et enregistre l'utilisateur
    dans le thread context.
    """
    def authenticate(self, request):
        header = self.get_header(request)
        used_cookie = False
        if header is None:
            # Cherche le token dans les cookies
            raw_token = request.COOKIES.get('access_token')
            used_cookie = raw_token is not None
        else:
            raw_token = self.get_raw_token(header)

        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
        except Exception:
            return None

        if used_cookie and request.method not in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
            enforce_csrf(request)

        set_current_user(user)
        return user, validated_token
