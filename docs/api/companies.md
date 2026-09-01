# API — App `companies`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Isolation multi-tenant stricte : un `company_admin` n'accède qu'à **sa propre** compagnie
(résolue via `request.user.administered_company`). Toute tentative d'accès sans compagnie
associée renvoie `404`.

---

## Super admin — `IsSuperAdmin`

### GET `/api/v1/super/companies/`

Liste toutes les compagnies. Filtres : `?status=`, `?city=`, `?created_after=YYYY-MM-DD`,
`?created_before=YYYY-MM-DD`. Pagination `?page=` / `?page_size=`.

```bash
curl "https://api.transbooking.bf/api/v1/super/companies/?status=active" \
  -H "Authorization: Bearer <access>"
```

**200 OK** — liste paginée de compagnies (cf. `CompanyDetailSerializer`).
Erreurs : `401` (non authentifié), `403` (pas super admin).

### POST `/api/v1/super/companies/`

Crée une compagnie (active immédiatement).

| Champ              | Type    | Obligatoire | Notes                       |
|--------------------|---------|-------------|-----------------------------|
| `name`             | string  | oui         | unique                      |
| `sigle`            | string  | non         |                             |
| `description`      | string  | non         |                             |
| `city`             | string  | non         |                             |
| `address`          | string  | non         |                             |
| `phone`            | string  | non         |                             |
| `email`            | string  | non         |                             |
| `responsible_name` | string  | non         |                             |
| `responsible_phone`| string  | non         | format BF                   |
| `rccm`             | string  | non         |                             |
| `ifu`              | string  | non         |                             |
| `commission_rate`  | decimal | non         | NULL → taux global appliqué |

```bash
curl -X POST https://api.transbooking.bf/api/v1/super/companies/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"name":"STAF Voyages","city":"Ouagadougou","commission_rate":"8.50"}'
```

**201 Created** — `{"id": 1, "name": "STAF Voyages", "status": "active", ...}`
Erreurs : `400` (nom déjà pris), `401`, `403`.

### GET / PATCH / DELETE `/api/v1/super/companies/{id}/`

Détail, modification partielle, suppression d'une compagnie.
Erreurs : `401`, `403`, `404`.

### POST `/api/v1/super/companies/{id}/activate/`

Réactive une compagnie suspendue (ou en attente). Envoie un SMS au responsable.

**200 OK** — compagnie avec `status: "active"`.
Erreurs : `400` (déjà active), `401`, `403`, `404`.

### POST `/api/v1/super/companies/{id}/suspend/`

Suspend une compagnie. Notifie le responsable par SMS.

| Champ    | Type   | Obligatoire |
|----------|--------|-------------|
| `reason` | string | oui         |

```bash
curl -X POST https://api.transbooking.bf/api/v1/super/companies/1/suspend/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"reason":"Abonnement impayé"}'
```

**200 OK** — compagnie avec `status: "suspended"`.
Erreurs : `400` (motif manquant), `401`, `403`, `404`.

### GET `/api/v1/super/company-requests/`

Liste les demandes de création **en cours d'instruction**, c'est-à-dire aux statuts
`pending` **et** `info_requested`. Une demande quitte la file uniquement quand elle est
approuvée (`active`) ou rejetée (`rejected`).

**200 OK** — liste paginée. Erreurs : `401`, `403`.

> Toutes les actions ci-dessous renvoient `404` si la demande n'est plus dans la file
> (compagnie déjà approuvée, rejetée ou suspendue) — elle sort du queryset.

### POST `/api/v1/super/company-requests/{id}/request-info/`

Demande des informations ou pièces complémentaires au demandeur. La demande passe au
statut `info_requested`, le message est stocké dans `info_request_message` et **reste dans
la file** du super admin, qui peut ensuite approuver, rejeter, ou redemander des infos.

