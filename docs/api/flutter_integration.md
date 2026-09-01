# TransBooking BF — Guide d'intégration API pour le frontend Flutter

> **But de ce document.** Servir de référence unique à Claude Code (et à tout développeur)
> pour brancher l'application Flutter sur l'API TransBooking BF. Chaque endpoint est décrit
> avec : sa méthode HTTP, son URL exacte, le rôle requis, les paramètres (query / body),
> la réponse attendue, les erreurs possibles, et **la partie de l'app Flutter concernée**.
>
> ⚠️ Ce fichier documente l'API **réellement implémentée** (routes présentes dans les
> `urls.py`), pas seulement la spec théorique. La section [Endpoints prévus mais non
> encore disponibles](#endpoints-prévus-mais-non-encore-disponibles) liste ce qu'il ne faut
> **pas** encore appeler.

---

## 1. Informations globales

| Élément | Valeur |
|---------|--------|
| **Base URL (dev)** | `http://localhost:8000` |
| **Préfixe API** | `/api/v1/` (toutes les routes métier) |
| **Format** | JSON (`Content-Type: application/json`) |
| **Auth** | JWT Bearer — header `Authorization: Bearer <access_token>` |
| **Durée access token** | 30 minutes |
| **Durée refresh token** | 7 jours |
| **Langue des messages d'erreur** | Français |
| **Fuseau horaire** | `Africa/Ouagadougou` (dates ISO 8601 en UTC dans les réponses) |
| **Doc OpenAPI live** | `GET /api/schema/` · Swagger `GET /api/docs/` · Redoc `GET /api/redoc/` |

> 💡 **Conseil Flutter** : définir une constante `kApiBaseUrl` + un `Dio`/`http.Client`
> avec un intercepteur qui : (1) ajoute le header `Authorization`, (2) rafraîchit
> automatiquement l'access token sur `401` via `/auth/token/refresh/`, (3) mappe les
> enveloppes d'erreur (voir §4).

### 1.1 Base URL selon la plateforme (dev)

- Émulateur Android : `http://10.0.2.2:8000`
- Simulateur iOS / Web / Desktop : `http://localhost:8000`
- Appareil physique : `http://<IP_LAN_du_serveur>:8000`

---

## 2. Rôles et permissions

L'API est **multi-tenant** : un utilisateur ne voit jamais les données d'une autre compagnie.
Le rôle est porté par `user.role.name` et renvoyé dans la réponse de login.

| Rôle (`role`) | Description | Espace Flutter suggéré |
|---------------|-------------|------------------------|
| `voyageur` | Client final (mobile) | App voyageur (recherche, réservation, billets) |
| `agent_guichet` | Vente au guichet (souvent hors ligne) | App agent — module guichet |
| `controleur` | Embarquement / scan QR | App agent — module contrôle |
| `company_admin` | Gestion d'une compagnie | Back-office compagnie (web/desktop/tablette) |
| `super_admin` | Administration plateforme | Back-office super admin |

> Une compagnie `suspended` ou `rejected` bloque **toutes** les requêtes de son
> `company_admin` (403). Prévoir un écran « compte suspendu ».
> Il en va de même quand son **abonnement est expiré** (cf. §6.17) — à une exception près :
> les routes `company/subscription/…` restent accessibles pour consulter le forfait et les
> factures.

---

## 3. Pagination

Tous les `GET` de listes (sauf ceux marqués « non paginé ») utilisent la pagination par page :

- Query params : `?page=<int>&page_size=<int>` (défaut `page_size=20`, max `100`).
- **Enveloppe de réponse** :

```json
{
  "count": 137,
  "next": "http://localhost:8000/api/v1/company/bookings/?page=3",
  "previous": "http://localhost:8000/api/v1/company/bookings/?page=1",
  "results": [ /* ... objets ... */ ]
}
```

> Listes **non paginées** (renvoient un tableau brut) : `cities`, `agent/trips/today/`,
> `agent/sync/conflicts/`, `agent/offline-data/`, et tous les endpoints dashboard qui
> renvoient des séries.

---

## 4. Format des erreurs

DRF renvoie des erreurs JSON. Deux formes principales à gérer côté Flutter :

```jsonc
// Erreur de validation de champ (400)
{ "phone": ["Ce numero de telephone est deja utilise."] }

// Erreur générique (401, 403, 404, 409, 429)
{ "detail": "Informations d'authentification non fournies." }
```

| Code | Signification | Réaction Flutter typique |
|------|---------------|--------------------------|
| `400` | Validation échouée | Afficher l'erreur sous le champ concerné |
| `401` | Token absent / expiré | Rafraîchir le token, sinon rediriger vers login |
| `403` | Rôle insuffisant / compagnie suspendue | Écran « accès refusé » |
| `404` | Ressource introuvable / hors périmètre | Message « introuvable » |
| `409` | Conflit (ex. siège déjà pris) | Proposer un autre siège / réessayer |
| `429` | Trop de requêtes (rate limit) | `{"detail": "Trop de tentatives..."}` → back-off |

> **Rate limiting** : endpoints d'auth = **10 requêtes/min/IP**. Renvoi d'un code de paiement
> (`payments/{id}/resend-otp`) = **1 / 30 s / paiement**. Débit global anonyme `60/min`,
> authentifié `1000/min`.

Certaines erreurs `400` ajoutent un champ **typé** à côté des messages, à lire tel quel
(ex. `attempts_remaining` sur la vérification d'un code de paiement, cf. §6.8).

---

## 5. Énumérations (valeurs exactes pour les `enum` Dart)

Créer des enums Dart alignées sur ces **valeurs techniques** (jamais le libellé affiché,
qui est fourni séparément par les champs `*_display`).

```dart
// Rôles
enum Role { super_admin, company_admin, agent_guichet, controleur, voyageur }

// Statut d'une réservation (booking.status)
enum BookingStatus { pending, paid, cancelled, refunded }

// Statut d'un voyage (trip.status)
enum TripStatus { scheduled, in_progress, delayed, cancelled, completed }

// Méthode de paiement (payment.method / booking.payment_method)
enum PaymentMethod { cash, orange_money, moov_money, coris_money, telecel_money, card }

// Statut d'un paiement
// `otp_required` = code de confirmation Mobile Money envoyé, en attente de saisie
// (état intermédiaire entre `pending` et `paid`).
enum PaymentStatus { pending, otp_required, paid, failed, refunded }

// Statut d'un colis
enum ParcelStatus { registered, in_transit, arrived, notified, collected }

// Notification colis
enum ParcelNotificationMethod { sms, call }

// Type de réclamation
enum ClaimType { retard, perte_bagage, bagage_endommage, comportement, surcharge, remboursement, autre }

// Statut d'une réclamation
enum ClaimStatus { submitted, in_progress, resolved, closed, escalated }

// Statut d'un signalement d'excès de vitesse
enum SpeedReportStatus { pending, reviewed, closed }

// Gravité estimée d'un signalement (speed_report.severity, optionnel → peut être null)
enum SpeedReportSeverity { low, medium, high }

// Statut d'un véhicule
enum VehicleStatus { active, maintenance, inactive }

// Statut d'une compagnie
// `info_requested` = demande d'inscription en attente de pièces complémentaires
// (toujours en cours d'instruction, au même titre que `pending`).
enum CompanyStatus { pending, info_requested, active, suspended, rejected }

// Type de notification in-app
enum NotificationType { booking, payment, parcel, claim, review, trip, message, system }

// Méthode d'embarquement
enum BoardingMethod { scan, manual }

// Emplacement d'un bagage enregistré (baggage.location)
enum BaggageLocation { hold, cabin } // hold = « En soute », cabin = « En cabine »

// Sexe du passager (booking.gender, optionnel — "" si non renseigné)
enum Gender { M, F } // M = « Masculin », F = « Féminin »

// Type de pièce d'identité (booking.id_type, défaut "none")
enum IdType { none, cnib, passport }

// Type d'agent
enum AgentType { guichet, controleur }

// Type de conflit de synchronisation
enum SyncConflictType { seat_conflict, trip_full, trip_unavailable, duplicate, invalid }

// Statut d'un abonnement (subscription.status)
enum SubscriptionStatus { active, expired, cancelled }

// Résultat d'un scan de billet (scan/history → result)
enum ScanResult { valid, unpaid, cancelled, refunded, already_boarded, invalid, not_found }

// Catégories du fil de supervision super admin (super/notifications → type)
enum SuperNotificationType { new_registration, subscription_expired, urgent_report, technical_incident }

// Criticité d'une alerte de supervision (super/notifications → severity)
enum SuperNotificationSeverity { info, warning, critical }
```

---

# 6. Endpoints par domaine

Convention colonnes : **Auth** = rôle requis (`public` = aucun).
Les corps de requête ne listent que les champs **envoyés par le client**
(les champs déduits côté serveur — compagnie, agent, tarif, `ticket_number`… — sont notés).

---

## 6.1 Authentification & Profil — `apps/users`

> **Flutter** : écran de connexion / inscription, splash (auto-login via refresh token),
> écran « Mon profil ». Stocker les tokens dans `flutter_secure_storage`.

### `POST /api/v1/auth/register/` · public
Inscription d'un **voyageur**.

- **Body**
  ```json
  { "prenom": "Awa", "nom": "Traore", "phone": "+22670000000", "password": "motdepasse8", "email": "awa@ex.com" }
  ```
  `email` optionnel. `phone` doit être un numéro BF valide et unique. `password` ≥ 8 caractères.
- **200/201** → `{ "prenom", "nom", "phone", "email", "role": "voyageur" }`
- **Erreurs** : `400` (téléphone déjà utilisé, mot de passe trop court), `429`.

### `POST /api/v1/auth/login/` · public
Connexion. **Le champ identifiant est le téléphone.**

- **Body** `{ "phone": "+22670000000", "password": "motdepasse8" }`
- **200** →
  ```json
  { "access": "<jwt>", "refresh": "<jwt>", "role": "voyageur", "prenom": "Awa" }
  ```
  → Router l'utilisateur selon `role`.
- **Erreurs** : `401` (identifiants invalides), `429`.

### `POST /api/v1/auth/token/refresh/` · public
Rafraîchit l'access token.
- **Body** `{ "refresh": "<jwt>" }` → **200** `{ "access": "<jwt>" }`

### `POST /api/v1/auth/logout/` · auth
Révoque (blackliste) le refresh token.
- **Body** `{ "refresh": "<jwt>" }` → **204** (pas de corps). `400` si token invalide.

### `GET /api/v1/users/me/` · auth
Profil courant → `{ "prenom", "nom", "phone", "email", "role" }`.

### `PATCH /api/v1/users/me/` · auth
Met à jour le profil.
- **Body** (partiel) `{ "phone": "...", "email": "..." }` → profil mis à jour.

### `POST /api/v1/auth/password/change/` · auth
Change le mot de passe de l'utilisateur connecté.

- **Body** `{ "old_password": "motdepasse8", "new_password": "TransBooking2026" }`
- **200** → `{ "detail": "Mot de passe modifie avec succes." }`
- **Erreurs** :
  - `400` `{ "old_password": ["Ancien mot de passe incorrect."] }`
  - `400` `{ "new_password": [...] }` — règles Django (≥ 8 caractères, pas entièrement
    numérique, pas un mot de passe courant, pas trop proche du téléphone/nom)
  - `400` `{ "new_password": ["Le nouveau mot de passe doit etre different de l'ancien."] }`
  - `401`, `429` (10 POST/min par IP)
- **Flutter** : les tokens en cours **restent valides**. Enchaîner avec `auth/logout`
  puis reconnexion si l'on veut forcer une nouvelle session.

---

## 6.2 Compagnies — `apps/companies`

### Public

#### `GET /api/v1/public/companies/` · public
Liste des compagnies **actives** (page d'accueil). Paginé, **caché 1h**.
- **Item** → `{ "id", "name", "sigle", "logo", "description", "city", "rating" }`
- `rating` = note moyenne des avis publics (non signalés), annotée côté serveur ; `null`
  uniquement si la compagnie n'a aucun avis.
- **Flutter** : carrousel/liste des partenaires sur l'accueil voyageur.

#### `GET /api/v1/public/companies/{id}/` · public
Fiche publique détaillée → champs de l'item de liste **+** `phone`, `email`, `routes`,
`reviews_count`, `rating_breakdown`, `reviews`.

| Champ | Type | Null | Notes |
|-------|------|------|-------|
| `routes` | array | non | trajets **actifs** desservis (voir ci-dessous) |
| `reviews_count` | int | non | total des avis publics (non signalés) |
| `rating_breakdown` | object | non | répartition `{"1".."5": n}` des notes |
| `reviews` | array | non | toujours `[]` → charger via `/reviews/?company_id=` (paginé) |

- **Entrée `routes`** : `{ "id", "origin_city_name", "destination_city_name",
  "base_price" (str décimal), "duration_minutes" (int|null) }`.
- **Flutter** : rétablir la section « Trajets desservis » depuis `routes` ; alimenter la carte de
  note avec `rating` + `reviews_count` + `rating_breakdown` (agrégat serveur fiable) au lieu de
  calculer la répartition sur la 1ʳᵉ page d'avis.

#### `POST /api/v1/auth/company/register/` · public
Demande d'ouverture d'un compte compagnie. **Ne crée ni compagnie active ni compte
utilisateur** : la demande part au statut `pending` et attend la validation du super admin.

- **Body** (`application/json`, ou `multipart/form-data` si `documents` est joint)
  ```json
  {
    "company_name": "Transport Sahel",
    "manager_name": "Awa Ouedraogo",
    "phone": "+22670000000",
    "email": "contact@sahel.bf",
    "city": "Ouagadougou"
  }
  ```
  `documents` (fichier, optionnel) : RCCM, agrément…
- **201** →
  ```json
  { "id": 12, "company_name": "Transport Sahel", "manager_name": "Awa Ouedraogo",
    "phone": "+22670000000", "email": "contact@sahel.bf", "city": "Ouagadougou",
    "status": "pending", "created_at": "2026-07-21T10:00:00Z" }
  ```
  `status` ∈ `CompanyStatus` (§5). Un SMS d'accusé de réception part vers `phone`.
- **Erreurs** : `400` (champs manquants, `phone` hors format BF, email invalide,
  `company_name` déjà pris), `429` (10 demandes/heure par IP).
- **Flutter** : écran « Devenir partenaire ». Après `201`, afficher un écran d'attente —
  la compagnie sera contactée par SMS après approbation.

### Super admin

| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/super/companies/` | Liste (filtres : `status`, `city`, `created_after`, `created_before`) |
| POST | `/api/v1/super/companies/` | Créer (active d'emblée) |
| GET | `/api/v1/super/companies/{id}/` | Détail complet |
| PATCH | `/api/v1/super/companies/{id}/` | Modifier |
| DELETE | `/api/v1/super/companies/{id}/` | Supprimer |
| POST | `/api/v1/super/companies/{id}/activate/` | Activer |
| POST | `/api/v1/super/companies/{id}/suspend/` | Suspendre — body `{ "reason": "..." }` |

- **Objet détail** (`CompanyDetailSerializer`) : `id, name, sigle, description, logo, banner,
  primary_color, welcome_message, city, address, phone, email, responsible_name,
  responsible_phone, rccm, ifu, commission_rate, status, rejection_reason,
  suspension_reason, info_request_message, active_payment_methods[], subscription_status,
  created_at, updated_at`.
- **Création** (body) : `name` (unique), `sigle, description, city, address, phone, email,
  responsible_name, responsible_phone, rccm, ifu, commission_rate`.
- **Flutter (super admin)** : liste des compagnies, fiche, actions activer/suspendre.

#### Demandes d'inscription compagnie (super admin)
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/super/company-requests/` | Liste des demandes ouvertes (`pending` **et** `info_requested`) |
| GET | `/api/v1/super/company-requests/{id}/` | Détail d'une demande |
| POST | `/api/v1/super/company-requests/{id}/approve/` | Approuver → `active` |
| POST | `/api/v1/super/company-requests/{id}/reject/` | Rejeter — body `{ "reason": "..." }` |
| POST | `/api/v1/super/company-requests/{id}/request-info/` | Demander des pièces — body `{ "message": "..." }` |

- Les demandes sont créées par `POST /api/v1/auth/company/register/` (§6.2 · public).
- `request-info` → **200** avec `{ "status": "info_requested", "info_request_message": "..." }`.
  La demande **reste dans la file** : on peut redemander des infos, puis approuver ou rejeter.
  Le demandeur est notifié par **SMS** (et in-app s'il a déjà un compte `admin_user`).
- `approve` et `reject` acceptent les deux statuts ouverts (`pending`, `info_requested`).
- **404** sur ces actions si la demande est close (compagnie déjà `active`/`rejected`) —
  elle n'appartient plus au queryset.
- **400** sur `request-info` si `message` est vide.
- **Flutter (super admin)** : dans la file d'attente, 3 boutons — Approuver / Demander des
  infos / Rejeter. Afficher un badge distinct pour `info_requested` et le dernier
  `info_request_message` sur la fiche de la demande.

### Admin compagnie — paramètres

| Méthode | URL | Description |
|---------|-----|-------------|
| GET / PATCH | `/api/v1/company/settings/` | Charte graphique & infos (logo, banner, `primary_color`, `welcome_message`, contacts) |
| GET / PATCH | `/api/v1/company/settings/payment-methods/` | Moyens de paiement activés |
| GET / PATCH | `/api/v1/company/settings/notifications/` | SMS automatiques |

- **payment-methods** — GET renvoie `[{ "method": "orange_money", "is_active": true }, ...]`.
  PATCH accepte `{ "payment_methods": [{ "method": "...", "is_active": true }] }`.
- **notifications** — objet `{ "sms_booking_confirmation", "sms_departure_reminder", "sms_parcel_arrival" }` (booléens).
- **Flutter (company admin)** : écran « Paramètres de la compagnie » (onglets Identité / Paiements / Notifications).

### Admin compagnie — gestion des agents

| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/agents/` | Agents de la compagnie (filtres `is_active`, `agent_profile__agent_type`) |
| POST | `/api/v1/company/agents/` | Créer un agent — mot de passe temporaire **par SMS** |
| GET / PATCH | `/api/v1/company/agents/{id}/` | Détail · modifier · activer/désactiver (`is_active`) |
| DELETE | `/api/v1/company/agents/{id}/` | Supprimer — **400** si l'agent a de l'activité |
| POST | `/api/v1/company/agents/{id}/reset-password/` | Nouveau mot de passe temporaire par SMS |
| POST | `/api/v1/company/agents/invite/` | Invitation SMS avec lien de création de compte |

- **POST body** : `{ prenom, nom, phone, role: "agent_guichet"|"controleur", email?, station? }`.
  Le mot de passe n'est **jamais** renvoyé par l'API (SMS uniquement).
- **Agent** : `{ id, prenom, nom, phone, email, role, agent_type ("guichet"|"controleur"),
  station {id,name}|null, is_active, created_at }`.
- **DELETE** → `400` dès que l'agent a saisi des réservations, encaissé, validé des
  embarquements ou synchronisé : proposer la **désactivation** (`PATCH {"is_active": false}`).
- **invite** → `201 { detail, phone, role, invite_url, expires_in_hours }`. Aucun compte
  n'est créé tant que le lien n'est pas suivi (jeton signé, 48 h).
- **Isolation** : `404` sur tout agent d'une autre compagnie.
- **Flutter (company admin)** : écran « Mes agents » (liste + création + switch actif/inactif
  + bouton réinitialiser le mot de passe + inviter).

---

## 6.3 Géographie — `apps/geography`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| GET | `/api/v1/cities/` | public | Villes desservies (**non paginé**, caché 1h) → `[{ "id", "name", "region" }]` |
| POST | `/api/v1/super/cities/` | super | Ajouter une ville (`name` unique, `region`) |
| GET | `/api/v1/super/cities/` | super | Liste des villes |
| GET | `/api/v1/company/stations/` | admin | Gares de la compagnie |
| POST | `/api/v1/company/stations/` | admin | Ajouter une gare |
| GET/PATCH/DELETE | `/api/v1/company/stations/{id}/` | admin | Détail / modifier / supprimer |

- **Station** : `{ "id", "city", "city_name", "name", "address", "localisation", "created_at", "updated_at" }`.
  `company` déduit de l'utilisateur.
- **Flutter** : `cities` alimente les **dropdowns départ/arrivée** de la recherche et des formulaires.

---

## 6.4 Véhicules — `apps/vehicles` (company admin)

| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/vehicles/` | Liste (filtres : `status`, `vehicle_type`) |
| POST | `/api/v1/company/vehicles/` | Ajouter |
| GET/PATCH/DELETE | `/api/v1/company/vehicles/{id}/` | Détail / modifier / supprimer |
| POST | `/api/v1/company/vehicles/{id}/maintenance/` | Passer en maintenance |
| POST | `/api/v1/company/vehicles/{id}/activate/` | Remettre en service |
| GET | `/api/v1/company/vehicles/{id}/seat-plan/` | Lire le plan des sièges (JSON) |
| PUT | `/api/v1/company/vehicles/{id}/seat-plan/` | Configurer le plan |

- **Vehicle** : `id, registration, brand, model, vehicle_type, total_seats, status,
  status_display, seat_plan, created_at, updated_at`. `status`, `seat_plan` en lecture seule (via actions).
- **seat-plan (PUT) body** : `{ "layout": [[1,2],[3,4]], "reserved": [1] }`.
- **Flutter** : écran flotte + éditeur graphique de plan de sièges.

---

## 6.5 Trajets (routes) — `apps/routes` (company admin)

| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/routes/` | Liste (filtres : `origin_city`, `destination_city`, `is_active`) |
| POST | `/api/v1/company/routes/` | Créer |
| GET/PATCH/DELETE | `/api/v1/company/routes/{id}/` | Détail / modifier / supprimer |
| POST | `/api/v1/company/routes/{id}/duplicate/` | Dupliquer en trajet inverse (→ 201) |
| GET | `/api/v1/company/routes/{route_pk}/stops/` | Escales du trajet |
| POST | `/api/v1/company/routes/{route_pk}/stops/` | Ajouter une escale |
| GET/PATCH/DELETE | `/api/v1/company/routes/{route_pk}/stops/{id}/` | Détail / modifier / supprimer |

- **Route** : `id, origin_city(+_name), destination_city(+_name), origin_station,
  destination_station, distance_km, base_price, duration_minutes, is_active, stops[], ...`.
  Départ ≠ arrivée (validation).
- **RouteStop** : `id, city(+city_name), stop_order, stop_price, ...`.
- **Flutter** : écran « Lignes/Trajets » + gestion des escales.

---

## 6.6 Voyages (trips) — `apps/trips`

### Recherche publique
#### `GET /api/v1/trips/search/` · public
Recherche de voyages à venir ouverts à la réservation.
- **Query params** : `origin_city` (id), `dest_city` (id), `date` (`YYYY-MM-DD`),
  `passengers` (int → sièges dispo ≥ N), `max_price` (nombre), `direct` (`true`/`1` = sans escale),
  `company` (id de compagnie), `min_rating` (nombre 0–5 = note moyenne minimale de la compagnie).
- **200** → liste paginée de `TripRead` (voir ci-dessous), triée par `departure_time`.
- **Flutter (voyageur)** : écran résultats de recherche. `company` / `min_rating` permettent de
  pousser les filtres « compagnie » et « note » **côté serveur** (au lieu d'un filtrage client).

#### `GET /api/v1/trips/{id}/` · public
Détail d'un voyage **+ sièges disponibles**.
- **200** → `TripRead` **+** `available_seat_numbers: ["1","2",...]`.
- **Flutter** : écran détail voyage / sélecteur de siège.

- **TripRead** : `id, route, route_label, origin_city, destination_city, vehicle,
  vehicle_registration, driver_name, driver_phone, departure_time, arrival_time, price,
  available_seats, status, status_display, created_at, updated_at` **+** les champs dérivés
  de `trip.route` ci-dessous.
  `driver_name`/`driver_phone` sont des chaînes vides (`""`) — jamais `null` — quand non
  renseignés (mêmes conventions que les autres champs texte optionnels de l'API).

| Champ (lecture seule) | Type | Null | Source |
|-----------------------|------|------|--------|
| `company` | int | non | `route.company_id` |
| `company_name` | string | non | `route.company.name` |
| `company_sigle` | string | oui (`""` si absent) | `route.company.sigle` |
| `company_rating` | number | oui | note moyenne des avis publics **non signalés** (arrondi 1 déc.) |
| `is_direct` | bool | non | `route` sans escale |
| `stops_count` | int | non | nombre d'escales de la route |
| `duration_minutes` | int | oui | `route.duration_minutes` |

  Ces champs alimentent la **carte de résultat** (nom de compagnie + note en étoiles + badge
  Direct / *n* escale(s)) et l'écran de réservation (4B). Ils sont annotés par sous-requête côté
  serveur → **pas de requête par ligne**. `company_rating` vaut `null` si la compagnie n'a aucun
  avis (mêmes règles que `public/companies` §6.2).

### Gestion (company admin)
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/trips/` | Liste (filtres : `route`, `status`, `date=YYYY-MM-DD`) |
| POST | `/api/v1/company/trips/` | Créer un voyage |
| GET/PATCH | `/api/v1/company/trips/{id}/` | Détail / modifier |
| DELETE | `/api/v1/company/trips/{id}/` | **Annule** le voyage (notifie les passagers) — body `{ "reason": "..." }`, renvoie 200 + trip |
| POST | `/api/v1/company/trips/generate/` | Générer en lot |

- **Création (body)** : `route, vehicle, departure_time, arrival_time, price?` (`price`
  reprend `route.base_price` si absent ; `available_seats` = `vehicle.total_seats`).
  Véhicule et trajet doivent être de la même compagnie.
- **generate (body)** : `{ "route_id": 12, "schedule_config": [...], "days": 30 }`
  → `{ "created": <n>, "trips": [...] }`.

### Agent
#### `GET /api/v1/agent/trips/today/` · agent (guichet ou contrôleur)
Voyages du périmètre de l'agent (sa gare et/ou son véhicule) pour une date donnée.
**Non paginé.**
- **Query params** : `date` (`YYYY-MM-DD`, optionnel, défaut = aujourd'hui). `400` si mal formé.
- **200** → liste de `TripRead`, triée par `departure_time`.
- **Flutter (agent)** : écran « Programme de la semaine » (sélecteur de jour — un appel par
  jour sélectionné, `date` passé à chaque changement d'onglet).

---

## 6.7 Réservations & billets — `apps/bookings`

### Voyageur
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/bookings/` | Mes réservations (paginé) |
| POST | `/api/v1/bookings/` | Créer une réservation |
| GET | `/api/v1/bookings/{id}/` | Détail |
| POST | `/api/v1/bookings/{id}/cancel/` | Annuler — body `{ "reason": "..." }` |
| GET | `/api/v1/bookings/{id}/ticket/` | **Billet PDF** (`application/pdf`, avec QR) |

- **POST body** : `{ "trip": <id>, "seat_number"?: "12", "first_name"?, "last_name"?, "phone"? }`.
  Identité/téléphone repris du compte si absents. Siège auto-attribué si absent.
  Réservation créée au statut `pending` → paiement à confirmer ensuite.
- **BookingRead** : `id, ticket_number, trip{id, origin_city, destination_city,
  company_name, company_sigle, departure_time, arrival_time, status}, first_name,
  last_name, passenger_name, phone, seat_number, amount, payment_method, qr_code (base64 PNG),
  status, status_display, is_offline, is_boarded, baggage[], baggage_total_weight_kg,
  created_at, updated_at`.
- **`trip.company_name`** (str) / **`trip.company_sigle`** (str, `""` si absent) : en-tête
  compagnie de la carte « Mon billet » (monogramme + nom).
- **`baggage[]`** : bagages enregistrés au guichet, chaque entrée
  `{ id, label, tag ("TB-B-0042"), weight_kg (str décimal), location (`hold`/`cabin`),
  location_display }`. **`baggage_total_weight_kg`** (str décimal) = somme des poids — pour
  l'écran « Bagages ». Tableau vide + `"0.0"` si aucun bagage.
- **Flutter (voyageur)** : « Mes billets », détail billet (affiche `qr_code` + en-tête
  compagnie), écran « Bagages » (liste `baggage[]` + poids total), bouton télécharger PDF,
  annulation.

### Agent guichet
| Méthode | URL | Description |
|---------|-----|-------------|
| POST | `/api/v1/agent/bookings/` | Enregistrer un passager au guichet (**hors ligne possible**) |
| GET | `/api/v1/agent/bookings/{ticket_number}/` | Rechercher un billet par **numéro** (pas d'id) |
| POST | `/api/v1/agent/bookings/{ticket_number}/print/` | Marquer imprimé + payload d'impression |

- **POST body** : `trip, first_name, last_name, phone, gender?, id_type?, id_number?,
  seat_number?, amount?, payment_method, transaction_ref? (requis si ≠ cash),
  discount_code?, is_offline?, offline_created_at? (requis si is_offline), ticket_number?,
  baggage?`. Créé directement au statut `paid`.
- **`gender`** (optionnel) : `"M"` ou `"F"`.
- **`id_type`** (optionnel, défaut `"none"`) : `"none"`·`"cnib"`·`"passport"`.
  **`id_number`** requis (`400` sinon) dès que `id_type ≠ "none"`.
  Ces deux champs sont des données sensibles : **stockés mais jamais renvoyés** dans
  `BookingRead` ni dans aucune liste de réservations.
- **`discount_code`** (optionnel) : code libre, persisté tel quel. **Aucune validation
  serveur pour l'instant** (pas de catalogue de codes) — un code invalide/expiré n'est pas
  détecté aujourd'hui, ne pas encore afficher de retour "code appliqué" côté app.
- **`baggage`** (liste, optionnel) : bagages pesés à étiqueter, chaque entrée
  `{ label, weight_kg, location? ("hold"|"cabin", défaut "hold") }`. Une étiquette `tag`
  (`TB-B-XXXX`) est générée par bagage et ressort dans `BookingRead.baggage[]`.
- **print** (corps vide) → `{ ticket_number, passenger_name, phone, seat_number, amount,
  status, company_name, origin_city, destination_city, departure_time, qr_code, printed_at,
  print_count }`. Réimpression autorisée : `print_count` s'incrémente à chaque appel.
- **Flutter (agent)** : formulaire de vente au guichet, recherche billet par numéro, bouton
  « Imprimer le billet » (le payload alimente l'imprimante thermique).

### Contrôleur — embarquement
| Méthode | URL | Description |
|---------|-----|-------------|
| POST | `/api/v1/agent/scan/` | Scanner un QR → statut du billet + code couleur |
| GET | `/api/v1/agent/scan/history/` | 50 derniers scans de l'agent (horodatés, paginé) |
| POST | `/api/v1/agent/trips/{trip_id}/boarding/{booking_id}/` | Cocher un passager (manuel) |
| POST | `/api/v1/agent/trips/{trip_id}/boarding/all/` | Embarquer tous les payés — body `{ "confirm": true }` |
| POST | `/api/v1/agent/trips/{trip_id}/boarding/validate/` | Verrouiller / résumé d'embarquement |

- **scan body** : `{ "qr_data": "BF2026001234" }` (ou `{ "ticket_number": "..." }`).
  → renvoie le résultat du scan (statut billet + info d'affichage). `404` si billet introuvable.
- **boarding/{booking_id}** : le booking doit être `paid` → crée une validation d'embarquement (201).
- **boarding/all** : `{ "boarded": <n> }`.
- **boarding/validate** : `{ "trip", "total_paid", "boarded", "not_boarded", "locked": true }`.
- **scan/history** : `{ id, ticket_number, result, result_display, passenger_name|null,
  seat_number|null, scanned_at }`. Chaque scan est tracé, y compris `not_found`.
  Enum `result` : `valid · unpaid · cancelled · refunded · already_boarded · invalid · not_found`.
- **Flutter (contrôleur)** : scanner QR (caméra), liste d'embarquement avec cases à cocher,
  bouton « tout embarquer », écran de validation finale.

### Admin compagnie
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/bookings/` | Toutes les réservations (filtres : `status`, `trip`, `route`, `payment_method`, `date_from`, `date_to`) |
| GET | `/api/v1/company/bookings/export/` | Export `?format=excel|pdf` (fichier) |

- **Flutter (company admin)** : tableau des réservations filtrable + export.

---

## 6.8 Paiements — `apps/payments`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| GET | `/api/v1/payments/` | auth | **Mes paiements** (paginé, périmètre de l'utilisateur) |
| POST | `/api/v1/payments/` | auth | Initier un paiement (Mobile Money → `otp_required`, espèces → `pending`) |
| GET | `/api/v1/payments/{id}/` | auth | Statut d'un paiement |
| POST | `/api/v1/payments/{id}/verify-otp/` | auth | **Confirmer avec le code reçu** — body `{ "otp": "123456" }` |
| POST | `/api/v1/payments/{id}/resend-otp/` | auth | **Renvoyer un code** (corps vide, 1 / 30 s) |
| POST | `/api/v1/payments/{id}/verify/` | auth | Confirmation manuelle **espèces uniquement** — body `{ "transaction_ref": "..." }` |
| GET | `/api/v1/payments/{id}/receipt/` | auth | **Reçu PDF** |
| POST | `/api/v1/agent/payments/` | agent guichet | Encaissement guichet (espèces en 1 étape, Mobile Money via OTP) |

- **POST /payments/ body** : `{ "booking_id": <id>, "method": "orange_money", "phone": "+226..." }`
  — `phone` est **obligatoire** pour un moyen Mobile Money (destinataire du code) ;
  `method: "card"` → **400** (hors périmètre) ; le paiement de **colis** `parcel_id` n'est
  **pas** encore supporté → 400.
- **agent/payments body** : `{ "booking_id": <id>, "method": "cash|orange_money|...",
  "phone"? (requis si Mobile Money), "transaction_ref"? (espèces uniquement) }`.
- **GET /payments/** : liste **paginée** des paiements du voyageur (ses réservations
  uniquement ; `transaction_ref`/`phone` masqués), triée par date décroissante — alimente le
  sous-onglet « Paiements » de l'écran « Mon profil ». Items = `PaymentRead`.
- **PaymentRead** : `id, ticket_number, amount, method, method_display, status,
  status_display, transaction_ref (masqué → "****1234"), phone (masqué → "****0001"),
  otp_expires_at, otp_attempts_remaining, receipt_url, paid_at, created_at`.
  `otp_expires_at` et `otp_attempts_remaining` valent `null` hors statut `otp_required`.

### Flux Mobile Money par OTP

```
POST /payments/                 → 201 { status: "otp_required", otp_expires_at, otp_attempts_remaining: 3 }
   ↓ (l'opérateur envoie un code à 6 chiffres au payeur, valable 5 min)
POST /payments/{id}/verify-otp/ → 200 { status: "paid", receipt_url }   ✅
                                → 400 { otp: [...], attempts_remaining: 2 }  (code faux)
POST /payments/{id}/resend-otp/ → 200 (nouveau code)  |  429 (moins de 30 s)
```

- **Code faux** → `400` avec `attempts_remaining` (entier). Après **3** tentatives, ou au-delà
  de `otp_expires_at`, le paiement passe `failed` → il faut **relancer** un paiement.
- **429** sur `resend-otp` : `{"detail": "Patientez N seconde(s) avant de demander un nouveau code."}`.
- **Réconciliation** : la `transaction_ref` renvoyée par l'opérateur est enregistrée
  automatiquement (plus de saisie manuelle), et n'est exposée que masquée.
- **Sandbox** : en `PAYMENT_SANDBOX=True`, aucun débit réel et le code accepté est celui de
  `PAYMENT_SANDBOX_OTP` (`123456` par défaut) — pratique pour les tests d'intégration Flutter.
- **Flutter** : écran paiement = choix méthode + saisie du numéro → écran de saisie OTP
  (compte à rebours sur `otp_expires_at`, compteur `attempts_remaining`, bouton « Renvoyer le
  code » désactivé 30 s) → reçu PDF. Côté agent : encaissement espèces direct, ou même écran
  OTP pour un paiement mobile au guichet.

---

## 6.9 Colis — `apps/parcels`

### Public
#### `GET /api/v1/parcels/track/{tracking_number}/` · public
Suivi d'un colis (téléphone destinataire masqué).
- **200** → `{ "tracking_number", "status", "status_display", "origin_city",
  "destination_city", "recipient_name", "recipient_phone" (masqué), "current_location",
  "estimated_delivery", "history": [...] }`.
- **Champs supplémentaires** :

  | Champ | Type | Null | Notes |
  |-------|------|------|-------|
  | `current_location` | string | oui | ville courante ; `null` en transit (position intermédiaire inconnue) |
  | `estimated_delivery` | date-time | oui | `trip.arrival_time` tant que le colis n'est pas remis |
  | `history` | `ParcelHistoryEntry[]` | non | chronologie horodatée, triée par `timestamp` |

- **`ParcelHistoryEntry`** : `{ "status" (enum `ParcelStatus`, §5), "status_display",
  "location" (str|null), "timestamp" (date-time), "note" (str|null) }`.
  Exemple :
  ```json
  {
    "status": "notified", "status_display": "Destinataire prevenu",
    "location": "Koudougou", "timestamp": "2026-07-08T07:40:00Z",
    "note": "A bord du bus TB-4821."
  }
  ```
- **Repli** : faute de table d'historique dédiée, la timeline est reconstruite à partir des
  seuls événements horodatés connus (enregistrement, notifications au destinataire, remise). Si
  la liste est incomplète, le front dérive les étapes manquantes (`in_transit`, `arrived`) à
  partir du `status` courant.
- **Flutter** : écran public « Suivre mon colis » (saisie du numéro de suivi) — bandeau
  « Livraison estimée » + timeline avec lieu et horodatage sous chaque étape.

### Agent guichet
| Méthode | URL | Description |
|---------|-----|-------------|
| POST | `/api/v1/agent/parcels/` | Enregistrer un colis (**hors ligne possible**) |
| GET | `/api/v1/agent/parcels/{id}/` | Détail |
| GET | `/api/v1/agent/parcels/arrivals/` | Colis arrivés à sa gare, en attente de notification |
| POST | `/api/v1/agent/parcels/{id}/notify/` | SMS ou appel — body `{ "method": "sms"|"call" }` |

- **POST body** : `origin_city, destination_city, destination_station?, trip?, sender_name,
  sender_phone, recipient_name, recipient_phone, description?, weight_kg (≥0.1),
  tracking_number? (hors ligne), is_offline?, offline_created_at?`.
  **Tarif et `tracking_number` calculés côté serveur** ; compagnie/gare de départ déduites du profil agent.
- **Réponse `201`** = `ParcelRead` (`id`, `tariff`, `tracking_number`, `qr_code`, `status`…) —
  lire directement le colis créé (pas de recherche par `tracking_number` a posteriori).
- **Flutter (agent)** : formulaire d'envoi colis, liste des arrivées, bouton notifier.

### Admin compagnie
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/parcels/` | Tous les colis (filtres : `status`, `destination`, `date_from`, `date_to`) |
| GET | `/api/v1/company/parcels/{id}/` | Détail + historique |
| PATCH | `/api/v1/company/parcels/{id}/` | Modifier (destinataire, expéditeur, description, gare, voyage) |
| POST | `/api/v1/company/parcels/{id}/status/` | Changer le statut — body `{ "status": "collected" }` |
| POST | `/api/v1/company/parcels/{id}/notify-again/` | Renvoyer le SMS |
| GET | `/api/v1/company/parcels/export/` | Export `?format=excel|pdf` |

- **ParcelRead** : `id, tracking_number, company, trip, origin_city, destination_city,
  origin_station, destination_station, sender_name, sender_phone, recipient_name,
  recipient_phone, description, weight_kg, tariff, qr_code, status, status_display,
  collected_at, is_offline, notifications[], history[], created_at, updated_at`.
- **Flutter (company admin)** : tableau colis, détail/historique, changement de statut, export.

---

## 6.10 Réclamations — `apps/claims`

### Voyageur
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/claims/` | Mes réclamations |
| POST | `/api/v1/claims/` | Déposer une réclamation (pièce jointe optionnelle) |
| GET | `/api/v1/claims/{id}/` | Détail + réponse |
| POST | `/api/v1/claims/{id}/attachment/` | Ajouter une pièce jointe (`multipart`) |

- **POST body** : `{ "booking"?: <id>, "company"?: <id>, "claim_type": "retard",
  "subject": "...", "description": "...", "attachment"?: <fichier> }`. Fournir **soit**
  `booking` (la compagnie est déduite du trajet) **soit** `company`. Le `booking` doit
  appartenir au voyageur. La réponse **201** est le `ClaimRead` (id, statut, référence).
- **Pièce jointe** (`attachment`) : envoyée en **`multipart/form-data`**, **PDF ou image**
  (JPEG, PNG, WebP), **10 Mo max** ; sinon `400`. Elle ressort dans `attachments[]`.
- **POST /claims/{id}/attachment/** : ajoute une pièce jointe à une réclamation existante —
  body `multipart` `{ "file": <fichier> }` (mêmes contraintes). Une réclamation peut en porter
  plusieurs. Réponse **201** = le `ClaimRead` à jour.

### Admin compagnie
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/claims/` | Réclamations reçues (filtres : `status`, `claim_type`) — non traitées en tête |
| GET | `/api/v1/company/claims/{id}/` | Détail |
| POST | `/api/v1/company/claims/{id}/respond/` | Répondre — body `{ "response": "...", "status": "resolved" }` |
| GET | `/api/v1/company/claims/stats/` | Taux de résolution + délai moyen |

### Super admin
| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/super/claims/unresolved/` | Réclamations non traitées (toutes compagnies) |
| GET | `/api/v1/super/claims/{id}/` | Détail |
| POST | `/api/v1/super/claims/{id}/escalate/` | Relancer la compagnie |
| POST | `/api/v1/super/claims/{id}/close/` | Clôturer directement |

- **ClaimRead** : `id, company(+name), booking, ticket_number, claim_type(+display),
  subject, description, status(+display), response, responded_at, is_overdue, attachments[],
  created_at, updated_at`. `is_overdue` = vrai si > 48 h sans réponse (annoté).
- **`attachments[]`** : `{ id, file (URL), original_name, content_type, size (octets),
  created_at }`.
- **Flutter** : voyageur → « Mes réclamations » (zone d'upload PDF/photo à la création + ajout
  après coup, affichage des pièces jointes) ; admin → boîte de réclamations + réponse ;
  super → supervision.

---

## 6.11 Signalements d'excès de vitesse — `apps/speed_reports`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| POST | `/api/v1/speed-reports/` | voyageur | Signaler (GPS optionnel, horodatage auto) |
| GET | `/api/v1/company/speed-reports/` | admin | Signalements reçus par la compagnie |
| GET | `/api/v1/company/speed-reports/{id}/` | admin | Détail |
| GET | `/api/v1/super/speed-reports/` | super | Tous les signalements |
| GET | `/api/v1/super/speed-reports/{id}/` | super | Détail |
| PATCH | `/api/v1/super/speed-reports/{id}/` | super | Changer le statut — body `{ "status": "reviewed" }` |

- **POST body** : `{ "company"?, "trip"?, "estimated_speed"?, "severity"?, "description"?,
  "latitude"?, "longitude"?, "reported_at"? }`. Fournir **soit** `company` **soit** `trip`
  (la compagnie en est déduite). La réponse **201** est le `SpeedReportRead` (id, statut).
- **`severity`** (enum `low`/`medium`/`high`, optionnel) : gravité estimée (Faible / Moyenne /
  Grave) — le voyageur ne connaît pas la vitesse exacte. Alimente les puces de la maquette au
  lieu de replier l'info dans `description`.
- **SpeedReportRead** : `id, company(+name), trip, estimated_speed, severity,
  severity_display (null si absent), description, latitude, longitude, reported_at,
  status(+display), created_at`.
- **Flutter** : voyageur → bouton « Signaler un excès de vitesse » (capture GPS + puces
  gravité) ; admin/super → liste des signalements.

---

## 6.12 Avis clients — `apps/reviews`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| GET | `/api/v1/reviews/` | public | Avis publics (`?company_id=<id>`, non signalés) |
| POST | `/api/v1/reviews/` | voyageur | Déposer un avis (après voyage **terminé** + booking payé) |
| GET | `/api/v1/company/reviews/` | admin | Tous les avis de la compagnie (signalés inclus) |
| POST | `/api/v1/company/reviews/{id}/respond/` | admin | Répondre — body `{ "response": "..." }` |
| PATCH | `/api/v1/company/reviews/{id}/respond/` | admin | Modifier la réponse |
| POST | `/api/v1/company/reviews/{id}/flag/` | admin | Signaler l'avis au super admin |
| GET | `/api/v1/company/reviews/word-cloud/` | admin | Fréquence des mots (nuage) |
| GET | `/api/v1/public/testimonials/` | public | Témoignages validés (page d'accueil, `?company_id=`) |
| GET | `/api/v1/super/reviews/` | super | Tous les avis (filtres `company`, `rating`, `is_flagged`, `is_testimonial`) |
| POST | `/api/v1/super/reviews/{id}/testimonial/` | super | Mettre en avant / retirer — body `{ "is_testimonial": true }` |

- **POST body** : `{ "trip": <id>, "rating": 1..5, "comment": "..." }`. La réponse **201** est
  le `ReviewRead` (id + statut) — plus besoin de réinvalider la liste pour récupérer l'avis créé.
- **ReviewRead** : `id, company(+name), trip, author (prénom + initiale), rating, comment,
  response, responded_at, is_flagged, is_testimonial, created_at`.
- **Testimonial** (public) : `id, company(+company_name), author, rating, comment, created_at`.
  Sélection **réservée au super admin** ; un avis `is_flagged` ne peut pas être promu (400).
- **Flutter** : page d'accueil (carrousel de témoignages), fiche compagnie (avis publics),
  formulaire d'avis post-voyage, back-office avis.

---

## 6.13 Messagerie Agent ↔ Client — `apps/messaging`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| GET | `/api/v1/messages/` | auth | Messages reçus/envoyés |
| POST | `/api/v1/messages/` | auth | Envoyer — body `{ "recipient": <user_id>, "subject": "...", "body": "..." }` |
| GET | `/api/v1/messages/{id}/` | auth | Lire (marque comme **lu** si destinataire) |
| GET | `/api/v1/agent/trips/{trip_id}/passenger-list/` | agent | Passagers d'un voyage (choix du destinataire) |

- **MessageRead** : `id, sender(+name), recipient(+name), subject, body, is_read, created_at`.
  `subject` obligatoire quand l'expéditeur est un agent.
- **passenger-list** → `[{ "id", "full_name", "phone" }]`.
- **Flutter** : boîte de messages, composition (agent choisit un passager via passenger-list).

---

## 6.14 Notifications in-app — `apps/notifications`

| Méthode | URL | Auth | Description |
|---------|-----|------|-------------|
| GET | `/api/v1/notifications/` | auth | Mes notifications (non lues d'abord) |
| POST | `/api/v1/notifications/{id}/read/` | auth | Marquer une notification comme lue |
| POST | `/api/v1/notifications/read-all/` | auth | Tout marquer comme lu → `{ "updated": <n> }` |

- **Notification** : `id, type, type_display, title, body, is_read, reference_id,
  reference_type, created_at`. `reference_id`/`reference_type` permettent la navigation
  profonde (ex. ouvrir la réservation liée).
- **Flutter** : cloche de notifications + liste ; badge « non lues ».

---

## 6.15 Synchronisation hors ligne — `apps/sync` (agent)

> **Cœur du mode hors ligne.** L'agent travaille sans internet, stocke localement, puis
> synchronise. Voir aussi les champs `is_offline` / `offline_created_at` des POST agent.

#### `GET /api/v1/agent/offline-data/` · agent
Paquet de travail du jour à mettre en cache local. **Non paginé.**
Schéma OpenAPI : **`AgentOfflineData`** (items : `OfflineTrip`, `OfflineBookingRead`,
`OfflineParcelRead`) — DTO générables directement.
- **200** →
  ```json
  {
    "trips": [ { "id", "origin_city", "destination_city", "departure_time",
                 "available_seats", "vehicle", "seat_plan", "status",
                 "driver_name", "driver_phone" } ],
    "bookings": [ { "ticket_number", "trip_id", "passenger_name", "phone",
                    "seat_number", "qr_code", "status" } ],
    "parcel_arrivals": [ { "tracking_number", "recipient_name", "recipient_phone",
                           "destination_city", "status" } ]
  }
  ```
  `driver_name`/`driver_phone` : `""` (jamais `null`) si non renseignés côté serveur.

#### `POST /api/v1/agent/sync/` · agent
Envoie les données saisies hors ligne (transaction atomique, résolution auto des conflits).
- **Body**
  ```json
  {
    "bookings": [ { "ticket_number": "BF2026...", "trip_id": 12, "first_name": "...",
                    "last_name": "...", "phone": "...", "seat_number": "12",
                    "amount": "3000.00", "payment_method": "orange_money",
                    "transaction_ref": "OM-77889900",
                    "baggage": [ { "label": "Valise rigide", "weight_kg": "18.0",
                                   "location": "hold" } ],
                    "offline_created_at": "2026-07-12T08:30:00Z" } ],
    "parcels": [ { "tracking_number": "...", "origin_city": 1, "destination_city": 2,
                   "sender_name": "...", "sender_phone": "...", "recipient_name": "...",
                   "recipient_phone": "...", "weight_kg": "5.0",
                   "offline_created_at": "..." } ],
    "validations": [ { "ticket_number": "BF2026...", "offline_created_at": "..." } ],
    "parcel_notifications": [ { "tracking_number": "COL2026...", "method": "call",
                                "offline_created_at": "..." } ]
  }
  ```
  Les quatre listes sont optionnelles (défaut `[]`). Le `ticket_number` / `tracking_number`
  généré localement sert de **clé d'idempotence** (pour `parcel_notifications`, le couple
  `tracking_number` + `offline_created_at`).
- **`bookings[].transaction_ref`** : requis si `payment_method ≠ cash` (même règle qu'en
  ligne) → débloque la **vente Mobile Money hors ligne**.
- **`bookings[].baggage`** (optionnel, même forme qu'en ligne — voir §6.7) : bagages pesés
  au guichet hors ligne. Créés `is_offline=true` et rattachés uniquement si la réservation
  est acceptée par la synchronisation (aucun bagage créé pour une réservation rejetée).
- **`parcel_notifications[]`** (« marquer prévenu » hors ligne) : `method` toujours `call`
  (un SMS ne part jamais hors ligne) ; colis introuvable → `errors[]`.
- **200** → schéma OpenAPI **`SyncResult`** (items `SyncResultConflict` / `SyncResultError`)
  ```jsonc
  {
    "synced": { "bookings": 3, "parcels": 1, "validations": 5, "parcel_notifications": 2 },
    "conflicts": [
      { "type": "seat_conflict", "ticket_number": "BF2026000041",
        "original_seat": "12", "assigned_seat": "18",
        "message": "Siege 12 deja attribue. Nouveau siege attribue : 18." }
    ],
    "errors": [
      { "type": "trip_full", "entity": "booking", "reference": "BF2026000043",
        "message": "Voyage complet. Reservation rejetee." }
    ]
  }
  ```
  > **⚠ Formes exactes (ne pas confondre avec `SyncConflict`).** Les descripteurs
  > renvoyés ici sont **transitoires**, différents du modèle `SyncConflict` exposé
  > par `GET /agent/sync/conflicts/` :
  > - **`conflicts[]`** = `{ type, ticket_number, original_seat, assigned_seat, message }`.
  >   N'y figurent **que** les conflits de siège réattribués (`type` toujours
  >   `seat_conflict`, toujours résolus avec succès). Appliquer `assigned_seat`
  >   localement pour corriger le billet.
  > - **`errors[]`** = `{ type, entity, reference, message }` (réponse à la question 2b).
  >   Le message est le champ **`message`** (pas `detail`). `type` ∈ `trip_full` ·
  >   `trip_unavailable` · `invalid` · `seat_conflict` (échec de réattribution) ;
  >   `entity` ∈ `booking` · `parcel` · `validation`. Chaque entrée = une écriture
  >   locale à **marquer en échec**.
  > - **Résolu vs rejeté (question 2c)** : la distinction se lit sur `conflicts[]`
  >   (traité avec succès) **vs** `errors[]` (rejeté), **pas** sur un champ `resolved`.
  >   `trip_full` / `invalid` arrivent donc dans **`errors[]`**, jamais dans `conflicts[]`.
  >   Le champ `resolved` n'existe que sur le modèle `SyncConflict`
  >   (`GET /agent/sync/conflicts/`), où il vaut `true` pour les seuls conflits de siège.

#### `GET /api/v1/agent/sync/logs/` · agent
Historique des synchronisations → `SyncLog` avec `bookings_synced, parcels_synced,
validations_synced, parcel_notifications_synced, conflicts_count, errors_count, conflicts[],
created_at`.

#### `GET /api/v1/agent/sync/conflicts/` · agent
Conflits résolus lors de la **dernière** sync (**non paginé**) → liste de
`{ id, entity, conflict_type(+display), reference, original_seat, assigned_seat,
resolution, resolved, created_at }`.

- **Flutter (agent)** : moteur de synchronisation en arrière-plan (au retour du réseau),
  écran « État de synchronisation » (compteurs + conflits résolus, ex. siège réattribué).

---

## 6.16 Tableaux de bord — `apps/dashboard`

> Tous cachés 5 min, isolés par utilisateur. Les vues « chart » renvoient des **tableaux**
> (non paginés) prêts pour les graphiques.

### Voyageur
#### `GET /api/v1/dashboard/traveler/`
→ `{ next_trips: [{ ticket_number, origin, destination, departure_time, seat_number,
status, company_name, company_sigle }], active_bookings_count, pending_count,
paid_count, cancelled_count, recent_notifications: [{ id, title, body, is_read,
created_at, type, type_display }] }`.

**Champs (ajouts additifs — l'écran devient autosuffisant, un seul appel) :**

| Champ | Emplacement | Type | Nullable | Usage Flutter |
|-------|-------------|------|----------|---------------|
| `company_name` | `next_trips[]` | `string` | non | Ligne « HH:MM · Compagnie » sous chaque trajet |
| `company_sigle` | `next_trips[]` | `string` | oui (`null`) | Fallback compact si pas de place pour le nom |
| `paid_count` | racine | `int` | non | Carte « Statut des billets » → compteur **Payé** |
| `cancelled_count` | racine | `int` | non | Compteur **Annulé** (= `cancelled` + `refunded`) |
| `type` | `recent_notifications[]` | `enum` | non | Clé de mapping **icône + couleur** (voir enum ci-dessous) |
| `type_display` | `recent_notifications[]` | `string` | oui | Libellé FR prêt à afficher (facultatif) |

- **`type`** ∈ `booking · payment · parcel · claim · review · trip · message · system`
  (schéma OpenAPI : `TypeEnum`). Le mapping icône/couleur reste **côté Flutter** ;
  une valeur inconnue doit retomber sur l'icône neutre.
- **`paid_count`** vaut le même total que `active_bookings_count` (statut `paid`),
  exposé séparément pour la carte « Statut des billets » → **supprime l'appel
  supplémentaire à `/bookings/`** qui servait à dériver les compteurs.
- **Rebranchement** : `TravelerTripPreview.companyName`,
  `TravelerNotificationPreview.type`, `_TicketStatusCard` (lire `paid_count` /
  `cancelled_count` au lieu de `myBookingsProvider`).

### Agent
#### `GET /api/v1/agent/dashboard/`
→ `{ next_departures: [{ trip_id, origin, destination, departure_time, available_seats,
passenger_count }], pending_alerts, connection_status }`.

### Company admin (query commun : `period=day|week|month|year`, `start_date`, `end_date`)
| URL | Réponse |
|-----|---------|
| `/api/v1/company/dashboard/` | `{ period, revenue_total, fill_rate_avg, bookings_count, avg_rating, vs_previous_period{...} }` |
| `/api/v1/company/dashboard/revenue-chart/` | `[{ date, revenue }]` |
| `/api/v1/company/dashboard/fill-rate-by-route/` | `[{ route_label, fill_rate_pct }]` |
| `/api/v1/company/dashboard/payment-breakdown/` | `[{ method, amount, pct }]` |
| `/api/v1/company/dashboard/top-routes/` | `[{ route, revenue, passengers }]` |
| `/api/v1/company/dashboard/agent-activity/` | `[{ agent_name, bookings_today, parcels_today }]` |
| `/api/v1/company/dashboard/alerts/` | `{ unresolved_claims, unreturned_parcels, speed_reports_pending }` |
| `/api/v1/company/dashboard/export/` | Fichier `?format=excel|pdf` |

### Super admin
| URL | Réponse |
|-----|---------|
| `/api/v1/super/dashboard/` | `{ total_companies, active_companies, total_bookings, total_commission_revenue, active_users }` |
| `/api/v1/super/dashboard/revenue-by-company/` | `[{ company, revenue, commission }]` |
| `/api/v1/super/dashboard/bookings-chart/` | `[{ date, count }]` (query `period`, `start_date`, `end_date`) |

- **Flutter** : écrans d'accueil par rôle + graphiques (fl_chart / syncfusion).

---

## 6.17 Abonnements — `apps/subscriptions`

### Super admin

| Méthode | URL | Description |
|---------|-----|-------------|
| GET / POST | `/api/v1/super/subscription-plans/` | Forfaits (filtres `is_active`, `duration_months`) |
| GET / PATCH / DELETE | `/api/v1/super/subscription-plans/{id}/` | Détail · modifier · supprimer |
| GET / POST | `/api/v1/super/subscriptions/` | Abonnements (filtres `company`, `plan`, `status`, `auto_renew`) |
| GET / PATCH | `/api/v1/super/subscriptions/{id}/` | Détail · activer/désactiver/prolonger |
| POST | `/api/v1/super/subscriptions/{id}/renew/` | Renouveler (nouvelle période + facture) |

- **Plan** : `{ id, name, description, price, duration_months, features (JSON), is_active, created_at }`.
  `DELETE` → **400** si le forfait est déjà souscrit (désactiver via `is_active: false`).
- **POST subscription body** : `{ company, plan, start_date?, end_date?, auto_renew? }`.
  `end_date` par défaut = `start_date` + `duration_months`. **400** si la compagnie a déjà un
  abonnement en cours. Une facture est émise automatiquement.
- **Subscription** : `{ id, company, company_name, plan{…}, start_date, end_date, status,
  status_display, auto_renew, created_at, days_remaining, is_current, renewal_date }`.

### Company admin (accessible même si la compagnie est suspendue)

| Méthode | URL | Description |
|---------|-----|-------------|
| GET | `/api/v1/company/subscription/` | Forfait courant, échéance (`renewal_date`), statut |
| GET | `/api/v1/company/subscription/invoices/` | Factures (paginé) |
| GET | `/api/v1/company/subscription/invoices/{id}/download/` | Facture en **PDF** (fichier) |

- **Invoice** : `{ id, reference ("FACT-2026-000014"), subscription, plan_name, amount,
  paid_at, created_at, is_paid, download_url }`.
- Si aucun abonnement n'est valide, `GET /company/subscription/` renvoie le **dernier connu**
  avec `is_current: false` (afficher « expiré le … »), ou `404` si la compagnie n'a jamais souscrit.

> ⚠️ **Règle métier** : une compagnie dont l'abonnement est **expiré** est traitée comme
> **suspendue** → `403` sur toutes les autres routes `company_admin`. Seules les routes
> `company/subscription/…` restent ouvertes pour se remettre en règle. Une compagnie n'ayant
> jamais souscrit n'est pas bloquée.
> **Flutter (company admin)** : intercepter le `403` global → écran « Abonnement expiré »
> avec le bouton « Voir mes factures ».

---

## 6.18 Configuration plateforme & audit — `apps/core` (super admin)

| Méthode | URL | Description |
|---------|-----|-------------|
| GET / PATCH | `/api/v1/super/settings/` | Paramètres généraux |
| GET / PATCH | `/api/v1/super/settings/commissions/` | Taux global + surcharges par compagnie |
| GET / PATCH | `/api/v1/super/settings/payment-methods/` | Moyens de paiement au niveau plateforme |
| GET | `/api/v1/super/activity-logs/` | Journal d'audit (paginé) |
| GET | `/api/v1/super/notifications/` | Fil de supervision (paginé) |

- **settings** : `{ platform_name, support_phone, support_email, maintenance_mode,
  sms_provider (lecture seule) }`. La clé API SMS n'est jamais exposée.
- **commissions** : `{ global_rate, company_overrides: [{ company_id, company_name,
  commission_rate }] }`. PATCH : `global_rate` (0–100) et/ou `company_overrides`
  (`commission_rate: null` → retour au taux global).
- **payment-methods** (non paginé) : `[{ method, method_display, is_active }]` pour
  `orange_money · moov_money · coris_money · telecel_money · card`. `cash` est toujours
  disponible et n'apparaît pas dans la liste.
- **activity-logs** — filtres : `user`, `action` (partiel), `entity_type`, `entity_id`,
  `date_from`, `date_to`. Élément : `{ id, user, user_name ("Systeme" si tâche automatique),
  user_role, action, entity_type, entity_id, details, ip_address, created_at }`.
- **notifications** (super admin) — filtres `type`, `severity` ; élément :
  `{ type, severity, title, body, reference_type, reference_id, created_at }`.
  **Calculé à la volée** : ce ne sont pas les notifications in-app de §6.14.
- **Flutter (super admin)** : écrans « Paramètres plateforme », « Commissions »,
  « Journal d'audit » (filtres date/utilisateur/type) et cloche de supervision.

---

# 7. Endpoints prévus mais non encore disponibles

Ces routes figurent dans `docs/specs/endpoints.md` mais **ne sont pas implémentées** — ne
pas les brancher (elles renverront `404`). Prévoir des placeholders ou masquer les écrans.

- `GET /api/v1/agent/trips/{id}/passengers/` — utiliser
  `/api/v1/agent/trips/{id}/passenger-list/` (§6.13)
- Consommation du lien d'invitation d'agent
  (`POST /api/v1/auth/agent/invitation/{token}/`) : l'invitation par SMS existe (§6.2), le
  parcours de création de compte depuis le lien reste à spécifier.
- **Paiement par carte bancaire** (`method: "card"`) : refusé (`400`) tant qu'aucun PSP n'est
  contractualisé.
- **Mobile Money en production** : le flux OTP (§6.8) est complet, mais seul le fournisseur
  **sandbox** est opérationnel (`PAYMENT_SANDBOX=True`, aucun débit réel). Les connecteurs
  Orange / Moov / Coris / Telecel attendent le contrat agrégateur — hors sandbox ils
  renvoient `400`/`503`. Le contrat d'API côté Flutter, lui, ne changera pas.

**Implémenté depuis la dernière révision** : paiement Mobile Money par OTP (§6.8), abonnements
(§6.17), gestion des agents (§6.2), configuration plateforme & audit (§6.18), témoignages
publics (§6.12), impression de billet et historique de scans (§6.7). **Compléments phase 4A** :
compagnie + note + badge direct/escale sur `TripRead` et filtres serveur `company`/`min_rating`
(§6.6) ; timeline colis typée (`ParcelHistoryEntry`) + `current_location`/`estimated_delivery`
(§6.9) ; `routes` desservis + `reviews_count`/`rating_breakdown` et `rating` réellement peuplé
sur les fiches compagnie publiques (§6.2).

**Compléments phase 4C (espace voyageur)** :
- `POST /claims/`, `/reviews/`, `/speed-reports/` renvoient désormais leur sérialiseur de
  **lecture** (id + statut + référence) — écrans de confirmation avec numéro de suivi (§6.10–6.12).
- **`severity`** (`low`/`medium`/`high`) sur les signalements d'excès de vitesse (§6.11).
- **`company_name`/`company_sigle`** sur `BookingRead.trip` — en-tête compagnie du billet (§6.7).
- **`GET /api/v1/payments/`** : liste paginée des paiements du voyageur (§6.8).
- **Bagages** : `baggage[]` + `baggage_total_weight_kg` sur `BookingRead`, écriture `baggage[]`
  à la création agent (§6.7).
- **Pièces jointes de réclamation** : `attachment` (multipart) sur `POST /claims/`, endpoint
  `POST /claims/{id}/attachment/`, `attachments[]` sur `ClaimRead` — PDF/photo, 10 Mo (§6.10).

**Compléments phase 5B (guichet)** :
- `POST /agent/parcels/` : réponse 201 typée `ParcelRead` (tarif + QR lisibles directement) (§6.9).
- **`OfflineBooking.transaction_ref`** (sync) : débloque la vente Mobile Money hors ligne (§6.15).
- **`parcel_notifications[]`** dans `POST /agent/sync/` : « marquer prévenu » (appel) hors ligne,
  + compteur `parcel_notifications_synced` (§6.15).

**Compléments module agent (2026-08-08)** — lèvent les contournements de
`agent_schedule_screen.dart` (« Programme de la semaine ») et « Enregistrer un passager » :
- **`date`** sur `GET /agent/trips/today/` : consulter un autre jour que « aujourd'hui »,
  active le sélecteur de jour au-delà du premier onglet (§6.6).
- **`driver_name`/`driver_phone`** sur `TripRead` et `OfflineTrip` : colonne « Chauffeur »
  du programme agent, guichet et contrôleur (§6.6, §6.15).
- **`gender`**, **`id_type`**/**`id_number`** sur `AgentBookingCreate` : champs
  Homme/Femme et pièce d'identité de l'écran « Enregistrer un passager » (§6.7). Données
  sensibles — jamais renvoyées en lecture.
- **`discount_code`** sur `AgentBookingCreate` : persisté tel quel, aucune validation de
  code encore implémentée côté serveur (§6.7).
- **`OfflineBooking.baggage`** (sync) : un bagage saisi hors ligne au guichet peut désormais
  être transmis à la synchronisation (§6.15).

---

# 8. Correspondance rapide : fonctionnalité Flutter → endpoints

| Module / écran Flutter | Endpoints principaux |
|------------------------|----------------------|
| **Auth & session** | `auth/register`, `auth/login`, `auth/token/refresh`, `auth/logout`, `users/me`, `auth/password/change` |
| **Devenir partenaire (compagnie)** | `auth/company/register` |
| **Accueil voyageur** | `dashboard/traveler`, `public/companies`, `cities`, `notifications` |
| **Recherche & réservation** | `trips/search`, `trips/{id}`, `bookings` (POST/GET), `payments` |
| **Mes billets** | `bookings`, `bookings/{id}/ticket`, `bookings/{id}/cancel` |
| **Mon billet (bagages)** | `bookings/{id}` → `baggage[]` + `baggage_total_weight_kg` |
| **Mon profil — Paiements** | `payments` (GET liste) |
| **Paiement** | `payments`, `payments/{id}/verify-otp`, `payments/{id}/resend-otp`, `payments/{id}/receipt` |
| **Suivi colis (public)** | `parcels/track/{tracking_number}` |
| **Réclamations / avis / signalements (voyageur)** | `claims`, `reviews`, `speed-reports` |
| **Messagerie / notifications** | `messages`, `notifications` |
| **App agent — accueil** | `agent/dashboard`, `agent/trips/today` |
| **App agent — guichet** | `agent/bookings`, `agent/payments`, `agent/parcels` |
| **App agent — contrôle** | `agent/scan`, `agent/trips/{id}/boarding/…` |
| **App agent — hors ligne** | `agent/offline-data`, `agent/sync`, `agent/sync/logs`, `agent/sync/conflicts` |
| **Back-office compagnie** | `company/dashboard/*`, `company/vehicles`, `company/routes`, `company/trips`, `company/stations`, `company/bookings`, `company/parcels`, `company/claims`, `company/reviews`, `company/speed-reports`, `company/settings/*`, `company/agents/*`, `company/subscription/*` |
| **Back-office super admin** | `super/dashboard/*`, `super/companies`, `super/company-requests`, `super/cities`, `super/claims`, `super/speed-reports`, `super/subscription-plans`, `super/subscriptions`, `super/settings/*`, `super/activity-logs`, `super/notifications`, `super/reviews` |
| **Page d'accueil publique** | `public/companies`, `public/testimonials`, `trips/search`, `cities` |

---

*Généré à partir du code source (`apps/*/urls.py`, `views.py`, `serializers.py`,
`models.py`, `config/settings/base.py`) — reflète l'état réel de l'API au moment de la
rédaction. En cas de doute, la source de vérité vivante est `GET /api/docs/` (Swagger).*
