from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import User


def _validate_strong_password(password, user=None):
    try:
        django_validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return password


class SelfProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer restreint pour la mise à jour de son propre profil (/api/auth/me/)."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'city']


class UserSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'role',
            'client', 'client_name', 'is_active', 'full_name', 'created_at',
            'phone', 'city'
        ]
        read_only_fields = ['created_at', 'full_name', 'client_name']

    def get_client_name(self, obj):
        return obj.client.display_name if obj.client else None

    def validate_role(self, value):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            if request.user.role != User.ADMIN and value == User.ADMIN:
                raise serializers.ValidationError("Seul un administrateur peut attribuer le rôle Administrateur.")
        return value


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    username = serializers.CharField(required=False, allow_blank=True)
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'role',
            'client', 'client_name', 'password', 'phone', 'city'
        ]
        read_only_fields = ['client_name']

    def get_client_name(self, obj):
        return obj.client.display_name if obj.client else None

    def validate_password(self, value):
        return _validate_strong_password(value)

    def validate_role(self, value):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            if request.user.role != User.ADMIN and value == User.ADMIN:
                raise serializers.ValidationError("Seul un administrateur peut attribuer le rôle Administrateur.")
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        # If username is empty string, remove it so the model's save() handles generation
        if 'username' in validated_data and not validated_data['username']:
            validated_data.pop('username')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        request = self.context.get('request') if self.context else None
        user = getattr(request, 'user', None) if request else None
        if user and not getattr(user, 'is_authenticated', False):
            user = None
        return _validate_strong_password(value, user=user)


class ForgotPasswordSerializer(serializers.Serializer):
    login = serializers.CharField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)
    login = serializers.CharField(required=True)
    code = serializers.CharField(required=True)

    def validate_new_password(self, value):
        return _validate_strong_password(value)
