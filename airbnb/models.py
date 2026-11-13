from django.db import models
from django.conf import settings
import uuid


def default_intervenantes_par_typologie():
    return {
        'studio': 1,
        '1ch': 1,
        '2ch': 1,
        '3ch': 1,
        '4ch': 1,
        '5ch': 1,
        'villa_riad': 2,
    }


def default_zones_eloignees():
    return [
        "Bouskoura",
        "Dar Bouazza",
        "Mohammédia",
        "Ville Verte",
        "Mansouria",
        "Benslimane",
        "Sidi Rahal",
        "Almaz",
    ]


def default_photos_attendues():
    return ["Salon", "Cuisine", "Salle de bain", "Chambres"]


def default_set_composition_standard():
    return {
        "housses": 1,
        "draps": 1,
        "taies": 2,
        "grandes_serviettes": 2,
        "petites_serviettes": 2,
    }


def default_articles_hors_set():
    return [
        {"code": "drap_housse", "label": "Drap housse", "actif": True},
        {"code": "tapis_bain", "label": "Tapis de bain", "actif": True},
        {"code": "torchon", "label": "Torchon", "actif": True},
        {"code": "peignoir", "label": "Peignoir", "actif": True},
        {"code": "autre", "label": "Autre article", "actif": True, "libelle_libre": True},
    ]


def default_services_souscrits():
    return ['menage', 'linge']


