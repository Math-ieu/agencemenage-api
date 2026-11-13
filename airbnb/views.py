import os
import re
import uuid
import mimetypes
from decimal import Decimal
from datetime import datetime, date, time, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.conf import settings
from django.db.models import Count, Sum, Q
from django.http import HttpResponse
from django.utils import timezone

from rest_framework import viewsets, status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import RoleBasedPermission
from agents.models import Agent
from clients.models import Client
from demandes.models import Demande
from finance.models import Facture
from missions.models import Mission

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
from .serializers import (
    AirbnbConfigSerializer,
    GrilleTarifaireVersionSerializer,
    BienListSerializer,
    BienDetailSerializer,
    CommandeAirbnbListSerializer,
    CommandeAirbnbDetailSerializer,
    FiletLingeSerializer,
    ObservationLingeSerializer,
    SignalementCommandeSerializer,
    ObjetTrouveSerializer,
    FactureAirbnbSerializer,
    FactureLigneAirbnbSerializer,
    JournalAuditAirbnbSerializer,
    PricingCalculateSerializer,
    AssignationSerializer,
    ClotureCommandeSerializer,
    ForcerPrixSerializer,
)
from .services.codification_service import preview_bien_code, generate_bien_code, compute_client_trigramme
from .services.pricing_engine import (
    get_airbnb_config,
    ensure_initial_grille_version,
    get_active_grille_version,
    create_grille_tarifaire_version,
    verifier_seuil_client,
    validate_rabat_rules,
    normalize_commande_options,
    calculate_commande_pricing,
    check_cutoff_constraint,
    forcer_prix_commande,
)
from .services.linen_engine import (
    normalize_comptage,
    calculate_linen_pieces_and_amount,
    confirmer_retrait_bureau,
    contester_retrait_bureau,
    compter_runner,
    recevoir_laverie,
    freeze_laundry_filet,
    arbitrer_ecart_filet,
    toggle_observation_facturation,
    transmettre_observation_client,
)
from .services.billing_engine import (
    is_commande_facturable,
    update_commande_facturable_status,
    preview_calendrier_facturation,
    generer_facture_passage,
    generer_factures_cycle,
    enregistrer_paiement,
    declarer_virement,
    annuler_facture,
    appliquer_geste_commercial,
    appliquer_reduction_partielle,
    annuler_bascule_mensuelle,
)
from .services.ical_service import sync_bien_ical_turnovers, confirmer_proposition, rejeter_proposition
from .services.pdf_service import generate_fiche_mission_pdf, generate_facture_airbnb_pdf
from .services.whatsapp_service import generate_mission_pdf_data
from .services.notification_service import (
    notify_commande_confirmee,
    notify_commande_annulee,
    notify_affectation_mission,
    notify_cloture_commande,
    notify_remise_en_etat_client,
    notify_signalement_operations,
    notify_signalement_client,
    notify_observation_linge_commercial,
    notify_objet_trouve,
    notify_objet_trouve_client,
    notify_reactivation_client,
)


def _assert_client_access(user, client):
    role = getattr(user, 'role', None)
    if role == 'client_conciergerie':
        if not user.client_id or not client or client.id != user.client_id:
            raise PermissionDenied("Accès refusé pour ce client.")
    elif role == 'commercial':
        if not client or client.assigned_commercial_id != user.id:
            raise PermissionDenied("Accès refusé : client non assigné à ce commercial.")


def _extract_error_message(exc):
    if hasattr(exc, 'messages') and exc.messages:
        return " ".join(str(m) for m in exc.messages)
    if hasattr(exc, 'message'):
        return str(exc.message)
    return str(exc)


def _parse_time_str(value, default_time=time(10, 0)):
    if isinstance(value, time):
        return value
    if not value:
        return default_time
    s = str(value).strip().lower().replace('h', ':')
    match = re.search(r'(\d{1,2})(?::(\d{2}))?', s)
    if not match:
        return default_time
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2) or 0)))
    return time(hour, minute)


def _times_overlap(target_date, time_a, time_b, duration_hours=4):
    dt_a_start = datetime.combine(target_date, time_a)
    dt_a_end = dt_a_start + timedelta(hours=duration_hours)
    dt_b_start = datetime.combine(target_date, time_b)
    dt_b_end = dt_b_start + timedelta(hours=duration_hours)
    return dt_a_start < dt_b_end and dt_b_start < dt_a_end


_FR_WEEKDAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
_EN_WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
_FR_WEEKDAYS_SHORT = ('lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim')


def _resolve_planning_occurrence(dem, target_date, fallback_time):
    """
    Détermine si une Demande (ponctuelle, enfant ou abonnement avec SubscriptionPlanning)
    a réellement une occurrence active à `target_date`, et retourne `(is_active, start_time)`.
    """
    planning = getattr(dem, 'planning', None)
    base_time = fallback_time
    if planning and planning.heure_debut:
        base_time = planning.heure_debut
    elif dem.heure_intervention:
        base_time = _parse_time_str(dem.heure_intervention, default_time=fallback_time)
    elif isinstance(dem.formulaire_data, dict) and dem.formulaire_data.get('heure'):
        base_time = _parse_time_str(dem.formulaire_data.get('heure'), default_time=fallback_time)

    # Demande ponctuelle / enfant sans planning actif
    if not planning:
        return (dem.date_intervention == target_date), base_time

    # Si cette demande possède une date explicite différente et qu'il s'agit d'une enfant
    if dem.parent_demande_id and dem.date_intervention != target_date:
        return False, None

    if planning.statut in ('annule', 'termine', 'resilie'):
        return False, None
    if planning.date_debut and target_date < planning.date_debut:
        return False, None
    if planning.date_fin and target_date > planning.date_fin:
        return False, None

    target_iso = target_date.isoformat()
    target_wd = target_date.weekday()
    wd_fr = _FR_WEEKDAYS[target_wd]
    wd_en = _EN_WEEKDAYS[target_wd]
    wd_short = _FR_WEEKDAYS_SHORT[target_wd]

    if isinstance(dem.formulaire_data, dict):
        overrides = dem.formulaire_data.get('date_overrides') or {}
        if isinstance(overrides, dict):
            ov = overrides.get(target_iso)
            if isinstance(ov, dict):
                if ov.get('statut') in ('annule', 'annulee', Demande.ANNULE, Demande.RESILIE):
                    return False, None
                if ov.get('heure_debut'):
                    base_time = _parse_time_str(ov.get('heure_debut'), default_time=base_time)

    # Vérifier le détail hebdomadaire `planning.semaines` s'il couvre la semaine cible
    if isinstance(planning.semaines, list) and planning.semaines:
        matched_week = False
        matched_day = None
        for week in planning.semaines:
            if not isinstance(week, dict):
                continue
            w_start = w_end = None
            try:
                if week.get('date_debut'):
                    w_start = date.fromisoformat(str(week['date_debut'])[:10])
                if week.get('date_fin'):
                    w_end = date.fromisoformat(str(week['date_fin'])[:10])
            except ValueError:
                w_start = w_end = None

            if w_start and target_date < w_start:
                continue
            if w_end and target_date > w_end:
                continue

            jours_map = week.get('jours') or {}
            day_entry = None
            if isinstance(jours_map, dict):
                if target_iso in jours_map:
                    day_entry = jours_map[target_iso]
                else:
                    for key, val in jours_map.items():
                        k_norm = str(key).strip().lower()
                        if k_norm in (wd_fr, wd_en, wd_short, str(target_wd)) or (
                            isinstance(val, dict) and str(val.get('date', ''))[:10] == target_iso
                        ):
                            day_entry = val
                            break

            if w_start is not None or w_end is not None or day_entry is not None:
                matched_week = True
                matched_day = day_entry
                if day_entry is not None:
                    break

        if matched_week:
            if matched_day is None:
                return False, None
            if isinstance(matched_day, bool):
                return (matched_day, base_time if matched_day else None)
            if isinstance(matched_day, dict):
                if matched_day.get('selected') is False or matched_day.get('statut') in (
                    'annule', 'annulee', Demande.ANNULE, Demande.RESILIE
                ):
                    return False, None
                occ_time = (
                    _parse_time_str(matched_day.get('heure_debut'), default_time=base_time)
                    if matched_day.get('heure_debut')
                    else base_time
                )
                return True, occ_time

    # Sinon repli sur `planning.jours_intervention`
    if isinstance(planning.jours_intervention, list) and planning.jours_intervention:
        allowed_tokens = {wd_fr, wd_en, wd_short, str(target_wd)}
        day_matched = False
        for item in planning.jours_intervention:
            if isinstance(item, int) and item == target_wd:
                day_matched = True
                break
            if isinstance(item, str) and item.strip().lower() in allowed_tokens:
                day_matched = True
                break
        if not day_matched:
            return False, None

    return True, base_time


def _find_agent_conflicts(agent_ids, target_date, target_time, exclude_commande_id=None):
    """
    Vérifie les conflits horaires d'une intervenante le même jour sur :
    1) Les autres Commandes Airbnb actives
    2) Les Demandes classiques / Abonnements (`profils_envoyes` + `Mission`)
    """
    clean_ids = [aid for aid in agent_ids if aid]
    if not clean_ids or not target_date:
        return []

    target_t = _parse_time_str(target_time)
    conflicts = []

    # 1. Commandes Airbnb actives ce jour-là
    cmd_qs = CommandeAirbnb.objects.filter(
        date_prestation=target_date,
        statut__in=['saisie', 'confirmee', 'remontee_tdb', 'assignee', 'en_cours'],
    ).filter(
        Q(intervenante_id__in=clean_ids) | Q(intervenante_2_id__in=clean_ids)
    ).select_related('bien')
    if exclude_commande_id:
        cmd_qs = cmd_qs.exclude(id=exclude_commande_id)

    for cmd in cmd_qs:
        cmd_time = _parse_time_str(cmd.heure_prestation)
        if _times_overlap(target_date, target_t, cmd_time):
            conflicts.append({
                'source': 'airbnb',
                'id': str(cmd.id),
                'reference': cmd.numero,
                'bien_code': cmd.bien.code if cmd.bien else '',
                'heure': cmd_time.strftime('%H:%M'),
                'agent_ids': [i for i in (cmd.intervenante_id, cmd.intervenante_2_id) if i in clean_ids],
            })

    # 2. Demandes classiques / Abonnements
    demande_qs = Demande.objects.exclude(
        statut__in=[Demande.ANNULE, Demande.RESILIE]
    ).filter(
        profils_envoyes__id__in=clean_ids
    ).filter(
        Q(date_intervention=target_date) |
        Q(planning__date_debut__lte=target_date, planning__date_fin__isnull=True) |
        Q(planning__date_debut__lte=target_date, planning__date_fin__gte=target_date)
    ).distinct().select_related('planning').prefetch_related('profils_envoyes')

    for dem in demande_qs:
        occurs_today, dem_time = _resolve_planning_occurrence(dem, target_date, target_t)
        if not occurs_today:
            continue

        if _times_overlap(target_date, target_t, dem_time):
            matched_agents = list(
                dem.profils_envoyes.filter(id__in=clean_ids).values_list('id', flat=True)
            )
            conflicts.append({
                'source': 'demande',
                'id': str(dem.id),
                'reference': f"Demande #{dem.id} ({dem.service})",
                'heure': dem_time.strftime('%H:%M'),
                'agent_ids': matched_agents,
            })

    # 3. Missions classiques directement liées à un agent
    mission_qs = Mission.objects.exclude(statut=Mission.ANNULEE).filter(
        Q(agent_id__in=clean_ids) | Q(intervenants__id__in=clean_ids)
    ).filter(
        Q(date_debut__date=target_date) | Q(demande__date_intervention=target_date)
    ).distinct().select_related('demande')

    seen_demandes = {c['id'] for c in conflicts if c['source'] == 'demande'}
    for m in mission_qs:
        if m.demande_id and str(m.demande_id) in seen_demandes:
            continue
        m_time = m.date_debut.time() if m.date_debut else _parse_time_str(
            m.demande.heure_intervention if m.demande else None, target_t
        )
        if _times_overlap(target_date, target_t, m_time):
            m_agents = []
            if m.agent_id in clean_ids:
                m_agents.append(m.agent_id)
            m_agents.extend(list(m.intervenants.filter(id__in=clean_ids).values_list('id', flat=True)))
            conflicts.append({
                'source': 'mission',
                'id': str(m.id),
                'reference': f"Mission #{m.id}",
                'heure': m_time.strftime('%H:%M'),
                'agent_ids': list(set(m_agents)),
            })

    return conflicts


