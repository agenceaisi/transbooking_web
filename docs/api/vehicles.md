# API — App `vehicles`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Isolation multi-tenant stricte : un `company_admin` ne gère que les véhicules de **sa propre**
compagnie (résolue via `request.user.administered_company`). Sans compagnie associée → `404`.

---

## Véhicules — `IsCompanyAdmin`

CRUD filtré par la compagnie de l'utilisateur courant. La `company` est déduite
automatiquement. Filtres : `?status=`, `?vehicle_type=`.

### GET `/api/v1/company/vehicles/`

Liste paginée des véhicules de la compagnie.

### POST `/api/v1/company/vehicles/`

| Champ          | Type    | Obligatoire | Notes                                   |
|----------------|---------|-------------|-----------------------------------------|
| `registration` | string  | oui         | unique (immatriculation)                |
| `brand`        | string  | non         |                                         |
| `model`        | string  | non         |                                         |
| `vehicle_type` | string  | non         | ex: `standard`, `vip`, `vvip`            |
| `total_seats`  | integer | oui         | > 0                                     |

`status` (`active`/`maintenance`/`inactive`) et `seat_plan` sont en lecture seule à la
création — voir les actions dédiées. `status` vaut `active` par défaut.

```bash
curl -X POST "https://api.transbooking.bf/api/v1/company/vehicles/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"registration": "11-AA-1234", "brand": "Toyota", "total_seats": 30}'
```

**201 Created** — véhicule sérialisé (`VehicleSerializer`).
Erreurs : `400` (immatriculation dupliquée, sièges ≤ 0), `401`, `403`.

### GET/PATCH/DELETE `/api/v1/company/vehicles/{id}/`

Détail / modification / suppression. `404` si le véhicule appartient à une autre compagnie.

### POST `/api/v1/company/vehicles/{id}/maintenance/`

Passe le véhicule en `maintenance`. **200 OK** — véhicule mis à jour.
Un véhicule en maintenance ne peut plus être affecté à un nouveau voyage
(garde `services.ensure_vehicle_assignable`).

### POST `/api/v1/company/vehicles/{id}/activate/`

Remet le véhicule en service (`active`). **200 OK** — véhicule mis à jour.

### GET `/api/v1/company/vehicles/{id}/seat-plan/`

Retourne le plan des sièges (JSON brut). `{}` si non configuré.

### PUT `/api/v1/company/vehicles/{id}/seat-plan/`

Configure le plan des sièges.

| Champ      | Type            | Obligatoire | Notes                                          |
|------------|-----------------|-------------|------------------------------------------------|
| `layout`   | liste de listes | oui         | rangées de numéros, ex: `[[1,2],[3,4]]`        |
| `reserved` | liste           | non         | numéros non commercialisables (chauffeur, etc.)|

```bash
curl -X PUT "https://api.transbooking.bf/api/v1/company/vehicles/5/seat-plan/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"layout": [[1,2],[3,4]], "reserved": [0]}'
```

**200 OK**
```json
{"layout": [[1, 2], [3, 4]], "reserved": [0]}
```
Erreurs : `400` (`layout` vide ou invalide), `401`, `403`, `404`.

---

## Services (`vehicles/services.py`)

- `get_available_seats(vehicle, trip) -> list[str]` — sièges libres pour un voyage.
  Sans `seat_plan`, génère `"1"`..`"total_seats"`. Exclut `reserved` et les sièges
  déjà réservés (réservations non annulées).
- `next_available_seat(vehicle, trip) -> str` — premier siège libre (auto-attribution).
  Lève `ValidationError` si complet.
- `ensure_vehicle_assignable(vehicle)` — lève `ValidationError` si le véhicule n'est pas `active`.
