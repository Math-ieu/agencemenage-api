import calendar
from datetime import date
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.utils import timezone


class Client(models.Model):
    PARTICULIER = 'particulier'
    ENTREPRISE = 'entreprise'
    SEGMENT_CHOICES = [
        (PARTICULIER, 'Particulier'),
        (ENTREPRISE, 'Entreprise'),
    ] 

    # Contact info
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    entity_name = models.CharField(max_length=200, blank=True, verbose_name="Nom entreprise")
    contact_person = models.CharField(max_length=200, blank=True, verbose_name="Personne de contact")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30)
    whatsapp = models.CharField(max_length=30, blank=True)

    # Segment
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES, default=PARTICULIER)

    # Location
    city = models.CharField(max_length=100, blank=True)
    neighborhood = models.CharField(max_length=200, blank=True, verbose_name="Quartier")
    address = models.TextField(blank=True, verbose_name="Adresse")

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    avis_commercial = models.TextField(blank=True, verbose_name="Avis commercial")
    avis_operationnel = models.TextField(blank=True, verbose_name="Avis opérationnel")
    is_archived = models.BooleanField(default=False, db_index=True)
    is_blacklisted = models.BooleanField(default=False, db_index=True, verbose_name="Blacklisté")
    opt_out_feedback = models.BooleanField(default=False, verbose_name="Désinscription Feedback")
    
    assigned_commercial = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='clients_geres',
        verbose_name="Commercial assigné (Owner)"
    )
    phone_history = models.JSONField(default=list, blank=True, verbose_name="Historique des numéros")

    # Champs spécifiques module Airbnb / Conciergerie
    TYPE_CLIENT_AIRBNB_CHOICES = [
        ('conciergerie', 'Conciergerie'),
        ('particulier', 'Particulier'),
        ('agence', 'Agence'),
        ('autre', 'Autre'),
    ]
    MODE_PAIEMENT_AIRBNB_CHOICES = [
        ('passage', 'Après chaque passage'),
        ('mensuel', 'Mensuel groupé'),
    ]
    STATUT_AIRBNB_CHOICES = [
        ('actif', 'Actif'),
        ('suspendu', 'Suspendu'),
    ]

    trigramme = models.CharField(max_length=5, unique=True, null=True, blank=True, db_index=True)
    type_client_airbnb = models.CharField(
        max_length=30,
        choices=TYPE_CLIENT_AIRBNB_CHOICES,
        default='conciergerie',
        blank=True,
    )
    mode_paiement_airbnb = models.CharField(
        max_length=20,
        choices=MODE_PAIEMENT_AIRBNB_CHOICES,
        default='passage',
    )
    date_demarrage_airbnb = models.DateField(null=True, blank=True)
    probatoire_jusqu_au = models.DateField(null=True, blank=True)
    probatoire_bascule_annulee = models.BooleanField(default=False)
    statut_airbnb = models.CharField(
        max_length=20,
        choices=STATUT_AIRBNB_CHOICES,
        default='actif',
        db_index=True,
    )
    eligible_conciergerie = models.BooleanField(default=False)
    derniere_verification_conciergerie = models.DateField(null=True, blank=True)
    reclassement_preavis_envoye_le = models.DateField(null=True, blank=True)
    contrat_signe_airbnb = models.BooleanField(default=False)
    contrat_signe_date_airbnb = models.DateField(null=True, blank=True)
    contrat_signe_url_airbnb = models.URLField(max_length=500, blank=True, default='')

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.trigramme is not None:
            cleaned = self.trigramme.strip().upper()
            self.trigramme = cleaned if cleaned else None
        if (
            self.mode_paiement_airbnb == 'mensuel'
            and not self.probatoire_bascule_annulee
            and self.probatoire_jusqu_au is None
        ):
            if self.date_demarrage_airbnb is None:
                self.date_demarrage_airbnb = timezone.localdate()
            d = self.date_demarrage_airbnb
            month_idx = d.month - 1 + 2
            year = d.year + month_idx // 12
            month = month_idx % 12 + 1
            last_day = calendar.monthrange(year, month)[1]
            self.probatoire_jusqu_au = date(year, month, min(d.day, last_day))
        super().save(*args, **kwargs)

    def __str__(self):
        if self.segment == self.ENTREPRISE:
            return f"{self.entity_name} ({self.phone})"
        return f"{self.first_name} {self.last_name} ({self.phone})"

    @property
    def display_name(self):
        name_parts = f"{self.first_name} {self.last_name}".strip()
        if self.segment == self.ENTREPRISE:
            return self.entity_name or self.contact_person or name_parts or self.phone
        return name_parts or self.entity_name or self.phone

    @staticmethod
    def airbnb_client_q():
        """Predicat ORM identifiant strictement les clients du module Airbnb."""
        return (
            Q(demandes__service__icontains='airbnb')
            | Q(demandes__service__icontains='air bnb')
            | Q(demandes__service__icontains='conciergerie')
            | Q(biens_airbnb__isnull=False)
            | (Q(trigramme__isnull=False) & ~Q(trigramme=''))
            | Q(date_demarrage_airbnb__isnull=False)
            | Q(contrat_signe_airbnb=True)
        )

    def is_airbnb_client(self):
        """Indique si ce client appartient au périmètre Airbnb."""
        return bool(
            (self.trigramme and self.trigramme.strip())
            or self.date_demarrage_airbnb is not None
            or self.contrat_signe_airbnb
            or (hasattr(self, 'biens_airbnb') and self.biens_airbnb.exists())
            or self.demandes.filter(
                Q(service__icontains='airbnb')
                | Q(service__icontains='air bnb')
                | Q(service__icontains='conciergerie')
            ).exists()
        )

