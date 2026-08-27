from rest_framework import serializers
from .models import AirbnbConfig, Bien, CommandeAirbnb, FiletLinge, ObjetTrouve
from clients.models import Client
from agents.models import Agent
from accounts.models import User
from .services.codification_service import generate_bien_code
from .services.pricing_engine import calculate_commande_pricing, check_cutoff_constraint
from .services.linen_engine import calculate_linen_pieces_and_amount


class AirbnbConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = AirbnbConfig
        fields = '__all__'


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


class BienDetailSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    client_segment = serializers.CharField(source='client.segment', read_only=True)
    client_phone = serializers.CharField(source='client.phone', read_only=True)
    client_whatsapp = serializers.CharField(source='client.whatsapp', read_only=True)
    client_email = serializers.CharField(source='client.email', read_only=True)
    total_biens_client = serializers.SerializerMethodField()
    is_seuil_conciergerie = serializers.SerializerMethodField()

    class Meta:
        model = Bien
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_client_name(self, obj):
        if obj.client:
            if obj.client.segment == 'entreprise' and obj.client.entity_name:
                return obj.client.entity_name
            return f"{obj.client.first_name} {obj.client.last_name}".strip()
        return "Client Inconnu"

    def get_total_biens_client(self, obj):
        if obj.client:
            return obj.client.biens_airbnb.count()
        return 0

    def get_is_seuil_conciergerie(self, obj):
        # Alerte si le client a moins de 3 biens
        return self.get_total_biens_client(obj) >= 3

    def create(self, validated_data):
        # Auto-génération du code si non renseigné
        if not validated_data.get('code'):
            client = validated_data.get('client')
            validated_data['code'] = generate_bien_code(client)
        return super().create(validated_data)


class ObjetTrouveSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    commande_numero = serializers.CharField(source='commande.numero', read_only=True)

    class Meta:
        model = ObjetTrouve
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class FiletLingeSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    client_name = serializers.SerializerMethodField()
    commande_ramassage_numero = serializers.CharField(source='commande_ramassage.numero', read_only=True)
    commande_depot_numero = serializers.CharField(source='commande_depot.numero', read_only=True)
    fige_par_name = serializers.SerializerMethodField()

    class Meta:
        model = FiletLinge
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_client_name(self, obj):
        if obj.bien and obj.bien.client:
            return obj.bien.client.display_name if hasattr(obj.bien.client, 'display_name') else str(obj.bien.client)
        return ""

    def get_fige_par_name(self, obj):
        if obj.fige_par:
            return f"{obj.fige_par.first_name} {obj.fige_par.last_name}".strip() or obj.fige_par.username
        return ""


class CommandeAirbnbListSerializer(serializers.ModelSerializer):
    bien_code = serializers.CharField(source='bien.code', read_only=True)
    bien_nom = serializers.CharField(source='bien.nom_bien', read_only=True)
    bien_quartier = serializers.CharField(source='bien.quartier', read_only=True)
    client_name = serializers.SerializerMethodField()
    intervenante_name = serializers.SerializerMethodField()
    intervenante_2_name = serializers.SerializerMethodField()
    runner_name = serializers.SerializerMethodField()

    class Meta:
        model = CommandeAirbnb
        fields = [
            'id', 'numero', 'bien', 'bien_code', 'bien_nom', 'bien_quartier',
            'client_name', 'date_prestation', 'heure_prestation', 'creneau',
            'nature_linge', 'prix_menage', 'supplement_zone', 'prix_options',
            'montant_linge', 'remise_en_etat', 'total_ttc', 'statut',
            'intervenante', 'intervenante_name', 'intervenante_2', 'intervenante_2_name',
            'runner', 'runner_name', 'photos_cloture', 'created_at'
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
        if obj.runner:
            return f"{obj.runner.first_name} {obj.runner.last_name}".strip() or obj.runner.username
        return ""


class CommandeAirbnbDetailSerializer(serializers.ModelSerializer):
    bien_details = BienDetailSerializer(source='bien', read_only=True)
    objets_trouves = ObjetTrouveSerializer(many=True, read_only=True)
    filets_ramasses = FiletLingeSerializer(many=True, read_only=True)
    filets_deposes = FiletLingeSerializer(many=True, read_only=True)

    class Meta:
        model = CommandeAirbnb
        fields = '__all__'
        read_only_fields = [
            'id', 'numero', 'prix_menage', 'supplement_zone', 'prix_options', 
            'montant_linge', 'total_ttc', 'created_by', 'created_at', 'updated_at'
        ]


class PricingCalculateSerializer(serializers.Serializer):
    bien_id = serializers.UUIDField(required=True)
    typologie = serializers.CharField(required=False, allow_blank=True)
    options = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    remise_en_etat = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0.0)
    date_prestation = serializers.DateField(required=False)
    heure_prestation = serializers.TimeField(required=False)
    creneau = serializers.CharField(required=False, default='matin')


class AssignationSerializer(serializers.Serializer):
    intervenante_id = serializers.IntegerField(required=True)
    intervenante_2_id = serializers.IntegerField(required=False, allow_null=True)
    runner_id = serializers.IntegerField(required=False, allow_null=True)


class ClotureCommandeSerializer(serializers.Serializer):
    photos = serializers.ListField(child=serializers.CharField(), min_length=4, required=True)
    rapport_notes = serializers.CharField(required=False, allow_blank=True)
