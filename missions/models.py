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

    ENCAISSE_AGENCE = 'agence'
    ENCAISSE_PROFIL = 'profil'
    ENCAISSE_CHOICES = [
        (ENCAISSE_AGENCE, 'Agence'),
        (ENCAISSE_PROFIL, 'Profil'),
    ]

    PAIEMENT_NON_PAYE = 'non_paye'
    PAIEMENT_EN_ATTENTE = 'en_attente'
    PAIEMENT_EFFECTUE = 'effectue'
    PAIEMENT_PARTIEL = 'partiel'
    PAIEMENT_AGENCE_PAYEE = 'agence_payee_client'
    PAIEMENT_PROFIL_PAYE = 'profil_paye_client'
    PAIEMENT_COMMERCIAL_PAYE = 'commercial_paye_client'
    PAIEMENT_ANNULE = 'facturation_annulee'
    PAIEMENT_GRATUIT = 'intervention_gratuite'
    PAIEMENT_STATUT_CHOICES = [
        (PAIEMENT_NON_PAYE, 'Non payé'),
        (PAIEMENT_EN_ATTENTE, 'Paiement en attente'),
        (PAIEMENT_EFFECTUE, 'Paiement effectué'),
        (PAIEMENT_PARTIEL, 'Paiement partiel'),
        (PAIEMENT_AGENCE_PAYEE, 'Agence payée / Client'),
        (PAIEMENT_PROFIL_PAYE, 'Profil payé / Client'),
        (PAIEMENT_COMMERCIAL_PAYE, 'Commercial payé / client'),
        (PAIEMENT_ANNULE, 'Annulé'),
        (PAIEMENT_GRATUIT, 'Intervention gratuite'),
    ]


    MODE_VIREMENT = 'virement'
    MODE_CHEQUE = 'cheque'
    MODE_ESPECES_AGENCE = 'especes_agence'
    MODE_SUR_PLACE = 'sur_place'
    MODE_CHOICES = [
        (MODE_VIREMENT, 'Virement'),
        (MODE_CHEQUE, 'Chèque'),
        (MODE_ESPECES_AGENCE, "Espèces à l'agence"),
        (MODE_SUR_PLACE, 'Sur place'),
    ]

    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='missions')
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name='missions')
    intervenants = models.ManyToManyField(Agent, related_name='missions_incluses', blank=True)
    delegue = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True, related_name='missions_deleguees')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=EN_ATTENTE)
    date_debut = models.DateTimeField(null=True, blank=True)
    date_fin = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Finance mission
    encaisse_par = models.CharField(max_length=10, choices=ENCAISSE_CHOICES, default=ENCAISSE_AGENCE)
    montant_paye = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    montant_encaisse_profil = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mode_paiement_reel = models.CharField(max_length=20, choices=MODE_CHOICES, blank=True)
    date_paiement = models.DateField(null=True, blank=True)
    paiement_client_statut = models.CharField(max_length=30, choices=PAIEMENT_STATUT_CHOICES, default=PAIEMENT_NON_PAYE)
    justificatif_financier = models.FileField(upload_to='missions/finance/', null=True, blank=True)

    part_profil_versee = models.BooleanField(default=False)
    date_versement_profil = models.DateField(null=True, blank=True)
    part_agence_reversee = models.BooleanField(default=False)
    date_remise_agence = models.DateField(null=True, blank=True)

    # Complex Billing workflows
    annulation_raison = models.TextField(blank=True)
    profil_sera_paye = models.BooleanField(default=False)
    montant_profil_annulation = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    montant_agence_doit_profil = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    montant_profil_doit_agence = models.DecimalField(max_digits=10, decimal_places=2, default=0)

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
