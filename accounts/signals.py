import logging
import sys
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import User
from .emails import send_account_creation_email

logger = logging.getLogger(__name__)

@receiver(post_save, sender=User)
def handle_user_creation(sender, instance, created, **kwargs):
    if created:
        # Detect if running under tests
        is_testing = 'test' in sys.argv or getattr(settings, 'TESTING', False)
        
        if is_testing or not getattr(settings, 'RESEND_API_KEY', None):
            logger.info(f"Skipping welcome email for user {instance.email} (Testing or RESEND_API_KEY missing).")
            return
            
        try:
            logger.info(f"Sending welcome email for user {instance.email}...")
            send_account_creation_email(instance)
        except Exception as e:
            logger.error(f"Failed to send welcome email for user {instance.email}: {str(e)}")
