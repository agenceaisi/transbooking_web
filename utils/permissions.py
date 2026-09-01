from rest_framework.permissions import BasePermission


class RolePermission(BasePermission):
    role_name = ""

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        role = getattr(user, "role", None)
        return bool(user and user.is_authenticated and role and role.name == self.role_name)


class IsSuperAdmin(RolePermission):
    role_name = "super_admin"


# Statuts de compagnie qui interdisent toute operation de son administrateur.
_BLOCKING_COMPANY_STATUSES = {"suspended", "rejected"}


class IsCompanyAdmin(RolePermission):
    role_name = "company_admin"

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        # Une compagnie suspendue (ou rejetee) ne peut plus operer : son admin
        # est refuse. L'admin sans compagnie reste autorise (la vue renvoie 404).
        company = getattr(request.user, "administered_company", None)
        status = getattr(company, "status", None)
        if status in _BLOCKING_COMPANY_STATUSES:
            return False

        # Abonnement expire => compagnie traitee comme suspendue (cf. PROMPT_SUP A3).
        # Import local : evite une dependance d'import au chargement des apps.
        from apps.subscriptions.services import has_blocking_subscription

        return not has_blocking_subscription(company)


class IsCompanyAdminBilling(RolePermission):
    """Company admin, sans controle du statut de la compagnie ni de l'abonnement.

    Reservee aux routes de facturation (`company/subscription/...`) : une
    compagnie suspendue ou dont l'abonnement a expire doit pouvoir consulter son
    forfait et ses factures pour se remettre en regle.
    """

    role_name = "company_admin"


class IsAgent(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        role = getattr(getattr(user, "role", None), "name", None)
        return bool(user and user.is_authenticated and role in {"agent_guichet", "controleur"})


class IsAgentGuichet(RolePermission):
    role_name = "agent_guichet"


class IsControleur(RolePermission):
    role_name = "controleur"


class IsVoyageur(RolePermission):
    role_name = "voyageur"
