from django.db import models


class Agent(models.Model):
    DISPONIBLE = 'disponible'
    NON_DISPONIBLE = 'non_disponible'

    STATUT_CHOICES = [
        (DISPONIBLE, 'Disponible'),
        (NON_DISPONIBLE, 'Non disponible'),
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

    # Availability
    avail_emergencies = models.BooleanField(default=False, verbose_name="Disponible pour les urgences")
    avail_7_7 = models.BooleanField(default=False, verbose_name="7 jours / 7")
    avail_day = models.BooleanField(default=False, verbose_name="Journée (7h-18h)")
    avail_holidays = models.BooleanField(default=False, verbose_name="Jours fériés")
    avail_evening = models.BooleanField(default=False, verbose_name="Soirée (après 18h)")

    # Location
    city = models.CharField(max_length=100, blank=True, default="Casablanca")
    neighborhood = models.CharField(max_length=200, blank=True, verbose_name="Quartier")

    # Status
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=DISPONIBLE)

    # Meta
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    operator_notes = models.TextField(blank=True, verbose_name="Note de l'opérateur")
    photo = models.ImageField(upload_to='agents/photos/', blank=True, null=True)
    cin_file = models.FileField(upload_to='agents/cin/', blank=True, null=True)
    attestation_file = models.FileField(upload_to='agents/attestations/', blank=True, null=True)
    fiche_antropometrique = models.FileField(upload_to='agents/fiches_antropometriques/', blank=True, null=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = 'Agent / Profil'
        verbose_name_plural = 'Agents / Profils'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.get_poste_display()}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


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
