from datetime import timedelta
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
    PRES_EN_COURS = 'pres_en_cours'
    PRES_TERMINEE = 'pres_terminee'
    STATUT_CHOICES = [
        (EN_ATTENTE, 'En attente'),
        (ENCOURS, 'En cours'),
        (ANNULE, 'Annulé'),
        (TERMINE, 'Terminé'),
        (PRES_EN_COURS, 'Pres. en cours'),
        (PRES_TERMINEE, 'Pres. terminée'),
    ]

    # Statuts du devis (workflow brief — indépendant de Demande.statut)
    DEVIS_BROUILLON = 'brouillon'
    DEVIS_EN_ATTENTE_VALIDATION = 'en_attente_validation'
    DEVIS_VALIDE = 'valide'
    DEVIS_ENVOYE = 'envoye'
    DEVIS_ACCEPTE = 'accepte'
    DEVIS_REFUSE = 'refuse'
    DEVIS_STATUT_CHOICES = [
        (DEVIS_BROUILLON, 'Brouillon'),
        (DEVIS_EN_ATTENTE_VALIDATION, 'En attente validation'),
        (DEVIS_VALIDE, 'Validé'),
        (DEVIS_ENVOYE, 'Envoyé'),
        (DEVIS_ACCEPTE, 'Accepté'),
        (DEVIS_REFUSE, 'Refusé / Expiré'),
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
    ESPECES = 'especes'
    CARTE = 'carte'
    PAIEMENT_CHOICES = [
        (VIREMENT, 'Par virement'),
        (CHEQUE, 'Par chèque'),
        (ESPECES, 'En espèces'),
        (CARTE, 'Par carte bancaire (solution de paiement en ligne)'),
        (AGENCE, 'À l\'agence'),
        (SUR_PLACE, 'Sur place'),
    ]

    NON_PAYE = 'non_paye'
    ACOMPTE = 'acompte'
    PARTIEL = 'partiel'
    INTEGRAL = 'integral'
    EN_ATTENTE = 'en_attente'
    INTERVENTION_GRATUITE = 'intervention_gratuite'
    FACTURATION_ANNULEE = 'facturation_annulee'
    PAIEMENT_STATUT_CHOICES = [
        (NON_PAYE, 'Non payé'),
        (ACOMPTE, 'Acompte versé'),
        (PARTIEL, 'Paiement partiel'),
        (INTEGRAL, 'Payé'),
        (EN_ATTENTE, 'Paiement en attente'),
        (INTERVENTION_GRATUITE, 'Intervention gratuite'),
        (FACTURATION_ANNULEE, 'Annulé'),
    ]

    # Core fields
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='demandes', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='demandes_creees',
        verbose_name="Créateur de la demande"
    )
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
    devis_statut = models.CharField(
        max_length=30, choices=DEVIS_STATUT_CHOICES, default=DEVIS_BROUILLON,
        verbose_name="Statut du devis"
    )
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
    assigned_to_operations = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='demandes_operations',
        verbose_name="Chargé des opérations assigné"
    )
    parent_demande = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='interventions_generees',
        verbose_name="Demande d'abonnement parente"
    )

    # Identification & Matching Logic
    ID_NOUVELLE = 'nouvelle'
    ID_EXISTANT = 'existant_valide'
    ID_VERIF_REQUISE = 'verification_requise'
    ID_STATUT_CHOICES = [
        (ID_NOUVELLE, 'Nouvelle'),
        (ID_EXISTANT, 'Client existe déjà'),
        (ID_VERIF_REQUISE, 'Vérification requise'),
    ]
    identification_statut = models.CharField(
        max_length=30, 
        choices=ID_STATUT_CHOICES, 
        default=ID_NOUVELLE,
        verbose_name="Statut d'identification"
    )
    potential_duplicate_client = models.ForeignKey(
        Client, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='demandes_suspectes',
        verbose_name="Client potentiel (doublon)"
    )

    # Raw form data from website (JSON)
    formulaire_data = models.JSONField(default=dict, blank=True)

    # Confirmation avant opération
    cao = models.BooleanField(default=False, verbose_name="Confirmation avant opération")
    
    # Gestion des parts
    part_agence = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Part agence")
    parts_repartition = models.JSONField(default=list, blank=True, verbose_name="Répartition des parts")

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

    def devis_numero(self):
        """Numéro de devis officiel, aligné sur le PDF (buildDevisNumber côté frontend) :
        DEV-{année}-{id sur 4 chiffres}."""
        from django.utils import timezone
        return f"DEV-{timezone.now().year}-{self.id:04d}"

    def requires_devis_validation(self):
        """Déclencheurs « En attente validation » (brief) : fin de chantier > 5 000 DH,
        post-sinistre grave, remise manuelle, déchets > 500 kg."""
        form = self.formulaire_data or {}
        service = (self.service or '').lower()

        def _num(*keys):
            for k in keys:
                v = form.get(k)
                if v not in (None, ''):
                    try:
                        return float(str(v).replace(' ', '').replace(',', '.'))
                    except (ValueError, TypeError):
                        continue
            return 0

        total = float(self.prix) if self.prix else _num('total', 'total_ht', 'montant_total', 'montant', 'prix')

        if ('fin de chantier' in service or 'fin chantier' in service) and total > 5000:
            return True
        if 'sinistre' in service:
            niveau = str(form.get('niveau') or form.get('gravite') or '').lower()
            if 'grave' in niveau:
                return True
        if _num('reduction', 'reduction_montant') > 0:
            return True
        if _num('poids_dechets', 'dechets_kg') > 500:
            return True
        return False

    def apply_devis_auto_validation(self):
        """Escalade brouillon -> en_attente_validation si un déclencheur s'applique.
        N'altère jamais un statut déjà avancé (validé / envoyé / accepté / refusé)."""
        if (self.is_devis
                and self.devis_statut == self.DEVIS_BROUILLON
                and self.requires_devis_validation()):
            self.devis_statut = self.DEVIS_EN_ATTENTE_VALIDATION
            return True
        return False

    class Meta:
        verbose_name = 'Demande'
        verbose_name_plural = 'Demandes'
        ordering = ['-created_at']

    def __str__(self):
        client_name = self.client.display_name if self.client else "Sans client"
        return f"[{self.get_statut_display()}] {self.service} — {client_name}"


