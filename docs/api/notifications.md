# API — App `notifications`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Notifications in-app destinées à un utilisateur. Elles sont créées exclusivement via le
service `notifications.services.notify()`, appelé depuis les autres apps (bookings, parcels,
claims…) plutôt qu'en ligne.

- `type` : `booking · payment · parcel · claim · review · trip · message · system`.
- `reference_id` / `reference_type` : lien léger vers l'objet concerné (ex. `reference_type="booking"`,
  `reference_id=42`) permettant au front d'ouvrir la bonne page.
- Isolation : chaque utilisateur ne voit que ses propres notifications.

---

## Voyageur / agent / admin — `IsAuthenticated`

### GET `/api/v1/notifications/`

Liste les notifications de l'utilisateur courant, **non lues d'abord** puis par date décroissante.
Paginé (`StandardPagination`).

```bash
curl https://api.transbooking.bf/api/v1/notifications/ \
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
      "id": 12,
      "type": "booking",
      "type_display": "Reservation",
      "title": "Réservation confirmée",
      "body": "Votre siège A3 est réservé.",
      "is_read": false,
      "reference_id": 42,
      "reference_type": "booking",
      "created_at": "2026-06-30T09:00:00Z"
    }
  ]
}
```

### POST `/api/v1/notifications/{id}/read/`

Marque une notification comme lue. Renvoie la notification mise à jour.

Réponse `200` : objet notification avec `"is_read": true`.

Erreurs : `401` (non authentifié), `404` (notification d'un autre utilisateur).

### POST `/api/v1/notifications/read-all/`

Marque toutes les notifications non lues de l'utilisateur comme lues.

Réponse `200` :

```json
{ "updated": 4 }
```

---

## Service interne — `notify()`

```python
from apps.notifications.services import notify

notify(
    user_id=user.id,
    type="booking",
    title="Réservation confirmée",
    body="Votre siège A3 est réservé.",
    reference_id=booking.id,
    reference_type="booking",
)
```

À appeler depuis les services métier au lieu de créer un objet `Notification` en ligne.
