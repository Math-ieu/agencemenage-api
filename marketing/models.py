from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from demandes.models import Demande
from clients.models import Client

STATUS_LABEL_TO_KEY = {
    "Tous les clients": "tous",
    "Nouveau client": "nouveau",
    "Client inactif": "inactif",
    "Client régulier": "regulier",
    "Client abonné": "abonne",
}

def get_status_key_from_label(label: str) -> str:
    if not label:
        return "tous"
    if label in STATUS_LABEL_TO_KEY:
        return STATUS_LABEL_TO_KEY[label]
    lbl_lower = label.lower()
    if "nouveau" in lbl_lower:
        return "nouveau"
    if "inactif" in lbl_lower:
        return "inactif"
    if "regulier" in lbl_lower or "régulier" in lbl_lower:
        return "regulier"
    if "abonne" in lbl_lower or "abonné" in lbl_lower:
        return "abonne"
    return "tous"

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
    PROMO_TYPE_CHOICES = [
        ('simple', 'Simple'),
        ('bd', 'BD'),
    ]

    name = models.CharField(max_length=255)
    promo_type = models.CharField(max_length=20, choices=PROMO_TYPE_CHOICES, default='simple')
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
    limit_uses = models.IntegerField(null=True, blank=True)
    one_use_per_client = models.BooleanField(default=False)
    generated_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    archived = models.BooleanField(default=False)
    broadcasted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def matches_client(self, client) -> bool:
        """
        Check if the given client matches the customer_status target of this promo code.
        """
        status_key = get_status_key_from_label(self.customer_status)
        if status_key == 'tous':
            return True
            
        if client is None:
            # A new client (not in DB yet) only matches 'nouveau'
            return status_key == 'nouveau'
            
        from django.utils import timezone
        from datetime import timedelta
        
        if status_key == 'nouveau':
            demandes_count = client.demandes.count()
            is_new_by_date = client.created_at >= timezone.now() - timedelta(days=30)
            return demandes_count == 0 or is_new_by_date
            
        elif status_key == 'abonne':
            return client.demandes.filter(frequency='abonnement').exists()
            
        elif status_key == 'regulier':
            return client.demandes.count() >= 2
            
        elif status_key == 'inactif':
            # Has at least one demand, but none in the last 60 days
            has_demands = client.demandes.exists()
            has_recent_demands = client.demandes.filter(created_at__gte=timezone.now() - timedelta(days=60)).exists()
            return has_demands and not has_recent_demands
            
        return True

    def matches_phone(self, phone: str) -> tuple[bool, str]:
        """
        Check if a phone number matches the targeted client criteria.
        Returns a tuple of (is_valid, message).
        """
        if self.promo_type != 'bd':
            return True, ""
            
        if not phone:
            return False, "Veuillez renseigner votre téléphone pour appliquer ce code."
            
        from clients.models import Client
        phone_clean = phone.strip()
        phone_no_spaces = phone_clean.replace(" ", "")
        
        client = Client.objects.filter(phone=phone_clean, is_archived=False).order_by('-created_at').first()
        if not client:
            client = Client.objects.filter(phone=phone_no_spaces, is_archived=False).order_by('-created_at').first()
            
        if not self.matches_client(client):
            status_display = self.customer_status.lower()
            return False, f"Ce code promo est réservé aux cibles ({status_display})."
            
        return True, ""

    def broadcast_to_targets(self):
        """
        Broadcast this promo code to targeted clients via Email and/or WhatsApp.
        """
        if self.promo_type != 'bd' or self.status != 'active':
            return 0, 0

        from clients.models import Client
        from django.db.models import Count
        from django.utils import timezone
        from datetime import timedelta
        import logging
        logger = logging.getLogger(__name__)

        recipients = Client.objects.filter(is_archived=False, is_blacklisted=False)

        # Filter by segment
        if self.segment == 'particulier':
            recipients = recipients.filter(segment=Client.PARTICULIER)
        elif self.segment == 'entreprise':
            recipients = recipients.filter(segment=Client.ENTREPRISE)

        # Filter by customer status
        status_key = get_status_key_from_label(self.customer_status)
        if status_key == 'nouveau':
            cutoff_date = timezone.now() - timedelta(days=30)
            recipients = recipients.annotate(num_demandes=Count('demandes')).filter(
                models.Q(num_demandes=0) | models.Q(created_at__gte=cutoff_date)
            )
        elif status_key == 'abonne':
            recipients = recipients.filter(demandes__frequency='abonnement').distinct()
        elif status_key == 'regulier':
            recipients = recipients.annotate(num_demandes=Count('demandes')).filter(num_demandes__gte=2)
        elif status_key == 'inactif':
            recipients = recipients.filter(demandes__isnull=False).distinct()
            recent_cutoff = timezone.now() - timedelta(days=60)
            recipients = recipients.exclude(demandes__created_at__gte=recent_cutoff)

        sent_emails = 0
        sent_whatsapps = 0

        reduction_str = f"{self.reduction:.0f}%" if self.reduction_type == 'pourcentage' else f"{self.reduction:.0f} MAD"
        expiration_str = self.valid_until.strftime('%d/%m/%Y') if self.valid_until else "une date indéterminée"
        lien_str = "https://agencemenage.ma"

        for client in recipients:
            first_name = client.first_name or ""
            
            # Format/replace placeholders in message_promotionnel
            custom_msg = self.message_promotionnel or ""
            custom_msg = custom_msg.replace("{prénom}", first_name)
            custom_msg = custom_msg.replace("{prenom}", first_name)
            custom_msg = custom_msg.replace("{code}", self.code)
            custom_msg = custom_msg.replace("{valeur}", reduction_str)
            custom_msg = custom_msg.replace("{expiration}", expiration_str)
            custom_msg = custom_msg.replace("{lien}", lien_str)

            # Send Email if configured
            if 'email' in (self.canaux or []) and client.email:
                try:
                    from accounts.emails import send_resend_email, get_base_html_template
                    subject = f"Offre spéciale : {self.name}"
                    html_body = custom_msg.replace("\n", "<br>")
                    html_content = get_base_html_template(subject, html_body)
                    success = send_resend_email(client.email, subject, html_content)
                    if success:
                        sent_emails += 1
                except Exception as e:
                    logger.error(f"Error sending BD promo code email to {client.email}: {str(e)}")

            # Send WhatsApp if configured
            if 'whatsapp' in (self.canaux or []) and client.phone:
                try:
                    from demandes.utils.whatsapp import WhatsAppService
                    # Send template message
                    variables = [
                        first_name or "Client",
                        reduction_str,
                        self.code,
                        expiration_str,
                        lien_str
                    ]
                    res = WhatsAppService.send_template_message(
                        to=client.phone,
                        template_name='code_promo_bd',
                        variables=variables
                    )
                    if res:
                        sent_whatsapps += 1
                except Exception as e:
                    logger.error(f"Error sending BD promo code WhatsApp to {client.phone}: {str(e)}")

        return sent_emails, sent_whatsapps

    def __str__(self):
        return f"{self.name} ({self.code})"

