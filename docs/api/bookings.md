# API — App `bookings`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Cœur du système. Le siège est réservé sous **verrou ligne** (`select_for_update()` sur le
voyage, cf. `business_rules.md §1`) : pas de surréservation possible. Une contrainte d'unicité
DB `(trip, seat_number)` (hors réservations annulées) garantit qu'un siège actif est unique.

- `ticket_number` : `BF` + année + séquence à 6 chiffres (ex: `BF2026001234`).
- `qr_code` : PNG base64 encodant le `ticket_number` (jamais l'`id` DB).
- Annulation voyageur autorisée **uniquement** jusqu'à 2h avant le départ → sinon `409`.
  L'admin (`company_admin`/`super_admin`) annule sans restriction.
- Mode hors ligne : `is_offline=true` → `synced_at=null`, `ticket_number`/`qr_code` générés
  localement (l'agent fournit le `ticket_number`).
- Attribution des sièges : quand `seat_number` est absent, le **plus petit numéro de
  siège encore libre** (échelle `1..total_seats`) est attribué, guichet et « dernière
  minute » confondus (cf. requetes agent module §4). Un voyage dont `registration_closes_at`
  (voir `docs/api/trips.md`) est dépassé refuse toute nouvelle réservation (`410`), y compris
  si le job de clôture planifié n'est pas encore repassé (bascule appliquée à la volée).

---

## Voyageur — `IsVoyageur`

`get_queryset()` filtré sur `user = request.user`.

### POST `/api/v1/bookings/`

Crée une réservation au statut `pending` (paiement à confirmer). L'identité passager reprend
par défaut le compte voyageur ; le siège est auto-attribué si non fourni.

| Champ         | Type   | Obligatoire | Notes                                  |
|---------------|--------|-------------|----------------------------------------|
| `trip`        | int    | oui         | FK `trips.Trip` (ni annulé ni terminé) |
| `seat_number` | string | non         | auto-attribué si absent                |
| `first_name`  | string | non         | défaut = `user.prenom`                 |
| `last_name`   | string | non         | défaut = `user.nom`                    |
| `phone`       | string | non         | défaut = `user.phone`                  |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/bookings/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"trip": 42}'
```

**201 Created** — `BookingReadSerializer` (`ticket_number`, `qr_code`, `seat_number`, `status`…).
Erreurs : `400`, `401`, `403`, `409` (voyage complet / siège pris), `410` (voyage annulé/terminé).

### GET `/api/v1/bookings/`

Liste paginée de mes réservations.

### GET `/api/v1/bookings/{id}/`

Détail d'une réservation (`BookingReadSerializer`). `404` si réservation d'un autre voyageur.

Le champ `trip` est un résumé embarqué (`TripSummary`) qui porte l'**en-tête compagnie** du
billet (maquette « Mon billet ») :

```json
"trip": {
  "id": 42,
  "origin_city": "Ouagadougou",
  "destination_city": "Bobo-Dioulasso",
  "company_name": "Transport Sahel",
  "company_sigle": "TSA",
  "departure_time": "2026-07-22T07:00:00Z",
  "arrival_time": "2026-07-22T12:00:00Z",
  "status": "scheduled"
}
```

`company_sigle` peut être une chaîne vide si la compagnie n'a pas de sigle configuré.

`BookingRead` porte aussi les **bagages enregistrés** (écran « Bagages ») et le **poids total** :

```json
"baggage": [
  {"id": 1, "label": "Valise rigide", "tag": "TB-B-0042",
   "weight_kg": "18.0", "location": "hold", "location_display": "En soute"},
  {"id": 2, "label": "Sac à dos", "tag": "TB-B-0043",
   "weight_kg": "5.5", "location": "cabin", "location_display": "En cabine"}
],
"baggage_total_weight_kg": "23.5"
```

`location` : `hold` (« En soute ») ou `cabin` (« En cabine »). Les bagages sont pesés et
étiquetés au guichet — voir le champ `baggage[]` de la création agent ci-dessous.

### POST `/api/v1/bookings/{id}/cancel/`

Annule la réservation et **libère le siège** (`available_seats += 1`).

| Champ    | Type   | Obligatoire | Notes              |
|----------|--------|-------------|--------------------|
| `reason` | string | non         | motif d'annulation |

**200 OK** — réservation sérialisée (`status=cancelled`).
Erreurs : `401`, `403`, `404`, `409` (moins de 2h avant le départ).

### GET `/api/v1/bookings/{id}/ticket/`

Télécharge le billet **PDF** (ReportLab) avec QR code.

**200 OK** — `Content-Type: application/pdf`. Erreurs : `401`, `403`, `404`.

---

## Agent guichet — `IsAgentGuichet`

Périmètre résolu via `request.user.agent_profile.company` (sinon `404`).

### POST `/api/v1/agent/bookings/`

Enregistre un passager au guichet (statut `paid` — l'agent encaisse). **Fonctionne hors ligne.**

| Champ                | Type     | Obligatoire | Notes                                          |
|----------------------|----------|-------------|------------------------------------------------|
| `trip`               | int      | oui         | FK `trips.Trip`                                |
| `first_name`         | string   | oui         |                                                |
| `last_name`          | string   | oui         |                                                |
| `phone`              | string   | oui         | format `+226XXXXXXXX`                          |
| `gender`             | string   | non         | `M`·`F` (`""` si non renseigné)                |
| `id_type`            | string   | non         | `none`(défaut)·`cnib`·`passport`               |
| `id_number`          | string   | cond.       | requis si `id_type ≠ none`                     |
| `payment_method`     | string   | oui         | `cash`·`orange_money`·`moov_money`…            |
| `transaction_ref`    | string   | cond.       | requis si `payment_method ≠ cash`              |
| `discount_code`      | string   | non         | code libre, aucune validation serveur pour l'instant |
| `seat_number`        | string   | non         | auto-attribué si absent                        |
| `amount`             | decimal  | non         | défaut = `trip.price`                          |
| `ticket_number`      | string   | cond.       | fourni si saisie hors ligne                    |
| `is_offline`         | bool     | non         | défaut `false`                                 |
| `offline_created_at` | datetime | cond.       | requis si `is_offline=true`                    |
| `baggage`            | list     | non         | bagages pesés à étiqueter (voir ci-dessous)    |

> `id_type`/`id_number` sont des données sensibles : stockées mais **jamais renvoyées**
> dans `BookingReadSerializer` ni dans aucune liste (cf. `mcd.md §7`).
> `discount_code` est persisté tel quel — aucun catalogue de codes n'existe encore côté
> serveur, donc aucun code n'est aujourd'hui rejeté comme invalide/expiré.

Chaque entrée de `baggage[]` : `label` (str, obligatoire), `weight_kg` (decimal, obligatoire),
`location` (`hold`/`cabin`, défaut `hold`). Une étiquette unique `tag` (`TB-B-XXXX`) est
générée par bagage et renvoyée dans `BookingRead.baggage[]`.

```bash
curl -X POST "https://api.transbooking.bf/api/v1/agent/bookings/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"trip": 42, "first_name": "Aminata", "last_name": "TRAORE",
       "phone": "+22670000001", "payment_method": "cash",
       "baggage": [{"label": "Valise rigide", "weight_kg": "18.0"},
                   {"label": "Sac à dos", "weight_kg": "5.5", "location": "cabin"}]}'
