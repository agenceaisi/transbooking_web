# API — App `core` (configuration globale & audit)

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).
**Toutes les routes de cette app sont réservées au `super_admin`** (`IsSuperAdmin`) : tout
autre rôle reçoit `403`, un appel anonyme `401`.

Deux modèles support :
- `GlobalSetting` : table clé/valeur des paramètres plateforme (valeur stockée en texte,
  convertie par `core.services`).
- `ActivityLog` : journal d'audit des actions sensibles (`user = null` → action système).

---

## GET `/api/v1/super/settings/`

Paramètres généraux de la plateforme.

```json
{
  "platform_name": "TransBooking BF",
  "support_phone": "+22670000000",
  "support_email": "support@transbooking.bf",
  "maintenance_mode": false,
  "sms_provider": "console"
}
```

> `sms_provider` est **en lecture seule** (issu des variables d'environnement) et la clé API
> SMS n'est jamais exposée.

## PATCH `/api/v1/super/settings/`

| Champ              | Type   | Obligatoire | Notes                                 |
|--------------------|--------|-------------|---------------------------------------|
| `platform_name`    | string | non         |                                       |
| `support_phone`    | string | non         |                                       |
| `support_email`    | string | non         | doit être un email valide             |
| `maintenance_mode` | bool   | non         | `true` = bandeau maintenance côté front |

```bash
curl -X PATCH https://api.transbooking.bf/api/v1/super/settings/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"maintenance_mode": true}'
```

**200 OK** : payload complet ci-dessus. Erreurs : `400` (email invalide), `401`, `403`.
Journalisé sous l'action `settings.update`.

---

## GET `/api/v1/super/settings/commissions/`

Taux de commission global + surcharges par compagnie (compagnies dont
`commission_rate` n'est pas `null`).

```json
{
  "global_rate": "10.00",
  "company_overrides": [
    { "company_id": 3, "company_name": "Transport Sahel", "commission_rate": "8.00" }
  ]
}
```

## PATCH `/api/v1/super/settings/commissions/`

| Champ                                | Type    | Obligatoire | Notes                                    |
|--------------------------------------|---------|-------------|------------------------------------------|
| `global_rate`                        | decimal | non         | 0 ≤ taux ≤ 100                           |
| `company_overrides[].company_id`     | int     | oui         | compagnie existante, sinon `400`         |
| `company_overrides[].commission_rate`| decimal \| null | oui | `null` = la compagnie repasse au taux global |

```bash
curl -X PATCH https://api.transbooking.bf/api/v1/super/settings/commissions/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"global_rate":"12.50","company_overrides":[{"company_id":3,"commission_rate":"8.00"}]}'
```

**200 OK** : payload rafraîchi. Erreurs : `400` (taux hors bornes, compagnie inconnue),
`401`, `403`.

> Le taux global est consommé par `payments.services.compute_commission()` :
> `commission = booking.amount × taux / 100`, taux propre de la compagnie sinon taux global,
> sinon `COMMISSION_RATE_DEFAULT` (env). Actions journalisées :
> `settings.commission_rate`, `settings.company_commission`.

---

## GET `/api/v1/super/settings/payment-methods/`

Activation des moyens de paiement **au niveau plateforme**. Non paginé.

```json
[
  { "method": "orange_money",  "method_display": "Orange Money",  "is_active": true },
  { "method": "moov_money",    "method_display": "Moov Money",    "is_active": true },
  { "method": "coris_money",   "method_display": "Coris Money",   "is_active": true },
  { "method": "telecel_money", "method_display": "Telecel Money", "is_active": true },
  { "method": "card",          "method_display": "Carte bancaire","is_active": true }
]
```

> `cash` n'apparaît pas : les espèces n'impliquent aucun opérateur externe et restent
> toujours disponibles.

## PATCH `/api/v1/super/settings/payment-methods/`

Corps : `{"payment_methods": [{"method": "card", "is_active": false}]}` (la liste brute est
également acceptée). Seuls les moyens envoyés sont modifiés.

**200 OK** : la configuration complète rafraîchie. Erreurs : `400` (moyen inconnu), `401`,
`403`. Action journalisée : `settings.payment_methods`.

---

## GET `/api/v1/super/activity-logs/`

Journal d'audit paginé, du plus récent au plus ancien.

| Query param   | Type | Notes                                                    |
|---------------|------|----------------------------------------------------------|
| `user`        | int  | ID de l'auteur                                           |
| `action`      | str  | filtre **partiel** insensible à la casse (ex. `company.`)|
| `entity_type` | str  | `company` · `subscription` · `user` · `global_setting`   |
| `entity_id`   | int  | ID de l'objet impacté                                    |
| `date_from`   | date | `YYYY-MM-DD`, borne incluse                              |
| `date_to`     | date | `YYYY-MM-DD`, borne incluse                              |

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 51,
      "user": 1,
      "user_name": "Ali Traore",
      "user_role": "super_admin",
      "action": "company.suspend",
      "entity_type": "company",
      "entity_id": 3,
      "details": { "reason": "Impayes" },
      "ip_address": null,
      "created_at": "2026-07-21T10:00:00Z"
    }
  ]
}
```

`user: null` / `user_name: "Systeme"` = action déclenchée par une tâche Celery
(ex. suspension automatique pour abonnement expiré).

**Actions journalisées** : `company.approve` · `company.reject` · `company.request_info` ·
`company.suspend` · `company.activate` · `subscription.create` · `subscription.renew` ·
`agent.create` · `agent.update` · `agent.delete` · `agent.reset_password` ·
`settings.update` · `settings.commission_rate` · `settings.company_commission` ·
`settings.payment_methods`.

> **TODO** : `ip_address` reste `null` — le service d'audit est appelé depuis les services
> métier, sans accès à la requête. À alimenter via un middleware si l'exigence est confirmée.

---

## GET `/api/v1/super/notifications/`

Fil de supervision **calculé à la volée** (aucune ligne stockée) : ce que l'équipe
plateforme doit traiter. Paginé (`StandardPagination`), trié par date décroissante.

| Query param | Valeurs                                                                              |
|-------------|--------------------------------------------------------------------------------------|
| `type`      | `new_registration` · `subscription_expired` · `urgent_report` · `technical_incident`  |
| `severity`  | `info` · `warning` · `critical`                                                       |

Sources agrégées :

| `type`                 | Source                                                       | `severity` |
|------------------------|--------------------------------------------------------------|------------|
| `new_registration`     | compagnies `pending` / `info_requested`                      | `info`     |
| `subscription_expired` | abonnements `expired` ou `active` avec `end_date` dépassée   | `warning`  |
| `urgent_report`        | signalements d'excès de vitesse `pending`, réclamations `escalated` | `critical` |
| `technical_incident`   | synchronisations hors ligne en `error`                       | `warning`  |

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "type": "subscription_expired",
      "severity": "warning",
      "title": "Abonnement expire",
      "body": "L'abonnement de Transport Sahel a expire le 20/07/2026.",
      "reference_type": "subscription",
      "reference_id": 7,
      "created_at": "2026-07-20T23:00:00Z"
    }
  ]
}
```

Erreurs : `401`, `403`.

---

## Service interne — `log_activity()`

```python
from apps.core.services import log_activity

log_activity(
    request.user,              # None => action systeme
    action="company.suspend",
    entity_type="company",
    entity_id=company.id,
    details={"reason": reason},
)
```

À appeler depuis les services métier pour toute action sensible. **Ne jamais y stocker** de
mot de passe, code OTP ou référence de transaction complète.