class AirbnbConfig(models.Model):
    """
    Configuration globale des tarifs, suppléments de zones et règles du module Airbnb.
    Modèle singleton ou paramétrage dynamique.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Tarifs de base ménage par typologie (MAD) — Maquette p.25
    prix_studio = models.DecimalField(max_digits=10, decimal_places=2, default=130.00, verbose_name="Prix Studio")
    prix_1ch = models.DecimalField(max_digits=10, decimal_places=2, default=130.00, verbose_name="Prix 1 Chambre")
    prix_2ch = models.DecimalField(max_digits=10, decimal_places=2, default=160.00, verbose_name="Prix 2 Chambres")
    prix_3ch = models.DecimalField(max_digits=10, decimal_places=2, default=190.00, verbose_name="Prix 3 Chambres")
    prix_4ch = models.DecimalField(max_digits=10, decimal_places=2, default=220.00, verbose_name="Prix 4 Chambres")
    prix_5ch = models.DecimalField(max_digits=10, decimal_places=2, default=250.00, verbose_name="Prix 5 Chambres")
    prix_villa_riad = models.DecimalField(max_digits=10, decimal_places=2, default=300.00, verbose_name="Prix Villa / Riad")
    intervenantes_par_typologie = models.JSONField(
        default=default_intervenantes_par_typologie,
        blank=True,
        verbose_name="Nombre d'intervenantes par typologie",
    )

    # Seuil conciergerie & reclassement
    seuil_biens_conciergerie = models.PositiveIntegerField(default=3, verbose_name="Seuil minimum biens conciergerie")
    tarif_repli_standard = models.DecimalField(max_digits=10, decimal_places=2, default=240.00, verbose_name="Tarif de repli standard (4h, MAD)")
    delai_verif_seuil_mois = models.PositiveIntegerField(default=1, verbose_name="Délai de vérification du seuil (mois)")
    preavis_reclassement_jours = models.PositiveIntegerField(default=15, verbose_name="Préavis de reclassement (jours)")

    # Suppléments & Zones
    supplement_zone_eloignee = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Supplément zone éloignée (MAD)")
    zones_eloignees_list = models.JSONField(
        default=default_zones_eloignees,
        blank=True,
        verbose_name="Liste des zones éloignées (ex: Bouskoura, Dar Bouazza)"
    )

    # Options & Remise en état
    prix_reassort_essentiel = models.DecimalField(max_digits=10, decimal_places=2, default=49.00, verbose_name="Prix Réassort Essentiel (MAD)")
    prix_reassort_confort = models.DecimalField(max_digits=10, decimal_places=2, default=79.00, verbose_name="Prix Réassort Confort (MAD)")
    prix_video = models.DecimalField(max_digits=10, decimal_places=2, default=10.00, verbose_name="Prix option Vidéo avant/après (MAD)")
    prix_materiel = models.DecimalField(max_digits=10, decimal_places=2, default=29.00, verbose_name="Prix option Matériel fourni (MAD)")
    tarif_remise_en_etat_heure = models.DecimalField(max_digits=10, decimal_places=2, default=60.00, verbose_name="Tarif horaire remise en état (MAD/h)")
    photos_attendues = models.JSONField(
        default=default_photos_attendues,
        blank=True,
        verbose_name="Photos attendues par défaut",
    )

    # Tarification & Paramètres Chaîne du Linge
    set_composition_standard = models.JSONField(
        default=default_set_composition_standard,
        blank=True,
        verbose_name="Composition standard du set (8 pièces)",
    )
    articles_hors_set = models.JSONField(
        default=default_articles_hors_set,
        blank=True,
        verbose_name="Articles hors set proposés sur la borne",
    )
    prix_set_linge_standard = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Prix 1 Set Standard (8 pièces)")
    prix_piece_supp_linge = models.DecimalField(max_digits=10, decimal_places=2, default=5.00, verbose_name="Prix par pièce supplémentaire")
    forfait_min_linge = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Forfait minimum linge présent")
    sets_rechange_requis = models.PositiveIntegerField(default=3, verbose_name="Nombre de sets de rechange exigés")
    delai_lavage_heures = models.PositiveIntegerField(default=48, verbose_name="Délai de lavage (heures)")
    remplissage_max_filet_pct = models.PositiveIntegerField(default=60, verbose_name="Taux de remplissage max filet (%)")
    ecart_tolere_pieces = models.PositiveIntegerField(default=0, verbose_name="Écart toléré au recomptage (pièces)")

    # Heures Cut-Off & Délais facturation
    cutoff_matin = models.TimeField(default="21:00", verbose_name="Heure Cut-off matin (veille)")
    cutoff_apres_midi = models.TimeField(default="22:00", verbose_name="Heure Cut-off après-midi (veille)")
    cutoff_apres_midi_illimite = models.BooleanField(default=True, verbose_name="Cut-off après-midi illimité la veille")
    jour_emission_mensuelle = models.PositiveIntegerField(default=26, verbose_name="Jour d'émission mensuelle")
    delai_paiement_jours = models.PositiveIntegerField(default=4, verbose_name="Délai de paiement (jours)")
    duree_probatoire_mois = models.PositiveIntegerField(default=2, verbose_name="Durée période probatoire (mois)")

    # Synchro iCal
    ical_frequence_jour = models.PositiveIntegerField(default=3, verbose_name="Fréquence synchro iCal par jour")
    ical_heure_defaut = models.TimeField(default="11:00", verbose_name="Heure proposée par défaut (iCal)")
    ical_horizon_jours = models.PositiveIntegerField(default=15, verbose_name="Horizon de détection iCal (jours)")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration Airbnb"
        verbose_name_plural = "Configurations Airbnb"

    def __str__(self):
        return "Configuration Tarifaire & Paramètres Airbnb"


class GrilleTarifaireVersion(models.Model):
    """
    Historique versionné et daté de la grille tarifaire Airbnb (Brief §9.2).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version_label = models.CharField(max_length=50, db_index=True, verbose_name="Libellé version (ex: 2026-06-01)")
    date_entree_vigueur = models.DateField(db_index=True, verbose_name="Date d'entrée en vigueur")
    is_active = models.BooleanField(default=False, db_index=True, verbose_name="Version active")
    notified_veille = models.BooleanField(default=False, verbose_name="Notification veille envoyée")
    tarifs_json = models.JSONField(default=dict, blank=True, verbose_name="Tarifs ménage par typologie")
    intervenantes_json = models.JSONField(default=dict, blank=True, verbose_name="Intervenantes par typologie")
    config_snapshot = models.JSONField(default=dict, blank=True, verbose_name="Snapshot complet de configuration")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='grilles_tarifaires_creees'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Version de Grille Tarifaire"
        verbose_name_plural = "Versions de Grille Tarifaire"
        ordering = ['-date_entree_vigueur', '-created_at']

    def __str__(self):
        return f"Grille {self.version_label} ({'Active' if self.is_active else 'Archivée/Planifiée'})"


