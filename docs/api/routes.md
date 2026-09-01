# API — App `routes`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Isolation multi-tenant stricte : un `company_admin` ne gère que les trajets de **sa propre**
compagnie (résolue via `request.user.administered_company`). Sans compagnie associée → `404`.

---

## Trajets — `IsCompanyAdmin`

CRUD filtré par la compagnie de l'utilisateur courant. La `company` est déduite
automatiquement. Filtres : `?origin_city=`, `?destination_city=`, `?is_active=`.

### GET `/api/v1/company/routes/`

Liste paginée des trajets de la compagnie (avec escales imbriquées).

### POST `/api/v1/company/routes/`

| Champ                 | Type    | Obligatoire | Notes                                        |
|-----------------------|---------|-------------|----------------------------------------------|
| `origin_city`         | int     | oui         | FK `geography.City`                          |
| `destination_city`    | int     | oui         | FK `geography.City` (≠ `origin_city`)        |
| `origin_station`      | int     | non         | FK `geography.Station`                       |
| `destination_station` | int     | non         | FK `geography.Station`                       |
| `distance_km`         | decimal | non         | défaut `0` — sert aux tranches tarif colis   |
| `base_price`          | decimal | oui         | prix de base du billet (FCFA)                |
| `duration_minutes`    | int     | non         | durée estimée                                |
| `is_active`           | bool    | non         | défaut `true`                                |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/company/routes/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"origin_city": 1, "destination_city": 2, "distance_km": 350, "base_price": 5000}'
```

**201 Created** — trajet sérialisé (`RouteSerializer`).
Erreurs : `400` (ville départ = ville arrivée, prix manquant), `401`, `403`.

### GET/PATCH/DELETE `/api/v1/company/routes/{id}/`

Détail / modification / suppression. `404` si le trajet appartient à une autre compagnie.

### POST `/api/v1/company/routes/{id}/duplicate/`

Crée le **trajet inverse** : villes et gares départ/arrivée permutées, mêmes prix et
distance, escales reconstruites dans l'ordre inverse.

**201 Created** — nouveau trajet sérialisé. Erreurs : `401`, `403`, `404`.

---

## Escales — `IsCompanyAdmin`

URL imbriquée sous un trajet. Les escales sont triées par `stop_order`.

### GET `/api/v1/company/routes/{route_pk}/stops/`

Liste paginée des escales du trajet.

### POST `/api/v1/company/routes/{route_pk}/stops/`

| Champ        | Type    | Obligatoire | Notes                              |
|--------------|---------|-------------|------------------------------------|
| `city`       | int     | oui         | FK `geography.City`                |
| `stop_order` | int     | oui         | unique par trajet                  |
| `stop_price` | decimal | oui         | prix partiel jusqu'à l'escale      |

**201 Created** — escale sérialisée (`RouteStopSerializer`).
Erreurs : `400` (`stop_order` dupliqué), `401`, `403`, `404`.

### PATCH/DELETE `/api/v1/company/routes/{route_pk}/stops/{id}/`

Modification / suppression d'une escale. `404` si l'escale ou le trajet n'appartient
pas à la compagnie de l'utilisateur.

---

## Services (`routes/services.py`)

- `duplicate_reverse_route(route) -> Route` — crée le trajet inverse (transaction atomique),
  permute origine/destination et reconstruit les escales en ordre inverse.
