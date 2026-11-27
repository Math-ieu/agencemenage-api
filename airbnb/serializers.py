from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers
from agencemenage.validators import validate_uploaded_image
from clients.models import Client
from agents.models import Agent
from accounts.models import User
from finance.models import Facture, Paiement

from .models import (
    AirbnbConfig,
    GrilleTarifaireVersion,
    Bien,
    CommandeAirbnb,
    FiletLinge,
    ObservationLinge,
    SignalementCommande,
    ObjetTrouve,
    FactureLigneAirbnb,
    JournalAuditAirbnb,
)
from .services.codification_service import generate_bien_code
from .services.pricing_engine import (
    calculate_commande_pricing,
    check_cutoff_constraint,
    validate_rabat_rules,
    normalize_commande_options,
)
from .services.linen_engine import calculate_linen_pieces_and_amount
from .services.billing_engine import is_commande_facturable


def _get_request_role(serializer):
    request = serializer.context.get('request') if serializer.context else None
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        return getattr(user, 'role', None)
    return None


def _strip_fields(data, fields):
    for field in fields:
        data.pop(field, None)
    return data


_BIEN_LINGE_SENSITIVE_FIELDS = (
    'adresse', 'complement_adresse', 'etage_porte',
    'acces_detail', 'acces_type', 'gardien_nom', 'gardien_horaires', 'photo_acces',
    'client_phone', 'client_whatsapp', 'client_email', 'ical_url',
)
_BIEN_RUNNER_HIDDEN_FIELDS = (
    'client_phone', 'client_whatsapp', 'client_email', 'ical_url',
)
_COMMANDE_PRICING_FIELDS = (
    'prix_menage', 'supplement_zone', 'prix_options',
    'remise_en_etat', 'remise_en_etat_heures', 'total_ttc', 'facture',
    'prix_force_par', 'prix_force_motif', 'lignes_facture', 'grille_version',
)
_COMMANDE_RUNNER_HIDDEN_FIELDS = _COMMANDE_PRICING_FIELDS + (
    'montant_linge',
    'intervenante', 'intervenante_name',
    'intervenante_2', 'intervenante_2_name',
)
_COMMANDE_CONCIERGERIE_HIDDEN_FIELDS = (
    'intervenante', 'intervenante_name',
    'intervenante_2', 'intervenante_2_name',
    'runner', 'runner_name',
    'prix_force_par', 'prix_force_motif',
)


def _mask_commande_data(data, role):
    if role == 'runner':
        return _strip_fields(data, _COMMANDE_RUNNER_HIDDEN_FIELDS)
    if role == 'responsable_linge':
        return _strip_fields(data, _COMMANDE_PRICING_FIELDS)
    if role == 'client_conciergerie':
        return _strip_fields(data, _COMMANDE_CONCIERGERIE_HIDDEN_FIELDS)
    return data


def _format_user_name(user):
    if not user:
        return ""
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.username or str(user.id)


class AirbnbConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AirbnbConfig
        fields = '__all__'


class GrilleTarifaireVersionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = GrilleTarifaireVersion
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at']

    def get_created_by_name(self, obj):
        return _format_user_name(obj.created_by)


class BienListSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    commandes_actives_count = serializers.SerializerMethodField()
    stock_filets_count = serializers.SerializerMethodField()

    class Meta:
        model = Bien
        fields = [
            'id', 'code', 'nom_bien', 'client', 'client_name', 'client_phone',
            'ville', 'quartier', 'adresse', 'typologie', 'zone_eloignee',
            'chambres', 'salles_de_bain', 'acces_type', 'sets_rechange_client',
            'services_souscrits', 'statut_activation', 'ical_derniere_lecture',
            'photo_principale', 'photo_acces',
            'commandes_actives_count', 'stock_filets_count', 'is_active', 'created_at'
        ]

    def get_client_name(self, obj):
        if obj.client:
            if obj.client.segment == 'entreprise' and obj.client.entity_name:
                return obj.client.entity_name
            return f"{obj.client.first_name} {obj.client.last_name}".strip()
        return "Client Inconnu"

    def get_commandes_actives_count(self, obj):
        return obj.commandes.filter(statut__in=['saisie', 'remontee_tdb', 'assignee', 'en_cours']).count()

    def get_stock_filets_count(self, obj):
        return obj.filets.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        role = _get_request_role(self)
        if role == 'responsable_linge':
            return _strip_fields(data, _BIEN_LINGE_SENSITIVE_FIELDS)
        if role == 'runner':
            return _strip_fields(data, _BIEN_RUNNER_HIDDEN_FIELDS)
        return data


class BienDetailSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    client_name = serializers.SerializerMethodField()
    client_trigramme = serializers.CharField(source='client.trigramme', read_only=True)
    client_segment = serializers.CharField(source='client.segment', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_whatsapp = serializers.CharField(source='client.whatsapp', read_only=True)
    client_email = serializers.CharField(source='client.email', read_only=True)
    total_biens_client = serializers.SerializerMethodField()
    is_seuil_conciergerie = serializers.SerializerMethodField()

    class Meta:
        model = Bien
        fields = '__all__'
        read_only_fields = ['id', 'demande_activation_par', 'created_at', 'updated_at']

    def get_client_name(self, obj):
        if obj.client:
            if obj.client.segment == 'entreprise' and obj.client.entity_name:
                return obj.client.entity_name
            return f"{obj.client.first_name} {obj.client.last_name}".strip()
        return "Client Inconnu"

    def get_total_biens_client(self, obj):
        if obj.client:
            return obj.client.biens_airbnb.filter(is_active=True).count()
        return 0

    def get_is_seuil_conciergerie(self, obj):
        return self.get_total_biens_client(obj) >= 3

    def validate_photo_principale(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_image(value)
        return value

    def validate_photo_acces(self, value):
        if isinstance(value, UploadedFile):
            return validate_uploaded_image(value)
        return value

    def validate(self, attrs):
        role = _get_request_role(self)
        if role == 'client_conciergerie':
            if self.instance:
                for field_name in ('zone_eloignee', 'statut_activation', 'is_active', 'client'):
                    if field_name in attrs:
                        attrs.pop(field_name, None)
            else:
                attrs.pop('zone_eloignee', None)
                attrs['statut_activation'] = 'en_validation'
                attrs['is_active'] = False

        if self.instance and 'code' in attrs:
            incoming_code = (attrs.get('code') or '').strip()
            if incoming_code and incoming_code != self.instance.code:
                raise serializers.ValidationError({'code': "Le code unique du bien est immuable et ne peut pas être modifié."})
            attrs.pop('code', None)

        ville = attrs.get('ville', getattr(self.instance, 'ville', 'Casablanca'))
        services = attrs.get('services_souscrits', getattr(self.instance, 'services_souscrits', ['menage']))

        if ville and ville.strip().lower() == 'rabat':
            if isinstance(services, list) and any(str(s).strip().lower() in ('linge', 'ramassage') for s in services):
                raise serializers.ValidationError({
                    'services_souscrits': (
                        "Règle Rabat : le module linge et le ramassage ne sont pas "
                        "disponibles à Rabat (ménage uniquement)."
                    )
                })
            if not self.instance and 'services_souscrits' not in attrs:
                attrs['services_souscrits'] = ['menage']

        # Détection automatique de la zone éloignée (ex: Bouskoura, Dar Bouazza)
        quartier = attrs.get('quartier', getattr(self.instance, 'quartier', ''))
        current_zone = attrs.get('zone_eloignee', getattr(self.instance, 'zone_eloignee', False))
        if quartier and not current_zone:
            from .services.pricing_engine import get_airbnb_config, _norm_text
            q_norm = _norm_text(quartier)
            zones = [_norm_text(z) for z in (get_airbnb_config().zones_eloignees_list or []) if z]
            if q_norm and any(z in q_norm for z in zones):
                attrs['zone_eloignee'] = True

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        role = _get_request_role(self)
        if role == 'responsable_linge':
            return _strip_fields(data, _BIEN_LINGE_SENSITIVE_FIELDS)
        if role == 'runner':
            return _strip_fields(data, _BIEN_RUNNER_HIDDEN_FIELDS)
        return data

    def create(self, validated_data):
        request = self.context.get('request') if self.context else None
        user = getattr(request, 'user', None)
        role = getattr(user, 'role', None) if user and user.is_authenticated else None

        if not validated_data.get('code'):
            client = validated_data.get('client')
            validated_data['code'] = generate_bien_code(client, validated_data.get('ville'))

        if role == 'client_conciergerie':
            validated_data['statut_activation'] = 'en_validation'
            validated_data['is_active'] = False
            validated_data['demande_activation_par'] = user

        return super().create(validated_data)


class ObservationLingeSerializer(serializers.ModelSerializer):
    filet_code = serializers.CharField(source='filet.code_filet', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ObservationLinge
        fields = '__all__'
        read_only_fields = [
            'id', 'facturee', 'montant_facture', 'created_by', 'created_at',
            'notifie_commercial_le', 'notifie_client_le',
        ]

    def get_created_by_name(self, obj):
        return _format_user_name(obj.created_by)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        role = _get_request_role(self)
        if role == 'runner':
            _strip_fields(data, ('facturee', 'montant_facture'))
        elif role == 'responsable_linge':
            _strip_fields(data, ('montant_facture',))
        return data


class FiletLingeSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    client_name = serializers.SerializerMethodField()
    commande_ramassage_numero = serializers.CharField(source='commande_ramassage.numero', read_only=True)
    commande_depot_numero = serializers.CharField(source='commande_depot.numero', read_only=True)
    fige_par_name = serializers.SerializerMethodField()
    est_fige = serializers.SerializerMethodField()
    details_articles = serializers.SerializerMethodField()
    observations = ObservationLingeSerializer(many=True, read_only=True)

    class Meta:
        model = FiletLinge
        fields = '__all__'
        read_only_fields = [
            'id', 'montant', 'total_pieces', 'sets_calcules', 'pieces_supp_calculees',
            'ecart', 'ecart_arbitre', 'ecart_commentaire', 'motif_ecart',
            'comptage_runner', 'comptage_laverie', 'statut',
            'retire_bureau_confirme_par', 'retire_bureau_confirme_le',
            'retire_bureau_conteste', 'retire_bureau_nb_conteste',
            'montant_fige_le', 'fige_par', 'created_at', 'updated_at',
        ]

    def get_client_name(self, obj):
        if obj.bien and obj.bien.client:
            return obj.bien.client.display_name if hasattr(obj.bien.client, 'display_name') else str(obj.bien.client)
        return ""

    def get_fige_par_name(self, obj):
        return _format_user_name(obj.fige_par)

    def get_est_fige(self, obj):
        return bool(obj.montant_fige_le)

    def get_details_articles(self, obj):
        comptage = obj.comptage_laverie or obj.comptage_runner or {}
        if not comptage:
            return None
        res = calculate_linen_pieces_and_amount(comptage)
        role = _get_request_role(self)
        if role in ('runner', 'responsable_linge'):
            for k in (
                'montant', 'montant_sets', 'montant_pieces_hors_set',
                'montant_brut', 'montant_total', 'minimum_applique', 'forfait_minimum_applique',
            ):
                res.pop(k, None)
        return res

    def to_representation(self, instance):
        data = super().to_representation(instance)
        role = _get_request_role(self)
        if role in ('runner', 'responsable_linge'):
            data.pop('montant', None)
        return data


class SignalementCommandeSerializer(serializers.ModelSerializer):
    commande_numero = serializers.CharField(source='commande.numero', read_only=True)
    bien_code = serializers.CharField(source='commande.bien.code', read_only=True)
    signale_par_name = serializers.SerializerMethodField()
    valide_par_name = serializers.SerializerMethodField()
    arbitre_par_name = serializers.SerializerMethodField()

    class Meta:
        model = SignalementCommande
        fields = '__all__'
        read_only_fields = ['id', 'signale_par', 'valide_par', 'arbitre_par', 'created_at', 'arbitre_le']

    def get_signale_par_name(self, obj):
        return _format_user_name(obj.signale_par)

    def get_valide_par_name(self, obj):
        return _format_user_name(obj.valide_par)

    def get_arbitre_par_name(self, obj):
        return _format_user_name(obj.arbitre_par)


class ObjetTrouveSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    commande_numero = serializers.CharField(source='commande.numero', read_only=True)
    client_name = serializers.SerializerMethodField()
    signale_par_name = serializers.SerializerMethodField()
    mis_en_securite_par_name = serializers.SerializerMethodField()
    client_informe_par_name = serializers.SerializerMethodField()

    class Meta:
        model = ObjetTrouve
        fields = '__all__'
        read_only_fields = [
            'id', 'signale_par', 'signale_le',
            'mis_en_securite_par', 'mis_en_securite_le',
            'client_informe_par', 'client_informe_le',
            'relance_j1_le', 'relance_j7_le',
            'created_at', 'updated_at',
        ]

    def get_client_name(self, obj):
        if obj.bien and obj.bien.client:
            return obj.bien.client.display_name
        return ""

    def get_signale_par_name(self, obj):
        return _format_user_name(obj.signale_par)

    def get_mis_en_securite_par_name(self, obj):
        return _format_user_name(obj.mis_en_securite_par)

    def get_client_informe_par_name(self, obj):
        return _format_user_name(obj.client_informe_par)


class FactureLigneAirbnbSerializer(serializers.ModelSerializer):
    commande_numero = serializers.CharField(source='commande.numero', read_only=True)
    bien_code = serializers.CharField(source='commande.bien.code', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FactureLigneAirbnb
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at']

    def get_created_by_name(self, obj):
        return _format_user_name(obj.created_by)


class FactureAirbnbSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_trigramme = serializers.CharField(source='client.trigramme', read_only=True)
    client_mode_paiement = serializers.CharField(source='client.mode_paiement_airbnb', read_only=True)
    client_statut_airbnb = serializers.CharField(source='client.statut_airbnb', read_only=True)
    reste_a_payer = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    lignes_airbnb = FactureLigneAirbnbSerializer(many=True, read_only=True)
    paiements = serializers.SerializerMethodField()
    commandes_numeros = serializers.SerializerMethodField()

    class Meta:
        model = Facture
        fields = [
            'id', 'numero', 'client', 'client_name', 'client_trigramme',
            'client_mode_paiement', 'client_statut_airbnb',
            'source', 'mode_facturation', 'periode_debut', 'periode_fin', 'est_prorata',
            'montant_total', 'montant_paye', 'reste_a_payer', 'statut',
            'date_emission', 'date_echeance', 'pdf_file', 'notes',
            'motif_annulation', 'annulee_le',
            'virement_declare_le', 'virement_reference', 'virement_justificatif_url', 'virement_montant_declare',
            'lignes_airbnb', 'paiements', 'commandes_numeros', 'created_at',
        ]

    def get_client_name(self, obj):
        return obj.client.display_name if obj.client else ""

    def get_paiements(self, obj):
        return [
            {
                'id': p.id,
                'montant': str(p.montant),
                'mode': p.mode,
                'date': str(p.date),
                'reference': p.reference,
                'notes': p.notes,
            }
            for p in obj.paiements.all()
        ]

    def get_commandes_numeros(self, obj):
        return list(obj.commandes_airbnb.values_list('numero', flat=True))


class JournalAuditAirbnbSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_role = serializers.CharField(source='user.role', read_only=True)

    class Meta:
        model = JournalAuditAirbnb
        fields = '__all__'

    def get_user_name(self, obj):
        return _format_user_name(obj.user)


class CommandeAirbnbListSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    bien_nom = serializers.CharField(source='bien.nom_bien', read_only=True)
    bien_ville = serializers.CharField(source='bien.ville', read_only=True)
    bien_quartier = serializers.CharField(source='bien.quartier', read_only=True)
    client_name = serializers.SerializerMethodField()
    intervenante_name = serializers.SerializerMethodField()
    intervenante_2_name = serializers.SerializerMethodField()
    runner_name = serializers.SerializerMethodField()
    est_facturable = serializers.SerializerMethodField()

    class Meta:
        model = CommandeAirbnb
        fields = [
            'id', 'numero', 'bien', 'bien_code', 'bien_nom', 'bien_ville', 'bien_quartier',
            'client_name', 'date_prestation', 'heure_prestation', 'creneau',
            'nature_linge', 'grille_version', 'prix_menage', 'supplement_zone', 'prix_options',
            'montant_linge', 'remise_en_etat', 'remise_en_etat_statut', 'total_ttc', 'statut',
            'intervenante', 'intervenante_name', 'intervenante_2', 'intervenante_2_name',
            'runner', 'runner_name', 'photos_cloture', 'hors_delai_derogation',
            'facture', 'est_facturable', 'created_at'
        ]

    def get_client_name(self, obj):
        if obj.bien and obj.bien.client:
            c = obj.bien.client
            if c.segment == 'entreprise' and c.entity_name:
                return c.entity_name
            return f"{c.first_name} {c.last_name}".strip()
        return ""

    def get_intervenante_name(self, obj):
        if obj.intervenante:
            return f"{obj.intervenante.first_name} {obj.intervenante.last_name}"
        return ""

    def get_intervenante_2_name(self, obj):
        if obj.intervenante_2:
            return f"{obj.intervenante_2.first_name} {obj.intervenante_2.last_name}"
        return ""

    def get_runner_name(self, obj):
        return _format_user_name(obj.runner)

    def get_est_facturable(self, obj):
        ok, _ = is_commande_facturable(obj)
        return ok

    def to_representation(self, instance):
        return _mask_commande_data(super().to_representation(instance), _get_request_role(self))


class CommandeAirbnbDetailSerializer(serializers.ModelSerializer):
    bien_details = BienDetailSerializer(source='bien', read_only=True)
    objets_trouves = ObjetTrouveSerializer(many=True, read_only=True)
    filets_ramasses = FiletLingeSerializer(many=True, read_only=True)
    filets_deposes = FiletLingeSerializer(many=True, read_only=True)
    signalements = SignalementCommandeSerializer(many=True, read_only=True)
    lignes_facture = FactureLigneAirbnbSerializer(many=True, read_only=True)
    est_facturable_details = serializers.SerializerMethodField()

    class Meta:
        model = CommandeAirbnb
        fields = '__all__'
        read_only_fields = [
            'id', 'numero', 'grille_version', 'prix_menage', 'supplement_zone', 'prix_options',
            'montant_linge', 'total_ttc', 'prix_force_par', 'prix_force_motif',
            'intervenante', 'intervenante_2', 'runner',
            'remise_en_etat', 'remise_en_etat_heures', 'remise_en_etat_statut',
            'remise_en_etat_photos', 'remise_en_etat_accord_preuve', 'remise_en_etat_accord_le',
            'facture', 'fiche_mission_pdf_url', 'fiche_envoyee_le',
            'annulee_par_suspension', 'reactivable_apres_suspension', 'annulee_le',
            'relance_2h_envoyee', 'relance_fin_journee_envoyee', 'relance_lendemain_envoyee',
            'hors_delai_derogation', 'remontee_tdb_le', 'demarrage_reel_le', 'fin_reelle_le',
            'created_by', 'created_at', 'updated_at',
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None and 'statut' in fields:
            fields['statut'].read_only = True
        return fields

    def get_est_facturable_details(self, obj):
        ok, reasons = is_commande_facturable(obj)
        return {'facturable': ok, 'blockers': reasons}

    def validate(self, attrs):
        bien = attrs.get('bien') or getattr(self.instance, 'bien', None)
        initial_data = getattr(self, 'initial_data', None) or {}
        if bien and not self.instance and (bien.ville or '').strip().lower() == 'rabat':
            if 'nature_linge' not in initial_data and not attrs.get('nature_linge'):
                attrs['nature_linge'] = 'sans_linge'
            elif 'nature_linge' not in initial_data and attrs.get('nature_linge') == 'depot_ramassage':
                attrs['nature_linge'] = 'sans_linge'
        nature_linge = attrs.get('nature_linge', getattr(self.instance, 'nature_linge', 'depot_ramassage'))
        options = attrs.get('options', getattr(self.instance, 'options', []))

        # Respecter Rabat : ménage uniquement
        if bien:
            try:
                validate_rabat_rules(
                    bien=bien,
                    nature_linge=nature_linge,
                    ramassage_specifique=(nature_linge == 'ramassage_seul'),
                )
            except Exception as exc:
                raise serializers.ValidationError({'nature_linge': str(exc)})

        # Exclusivité Réassort Essentiel vs Confort + rejet options négatives / libres non autorisées
        if 'options' in attrs:
            role = _get_request_role(self)
            try:
                normalized_opts, _ = normalize_commande_options(
                    options=options,
                    allow_custom_options=(role in ('admin', 'responsable_commercial')),
                )
                attrs['options'] = normalized_opts
            except Exception as exc:
                raise serializers.ValidationError({'options': str(exc)})

        return attrs

    def to_representation(self, instance):
        return _mask_commande_data(super().to_representation(instance), _get_request_role(self))


class PricingCalculateSerializer(serializers.Serializer):
    bien_id = serializers.UUIDField(required=True)
    typologie = serializers.CharField(required=False, allow_blank=True)
    options = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    remise_en_etat = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0.0)
    date_prestation = serializers.DateField(required=False)
    heure_prestation = serializers.TimeField(required=False)
    creneau = serializers.CharField(required=False, default='matin')
    reassort = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    video = serializers.BooleanField(required=False, default=False)
    materiel = serializers.BooleanField(required=False, default=False)
    ramassage_specifique = serializers.BooleanField(required=False, default=False)
    menage_inclus = serializers.BooleanField(required=False, default=True)


class AssignationSerializer(serializers.Serializer):
    intervenante_id = serializers.IntegerField(required=True)
    intervenante_2_id = serializers.IntegerField(required=False, allow_null=True)
    runner_id = serializers.IntegerField(required=False, allow_null=True)


class ClotureCommandeSerializer(serializers.Serializer):
    photos = serializers.ListField(child=serializers.CharField(), min_length=4, required=True)
    rapport_notes = serializers.CharField(required=False, allow_blank=True)


class ForcerPrixSerializer(serializers.Serializer):
    prix_menage = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    supplement_zone = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    motif = serializers.CharField(required=True, min_length=3)
