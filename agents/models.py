from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


class Agent(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    STATUT_CHOICES = [
        ('nouveau', 'Nouveau'),
        ('active', 'Active'),
        ('blacklist', 'Blacklisté'),
        ('stand_by', 'Stand by'),
        ('en_conge', 'En congé'),
        ('malade', 'Malade'),
    ]

    POSTE_CHOICES = [
        ('femme_menage', 'Femme de ménage'),
        ('garde_malade', 'Garde malade'),
        ('auxiliaire_vie', 'Auxiliaire de vie'),
        ('nounou', 'Nounou'),
        ('autre', 'Autre'),
    ]

    # Identity
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    gender = models.CharField(max_length=10, blank=True, choices=[('homme', 'Homme'), ('femme', 'Femme')], verbose_name="Sexe")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Date de naissance")
    marital_status = models.CharField(max_length=50, blank=True, verbose_name="Situation matrimoniale")
    has_children = models.BooleanField(default=False, verbose_name="A des enfants")

    # Professional info
    poste = models.CharField(max_length=50, choices=POSTE_CHOICES, default='femme_menage')
    experience = models.CharField(max_length=100, blank=True)
    experience_years = models.PositiveIntegerField(default=0, verbose_name="Expérience (années)")
    experience_months = models.PositiveIntegerField(default=0, verbose_name="Expérience (mois)")
    education_level = models.CharField(max_length=100, blank=True, verbose_name="Niveau d'étude")
    languages = models.JSONField(default=list, blank=True)
    nationality = models.CharField(max_length=100, blank=True, default="Marocaine")
    cin = models.CharField(max_length=50, blank=True, verbose_name="CIN")
    situation = models.CharField(max_length=50, blank=True, verbose_name="Situation familiale")
    type_profil = models.CharField(max_length=100, blank=True, verbose_name="Type de profil")

    # Characteristics
    training_details = models.TextField(blank=True, verbose_name="Formation requise")
    can_read_write = models.BooleanField(default=False, verbose_name="Sait lire et écrire")
    health_issues = models.CharField(max_length=255, blank=True, verbose_name="Maladie / Handicap")
    physical_appearance = models.CharField(max_length=100, blank=True, verbose_name="Présentation physique")
    corpulence = models.CharField(max_length=100, blank=True, verbose_name="Corpulence")
    allergy_animals = models.BooleanField(default=False, verbose_name="Allergie aux animaux")
    shoe_size = models.CharField(max_length=10, blank=True, verbose_name="Pointure de chaussures")
    is_smoking = models.BooleanField(default=False, verbose_name="Fume")

    # Availability
    availability_calendar = models.JSONField(default=dict, blank=True)
    avail_emergencies = models.BooleanField(default=False, verbose_name="Disponible pour les urgences")
    avail_7_7 = models.BooleanField(default=False, verbose_name="7 jours / 7")
    avail_day = models.BooleanField(default=False, verbose_name="Journée (7h-18h)")
    avail_holidays = models.BooleanField(default=False, verbose_name="Jours fériés")
    avail_evening = models.BooleanField(default=False, verbose_name="Soirée (après 18h)")

    # Location
    city = models.CharField(max_length=100, blank=True, default="Casablanca")
    neighborhood = models.CharField(max_length=200, blank=True, verbose_name="Quartier")

    # Status
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='nouveau')
    DISPONIBILITE_CHOICES = [
        ('disponible', 'Disponible'),
        ('non_disponible', 'Non disponible'),
        ('occupee', 'Occupée (en mission)'),
    ]
    disponibilite_intervention = models.CharField(
        max_length=20, 
        choices=DISPONIBILITE_CHOICES, 
        default='disponible', 
        verbose_name="Disponibilité d'intervention"
    )
    standby_days = models.PositiveIntegerField(null=True, blank=True, verbose_name="Nombre de jours standby")
    standby_until = models.DateField(null=True, blank=True, verbose_name="Standby jusqu'au")
    leave_start = models.DateField(null=True, blank=True, verbose_name="Début de congé")
    leave_end = models.DateField(null=True, blank=True, verbose_name="Fin de congé")

    # Meta
    registration_date = models.DateField(default=timezone.now, verbose_name="Date d'enregistrement")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    operator_notes = models.TextField(blank=True, verbose_name="Note de l'opérateur")
    recruiter_notes = models.TextField(blank=True, verbose_name="Remarque du recruteur")
    photo = models.ImageField(upload_to='agents/photos/', blank=True, null=True)
    photo2 = models.ImageField(upload_to='agents/photos/', blank=True, null=True)
    photo3 = models.ImageField(upload_to='agents/photos/', blank=True, null=True)
    active_photo = models.CharField(max_length=10, default='photo', choices=[('photo', 'Photo 1'), ('photo2', 'Photo 2')])
    cin_file = models.FileField(upload_to='agents/cin/', blank=True, null=True)
    cin_verso_file = models.FileField(upload_to='agents/cin/', blank=True, null=True, verbose_name="CIN Verso")
    attestation_file = models.FileField(upload_to='agents/attestations/', blank=True, null=True)
    fiche_antropometrique = models.FileField(upload_to='agents/fiches_antropometriques/', blank=True, null=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    is_blacklisted = models.BooleanField(default=False, db_index=True, verbose_name="Blacklisté")
    assigned_to = models.ForeignKey(
        'accounts.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='assigned_agents',
        verbose_name="Chargé assigné"
    )

    class Meta:
        verbose_name = 'Agent / Profil'
        verbose_name_plural = 'Agents / Profils'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.get_poste_display()}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def average_rating(self):
        # We check both direct mission feedback and demande feedback where this agent was the last sent
        from feedback.models import Feedback
        from django.db.models import Avg, Q
        
        avg = Feedback.objects.filter(
            Q(mission__agent=self) | 
            Q(demande__profils_envoyes=self)
        ).aggregate(avg_note=Avg('note_intervenant'))['avg_note']
        
        return round(avg, 1) if avg else None

    def save(self, *args, **kwargs):
        # Sync status and is_blacklisted
        if self.statut == 'blacklist':
            self.is_blacklisted = True
        elif self.is_blacklisted:
            self.statut = 'blacklist'
        
        # If is_blacklisted was True but status was changed to something else, clear is_blacklisted
        if self.statut != 'blacklist' and self.is_blacklisted:
            self.is_blacklisted = False
            
        # Update disponibilite_intervention automatically on save
        # Check for stand_by or en_conge expiration first
        today = timezone.now().date()
        
        # Sync standby_until if status is stand_by and standby_days is set
        if self.statut == 'stand_by':
            if self.standby_days and not self.standby_until:
                from datetime import timedelta
                self.standby_until = today + timedelta(days=self.standby_days)
            elif self.standby_until and today > self.standby_until:
                self.statut = 'active'
                self.standby_days = None
                self.standby_until = None
        elif self.statut == 'en_conge':
            if self.leave_end and today > self.leave_end:
                self.statut = 'active'
        else:
            self.standby_days = None
            self.standby_until = None
                
        # Now set disponibilite_intervention
        if self.statut in ['blacklist', 'stand_by', 'en_conge', 'malade']:
            self.disponibilite_intervention = 'non_disponible'
        else:
            # Check for active mission: confiremee or en_cours
            try:
                from missions.models import Mission
                active_missions = Mission.objects.filter(
                    agent=self,
                    statut__in=[Mission.CONFIRMEE, Mission.EN_COURS]
                ).exists()
            except Exception:
                active_missions = False
                
            if active_missions:
                self.disponibilite_intervention = 'occupee'
            else:
                self.disponibilite_intervention = 'disponible'

        super().save(*args, **kwargs)


class AgentExperience(models.Model):
    agent = models.ForeignKey(Agent, related_name='experiences', on_delete=models.CASCADE)
    position = models.CharField(max_length=200)
    company = models.CharField(max_length=200, blank=True)
    duration = models.CharField(max_length=100, blank=True)
    duration_text = models.CharField(max_length=100, blank=True, verbose_name="Depuis combien de temps ?")
    work_locations = models.JSONField(default=list, blank=True, verbose_name="Lieux de travail")
    tasks = models.JSONField(default=list, blank=True, verbose_name="Tâches")
    has_allergies = models.BooleanField(default=False, verbose_name="Allergies produits ménagers")
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.position} (Agent: {self.agent.id})"


class AgentAssignment(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='assignments')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agent_assignments'
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_agent_assignments'
    )
    assigned_by_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Affectation de Profil"
        verbose_name_plural = "Affectations de Profils"
        ordering = ['-created_at']

    def __str__(self):
        assigned_name = self.assigned_to.full_name if self.assigned_to else 'Non affecté'
        return f"Affectation {self.agent} -> {assigned_name}"

