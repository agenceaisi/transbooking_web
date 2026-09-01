# API — App `sync` (synchronisation hors ligne)

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).
Tous les endpoints requièrent le rôle `agent_guichet` **ou** `controleur` (permission `IsAgent`)
et un `AgentProfile` rattaché à une compagnie (sinon `404`).

Moteur de synchronisation différée des données saisies sans connexion par les agents
(cf. `business_rules.md §6`).

- L'intégralité d'une synchronisation s'exécute dans **une seule transaction atomique**.
- **Idempotence** : un `ticket_number` / `tracking_number` déjà synchronisé est ignoré
  silencieusement (un re-`POST` du même lot ne crée rien).
- **Conflit de siège** : si le siège saisi hors ligne est déjà occupé, le prochain siège libre
  est attribué automatiquement et un `SyncConflict` (résolu) est journalisé avec une `resolution`
  en français clair (ex : `Siege A3 deja attribue. Nouveau siege attribue : B7.`).
- **Rejets** : voyage complet (`trip_full`), annulé/terminé (`trip_unavailable`), donnée invalide
  ou hors compagnie (`invalid`) → retournés dans `errors[]` (non résolus).
- **Isolation multi-tenant** : un agent ne synchronise que les voyages/colis de sa compagnie.
- **Ordre d'attribution des sièges** : les réservations d'un même lot sont intégrées dans
  l'ordre chronologique réel de saisie (`offline_created_at`), pas l'ordre d'arrivée dans le
  tableau JSON — « premier enregistré, premier servi » (cf. requetes agent module §4).

---

## POST `/api/v1/agent/sync/`

Synchronise un lot de données hors ligne (réservations, colis, embarquements).

**Auth** : JWT requis — rôle `agent_guichet` ou `controleur`.

**Body (JSON)**

| Champ                  | Type  | Obligatoire | Description                                  |
|------------------------|-------|-------------|----------------------------------------------|
| `bookings`             | array | Non         | Réservations saisies hors ligne              |
| `parcels`              | array | Non         | Colis enregistrés hors ligne                 |
| `validations`          | array | Non         | Embarquements validés hors ligne             |
| `parcel_notifications` | array | Non         | Colis « marqués prévenus » hors ligne (appel)|
| `cancellations`        | array | Non         | Annulations de billets déjà synchronisés     |

Objet `bookings[]` :

