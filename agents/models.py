from django.db import models


class Agent(models.Model):
    ACTIF = 'actif'
    INACTIF = 'inactif'
    EN_MISSION = 'en_mission'
    DISPONIBLE = 'disponible'

    STATUT_CHOICES = [
        (ACTIF, 'Actif'),
        (INACTIF, 'Inactif'),
        (EN_MISSION, 'En mission'),
        (DISPONIBLE, 'Disponible'),
    ]

    POSTE_CHOICES = [
        ('agent_menage', 'Agent de ménage'),
        ('garde_malade', 'Garde malade'),
        ('agent_nettoyage', 'Agent de nettoyage'),
        ('placement', 'Placement'),
        ('autre', 'Autre'),
    ]

    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    # Professional info
    poste = models.CharField(max_length=50, choices=POSTE_CHOICES, default='agent_menage')
    experience = models.CharField(max_length=100, blank=True)
    languages = models.JSONField(default=list, blank=True)
    nationality = models.CharField(max_length=100, blank=True)

    # Location
    city = models.CharField(max_length=100, blank=True)
    neighborhood = models.CharField(max_length=200, blank=True, verbose_name="Quartier/Adresse")

    # Status
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=DISPONIBLE)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    photo = models.ImageField(upload_to='agents/photos/', blank=True, null=True)

    class Meta:
        verbose_name = 'Agent / Profil'
        verbose_name_plural = 'Agents / Profils'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.get_poste_display()}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