class AirbnbConfigViewSet(viewsets.ModelViewSet):
    queryset = AirbnbConfig.objects.all()
    serializer_class = AirbnbConfigSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def list(self, request, *args, **kwargs):
        config = get_airbnb_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def current(self, request):
        config = get_airbnb_config()
        serializer = self.get_serializer(config)
        return Response(serializer.data)


class GrilleTarifaireVersionViewSet(viewsets.ModelViewSet):
    queryset = GrilleTarifaireVersion.objects.all()
    serializer_class = GrilleTarifaireVersionSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def update(self, request, *args, **kwargs):
        return Response(
            {'error': "Les versions de grille tarifaire sont immuables. Créez une nouvelle version."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'error': "La suppression d'une version de grille tarifaire est interdite."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=['get'])
    def active(self, request):
        grille = get_active_grille_version() or ensure_initial_grille_version()
        return Response(self.get_serializer(grille).data)

    @action(detail=False, methods=['get'])
    def current(self, request):
        return self.active(request)

    def create(self, request, *args, **kwargs):
        data = request.data
        date_str = data.get('date_entree_vigueur')
        if date_str:
            try:
                eff_date = datetime.strptime(str(date_str), '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': "Format date_entree_vigueur invalide (YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            eff_date = timezone.localdate()

        grille = create_grille_tarifaire_version(
            version_label=data.get('version_label') or eff_date.isoformat(),
            date_entree_vigueur=eff_date,
            tarifs_json=data.get('tarifs_json'),
            intervenantes_json=data.get('intervenantes_json'),
            config_snapshot=data.get('config_snapshot'),
            user=request.user,
        )
        return Response(self.get_serializer(grille).data, status=status.HTTP_201_CREATED)


class BienViewSet(viewsets.ModelViewSet):
    queryset = Bien.objects.select_related('client').prefetch_related('commandes', 'filets').all()
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_serializer_class(self):
        if self.action in ['list']:
            return BienListSerializer
        return BienDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)

        if role == 'responsable_linge':
            return qs.none()
        if role == 'client_conciergerie':
            qs = qs.filter(client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(client__assigned_commercial=user)
        elif role == 'runner':
            qs = qs.filter(
                commandes__runner=user,
                commandes__date_prestation=timezone.localdate(),
            ).distinct()

        client_id = self.request.query_params.get('client')
        ville = self.request.query_params.get('ville')
        typologie = self.request.query_params.get('typologie')
        zone_eloignee = self.request.query_params.get('zone_eloignee')
        is_active = self.request.query_params.get('is_active')
        statut_activation = self.request.query_params.get('statut_activation')
        search = self.request.query_params.get('search')

        if client_id:
            qs = qs.filter(client_id=client_id)
        if ville:
            qs = qs.filter(ville__iexact=ville)
        if typologie:
            qs = qs.filter(typologie=typologie)
        if zone_eloignee in ['true', '1']:
            qs = qs.filter(zone_eloignee=True)
        if is_active in ['true', '1']:
            qs = qs.filter(is_active=True)
        elif is_active in ['false', '0']:
            qs = qs.filter(is_active=False)
        if statut_activation:
            qs = qs.filter(statut_activation=statut_activation)
        if search:
            qs = qs.filter(
                Q(code__icontains=search) |
                Q(nom_bien__icontains=search) |
                Q(quartier__icontains=search) |
                Q(ville__icontains=search) |
                Q(client__first_name__icontains=search) |
                Q(client__last_name__icontains=search) |
                Q(client__entity_name__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        client = serializer.validated_data.get('client')
        _assert_client_access(self.request.user, client)
        if client and not client.trigramme:
            compute_client_trigramme(client, persist=True)
        bien = serializer.save()
        if bien.is_active and bien.client:
            verifier_seuil_client(bien.client, user=self.request.user)

    def perform_update(self, serializer):
        bien = self.get_object()
        client = serializer.validated_data.get('client', bien.client)
        _assert_client_access(self.request.user, client)
        role = getattr(self.request.user, 'role', None)
        if role == 'client_conciergerie':
            # Le portail client ne peut pas auto-valider son bien
            serializer.validated_data.pop('statut_activation', None)
            serializer.validated_data.pop('is_active', None)
        updated = serializer.save()
        if updated.client:
            verifier_seuil_client(updated.client, user=self.request.user)

    def perform_destroy(self, instance):
        client = instance.client
        super().perform_destroy(instance)
        if client:
            verifier_seuil_client(client, user=self.request.user)

    @action(detail=True, methods=['post'])
    def activer(self, request, pk=None):
        bien = self.get_object()
        bien.statut_activation = 'actif'
        bien.is_active = True
        bien.save(update_fields=['statut_activation', 'is_active', 'updated_at'])
        seuil_info = verifier_seuil_client(bien.client, user=request.user)
        JournalAuditAirbnb.objects.create(
            entite='Bien',
            entite_id=str(bien.id),
            action='activation_bien',
            user=request.user,
            valeur_apres={'statut_activation': 'actif', 'is_active': True, 'seuil': seuil_info},
        )
        return Response({
            'success': True,
            'statut_activation': bien.statut_activation,
            'is_active': bien.is_active,
            'seuil_client': seuil_info,
        })

    @action(detail=True, methods=['post'])
    def desactiver(self, request, pk=None):
        bien = self.get_object()
        bien.is_active = False
        bien.save(update_fields=['is_active', 'updated_at'])
        seuil_info = verifier_seuil_client(bien.client, user=request.user)
        JournalAuditAirbnb.objects.create(
            entite='Bien',
            entite_id=str(bien.id),
            action='desactivation_bien',
            user=request.user,
            valeur_apres={'is_active': False, 'seuil': seuil_info},
        )
        return Response({
            'success': True,
            'is_active': bien.is_active,
            'seuil_client': seuil_info,
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        base_qs = self.get_queryset()
        total_biens = base_qs.count()
        active_biens_qs = base_qs.filter(is_active=True, statut_activation='actif')
        biens_actifs = active_biens_qs.count()
        clients_conciergerie = base_qs.values('client').distinct().count()
        biens_zone_eloignee = base_qs.filter(zone_eloignee=True).count()

        seuil = get_airbnb_config().seuil_biens_conciergerie or 3
        role = getattr(request.user, 'role', None)
        client_qs = Client.objects.all()
        if role == 'client_conciergerie':
            client_qs = client_qs.filter(id=request.user.client_id) if request.user.client_id else client_qs.none()
        elif role == 'commercial':
            client_qs = client_qs.filter(assigned_commercial=request.user)
        else:
            client_qs = client_qs.filter(
                Q(id__in=base_qs.values_list('client_id', flat=True))
                | Q(type_client_airbnb__in=['conciergerie', 'particulier_sous_seuil'])
            ).distinct()

        clients_sous_seuil = (
            client_qs.annotate(
                nb_actifs=Count(
                    'biens_airbnb',
                    filter=Q(biens_airbnb__is_active=True, biens_airbnb__statut_activation='actif'),
                    distinct=True,
                )
            )
            .filter(nb_actifs__lt=seuil)
            .count()
        )
        return Response({
            'total_biens': total_biens,
            'biens_actifs': biens_actifs,
            'clients_conciergerie': clients_conciergerie,
            'biens_zone_eloignee': biens_zone_eloignee,
            'clients_sous_seuil_alerte': clients_sous_seuil,
        })

    @action(detail=False, methods=['get'])
    def generate_code_preview(self, request):
        client_id = request.query_params.get('client_id')
        ville = request.query_params.get('ville')
        if not client_id:
            return Response({'error': "client_id requis"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            client = Client.objects.get(id=client_id)
            _assert_client_access(request.user, client)
            code = preview_bien_code(client, ville)
            return Response({'code': code, 'trigramme': client.trigramme or compute_client_trigramme(client, persist=False)})
        except Client.DoesNotExist:
            return Response({'error': "Client introuvable"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def sync_ical(self, request, pk=None):
        bien = self.get_object()
        ical_content = request.data.get('ical_content')
        try:
            result = sync_bien_ical_turnovers(bien, ical_content=ical_content)
            return Response(result)
        except Exception as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def connecter_ical(self, request, pk=None):
        bien = self.get_object()
        ical_url = (request.data.get('ical_url') or '').strip()
        if not ical_url:
            return Response({'error': "URL iCal requise."}, status=status.HTTP_400_BAD_REQUEST)
        bien.ical_url = ical_url
        bien.save(update_fields=['ical_url', 'updated_at'])
        sync_res = None
        if request.data.get('sync_now'):
            sync_res = sync_bien_ical_turnovers(bien, ical_content=request.data.get('ical_content'))
        return Response({'success': True, 'ical_url': bien.ical_url, 'sync': sync_res})

    @action(detail=True, methods=['post'])
    def retirer_ical(self, request, pk=None):
        bien = self.get_object()
        bien.ical_url = ''
        bien.save(update_fields=['ical_url', 'updated_at'])
        return Response({'success': True, 'ical_url': ''})


class CommandeAirbnbViewSet(viewsets.ModelViewSet):
    queryset = (
        CommandeAirbnb.objects
        .select_related('bien', 'bien__client', 'intervenante', 'intervenante_2', 'runner', 'facture', 'prix_force_par')
        .prefetch_related('objets_trouves', 'filets_ramasses', 'filets_deposes', 'signalements', 'lignes_facture')
        .all()
    )
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_serializer_class(self):
        if self.action in ['list']:
            return CommandeAirbnbListSerializer
        return CommandeAirbnbDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)

        if role == 'responsable_linge':
            return qs.none()
        if role == 'client_conciergerie':
            qs = qs.filter(bien__client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(bien__client__assigned_commercial=user)
        elif role == 'runner':
            qs = qs.filter(runner=user, date_prestation=timezone.localdate())

        date_prestation = self.request.query_params.get('date')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        statut = self.request.query_params.get('statut')
        bien_id = self.request.query_params.get('bien')
        client_id = self.request.query_params.get('client')
        intervenante_id = self.request.query_params.get('intervenante')
        creneau = self.request.query_params.get('creneau')
        source = self.request.query_params.get('source')
        search = self.request.query_params.get('search')

        if date_prestation:
            qs = qs.filter(date_prestation=date_prestation)
        if date_from:
            qs = qs.filter(date_prestation__gte=date_from)
        if date_to:
            qs = qs.filter(date_prestation__lte=date_to)
        if statut:
            qs = qs.filter(statut=statut)
        if bien_id:
            qs = qs.filter(bien_id=bien_id)
        if client_id:
            qs = qs.filter(bien__client_id=client_id)
        if intervenante_id:
            qs = qs.filter(Q(intervenante_id=intervenante_id) | Q(intervenante_2_id=intervenante_id))
        if creneau:
            qs = qs.filter(creneau=creneau)
        if source:
            qs = qs.filter(source=source)
        if search:
            qs = qs.filter(
                Q(numero__icontains=search) |
                Q(bien__code__icontains=search) |
                Q(bien__nom_bien__icontains=search) |
                Q(bien__client__first_name__icontains=search) |
                Q(bien__client__last_name__icontains=search)
            )
        return qs

    def _check_premier_passage_warning(self, commande):
        if not commande or not commande.bien_id:
            return None
        if commande.nature_linge in ('depot_ramassage', 'depot_seul'):
            if not FiletLinge.objects.filter(bien_id=commande.bien_id).exists():
                return (
                    "Premier passage linge détecté pour ce bien sans filet en stock : "
                    "pensez à prévoir un premier ramassage ou dépôt au bureau avant la prestation."
                )
        return None

    def create(self, request, *args, **kwargs):
        self._last_created_commande = None
        response = super().create(request, *args, **kwargs)
        warn = self._check_premier_passage_warning(getattr(self, '_last_created_commande', None))
        if warn and isinstance(response.data, dict):
            response.data['avertissement_premier_passage'] = warn
        return response

    def _next_commande_numero(self):
        year = timezone.now().year
        prefix = f"CMD-{year}-"
        existing = CommandeAirbnb.objects.filter(numero__startswith=prefix).values_list('numero', flat=True)
        max_seq = 0
        for num in existing:
            tail = num.replace(prefix, '', 1)
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
        return f"{prefix}{max_seq + 1:04d}"

    def perform_create(self, serializer):
        bien = serializer.validated_data.get('bien')
        _assert_client_access(self.request.user, bien.client if bien else None)

        if bien and bien.client and bien.client.statut_airbnb == 'suspendu':
            raise DRFValidationError({
                'client': "Compte client suspendu pour impayé. Régularisation requise avant toute nouvelle commande."
            })

        date_prestation = serializer.validated_data.get('date_prestation')
        heure_prestation = serializer.validated_data.get('heure_prestation')
        creneau = serializer.validated_data.get('creneau', 'matin')
        nature_linge = serializer.validated_data.get('nature_linge', 'depot_ramassage')
        options = serializer.validated_data.get('options', [])
        remise_en_etat = serializer.validated_data.get('remise_en_etat', Decimal('0.00'))

        # Validation cut-off (sauf dérogation explicite Admin/R.C./R.O.)
        role = getattr(self.request.user, 'role', None)
        forcer_hors_delai = bool(
            self.request.data.get('forcer_hors_delai')
            or self.request.data.get('hors_delai_derogation')
            or serializer.validated_data.get('hors_delai_derogation')
        )
        can_bypass = role in ('admin', 'responsable_commercial', 'responsable_operations') and forcer_hors_delai

        cutoff = check_cutoff_constraint(
            date_prestation=date_prestation,
            heure_prestation=heure_prestation,
            creneau=creneau,
        )
        if not cutoff.get('allowed', True) and not can_bypass:
            raise DRFValidationError({'date_prestation': cutoff['message']})

        allow_custom = getattr(self.request.user, 'role', None) in ('admin', 'responsable_commercial')
        try:
            pricing = calculate_commande_pricing(
                bien=bien,
                options=options,
                remise_en_etat=remise_en_etat,
                date_prestation=date_prestation,
                ramassage_specifique=(nature_linge == 'ramassage_seul'),
                menage_inclus=(nature_linge != 'ramassage_seul'),
                allow_custom_options=allow_custom,
            )
        except DjangoValidationError as exc:
            raise DRFValidationError({'pricing': _extract_error_message(exc)})

        numero = self._next_commande_numero()
        statut = serializer.validated_data.get('statut', 'saisie')
        if statut not in ('brouillon', 'saisie', 'confirmee'):
            statut = 'saisie'

        commande = serializer.save(
            numero=numero,
            statut=statut,
            hors_delai_derogation=can_bypass and not cutoff.get('allowed', True),
            created_by=self.request.user if self.request.user.is_authenticated else None,
            grille_version=pricing.get('grille_version') or '',
            prix_menage=Decimal(str(pricing['prix_menage'])),
            supplement_zone=Decimal(str(pricing['supplement_zone'])),
            prix_options=Decimal(str(pricing['prix_options'])),
            total_ttc=Decimal(str(pricing['total_ttc_hors_linge'])),
        )
        if commande.hors_delai_derogation:
            JournalAuditAirbnb.objects.create(
                entite='CommandeAirbnb',
                entite_id=str(commande.id),
                action='creation_hors_delai_derogation',
                user=self.request.user,
                motif=str(self.request.data.get('motif_derogation', cutoff.get('message', ''))),
                valeur_apres={'date_prestation': str(date_prestation), 'creneau': creneau},
            )
        if commande.statut in ('saisie', 'confirmee'):
            notify_commande_confirmee(commande)
        self._last_created_commande = commande

    def perform_update(self, serializer):
        commande = serializer.instance
        role = getattr(self.request.user, 'role', None)

        if commande.statut in ('cloturee', 'facturable', 'facturee', 'annulee', 'ecart_linge', 'suspendue'):
            raise DRFValidationError({
                'statut': f"Modification directe impossible sur une commande au statut '{commande.statut}'."
            })

        if commande.bien and commande.bien.client and commande.bien.client.statut_airbnb == 'suspendu' and role != 'admin':
            raise DRFValidationError({
                'client': "Compte client suspendu pour impayé. Régularisation requise avant toute modification."
            })

        new_bien = serializer.validated_data.get('bien', commande.bien)
        _assert_client_access(self.request.user, new_bien.client if new_bien else None)

        if new_bien and new_bien.client and new_bien.client.statut_airbnb == 'suspendu' and role != 'admin':
            raise DRFValidationError({
                'client': "Le client du bien sélectionné est suspendu pour impayé."
            })

        new_date = serializer.validated_data.get('date_prestation', commande.date_prestation)
        new_heure = serializer.validated_data.get('heure_prestation', commande.heure_prestation)
        new_creneau = serializer.validated_data.get('creneau', commande.creneau)
        new_nature_linge = serializer.validated_data.get('nature_linge', commande.nature_linge)
        new_options = serializer.validated_data.get('options', commande.options or [])

        # Validation Rabat + Réassort sur état effectif
        try:
            if new_bien:
                validate_rabat_rules(
                    bien=new_bien,
                    nature_linge=new_nature_linge,
                    ramassage_specifique=(new_nature_linge == 'ramassage_seul'),
                )
            allow_custom = role in ('admin', 'responsable_commercial')
            normalize_commande_options(new_options, allow_custom_options=allow_custom)
        except DjangoValidationError as exc:
            raise DRFValidationError({'validation': _extract_error_message(exc)})

        schedule_changed = (
            new_date != commande.date_prestation
            or new_heure != commande.heure_prestation
            or new_creneau != commande.creneau
        )
        hors_delai_bypassed = False
        cutoff = {}
        if schedule_changed:
            forcer_hors_delai = bool(
                self.request.data.get('forcer_hors_delai')
                or self.request.data.get('hors_delai_derogation')
            )
            can_bypass = role in ('admin', 'responsable_commercial', 'responsable_operations') and forcer_hors_delai
            cutoff = check_cutoff_constraint(
                date_prestation=new_date,
                heure_prestation=new_heure,
                creneau=new_creneau,
            )
            if not cutoff.get('allowed', True) and not can_bypass:
                raise DRFValidationError({'date_prestation': cutoff['message']})
            hors_delai_bypassed = can_bypass and not cutoff.get('allowed', True)

        pricing_inputs_changed = (
            new_bien.id != commande.bien_id
            or new_date != commande.date_prestation
            or new_nature_linge != commande.nature_linge
            or 'options' in serializer.validated_data
        )

        save_kwargs = {}
        if hors_delai_bypassed:
            save_kwargs['hors_delai_derogation'] = True

        if not (commande.prix_force_par_id is not None and not pricing_inputs_changed):
            try:
                pricing = calculate_commande_pricing(
                    bien=new_bien,
                    options=new_options,
                    remise_en_etat=commande.remise_en_etat,
                    date_prestation=new_date,
                    ramassage_specifique=(new_nature_linge == 'ramassage_seul'),
                    menage_inclus=(new_nature_linge != 'ramassage_seul'),
                    allow_custom_options=allow_custom,
                )
            except DjangoValidationError as exc:
                raise DRFValidationError({'pricing': _extract_error_message(exc)})

            montant_linge = Decimal(str(commande.montant_linge or 0))
            save_kwargs.update({
                'grille_version': pricing.get('grille_version') or '',
                'prix_menage': Decimal(str(pricing['prix_menage'])),
                'supplement_zone': Decimal(str(pricing['supplement_zone'])),
                'prix_options': Decimal(str(pricing['prix_options'])),
                'total_ttc': Decimal(str(pricing['total_ttc_hors_linge'])) + montant_linge,
            })

        updated = serializer.save(**save_kwargs)
        if hors_delai_bypassed:
            JournalAuditAirbnb.objects.create(
                entite='CommandeAirbnb',
                entite_id=str(updated.id),
                action='modification_hors_delai_derogation',
                user=self.request.user,
                motif=str(self.request.data.get('motif_derogation', cutoff.get('message', ''))),
                valeur_apres={'date_prestation': str(new_date), 'creneau': new_creneau},
            )

    @action(detail=False, methods=['post'])
    def calculate_price(self, request):
        serializer = PricingCalculateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            bien = Bien.objects.select_related('client').get(id=serializer.validated_data['bien_id'])
        except Bien.DoesNotExist:
            return Response({'error': "Bien introuvable"}, status=status.HTTP_404_NOT_FOUND)

        _assert_client_access(request.user, bien.client)

        allow_custom = getattr(request.user, 'role', None) in ('admin', 'responsable_commercial')
        try:
            pricing = calculate_commande_pricing(
                bien=bien,
                typologie=serializer.validated_data.get('typologie'),
                options=serializer.validated_data.get('options'),
                remise_en_etat=serializer.validated_data.get('remise_en_etat'),
                date_prestation=serializer.validated_data.get('date_prestation'),
                reassort=serializer.validated_data.get('reassort'),
                video=serializer.validated_data.get('video', False),
                materiel=serializer.validated_data.get('materiel', False),
                ramassage_specifique=serializer.validated_data.get('ramassage_specifique', False),
                menage_inclus=serializer.validated_data.get('menage_inclus', True),
                allow_custom_options=allow_custom,
            )
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

        cutoff = {}
        if serializer.validated_data.get('date_prestation'):
            cutoff = check_cutoff_constraint(
                date_prestation=serializer.validated_data['date_prestation'],
                heure_prestation=serializer.validated_data.get('heure_prestation'),
                creneau=serializer.validated_data.get('creneau', 'matin'),
            )

        return Response({'pricing': pricing, 'cutoff': cutoff})

    @action(detail=True, methods=['post'], url_path='confirmer')
    def confirmer(self, request, pk=None):
        commande = self.get_object()
        if commande.bien.client.statut_airbnb == 'suspendu':
            return Response({'error': "Client suspendu pour impayé."}, status=status.HTTP_400_BAD_REQUEST)
        cutoff = check_cutoff_constraint(commande.date_prestation, commande.heure_prestation, commande.creneau)
        role = getattr(request.user, 'role', None)
        can_bypass = role in ('admin', 'responsable_commercial', 'responsable_operations') and request.data.get('forcer_hors_delai')
        if not cutoff.get('allowed', True) and not can_bypass:
            return Response({'error': cutoff['message']}, status=status.HTTP_400_BAD_REQUEST)

        if commande.statut == 'proposition':
            try:
                updated = confirmer_proposition(commande, overrides=request.data, user=request.user)
                payload = {'success': True, 'statut': updated.statut, 'numero': updated.numero}
                warn = self._check_premier_passage_warning(updated)
                if warn:
                    payload['avertissement_premier_passage'] = warn
                return Response(payload)
            except DjangoValidationError as exc:
                return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

        commande.statut = 'saisie'
        commande.save(update_fields=['statut', 'updated_at'])
        notify_commande_confirmee(commande)
        payload = {'success': True, 'statut': commande.statut}
        warn = self._check_premier_passage_warning(commande)
        if warn:
            payload['avertissement_premier_passage'] = warn
        return Response(payload)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        return self.confirmer(request, pk=pk)

    @action(detail=True, methods=['post'])
    def confirmer_proposition(self, request, pk=None):
        commande = self.get_object()
        try:
            updated = confirmer_proposition(commande, overrides=request.data, user=request.user)
            payload = {
                'success': True,
                'statut': updated.statut,
                'commande': CommandeAirbnbDetailSerializer(updated, context={'request': request}).data,
            }
            warn = self._check_premier_passage_warning(updated)
            if warn:
                payload['avertissement_premier_passage'] = warn
            return Response(payload)
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def rejeter_proposition(self, request, pk=None):
        commande = self.get_object()
        try:
            updated = rejeter_proposition(commande, motif=request.data.get('motif', ''), user=request.user)
            return Response({'success': True, 'statut': updated.statut})
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='annuler')
    def annuler(self, request, pk=None):
        commande = self.get_object()
        role = getattr(request.user, 'role', None)
        if commande.statut in ('facturee', 'cloturee', 'facturable') and role != 'admin':
            return Response(
                {'error': "Impossible d'annuler une commande déjà clôturée, facturable ou facturée."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cutoff = check_cutoff_constraint(
            date_prestation=commande.date_prestation,
            heure_prestation=commande.heure_prestation,
            creneau=commande.creneau,
        )
        hors_delai = not cutoff.get('allowed', True)
        forcer_hors_delai = bool(
            request.data.get('forcer_hors_delai') or request.data.get('hors_delai_derogation')
        )
        can_bypass = role in ('admin', 'responsable_commercial') and forcer_hors_delai
        if hors_delai and not can_bypass:
            return Response(
                {
                    'error': cutoff.get(
                        'message',
                        "Annulation impossible après le cut-off (dérogation R.C. ou Admin requise).",
                    ),
                    'cutoff': cutoff,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        motif = request.data.get('motif', '')
        old_statut = commande.statut
        was_dispatched = bool(commande.fiche_envoyee_le)
        commande.statut = 'annulee'
        commande.annulee_le = timezone.now()
        commande.annulation_motif = motif
        if hors_delai and can_bypass:
            commande.hors_delai_derogation = True
        commande.intervenante = None
        commande.intervenante_2 = None
        commande.runner = None
        update_fields = [
            'statut', 'annulee_le', 'annulation_motif',
            'intervenante', 'intervenante_2', 'runner', 'updated_at',
        ]
        if hors_delai and can_bypass:
            update_fields.append('hors_delai_derogation')
        commande.save(update_fields=update_fields)
        JournalAuditAirbnb.objects.create(
            entite='CommandeAirbnb',
            entite_id=str(commande.id),
            action='annulation_hors_delai_derogation' if (hors_delai and can_bypass) else 'annulation_commande',
            user=request.user,
            motif=motif,
            valeur_avant={'statut': old_statut},
            valeur_apres={
                'statut': 'annulee',
                'horodatage_annulation': commande.annulee_le.isoformat(),
                'hors_delai': hors_delai,
            },
        )
        notify_commande_annulee(
            commande,
            is_tardive=was_dispatched or hors_delai or (old_statut in ('assignee', 'en_cours')),
        )
        return Response({
            'success': True,
            'statut': commande.statut,
            'horodatage_annulation': commande.annulee_le.isoformat(),
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self.annuler(request, pk=pk)

    @action(detail=True, methods=['post'])
    def reactiver(self, request, pk=None):
        commande = self.get_object()
        if commande.statut != 'annulee':
            return Response({'error': "Seule une commande annulée peut être réactivée."}, status=status.HTTP_400_BAD_REQUEST)
        if commande.bien.client.statut_airbnb == 'suspendu':
            return Response({'error': "Le client est encore suspendu."}, status=status.HTTP_400_BAD_REQUEST)

        commande.statut = 'saisie'
        commande.annulee_par_suspension = False
        commande.reactivable_apres_suspension = False
        commande.annulee_le = None
        commande.save(update_fields=[
            'statut', 'annulee_par_suspension', 'reactivable_apres_suspension', 'annulee_le', 'updated_at',
        ])
        JournalAuditAirbnb.objects.create(
            entite='CommandeAirbnb',
            entite_id=str(commande.id),
            action='reactivation_commande',
            user=request.user,
            motif=request.data.get('motif', 'Réactivation manuelle après régularisation'),
            valeur_apres={'statut': commande.statut},
        )
        return Response({'success': True, 'statut': commande.statut})

    @action(detail=True, methods=['post'], url_path='forcer_prix')
    def forcer_prix(self, request, pk=None):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_commercial'):
            raise PermissionDenied("Seuls Admin et Responsable Commercial peuvent forcer le prix.")
        serializer = ForcerPrixSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        commande = self.get_object()
        try:
            updated = forcer_prix_commande(
                commande=commande,
                nouveau_prix_menage=serializer.validated_data['prix_menage'],
                motif=serializer.validated_data['motif'],
                user=request.user,
                nouveau_supplement_zone=serializer.validated_data.get('supplement_zone'),
            )
            return Response({
                'success': True,
                'prix_menage': str(updated.prix_menage),
                'supplement_zone': str(updated.supplement_zone),
                'total_ttc': str(updated.total_ttc),
            })
        except PermissionError as exc:
            raise PermissionDenied(str(exc))
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def force_price(self, request, pk=None):
        return self.forcer_prix(request, pk=pk)

    @action(detail=True, methods=['post'])
    def remonter_tdb(self, request, pk=None):
        commande = self.get_object()
        commande.statut = 'remontee_tdb'
        commande.remontee_tdb_le = timezone.now()
        commande.save(update_fields=['statut', 'remontee_tdb_le', 'updated_at'])
        return Response({'success': True, 'statut': commande.statut})

    @action(detail=True, methods=['post'])
    def demarrer(self, request, pk=None):
        commande = self.get_object()
        commande.statut = 'en_cours'
        if not commande.demarrage_reel_le:
            commande.demarrage_reel_le = timezone.now()
        commande.save(update_fields=['statut', 'demarrage_reel_le', 'updated_at'])
        return Response({'success': True, 'statut': commande.statut, 'demarrage_reel_le': commande.demarrage_reel_le})

    @action(detail=True, methods=['post'])
    def assigner(self, request, pk=None):
        commande = self.get_object()
        serializer = AssignationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        intervenante_id = serializer.validated_data.get('intervenante_id')
        intervenante_2_id = serializer.validated_data.get('intervenante_2_id')
        runner_id = serializer.validated_data.get('runner_id')

        if commande.bien.typologie == 'villa_riad':
            if not intervenante_2_id or intervenante_2_id == intervenante_id:
                return Response({
                    'error': "Règle Villa/Riad : Cette typologie requiert strictement 2 femmes de ménage distinctes assignées."
                }, status=status.HTTP_400_BAD_REQUEST)

        # Contrôle anti-chevauchement inter-services (Airbnb + Demandes/Missions classiques)
        conflicts = _find_agent_conflicts(
            [intervenante_id, intervenante_2_id],
            commande.date_prestation,
            commande.heure_prestation,
            exclude_commande_id=commande.id,
        )
        if conflicts:
            first_c = conflicts[0]
            return Response({
                'error': f"Conflit horaire détecté pour cette intervenante ({first_c['reference']} à {first_c['heure']}).",
                'conflicts': conflicts,
            }, status=status.HTTP_400_BAD_REQUEST)

        commande.intervenante_id = intervenante_id
        commande.intervenante_2_id = intervenante_2_id
        if runner_id:
            commande.runner_id = runner_id

        commande.statut = 'assignee'
        commande.save()
        notify_affectation_mission(commande, modified_after_dispatch=bool(commande.fiche_envoyee_le))

        return Response({
            'success': True,
            'message': "Mission assignée avec succès.",
            'statut': commande.statut,
        })

    @action(detail=False, methods=['get'])
    def suggestions_intervenantes(self, request):
        commande_id = request.query_params.get('commande_id')
        bien_id = request.query_params.get('bien_id')
        target_date = request.query_params.get('date')
        target_time = request.query_params.get('heure', '10:00')
        ville = request.query_params.get('ville', '')
        quartier = request.query_params.get('quartier', '')
        bien = None

        if commande_id:
            try:
                cmd = CommandeAirbnb.objects.select_related('bien').get(id=commande_id)
                bien = cmd.bien
                target_date = cmd.date_prestation
                target_time = cmd.heure_prestation
                ville = bien.ville
                quartier = bien.quartier
            except CommandeAirbnb.DoesNotExist:
                return Response({'error': "Commande introuvable."}, status=status.HTTP_404_NOT_FOUND)
        else:
            if bien_id:
                bien = Bien.objects.filter(id=bien_id).first()
                if bien:
                    ville = ville or bien.ville
                    quartier = quartier or bien.quartier
            if target_date:
                target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
            else:
                target_date = timezone.localdate()

        agents = Agent.objects.filter(
            is_archived=False,
            is_blacklisted=False,
            poste='femme_menage',
        ).exclude(statut__in=['blacklist', 'stand_by', 'en_conge', 'malade'])

        agent_ids = list(agents.values_list('id', flat=True))
        all_conflicts = _find_agent_conflicts(
            agent_ids, target_date, target_time, exclude_commande_id=commande_id
        )
        conflicted_map = {}
        for c in all_conflicts:
            for aid in c.get('agent_ids', []):
                conflicted_map.setdefault(aid, []).append(c)

        # Continuité sur ce bien (intervenante 1 ou 2 sur prestations terminées)
        continuite_counts = {}
        if bien:
            for row in CommandeAirbnb.objects.filter(
                bien=bien,
                statut__in=['cloturee', 'facturable', 'facturee'],
            ).values('intervenante_id', 'intervenante_2_id'):
                if row['intervenante_id']:
                    continuite_counts[row['intervenante_id']] = continuite_counts.get(row['intervenante_id'], 0) + 1
                if row['intervenante_2_id']:
                    continuite_counts[row['intervenante_2_id']] = continuite_counts.get(row['intervenante_2_id'], 0) + 1

        # Zone d'intervention récente (30 derniers jours sur le même quartier / ville)
        recent_zone_agents = set()
        if bien and (ville or quartier):
            cutoff_30d = target_date - timedelta(days=30)
            recent_qs = CommandeAirbnb.objects.filter(
                date_prestation__gte=cutoff_30d,
                date_prestation__lte=target_date,
                statut__in=['assignee', 'en_cours', 'cloturee', 'facturable', 'facturee'],
            ).select_related('bien')
            for cmd_rec in recent_qs:
                b_rec = cmd_rec.bien
                if not b_rec:
                    continue
                q_match = quartier and b_rec.quartier and quartier.strip().lower() == b_rec.quartier.strip().lower()
                v_match = ville and b_rec.ville and ville.strip().lower() == b_rec.ville.strip().lower()
                if q_match or (not quartier and v_match):
                    if cmd_rec.intervenante_id:
                        recent_zone_agents.add(cmd_rec.intervenante_id)
                    if cmd_rec.intervenante_2_id:
                        recent_zone_agents.add(cmd_rec.intervenante_2_id)

        # Charge du jour (Airbnb + Missions classiques + Demandes classiques/abonnements actives)
        day_loads = {}
        for row in CommandeAirbnb.objects.filter(
            date_prestation=target_date,
        ).exclude(
            statut__in=['brouillon', 'proposition', 'annulee', 'suspendue']
        ).values('intervenante_id', 'intervenante_2_id'):
            if row['intervenante_id']:
                day_loads[row['intervenante_id']] = day_loads.get(row['intervenante_id'], 0) + 1
            if row['intervenante_2_id']:
                day_loads[row['intervenante_2_id']] = day_loads.get(row['intervenante_2_id'], 0) + 1

        counted_demande_agents = set()
        for m in Mission.objects.exclude(statut=Mission.ANNULEE).filter(
            Q(date_debut__date=target_date) | Q(demande__date_intervention=target_date)
        ).prefetch_related('intervenants'):
            m_agents = set()
            if m.agent_id:
                m_agents.add(m.agent_id)
            for ia_id in m.intervenants.values_list('id', flat=True):
                m_agents.add(ia_id)
            for aid in m_agents:
                day_loads[aid] = day_loads.get(aid, 0) + 1
                if m.demande_id:
                    counted_demande_agents.add((aid, m.demande_id))

        dem_day_qs = Demande.objects.exclude(
            statut__in=[Demande.ANNULE, Demande.RESILIE]
        ).filter(
            Q(date_intervention=target_date) |
            Q(planning__date_debut__lte=target_date, planning__date_fin__isnull=True) |
            Q(planning__date_debut__lte=target_date, planning__date_fin__gte=target_date)
        ).distinct().select_related('planning').prefetch_related('profils_envoyes')

        for dem in dem_day_qs:
            occurs_today, _ = _resolve_planning_occurrence(dem, target_date, _parse_time_str(target_time))
            if not occurs_today:
                continue
            for ag_id in dem.profils_envoyes.values_list('id', flat=True):
                if (ag_id, dem.id) not in counted_demande_agents:
                    day_loads[ag_id] = day_loads.get(ag_id, 0) + 1
                    counted_demande_agents.add((ag_id, dem.id))

        suggestions = []
        for ag in agents:
            ag_conflicts = conflicted_map.get(ag.id, [])
            disponible = len(ag_conflicts) == 0
            cont = continuite_counts.get(ag.id, 0)
            same_city = bool(ville and ag.city and ag.city.strip().lower() == ville.strip().lower())
            same_quartier = bool(quartier and ag.neighborhood and quartier.strip().lower() in ag.neighborhood.strip().lower())
            recent_zone = ag.id in recent_zone_agents
            charge = day_loads.get(ag.id, 0)
            score = (
                (100 if disponible else -100)
                + (cont * 20)
                + (15 if same_quartier else 0)
                + (12 if recent_zone else 0)
                + (10 if same_city else 0)
                - (charge * 5)
            )
            suggestions.append({
                'id': ag.id,
                'full_name': ag.full_name,
                'phone': ag.phone,
                'city': ag.city,
                'neighborhood': ag.neighborhood,
                'disponible': disponible,
                'conflits': ag_conflicts,
                'continuite_bien': cont,
                'same_city': same_city,
                'same_quartier': same_quartier,
                'zone_recente': recent_zone,
                'charge_jour': charge,
                'score': score,
            })

        suggestions.sort(key=lambda x: (-int(x['disponible']), -x['score'], x['charge_jour'], x['id']))
        return Response({'date': str(target_date), 'suggestions': suggestions})

    @action(detail=True, methods=['post'])
    def cloturer(self, request, pk=None):
        commande = self.get_object()
        serializer = ClotureCommandeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        photos = serializer.validated_data.get('photos', [])
        if len(photos) < 4:
            return Response({
                'error': "Clôture impossible : Minimum 4 photos obligatoires (Salon, Chambre, SDB, Cuisine)."
            }, status=status.HTTP_400_BAD_REQUEST)

        commande.photos_cloture = photos
        commande.rapport_notes = serializer.validated_data.get('rapport_notes', commande.rapport_notes)
        commande.fin_reelle_le = timezone.now()
        commande.statut = 'cloturee'
        commande.save(update_fields=['photos_cloture', 'rapport_notes', 'fin_reelle_le', 'statut', 'updated_at'])

        facturable = update_commande_facturable_status(commande)
        notify_cloture_commande(commande)

        return Response({
            'success': True,
            'message': "Commande clôturée avec succès.",
            'statut': commande.statut,
            'facturable': facturable,
        })

    @action(detail=True, methods=['post'])
    def valider_remise_en_etat(self, request, pk=None):
        commande = self.get_object()
        heures = Decimal(str(request.data.get('heures', commande.remise_en_etat_heures or 0)))
        montant = Decimal(str(request.data.get('montant', commande.remise_en_etat or 0)))
        photos = request.data.get('photos', commande.remise_en_etat_photos or [])

        commande.remise_en_etat_heures = heures
        commande.remise_en_etat = montant
        commande.remise_en_etat_photos = photos
        commande.remise_en_etat_statut = 'validee_ops'
        commande.save(update_fields=[
            'remise_en_etat_heures', 'remise_en_etat',
            'remise_en_etat_photos', 'remise_en_etat_statut', 'updated_at',
        ])
        return Response({
            'success': True,
            'remise_en_etat_statut': commande.remise_en_etat_statut,
            'remise_en_etat': str(commande.remise_en_etat),
        })

    @action(detail=True, methods=['post'])
    def transmettre_remise_en_etat(self, request, pk=None):
        commande = self.get_object()
        commande.remise_en_etat_statut = 'envoyee_client'
        commande.save(update_fields=['remise_en_etat_statut', 'updated_at'])
        notify_remise_en_etat_client(commande)
        return Response({'success': True, 'remise_en_etat_statut': commande.remise_en_etat_statut})

    @action(detail=True, methods=['post'])
    def accord_remise_en_etat(self, request, pk=None):
        commande = self.get_object()
        decision = request.data.get('decision', 'accepte')
        preuve = (request.data.get('accord_preuve') or request.data.get('preuve') or '').strip()

        if decision in ('accepte', 'accord', 'oui'):
            if not preuve:
                return Response(
                    {'error': "Une preuve d'accord écrit est obligatoire pour facturer la remise en état."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            commande.remise_en_etat_statut = 'accord_ecrit'
            commande.remise_en_etat_accord_preuve = preuve
            commande.remise_en_etat_accord_le = timezone.now()
            if 'montant' in request.data:
                commande.remise_en_etat = Decimal(str(request.data['montant']))
            commande.total_ttc = (
                Decimal(str(commande.prix_menage or 0))
                + Decimal(str(commande.supplement_zone or 0))
                + Decimal(str(commande.prix_options or 0))
                + Decimal(str(commande.montant_linge or 0))
                + Decimal(str(commande.remise_en_etat or 0))
            )
        else:
            commande.remise_en_etat_statut = 'refusee'
            commande.remise_en_etat = Decimal('0.00')
            commande.total_ttc = (
                Decimal(str(commande.prix_menage or 0))
                + Decimal(str(commande.supplement_zone or 0))
                + Decimal(str(commande.prix_options or 0))
                + Decimal(str(commande.montant_linge or 0))
            )

        commande.save()
        facturable = update_commande_facturable_status(commande)
        return Response({
            'success': True,
            'remise_en_etat_statut': commande.remise_en_etat_statut,
            'total_ttc': str(commande.total_ttc),
            'facturable': facturable,
        })

    @action(detail=True, methods=['post'])
    def accorder_remise_en_etat(self, request, pk=None):
        return self.accord_remise_en_etat(request, pk=pk)

    @action(detail=True, methods=['get'])
    def mission_pdf_data(self, request, pk=None):
        commande = self.get_object()
        data = generate_mission_pdf_data(commande)
        if getattr(request.user, 'role', None) == 'runner':
            data.pop('intervenantes', None)
        return Response(data)

    @action(detail=True, methods=['get'])
    def exporter_fiche_mission_pdf(self, request, pk=None):
        commande = self.get_object()
        hide_agents = getattr(request.user, 'role', None) == 'runner'
        pdf_bytes = generate_fiche_mission_pdf(commande, hide_intervenantes=hide_agents)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="fiche-mission-{commande.numero}.pdf"'
        return response

    @action(detail=False, methods=['get'])
    def tdb_interventions(self, request):
        date_str = request.query_params.get('date')
        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = timezone.localdate()

        base_qs = self.get_queryset().filter(date_prestation=target_date).exclude(statut__in=['proposition', 'annulee'])
        ser = CommandeAirbnbListSerializer
        ctx = {'request': request}

        return Response({
            'date': str(target_date),
            'a_assigner': ser(base_qs.filter(statut__in=['saisie', 'confirmee', 'remontee_tdb']), many=True, context=ctx).data,
            'assignees': ser(base_qs.filter(statut='assignee'), many=True, context=ctx).data,
            'en_cours': ser(base_qs.filter(statut='en_cours'), many=True, context=ctx).data,
            'cloturees': ser(base_qs.filter(statut__in=['cloturee', 'facturable', 'facturee']), many=True, context=ctx).data,
            'ecarts_linge': ser(base_qs.filter(statut='ecart_linge'), many=True, context=ctx).data,
            'sans_demarrage_2h': ser(base_qs.filter(relance_2h_envoyee=True, statut='assignee'), many=True, context=ctx).data,
        })

    @action(detail=False, methods=['get'])
    def planning_grid(self, request):
        date_start = request.query_params.get('start', str(timezone.now().date()))
        days_count = int(request.query_params.get('days', 7))
        start = datetime.strptime(date_start, '%Y-%m-%d').date()
        end = start + timedelta(days=days_count)
        commandes = self.get_queryset().filter(date_prestation__gte=start, date_prestation__lt=end)
        serializer = CommandeAirbnbListSerializer(commandes, many=True, context={'request': request})
        return Response({'start': str(start), 'end': str(end), 'commandes': serializer.data})

    @action(detail=False, methods=['get'])
    def stats(self, request):
        today = timezone.now().date()
        base_qs = self.get_queryset()
        total_mois = base_qs.filter(date_prestation__month=today.month, date_prestation__year=today.year).count()
        today_count = base_qs.filter(date_prestation=today).count()
        a_assigner_18h = base_qs.filter(
            date_prestation=today + timedelta(days=1),
            statut__in=['saisie', 'confirmee', 'remontee_tdb'],
        ).count()
        ecarts_linge = base_qs.filter(statut='ecart_linge').count()
        propositions_ical = base_qs.filter(statut='proposition').count()
        return Response({
            'total_mois': total_mois,
            'today_count': today_count,
            'a_assigner_demain_18h': a_assigner_18h,
            'ecarts_linge_en_cours': ecarts_linge,
            'propositions_ical': propositions_ical,
        })


class FiletLingeViewSet(viewsets.ModelViewSet):
    queryset = (
        FiletLinge.objects
        .select_related('bien', 'bien__client', 'commande_ramassage', 'commande_depot', 'fige_par', 'retire_bureau_confirme_par')
        .prefetch_related('observations', 'observations__created_by')
        .all()
    )
    serializer_class = FiletLingeSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)
        if role == 'client_conciergerie':
            qs = qs.filter(bien__client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(bien__client__assigned_commercial=user)
        elif role == 'runner':
            today = timezone.localdate()
            qs = qs.filter(
                Q(commande_ramassage__runner=user, commande_ramassage__date_prestation=today)
                | Q(commande_depot__runner=user, commande_depot__date_prestation=today)
            ).distinct()

        bien_id = self.request.query_params.get('bien')
        statut = self.request.query_params.get('statut')
        if bien_id:
            qs = qs.filter(bien_id=bien_id)
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    def perform_update(self, serializer):
        if serializer.instance.montant_fige_le is not None:
            raise DRFValidationError({
                'montant': "Modification impossible : le montant de ce filet est déjà figé."
            })
        serializer.save()

    def perform_destroy(self, instance):
        if instance.montant_fige_le is not None:
            raise DRFValidationError({
                'montant': "Suppression impossible : le montant de ce filet est déjà figé."
            })
        instance.delete()

    @action(detail=True, methods=['post'])
    def confirmer_retrait_bureau(self, request, pk=None):
        filet = self.get_object()
        updated = confirmer_retrait_bureau(filet, request.user)
        return Response({'success': True, 'filet': self.get_serializer(updated).data})

    @action(detail=True, methods=['post'])
    def contester_retrait_bureau(self, request, pk=None):
        filet = self.get_object()
        nb_conteste = int(request.data.get('nb_conteste', 0))
        motif = request.data.get('motif', '')
        updated = contester_retrait_bureau(filet, nb_conteste=nb_conteste, motif=motif, user=request.user)
        return Response({'success': True, 'filet': self.get_serializer(updated).data})

    @action(detail=True, methods=['post'])
    def compter_runner(self, request, pk=None):
        filet = self.get_object()
        raw_comptage = request.data.get('comptage_runner')
        if raw_comptage is None:
            raw_comptage = normalize_comptage(request.data, strict_known_only=True)
        try:
            res = compter_runner(
                filet=filet,
                comptage_runner=raw_comptage,
                user=request.user,
                photo_ramassage=request.data.get('photo_ramassage', ''),
                remplissage_pct=int(request.data.get('remplissage_pct', filet.remplissage_pct or 50)),
                necessite_second_filet=bool(request.data.get('necessite_second_filet', False)),
            )
            safe_details = {k: v for k, v in res.items() if k != 'filet'}
            if getattr(request.user, 'role', None) in ('runner', 'responsable_linge') and isinstance(safe_details.get('calcul'), dict):
                safe_calc = dict(safe_details['calcul'])
                for key in ('montant', 'montant_sets', 'montant_pieces_supp', 'montant_minimum_applique', 'minimum_applique', 'tarif_set', 'tarif_piece_supp', 'minimum_linge'):
                    safe_calc.pop(key, None)
                safe_details['calcul'] = safe_calc
            return Response({'success': True, 'filet': self.get_serializer(filet).data, 'details': safe_details})
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def recevoir_laverie(self, request, pk=None):
        filet = self.get_object()
        raw_comptage = request.data.get('comptage_laverie')
        if raw_comptage is None:
            raw_comptage = normalize_comptage(request.data, strict_known_only=True)
        try:
            res = recevoir_laverie(
                filet=filet,
                comptage_laverie=raw_comptage,
                user=request.user,
                motif_ecart=request.data.get('motif_ecart', ''),
            )
            safe_controle = {k: v for k, v in res.items() if k != 'filet'}
            return Response({'success': True, 'filet': self.get_serializer(filet).data, 'controle': safe_controle})
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def marquer_lavage(self, request, pk=None):
        filet = self.get_object()
        filet.statut = 'en_traitement'
        filet.save(update_fields=['statut', 'updated_at'])
        return Response({'success': True, 'statut': filet.statut})

    @action(detail=True, methods=['post'])
    def marquer_pret(self, request, pk=None):
        filet = self.get_object()
        if filet.ecart != 0 and not filet.ecart_arbitre:
            return Response(
                {'error': "Écart non arbitré : impossible de marquer le filet prêt."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        filet.statut = 'pret'
        filet.save(update_fields=['statut', 'updated_at'])
        return Response({'success': True, 'statut': filet.statut})

    @action(detail=True, methods=['post'])
    def remettre_runner(self, request, pk=None):
        filet = self.get_object()
        filet.statut = 'remis_runner'
        filet.save(update_fields=['statut', 'updated_at'])
        return Response({'success': True, 'statut': filet.statut})

    @action(detail=True, methods=['post'])
    def deposer(self, request, pk=None):
        filet = self.get_object()
        if filet.statut not in ('pret', 'remis_runner'):
            return Response(
                {'error': f"Dépôt impossible : le filet est au statut '{filet.statut}' (attendu 'pret' ou 'remis_runner')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        commande_depot_id = request.data.get('commande_depot_id')
        cmd_depot = filet.commande_depot
        if commande_depot_id:
            try:
                cmd_depot = CommandeAirbnb.objects.select_related('bien').get(id=commande_depot_id)
            except (CommandeAirbnb.DoesNotExist, ValueError, TypeError):
                return Response({'error': "Commande de dépôt introuvable."}, status=status.HTTP_404_NOT_FOUND)
            if cmd_depot.bien_id != filet.bien_id:
                return Response(
                    {'error': "Le bien de la commande de dépôt ne correspond pas à ce filet."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if cmd_depot:
            if (cmd_depot.bien.ville or '').strip().lower() == 'rabat':
                return Response(
                    {'error': "Service linge / dépôt interdit à Rabat."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if cmd_depot.nature_linge not in ('depot_ramassage', 'depot_seul'):
                return Response(
                    {'error': f"La commande {cmd_depot.numero} ne prévoit pas de dépôt de linge."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        filet.statut = 'depose'
        if cmd_depot:
            filet.commande_depot = cmd_depot
        filet.save(update_fields=['statut', 'commande_depot', 'updated_at'])
        return Response({'success': True, 'statut': filet.statut})

    @action(detail=True, methods=['post'])
    def figer_montant(self, request, pk=None):
        filet = self.get_object()
        comptage_laverie = request.data.get('comptage_laverie')
        try:
            updated_filet = freeze_laundry_filet(
                filet=filet,
                user=request.user,
                comptage_laverie_final=comptage_laverie,
            )
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(updated_filet)
        return Response({
            'success': True,
            'message': f"Montant du linge figé pour le sac {updated_filet.code_filet or updated_filet.id}.",
            'filet': serializer.data,
        })

    @action(detail=True, methods=['post'])
    def arbitrer_ecart(self, request, pk=None):
        filet = self.get_object()
        commentaire = request.data.get('commentaire', '')
        base_retenue = request.data.get('base_retenue', 'laverie')
        try:
            updated = arbitrer_ecart_filet(
                filet=filet,
                commentaire=commentaire,
                user=request.user,
                base_retenue=base_retenue,
            )
            return Response({
                'success': True,
                'message': "Écart arbitré et validé.",
                'filet': self.get_serializer(updated).data,
            })
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def tournee_runner(self, request):
        today = timezone.localdate()
        user = request.user
        role = getattr(user, 'role', None)
        date_param = str(today) if role == 'runner' else request.query_params.get('date', str(today))

        commandes = (
            CommandeAirbnb.objects.filter(
                date_prestation=date_param,
                nature_linge__in=['depot_ramassage', 'depot_seul', 'ramassage_seul'],
            )
            .exclude(statut__in=['proposition', 'brouillon', 'annulee', 'suspendue'])
            .exclude(bien__ville__iexact='rabat')
            .select_related('bien', 'runner')
            .prefetch_related('filets_deposes')
        )

        if role == 'runner':
            commandes = commandes.filter(runner=user)
        elif role == 'client_conciergerie':
            commandes = commandes.filter(bien__client_id=user.client_id) if user.client_id else commandes.none()
        elif role == 'commercial':
            commandes = commandes.filter(bien__client__assigned_commercial=user)

        alertes_filets_non_prets = []
        for cmd in commandes:
            if cmd.nature_linge not in ('depot_ramassage', 'depot_seul'):
                continue
            linked_depots = list(cmd.filets_deposes.all())
            if linked_depots:
                not_ready = [f for f in linked_depots if f.statut not in ('pret', 'remis_runner', 'depose')]
                if not_ready:
                    alertes_filets_non_prets.append({
                        'commande_id': cmd.id,
                        'commande_numero': cmd.numero,
                        'bien_code': cmd.bien.code if cmd.bien else '',
                        'filet_ids': [f.id for f in not_ready],
                        'message': f"{len(not_ready)} filet(s) de dépôt non prêt(s) pour {cmd.numero}.",
                    })
            else:
                has_ready_stock = FiletLinge.objects.filter(
                    bien_id=cmd.bien_id,
                    statut__in=['pret', 'remis_runner'],
                ).exists()
                if not has_ready_stock:
                    alertes_filets_non_prets.append({
                        'commande_id': cmd.id,
                        'commande_numero': cmd.numero,
                        'bien_code': cmd.bien.code if cmd.bien else '',
                        'filet_ids': [],
                        'message': f"Aucun filet prêt disponible pour le dépôt de {cmd.numero} ({cmd.bien.code}).",
                    })

        serializer = CommandeAirbnbListSerializer(commandes, many=True, context={'request': request})
        return Response({
            'date': date_param,
            'missions_runner': serializer.data,
            'alertes_filets_non_prets': alertes_filets_non_prets,
        })


class ObservationLingeViewSet(viewsets.ModelViewSet):
    queryset = ObservationLinge.objects.select_related(
        'filet', 'filet__bien', 'filet__bien__client', 'created_by'
    ).all()
    serializer_class = ObservationLingeSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)
        if role == 'client_conciergerie':
            qs = qs.filter(filet__bien__client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(filet__bien__client__assigned_commercial=user)
        elif role == 'runner':
            today = timezone.localdate()
            qs = qs.filter(
                Q(filet__commande_ramassage__runner=user, filet__commande_ramassage__date_prestation=today)
                | Q(filet__commande_depot__runner=user, filet__commande_depot__date_prestation=today)
            ).distinct()

        filet_id = self.request.query_params.get('filet')
        if filet_id:
            qs = qs.filter(filet_id=filet_id)
        return qs

    def perform_create(self, serializer):
        # Règle immuable : facturee=False par défaut et jamais retiré du filet
        obs = serializer.save(
            created_by=self.request.user,
            facturee=False,
            notifie_commercial_le=timezone.now(),
        )
        notify_observation_linge_commercial(obs)

    @action(detail=True, methods=['post'])
    def activer_facturation(self, request, pk=None):
        obs = self.get_object()
        facturee = bool(request.data.get('facturee', True))
        montant_facture = request.data.get('montant_facture')
        try:
            updated = toggle_observation_facturation(
                observation=obs,
                facturee=facturee,
                montant_facture=montant_facture,
                user=request.user,
            )
            return Response({'success': True, 'observation': self.get_serializer(updated).data})
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def toggle_facturation(self, request, pk=None):
        return self.activer_facturation(request, pk=pk)

    @action(detail=True, methods=['post'])
    def notifier_client(self, request, pk=None):
        obs = self.get_object()
        msg = request.data.get('message_commercial', '')
        updated = transmettre_observation_client(obs, message_commercial=msg, user=request.user)
        return Response({'success': True, 'observation': self.get_serializer(updated).data})

    @action(detail=True, methods=['post'])
    def transmettre_client(self, request, pk=None):
        return self.notifier_client(request, pk=pk)


class SignalementCommandeViewSet(viewsets.ModelViewSet):
    queryset = SignalementCommande.objects.select_related(
        'commande', 'commande__bien', 'commande__bien__client',
        'signale_par', 'valide_par', 'arbitre_par',
    ).all()
    serializer_class = SignalementCommandeSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)
        if role == 'client_conciergerie':
            qs = qs.filter(commande__bien__client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(commande__bien__client__assigned_commercial=user)
        elif role == 'runner':
            qs = qs.filter(commande__runner=user)

        commande_id = self.request.query_params.get('commande')
        statut = self.request.query_params.get('statut')
        if commande_id:
            qs = qs.filter(commande_id=commande_id)
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    def _resolve_suspended_commande(self, sig, request):
        cmd = sig.commande
        if not cmd or sig.motif != 'acces_impossible' or cmd.statut != 'suspendue':
            return None
        decision = (request.data.get('decision_commande') or request.data.get('statut_commande') or '').strip().lower()
        if not decision:
            return None
        old_statut = cmd.statut
        motif = request.data.get('commentaire', '') or sig.description or "Résolution incident accès impossible"
        if decision in ('annuler', 'annulee'):
            cmd.statut = 'annulee'
            cmd.annulee_le = timezone.now()
            cmd.annulation_motif = motif
            cmd.intervenante = None
            cmd.intervenante_2 = None
            cmd.runner = None
            cmd.save(update_fields=[
                'statut', 'annulee_le', 'annulation_motif',
                'intervenante', 'intervenante_2', 'runner', 'updated_at',
            ])
        elif decision in ('reprendre', 'reprogrammer', 'confirmee', 'saisie', 'assignee'):
            if decision in ('reprendre', 'reprogrammer'):
                target_statut = 'assignee' if cmd.intervenante_id else 'saisie'
            else:
                target_statut = decision
            update_fields = ['statut', 'updated_at']
            new_date = request.data.get('nouvelle_date_prestation')
            if new_date:
                cmd.date_prestation = date.fromisoformat(str(new_date)[:10])
                update_fields.append('date_prestation')
            cmd.statut = target_statut
            cmd.save(update_fields=update_fields)
        else:
            return None

        JournalAuditAirbnb.objects.create(
            entite='CommandeAirbnb',
            entite_id=str(cmd.id),
            action='resolution_suspension_acces_impossible',
            user=request.user,
            motif=motif,
            valeur_avant={'statut': old_statut},
            valeur_apres={'statut': cmd.statut, 'signalement_id': str(sig.id)},
        )
        return cmd.statut

    def perform_create(self, serializer):
        commande = serializer.validated_data.get('commande')
        _assert_client_access(self.request.user, commande.bien.client if commande else None)
        sig = serializer.save(signale_par=self.request.user)
        cmd = sig.commande
        if sig.motif == 'bien_sale':
            cmd.remise_en_etat_statut = 'signalee'
            cmd.remise_en_etat_heures = sig.heures_estimees
            if sig.photos:
                cmd.remise_en_etat_photos = sig.photos
            cmd.save(update_fields=[
                'remise_en_etat_statut', 'remise_en_etat_heures',
                'remise_en_etat_photos', 'updated_at',
            ])
        elif sig.motif == 'objet_oublie':
            first_photo = sig.photos[0] if isinstance(sig.photos, list) and sig.photos else ''
            objet = ObjetTrouve.objects.create(
                bien=cmd.bien,
                commande=cmd,
                description=sig.description or "Objet oublié signalé lors de la prestation",
                piece=str(self.request.data.get('piece', '') or ''),
                photo_url=first_photo,
                statut='trouve',
                signale_par=self.request.user,
                signale_le=timezone.now(),
            )
            notify_objet_trouve(objet)
        elif sig.motif == 'acces_impossible':
            old_statut = cmd.statut
            if cmd.statut not in ('cloturee', 'facturable', 'facturee', 'annulee'):
                cmd.statut = 'suspendue'
                cmd.save(update_fields=['statut', 'updated_at'])
                JournalAuditAirbnb.objects.create(
                    entite='CommandeAirbnb',
                    entite_id=str(cmd.id),
                    action='suspension_commande_acces_impossible',
                    user=self.request.user,
                    motif=sig.description or "Accès impossible signalé",
                    valeur_avant={'statut': old_statut},
                    valeur_apres={'statut': 'suspendue', 'signalement_id': str(sig.id)},
                )
            notify_signalement_client(sig)
        notify_signalement_operations(sig)

    @action(detail=True, methods=['post'])
    def valider(self, request, pk=None):
        sig = self.get_object()
        sig.statut = 'validee_ops'
        sig.valide_par = request.user
        if 'heures_estimees' in request.data:
            sig.heures_estimees = Decimal(str(request.data['heures_estimees']))
        sig.save(update_fields=['statut', 'valide_par', 'heures_estimees'])

        if sig.motif == 'bien_sale':
            cmd = sig.commande
            cmd.remise_en_etat_statut = 'validee_ops'
            cmd.remise_en_etat_heures = sig.heures_estimees
            if 'montant' in request.data:
                cmd.remise_en_etat = Decimal(str(request.data['montant']))
            cmd.save(update_fields=['remise_en_etat_statut', 'remise_en_etat_heures', 'remise_en_etat', 'updated_at'])

        return Response({'success': True, 'signalement': self.get_serializer(sig).data})

    @action(detail=True, methods=['post'])
    def transmettre_client(self, request, pk=None):
        sig = self.get_object()
        sig.statut = 'transmis_client'
        sig.save(update_fields=['statut'])
        if sig.motif == 'bien_sale':
            cmd = sig.commande
            cmd.remise_en_etat_statut = 'envoyee_client'
            cmd.save(update_fields=['remise_en_etat_statut', 'updated_at'])
        notify_signalement_client(sig)
        return Response({'success': True, 'signalement': self.get_serializer(sig).data})

    @action(detail=True, methods=['post'])
    def accord_client(self, request, pk=None):
        sig = self.get_object()
        decision = request.data.get('accord_client', request.data.get('decision', 'accepte'))
        preuve = (request.data.get('accord_preuve') or '').strip()
        if decision == 'accepte' and not preuve:
            return Response(
                {'error': "Une preuve d'accord écrit est requise pour valider un supplément."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sig.accord_client = 'accepte' if decision == 'accepte' else 'refuse'
        sig.accord_preuve = preuve
        sig.save(update_fields=['accord_client', 'accord_preuve'])

        if sig.motif == 'bien_sale':
            cmd = sig.commande
            if sig.accord_client == 'accepte':
                cmd.remise_en_etat_statut = 'accord_ecrit'
                cmd.remise_en_etat_accord_preuve = preuve
                cmd.remise_en_etat_accord_le = timezone.now()
                if 'montant' in request.data:
                    cmd.remise_en_etat = Decimal(str(request.data['montant']))
            else:
                cmd.remise_en_etat_statut = 'refusee'
                cmd.remise_en_etat = Decimal('0.00')
            cmd.total_ttc = (
                Decimal(str(cmd.prix_menage or 0))
                + Decimal(str(cmd.supplement_zone or 0))
                + Decimal(str(cmd.prix_options or 0))
                + Decimal(str(cmd.montant_linge or 0))
                + Decimal(str(cmd.remise_en_etat or 0))
            )
            cmd.save()
            update_commande_facturable_status(cmd)

        return Response({'success': True, 'signalement': self.get_serializer(sig).data})

    @action(detail=True, methods=['post'])
    def repondre(self, request, pk=None):
        return self.accord_client(request, pk=pk)

    @action(detail=True, methods=['post'])
    def accord(self, request, pk=None):
        return self.accord_client(request, pk=pk)

    @action(detail=True, methods=['post'])
    def arbitrer(self, request, pk=None):
        sig = self.get_object()
        sig.statut = 'arbitre'
        sig.arbitre_par = request.user
        sig.arbitre_le = timezone.now()
        sig.save(update_fields=['statut', 'arbitre_par', 'arbitre_le'])
        cmd_statut = self._resolve_suspended_commande(sig, request)
        JournalAuditAirbnb.objects.create(
            entite='SignalementCommande',
            entite_id=str(sig.id),
            action='arbitrage_signalement',
            user=request.user,
            motif=request.data.get('commentaire', ''),
            valeur_apres={'statut': sig.statut, 'accord_client': sig.accord_client, 'commande_statut': cmd_statut},
        )
        payload = {'success': True, 'signalement': self.get_serializer(sig).data}
        if cmd_statut:
            payload['commande_statut'] = cmd_statut
        return Response(payload)

    @action(detail=True, methods=['post'])
    def clore(self, request, pk=None):
        sig = self.get_object()
        sig.statut = 'clos'
        sig.save(update_fields=['statut'])
        cmd_statut = self._resolve_suspended_commande(sig, request)
        payload = {'success': True, 'statut': sig.statut}
        if cmd_statut:
            payload['commande_statut'] = cmd_statut
        return Response(payload)


class ObjetTrouveViewSet(viewsets.ModelViewSet):
    queryset = ObjetTrouve.objects.select_related(
        'bien', 'bien__client', 'commande', 'signale_par', 'mis_en_securite_par', 'client_informe_par'
    ).all()
    serializer_class = ObjetTrouveSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)
        if role == 'responsable_linge':
            return qs.none()
        if role == 'client_conciergerie':
            return qs.filter(bien__client_id=user.client_id) if user.client_id else qs.none()
        if role == 'commercial':
            return qs.filter(bien__client__assigned_commercial=user)
        if role == 'runner':
            return qs.filter(commande__runner=user)
        return qs

    def perform_create(self, serializer):
        objet = serializer.save(
            signale_par=self.request.user,
            signale_le=timezone.now(),
        )
        notify_objet_trouve(objet)

    @action(detail=True, methods=['post'])
    def mettre_en_securite(self, request, pk=None):
        objet = self.get_object()
        objet.statut = 'mis_en_securite'
        objet.mis_en_securite_par = request.user
        objet.mis_en_securite_le = timezone.now()
        if request.data.get('photo_mise_en_securite'):
            objet.photo_mise_en_securite = request.data['photo_mise_en_securite']
        objet.save(update_fields=[
            'statut', 'mis_en_securite_par', 'mis_en_securite_le',
            'photo_mise_en_securite', 'updated_at',
        ])
        return Response({'success': True, 'objet': self.get_serializer(objet).data})

    @action(detail=True, methods=['post'])
    def notifier_client(self, request, pk=None):
        objet = self.get_object()
        objet.statut = 'signale_client'
        objet.client_informe_par = request.user
        objet.client_informe_le = timezone.now()
        objet.save(update_fields=['statut', 'client_informe_par', 'client_informe_le', 'updated_at'])
        notify_objet_trouve_client(objet)
        return Response({'success': True, 'objet': self.get_serializer(objet).data})

    @action(detail=True, methods=['post'])
    def informer_client(self, request, pk=None):
        return self.notifier_client(request, pk=pk)

    @action(detail=True, methods=['post'])
    def indiquer_instruction(self, request, pk=None):
        objet = self.get_object()
        instruction = (request.data.get('instruction_client') or request.data.get('instruction') or '').strip()
        if not instruction:
            return Response({'error': "Instruction client requise."}, status=status.HTTP_400_BAD_REQUEST)
        objet.instruction_client = instruction
        objet.save(update_fields=['instruction_client', 'updated_at'])
        return Response({'success': True, 'instruction_client': objet.instruction_client})

    @action(detail=True, methods=['post'])
    def instruction(self, request, pk=None):
        return self.indiquer_instruction(request, pk=pk)

    @action(detail=True, methods=['post'])
    def restituer(self, request, pk=None):
        objet = self.get_object()
        remis_a = request.data.get('remis_a', '')
        objet.statut = 'restitue'
        objet.remis_a = remis_a
        objet.date_restitution = timezone.now()
        objet.save(update_fields=['statut', 'remis_a', 'date_restitution', 'updated_at'])
        return Response({
            'success': True,
            'message': f"Objet marqué comme restitué à {remis_a}.",
        })


class FacturationAirbnbViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Facture.objects
        .filter(source=Facture.SOURCE_AIRBNB)
        .select_related('client', 'created_by', 'annulee_par')
        .prefetch_related('lignes_airbnb', 'lignes_airbnb__commande', 'paiements', 'commandes_airbnb')
        .order_by('-date_emission', '-created_at')
    )
    serializer_class = FactureAirbnbSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        role = getattr(user, 'role', None)
        if role == 'client_conciergerie':
            qs = qs.filter(client_id=user.client_id) if user.client_id else qs.none()
        elif role == 'commercial':
            qs = qs.filter(client__assigned_commercial=user)
        elif role == 'responsable_operations':
            qs = qs.none()

        client_id = self.request.query_params.get('client')
        statut = self.request.query_params.get('statut')
        if client_id:
            qs = qs.filter(client_id=client_id)
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    @action(detail=False, methods=['get'])
    def resume(self, request):
        qs = self.get_queryset()
        today = timezone.localdate()
        agg = qs.exclude(statut=Facture.ANNULE).aggregate(
            total_facture=Sum('montant_total'),
            total_paye=Sum('montant_paye'),
        )
        en_retard = qs.filter(
            statut__in=[Facture.EN_ATTENTE, Facture.PARTIEL],
            date_echeance__lt=today,
        ).count()
        role = getattr(request.user, 'role', None)
        if role == 'client_conciergerie':
            clients_suspendus_qs = (
                Client.objects.filter(id=request.user.client_id, statut_airbnb='suspendu')
                if request.user.client_id else Client.objects.none()
            )
        elif role == 'commercial':
            clients_suspendus_qs = Client.objects.filter(
                assigned_commercial=request.user,
                statut_airbnb='suspendu',
            )
        elif role == 'responsable_operations':
            clients_suspendus_qs = Client.objects.none()
        else:
            clients_suspendus_qs = Client.objects.filter(statut_airbnb='suspendu')
        clients_suspendus = clients_suspendus_qs.count()
        return Response({
            'nb_factures': qs.count(),
            'total_facture': str(agg.get('total_facture') or Decimal('0.00')),
            'total_paye': str(agg.get('total_paye') or Decimal('0.00')),
            'factures_en_retard': en_retard,
            'clients_suspendus': clients_suspendus,
        })

    @action(detail=False, methods=['get'])
    def stats(self, request):
        return self.resume(request)

    @action(detail=False, methods=['get'])
    def calendrier_facturation(self, request):
        client_id = request.query_params.get('client_id') or request.query_params.get('client')
        if not client_id:
            if getattr(request.user, 'role', None) == 'client_conciergerie' and request.user.client_id:
                client_id = request.user.client_id
            else:
                return Response({'error': "client_id requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response({'error': "Client introuvable."}, status=status.HTTP_404_NOT_FOUND)
        _assert_client_access(request.user, client)
        n = int(request.query_params.get('n', 5))
        return Response({'client_id': client.id, 'calendrier': preview_calendrier_facturation(client, n=n)})

    @action(detail=False, methods=['post'])
    def generer_facture_passage(self, request):
        commande_id = request.data.get('commande_id')
        if not commande_id:
            return Response({'error': "commande_id requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            commande = CommandeAirbnb.objects.select_related('bien', 'bien__client').get(id=commande_id)
        except CommandeAirbnb.DoesNotExist:
            return Response({'error': "Commande introuvable."}, status=status.HTTP_404_NOT_FOUND)

        try:
            facture = generer_facture_passage(commande, user=request.user)
            return Response(self.get_serializer(facture).data, status=status.HTTP_201_CREATED)
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def generer_factures_cycle(self, request):
        date_str = request.data.get('date')
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
        client_id = request.data.get('client_id')
        res = generer_factures_cycle(target_date=target_date, user=request.user, client_id=client_id)
        return Response({
            'date': str(res['date']),
            'bascules_count': len(res['bascules']),
            'factures_creees': [self.get_serializer(f).data for f in res['factures']],
        })

    @action(detail=True, methods=['post'])
    def enregistrer_paiement(self, request, pk=None):
        facture = self.get_object()
        try:
            montant = Decimal(str(request.data.get('montant')))
        except Exception:
            return Response({'error': "Montant invalide."}, status=status.HTTP_400_BAD_REQUEST)

        mode = request.data.get('mode', 'virement')
        date_str = request.data.get('date')
        payment_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
        try:
            res = enregistrer_paiement(
                facture=facture,
                montant=montant,
                mode=mode,
                payment_date=payment_date,
                reference=request.data.get('reference', ''),
                notes=request.data.get('notes', ''),
                user=request.user,
            )
            return Response({
                'success': True,
                'facture': self.get_serializer(res['facture']).data,
                'entree_caisse_id': res['entree_caisse'].id,
                'reactived_client': res['reactived_client'],
            })
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def declarer_virement(self, request, pk=None):
        facture = self.get_object()
        reference = (request.data.get('reference') or '').strip()
        if not reference:
            return Response({'error': "La référence de virement est obligatoire."}, status=status.HTTP_400_BAD_REQUEST)
        updated = declarer_virement(
            facture=facture,
            reference=reference,
            justificatif_url=request.data.get('justificatif_url', ''),
            montant_declare=request.data.get('montant_declare'),
            user=request.user,
        )
        return Response({'success': True, 'facture': self.get_serializer(updated).data})

    @action(detail=True, methods=['post'])
    def annuler_facture(self, request, pk=None):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_facturation'):
            raise PermissionDenied("Seuls Admin et Responsable Facturation peuvent annuler une facture.")
        facture = self.get_object()
        motif = (request.data.get('motif') or '').strip()
        try:
            updated = annuler_facture(
                facture,
                motif=motif,
                user=request.user,
                commande_id=request.data.get('commande_id'),
                ligne_ids=request.data.get('ligne_ids'),
            )
            return Response({'success': True, 'facture': self.get_serializer(updated).data})
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def geste_commercial(self, request, pk=None):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_facturation'):
            raise PermissionDenied("Seuls Admin et Responsable Facturation peuvent appliquer un geste commercial.")
        facture = self.get_object()
        try:
            ligne = appliquer_geste_commercial(
                facture=facture,
                montant=request.data.get('montant'),
                designation=request.data.get('designation', 'Geste commercial'),
                motif=request.data.get('motif', ''),
                user=request.user,
            )
            facture.refresh_from_db()
            return Response({
                'success': True,
                'ligne': FactureLigneAirbnbSerializer(ligne).data,
                'facture': self.get_serializer(facture).data,
            })
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reduction_partielle(self, request, pk=None):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_facturation'):
            raise PermissionDenied("Seuls Admin et Responsable Facturation peuvent appliquer une réduction partielle.")
        facture = self.get_object()
        try:
            ligne = appliquer_reduction_partielle(
                facture=facture,
                montant_reduction=request.data.get('montant'),
                motif=request.data.get('motif', ''),
                commande_id=request.data.get('commande_id'),
                designation=request.data.get('designation', ''),
                user=request.user,
            )
            facture.refresh_from_db()
            return Response({
                'success': True,
                'ligne': FactureLigneAirbnbSerializer(ligne).data,
                'facture': self.get_serializer(facture).data,
            })
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def lever_suspension(self, request):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_facturation'):
            raise PermissionDenied("Seuls Admin et Responsable Facturation peuvent lever une suspension manuellement.")
        client_id = request.data.get('client_id')
        motif = (request.data.get('motif') or '').strip()
        if not client_id:
            return Response({'error': "client_id requis."}, status=status.HTTP_400_BAD_REQUEST)
        if not motif:
            return Response({'error': "Un motif explicite est obligatoire pour lever une suspension."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response({'error': "Client introuvable."}, status=status.HTTP_404_NOT_FOUND)
        if client.statut_airbnb != 'suspendu':
            return Response({'error': "Ce client n'est pas suspendu."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        client.statut_airbnb = 'actif'
        client.save(update_fields=['statut_airbnb'])

        CommandeAirbnb.objects.filter(
            bien__client=client,
            statut='annulee',
            annulee_par_suspension=True,
            date_prestation__gte=today,
        ).update(reactivable_apres_suspension=True)

        reactivable_commandes = list(
            CommandeAirbnb.objects.filter(
                bien__client=client,
                statut='annulee',
                annulee_par_suspension=True,
                reactivable_apres_suspension=True,
                date_prestation__gte=today,
            ).values('id', 'numero', 'date_prestation')
        )
        JournalAuditAirbnb.objects.create(
            entite='Client',
            entite_id=str(client.id),
            action='suspension_levee_manuelle',
            user=request.user,
            motif=motif,
            valeur_avant={'statut_airbnb': 'suspendu'},
            valeur_apres={
                'statut_airbnb': 'actif',
                'reactivable_count': len(reactivable_commandes),
            },
        )
        notify_reactivation_client(client, reactivable_count=len(reactivable_commandes))
        return Response({
            'success': True,
            'client_id': client.id,
            'statut_airbnb': client.statut_airbnb,
            'reactivable_count': len(reactivable_commandes),
            'reactivable_commandes': reactivable_commandes,
        })

    @action(detail=False, methods=['post'])
    def annuler_bascule_mensuelle(self, request):
        if getattr(request.user, 'role', None) not in ('admin', 'responsable_commercial', 'responsable_facturation'):
            raise PermissionDenied("Action réservée au Responsable Commercial, Responsable Facturation ou Admin.")
        client_id = request.data.get('client_id')
        motif = (request.data.get('motif') or '').strip()
        if not client_id:
            return Response({'error': "client_id requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response({'error': "Client introuvable."}, status=status.HTTP_404_NOT_FOUND)
        try:
            updated = annuler_bascule_mensuelle(client, motif=motif, user=request.user)
            return Response({
                'success': True,
                'client_id': updated.id,
                'probatoire_bascule_annulee': updated.probatoire_bascule_annulee,
            })
        except DjangoValidationError as exc:
            return Response({'error': _extract_error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def annuler_bascule(self, request):
        return self.annuler_bascule_mensuelle(request)

    @action(detail=True, methods=['get'])
    def exporter_facture_pdf(self, request, pk=None):
        facture = self.get_object()
        pdf_bytes = generate_facture_airbnb_pdf(facture)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="facture-{facture.numero}.pdf"'
        return response

    @action(detail=False, methods=['post'])
    def lancer_cron(self, request):
        ALLOWED_CRONS = {
            'remontee_tdb_18h',
            'dispatch_whatsapp_20h',
            'sync_ical_turnovers',
            'verifier_suspensions_clients',
            'generer_factures_airbnb',
            'relances_execution_airbnb',
            'verifier_seuil_conciergerie',
        }
        OPS_CRONS = {
            'remontee_tdb_18h',
            'dispatch_whatsapp_20h',
            'sync_ical_turnovers',
            'relances_execution_airbnb',
        }
        job = request.data.get('job') or request.data.get('command')
        if job not in ALLOWED_CRONS:
            return Response(
                {'error': f"Job inconnu. Autorisés : {sorted(ALLOWED_CRONS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        role = getattr(request.user, 'role', None)
        if role in ('charge_operations', 'responsable_operations') and job not in OPS_CRONS:
            raise PermissionDenied("Les crons de facturation ou seuil sont réservés au Responsable Facturation / Admin.")
        kwargs = {}
        if request.data.get('date') and job in ('generer_factures_airbnb', 'verifier_suspensions_clients', 'dispatch_whatsapp_20h', 'remontee_tdb_18h', 'relances_execution_airbnb', 'verifier_seuil_conciergerie'):
            kwargs['date'] = request.data['date']
        call_command(job, **kwargs)
        JournalAuditAirbnb.objects.create(
            entite='CronJob',
            entite_id=job,
            action='lancement_manuel_cron',
            user=request.user,
            valeur_apres={'job': job, 'args': kwargs},
        )
        return Response({'success': True, 'job': job})


class JournalAuditAirbnbViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JournalAuditAirbnb.objects.select_related('user').all()
    serializer_class = JournalAuditAirbnbSerializer
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        entite = self.request.query_params.get('entite')
        entite_id = self.request.query_params.get('entite_id')
        action_name = self.request.query_params.get('action')
        if entite:
            qs = qs.filter(entite=entite)
        if entite_id:
            qs = qs.filter(entite_id=entite_id)
        if action_name:
            qs = qs.filter(action=action_name)
        return qs


class AirbnbPhotoUploadView(APIView):
    """
    Endpoint pour le téléversement physique de photos du module Airbnb.
    """
    permission_classes = [permissions.IsAuthenticated, RoleBasedPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.pdf'}
    MAX_FILE_SIZE = 15 * 1024 * 1024

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('photo') or request.FILES.get('file')
        if not file_obj:
            return Response(
                {'error': "Aucun fichier photo fourni dans la requête (clé attendue : 'photo' ou 'file')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file_obj.size > self.MAX_FILE_SIZE:
            return Response(
                {'error': f"Le fichier est trop volumineux ({round(file_obj.size / (1024 * 1024), 2)} Mo). Limite maximale : 15 Mo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _, ext = os.path.splitext(file_obj.name)
        ext = ext.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            return Response(
                {'error': f"Extension non supportée ({ext}). Formats autorisés : JPG, JPEG, PNG, WEBP, HEIC, PDF."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        category = request.data.get('category', 'general')
        safe_category = "".join(c for c in category if c.isalnum() or c in ('_', '-')) or 'general'

        unique_id = uuid.uuid4().hex[:12]
        raw_name = os.path.basename(file_obj.name).replace(' ', '_')
        clean_filename = f"{unique_id}_{raw_name}"
        storage_path = f"airbnb/{safe_category}/{clean_filename}"

        try:
            saved_name = default_storage.save(storage_path, file_obj)
            clean_saved_name = saved_name.lstrip('/')
            media_prefix = getattr(settings, 'MEDIA_URL', '/api/media/').rstrip('/')
            relative_url = f"{media_prefix}/{clean_saved_name}"
            try:
                storage_url = default_storage.url(saved_name)
            except Exception:
                storage_url = relative_url

            if isinstance(storage_url, str) and storage_url.startswith(('http://', 'https://')):
                media_url = storage_url
            else:
                api_base = str(getattr(settings, 'API_BASE_URL', '') or '').rstrip('/')
                if api_base.startswith(('http://localhost', 'http://127.0.0.1')):
                    api_base = ''
                public_base = (
                    getattr(settings, 'BACKEND_PUBLIC_URL', '')
                    or getattr(settings, 'SITE_URL', '')
                    or api_base
                    or ''
                ).rstrip('/')
                if public_base:
                    media_url = f"{public_base}{relative_url}"
                else:
                    media_url = request.build_absolute_uri(relative_url)
            content_type = file_obj.content_type or mimetypes.guess_type(saved_name)[0] or 'image/jpeg'

            return Response({
                'success': True,
                'url': media_url,
                'filename': clean_filename,
                'path': saved_name,
                'size': file_obj.size,
                'content_type': content_type,
                'category': safe_category,
            }, status=status.HTTP_201_CREATED)
        except Exception as err:
            return Response(
                {'error': f"Erreur lors de l'enregistrement dans le bucket de stockage : {str(err)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
