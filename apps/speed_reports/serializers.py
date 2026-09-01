from rest_framework import serializers

from apps.companies.models import Company
from apps.trips.models import Trip

from .models import SpeedReport, SpeedReportStatus


class SpeedReportReadSerializer(serializers.ModelSerializer):
    """Lecture d'un signalement (admin compagnie, super admin)."""

    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    severity_display = serializers.CharField(
        source="get_severity_display", read_only=True, default=None
    )
    company_name = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = SpeedReport
        fields = [
            "id",
            "company",
            "company_name",
            "trip",
            "estimated_speed",
            "severity",
            "severity_display",
            "description",
            "latitude",
            "longitude",
            "reported_at",
            "status",
            "status_display",
            "created_at",
        ]


class SpeedReportCreateSerializer(serializers.ModelSerializer):
    """Depot d'un signalement par un voyageur (horodatage auto, GPS optionnel)."""

    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(), required=False
    )
    trip = serializers.PrimaryKeyRelatedField(
        queryset=Trip.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = SpeedReport
        fields = [
            "company",
            "trip",
            "estimated_speed",
            "severity",
            "description",
            "latitude",
            "longitude",
            "reported_at",
        ]
        extra_kwargs = {"reported_at": {"required": False}}


class SpeedReportStatusSerializer(serializers.Serializer):
    """Changement de statut d'un signalement (super admin)."""

    status = serializers.ChoiceField(choices=SpeedReportStatus.choices)
