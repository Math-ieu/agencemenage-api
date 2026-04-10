from django.db import models
from django.conf import settings
from clients.models import Client


class Demande(models.Model):
    # Source
    SITE = 'site'
    BACKOFFICE = 'backoffice'
    SOURCE_CHOICES = [
        (SITE, 'Site web'),
        (BACKOFFICE, 'Back-office'),
    ]

    # Statuts
    EN_ATTENTE = 'en_attente'
    ENCOURS = 'en_cours'
    ANNULE = 'annule'
    TERMINE = 'termine'
    STATUT_CHOICES = [
        (EN_ATTENTE, 'En attente'),
        (ENCOURS, 'En cours'),
        (ANNULE, 'Annulé'),
        (TERMINE, 'Terminé'),
    ]

    # Fréquences
    ONCE = 'oneshot'
    ABONNEMENT = 'abonnement'
    FREQUENCY_CHOICES = [
        (ONCE, 'Une fois'),
        (ABONNEMENT, 'Abonnement'),
    ]

    # Segments
    PARTICULIER = 'particulier'
    ENTREPRISE = 'entreprise'
    SEGMENT_CHOICES = [
        (PARTICULIER, 'Particulier'),
        (ENTREPRISE, 'Entreprise'),
    ]

    # Modes de paiement
    VIREMENT = 'virement'
    CHEQUE = 'cheque'
    AGENCE = 'agence'
    SUR_PLACE = 'sur_place'
    PAIEMENT_CHOICES = [
        (VIREMENT, 'Virement'),
        (CHEQUE, 'Par chèque'),
        (AGENCE, 'À l\'agence'),
        (SUR_PLACE, 'Sur place'),
    ]

    # Statuts paiement
    NON_PAYE = 'non_paye'
    ACOMPTE = 'acompte'
    PARTIEL = 'partiel'
    INTEGRAL = 'integral'
    PAIEMENT_STATUT_CHOICES = [
        (NON_PAYE, 'Non payé'),
        (ACOMPTE, 'Acompte versé'),
        (PARTIEL, 'Paiement partiel'),
        (INTEGRAL, 'Paiement intégral'),
    ]

    # Core fields
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='demandes', null=True, blank=True)
    service = models.CharField(max_length=200)
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES, default=PARTICULIER)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SITE)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=EN_ATTENTE)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default=ONCE)
    frequency_label = models.CharField(max_length=100, blank=True)

    # Scheduling
    date_intervention = models.DateField(null=True, blank=True)
    heure_intervention = models.CharField(max_length=50, blank=True)
    preference_horaire = models.CharField(max_length=50, blank=True, verbose_name="Préférence horaire")

    # Pricing
    prix = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Prix")
    is_devis = models.BooleanField(default=False, verbose_name="Sur devis")
    mode_paiement = models.CharField(max_length=20, choices=PAIEMENT_CHOICES, blank=True)
    statut_paiement = models.CharField(max_length=30, choices=PAIEMENT_STATUT_CHOICES, default=NON_PAYE)
    avance_paiement = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Assignment
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='demandes_assignees',
        verbose_name="Commercial assigné"
    )

    # Raw form data from website (JSON)
    formulaire_data = models.JSONField(default=dict, blank=True)

    # Confirmation avant opération
    cao = models.BooleanField(default=False, verbose_name="Confirmation avant opération")

    # Profils envoyés pour cette demande
    profils_envoyes = models.ManyToManyField(
        'agents.Agent',
        blank=True,
        related_name='demandes_proposees',
        verbose_name='Profils envoyés'
    )

    # Notes
    note_commercial = models.TextField(blank=True)
    note_operationnel = models.TextField(blank=True)
    avis_annulation = models.TextField(blank=True)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def reste_a_payer(self):
        """Calcule automatiquement le reste à payer."""
        if not self.prix:
            return 0
        if self.statut_paiement == self.NON_PAYE:
            return self.prix
        if self.statut_paiement == self.INTEGRAL:
            return 0
        if self.statut_paiement in [self.ACOMPTE, self.PARTIEL]:
            avance = self.avance_paiement or 0
            return max(0, self.prix - avance)
        return self.prix

    class Meta:
        verbose_name = 'Demande'
        verbose_name_plural = 'Demandes'
        ordering = ['-created_at']

    def __str__(self):
        client_name = self.client.display_name if self.client else "Sans client"
        return f"[{self.get_statut_display()}] {self.service} — {client_name}"


class NRPLog(models.Model):
    """Log des appels sans réponse du client."""
    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='nrp_logs')
    commercial = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'NRP'
        verbose_name_plural = 'NRPs'
        ordering = ['-date']

    def __str__(self):
        return f"NRP — {self.demande} ({self.date.strftime('%d/%m/%Y')})"


class Document(models.Model):
    DEVIS = 'devis'
    PNG = 'png'
    FACTURE = 'facture'
    AUTRE = 'autre'
    TYPE_CHOICES = [
        (DEVIS, 'Devis PDF'),
        (PNG, 'Récapitulatif PNG'),
        (FACTURE, 'Facture'),
        (AUTRE, 'Autre'),
    ]

    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='documents')
    type_document = models.CharField(max_length=20, choices=TYPE_CHOICES, default=AUTRE)
    fichier = models.FileField(upload_to='documents/%Y/%m/')
    nom = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        verbose_name = 'Document'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_type_document_display()} — {self.demande}"


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    action = models.CharField(max_length=200)
    model_name = models.CharField(max_length=100)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Journal d\'audit'
        verbose_name_plural = 'Journal d\'audit'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} — {self.model_name} #{self.object_id}"
