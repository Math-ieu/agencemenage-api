from django.db import models
from django.conf import settings
from demandes.models import Demande
from agents.models import Agent


class Mission(models.Model):
    EN_ATTENTE = 'en_attente'
    CONFIRMEE = 'confirmee'
    EN_COURS = 'en_cours'
    TERMINEE = 'terminee'
    ANNULEE = 'annulee'
    STATUT_CHOICES = [
        (EN_ATTENTE, 'En attente'),
        (CONFIRMEE, 'Confirmée'),
        (EN_COURS, 'En cours'),
        (TERMINEE, 'Terminée'),
        (ANNULEE, 'Annulée'),
    ]

    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='missions')
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name='missions')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=EN_ATTENTE)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Mission'
        verbose_name_plural = 'Missions'
        ordering = ['-created_at']

    def __str__(self):
        return f"Mission {self.agent} → {self.demande}"
