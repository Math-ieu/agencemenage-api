from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import viewsets, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.db.models import Q
import hmac
import secrets

from .authentication import enforce_csrf
from .models import User, RolePermission, PasswordResetCode
from .serializers import (
    UserSerializer, UserCreateSerializer, SelfProfileUpdateSerializer,
    ChangePasswordSerializer, ForgotPasswordSerializer, ResetPasswordSerializer
)
from .emails import send_password_reset_email


class CsrfTokenView(APIView):
    """Retourne et dépose un jeton CSRF pour les clients authentifiés par cookies."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        token = get_token(request)
        return Response({'csrfToken': token})


def set_jwt_cookies(response, access_token=None, refresh_token=None):
    access_max_age = int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds())
    refresh_max_age = int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds())
    if access_token:
        response.set_cookie(
            key='access_token',
            value=access_token,
            max_age=access_max_age,
            path='/',
            secure=getattr(settings, 'AUTH_COOKIE_SECURE', False),
            httponly=getattr(settings, 'AUTH_COOKIE_HTTP_ONLY', True),
            samesite=getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax')
        )
    if refresh_token:
        response.set_cookie(
            key='refresh_token',
            value=refresh_token,
            max_age=refresh_max_age,
            path='/',
            secure=getattr(settings, 'AUTH_COOKIE_SECURE', False),
            httponly=getattr(settings, 'AUTH_COOKIE_HTTP_ONLY', True),
            samesite=getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax')
        )


def _blacklist_all_user_tokens(user):
    """Révoque tous les refresh tokens actifs d'un utilisateur (si token_blacklist est actif)."""
    try:
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        for token_obj in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token_obj)
    except Exception:
        pass

class CustomTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.CharField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    login = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        login_val = (attrs.get('email') or attrs.get('username') or attrs.get('login') or '').strip()
        password = attrs.get('password')

        if not login_val:
            raise serializers.ValidationError("L'adresse e-mail ou le nom d'utilisateur est requis.")

        self.user = authenticate(username=login_val, password=password)

        if not self.user:
            raise serializers.ValidationError("Aucun compte actif trouvé avec ces identifiants.")

        if not self.user.is_active:
            raise serializers.ValidationError("Ce compte est inactif.")

        refresh = RefreshToken.for_user(self.user)

        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(self.user).data
        }
        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = CustomTokenObtainPairSerializer
    throttle_scope = 'auth_login'

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            access_token = response.data.get('access')
            refresh_token = response.data.get('refresh')
            set_jwt_cookies(response, access_token, refresh_token)
            response.data['csrf_token'] = get_token(request)

            # On retire les tokens du payload JSON pour forcer l'usage des cookies exclusifs côté JS
            if 'access' in response.data:
                del response.data['access']
            if 'refresh' in response.data:
                del response.data['refresh']
        return response


class CookieTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        enforce_csrf(request)
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({"detail": "Refresh token manquant dans les cookies."}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = self.get_serializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        access_token = serializer.validated_data.get('access')
        new_refresh_token = serializer.validated_data.get('refresh')
        response = Response({'csrf_token': get_token(request)}, status=status.HTTP_200_OK)
        set_jwt_cookies(response, access_token, new_refresh_token)
        return response


class LogoutView(APIView):
    """Supprime les cookies d'authentification et révoque le refresh token."""
    def post(self, request):
        if (request.COOKIES.get('access_token') or request.COOKIES.get('refresh_token')) and not request.META.get('HTTP_AUTHORIZATION'):
            enforce_csrf(request)
        refresh_token = request.COOKIES.get('refresh_token')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                pass
        response = Response({"message": "Déconnexion réussie"}, status=status.HTTP_200_OK)
        samesite = getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax')
        response.delete_cookie('access_token', path='/', samesite=samesite)
        response.delete_cookie('refresh_token', path='/', samesite=samesite)
        return response


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_permissions(self):
        from .permissions import RoleBasedPermission
        return [IsAuthenticated(), RoleBasedPermission()]

    def get_queryset(self):
        qs = super().get_queryset()
        query_params = getattr(self.request, 'query_params', getattr(self.request, 'GET', {}))
        role = query_params.get('role')
        if role:
            if ',' in role:
                roles = [r.strip() for r in role.split(',') if r.strip()]
                qs = qs.filter(role__in=roles)
            else:
                qs = qs.filter(role=role)
        is_active = query_params.get('is_active')
        if is_active is not None:
            if is_active.lower() in ['true', '1']:
                qs = qs.filter(is_active=True)
            elif is_active.lower() in ['false', '0']:
                qs = qs.filter(is_active=False)
        return qs

    def _check_non_admin_mutation(self, request, instance, is_update=False):
        if request.user.role == User.ADMIN:
            return None
        if instance.role == User.ADMIN or instance.is_superuser:
            return Response(
                {"detail": "Seul un administrateur peut modifier ou supprimer un compte administrateur."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if is_update:
            from accounts.permissions import map_role_to_db_key
            db_role = map_role_to_db_key(request.user.role)
            rp = RolePermission.objects.filter(role=db_role).first()
            perms = rp.permissions if rp else []
            if 'activer_desactiver_utilisateurs' in perms and 'parametres_globaux' not in perms:
                extra_keys = set(request.data.keys()) - {'is_active'}
                if extra_keys:
                    return Response(
                        {"detail": "Vous êtes uniquement autorisé à activer ou désactiver un compte."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        denied = self._check_non_admin_mutation(request, instance, is_update=True)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        denied = self._check_non_admin_mutation(request, instance, is_update=False)
        if denied:
            return denied
        # Le compte de Mehdi Harit est strictement insupprimable
        if (
            (instance.email or '').lower() == 'mehdi@agencemenage.ma'
            or ('mehdi' in (instance.first_name or '').lower() and 'harit' in (instance.last_name or '').lower())
            or instance.id == 8
        ):
            return Response(
                {"error": "Le compte de Mehdi HARIT ne peut pas être supprimé."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)


class MeView(APIView):
    """Retourne l'utilisateur connecté."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = SelfProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({'error': 'Mot de passe actuel incorrect.'}, status=400)
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        _blacklist_all_user_tokens(user)
        return Response({'message': 'Mot de passe modifié avec succès.'})


class RolePermissionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from accounts.permissions import AIRBNB_ONLY_ROLES, map_role_to_db_key
        if request.user.role in AIRBNB_ONLY_ROLES:
            db_role = map_role_to_db_key(request.user.role)
            rp = RolePermission.objects.filter(role=db_role).first()
            return Response({db_role: rp.permissions if rp else []})
        permissions_dict = {}
        for rp in RolePermission.objects.all():
            permissions_dict[rp.role] = rp.permissions
        return Response(permissions_dict)

    def post(self, request):
        user = request.user
        allowed = False
        if user.role == 'admin':
            allowed = True
        else:
            from accounts.permissions import map_role_to_db_key
            db_role = map_role_to_db_key(user.role)
            try:
                rp = RolePermission.objects.filter(role=db_role).first()
                permissions_list = rp.permissions if rp else []
            except Exception:
                permissions_list = []
            if 'parametres_globaux' in permissions_list:
                allowed = True
                
        if not allowed:
            return Response({"detail": "Seuls les administrateurs ou les utilisateurs disposant du privilège parametres_globaux peuvent modifier les privilèges."}, status=status.HTTP_403_FORBIDDEN)
            
        data = request.data
        if not isinstance(data, dict):
            return Response({"detail": "Format de données invalide."}, status=status.HTTP_400_BAD_REQUEST)

        if user.role != User.ADMIN:
            if any(str(r).strip().lower() == 'admin' for r in data.keys()):
                return Response(
                    {"detail": "Seul un administrateur peut modifier les privilèges du rôle Administrateur."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            
        for role, perms in data.items():
            if not isinstance(perms, list):
                continue
            RolePermission.objects.update_or_create(
                role=role,
                defaults={'permissions': perms}
            )
            
        return Response({"message": "Permissions enregistrées avec succès."})


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth_forgot_password'

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_val = serializer.validated_data['login']

        # Find user by email or username case-insensitively
        user = User.objects.filter(Q(email__iexact=login_val) | Q(username__iexact=login_val)).first()

        if user:
            # Generate OTP code (6 digits using CSPRNG)
            otp_code = f"{secrets.randbelow(900000) + 100000}"
            # Delete/invalidate any previous codes for this user
            PasswordResetCode.objects.filter(user=user).update(is_used=True)
            # Create new reset code
            PasswordResetCode.objects.create(user=user, code=otp_code)

            # Send email
            try:
                send_password_reset_email(user, otp_code)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send password reset email: {str(e)}")

        # Always return success to prevent user enumeration attacks
        return Response(
            {"message": "Si le compte existe, un e-mail contenant les instructions de récupération a été envoyé."},
            status=status.HTTP_200_OK
        )


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'auth_reset_password'

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        login_val = serializer.validated_data['login']
        code = str(serializer.validated_data['code'] or '').strip()

        user = User.objects.filter(Q(email__iexact=login_val) | Q(username__iexact=login_val)).first()
        if not user:
            return Response(
                {"error": "Code de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        reset_code = PasswordResetCode.objects.filter(user=user, is_used=False).order_by('-created_at').first()
        if not reset_code or not reset_code.is_valid():
            return Response(
                {"error": "Code de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not hmac.compare_digest(str(reset_code.code), code):
            reset_code.attempts += 1
            if reset_code.attempts >= 5:
                reset_code.is_used = True
            reset_code.save(update_fields=['attempts', 'is_used'])
            return Response(
                {"error": "Code de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark code as used
        reset_code.is_used = True
        reset_code.save(update_fields=['is_used'])

        user.set_password(new_password)
        user.save()
        _blacklist_all_user_tokens(user)

        return Response(
            {"message": "Votre mot de passe a été réinitialisé avec succès."},
            status=status.HTTP_200_OK
        )
