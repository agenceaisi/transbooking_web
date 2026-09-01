from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from utils.permissions import IsCompanyAdmin

from .models import Vehicle
from .serializers import SeatPlanSerializer, VehicleSerializer
from .services import set_active, set_maintenance


class VehicleViewSet(viewsets.ModelViewSet):
    """CRUD des vehicules de la compagnie du company admin courant."""

    serializer_class = VehicleSerializer
    permission_classes = [IsCompanyAdmin]
    filterset_fields = ["status", "vehicle_type"]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company

    def get_queryset(self):
        return Vehicle.objects.filter(company=self.get_company())

    def perform_create(self, serializer):
        serializer.save(company=self.get_company())

    @action(detail=True, methods=["post"])
    def maintenance(self, request, pk=None):
        vehicle = self.get_object()
        set_maintenance(vehicle)
        return Response(VehicleSerializer(vehicle).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        vehicle = self.get_object()
        set_active(vehicle)
        return Response(VehicleSerializer(vehicle).data)

    @action(detail=True, methods=["get", "put"], url_path="seat-plan")
    def seat_plan(self, request, pk=None):
        vehicle = self.get_object()
        if request.method == "GET":
            return Response(vehicle.seat_plan or {})

        serializer = SeatPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vehicle.seat_plan = serializer.validated_data
        vehicle.save(update_fields=["seat_plan", "updated_at"])
        return Response(vehicle.seat_plan, status=status.HTTP_200_OK)
