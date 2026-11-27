import unicodedata
from decimal import Decimal, InvalidOperation
from django.utils import timezone

from .serializers import FORBIDDEN_DEMO_PROMO_CODES


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    s = str(value).strip().lower()
    s = "".join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return " ".join(s.split())


def _normalize_booking_mode(mode: str) -> str:
    cleaned = _normalize_text(mode).replace("-", "").replace("_", "").replace(" ", "")
    if cleaned in ("subscription", "abonnement", "abonne", "recurrent", "recurring"):
        return "abonnement"
    if cleaned in ("once", "oneshot", "ponctuel", "ponctuelle", "unique", "single"):
        return "oneshot"
    return cleaned


def _clean_service(s: str) -> str:
    if not s:
        return ""
    s = _normalize_text(s)
    s = s.replace("nettoyage", "menage")
    s = s.replace("air bnb", "airbnb")
    s = s.replace("garde malade", "auxiliaire de vie")
    s = s.replace("placement & gestion", "placement")
    s = s.replace("placement et gestion", "placement")
    return "".join(c for c in s if c.isalnum())


def _fail(status_code: int, reason_code: str, message: str, **extra) -> dict:
    payload = {
        "valid": False,
        "reason_code": reason_code,
        "message": message,
        **extra,
    }
    return {
        "valid": False,
        "status_code": status_code,
        "reason_code": reason_code,
        "message": message,
        "promo": None,
        "payload": payload,
    }