class Bien(models.Model):
    """
    Logement Airbnb géré par un client conciergerie ou particulier.
    Identifié par un code trigramme unique non réassignable (ex: GBE001).
    """
    TYPOLOGIE_CHOICES = [
        ('studio', 'Studio'),
        ('1ch', '1 Chambre'),
        ('2ch', '2 Chambres'),
        ('3ch', '3 Chambres'),
        ('4ch', '4 Chambres'),
        ('5ch', '5 Chambres'),
        ('villa_riad', 'Villa / Riad (2 intervenantes)'),
    ]

    ACCES_CHOICES = [
        ('boite_cle', 'Boîte à clés'),
        ('serrure_connectee', 'Serrure connectée'),
        ('gardien', 'Gardien'),
        ('physique', 'Remise physique'),
    ]

    STATUT_ACTIVATION_CHOICES = [
        ('actif', 'Actif'),
        ('en_validation', 'En validation'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=10, unique=True, db_index=True, verbose_name="Code unique (ex: GBE001)")
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='biens_airbnb', verbose_name="Propriétaire / Conciergerie")
    nom_bien = models.CharField(max_length=150, blank=True, verbose_name="Nom usuel du logement")
    ville = models.CharField(max_length=100, default='Casablanca', verbose_name="Ville")
    quartier = models.CharField(max_length=150, verbose_name="Quartier")
    adresse = models.TextField(verbose_name="Adresse complète")
    complement_adresse = models.CharField(max_length=255, blank=True, verbose_name="Complément d'adresse")
    etage_porte = models.CharField(max_length=50, blank=True, verbose_name="Étage / Numéro de porte")
    zone_eloignee = models.BooleanField(default=False, db_index=True, verbose_name="Zone éloignée (+50 DH)")

    # Caractéristiques du logement
    typologie = models.CharField(max_length=50, choices=TYPOLOGIE_CHOICES, default='studio', verbose_name="Typologie")
    services_souscrits = models.JSONField(default=default_services_souscrits, blank=True, verbose_name="Services souscrits")
    chambres = models.PositiveIntegerField(default=1, verbose_name="Nombre de chambres")
    couchages = models.JSONField(default=list, blank=True, verbose_name="Détail des couchages")
    salles_de_bain = models.PositiveIntegerField(default=1, verbose_name="Nombre de salles de bain")
    autres_pieces = models.CharField(max_length=255, blank=True, default='', verbose_name="Autres pièces")

    # Sécurité & Accès
    acces_type = models.CharField(max_length=50, choices=ACCES_CHOICES, default='boite_cle', verbose_name="Type d'accès")
    acces_detail = models.TextField(blank=True, null=True, verbose_name="Digicodes & Consignes sensibles (Sécurisé)")
    gardien_nom = models.CharField(max_length=150, blank=True, default='', verbose_name="Nom du gardien")
    gardien_horaires = models.CharField(max_length=150, blank=True, default='', verbose_name="Horaires du gardien")
    consignes = models.JSONField(default=list, blank=True, verbose_name="Consignes spécifiques du logement")
    photos_attendues = models.JSONField(default=list, blank=True, verbose_name="Photos attendues spécifiques")

    # Chaîne du Linge & Stock Client
    set_composition = models.JSONField(default=dict, blank=True, verbose_name="Composition standard du linge")
    sets_rechange_client = models.PositiveIntegerField(default=3, verbose_name="Stock de roulement de jeux de rechange")

    # Photos & Visuels du Logement
    photo_principale = models.URLField(max_length=500, blank=True, null=True, verbose_name="Photo principale du logement")
    photo_acces = models.URLField(max_length=500, blank=True, null=True, verbose_name="Photo boîte à clés / digicode / accès")

    # Intégration iCal / Channel Manager
    ical_url = models.URLField(blank=True, null=True, max_length=500, verbose_name="URL du flux iCal (Smoobu, Hostaway, Airbnb)")
    ical_derniere_lecture = models.DateTimeField(blank=True, null=True, verbose_name="Dernière synchro iCal")

    # Activation & État
    statut_activation = models.CharField(
        max_length=20,
        choices=STATUT_ACTIVATION_CHOICES,
        default='actif',
        db_index=True,
        verbose_name="Statut d'activation",
    )
    demande_activation_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='biens_demandes_activation',
        verbose_name="Activation demandée par",
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bien Airbnb"
        verbose_name_plural = "Biens Airbnb"
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.nom_bien or self.quartier} ({self.client})"


