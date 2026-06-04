from rest_framework_simplejwt.authentication import JWTAuthentication
from config.middleware import set_current_user

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
        if header is None:
            # Cherche le token dans les cookies
            raw_token = request.COOKIES.get('access_token')
        else:
            raw_token = self.get_raw_token(header)
            
        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)
            set_current_user(user)
            return user, validated_token
        except Exception:
            return None
