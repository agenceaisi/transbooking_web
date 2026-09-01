from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.routes.models import Route
from utils.qr import generate_qr
from utils.sms import send_sms

from .models import NotificationMethod, Parcel, ParcelNotification, ParcelStatus

# Bornes des tranches de distance (km) pour la grille tarifaire colis.
TIER_SHORT_MAX = Decimal("100")
TIER_MEDIUM_MAX = Decimal("300")


def _resolve_distance_km(origin_city_id: int, dest_city_id: int, company) -> Decimal:
    """Return the route distance between two cities for a company.

    Args:
        origin_city_id: Departure city primary key.
        dest_city_id: Destination city primary key.
        company: The carrier company owning the route.

    Returns:
        The distance in kilometres of the matching active route.

    Raises:
        ValidationError: If the company has no route between the two cities.
    """
    distance = (
        Route.objects.filter(
            company=company,
            origin_city_id=origin_city_id,
            destination_city_id=dest_city_id,
        )
        .order_by("-is_active")
        .values_list("distance_km", flat=True)
        .first()
    )
    if distance is None:
        raise ValidationError(
            "Aucun trajet de la compagnie ne relie ces deux villes."
        )
    return Decimal(distance)


def calculate_tariff(weight_kg, origin_city_id: int, dest_city_id: int, company) -> Decimal:
    """Compute the transport tariff of a parcel (cf. business_rules.md §3).

    The price is ``weight_kg x price_per_kg + fixed_fee`` where the per-kg price
    and fixed fee come from the company's ``parcel_pricing_config`` for the
    distance tier of the route (short < 100 km, medium <= 300 km, long > 300 km).

    Args:
        weight_kg: Parcel weight in kilograms.
        origin_city_id: Departure city primary key.
        dest_city_id: Destination city primary key.
        company: The carrier company (holds the pricing grid).

    Returns:
        The total tariff in FCFA, rounded to the nearest unit.

    Raises:
        ValidationError: If no route links the cities or the pricing config is
            incomplete.
    """
    distance_km = _resolve_distance_km(origin_city_id, dest_city_id, company)
    config = company.parcel_pricing_config or {}

    if distance_km < TIER_SHORT_MAX:
        tier = config.get("tier_short")
    elif distance_km <= TIER_MEDIUM_MAX:
        tier = config.get("tier_medium")
    else:
        tier = config.get("tier_long")

    if not tier or "price_per_kg" not in tier or "fixed_fee" not in tier:
        raise ValidationError("Grille tarifaire colis incomplete pour cette compagnie.")

    price_per_kg = Decimal(str(tier["price_per_kg"]))
    fixed_fee = Decimal(str(tier["fixed_fee"]))
    total = Decimal(str(weight_kg)) * price_per_kg + fixed_fee
    return total.quantize(Decimal("1"))


def estimate_price_range(
    weight_kg, origin_city_id: int, dest_city_id: int
) -> dict | None:
    """Estimate what a parcel would cost, across every company serving the axis.

    La grille tarifaire est propre a chaque compagnie (``parcel_pricing_config``) :
    il n'existe pas de tarif national unique. Cette fonction repond donc a la
    question du voyageur avant qu'il ait choisi de compagnie, en bornant le prix
    reel qu'il paiera plutot qu'en inventant un chiffre moyen.

    Args:
        weight_kg: Parcel weight in kilograms.
        origin_city_id: Departure city primary key.
        dest_city_id: Destination city primary key.

    Returns:
        ``{"min": Decimal, "max": Decimal, "companies_count": int}``, or
        ``None`` when no active company operates a route between the two
        cities.
    """
    from apps.companies.models import Company, CompanyStatus

    companies = Company.objects.filter(
        status=CompanyStatus.ACTIVE,
        routes__origin_city_id=origin_city_id,
        routes__destination_city_id=dest_city_id,
        routes__is_active=True,
    ).distinct()

    tarifs = []
    for company in companies:
        try:
            tarifs.append(
                calculate_tariff(weight_kg, origin_city_id, dest_city_id, company)
            )
        except ValidationError:
            continue

    if not tarifs:
        return None
    return {"min": min(tarifs), "max": max(tarifs), "companies_count": len(tarifs)}


