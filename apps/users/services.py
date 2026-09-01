import secrets
import string

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.services import log_activity
from utils.sms import send_sms

from .models import AgentProfile, Role, User

# Roles qu'un company admin peut attribuer a un agent de sa compagnie.
AGENT_ROLES = {
    Role.RoleName.AGENT_GUICHET: AgentProfile.AgentType.GUICHET,
    Role.RoleName.CONTROLEUR: AgentProfile.AgentType.CONTROLEUR,
}

# Sel de signature des invitations d'agent (lien de creation de compte).
AGENT_INVITE_SALT = "transbooking.agent-invite"


def create_voyageur(data: dict) -> User:
    """Create a traveler account.

    Args:
        data: Validated user registration data.

    Returns:
        Created user with the voyageur role.

    Raises:
        ValidationError: If the phone number is already used.
    """
    phone = data.get("phone", "").strip()
    if User.objects.filter(phone=phone).exists():
        raise ValidationError({"phone": "Ce numero de telephone est deja utilise."})

    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    user = User(
        prenom=data["prenom"],
        nom=data["nom"],
        email=data.get("email") or None,
        phone=phone,
        role=role,
    )
    user.set_password(data["password"])
    user.full_clean(exclude=["password"])
    user.save()
    return user


def change_password(user: User, new_password: str) -> User:
    """Set a new password for an authenticated user.

    The caller is responsible for checking the old password and for running
    Django's password validators (done in ``PasswordChangeSerializer``).

    Args:
        user: The user changing their password.
        new_password: The new plain-text password.

    Returns:
        The updated user.

    Raises:
        ValidationError: If the new password is empty.
    """
    if not new_password:
        raise ValidationError({"new_password": "Le nouveau mot de passe est obligatoire."})

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    return user


def send_temp_password_sms(agent: User) -> str:
    """Generate and send a temporary password to an agent by SMS.

    Args:
        agent: Agent user receiving the temporary password.

    Returns:
        The generated temporary password.

    Raises:
        ValidationError: If the user does not have a phone number.
    """
    if not agent.phone:
        raise ValidationError({"phone": "Le telephone de l'agent est obligatoire."})

    alphabet = string.ascii_letters + string.digits
    temp_password = "".join(secrets.choice(alphabet) for _ in range(8))
    agent.set_password(temp_password)
    agent.save(update_fields=["password", "updated_at"])
    send_sms(agent.phone, f"Votre mot de passe temporaire TransBooking BF: {temp_password}")
    return temp_password


def create_agent(data: dict, company, actor=None) -> User:
    """Create an agent account attached to a company.

    The agent receives a temporary password by SMS; the ``role`` drives the
    matching ``AgentProfile.agent_type`` (cf. PROMPT_SUP A4).

    Args:
        data: Validated payload with ``prenom``, ``nom``, ``phone``, ``role``
            and the optional ``email`` and ``station`` keys.
        company: The company the agent belongs to (isolation multi-tenant).
        actor: The company admin creating the agent (audit trail).

    Returns:
        The created agent user, with its profile.

    Raises:
        ValidationError: If the phone is already used or the role is not an
            agent role.
    """
    phone = (data.get("phone") or "").strip()
    if User.objects.filter(phone=phone).exists():
        raise ValidationError({"phone": "Ce numero de telephone est deja utilise."})

    role_name = data["role"]
    if role_name not in AGENT_ROLES:
        raise ValidationError({"role": "Role d'agent invalide."})

    role, _ = Role.objects.get_or_create(name=role_name)
    with transaction.atomic():
        agent = User(
            prenom=data["prenom"],
            nom=data["nom"],
            email=data.get("email") or None,
            phone=phone,
            role=role,
        )
        agent.set_unusable_password()
        agent.full_clean(exclude=["password"])
        agent.save()
        AgentProfile.objects.create(
            user=agent,
            company=company,
            agent_type=AGENT_ROLES[role_name],
            station=data.get("station"),
        )

    log_activity(
        actor,
        action="agent.create",
        entity_type="user",
        entity_id=agent.id,
        details={"company_id": company.id, "role": role_name},
    )
    # Le mot de passe temporaire est envoye par SMS (jamais renvoye dans l'API).
    send_temp_password_sms(agent)
    return agent


