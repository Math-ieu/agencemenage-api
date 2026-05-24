from django.db import models
from django.conf import settings
from demandes.models import Demande
from clients.models import Client

class PromoCode(models.Model):
    REDUCTION_TYPE_CHOICES = [
        ('pourcentage', 'Pourcentage (%)'),
        ('montant_fixe', 'Montant fixe (MAD)'),
    ]
    SEGMENT_CHOICES = [
        ('tous', 'Tous'),
        ('particulier', 'Particulier'),
        ('entreprise', 'Entreprise'),
        ('nouveaux', 'Nouveaux'),
    ]
    STATUS_CHOICES = [
        ('brouillon', 'Brouillon'),
        ('active', 'Actif'),
        ('desactivee', 'Inactif'),
        ('expiree', 'Expiré'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    reduction = models.DecimalField(max_digits=10, decimal_places=2)
    reduction_type = models.CharField(max_length=20, choices=REDUCTION_TYPE_CHOICES)
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon')
    customer_status = models.CharField(max_length=255)
    services = models.JSONField(default=list, blank=True)
    canaux = models.JSONField(default=list, blank=True)
    message_promotionnel = models.TextField(blank=True)
    uses = models.IntegerField(default=0)
    generated_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class CommercialGesture(models.Model):
    TYPE_CHOICES = [
        ('reduction_tarif', 'Réduction sur le tarif'),
        ('facturation_annulee', 'Facturation annulée'),
        ('intervention_gratuite', 'Intervention gratuite'),
    ]
    STATUS_CHOICES = [
        ('en_attente', 'En attente'),
        ('en_cours', 'En cours'),
        ('cloture', 'Clôturé'),
    ]
    REDUCTION_TYPE_CHOICES = [
        ('montant', 'Montant fixe'),
        ('pourcentage', 'Pourcentage (%)'),
    ]

    demande = models.ForeignKey(Demande, on_delete=models.SET_NULL, null=True, blank=True, related_name='gestes_commerciaux')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='gestes_commerciaux')
    date = models.DateField()
    gesture_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='en_attente')
    montant_ht = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    tva_active = models.BooleanField(default=False)
    reduction_type = models.CharField(max_length=20, choices=REDUCTION_TYPE_CHOICES, default='montant')
    reduction_value = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total_a_payer = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    part_profil = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    part_agence = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    motif = models.TextField(blank=True)
    envoyer_message = models.BooleanField(default=False)
    message_client = models.TextField(blank=True)
    canal_diffusion = models.JSONField(default=list, blank=True)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='gestes_crees')
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.demande:
            self.client = self.demande.client
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Geste {self.id} - {self.client}"


class Campaign(models.Model):
    TARGET_CHOICES = [
        ('client', 'Client'),
        ('profil', 'Profil'),
    ]
    SEGMENT_CHOICES = [
        ('tous', 'Tous'),
        ('particulier', 'Particulier'),
        ('entreprise', 'Entreprise'),
    ]
    STATUS_CHOICES = [
        ('brouillon', 'Brouillon'),
        ('programmee', 'Programmée'),
        ('envoyee', 'Envoyée'),
        ('annulee', 'Annulée'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField()
    target = models.CharField(max_length=20, choices=TARGET_CHOICES)
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES, default='tous')
    criteria = models.CharField(max_length=255, blank=True)
    channel = models.JSONField(default=list, blank=True)
    city = models.CharField(max_length=100, blank=True)
    broadcast_time_start = models.TimeField(null=True, blank=True)
    broadcast_time_end = models.TimeField(null=True, blank=True)
    broadcast_date = models.DateField(null=True, blank=True)
    per_day_dest = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='brouillon')
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