def generate_tracking_number() -> str:
    """Build the next tracking number: ``COL`` + year + 6-digit sequence.

    The sequence is scoped to the current calendar year (e.g. ``COL2026000456``).

    Returns:
        The next available tracking number for the current year.
    """
    prefix = f"COL{timezone.now().year}"
    last = (
        Parcel.objects.filter(tracking_number__startswith=prefix)
        .aggregate(last=Max("tracking_number"))
        .get("last")
    )
    sequence = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{sequence:06d}"


def register_parcel(validated_data: dict, agent=None) -> Parcel:
    """Register a parcel, computing its tariff and a tracking number.

    Auto-generates the tracking number and QR code, computes the tariff from the
    company pricing grid, and sends a registration SMS to the recipient (skipped
    for offline entries until they are synced).

    Args:
        validated_data: Cleaned fields. Recognised keys: ``company``,
            ``origin_city``, ``destination_city``, ``origin_station``,
            ``destination_station``, ``sender_name``, ``sender_phone``,
            ``recipient_name``, ``recipient_phone``, ``description``,
            ``weight_kg``, ``trip`` (optional), ``is_offline``,
            ``offline_created_at``, ``tracking_number`` (offline).
        agent: The agent user registering the parcel, or ``None`` online.

    Returns:
        The created parcel.

    Raises:
        ValidationError: If no route links the cities (tariff cannot be priced).
    """
    company = validated_data["company"]
    origin_city = validated_data["origin_city"]
    destination_city = validated_data["destination_city"]
    is_offline = validated_data.get("is_offline", False)

    tariff = calculate_tariff(
        validated_data["weight_kg"],
        origin_city.id if hasattr(origin_city, "id") else origin_city,
        destination_city.id if hasattr(destination_city, "id") else destination_city,
        company,
    )

    with transaction.atomic():
        tracking_number = (
            validated_data.get("tracking_number") or generate_tracking_number()
        )
        parcel = Parcel.objects.create(
            company=company,
            trip=validated_data.get("trip"),
            origin_city=origin_city,
            destination_city=destination_city,
            origin_station=validated_data.get("origin_station"),
            destination_station=validated_data.get("destination_station"),
            sender_name=validated_data["sender_name"],
            sender_phone=validated_data["sender_phone"],
            recipient_name=validated_data["recipient_name"],
            recipient_phone=validated_data["recipient_phone"],
            description=validated_data.get("description", ""),
            weight_kg=validated_data["weight_kg"],
            tariff=tariff,
            tracking_number=tracking_number,
            qr_code=generate_qr(tracking_number),
            status=ParcelStatus.REGISTERED,
            registered_by=agent,
            is_offline=is_offline,
            offline_created_at=validated_data.get("offline_created_at"),
            synced_at=None if is_offline else timezone.now(),
        )

    # Le SMS d'enregistrement n'est pas une ParcelNotification : il ne consomme
    # pas la regle anti-doublon reservee au SMS d'arrivee (notify_recipient).
    # Envoye de maniere asynchrone (cf. parcels.tasks.send_parcel_dispatch_sms).
    if not is_offline:
        from .tasks import send_parcel_dispatch_sms

        send_parcel_dispatch_sms.delay(parcel.pk)
    return parcel