```

**201 Created** — `BookingReadSerializer`.
Erreurs : `400` (champ manquant, `transaction_ref` absent), `401`, `403`, `409`, `410`.

### GET `/api/v1/agent/bookings/{ticket_number}/`

Recherche un billet par numéro (jamais par `id`). Filtré sur la compagnie de l'agent.

**200 OK** — `BookingReadSerializer`. Erreurs : `401`, `403`, `404`.

### POST `/api/v1/agent/bookings/{ticket_number}/print/`

Marque le billet comme imprimé (`printed_at`, `print_count`) et renvoie le **payload
d'impression** pour l'imprimante du guichet. Corps vide. Une réimpression est autorisée :
chaque appel incrémente `print_count`.

```bash
curl -X POST https://api.transbooking.bf/api/v1/agent/bookings/BF2026001234/print/   -H "Authorization: Bearer <token>"
```

**200 OK**
```json
{
  "ticket_number": "BF2026001234",
  "passenger_name": "Aminata TRAORE",
  "phone": "+22670000001",
  "seat_number": "A3",
  "amount": "5000.00",
  "status": "paid",
  "company_name": "Transport Sahel",
  "origin_city": "Ouagadougou",
  "destination_city": "Bobo-Dioulasso",
  "departure_time": "2026-07-22T07:00:00Z",
  "qr_code": "<png base64>",
  "printed_at": "2026-07-21T10:05:00Z",
  "print_count": 1
}
```

Erreurs : `401`, `403` (rôle ≠ agent_guichet), `404` (billet inconnu **ou d'une autre
compagnie** — isolation multi-tenant).

### POST `/api/v1/agent/bookings/{ticket_number}/cancel/`

Annule un billet au guichet (erreur de saisie, client qui renonce avant paiement définitif…).
**Pas de restriction propriétaire** contrairement à `POST /bookings/{id}/cancel/` (voyageur) :
tout billet du périmètre de l'agent (sa compagnie) est annulable, **sans contrainte de délai**
avant le départ — l'annulation est initiée par le staff, pas en libre-service voyageur.
L'annulation reste **distincte** d'un remboursement Mobile Money (aucune logique Mobile Money
directe, cf. `CLAUDE.md`) : le statut passe à `cancelled`, jamais `refunded`.

| Champ    | Type   | Obligatoire | Notes              |
|----------|--------|-------------|--------------------|
| `reason` | string | non         | motif d'annulation |

```bash
curl -X POST https://api.transbooking.bf/api/v1/agent/bookings/BF2026001234/cancel/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"reason": "Client absent au guichet"}'
```

**200 OK** — `BookingReadSerializer` (`status=cancelled`).
Erreurs : `401`, `403`, `404` (billet inconnu ou d'une autre compagnie), `409` (billet déjà
embarqué ou remboursé — non annulable).

> **Hors ligne** : un billet créé hors ligne le jour même et **jamais synchronisé** est annulé
> localement (l'agent retire simplement l'entrée de son outbox, aucun appel serveur). Un billet
> **déjà synchronisé** doit passer par cet endpoint en ligne, ou par `cancellations[]` dans
> `POST /agent/sync/` (voir `docs/api/sync.md`) s'il doit être annulé hors ligne.

---

## Contrôleur — embarquement — `IsControleur`

### POST `/api/v1/agent/scan/`

Décode un QR code et renvoie le statut du billet avec **code couleur** (feu tricolore).
Isolation : seul un billet de la compagnie du contrôleur est résolu.

| Champ           | Type   | Obligatoire | Notes                            |
|-----------------|--------|-------------|----------------------------------|
| `qr_data`       | string | cond.       | contenu scanné (= ticket_number) |
| `ticket_number` | string | cond.       | alternative à `qr_data`          |

**200 OK**
```json
{
  "status": "valid",
  "color": "green",
  "message": "Billet valide.",
  "booking": {
    "ticket_number": "BF2026001234",
    "passenger_name": "Aminata TRAORE",
    "seat_number": "A3",
    "status": "paid",
    "trip": {
      "id": 42,
      "origin_city": "Ouagadougou",
      "destination_city": "Bobo-Dioulasso",
      "departure_time": "2026-07-22T07:00:00Z"
    }
  }
}
```
Codes couleur : `green` (payé valide) · `orange` (paiement en attente / déjà embarqué) ·
`red` (annulé / remboursé). Erreurs : `400` (champ manquant), `401`, `403`,
`404` (billet introuvable ou d'une autre compagnie — **toujours** un `404`, jamais un `200`
avec `result: "not_found"`).

### GET `/api/v1/agent/scan/history/` · `IsAgent` (guichet ou contrôleur)

**50 derniers scans de l'agent connecté**, horodatés, du plus récent au plus ancien.
Paginé (`StandardPagination`). Chaque scan — y compris un scan infructueux — est tracé par
`scan_qr()` dans `ScanLog`. Isolation : un agent ne voit que ses propres scans.

**200 OK**
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 88,
      "ticket_number": "BF2026001234",
      "result": "valid",
      "result_display": "Billet valide",
      "passenger_name": "Aminata TRAORE",
      "seat_number": "A3",
      "scanned_at": "2026-07-21T07:12:00Z"
    },
    {
      "id": 87,
      "ticket_number": "BF2026999999",
      "result": "not_found",
      "result_display": "Billet introuvable",
      "passenger_name": null,
      "seat_number": null,
      "scanned_at": "2026-07-21T07:10:00Z"
    }
  ]
}
```