class ClientActionLog(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='action_logs')
    action = models.CharField(max_length=255)
    details = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_action_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Historique Action Client'
        verbose_name_plural = 'Historiques Actions Client'


from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from config.middleware import get_current_user

@receiver(post_save, sender=Client)
def log_client_creation(sender, instance, created, **kwargs):
    if created:
        ClientActionLog.objects.create(
            client=instance,
            action="Création du client",
            details="Fiche client créée",
            user=get_current_user()
        )

@receiver(pre_save, sender=Client)
def log_client_changes(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_instance = Client.objects.get(pk=instance.pk)
    except Client.DoesNotExist:
        return
        
    if instance.is_blacklisted != old_instance.is_blacklisted:
        action_name = "Client blacklisté" if instance.is_blacklisted else "Client retiré de la blacklist"
        details_str = "Le client a été ajouté à la liste noire." if instance.is_blacklisted else "Le client a été retiré de la liste noire."
        ClientActionLog.objects.create(
            client=instance,
            action=action_name,
            details=details_str,
            user=get_current_user()
        )

    # Track changes to standard client fields
    fields_to_track = {
        'first_name': 'Prénom',
        'last_name': 'Nom',
        'entity_name': 'Nom entreprise',
        'email': 'Email',
        'phone': 'Téléphone',
        'whatsapp': 'WhatsApp',
        'segment': 'Segment',
        'city': 'Ville',
        'neighborhood': 'Quartier',
        'address': 'Adresse',
        'assigned_commercial': 'Commercial',
    }
    
    changes = []
    for field, label in fields_to_track.items():
        old_val = getattr(old_instance, field, None)
        new_val = getattr(instance, field, None)
        
        if field == 'assigned_commercial':
            old_str = old_val.full_name if old_val else ''
            new_str = new_val.full_name if new_val else ''
        else:
            old_str = str(old_val or '').strip()
            new_str = str(new_val or '').strip()
        
        if old_str != new_str:
            if field == 'segment':
                old_str = 'Particulier' if old_str == 'particulier' else 'Entreprise' if old_str == 'entreprise' else old_str
                new_str = 'Particulier' if new_str == 'particulier' else 'Entreprise' if new_str == 'entreprise' else new_str
                
            old_display = old_str if old_str else "[Vide]"
            new_display = new_str if new_str else "[Vide]"
            changes.append(f"{label} : {old_display} → {new_display}")
            
    if changes:
        details_str = " | ".join(changes)
        ClientActionLog.objects.create(
            client=instance,
            action="Informations modifiées",
            details=details_str,
            user=get_current_user()
        )


@receiver(pre_save, sender=Client)
def detect_commercial_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_instance = Client.objects.get(pk=instance.pk)
        instance._commercial_changed = (instance.assigned_commercial != old_instance.assigned_commercial)
    except Client.DoesNotExist:
        pass


@receiver(post_save, sender=Client)
def sync_demandes_on_client_commercial_change(sender, instance, created, **kwargs):
    if not created and getattr(instance, '_commercial_changed', False):
        instance.demandes.all().update(assigned_to=instance.assigned_commercial)


class ClientCommercialAssignment(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='assignments')
    commercial = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='client_assignments'
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_assignments'
    )
    assigned_by_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Affectation Commercial Client'
        verbose_name_plural = 'Affectations Commerciaux Client'