| Champ                | Type     | Obligatoire | Description                                |
|----------------------|----------|-------------|--------------------------------------------|
| `ticket_number`      | string   | Oui         | Numéro de billet généré localement (`BF…`) |
| `trip_id`            | int      | Oui         | ID du voyage (de la compagnie de l'agent)  |
| `first_name`         | string   | Oui         | Prénom du passager                         |
| `last_name`          | string   | Oui         | Nom du passager                            |
| `phone`              | string   | Oui         | Téléphone du passager                      |
| `seat_number`        | string   | Non         | Siège saisi (réattribué si déjà pris)      |
| `amount`             | decimal  | Non         | Montant (défaut : prix du voyage)          |
| `payment_method`     | string   | Non         | `cash` · `orange_money` · …                |
| `transaction_ref`    | string   | Cond.       | **Requis si `payment_method ≠ cash`** (Mobile Money) |
| `baggage`            | array    | Non         | Bagages pesés au guichet hors ligne (voir ci-dessous) |
| `offline_created_at` | datetime | Oui         | Date de saisie hors ligne                  |

`transaction_ref` applique la **même règle** que la création directe
(`POST /agent/bookings/`) : une vente non-espèces sans référence rejette le lot (`400`).
Cela débloque la vente Mobile Money **hors ligne** (auparavant limitée aux espèces).

Chaque entrée de `baggage[]` : `label` (str, obligatoire), `weight_kg` (decimal, obligatoire),
`location` (`hold`/`cabin`, défaut `hold`) — même forme que `POST /agent/bookings/`
(`BaggageWrite`). Les bagages sont créés `is_offline=true` et rattachés à la réservation
une fois celle-ci synchronisée avec succès (aucun bagage n'est créé pour une réservation
rejetée — voir « Rejets » ci-dessus).

Objet `parcels[]` :

| Champ                  | Type     | Obligatoire | Description                              |
|------------------------|----------|-------------|------------------------------------------|
| `tracking_number`      | string   | Oui         | Numéro de suivi généré localement (`COL…`) |
| `origin_city`          | int      | Oui         | ID ville de départ                       |
| `destination_city`     | int      | Oui         | ID ville d'arrivée                       |
| `destination_station`  | int      | Non         | ID gare d'arrivée (même compagnie)       |
| `trip`                 | int      | Non         | ID voyage transporteur (même compagnie)  |
| `sender_name`          | string   | Oui         | Nom expéditeur                           |
| `sender_phone`         | string   | Oui         | Téléphone expéditeur                     |
| `recipient_name`       | string   | Oui         | Nom destinataire                         |
| `recipient_phone`      | string   | Oui         | Téléphone destinataire                   |
| `description`          | string   | Non         | Description du colis                     |
| `weight_kg`            | decimal  | Oui         | Poids (sert au calcul du tarif)          |
| `offline_created_at`   | datetime | Oui         | Date de saisie hors ligne                |

Objet `validations[]` :

| Champ                | Type     | Obligatoire | Description                            |
|----------------------|----------|-------------|----------------------------------------|
| `ticket_number`      | string   | Oui         | Billet embarqué (de la compagnie)      |
| `offline_created_at` | datetime | Oui         | Date de validation hors ligne          |

Objet `parcel_notifications[]` :

| Champ                | Type     | Obligatoire | Description                                     |
|----------------------|----------|-------------|-------------------------------------------------|
| `tracking_number`    | string   | Oui         | Colis à marquer prévenu (de la compagnie)       |
| `method`             | string   | Non         | Toujours `call` (seul l'appel manuel est hors ligne) |
| `offline_created_at` | datetime | Oui         | Date du « marquage prévenu » hors ligne         |

> **Seul l'appel manuel (`call`) est synchronisable** : un SMS ne peut pas partir hors ligne
> (l'app ne doit jamais laisser croire qu'un SMS a été envoyé). Le couple
> (`tracking_number`, `offline_created_at`) est la **clé d'idempotence** ; un colis introuvable
> ressort dans `errors[]`.

Objet `cancellations[]` :

| Champ                | Type     | Obligatoire | Description                                     |
|----------------------|----------|-------------|--------------------------------------------------|
| `ticket_number`      | string   | Oui         | Billet à annuler (doit déjà exister côté serveur) |
| `reason`             | string   | Non         | Motif d'annulation                                |
| `offline_created_at` | datetime | Oui         | Date de l'annulation hors ligne                   |

> Ne concerne qu'un billet **déjà synchronisé** avant la coupure : un billet créé hors ligne et
> jamais synchronisé est annulé localement (l'agent retire l'entrée de son outbox, aucun appel
> serveur nécessaire — cf. `docs/api/bookings.md`). Idempotent : une annulation déjà intégrée
> (billet déjà `cancelled`) est ignorée silencieusement. Un billet introuvable pour la compagnie,
> déjà embarqué ou déjà remboursé ressort dans `errors[]`.

**Exemple de requête**

```bash
curl -X POST https://api.transbooking.bf/api/v1/agent/sync/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "bookings": [
      {
        "ticket_number": "BF2026001234",
        "trip_id": 42,
        "first_name": "Aminata",
        "last_name": "TRAORE",
        "phone": "+22670000001",
        "seat_number": "A3",
        "amount": "5000.00",
        "payment_method": "cash",
        "offline_created_at": "2026-06-01T08:23:00Z"
      }
    ],
    "parcels": [],
    "validations": []
  }'
```

**Réponse `200`**

```json
{
  "synced": {
    "bookings": 1, "parcels": 0, "validations": 0,
    "parcel_notifications": 0, "cancellations": 0
  },
  "conflicts": [
    {
      "type": "seat_conflict",
      "ticket_number": "BF2026001234",
      "original_seat": "A3",
      "assigned_seat": "B7",
      "message": "Siege A3 deja attribue. Nouveau siege attribue : B7."
    }
  ],
  "errors": []
}
```

**Erreurs** : `400` (payload invalide), `401` (non authentifié), `403` (rôle non agent),
`404` (aucun profil agent).

---

## GET `/api/v1/agent/sync/logs/`

Historique paginé des synchronisations de l'agent courant (le plus récent en premier).

**Réponse `200`** (extrait `results[]`)

```json
{
  "id": 12,
  "bookings_synced": 3,
  "parcels_synced": 1,
  "validations_synced": 5,
  "parcel_notifications_synced": 0,
  "cancellations_synced": 0,
  "conflicts_count": 2,
  "errors_count": 0,
  "conflicts": [
    {
      "id": 7,
      "entity": "booking",
      "conflict_type": "seat_conflict",
      "conflict_type_display": "Conflit de siege",
      "reference": "BF2026001234",
      "original_seat": "A3",
      "assigned_seat": "B7",
      "resolution": "Siege A3 deja attribue. Nouveau siege attribue : B7.",
      "resolved": true,
      "created_at": "2026-06-01T09:00:00Z"
    }
  ],
  "created_at": "2026-06-01T09:00:00Z"
}
```

---

## GET `/api/v1/agent/sync/conflicts/`

Conflits **résolus** (siège réattribué) lors de la **dernière** synchronisation de l'agent.
Non paginé. Renvoie `[]` si l'agent n'a jamais synchronisé.

**Réponse `200`**

```json
[
  {
    "id": 7,
    "entity": "booking",
    "conflict_type": "seat_conflict",
    "conflict_type_display": "Conflit de siege",
    "reference": "BF2026001234",
    "original_seat": "A3",
    "assigned_seat": "B7",
    "resolution": "Siege A3 deja attribue. Nouveau siege attribue : B7.",
    "resolved": true,
    "created_at": "2026-06-01T09:00:00Z"
  }
]
```

---

## GET `/api/v1/agent/offline-data/`

Télécharge tout ce dont l'agent a besoin pour travailler hors ligne aujourd'hui, dans le
périmètre de sa gare et/ou de son véhicule (voyages du jour non annulés, réservations actives
de ces voyages, colis arrivés en attente de remise). Non paginé.

**Réponse `200`**

```json
{
  "trips": [
    {
      "id": 42,
      "origin_city": "Ouagadougou",
      "destination_city": "Bobo-Dioulasso",
      "departure_time": "2026-06-30T06:00:00Z",
      "registration_closes_at": "2026-06-30T06:00:00Z",
      "available_seats": 18,
      "vehicle": "11-AA-0042",
      "vehicle_type": "vip",
      "total_seats": 30,
      "seat_plan": { "layout": [[1, 2], [3, 4]], "reserved": [0] },
      "status": "scheduled",
      "driver_name": "Salif Traore",
      "driver_phone": "+22670001122"
    }
  ],
  "bookings": [
    {
      "id": 1017,
      "ticket_number": "BF2026001234",
      "trip_id": 42,
      "passenger_name": "Aminata TRAORE",
      "phone": "+22670000001",
      "seat_number": "A3",
      "qr_code": "<base64-png>",
      "status": "paid"
    }
  ],
  "parcel_arrivals": [
    {
      "tracking_number": "COL2026000456",
      "recipient_name": "Fatou DIALLO",
      "recipient_phone": "+22660000011",
      "destination_city": "Bobo-Dioulasso",
      "status": "arrived"
    }
  ]
}
```

**Erreurs** : `401` (non authentifié), `403` (rôle non agent), `404` (aucun profil agent).

> `bookings[].id` (numérique) permet d'appeler directement
> `POST /agent/trips/{trip_id}/boarding/{booking_id}/` sans aller-retour réseau
> supplémentaire pour résoudre l'id à partir du `ticket_number` (cf. requetes agent module §7).
> `trips[].vehicle_type`/`total_seats` alimentent le badge véhicule et la barre de progression
> d'embarquement même en cache hors ligne (cf. requetes agent module §4).