def validate_promo_for_booking(
    code_or_promo,
    *,
    segment: str = "",
    service: str = "",
    phone: str = "",
    city: str = "",
    booking_mode: str = "",
    order_amount=None,
    client=None,
) -> dict:
    """
    Validation serveur unique d'un code promo pour l'endpoint de vérification publique
    ET pour l'enregistrement définitif d'une demande (PublicDemandeCreateSerializer).
    """
    from .models import PromoCode

    promo = None
    if isinstance(code_or_promo, PromoCode):
        promo = code_or_promo
        code_str = (promo.code or "").strip()
    else:
        code_str = str(code_or_promo or "").strip()

    segment = str(segment or "").strip()
    service = str(service or "").strip()
    phone = str(phone or "").strip()
    city = str(city or "").strip()
    booking_mode = str(booking_mode or "").strip()

    if not code_str:
        return _fail(400, "empty_code", "Veuillez saisir un code promo.")

    # Strict rejection of demo codes (case-insensitive), regardless of DB state
    if code_str.upper() in FORBIDDEN_DEMO_PROMO_CODES:
        return _fail(
            400,
            "demo_code",
            "Ce code de démonstration n'est pas valable pour une réservation.",
        )

    # Parse and validate order_amount whenever provided (reject NaN, Infinity, negative, bool)
    parsed_amount = None
    if order_amount is not None:
        if isinstance(order_amount, bool):
            return _fail(400, "invalid_order_amount", "Le montant de commande fourni est invalide.")
        amount_str = str(order_amount).strip()
        if amount_str != "":
            try:
                parsed_amount = Decimal(amount_str)
            except (InvalidOperation, ValueError, TypeError):
                return _fail(
                    400,
                    "invalid_order_amount",
                    "Le montant de commande fourni est invalide.",
                )
            if not parsed_amount.is_finite() or parsed_amount < 0:
                return _fail(
                    400,
                    "invalid_order_amount",
                    "Le montant de commande fourni est invalide.",
                )

    if promo is None:
        promo = PromoCode.objects.filter(code__iexact=code_str, archived=False).first()
    elif promo.archived:
        promo = None

    if not promo:
        return _fail(404, "not_found", "Ce code promo n'existe pas ou est invalide.")

    if promo.status != 'active':
        return _fail(400, "inactive", "Ce code promo n'est pas actif.")

    today = timezone.localdate()
    if promo.valid_from > today:
        return _fail(400, "not_started", "Ce code promo n'est pas encore valide.")

    if promo.valid_until and promo.valid_until < today:
        return _fail(400, "expired", "Ce code promo a expiré.")

    # Segment check
    if promo.segment != 'tous':
        norm_seg = segment.lower()
        if promo.segment == 'particulier' and norm_seg != 'particulier':
            return _fail(400, "segment_ineligible", "Ce code promo est réservé aux particuliers.")
        elif promo.segment == 'entreprise' and norm_seg != 'entreprise':
            return _fail(400, "segment_ineligible", "Ce code promo est réservé aux entreprises.")

    # Service check
    if promo.services and isinstance(promo.services, list) and len(promo.services) > 0:
        cleaned_services = [_clean_service(srv) for srv in promo.services]
        cleaned_input_service = _clean_service(service)
        if not service or cleaned_input_service not in cleaned_services:
            return _fail(
                400,
                "service_ineligible",
                "Ce code promo n'est pas applicable à ce service.",
            )

    # City eligibility check (V3.2 — case & accent insensitive)
    if promo.villes and isinstance(promo.villes, list) and len(promo.villes) > 0:
        cleaned_villes = [
            _normalize_text(v) for v in promo.villes if str(v or "").strip()
        ]
        cleaned_city = _normalize_text(city)
        if cleaned_villes and (not cleaned_city or cleaned_city not in cleaned_villes):
            return _fail(
                400,
                "city_ineligible",
                "Ce code promo n'est pas valable pour cette ville.",
            )

    # Booking mode eligibility check (V3.2 — normalize subscription -> abonnement, once -> oneshot)
    if promo.modes_reservation and isinstance(promo.modes_reservation, list) and len(promo.modes_reservation) > 0:
        allowed_modes = [
            _normalize_booking_mode(m)
            for m in promo.modes_reservation
            if str(m or "").strip()
        ]
        normalized_mode = _normalize_booking_mode(booking_mode)
        if allowed_modes and (not normalized_mode or normalized_mode not in allowed_modes):
            return _fail(
                400,
                "mode_ineligible",
                "Ce code promo n'est pas compatible avec ce mode de réservation.",
            )

    # Minimum order amount check (V3.2)
    if promo.minimum_commande is not None and parsed_amount is not None:
        if parsed_amount < promo.minimum_commande:
            min_val = promo.minimum_commande
            min_str = f"{int(min_val)}" if min_val == int(min_val) else f"{min_val:.2f}"
            return _fail(
                400,
                "minimum_order_not_met",
                f"Ce code promo requiert un montant minimum de commande de {min_str} MAD.",
                minimum_commande=float(min_val),
            )

    # Target client check for BD promo codes
    if promo.promo_type == 'bd':
        if client is not None:
            if not promo.matches_client(client):
                status_display = promo.customer_status.lower()
                return _fail(
                    400,
                    "target_ineligible",
                    f"Ce code promo est réservé aux cibles ({status_display}).",
                )
        else:
            if not phone:
                return _fail(
                    400,
                    "phone_required",
                    "Veuillez renseigner votre téléphone pour appliquer ce code.",
                )
            is_valid_target, target_msg = promo.matches_phone(phone)
            if not is_valid_target:
                return _fail(400, "target_ineligible", target_msg)

    # Usage limit validation
    if promo.limit_uses is not None and promo.uses >= promo.limit_uses:
        return _fail(
            400,
            "limit_reached",
            "Ce code promo a atteint sa limite d'utilisation.",
        )

    # One use per client check
    if promo.one_use_per_client:
        target_client = client
        if target_client is None and phone:
            from clients.models import Client
            phone_clean = phone.strip()
            phone_no_spaces = phone_clean.replace(" ", "")
            target_client = Client.objects.filter(
                phone=phone_clean, is_archived=False
            ).order_by('-created_at').first()
            if not target_client:
                target_client = Client.objects.filter(
                    phone=phone_no_spaces, is_archived=False
                ).order_by('-created_at').first()

        if target_client and target_client.demandes.filter(promo_code=promo).exists():
            return _fail(
                400,
                "already_used",
                "Vous avez déjà utilisé ce code promo.",
            )

    payload = {
        "valid": True,
        "id": promo.id,
        "code": promo.code,
        "name": promo.name,
        "reduction": float(promo.reduction),
        "reduction_type": promo.reduction_type,
        "promo_type": promo.promo_type,
        "plafond_reduction": float(promo.plafond_reduction) if promo.plafond_reduction is not None else None,
        "minimum_commande": float(promo.minimum_commande) if promo.minimum_commande is not None else None,
        "cumulable": bool(promo.cumulable),
        "message": "Code promo valide !",
    }
    return {
        "valid": True,
        "status_code": 200,
        "reason_code": None,
        "message": payload["message"],
        "promo": promo,
        "payload": payload,
    }
