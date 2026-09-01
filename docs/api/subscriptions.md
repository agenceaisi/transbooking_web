# API — App `subscriptions`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Gestion des forfaits vendus aux compagnies (super admin) et consultation du forfait courant
et des factures par le company admin.

- `SubscriptionPlan` : nom, prix (FCFA), `duration_months` (1 = mensuel, 12 = annuel),
  `features` (JSON libre : limites et avantages), `is_active`.
- `Subscription` : compagnie + forfait + période (`start_date` → `end_date`) + `status`
  (`active · expired · cancelled`) + `auto_renew`.
- `SubscriptionInvoice` : une facture par cycle facturé (`paid_at = null` → en attente).

**Règle métier** : une compagnie dont l'abonnement est expiré est traitée comme suspendue —
`403` sur toutes les routes `company_admin`. Les routes de facturation
(`/api/v1/company/subscription/…`) restent accessibles pour qu'elle puisse se remettre en
règle. Une compagnie n'ayant jamais souscrit n'est pas bloquée.

---

## Super admin — forfaits (`IsSuperAdmin`)

### GET `/api/v1/super/subscription-plans/`

Liste paginée des forfaits. Filtres : `is_active` (bool), `duration_months` (int).

```bash
curl "https://api.transbooking.bf/api/v1/super/subscription-plans/?is_active=true" \
  -H "Authorization: Bearer <token>"
```

Réponse `200` :

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Premium",
      "description": "Forfait annuel toutes options",
      "price": "750000.00",
      "duration_months": 12,
      "features": { "max_vehicles": 50, "max_agents": 100, "support": "prioritaire" },
      "is_active": true,
      "created_at": "2026-07-21T10:00:00Z"
    }
  ]
}
```

### POST `/api/v1/super/subscription-plans/`

| Champ | Type | Obligatoire | Description |
|-------|------|-------------|-------------|
| `name` | string (100) | oui | Nom unique du forfait |
| `price` | decimal | non (défaut 0) | Prix en FCFA, ≥ 0 |
| `duration_months` | int | non (défaut 1) | Durée de validité, ≥ 1 |
| `description` | string | non | Descriptif commercial |
| `features` | object | non | Avantages / limites |
| `is_active` | bool | non (défaut true) | Proposable à la souscription |

Réponse `201` : l'objet forfait. Erreurs : `400` (nom déjà pris, `duration_months` < 1,
prix négatif), `401`, `403`.

### PATCH `/api/v1/super/subscription-plans/{id}/`

Mise à jour partielle. Réponse `200`.

### DELETE `/api/v1/super/subscription-plans/{id}/`

Réponse `204`. **`400`** si le forfait est déjà souscrit par au moins un abonnement
(`{"detail": "Ce forfait est utilisé par des abonnements existants : désactivez-le…"}`) :
utiliser `PATCH {"is_active": false}`.

---

## Super admin — abonnements (`IsSuperAdmin`)

### GET `/api/v1/super/subscriptions/`

Liste paginée. Filtres : `company`, `plan`, `status`, `auto_renew`.

Chaque élément contient le forfait imbriqué et les champs calculés `days_remaining`,
`is_current`, `renewal_date` (= `end_date`).

### POST `/api/v1/super/subscriptions/`

Attribue un forfait à une compagnie et émet la facture du cycle.

| Champ | Type | Obligatoire | Description |
|-------|------|-------------|-------------|
| `company` | int | oui | ID de la compagnie |
| `plan` | int | oui | ID du forfait (doit être `is_active`) |
| `start_date` | date | non | Défaut : aujourd'hui |
| `end_date` | date | non | Défaut : `start_date` + `duration_months` |
| `auto_renew` | bool | non (défaut false) | Renouvellement automatique à l'échéance |

```bash
curl -X POST https://api.transbooking.bf/api/v1/super/subscriptions/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"company": 3, "plan": 1, "auto_renew": true}'
```

Réponse `201` :

```json
{
  "id": 7,
  "company": 3,
  "company_name": "Transport Sahel",
  "plan": { "id": 1, "name": "Premium", "price": "750000.00", "duration_months": 12 },
  "start_date": "2026-07-21",
  "end_date": "2027-07-21",
  "status": "active",
  "status_display": "Actif",
  "auto_renew": true,
  "created_at": "2026-07-21T10:00:00Z",
  "days_remaining": 365,
  "is_current": true,
  "renewal_date": "2027-07-21"
}
```

Erreurs : `400` (`company` déjà couverte par un abonnement en cours, forfait inactif,
`end_date` < `start_date`), `401`, `403`.

### PATCH `/api/v1/super/subscriptions/{id}/`

Active / désactive / prolonge : champs acceptés `plan`, `start_date`, `end_date`,
`status` (`active · expired · cancelled`), `auto_renew`. Réponse `200` (objet complet en
lecture). Erreur `400` si `end_date` < `start_date`.

### POST `/api/v1/super/subscriptions/{id}/renew/`

Prolonge d'une durée de forfait à partir de la borne la plus tardive (`end_date` ou
aujourd'hui), repasse le statut à `active`, réarme le rappel d'expiration et émet une
nouvelle facture. Corps vide. Réponse `200` : l'abonnement renouvelé.

---

## Company admin — facturation (`company_admin`, routes accessibles même si suspendu)

### GET `/api/v1/company/subscription/`

Forfait courant de la compagnie de l'admin connecté : plan, échéance (`renewal_date`),
statut et `days_remaining`. Si aucun abonnement n'est valide, renvoie le **dernier connu**
avec `is_current: false` (permet au front d'afficher « expiré le … »).

Réponse `200` : même structure que ci-dessus.
Erreurs : `401`, `403` (rôle ≠ company_admin), `404` (aucune compagnie ou aucun abonnement).

### GET `/api/v1/company/subscription/invoices/`

Liste paginée des factures de la compagnie (les plus récentes d'abord).

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 14,
      "reference": "FACT-2026-000014",
      "subscription": 7,
      "plan_name": "Premium",
      "amount": "750000.00",
      "paid_at": null,
      "created_at": "2026-07-21T10:00:00Z",
      "is_paid": false,
      "download_url": "/api/v1/company/subscription/invoices/14/download/"
    }
  ]
}
```

### GET `/api/v1/company/subscription/invoices/{id}/download/`

Renvoie le PDF de la facture (`Content-Type: application/pdf`,
`Content-Disposition: attachment; filename="FACT-2026-000014.pdf"`). Le fichier stocké est
servi s'il existe, sinon le PDF est généré à la volée.

Erreurs : `401`, `403`, `404` (facture inexistante **ou appartenant à une autre compagnie**
— isolation multi-tenant stricte).

---

## Tâche Celery associée

`subscriptions.tasks.check_expiring_subscriptions` (quotidienne) : rappel SMS + in-app 7
jours avant l'échéance (idempotent via `expiry_reminder_sent`), puis à l'expiration →
renouvellement si `auto_renew`, sinon `status=expired` et suspension de la compagnie.