Enum `result` : `valid · unpaid · cancelled · refunded · already_boarded · invalid · not_found`.
Erreurs : `401`, `403` (rôle non agent).

### POST `/api/v1/agent/trips/{id}/boarding/{booking_id}/`

Coche manuellement un passager comme embarqué (idempotent).

**201 Created** — `BoardingValidationSerializer`. Erreurs : `401`, `403`, `404`.

### POST `/api/v1/agent/trips/{id}/boarding/all/`

Embarque tous les passagers payés du voyage. **Confirmation requise.**

| Champ     | Type | Obligatoire | Notes                |
|-----------|------|-------------|----------------------|
| `confirm` | bool | oui         | doit valoir `true`   |

**200 OK** — `{"boarded": <int>}`. Erreurs : `400` (confirmation absente), `401`, `403`, `404`.

### POST `/api/v1/agent/trips/{id}/boarding/validate/`

Verrouille l'embarquement et renvoie le récapitulatif.

**200 OK** — `{"trip", "total_paid", "boarded", "not_boarded", "locked": true}`.

---

## Admin compagnie — `IsCompanyAdmin`

`get_queryset()` filtré sur `trip__route__company = request.user.administered_company`.

### GET `/api/v1/company/bookings/`

Liste paginée filtrable : `?status=`, `?trip=`, `?route=`, `?payment_method=`,
`?date_from=YYYY-MM-DD`, `?date_to=YYYY-MM-DD`.

