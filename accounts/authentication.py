from rest_framework_simplejwt.authentication import JWTAuthentication

class CookieJWTAuthentication(JWTAuthentication):
    """
    Authentification JWT customisée qui cherche le token dans les cookies HttpOnly
    si le header Authorization n'est pas présent.
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
            return self.get_user(validated_token), validated_token
        except Exception:
            return None
