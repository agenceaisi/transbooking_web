# API — App `trips`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`)
sauf endpoints publics.

Isolation multi-tenant stricte : un `company_admin` ne gère que les voyages de **sa propre**
compagnie (filtre `route__company`). Sans compagnie associée → `404`.

> `available_seats` est initialisé depuis `vehicle.total_seats` à la création et n'est
> jamais fixé manuellement. Sa décrémentation se fait **uniquement** via `select_for_update()`
> (réservations — voir app `bookings`, PROMPT 05).
>
> `registration_closes_at` est initialisé à `departure_time` à la création du voyage,
> décalé uniquement par `POST /agent/trips/{id}/delay/`, et sert de seuil exact pour
> la clôture automatique des enregistrements (voir plus bas).

---

## Voyages — `IsCompanyAdmin`

CRUD filtré par la compagnie de l'utilisateur courant. Filtres : `?route=`, `?status=`,
`?date=YYYY-MM-DD` (sur la date de départ).

### GET `/api/v1/company/trips/`

Liste paginée des voyages (`TripReadSerializer`).

### POST `/api/v1/company/trips/`

| Champ            | Type     | Obligatoire | Notes                                          |
|------------------|----------|-------------|------------------------------------------------|
| `route`          | int      | oui         | FK `routes.Route` (même compagnie)             |
| `vehicle`        | int      | oui         | FK `vehicles.Vehicle` (même compagnie)         |
| `departure_time` | datetime | oui         | ISO 8601                                       |
| `arrival_time`   | datetime | non         | estimée                                        |
| `price`          | decimal  | non         | défaut = `route.base_price`                    |
| `status`         | string   | non         | `scheduled` (défaut)/`in_progress`/`delayed`…  |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/company/trips/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"route": 1, "vehicle": 3, "departure_time": "2026-07-01T06:00:00Z"}'
```

**201 Created** — voyage sérialisé. `available_seats` = `vehicle.total_seats`.
Erreurs : `400` (véhicule et trajet de compagnies différentes), `401`, `403`.

### GET/PATCH `/api/v1/company/trips/{id}/`

Détail / modification (véhicule, heure, prix). `404` si autre compagnie.

### DELETE `/api/v1/company/trips/{id}/`

**Annule** le voyage (status → `cancelled`) et notifie tous les passagers réservés par SMS.

| Champ    | Type   | Obligatoire | Notes                       |
|----------|--------|-------------|-----------------------------|
| `reason` | string | non         | motif d'annulation (SMS)    |

**200 OK** — voyage sérialisé (`status=cancelled`).
Erreurs : `400` (déjà annulé/terminé), `401`, `403`, `404`.

### POST `/api/v1/company/trips/generate/`

Génère des voyages à partir d'horaires types sur une fenêtre glissante de jours.

| Champ             | Type | Obligatoire | Notes                                                         |
|-------------------|------|-------------|---------------------------------------------------------------|
| `route_id`        | int  | oui         | trajet de la compagnie                                        |
| `schedule_config` | list | oui         | slots `{"time": "06:00", "days": [0..6], "vehicle_id": 3}`    |
| `days`            | int  | oui         | nombre de jours à générer (ex: 7, 15, 30, 90)                 |

`days` dans `schedule_config` = indices de jour de semaine (lundi = 0).

```bash
curl -X POST "https://api.transbooking.bf/api/v1/company/trips/generate/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"route_id": 1, "days": 7,
       "schedule_config": [{"time": "06:00", "days": [0,1,2,3,4,5,6], "vehicle_id": 3}]}'