### GET `/api/v1/company/bookings/export/?format=pdf|excel`

Export des réservations (filtres identiques). `excel` (openpyxl, `.xlsx`) par défaut, `pdf`
(ReportLab). Le paramètre `?format=` est réservé ici à l'export (négociation DRF neutralisée).

**200 OK** — fichier (`application/pdf` ou `…spreadsheetml.sheet`).

---

## Services (`bookings/services.py`)

- `create_booking(validated_data, agent=None) -> Booking` — réserve un siège sous
  `select_for_update()` sur le voyage, génère `ticket_number`/`qr_code`, envoie le SMS de
  confirmation. Lève `TripUnavailable` (410), `TripFull`/`SeatTaken` (409).
- `cancel_booking(booking, cancelled_by, reason="") -> Booking` — annule et libère le siège.
  Lève `CancellationTooLate` (409) si un voyageur annule à moins de 2h du départ, ou
  `BookingNotCancellable` (409) si le billet est déjà embarqué ou remboursé. Les admins et
  l'agent guichet (annulation au guichet) ne sont pas soumis au délai de 2h.
- `scan_qr(qr_data, agent) -> dict` — statut + code couleur du billet (isolation par
  compagnie) ; trace chaque scan dans `ScanLog` (succès comme échec).
- `mark_ticket_printed(booking, agent=None) -> dict` — horodate l'impression, incrémente
  `print_count` et renvoie le payload d'impression.
- `check_in(booking, agent, method) -> BoardingValidation` — enregistre l'embarquement (idempotent).
- `generate_ticket_number() -> str` — séquence `BF{année}{000000}` annuelle.
- `generate_ticket_pdf(booking) -> bytes` — billet PDF avec QR code.