def notify_recipient(
    parcel: Parcel,
    agent=None,
    method: str = NotificationMethod.SMS,
    force: bool = False,
) -> ParcelNotification:
    """Notify the parcel recipient by SMS or record a manual call.

    Sending an SMS sets the parcel status to ``notified``. A second SMS is
    blocked unless ``force`` is set (cf. business_rules.md §3 « renvoyer SMS »).

    Args:
        parcel: The parcel whose recipient must be notified.
        agent: The agent (or admin) triggering the notification.
        method: ``sms`` to text the recipient, ``call`` to log a manual call.
        force: Bypass the duplicate-SMS guard (used by « notifier a nouveau »).

    Returns:
        The created notification record.

    Raises:
        ValidationError: If an SMS was already sent and ``force`` is False.
    """
    if method == NotificationMethod.SMS and not force:
        already_sent = ParcelNotification.objects.filter(
            parcel=parcel, method=NotificationMethod.SMS
        ).exists()
        if already_sent:
            raise ValidationError("Un SMS a deja ete envoye pour ce colis.")

    if method == NotificationMethod.SMS:
        message = (
            f"Votre colis {parcel.tracking_number} est arrive a "
            f"{parcel.destination_city.name}. Veuillez venir le retirer."
        )
        send_sms(parcel.recipient_phone, message)
    else:
        message = "Destinataire prevenu par appel manuel."

    notification = ParcelNotification.objects.create(
        parcel=parcel,
        method=method,
        message=message,
        sent_by=agent,
    )

    if parcel.status != ParcelStatus.COLLECTED:
        parcel.status = ParcelStatus.NOTIFIED
        parcel.save(update_fields=["status", "updated_at"])

    return notification


def update_status(parcel: Parcel, new_status: str) -> Parcel:
    """Set a parcel status, stamping the collection time when relevant.

    Args:
        parcel: The parcel to update.
        new_status: The target status (a ``ParcelStatus`` value).

    Returns:
        The updated parcel.

    Raises:
        ValidationError: If ``new_status`` is not a known parcel status.
    """
    if new_status not in ParcelStatus.values:
        raise ValidationError({"status": "Statut de colis invalide."})

    parcel.status = new_status
    update_fields = ["status", "updated_at"]
    if new_status == ParcelStatus.COLLECTED and parcel.collected_at is None:
        parcel.collected_at = timezone.now()
        update_fields.append("collected_at")
    parcel.save(update_fields=update_fields)

    # A l'arrivee, le destinataire est prevenu par SMS (asynchrone, idempotent).
    if new_status == ParcelStatus.ARRIVED:
        from .tasks import send_parcel_arrival_sms

        send_parcel_arrival_sms.delay(parcel.pk)
    return parcel


def build_tracking_history(parcel: Parcel) -> list[dict]:
    """Build the public tracking timeline of a parcel from its known events.

    Faute d'une table d'historique dediee, la chronologie est reconstruite a
    partir des seuls evenements horodates dont on dispose : l'enregistrement, les
    notifications au destinataire et la remise. Le front derive les etapes
    manquantes (en transit, arrive) a partir du statut courant quand la liste est
    incomplete.

    Args:
        parcel: The parcel whose events are aggregated. Its ``notifications``
            should be prefetched to avoid extra queries.

    Returns:
        A list of dicts sorted by ``timestamp``, each matching
        ``ParcelHistoryEntrySerializer`` (``status``, ``status_display``,
        ``location``, ``timestamp``, ``note``).
    """
    labels = dict(ParcelStatus.choices)
    origin = parcel.origin_city.name if parcel.origin_city_id else None
    destination = parcel.destination_city.name if parcel.destination_city_id else None

    entries = [
        {
            "status": ParcelStatus.REGISTERED,
            "status_display": labels[ParcelStatus.REGISTERED],
            "location": origin,
            "timestamp": parcel.created_at,
            "note": "Colis enregistre au depot.",
        }
    ]

    # Chaque notification au destinataire marque l'etape « prevenu ».
    for notification in parcel.notifications.all():
        entries.append(
            {
                "status": ParcelStatus.NOTIFIED,
                "status_display": labels[ParcelStatus.NOTIFIED],
                "location": destination,
                "timestamp": notification.created_at,
                "note": notification.message or notification.get_method_display(),
            }
        )

    if parcel.collected_at:
        entries.append(
            {
                "status": ParcelStatus.COLLECTED,
                "status_display": labels[ParcelStatus.COLLECTED],
                "location": destination,
                "timestamp": parcel.collected_at,
                "note": None,
            }
        )

    return sorted(entries, key=lambda entry: entry["timestamp"])