class SubscriptionPlanning(models.Model):
    STATUS_CHOICES = [
        ('en_cours', 'En cours'),
        ('termine', 'Terminé'),
    ]
    
    demande = models.OneToOneField(Demande, on_delete=models.CASCADE, related_name='planning')
    jours_intervention = models.JSONField(default=list)  # ["lundi", "mercredi", "vendredi"]
    semaines = models.JSONField(default=list, blank=True)  # Detailed list of weeks with days and times
    heure_debut = models.TimeField(null=True, blank=True)
    heure_fin = models.TimeField(null=True, blank=True)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    statut = models.CharField(max_length=20, choices=STATUS_CHOICES, default='en_cours')
    notes = models.TextField(blank=True)
    notification_sent_dates = models.JSONField(default=list)  # Track sent notifications (dates as YYYY-MM-DD)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Planning d'abonnement"
        verbose_name_plural = "Plannings d'abonnement"

    def __str__(self):
        return f"Planning — {self.demande}"


class AppNotification(models.Model):
    TYPE_CHOICES = [
        ('rappel_intervention', 'Rappel intervention'),
        ('info', 'Information'),
    ]
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    target_roles = models.JSONField(default=list)  # ["operations", "admin"]
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Notification'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.created_at.strftime('%d/%m/%Y')})"


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


class ProfilShare(models.Model):
    """Lien unique généré pour partager un profil agent spécifique pour une demande."""
    import uuid
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    demande = models.ForeignKey(Demande, on_delete=models.CASCADE, related_name='shares')
    agent = models.ForeignKey('agents.Agent', on_delete=models.CASCADE, related_name='shares')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Partage de profil'
        ordering = ['-created_at']

    def __str__(self):
        return f"Partage {self.agent} pour {self.demande}"


from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from config.middleware import get_current_user