Notification du demandeur :
- **SMS** au `responsible_phone` (canal principal — une demande n'a pas encore de compte) ;
- **notification in-app** (`type=system`, `reference_type="company"`) uniquement si un
  `admin_user` est déjà rattaché à la compagnie.

| Champ     | Type   | Obligatoire | Notes                          |
|-----------|--------|-------------|--------------------------------|
| `message` | string | oui         | non vide (espaces seuls = 400) |

```bash
curl -X POST https://api.transbooking.bf/api/v1/super/company-requests/1/request-info/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"message":"Merci de fournir le RCCM et l’agrément de transport."}'
```

**200 OK** — compagnie (`CompanyDetailSerializer`) avec :
```json
{"status": "info_requested", "info_request_message": "Merci de fournir le RCCM et l’agrément de transport."}
```

Erreurs : `400` (`{"message": ["Ce champ ne peut être vide."]}`), `401`, `403` (pas super
admin), `404` (demande close).

### POST `/api/v1/super/company-requests/{id}/approve/`

Approuve une demande ouverte (`pending` ou `info_requested`) → `status=active`,
`info_request_message` remis à vide, SMS de bienvenue au responsable.

**200 OK** — compagnie approuvée.
Erreurs : `400` (demande non ouverte), `401`, `403`, `404`.

### POST `/api/v1/super/company-requests/{id}/reject/`

Rejette une demande ouverte (`pending` ou `info_requested`). `reason` obligatoire ;
SMS envoyé au responsable.

| Champ    | Type   | Obligatoire |
|----------|--------|-------------|
| `reason` | string | oui         |

**200 OK** — compagnie avec `status: "rejected"`.
Erreurs : `400` (motif manquant / demande non ouverte), `401`, `403`, `404`.

---

## Company admin — `IsCompanyAdmin`

### GET / PATCH `/api/v1/company/settings/`

Lit / met à jour les paramètres de la compagnie de l'utilisateur courant
(`name`, `sigle`, `description`, `logo`, `banner`, `primary_color`, `welcome_message`,
`address`, `phone`, `email`, `responsible_name`, `responsible_phone`).

```bash
curl -X PATCH https://api.transbooking.bf/api/v1/company/settings/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"primary_color":"#1A73E8","welcome_message":"Bon voyage !"}'
```

**200 OK** — paramètres mis à jour.
Erreurs : `400`, `401`, `403`, `404` (aucune compagnie associée).

### GET / PATCH `/api/v1/company/settings/payment-methods/`

Lit / active-désactive les moyens de paiement. Le PATCH attend une liste
`payment_methods` de `{method, is_active}` (upsert par méthode).

```bash
curl -X PATCH https://api.transbooking.bf/api/v1/company/settings/payment-methods/ \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"payment_methods":[{"method":"orange_money","is_active":true},{"method":"cash","is_active":true}]}'
```

**200 OK** — liste à jour des moyens de paiement.
Méthodes valides : `cash`, `orange_money`, `moov_money`, `coris_money`, `telecel_money`, `card`.
Erreurs : `400`, `401`, `403`, `404`.

### GET / PATCH `/api/v1/company/settings/notifications/`

Lit / met à jour les 3 commutateurs SMS (`sms_booking_confirmation`,
`sms_departure_reminder`, `sms_parcel_arrival`). Créés automatiquement au premier accès.

**200 OK** — `{"sms_booking_confirmation": true, "sms_departure_reminder": true, "sms_parcel_arrival": true}`
Erreurs : `400`, `401`, `403`, `404`.

---

## Public — sans authentification

### GET `/api/v1/public/companies/`

Liste les compagnies **actives** uniquement (page d'accueil). Réponse **mise en cache 1 h**.

```bash
curl https://api.transbooking.bf/api/v1/public/companies/
```

**200 OK** — liste paginée : `{"id", "name", "sigle", "logo", "description", "city", "rating"}`.
`rating` = note moyenne des avis publics (non signalés), annotée par sous-requête ;
`null` si la compagnie n'a aucun avis.

### GET `/api/v1/public/companies/{id}/`

Fiche publique détaillée d'une compagnie active. Ajoute au résumé de liste : `phone`,
`email`, `routes` (trajets desservis), `reviews_count`, `rating_breakdown` et `reviews`.

Champs supplémentaires :

| Champ              | Type   | Nullable | Notes                                              |
|--------------------|--------|----------|----------------------------------------------------|
| `routes`           | array  | non      | trajets **actifs** (`company.routes` `is_active`)  |
| `reviews_count`    | int    | non      | total des avis publics (non signalés)              |
| `rating_breakdown` | object | non      | répartition `{"1".."5": n}` des notes              |
| `reviews`          | array  | non      | toujours `[]` — chargés via `GET /reviews/?company_id=` (paginé) |

Chaque entrée `routes` : `{ "id", "origin_city_name", "destination_city_name",
"base_price", "duration_minutes" }` (`duration_minutes` nullable).

```json
{
  "id": 4, "name": "Faso Express", "sigle": "FE", "city": "Ouagadougou",
  "rating": 4.6, "reviews_count": 1248,
  "rating_breakdown": {"5": 812, "4": 289, "3": 91, "2": 34, "1": 22},
  "routes": [
    {
      "id": 12, "origin_city_name": "Ouagadougou",
      "destination_city_name": "Bobo-Dioulasso",
      "base_price": "8500.00", "duration_minutes": 315
    }
  ],
  "reviews": []
}
```

**200 OK** — fiche compagnie. Erreurs : `404` (compagnie inexistante ou non active).

### POST `/api/v1/auth/company/register/`

Demande publique de création d'un compte compagnie. Crée une **demande** au statut
`pending` : **aucune compagnie active et aucun compte utilisateur ne sont créés** tant
que le super admin n'a pas approuvé (`POST /api/v1/super/company-requests/{id}/approve/`).
La demande apparaît immédiatement dans `GET /api/v1/super/company-requests/`.

Rate limit : **10 requêtes POST / heure par IP** → `429` au-delà.
Accepte `application/json` et `multipart/form-data` (obligatoire si `documents` est envoyé).

| Champ          | Type   | Obligatoire | Notes                                            |
|----------------|--------|-------------|--------------------------------------------------|
| `company_name` | string | oui         | max 150, unique (insensible à la casse)          |
| `manager_name` | string | oui         | max 150, responsable légal                       |
| `phone`        | string | oui         | format BF `+226XXXXXXXX` ou `0XXXXXXXX`          |
| `email`        | string | oui         | email valide                                     |
| `city`         | string | oui         | max 100                                          |
| `documents`    | file   | non         | RCCM, agrément… (`multipart/form-data`)          |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/company/register/ \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Transport Sahel","manager_name":"Awa Ouedraogo","phone":"+22670000000","email":"contact@sahel.bf","city":"Ouagadougou"}'
```

**201 Created**
```json
{
  "id": 12,
  "company_name": "Transport Sahel",
  "manager_name": "Awa Ouedraogo",
  "phone": "+22670000000",
  "email": "contact@sahel.bf",
  "city": "Ouagadougou",
  "status": "pending",
  "created_at": "2026-07-21T10:00:00Z"
}
```

Un SMS d'accusé de réception est envoyé au responsable.

Erreurs :
- `400` — champs obligatoires manquants, `email` invalide, `phone` hors format BF,
  `{"company_name": ["Une compagnie porte deja ce nom."]}`
- `429` — trop de demandes depuis la même IP.
