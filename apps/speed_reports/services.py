from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import SpeedReport, SpeedReportStatus


def create_speed_report(validated_data: dict, user) -> SpeedReport:
    """Create a speed report, auto-stamping the time and resolving the company.

    Args:
        validated_data: Cleaned fields. Recognised keys: ``company`` (optional
            if ``trip`` is given), ``trip``, ``estimated_speed``, ``severity``,
            ``description``, ``latitude``, ``longitude``, ``reported_at``.
        user: The traveller filing the report.

    Returns:
        The created speed report.

    Raises:
        ValidationError: If neither a company nor a trip is provided.
    """
    trip = validated_data.get("trip")
    company = validated_data.get("company")
    if trip is not None:
        company = trip.route.company
    elif company is None:
        raise ValidationError(
            {"company": "La compagnie ou un voyage est obligatoire."}
        )

    return SpeedReport.objects.create(
        company=company,
        user=user,
        trip=trip,
        estimated_speed=validated_data.get("estimated_speed"),
        severity=validated_data.get("severity"),
        description=validated_data.get("description", ""),
        latitude=validated_data.get("latitude"),
        longitude=validated_data.get("longitude"),
        reported_at=validated_data.get("reported_at") or timezone.now(),
    )


def update_status(report: SpeedReport, new_status: str) -> SpeedReport:
    """Update the status of a speed report (super admin action).

    Args:
        report: The report to update.
        new_status: The target status (a ``SpeedReportStatus`` value).

    Returns:
        The updated report.

    Raises:
        ValidationError: If ``new_status`` is not a known status.
    """
    if new_status not in SpeedReportStatus.values:
        raise ValidationError({"status": "Statut de signalement invalide."})
    report.status = new_status
    report.save(update_fields=["status", "updated_at"])
    return report
