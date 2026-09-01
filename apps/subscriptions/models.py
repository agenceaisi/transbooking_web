from django.db import models

from utils.models import TimeStampedModel


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Actif"
    EXPIRED = "expired", "Expire"
    CANCELLED = "cancelled", "Annule"


class SubscriptionPlan(TimeStampedModel):
    """Forfait d'abonnement propose aux compagnies par le super admin.

    Definit le prix et la duree (en mois) ainsi que la liste d'avantages
    inclus (`features`, flexible). Un abonnement (`Subscription`) rattache une
    compagnie a un forfait (cf. mcd.md §3).
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Duree de validite du forfait en mois (1 = mensuel, 12 = annuel).
    duration_months = models.PositiveIntegerField(default=1)
    # Avantages inclus, stockes en JSON pour rester flexibles
    # (ex: {"max_vehicles": 10, "max_agents": 20, "support": "prioritaire"}).
    features = models.JSONField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["price"]
        verbose_name = "Forfait"
        verbose_name_plural = "Forfaits"

    def __str__(self) -> str:
        return self.name


class Subscription(TimeStampedModel):
    """Abonnement d'une compagnie a un forfait.

    Une compagnie peut avoir plusieurs abonnements dans le temps (historique,
    cf. mcd.md §3) ; l'abonnement courant est celui de statut `active`. La tache
    `subscriptions.tasks.check_expiring_subscriptions` previent la compagnie 7
    jours avant `end_date`, puis renouvelle (si `auto_renew`) ou suspend la
    compagnie a l'expiration (cf. PROMPT 12).
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE,
    )
    auto_renew = models.BooleanField(default=False)
    # Garde-fou d'idempotence : le SMS « expire dans 7 jours » n'est envoye
    # qu'une fois par cycle (remis a False a chaque renouvellement).
    expiry_reminder_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["end_date"]
        verbose_name = "Abonnement"
        verbose_name_plural = "Abonnements"
        indexes = [
            models.Index(fields=["status", "end_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.company.name} - {self.plan.name}"


class SubscriptionInvoice(TimeStampedModel):
    """Facture emise pour un cycle d'abonnement d'une compagnie.

    `paid_at` NULL = facture en attente de reglement. Le PDF est genere puis
    stocke (`pdf`) et transmis a la compagnie (cf. mcd.md §3).
    """

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # NULL = en attente ; renseigne a la confirmation du paiement.
    paid_at = models.DateTimeField(null=True, blank=True)
    pdf = models.FileField(upload_to="subscriptions/invoices/", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Facture d'abonnement"
        verbose_name_plural = "Factures d'abonnement"

    def __str__(self) -> str:
        return f"Facture {self.pk} - {self.subscription.company.name}"
