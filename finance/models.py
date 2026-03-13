from django.db import models
from django.conf import settings
from clients.models import Client
from demandes.models import Demande


class Facture(models.Model):
    EN_ATTENTE = 'en_attente'
    PARTIEL = 'partiel'
    PAYE = 'paye'
    ANNULE = 'annule'
    STATUT_CHOICES = [
        (EN_ATTENTE, 'En attente'),
        (PARTIEL, 'Partiellement payée'),
        (PAYE, 'Payée'),
        (ANNULE, 'Annulée'),
    ]

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='factures')
    demande = models.ForeignKey(Demande, on_delete=models.SET_NULL, null=True, blank=True, related_name='factures')
    numero = models.CharField(max_length=50, unique=True)
    montant_total = models.DecimalField(max_digits=10, decimal_places=2)
    montant_paye = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=EN_ATTENTE)
    date_emission = models.DateField(auto_now_add=True)
    date_echeance = models.DateField(null=True, blank=True)
    pdf_file = models.FileField(upload_to='factures/', null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Facture'
        verbose_name_plural = 'Factures'
        ordering = ['-created_at']

    def __str__(self):
        return f"Facture {self.numero} — {self.client}"

    @property
    def reste_a_payer(self):
        return self.montant_total - self.montant_paye


class Paiement(models.Model):
    VIREMENT = 'virement'
    CARTE = 'carte'
    CHEQUE = 'cheque'
    ESPECES = 'especes'
    MODE_CHOICES = [
        (VIREMENT, 'Virement'),
        (CARTE, 'Par carte'),
        (CHEQUE, 'Par chèque'),
        (ESPECES, 'Espèces'),
    ]

    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name='paiements')
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Paiement'
        ordering = ['-date']

    def __str__(self):
        return f"{self.montant} MAD ({self.get_mode_display()}) — {self.facture.numero}"


class EntreeCaisse(models.Model):
    """Entrée de caisse journalière."""
    ENTREE = 'entree'
    SORTIE = 'sortie'
    TYPE_CHOICES = [
        (ENTREE, 'Entrée'),
        (SORTIE, 'Sortie'),
    ]

    type_mouvement = models.CharField(max_length=10, choices=TYPE_CHOICES)
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=300)
    date = models.DateField()
    paiement = models.ForeignKey(Paiement, on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Entrée de caisse'
        verbose_name_plural = 'Caisse'
        ordering = ['-date']

    def __str__(self):
        return f"{self.get_type_mouvement_display()} {self.montant} MAD — {self.date}"