@receiver(pre_save, sender=Demande)
def log_demande_changes(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        old_instance = Demande.objects.get(pk=instance.pk)
    except Demande.DoesNotExist:
        return

    client = instance.client or old_instance.client
    if not client:
        return

    from clients.models import ClientActionLog
    current_user = get_current_user()

    # Check for changes in facturation
    old_fact = (old_instance.formulaire_data or {}).get('facturation', {}) if isinstance(old_instance.formulaire_data, dict) else {}
    new_fact = (instance.formulaire_data or {}).get('facturation', {}) if isinstance(instance.formulaire_data, dict) else {}

    old_statut_ui = old_fact.get('statut_paiement_ui') or old_instance.formulaire_data.get('statut_paiement_ui') if isinstance(old_instance.formulaire_data, dict) else None
    new_statut_ui = new_fact.get('statut_paiement_ui') or instance.formulaire_data.get('statut_paiement_ui') if isinstance(instance.formulaire_data, dict) else None

    if not old_statut_ui:
        old_statut_ui = getattr(old_instance, 'statut_paiement_ui', None)
    if not new_statut_ui:
        new_statut_ui = getattr(instance, 'statut_paiement_ui', None)

    old_annule = old_fact.get('facturation_annulee', False)
    new_annule = new_fact.get('facturation_annulee', False)

    paiement_ui_map = {
        'non_confirme': 'Non confirmé',
        'paiement_en_attente': 'Paiement en attente',
        'agence_payee_client': 'Agence payé / Client',
        'profil_paye_client': 'Profil payé / Client',
        'commercial_paye_client': 'Commercial payé / client',
        'paye': 'Payé',
        'paiement_partiel': 'Paiement partiel',
        'facturation_annulee': 'Annulé',
    }

    # 1. Facturation annulée
    if new_annule and not old_annule:
        raison = new_fact.get('annulation_raison') or instance.formulaire_data.get('annulation_raison') or 'Non spécifiée'
        profil_paye = new_fact.get('profil_sera_paye') or instance.formulaire_data.get('profil_sera_paye') or False
        montant_profil = new_fact.get('montant_profil_annulation') or instance.formulaire_data.get('montant_profil_annulation') or 0
        
        details_str = f"Raison : {raison} | "
        if profil_paye:
            details_str += f"Profil payé : {montant_profil} MAD"
        else:
            details_str += "Profil non payé"
            
        ClientActionLog.objects.create(
            client=client,
            action="Facturation annulée",
            details=details_str,
            user=current_user
        )
    # 2. Modification du statut paiement
    elif new_statut_ui != old_statut_ui and new_statut_ui:
        old_lbl = paiement_ui_map.get(old_statut_ui, old_statut_ui or 'Non défini')
        new_lbl = paiement_ui_map.get(new_statut_ui, new_statut_ui)
        ClientActionLog.objects.create(
            client=client,
            action="Modification du besoin",
            details=f"Statut paiement : {old_lbl} → {new_lbl}",
            user=current_user
        )
    # 3. Modification du statut de la demande
    elif instance.statut != old_instance.statut:
        status_label_map = {
            'en_attente': 'Nouveau besoin',
            'en_cours': 'En cours',
            'annule': 'Annulé',
            'termine': 'Terminé',
            'pres_en_cours': 'Prestation en cours',
            'pres_terminee': 'Prestation terminée',
        }
        old_lbl = status_label_map.get(old_instance.statut, old_instance.statut)
        new_lbl = status_label_map.get(instance.statut, instance.statut)
        
        ClientActionLog.objects.create(
            client=client,
            action=f"Statut passé à « {new_lbl} »",
            details=f"Statut demande : {old_lbl} → {new_lbl}",
            user=current_user
        )

@receiver(post_save, sender=Demande)
def log_demande_creation(sender, instance, created, **kwargs):
    if created and instance.client:
        from clients.models import ClientActionLog
        ClientActionLog.objects.create(
            client=instance.client,
            action="Nouveau besoin créé",
            details=f"Service : {instance.service} | Tarif : {instance.prix or 'À définir'} MAD",
            user=get_current_user()
        )


@receiver(pre_save, sender=Demande)
def handle_demande_cancellation(sender, instance, **kwargs):
    is_cancelled = False
    if not instance.pk:
        if instance.statut == Demande.ANNULE:
            is_cancelled = True
    else:
        try:
            old_instance = Demande.objects.get(pk=instance.pk)
            if instance.statut == Demande.ANNULE and old_instance.statut != Demande.ANNULE:
                is_cancelled = True
        except Demande.DoesNotExist:
            pass

    if is_cancelled:
        instance.prix = 0
        instance.part_agence = 0
        instance.parts_repartition = []
        instance.statut_paiement = Demande.FACTURATION_ANNULEE

        if not isinstance(instance.formulaire_data, dict):
            instance.formulaire_data = {}

        fact = instance.formulaire_data.get('facturation', {})
        if not isinstance(fact, dict):
            fact = {}

        fact['montant_ht'] = 0
        fact['total'] = 0
        fact['total_ht'] = 0
        fact['total_ttc'] = 0
        fact['montant_verse'] = 0
        fact['part_agence'] = 0
        fact['montant_agence_doit_profil'] = 0
        fact['montant_profil_doit_agence'] = 0
        fact['parts_repartition'] = []
        fact['statut_paiement_ui'] = 'facturation_annulee'
        fact['facturation_annulee'] = True
        fact['profil_sera_paye'] = False
        fact['montant_profil_annulation'] = 0

        instance.formulaire_data['facturation'] = fact
        instance.formulaire_data['statut_paiement_ui'] = 'facturation_annulee'


@receiver(post_save, sender=Demande)
def cancel_related_missions(sender, instance, **kwargs):
    if instance.statut == Demande.ANNULE:
        from missions.models import Mission
        Mission.objects.filter(demande=instance).update(
            statut=Mission.ANNULEE,
            montant_paye=0,
            montant_encaisse_profil=0,
            paiement_client_statut=Mission.PAIEMENT_ANNULE,
            part_profil_versee=False,
            part_agence_reversee=False,
            profil_sera_paye=False,
            montant_profil_annulation=0,
            montant_agence_doit_profil=0,
            montant_profil_doit_agence=0
        )




class FeteReligieuse(models.Model):
    """Calendrier des fêtes religieuses — saisie annuelle par l'admin (Section 4.2 du brief).

    Les dates des fêtes islamiques varient chaque année (calendrier hégirien).
    Règle de suspension : `jours_avant` avant + `jours_apres` après la date.
    Impact : passages annulés/reportés + notification automatique client & chargée de clientèle.
    """
    AID_KEBIR = 'aid_kebir'
    AID_FITR = 'aid_fitr'
    MAWLID = 'mawlid'
    TYPE_CHOICES = [
        (AID_KEBIR, 'Aïd el Kébir'),
        (AID_FITR, 'Aïd el Fitr'),
        (MAWLID, 'Mawlid Ennabawi'),
    ]

    type = models.CharField(max_length=100, verbose_name="Fête")
    date = models.DateField(verbose_name="Date de la fête")
    annee = models.IntegerField(verbose_name="Année")
    jours_avant = models.PositiveIntegerField(default=1, verbose_name="Jours suspendus avant")
    jours_apres = models.PositiveIntegerField(default=2, verbose_name="Jours suspendus après")
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fête religieuse"
        verbose_name_plural = "Fêtes religieuses"
        unique_together = ('type', 'annee')
        ordering = ['date']

    def __str__(self):
        return f"{self.get_type_display()} — {self.date}"

    def get_type_display(self):
        mapping = dict(self.TYPE_CHOICES)
        return mapping.get(self.type, self.type)

    @property
    def debut_suspension(self):
        return self.date - timedelta(days=self.jours_avant)

    @property
    def fin_suspension(self):
        return self.date + timedelta(days=self.jours_apres)

    def couvre(self, d):
        """La période de suspension (avant/après) couvre-t-elle la date d ?"""
        return self.debut_suspension <= d <= self.fin_suspension

    @classmethod
    def suspension_pour(cls, d):
        """Renvoie la fête dont la période de suspension couvre la date d, sinon None.
        Gère le chevauchement d'année (fête en tout début / toute fin d'année)."""
        for annee in (d.year, d.year - 1, d.year + 1):
            for f in cls.objects.filter(actif=True, annee=annee):
                if f.couvre(d):
                    return f
        return None