class CommandeAirbnb(models.Model):
    """
    Commande / Turnover Airbnb (« Colonne vertébrale »).
    Relie Commercial, Runner, Laverie, Intervenante(s) et Facturation.
    """
    STATUT_CHOICES = [
        ('proposition', 'Proposition iCal'),
        ('brouillon', 'Brouillon'),
        ('confirmee', 'Confirmée'),
        ('saisie', 'Saisie'),
        ('remontee_tdb', 'Remontée au TDB (18h J-1)'),
        ('assignee', 'Assignée'),
        ('en_cours', "En cours d'exécution"),
        ('cloturee', 'Clôturée avec photos'),
        ('ecart_linge', 'Écart Linge à arbitrer'),
        ('facturable', 'Facturable'),
        ('facturee', 'Facturée'),
        ('suspendue', 'Suspendue (accès impossible / incident)'),
        ('annulee', 'Annulée'),
    ]

    CRENEAU_CHOICES = [
        ('matin', 'Matin (avant 12h — Cut-off 21h J-1)'),
        ('apres_midi', 'Après-midi (après 12h — Cut-off 22h J-1)'),
    ]

    NATURE_LINGE_CHOICES = [
        ('depot_ramassage', 'Dépôt + Ramassage (Standard)'),
        ('depot_seul', 'Dépôt seul'),
        ('ramassage_seul', 'Ramassage seul'),
        ('sans_linge', 'Sans gestion de linge'),
    ]

    SOURCE_CHOICES = [
        ('manuel', 'Saisie manuelle Backoffice'),
        ('portail_client', 'Portail Conciergerie Client'),
        ('ical_auto', 'Générée par Synchro iCal'),
    ]

    REMISE_EN_ETAT_STATUT_CHOICES = [
        ('aucune', 'Aucune'),
        ('signalee', 'Signalée'),
        ('validee_ops', 'Validée par Opérations'),
        ('envoyee_client', 'Envoyée au client'),
        ('accord_ecrit', 'Accord écrit reçu'),
        ('refusee', 'Refusée'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=30, unique=True, db_index=True, verbose_name="Numéro Commande (ex: CMD-2026-0001)")
    bien = models.ForeignKey(Bien, on_delete=models.PROTECT, related_name='commandes', verbose_name="Logement")
    date_prestation = models.DateField(db_index=True, verbose_name="Date de prestation (check-out / ménage)")
    heure_prestation = models.TimeField(default="11:00", verbose_name="Heure souhaitée")
    creneau = models.CharField(max_length=20, choices=CRENEAU_CHOICES, default='matin', verbose_name="Créneau horaire")
    nature_linge = models.CharField(max_length=50, choices=NATURE_LINGE_CHOICES, default='depot_ramassage', verbose_name="Nature de l'opération linge")
    options = models.JSONField(default=list, blank=True, verbose_name="Options souscrites (packs réassort, café, etc.)")
    consigne_ponctuelle = models.TextField(blank=True, default='', verbose_name="Consigne ponctuelle")

    # Décomposition Financière
    grille_version = models.CharField(max_length=50, blank=True, default='', verbose_name="Version grille tarifaire")
    prix_menage = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Prix ménage de base")
    supplement_zone = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Supplément zone éloignée")
    prix_options = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total options réassort")
    montant_linge = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant facturé du linge ramassé")
    remise_en_etat = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Supplément remise en état / salissure extrême")
    total_ttc = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total TTC Commande")
    prix_force_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='commandes_airbnb_prix_forces',
        verbose_name="Prix forcé par",
    )
    prix_force_motif = models.TextField(blank=True, default='', verbose_name="Motif forçage prix")

    # Statut & Assignations
    statut = models.CharField(max_length=50, choices=STATUT_CHOICES, default='saisie', db_index=True, verbose_name="Statut")
    intervenante = models.ForeignKey(
        'agents.Agent',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='airbnb_missions',
        verbose_name="Intervenante principale"
    )
    intervenante_2 = models.ForeignKey(
        'agents.Agent',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='airbnb_missions_secondary',
        verbose_name="Intervenante secondaire (Obligatoire si Villa/Riad)"
    )
    runner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='airbnb_runner_missions',
        verbose_name="Runner assigné"
    )

    # Suivi exécution & Suspension
    remontee_tdb_le = models.DateTimeField(null=True, blank=True, verbose_name="Remontée au TDB le")
    demarrage_reel_le = models.DateTimeField(null=True, blank=True, verbose_name="Démarrage réel le")
    fin_reelle_le = models.DateTimeField(null=True, blank=True, verbose_name="Fin réelle le")
    annulee_par_suspension = models.BooleanField(default=False, verbose_name="Annulée par suspension client")
    reactivable_apres_suspension = models.BooleanField(default=False, verbose_name="Réactivable après suspension")
    annulee_le = models.DateTimeField(null=True, blank=True, verbose_name="Date d'annulation")
    annulation_motif = models.TextField(blank=True, default='', verbose_name="Motif d'annulation")

    # Remise en état
    remise_en_etat_heures = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Heures remise en état")
    remise_en_etat_statut = models.CharField(
        max_length=30,
        choices=REMISE_EN_ETAT_STATUT_CHOICES,
        default='aucune',
        verbose_name="Statut remise en état",
    )
    remise_en_etat_photos = models.JSONField(default=list, blank=True, verbose_name="Photos remise en état")
    remise_en_etat_accord_preuve = models.TextField(blank=True, default='', verbose_name="Preuve accord écrit client")
    remise_en_etat_accord_le = models.DateTimeField(null=True, blank=True, verbose_name="Date accord écrit")

    # Clôture, iCal & Relances
    photos_cloture = models.JSONField(default=list, blank=True, verbose_name="Photos de clôture (Min 4 obligatoires)")
    rapport_notes = models.TextField(blank=True, verbose_name="Remarques intervenante / incident")
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='manuel', verbose_name="Canal de création")
    ical_event_uid = models.CharField(max_length=255, blank=True, default='', db_index=True, verbose_name="UID événement iCal")
    fiche_mission_pdf_url = models.URLField(max_length=500, blank=True, default='', verbose_name="URL fiche mission PDF")
    fiche_envoyee_le = models.DateTimeField(null=True, blank=True, verbose_name="Fiche envoyée le")
    relance_2h_envoyee = models.BooleanField(default=False, verbose_name="Relance 2h sans démarrage envoyée")
    relance_fin_journee_envoyee = models.BooleanField(default=False, verbose_name="Relance fin de journée envoyée")
    relance_lendemain_envoyee = models.BooleanField(default=False, verbose_name="Relance lendemain envoyée")
    hors_delai_derogation = models.BooleanField(default=False, verbose_name="Hors délai par dérogation")

    # Rapprochement Facturation
    facture = models.ForeignKey(
        'finance.Facture',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='commandes_airbnb',
        verbose_name="Facture associée"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='airbnb_commandes_creees'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Commande Airbnb"
        verbose_name_plural = "Commandes Airbnb"
        ordering = ['-date_prestation', '-heure_prestation']

    def __str__(self):
        return f"{self.numero} — {self.bien.code} ({self.date_prestation})"


class FiletLinge(models.Model):
    """
    Sac / Filet de linge identifié par son code unique.
    Gère le cycle de vie : Ramassage en N-1, Comptage Runner, Comptage Laverie,
    Calcul des sets (8 pcs = 50 DH), Figeage du prix, Dépôt en N.
    """
    STATUT_CHOICES = [
        ('compte_runner', 'Compté par Runner'),
        ('en_laverie', 'En Laverie (Réceptionné)'),
        ('en_traitement', 'En Lavage / Séchage'),
        ('pret', 'Prêt (Emballé)'),
        ('remis_runner', 'Remis au Runner'),
        ('depose', 'Déposé chez le client'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_filet = models.CharField(max_length=50, blank=True, db_index=True, verbose_name="Code Sac Linge (ex: SAC-GBE001-01)")
    bien = models.ForeignKey(Bien, on_delete=models.CASCADE, related_name='filets', verbose_name="Bien rattaché")

    # Décalage N / N-1
    commande_ramassage = models.ForeignKey(
        CommandeAirbnb,
        on_delete=models.CASCADE,
        related_name='filets_ramasses',
        null=True, blank=True,
        verbose_name="Commande de ramassage (N-1 : Porteuse de la facturation)"
    )
    commande_depot = models.ForeignKey(
        CommandeAirbnb,
        on_delete=models.SET_NULL,
        related_name='filets_deposes',
        null=True, blank=True,
        verbose_name="Commande de dépôt du linge propre (N)"
    )

    # Comptages & Contrôles
    comptage_runner = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Comptage pièces Runner (ex: housses:2, draps:2, taies:2, serv:8, total:14)"
    )
    comptage_laverie = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Comptage contradictoire Laverie"
    )
    photo_ramassage = models.URLField(max_length=500, blank=True, default='', verbose_name="Photo ramassage")
    retire_bureau_confirme_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='filets_retires_confirmes',
        verbose_name="Retrait bureau confirmé par",
    )
    retire_bureau_confirme_le = models.DateTimeField(null=True, blank=True, verbose_name="Retrait bureau confirmé le")
    retire_bureau_conteste = models.BooleanField(default=False, verbose_name="Retrait bureau contesté")
    retire_bureau_nb_conteste = models.IntegerField(null=True, blank=True, verbose_name="Nombre contesté au retrait")
    remplissage_pct = models.PositiveIntegerField(default=50, verbose_name="Remplissage du filet (%)")
    necessite_second_filet = models.BooleanField(default=False, verbose_name="Nécessite second filet (>60%)")
    ecart = models.IntegerField(default=0, verbose_name="Écart constaté (Laverie - Runner)")
    ecart_arbitre = models.BooleanField(default=False, verbose_name="Écart vérifié et arbitré")
    ecart_commentaire = models.TextField(blank=True, verbose_name="Commentaire d'arbitrage de l'écart")
    motif_ecart = models.TextField(blank=True, default='', verbose_name="Motif de l'écart")

    # Calculs du moteur de linge
    total_pieces = models.IntegerField(default=0, verbose_name="Total pièces comptabilisées")
    sets_calcules = models.IntegerField(default=0, verbose_name="Nombre de sets standards (8 pcs)")
    pieces_supp_calculees = models.IntegerField(default=0, verbose_name="Pièces supplémentaires hors set")
    montant = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant total calculé (MAD)")

    # Figeage
    montant_fige_le = models.DateTimeField(null=True, blank=True, verbose_name="Date & heure du figeage du montant en laverie")
    fige_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='filets_figes',
        verbose_name="Opérateur ayant figé le décompte"
    )

    statut = models.CharField(max_length=50, choices=STATUT_CHOICES, default='compte_runner', verbose_name="Statut du linge")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Filet / Sac de Linge"
        verbose_name_plural = "Filets / Sacs de Linge"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code_filet or 'Sac'} — {self.bien.code} ({self.montant} DH)"


