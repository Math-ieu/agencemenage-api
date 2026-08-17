from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


class AirbnbConfig(models.Model):
    """
    Configuration globale des tarifs, suppléments de zones et règles du module Airbnb.
    Modèle singleton ou paramétrage dynamique.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Tarifs de base ménage par typologie (MAD)
    prix_studio = models.DecimalField(max_digits=10, decimal_places=2, default=130.00, verbose_name="Prix Studio / 1 Chambre")
    prix_2ch = models.DecimalField(max_digits=10, decimal_places=2, default=160.00, verbose_name="Prix 2 Chambres")
    prix_3ch = models.DecimalField(max_digits=10, decimal_places=2, default=200.00, verbose_name="Prix 3 Chambres")
    prix_4ch = models.DecimalField(max_digits=10, decimal_places=2, default=250.00, verbose_name="Prix 4 Chambres")
    prix_5ch = models.DecimalField(max_digits=10, decimal_places=2, default=300.00, verbose_name="Prix 5 Chambres")
    prix_villa_riad = models.DecimalField(max_digits=10, decimal_places=2, default=350.00, verbose_name="Prix Villa / Riad")
    
    # Suppléments & Zones
    supplement_zone_eloignee = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Supplément zone éloignée (MAD)")
    zones_eloignees_list = models.JSONField(
        default=list, 
        blank=True, 
        verbose_name="Liste des zones éloignées (ex: Bouskoura, Dar Bouazza)"
    )
    
    # Tarification Chaîne du Linge
    prix_set_linge_standard = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Prix 1 Set Standard (8 pièces)")
    prix_piece_supp_linge = models.DecimalField(max_digits=10, decimal_places=2, default=5.00, verbose_name="Prix par pièce supplémentaire")
    forfait_min_linge = models.DecimalField(max_digits=10, decimal_places=2, default=50.00, verbose_name="Forfait minimum linge présent")
    
    # Heures Cut-Off
    cutoff_matin = models.TimeField(default="21:00", verbose_name="Heure Cut-off matin (veille)")
    cutoff_apres_midi = models.TimeField(default="22:00", verbose_name="Heure Cut-off après-midi (veille)")
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration Airbnb"
        verbose_name_plural = "Configurations Airbnb"

    def __str__(self):
        return "Configuration Tarifaire & Paramètres Airbnb"


class Bien(models.Model):
    """
    Logement Airbnb géré par un client conciergerie ou particulier.
    Identifié par un code trigramme unique non réassignable (ex: GBE001).
    """
    TYPOLOGIE_CHOICES = [
        ('studio', 'Studio / 1 Chambre'),
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
    chambres = models.PositiveIntegerField(default=1, verbose_name="Nombre de chambres")
    couchages = models.JSONField(default=list, blank=True, verbose_name="Détail des couchages")
    salles_de_bain = models.PositiveIntegerField(default=1, verbose_name="Nombre de salles de bain")
    
    # Sécurité & Accès
    acces_type = models.CharField(max_length=50, choices=ACCES_CHOICES, default='boite_cle', verbose_name="Type d'accès")
    acces_detail = models.TextField(blank=True, null=True, verbose_name="Digicodes & Consignes sensibles (Sécurisé)")
    consignes = models.JSONField(default=list, blank=True, verbose_name="Consignes spécifiques du logement")
    
    # Chaîne du Linge & Stock Client
    set_composition = models.JSONField(default=dict, blank=True, verbose_name="Composition standard du linge")
    sets_rechange_client = models.PositiveIntegerField(default=3, verbose_name="Stock de roulement de jeux de rechange")
    
    # Intégration iCal / Channel Manager
    ical_url = models.URLField(blank=True, null=True, max_length=500, verbose_name="URL du flux iCal (Smoobu, Hostaway, Airbnb)")
    ical_derniere_lecture = models.DateTimeField(blank=True, null=True, verbose_name="Dernière synchro iCal")
    
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
        ('saisie', 'Saisie'),
        ('remontee_tdb', 'Remontée au TDB (18h J-1)'),
        ('assignee', 'Assignée'),
        ('en_cours', 'En cours d\'exécution'),
        ('cloturee', 'Clôturée avec photos'),
        ('ecart_linge', 'Écart Linge à arbitrer'),
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.CharField(max_length=30, unique=True, db_index=True, verbose_name="Numéro Commande (ex: CMD-2026-0001)")
    bien = models.ForeignKey(Bien, on_delete=models.PROTECT, related_name='commandes', verbose_name="Logement")
    date_prestation = models.DateField(db_index=True, verbose_name="Date de prestation (check-out / ménage)")
    heure_prestation = models.TimeField(default="11:00", verbose_name="Heure souhaitée")
    creneau = models.CharField(max_length=20, choices=CRENEAU_CHOICES, default='matin', verbose_name="Créneau horaire")
    nature_linge = models.CharField(max_length=50, choices=NATURE_LINGE_CHOICES, default='depot_ramassage', verbose_name="Nature de l'opération linge")
    options = models.JSONField(default=list, blank=True, verbose_name="Options souscrites (packs réassort, café, etc.)")
    
    # Décomposition Financière
    prix_menage = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Prix ménage de base")
    supplement_zone = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Supplément zone éloignée")
    prix_options = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total options réassort")
    montant_linge = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Montant facturé du linge ramassé")
    remise_en_etat = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Supplément remise en état / salissure extrême")
    total_ttc = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Total TTC Commande")
    
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
    
    # Clôture & Photos
    photos_cloture = models.JSONField(default=list, blank=True, verbose_name="Photos de clôture (Min 4 obligatoires)")
    rapport_notes = models.TextField(blank=True, verbose_name="Remarques intervenante / incident")
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='manuel', verbose_name="Canal de création")
    
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
    
    # Comptages
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
    ecart = models.IntegerField(default=0, verbose_name="Écart constaté (Laverie - Runner)")
    ecart_arbitre = models.BooleanField(default=False, verbose_name="Écart vérifié et arbitré")
    ecart_commentaire = models.TextField(blank=True, verbose_name="Commentaire d'arbitrage de l'écart")
    
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


class ObjetTrouve(models.Model):
    """
    Objets oubliés par les voyageurs lors du check-out.
    Traçabilité avec photo, localisation et statut de restitution.
    """
    STATUT_CHOICES = [
        ('trouve', 'Trouvé'),
        ('signale_client', 'Signalé au client / conciergerie'),
        ('restitue', 'Restitué au voyageur / client'),
        ('conserve_agence', 'Conservé à l\'agence'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commande = models.ForeignKey(CommandeAirbnb, on_delete=models.CASCADE, related_name='objets_trouves', verbose_name="Commande associée")
    bien = models.ForeignKey(Bien, on_delete=models.CASCADE, related_name='objets_trouves', verbose_name="Logement")
    description = models.TextField(verbose_name="Description de l'objet")
    piece = models.CharField(max_length=150, blank=True, verbose_name="Pièce / Emplacement exact")
    photo_url = models.URLField(max_length=500, blank=True, verbose_name="URL de la photo de l'objet")
    statut = models.CharField(max_length=50, choices=STATUT_CHOICES, default='trouve', verbose_name="Statut")
    remis_a = models.CharField(max_length=150, blank=True, verbose_name="Nom de la personne à qui l'objet a été remis")
    date_restitution = models.DateTimeField(null=True, blank=True, verbose_name="Date & heure de restitution")
    notes = models.TextField(blank=True, verbose_name="Remarques complémentaires")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Objet Trouvé"
        verbose_name_plural = "Objets Trouvés"
        ordering = ['-created_at']

    def __str__(self):
        return f"Objet: {self.description[:30]} ({self.bien.code})"
