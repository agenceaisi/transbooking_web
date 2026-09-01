from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from utils.models import TimeStampedModel
from utils.validators import validate_phone_bf


class Role(TimeStampedModel):
    class RoleName(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super admin"
        COMPANY_ADMIN = "company_admin", "Company admin"
        AGENT_GUICHET = "agent_guichet", "Agent guichet"
        CONTROLEUR = "controleur", "Controleur"
        VOYAGEUR = "voyageur", "Voyageur"

    name = models.CharField(max_length=50, choices=RoleName.choices, unique=True)

    def __str__(self) -> str:
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra_fields):
        if not phone:
            raise ValueError("Le numero de telephone est obligatoire.")

        user = self.model(phone=self.normalize_phone(phone), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Le superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Le superutilisateur doit avoir is_superuser=True.")

        return self.create_user(phone, password, **extra_fields)

    def normalize_phone(self, phone: str) -> str:
        return phone.strip()


class User(TimeStampedModel, AbstractBaseUser, PermissionsMixin):
    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=30, unique=True, validators=[validate_phone_bf])
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Preferences de notification du voyageur (ecran « Mon profil »). Les
    # alertes de depart et les confirmations de paiement/colis restent
    # toujours envoyees independamment de ces reglages (cf. CLAUDE.md).
    notify_departure_reminder = models.BooleanField(default=True)
    notify_parcel_arrival = models.BooleanField(default=True)
    notify_marketing = models.BooleanField(default=False)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = ["prenom", "nom"]

    objects = UserManager()

    def __str__(self) -> str:
        return self.phone


class AgentProfile(TimeStampedModel):
    class AgentType(models.TextChoices):
        GUICHET = "guichet", "Guichet"
        CONTROLEUR = "controleur", "Controleur"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="agent_profile",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="agent_profiles",
        null=True,
        blank=True,
    )
    agent_type = models.CharField(max_length=20, choices=AgentType.choices)
    station = models.ForeignKey(
        "geography.Station",
        on_delete=models.SET_NULL,
        related_name="agent_profiles",
        null=True,
        blank=True,
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.SET_NULL,
        related_name="agent_profiles",
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return f"{self.user.phone} - {self.agent_type}"