class ObservationLinge(models.Model):
    """
    Observation / signalement sur une pièce de linge abîmée ou tachée (Brief §5.8).
    RÈGLE NON NÉGOCIABLE : Les pièces signalées ne sont JAMAIS retirées du filet
    et la facturation est à False par défaut (activable pièce par pièce).
    """
    MOTIF_CHOICES = [
        ('taches_persistantes', 'Lavé, taches persistantes'),
        ('non_lavable', "Non lavable en l'état"),
        ('inutilisable', 'Inutilisable'),
        ('dechire', 'Déchiré'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filet = models.ForeignKey(FiletLinge, on_delete=models.CASCADE, related_name='observations', verbose_name="Filet")
    article = models.CharField(max_length=100, verbose_name="Article")
    quantite = models.PositiveIntegerField(default=1, verbose_name="Quantité")
    motif = models.CharField(max_length=30, choices=MOTIF_CHOICES, verbose_name="Motif")
    facturee = models.BooleanField(default=False, verbose_name="Facturée (activable pièce par pièce)")
    montant_facture = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant facturé (MAD)")
    photos = models.JSONField(default=list, blank=True, verbose_name="Photos justificatives")
    note = models.TextField(blank=True, default='', verbose_name="Note")
    message_commercial = models.TextField(blank=True, default='', verbose_name="Message commercial au client")
    notifie_commercial_le = models.DateTimeField(null=True, blank=True, verbose_name="Commercial notifié le")
    notifie_client_le = models.DateTimeField(null=True, blank=True, verbose_name="Client notifié le")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='observations_linge_creees',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Observation Linge"
        verbose_name_plural = "Observations Linge"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.article} x{self.quantite} ({self.get_motif_display()}) — {self.filet}"


class SignalementCommande(models.Model):
    """
    Signalements d'incidents en cours de prestation (Brief §6.4 & §6.5).
    """
    MOTIF_CHOICES = [
        ('bien_sale', 'Bien anormalement sale'),
        ('objet_oublie', 'Objet oublié'),
        ('acces_impossible', 'Accès impossible'),
    ]

    STATUT_CHOICES = [
        ('ouvert', 'Ouvert'),
        ('validee_ops', 'Validé par Opérations'),
        ('transmis_client', 'Transmis au client'),
        ('arbitre', 'Arbitré'),
        ('clos', 'Clos'),
    ]

    ACCORD_CLIENT_CHOICES = [
        ('en_attente', 'En attente'),
        ('accepte', 'Accepté'),
        ('refuse', 'Refusé'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commande = models.ForeignKey(CommandeAirbnb, on_delete=models.CASCADE, related_name='signalements', verbose_name="Commande")
    motif = models.CharField(max_length=30, choices=MOTIF_CHOICES, verbose_name="Motif")
    description = models.TextField(blank=True, default='', verbose_name="Description")
    photos = models.JSONField(default=list, blank=True, verbose_name="Photos")
    heures_estimees = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Heures estimées")
    statut = models.CharField(max_length=30, choices=STATUT_CHOICES, default='ouvert', verbose_name="Statut")
    accord_client = models.CharField(
        max_length=20,
        choices=ACCORD_CLIENT_CHOICES,
        default='en_attente',
        verbose_name="Accord client",
    )
    accord_preuve = models.TextField(blank=True, default='', verbose_name="Preuve accord client")
    signale_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='signalements_airbnb_crees',
    )
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='signalements_airbnb_valides',
    )
    arbitre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='signalements_airbnb_arbitres',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    arbitre_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Signalement Commande Airbnb"
        verbose_name_plural = "Signalements Commandes Airbnb"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_motif_display()} — {self.commande.numero}"


