from django.conf import settings
from rest_framework import viewsets, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.db.models import Q
import random

from .models import User, RolePermission, PasswordResetCode
from .serializers import (
    UserSerializer, UserCreateSerializer, ChangePasswordSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer
)
from .emails import send_password_reset_email


def set_jwt_cookies(response, access_token=None, refresh_token=None):
    if access_token:
        response.set_cookie(
            key='access_token',
            value=access_token,
            expires=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
            secure=getattr(settings, 'AUTH_COOKIE_SECURE', False),
            httponly=getattr(settings, 'AUTH_COOKIE_HTTP_ONLY', True),
            samesite=getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax')
        )
    if refresh_token:
        response.set_cookie(
            key='refresh_token',
            value=refresh_token,
            expires=settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'],
            secure=getattr(settings, 'AUTH_COOKIE_SECURE', False),
            httponly=getattr(settings, 'AUTH_COOKIE_HTTP_ONLY', True),
            samesite=getattr(settings, 'AUTH_COOKIE_SAMESITE', 'Lax')
        )

class CustomTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.CharField(required=False, allow_blank=True)
    username = serializers.CharField(required=False, allow_blank=True)
    login = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        login_val = attrs.get('email') or attrs.get('username') or attrs.get('login')
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
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            access_token = response.data.get('access')
            refresh_token = response.data.get('refresh')
            set_jwt_cookies(response, access_token, refresh_token)
            
            # On retire les tokens du payload JSON pour forcer l'usage des cookies exclusifs côté JS
            if 'access' in response.data:
                del response.data['access']
            if 'refresh' in response.data:
                del response.data['refresh']
        return response


class CookieTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({"detail": "Refresh token manquant dans les cookies."}, status=status.HTTP_401_UNAUTHORIZED)
        
        # Injecter le refresh token dans request.data de manière compatible
        # avec les QueryDict (form data) et les dict Python (JSON)
        if hasattr(request.data, '_mutable'):
            # QueryDict (application/x-www-form-urlencoded)
            request.data._mutable = True
            request.data['refresh'] = refresh_token
            request.data._mutable = False
        else:
            # dict Python standard (application/json) — on surcharge la propriété
            request._data = {**request.data, 'refresh': refresh_token}
        
        try:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                access_token = response.data.get('access')
                new_refresh_token = response.data.get('refresh')
                set_jwt_cookies(response, access_token, new_refresh_token)
                
                if 'access' in response.data:
                    del response.data['access']
                if 'refresh' in response.data:
                    del response.data['refresh']
            return response
        except InvalidToken as e:
            return Response({"detail": str(e)}, status=status.HTTP_401_UNAUTHORIZED)


class LogoutView(APIView):
    """Supprime les cookies d'authentification."""
    def post(self, request):
        response = Response({"message": "Déconnexion réussie"}, status=status.HTTP_200_OK)
        response.delete_cookie('access_token')
        response.delete_cookie('refresh_token')
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
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)
        return qs


class MeView(APIView):
    """Retourne l'utilisateur connecté."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({'error': 'Mot de passe actuel incorrect.'}, status=400)
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        return Response({'message': 'Mot de passe modifié avec succès.'})


class RolePermissionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
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

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login_val = serializer.validated_data['login']

        # Find user by email or username case-insensitively
        user = User.objects.filter(Q(email__iexact=login_val) | Q(username__iexact=login_val)).first()

        if user:
            # Generate OTP code (6 digits)
            otp_code = f"{random.randint(100000, 999999)}"
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

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        login_val = serializer.validated_data['login']
        code = serializer.validated_data['code']

        user = User.objects.filter(Q(email__iexact=login_val) | Q(username__iexact=login_val)).first()
        if not user:
            return Response(
                {"error": "Code de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        reset_code = PasswordResetCode.objects.filter(user=user, code=code, is_used=False).first()
        if not reset_code or not reset_code.is_valid():
            return Response(
                {"error": "Code de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Mark code as used
        reset_code.is_used = True
        reset_code.save()

        user.set_password(new_password)
        user.save()
        
        return Response(
            {"message": "Votre mot de passe a été réinitialisé avec succès."},
            status=status.HTTP_200_OK
        )