@receiver(post_save, sender=Demande)
def increment_promo_code_uses(sender, instance, created, **kwargs):
    if created and instance.promo_code:
        promo = instance.promo_code
        promo.uses += 1
        promo.save(update_fields=['uses'])


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


from clients.models import ClientActionLog

@receiver(post_save, sender=CommercialGesture)
def log_commercial_gesture_creation(sender, instance, created, **kwargs):
    if created and instance.client:
        reduction_str = ""
        if instance.gesture_type == 'reduction_tarif':
            symbol = "%" if instance.reduction_type == 'pourcentage' else "MAD"
            val = float(instance.reduction_value)
            val_str = f"{val:.0f}" if val.is_integer() else f"{val}"
            reduction_str = f" (réduction de {val_str} {symbol})"
        elif instance.gesture_type == 'facturation_annulee':
            reduction_str = " (Facturation annulée)"
        elif instance.gesture_type == 'intervention_gratuite':
            reduction_str = " (Intervention gratuite)"
        
        # Details of the gesture
        details_str = f"Motif : {instance.motif or 'Non spécifié'}"
        if instance.demande:
            details_str += f" | Demande #{instance.demande.id} ({instance.demande.service})"
            
        ClientActionLog.objects.create(
            client=instance.client,
            action=f"Geste commercial{reduction_str}",
            details=details_str,
            user=instance.cree_par
        )


@receiver(post_save, sender=PromoCode)
def broadcast_promo_code_on_active(sender, instance, created, **kwargs):
    if instance.promo_type == 'bd' and instance.status == 'active' and not instance.broadcasted:
        # Mark broadcasted as True using update to bypass post_save signal loop
        PromoCode.objects.filter(pk=instance.pk).update(broadcasted=True)
        # Reflect change on the in-memory instance
        instance.broadcasted = True
        # Run the broadcast
        instance.broadcast_to_targets()