```

**201 Created**
```json
{"created": 7, "trips": [ ... ]}
```
Erreurs : `400` (config invalide, véhicule en maintenance), `401`, `403`, `404` (trajet).

---

## Recherche publique — `AllowAny`

### GET `/api/v1/trips/search/`

Recherche de voyages programmés et à venir avec assez de places, triés par heure de départ.

| Query param   | Type | Notes                                            |
|---------------|------|--------------------------------------------------|
| `origin_city` | int  | id ville de départ                               |
| `dest_city`   | int  | id ville d'arrivée                               |
| `date`        | date | `YYYY-MM-DD` (date de départ)                    |
| `passengers`  | int  | `available_seats >= passengers`                  |
| `max_price`   | num  | prix maximum                                     |
| `direct`      | bool | `true`/`1` → trajets sans escale uniquement      |
| `company`     | int  | id de la compagnie                               |
| `min_rating`  | num  | note moyenne minimale de la compagnie (0–5)      |

**200 OK** — liste paginée (`TripReadSerializer`).

### GET `/api/v1/trips/{id}/`

Détail public d'un voyage + `available_seat_numbers` (liste des sièges libres).

**200 OK** — `TripDetailSerializer` (= `TripReadSerializer` + `available_seat_numbers`).
Erreurs : `404`.

### Champs `TripReadSerializer` (lecture seule)

Outre `id, route, route_label, origin_city, destination_city, vehicle,
vehicle_registration, driver_name, driver_phone, departure_time, arrival_time,
registration_closes_at, price, available_seats, status, status_display, created_at,
updated_at`, chaque
voyage porte les champs dérivés de `trip.route` (cartes de résultats et
réservation) :

| Champ             | Type    | Nullable | Source                                          |
|-------------------|---------|----------|-------------------------------------------------|
| `company`         | int     | non      | `route.company_id`                              |
| `company_name`    | string  | non      | `route.company.name`                            |
| `company_sigle`   | string  | oui      | `route.company.sigle` (`""` si absent)          |
| `company_rating`  | number  | oui      | note moyenne des avis publics de la compagnie   |
| `is_direct`       | bool    | non      | `route` sans escale                             |
| `stops_count`     | int     | non      | nombre d'escales de la route                    |
| `duration_minutes`| int     | oui      | `route.duration_minutes`                        |
| `vehicle_type`    | string  | oui      | `vehicle.vehicle_type` (`null` si non renseigné)|
| `total_seats`     | int     | non      | `vehicle.total_seats`                           |

> `driver_name`/`driver_phone` sont des champs directs de `Trip` (`""` si non
> renseignés — jamais `null`, conformément aux autres champs texte optionnels
> de l'API). Alimentent la colonne « Chauffeur » du programme agent.
>
> `vehicle_type`/`total_seats` alimentent le badge/filtre Standard·VIP·VVIP et
> la barre de progression d'embarquement du programme agent (cf. requetes agent
> module §4) ; exposés aussi sur `OfflineTrip` (`agent/offline-data/`) et
> `AgentDeparture` (`agent/dashboard/`).

> `company_rating`, `is_direct` et `stops_count` sont calculés par sous-requête
> côté serveur (`services.with_read_annotations`), sans requête par ligne. La note
> exclut les avis signalés (cohérente avec la liste d'avis publique).

Exemple (extrait) :

```json
{
  "id": 7, "route": 3, "company": 4, "company_name": "Faso Express",
  "company_sigle": "FE", "company_rating": 4.8,
  "is_direct": true, "stops_count": 0, "duration_minutes": 315
}
```

---

## Agent — programme du jour — `IsAgent`

### GET `/api/v1/agent/trips/today/`

Voyages rattachés à la gare et/ou au véhicule de l'agent connecté (résolus via
`request.user.agent_profile`) pour une date donnée. Non paginé.

| Query param | Type | Obligatoire | Notes                                          |
|-------------|------|-------------|-------------------------------------------------|
| `date`      | date | non         | `YYYY-MM-DD` — défaut : aujourd'hui             |

```bash
curl "https://api.transbooking.bf/api/v1/agent/trips/today/?date=2026-08-12" \
  -H "Authorization: Bearer <access>"
```

**200 OK** — liste de voyages (`TripReadSerializer`), triée par `departure_time`.
Erreurs : `400` (`date` mal formé), `401`, `403`, `404` (aucun profil agent).

### POST `/api/v1/agent/trips/{id}/delay/` — `IsAgentGuichet | IsControleur | IsCompanyAdmin`

Reporte un voyage de N minutes (bus en retard, imprévu terrain). Ouvert directement à
l'agent guichet, au contrôleur et au company admin du périmètre du voyage (isolation
par compagnie), sans étape de validation intermédiaire.

| Champ     | Type | Obligatoire | Notes                                    |
|-----------|------|-------------|-------------------------------------------|
| `minutes` | int  | oui         | ≥ 1, ajouté à `departure_time` et `registration_closes_at` |

Effet : `departure_time` et `registration_closes_at` sont tous les deux décalés de
`+minutes`, `status` bascule à `delayed`. Chaque appel est additif (un voyage déjà
retardé de 10 min qui reprend +5 min part à +15 min au total, pas de plafond).

```bash
curl -X POST "https://api.transbooking.bf/api/v1/agent/trips/42/delay/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"minutes": 10}'
```

**200 OK** — voyage sérialisé (`TripReadSerializer`), `status=delayed`.
Erreurs : `400` (`minutes` manquant/invalide), `401`, `403`, `404` (autre compagnie),
`409` (voyage déjà `completed` : un voyage clos ne se rouvre pas par un report).

---

## Clôture automatique des enregistrements

Une tâche planifiée (`apps.trips.tasks.close_expired_trip_registrations`, toutes les
2 min via Celery beat) bascule vers `completed` tout voyage `scheduled`/`in_progress`/
`delayed` dont `registration_closes_at` est passé — pile à l'heure, sans marge de
grâce. En complément, `bookings.services.create_booking` applique la même bascule à
la volée si la tâche planifiée n'est pas encore repassée, avant de refuser la
réservation (`TripUnavailable`, `410`). Toute nouvelle réservation sur un voyage
`completed` est donc systématiquement refusée, y compris l'enregistrement « dernière
minute » (même endpoint `POST /agent/bookings/`).

---

## Services (`trips/services.py`)

- `generate_trips(route_id, schedule_config, days) -> list[Trip]` — génère les voyages
  (transaction atomique). Vérifie que chaque véhicule est assignable (`active`).
- `cancel_trip(trip, reason) -> Trip` — passe le voyage en `cancelled`, enregistre le motif
  et envoie un SMS à chaque passager réservé. Lève `ValidationError` si déjà annulé/terminé.
- `delay_trip(trip, minutes) -> Trip` — décale `departure_time`/`registration_closes_at` de
  `+minutes`, bascule en `delayed`. Lève `TripAlreadyCompleted` (409) si déjà terminé.
  Le trip doit être verrouillé (`select_for_update()`) par l'appelant.
- `close_expired_registrations() -> int` — bascule en masse vers `completed` tout voyage
  ouvert dont `registration_closes_at` est passé. Retourne le nombre de voyages clos.
