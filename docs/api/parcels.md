# API — App `parcels`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`),
sauf le suivi public.

Gestion des colis transportés d'une gare à une autre par une compagnie.

- `tracking_number` : `COL` + année + séquence à 6 chiffres (ex: `COL2026000456`).
- `qr_code` : PNG base64 encodant le `tracking_number` (jamais l'`id` DB).
- `tariff` : calculé automatiquement à l'enregistrement (`poids_kg × prix_par_kg + frais_fixes`
  selon la tranche de distance du trajet, cf. `business_rules.md §3`). La grille tarifaire est
  stockée en JSON sur la compagnie (`parcel_pricing_config`, tranches `tier_short` < 100 km,
  `tier_medium` ≤ 300 km, `tier_long` > 300 km).
- Statuts : `registered → in_transit → arrived → notified → collected`.
- Règle anti-doublon SMS : un seul SMS d'arrivée par colis (`409`/`400`). « Notifier à nouveau »
  (admin) contourne la garde.
- Mode hors ligne : `is_offline=true` → `synced_at=null`, `tracking_number` fourni localement.

---

## Public — `AllowAny`

### GET `/api/v1/parcels/track/{tracking_number}/`

Suivi public d'un colis. Renvoie le statut courant, la localisation, l'estimation de livraison
et la chronologie typée des événements. Le téléphone du destinataire est masqué.

| Paramètre         | Type   | Emplacement | Notes                       |
|-------------------|--------|-------------|-----------------------------|
| `tracking_number` | string | path        | Numéro de suivi `COL…`      |

Champs de la réponse (`ParcelTrackSerializer`) :

| Champ                | Type              | Nullable | Notes                                            |
|----------------------|-------------------|----------|--------------------------------------------------|
| `current_location`   | string            | oui      | ville courante ; `null` en transit (inconnue)    |
| `estimated_delivery` | string(date-time) | oui      | `trip.arrival_time` tant que non remis            |
| `history`            | `ParcelHistoryEntry[]` | non | chronologie horodatée (voir ci-dessous)           |

Chaque entrée `history` (`ParcelHistoryEntry`) :

| Champ            | Type              | Nullable | Notes                              |
|------------------|-------------------|----------|------------------------------------|
| `status`         | enum `ParcelStatus`| non     | étape atteinte                     |
| `status_display` | string            | non      | libellé FR                         |
| `location`       | string            | oui      | ville / gare de l'événement        |
| `timestamp`      | string(date-time) | non      | horodatage UTC de l'événement      |
| `note`           | string            | oui      | précision libre                    |

> Faute de table d'historique dédiée, la chronologie est reconstruite à partir des
> seuls événements horodatés connus (enregistrement, notifications au destinataire,
> remise). Le front dérive les étapes manquantes (`in_transit`, `arrived`) à partir
> du statut courant si la liste est incomplète.

```bash
curl https://api.transbooking.bf/api/v1/parcels/track/COL2026000456/
```

Réponse `200` :

```json
{
  "tracking_number": "COL2026000456",
  "status": "in_transit",
  "status_display": "En transit",
  "origin_city": "Ouagadougou",
  "destination_city": "Koudougou",
  "recipient_name": "Salif Kabore",
  "recipient_phone": "********09",
  "current_location": null,
  "estimated_delivery": "2026-07-08T13:45:00Z",
  "history": [
    {
      "status": "registered", "status_display": "Enregistre",
      "location": "Ouagadougou", "timestamp": "2026-07-06T09:12:00Z",
      "note": "Colis enregistre au depot."
    },
    {
      "status": "notified", "status_display": "Destinataire prevenu",
      "location": "Koudougou", "timestamp": "2026-07-08T07:40:00Z",
      "note": "A bord du bus TB-4821."
    }
  ]
}
```

Erreurs : `404` (colis introuvable).

---

## Agent guichet — `IsAgentGuichet`

`get_queryset()` filtré sur la compagnie du profil agent.

### POST `/api/v1/agent/parcels/`

Enregistre un colis (mode hors ligne supporté). La compagnie et la gare de départ proviennent
du profil agent ; le tarif et le `tracking_number` sont calculés côté serveur.

| Champ                 | Type    | Obligatoire | Notes                                   |
|-----------------------|---------|-------------|-----------------------------------------|
| `origin_city`         | int     | oui         | FK `geography.City`                     |
| `destination_city`    | int     | oui         | FK `geography.City` (≠ origine)         |
| `destination_station` | int     | non         | FK `geography.Station`                  |
| `trip`                | int     | non         | FK `trips.Trip` (bus transporteur)      |
| `sender_name`         | string  | oui         |                                         |
| `sender_phone`        | string  | oui         |                                         |
| `recipient_name`      | string  | oui         |                                         |
| `recipient_phone`     | string  | oui         | reçoit les SMS                          |
| `description`         | string  | non         |                                         |
| `weight_kg`           | decimal | oui         | > 0                                     |
| `tracking_number`     | string  | non         | requis en mode hors ligne               |
| `is_offline`          | bool    | non         | défaut `false`                          |
| `offline_created_at`  | datetime| si offline  | date de saisie hors ligne               |

Réponse `201` : objet colis complet (`ParcelReadSerializer`).
Erreurs : `400` (villes identiques, pas de trajet pour pricer le tarif, offline sans date),
`403` (rôle), `404` (profil agent manquant).

### GET `/api/v1/agent/parcels/arrivals/`

Colis arrivés (`status=arrived`) à la gare de l'agent, en attente de notification.

```bash
curl -H "Authorization: Bearer <access>" \
  https://api.transbooking.bf/api/v1/agent/parcels/arrivals/
```

Réponse `200` : liste paginée de colis.

### POST `/api/v1/agent/parcels/{id}/notify/`

Notifie le destinataire : envoie un SMS (`method=sms`, défaut) ou enregistre un appel manuel
(`method=call`). Passe le colis à `notified`.

| Champ    | Type   | Obligatoire | Notes                        |
|----------|--------|-------------|------------------------------|
| `method` | string | non         | `sms` (défaut) ou `call`     |

Réponse `200` : objet colis. Erreurs : `400` (SMS déjà envoyé), `403`, `404`.

---

## Admin compagnie — `IsCompanyAdmin`

`get_queryset()` filtré sur `company = administered_company`.

### GET `/api/v1/company/parcels/`

Liste des colis de la compagnie. Filtres : `status`, `destination` (id ville), `date_from`,
`date_to` (sur `created_at`).

### GET / PATCH `/api/v1/company/parcels/{id}/`

Détail (historique complet + notifications) et mise à jour partielle (destinataire, expéditeur,
description, gare de destination, voyage).

### POST `/api/v1/company/parcels/{id}/status/`

Change le statut manuellement. `collected` horodate `collected_at`.

| Champ    | Type   | Obligatoire | Notes                                   |
|----------|--------|-------------|-----------------------------------------|
| `status` | string | oui         | un statut valide (`registered`…`collected`) |

Réponse `200` : objet colis. Erreurs : `400` (statut invalide), `403`, `404`.

### POST `/api/v1/company/parcels/{id}/notify-again/`

Renvoie le SMS d'arrivée au destinataire en contournant la garde anti-doublon.

Réponse `200` : objet colis.

### GET `/api/v1/company/parcels/export/?format=pdf|excel`

Exporte la liste filtrée. `format=excel` (défaut, repli CSV si openpyxl absent) ou `format=pdf`.
Réponse `200` : fichier en pièce jointe.