class ObjetTrouve(models.Model):
    """
    Objets oubliés par les voyageurs lors du check-out.
    Traçabilité avec photo, localisation et statut de restitution.
    """
    STATUT_CHOICES = [
        ('trouve', 'Trouvé'),
        ('mis_en_securite', 'Mis en sécurité au bureau'),
        ('signale_client', 'Signalé au client / conciergerie'),
        ('restitue', 'Restitué au voyageur / client'),
        ('conserve_agence', "Conservé à l'agence"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commande = models.ForeignKey(CommandeAirbnb, on_delete=models.CASCADE, related_name='objets_trouves', verbose_name="Commande associée")
    bien = models.ForeignKey(Bien, on_delete=models.CASCADE, related_name='objets_trouves', verbose_name="Logement")
    description = models.TextField(verbose_name="Description de l'objet")
    piece = models.CharField(max_length=150, blank=True, verbose_name="Pièce / Emplacement exact")
    photo_url = models.URLField(max_length=500, blank=True, verbose_name="URL de la photo de l'objet")
    photo_mise_en_securite = models.URLField(max_length=500, blank=True, default='', verbose_name="Photo mise en sécurité")
    statut = models.CharField(max_length=50, choices=STATUT_CHOICES, default='trouve', verbose_name="Statut")
    remis_a = models.CharField(max_length=150, blank=True, verbose_name="Nom de la personne à qui l'objet a été remis")
    date_restitution = models.DateTimeField(null=True, blank=True, verbose_name="Date & heure de restitution")
    notes = models.TextField(blank=True, verbose_name="Remarques complémentaires")
    signale_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='objets_trouves_signales',
    )
    signale_le = models.DateTimeField(null=True, blank=True)
    mis_en_securite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='objets_trouves_securises',
    )
    mis_en_securite_le = models.DateTimeField(null=True, blank=True)
    client_informe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='objets_trouves_notifies',
    )
    client_informe_le = models.DateTimeField(null=True, blank=True)
    instruction_client = models.TextField(blank=True, default='', verbose_name="Instruction du client")
    relance_j1_le = models.DateTimeField(null=True, blank=True)
    relance_j7_le = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Objet Trouvé"
        verbose_name_plural = "Objets Trouvés"
        ordering = ['-created_at']

    def __str__(self):
        return f"Objet: {self.description[:30]} ({self.bien.code})"


