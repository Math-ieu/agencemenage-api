from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est obligatoire")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ADMIN = 'admin'
    MODERATEUR = 'moderateur'
    RESPONSABLE_COMMERCIAL = 'responsable_commercial'
    COMMERCIAL = 'commercial'
    RESPONSABLE_OPERATIONS = 'responsable_operations'
    CHARGE_OPERATIONS = 'charge_operations'
    OPERATIONNEL = 'operationnel'

    ROLE_CHOICES = [
        (ADMIN, 'Administrateur'),
        (MODERATEUR, 'Modérateur'),
        (RESPONSABLE_COMMERCIAL, 'Responsable Commercial'),
        (COMMERCIAL, 'Commercial'),
        (RESPONSABLE_OPERATIONS, 'Responsable des Opérations'),
        (CHARGE_OPERATIONS, 'Chargée des Opérations'),
        (OPERATIONNEL, 'Opérationnel'),
    ]

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=COMMERCIAL)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
