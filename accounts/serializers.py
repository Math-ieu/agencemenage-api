from rest_framework import serializers
from .models import User


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


class ForgotPasswordSerializer(serializers.Serializer):
    login = serializers.CharField(required=True)


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)
    login = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
