# API — App `messaging`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Messagerie directe entre deux utilisateurs (agent ↔ client). Un agent peut récupérer la liste
des passagers d'un voyage pour choisir un destinataire.

- Chaque utilisateur ne voit que les messages qu'il a envoyés ou reçus.
- L'objet (`subject`) est **obligatoire** lorsque l'expéditeur est un agent (`agent_guichet`
  ou `controleur`).
- La lecture d'un message reçu (`GET /messages/{id}/`) le marque automatiquement comme lu.

---

## Utilisateur authentifié — `IsAuthenticated`

### GET `/api/v1/messages/`

Liste les messages envoyés **et** reçus par l'utilisateur courant, par date décroissante.
Paginé (`StandardPagination`).

```bash
curl https://api.transbooking.bf/api/v1/messages/ \
  -H "Authorization: Bearer <token>"
```

Réponse `200` : liste paginée de messages.

```json
{
  "id": 5,
  "sender": 10,
  "sender_name": "Awa Ouedraogo",
  "recipient": 22,
  "recipient_name": "Test User",
  "subject": "Information voyage",
  "body": "Votre bus part dans 1h.",
  "is_read": false,
  "created_at": "2026-06-30T08:30:00Z"
}
```

### POST `/api/v1/messages/`

Envoie un message. L'expéditeur est l'utilisateur courant.

| Champ       | Type | Obligatoire | Description                                  |
|-------------|------|-------------|----------------------------------------------|
| `recipient` | int  | Oui         | Utilisateur destinataire                     |
| `subject`   | str  | Cond.       | Obligatoire pour un agent                    |
| `body`      | str  | Oui         | Corps du message                             |

```bash
curl -X POST https://api.transbooking.bf/api/v1/messages/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"recipient": 22, "subject": "Information voyage", "body": "Votre bus part dans 1h."}'
```

Réponse `201` : le message créé (sérialiseur de lecture).

Erreurs : `400` (objet manquant pour un agent, destinataire = soi-même), `401`.

### GET `/api/v1/messages/{id}/`

Lit un message. S'il est adressé à l'utilisateur courant, il est marqué comme lu.

Réponse `200` : objet message. Erreurs : `401`, `404`.

---

## Agent — `IsAgent`

### GET `/api/v1/agent/trips/{id}/passenger-list/`

Liste les passagers d'un voyage (titulaires d'un compte, réservation active), pour cibler
un message. Limité aux voyages de la compagnie de l'agent.

```bash
curl https://api.transbooking.bf/api/v1/agent/trips/7/passenger-list/ \
  -H "Authorization: Bearer <token>"
```

Réponse `200` :

```json
[
  { "id": 22, "full_name": "Aminata Traore", "phone": "+22670000001" }
]
```

Erreurs : `401`, `403` (non agent), `404` (voyage inexistant ou d'une autre compagnie).