class FactureLigneAirbnb(models.Model):
    """
    Ligne détaillée d'une facture Airbnb (prestation, geste commercial, réduction partielle).
    """
    TYPE_LIGNE_CHOICES = [
        ('prestation', 'Prestation'),
        ('geste_commercial', 'Geste commercial'),
        ('reduction_partielle', 'Réduction partielle'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facture = models.ForeignKey('finance.Facture', on_delete=models.CASCADE, related_name='lignes_airbnb', verbose_name="Facture")
    commande = models.ForeignKey(
        CommandeAirbnb,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lignes_facture',
        verbose_name="Commande associée",
    )
    type_ligne = models.CharField(max_length=30, choices=TYPE_LIGNE_CHOICES, default='prestation', verbose_name="Type de ligne")
    designation = models.CharField(max_length=255, verbose_name="Désignation")
    montant = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Montant (MAD)")
    motif = models.TextField(blank=True, default='', verbose_name="Motif")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lignes_facture_airbnb_creees',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ligne de Facture Airbnb"
        verbose_name_plural = "Lignes de Facture Airbnb"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.designation} ({self.montant} DH)"


class JournalAuditAirbnb(models.Model):
    """
    Journal d'audit immuable spécifique au module Airbnb (forçage prix, leviers facturation,
    arbitrages linge, bascules, suspensions).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entite = models.CharField(max_length=100, db_index=True, verbose_name="Entité")
    entite_id = models.CharField(max_length=100, db_index=True, verbose_name="ID Entité")
    action = models.CharField(max_length=150, db_index=True, verbose_name="Action")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='audit_airbnb_actions',
    )
    motif = models.TextField(blank=True, default='', verbose_name="Motif")
    valeur_avant = models.JSONField(null=True, blank=True, verbose_name="Valeur avant")
    valeur_apres = models.JSONField(null=True, blank=True, verbose_name="Valeur après")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Journal d'audit Airbnb"
        verbose_name_plural = "Journaux d'audit Airbnb"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.entite}#{self.entite_id} — {self.action}"
