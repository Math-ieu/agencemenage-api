from django.db import models
from django.conf import settings


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

    class Meta:
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
        ordering = ['-created_at']

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
    }
    
    changes = []
    for field, label in fields_to_track.items():
        old_val = getattr(old_instance, field, None)
        new_val = getattr(instance, field, None)
        
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

