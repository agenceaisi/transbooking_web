from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.geography.models import Station
from utils.validators import validate_phone_bf

from .models import AgentProfile, Role, User
from .services import create_voyageur


class UserRegistrationSerializer(serializers.Serializer):
    prenom = serializers.CharField(max_length=100)
    nom = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=30, validators=[validate_phone_bf])
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)

    def validate_phone(self, value: str) -> str:
        phone = value.strip()
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("Ce numero de telephone est deja utilise.")
        return phone

    def create(self, validated_data: dict) -> User:
        try:
            return create_voyageur(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    """Changement de mot de passe par l'utilisateur authentifie."""

    old_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_old_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Ancien mot de passe incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        # Regles de robustesse Django (longueur, mot de passe courant, non numerique...).
        try:
            validate_password(value, user=self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "Le nouveau mot de passe doit etre different de l'ancien."}
            )
        return attrs


class DetailResponseSerializer(serializers.Serializer):
    """Reponse generique {"detail": "..."} (documentation OpenAPI)."""

    detail = serializers.CharField()


class UserProfileSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    station = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["prenom", "nom", "phone", "email", "role", "company_name", "station"]

    def get_role(self, obj: User) -> str | None:
        return obj.role.name if obj.role_id else None

    def get_company_name(self, obj: User) -> str | None:
        # Agent : compagnie de son profil agent. Company admin : compagnie administree.
        # Voyageur : aucune des deux, toujours null (cf. requetes agent module §5).
        profile = getattr(obj, "agent_profile", None)
        if profile is not None and profile.company_id:
            return profile.company.name
        company = getattr(obj, "administered_company", None)
        return company.name if company else None

    def get_station(self, obj: User) -> dict | None:
        profile = getattr(obj, "agent_profile", None)
        if profile is None or profile.station_id is None:
            return None
        return {"id": profile.station_id, "name": profile.station.name}


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["phone", "email"]

    def validate_phone(self, value: str) -> str:
        phone = value.strip()
        queryset = User.objects.filter(phone=phone)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Ce numero de telephone est deja utilise.")
        return phone


class AgentProfileSerializer(serializers.ModelSerializer):
    user = UserProfileSerializer(read_only=True)
    company_name = serializers.SerializerMethodField()
    station_info = serializers.SerializerMethodField()
    vehicle_info = serializers.SerializerMethodField()

    class Meta:
        model = AgentProfile
        fields = [
            "user",
            "agent_type",
            "company_name",
            "station_info",
            "vehicle_info",
        ]

    def get_company_name(self, obj: AgentProfile) -> str | None:
        return obj.company.name if obj.company_id else None

    def get_station_info(self, obj: AgentProfile) -> dict | None:
        if not obj.station_id:
            return None
        return {
            "id": obj.station_id,
            "name": obj.station.name,
            "city": obj.station.city.name,
        }

    def get_vehicle_info(self, obj: AgentProfile) -> dict | None:
        if not obj.vehicle_id:
            return None
        return {
            "id": obj.vehicle_id,
            "registration": obj.vehicle.registration,
            "total_seats": obj.vehicle.total_seats,
        }


class CompanyAgentSerializer(serializers.ModelSerializer):
    """Agent d'une compagnie vu par son company admin (lecture)."""

    role = serializers.SerializerMethodField()
    agent_type = serializers.CharField(source="agent_profile.agent_type", read_only=True)
    station = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "prenom",
            "nom",
            "phone",
            "email",
            "role",
            "agent_type",
            "station",
            "is_active",
            "created_at",
        ]

    def get_role(self, obj: User) -> str | None:
        return obj.role.name if obj.role_id else None

    def get_station(self, obj: User) -> dict | None:
        profile = getattr(obj, "agent_profile", None)
        if profile is None or profile.station_id is None:
            return None
        return {"id": profile.station_id, "name": profile.station.name}


class CompanyAgentCreateSerializer(serializers.Serializer):
    """Creation d'un agent par le company admin (mot de passe temporaire par SMS)."""

    prenom = serializers.CharField(max_length=100)
    nom = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=30, validators=[validate_phone_bf])
    role = serializers.ChoiceField(
        choices=[Role.RoleName.AGENT_GUICHET, Role.RoleName.CONTROLEUR]
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    station = serializers.PrimaryKeyRelatedField(
        queryset=Station.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate_phone(self, value: str) -> str:
        phone = value.strip()
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("Ce numero de telephone est deja utilise.")
        return phone

    def validate_station(self, station):
        # Isolation multi-tenant : la gare doit appartenir a la compagnie.
        company = self.context.get("company")
        if station is not None and company is not None and station.company_id != company.id:
            raise serializers.ValidationError("Gare inconnue pour cette compagnie.")
        return station


class CompanyAgentUpdateSerializer(serializers.Serializer):
    """Modification / activation / desactivation d'un agent."""

    prenom = serializers.CharField(max_length=100, required=False)
    nom = serializers.CharField(max_length=100, required=False)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    role = serializers.ChoiceField(
        choices=[Role.RoleName.AGENT_GUICHET, Role.RoleName.CONTROLEUR],
        required=False,
    )
    station = serializers.PrimaryKeyRelatedField(
        queryset=Station.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate_station(self, station):
        company = self.context.get("company")
        if station is not None and company is not None and station.company_id != company.id:
            raise serializers.ValidationError("Gare inconnue pour cette compagnie.")
        return station


class CompanyAgentInviteSerializer(serializers.Serializer):
    """Invitation d'un agent par SMS (lien de creation de compte)."""

    phone = serializers.CharField(max_length=30, validators=[validate_phone_bf])
    role = serializers.ChoiceField(
        choices=[Role.RoleName.AGENT_GUICHET, Role.RoleName.CONTROLEUR]
    )
    prenom = serializers.CharField(max_length=100, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_phone(self, value: str) -> str:
        phone = value.strip()
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("Ce numero de telephone est deja utilise.")
        return phone


class CompanyAgentInvitationResponseSerializer(serializers.Serializer):
    """Reponse d'une invitation d'agent (documentation OpenAPI)."""

    detail = serializers.CharField()
    phone = serializers.CharField()
    role = serializers.CharField()
    invite_url = serializers.CharField()
    expires_in_hours = serializers.IntegerField()


class TransBookingTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        data["role"] = self.user.role.name if self.user.role_id else None
        data["prenom"] = self.user.prenom
        return data