def update_agent(agent: User, data: dict, actor=None) -> User:
    """Update an agent's identity, role or activation state.

    Args:
        agent: The agent user to update.
        data: Validated subset of ``prenom``, ``nom``, ``email``, ``is_active``,
            ``role`` and ``station``.
        actor: The company admin performing the update (audit trail).

    Returns:
        The updated agent.

    Raises:
        ValidationError: If the requested role is not an agent role.
    """
    user_fields = []
    for field in ("prenom", "nom", "email", "is_active"):
        if field in data:
            setattr(agent, field, data[field])
            user_fields.append(field)

    if "role" in data:
        role_name = data["role"]
        if role_name not in AGENT_ROLES:
            raise ValidationError({"role": "Role d'agent invalide."})
        role, _ = Role.objects.get_or_create(name=role_name)
        agent.role = role
        user_fields.append("role")

    with transaction.atomic():
        if user_fields:
            agent.save(update_fields=[*user_fields, "updated_at"])

        profile = agent.agent_profile
        profile_fields = []
        if "role" in data:
            profile.agent_type = AGENT_ROLES[data["role"]]
            profile_fields.append("agent_type")
        if "station" in data:
            profile.station = data["station"]
            profile_fields.append("station")
        if profile_fields:
            profile.save(update_fields=[*profile_fields, "updated_at"])

    # Seuls les changements sensibles sont journalises (activation, role).
    if "is_active" in data or "role" in data:
        log_activity(
            actor,
            action="agent.update",
            entity_type="user",
            entity_id=agent.id,
            details={
                key: data[key] for key in ("is_active", "role") if key in data
            },
        )
    return agent


def agent_activity_count(agent: User) -> int:
    """Count the operational records produced by an agent.

    Used to forbid the deletion of an agent who already worked (only
    deactivation is allowed, cf. PROMPT_SUP A4).

    Args:
        agent: The agent user to inspect.

    Returns:
        The number of bookings, payments, boarding validations and offline
        syncs attached to the agent.
    """
    return (
        agent.agent_bookings.count()
        + agent.collected_payments.count()
        + agent.boarding_validations.count()
        + agent.sync_logs.count()
    )


def delete_agent(agent: User, actor=None) -> None:
    """Delete an agent account that never produced any activity.

    Args:
        agent: The agent user to delete.
        actor: The company admin deleting the agent (audit trail).

    Raises:
        ValidationError: If the agent already has activity (deactivate instead).
    """
    if agent_activity_count(agent) > 0:
        raise ValidationError(
            "Cet agent a de l'activite enregistree : desactivez-le "
            "(is_active=false) au lieu de le supprimer."
        )
    log_activity(
        actor,
        action="agent.delete",
        entity_type="user",
        entity_id=agent.id,
        details={"phone": agent.phone},
    )
    agent.delete()


def build_agent_invitation(data: dict, company) -> dict:
    """Create a signed agent invitation and send its link by SMS.

    No account is created: the token carries the company, the role and the
    phone, and is verified when the agent opens the link to set their password.

    Args:
        data: Validated payload with ``phone``, ``role`` and optional
            ``prenom`` / ``nom``.
        company: The inviting company.

    Returns:
        A dict with the ``phone``, ``role``, ``token``, ``invite_url`` and
        ``expires_in_hours``.

    Raises:
        ValidationError: If the phone already belongs to an account or the role
            is not an agent role.
    """
    phone = (data.get("phone") or "").strip()
    if User.objects.filter(phone=phone).exists():
        raise ValidationError({"phone": "Ce numero de telephone est deja utilise."})

    role_name = data["role"]
    if role_name not in AGENT_ROLES:
        raise ValidationError({"role": "Role d'agent invalide."})

    token = signing.dumps(
        {
            "company_id": company.id,
            "phone": phone,
            "role": role_name,
            "prenom": data.get("prenom", ""),
            "nom": data.get("nom", ""),
        },
        salt=AGENT_INVITE_SALT,
    )
    invite_url = f"{settings.AGENT_INVITE_URL.rstrip('/')}/{token}"
    send_sms(
        phone,
        f"{company.name} vous invite comme agent TransBooking BF. "
        f"Creez votre compte ici : {invite_url} "
        f"(lien valable {settings.AGENT_INVITE_MAX_AGE_HOURS}h).",
    )
    # TODO: exposer POST /api/v1/auth/agent/invitation/{token}/ pour consommer le
    # jeton (verification via signing.loads + AGENT_INVITE_MAX_AGE_HOURS) une fois
    # le parcours front de creation de compte agent specifie.
    return {
        "phone": phone,
        "role": role_name,
        "token": token,
        "invite_url": invite_url,
        "expires_in_hours": settings.AGENT_INVITE_MAX_AGE_HOURS,
    }
