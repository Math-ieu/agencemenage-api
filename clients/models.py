from django.db import models


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
    neighborhood = models.CharField(max_length=200, blank=True, verbose_name="Quartier/Adresse")

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

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
        if self.segment == self.ENTREPRISE:
            return self.entity_name or self.contact_person
        return f"{self.first_name} {self.last_name}".strip() or self.phone
