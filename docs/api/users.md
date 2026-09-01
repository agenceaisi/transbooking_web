# API — App `users`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Toutes les routes `auth/*` sont protégées par un rate limit de **10 requêtes POST / minute
par IP** (`django-ratelimit`) ; au-delà → `429 Too Many Requests`.

---

## POST `/api/v1/auth/register/`

Inscription d'un voyageur (public, rôle `voyageur` attribué automatiquement).

| Champ      | Type   | Obligatoire | Notes                                            |
|------------|--------|-------------|--------------------------------------------------|
| `prenom`   | string | oui         | max 100                                          |
| `nom`      | string | oui         | max 100                                          |
| `phone`    | string | oui         | unique, format BF `+226XXXXXXXX` ou `0XXXXXXXX`  |
| `password` | string | oui         | min 8 caractères (write-only)                    |
| `email`    | string | non         | optionnel                                        |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"prenom":"Awa","nom":"Ouedraogo","phone":"+22670000001","password":"password123","email":"awa@example.com"}'
```

**201 Created**
```json
{"prenom": "Awa", "nom": "Ouedraogo", "phone": "+22670000001", "email": "awa@example.com", "role": "voyageur"}
```

Erreurs : `400` (téléphone déjà utilisé, format invalide, mot de passe trop court),
`429` (trop de tentatives).

---

## POST `/api/v1/auth/login/`

Connexion. Retourne les tokens JWT enrichis du rôle et du prénom.

| Champ      | Type   | Obligatoire |
|------------|--------|-------------|
| `phone`    | string | oui         |
| `password` | string | oui         |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"phone":"+22670000001","password":"password123"}'
```

**200 OK**
```json
{"refresh": "<refresh_token>", "access": "<access_token>", "role": "voyageur", "prenom": "Awa"}
```

Erreurs : `400` (champs manquants), `401` (identifiants invalides), `429`.

---

## POST `/api/v1/auth/token/refresh/`

Rafraîchit un token d'accès à partir d'un refresh token valide.

| Champ     | Type   | Obligatoire |
|-----------|--------|-------------|
| `refresh` | string | oui         |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh":"<refresh_token>"}'
```

**200 OK**
```json
{"access": "<new_access_token>"}
```

Erreurs : `400` (champ manquant), `401` (refresh invalide/expiré), `429`.

---

## POST `/api/v1/auth/logout/`

Révoque (blacklist) le refresh token. Authentification requise.

| Champ     | Type   | Obligatoire |
|-----------|--------|-------------|
| `refresh` | string | oui         |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/logout/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"refresh":"<refresh_token>"}'
```

**204 No Content** (corps vide)

Erreurs : `400` (champ manquant, token invalide/expiré), `401` (non authentifié), `429`.

---

## POST `/api/v1/auth/password/change/`

Changement du mot de passe de l'utilisateur connecté. Authentification requise.
Le nouveau mot de passe est soumis aux validateurs Django
(`AUTH_PASSWORD_VALIDATORS` : longueur minimale, mot de passe courant,
mot de passe entièrement numérique, similarité avec les données du compte).

| Champ          | Type   | Obligatoire | Notes                                       |
|----------------|--------|-------------|---------------------------------------------|
| `old_password` | string | oui         | mot de passe actuel (write-only)            |
| `new_password` | string | oui         | write-only, doit différer de `old_password` |

```bash
curl -X POST https://api.transbooking.bf/api/v1/auth/password/change/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"old_password":"password123","new_password":"TransBooking2026"}'
```

**200 OK**
```json
{"detail": "Mot de passe modifie avec succes."}
```

Erreurs :
- `400` — `{"old_password": ["Ancien mot de passe incorrect."]}`
- `400` — `{"new_password": ["Ce mot de passe est trop court...", "..."]}` (validateurs Django)
- `400` — `{"new_password": ["Le nouveau mot de passe doit etre different de l'ancien."]}`
- `401` (non authentifié), `429` (trop de tentatives).

Les tokens JWT déjà émis restent valides après le changement ; le client peut appeler
`/auth/logout/` pour révoquer le refresh token courant.

---

## GET `/api/v1/users/me/`

Profil de l'utilisateur connecté. Authentification requise.

```bash
curl https://api.transbooking.bf/api/v1/users/me/ \
  -H "Authorization: Bearer <access_token>"
```

**200 OK** (voyageur)
```json
{"prenom": "Awa", "nom": "Ouedraogo", "phone": "+22670000001", "email": "awa@example.com",
 "role": "voyageur", "company_name": null, "station": null}
```

**200 OK** (agent guichet, affecté à une gare)
```json
{"prenom": "Issa", "nom": "Kabore", "phone": "+22670000100", "email": null,
 "role": "agent_guichet", "company_name": "Faso Express",
 "station": {"id": 3, "name": "Gare de Ouaga"}}
```

| Champ          | Type   | Nullable | Source                                                        |
|----------------|--------|----------|----------------------------------------------------------------|
| `company_name` | string | oui      | compagnie de l'agent (`agent_profile.company`) ou administrée (`administered_company`) ; `null` pour un voyageur |
| `station`      | object | oui      | `{id, name}` de la gare d'affectation de l'agent (`agent_profile.station`) ; `null` sinon |

> Alimentent l'en-tête agent (« Gare de Ouaga · Guichet ») et le `RoleSidebar` desktop
> (cf. requetes agent module §5).

Erreurs : `401` (non authentifié).

---

## PATCH `/api/v1/users/me/`

Mise à jour partielle du profil. Seuls `phone` et `email` sont modifiables ;
les autres champs envoyés sont ignorés. Authentification requise.

| Champ   | Type   | Obligatoire | Notes                                           |
|---------|--------|-------------|-------------------------------------------------|
| `phone` | string | non         | unique, format BF `+226XXXXXXXX` ou `0XXXXXXXX` |
| `email` | string | non         |                                                 |

```bash
curl -X PATCH https://api.transbooking.bf/api/v1/users/me/ \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"phone":"+22670000005","email":"new@example.com"}'
```

**200 OK**
```json
{"prenom": "Awa", "nom": "Ouedraogo", "phone": "+22670000005", "email": "new@example.com", "role": "voyageur"}
```

Erreurs : `400` (téléphone déjà utilisé, format invalide), `401` (non authentifié).

---

# Gestion des agents par le company admin

Routes réservées au rôle `company_admin` (`IsCompanyAdmin`). **Isolation multi-tenant
stricte** : l'admin ne voit et ne modifie que les agents rattachés à sa propre compagnie
(`AgentProfile.company`) ; tout autre agent renvoie `404`.

Rôles attribuables : `agent_guichet` (→ `agent_type = guichet`) et `controleur`
(→ `agent_type = controleur`). Tout autre rôle → `400`.

## GET `/api/v1/company/agents/`

Liste paginée des agents de la compagnie (triés par nom, prénom).
Filtres : `is_active` (bool), `agent_profile__agent_type` (`guichet · controleur`).

```bash
curl "https://api.transbooking.bf/api/v1/company/agents/?is_active=true" \
  -H "Authorization: Bearer <access_token>"
```

**200 OK**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 42,
      "prenom": "Issa",
      "nom": "Kabore",
      "phone": "+22670000100",
      "email": null,
      "role": "agent_guichet",
      "agent_type": "guichet",
      "station": { "id": 3, "name": "Gare de Ouaga" },
      "is_active": true,
      "created_at": "2026-07-21T10:00:00Z"
    }
  ]
}
```

## POST `/api/v1/company/agents/`

Crée un agent et lui envoie un **mot de passe temporaire par SMS** (jamais renvoyé dans la
réponse HTTP).

| Champ     | Type   | Obligatoire | Notes                                                |
|-----------|--------|-------------|------------------------------------------------------|
| `prenom`  | string | oui         |                                                      |
| `nom`     | string | oui         |                                                      |
| `phone`   | string | oui         | unique, format BF `+226XXXXXXXX` ou `0XXXXXXXX`      |
| `role`    | string | oui         | `agent_guichet` \| `controleur`                      |
| `email`   | string | non         |                                                      |
| `station` | int    | non         | doit appartenir à la compagnie de l'admin, sinon 400 |

```bash
curl -X POST https://api.transbooking.bf/api/v1/company/agents/ \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"prenom":"Issa","nom":"Kabore","phone":"+22670000100","role":"agent_guichet"}'
```

**201 Created** : objet agent (structure ci-dessus).

Erreurs : `400` (téléphone déjà utilisé ou format invalide, rôle non-agent, gare d'une autre
compagnie), `401`, `403` (rôle ≠ company_admin, compagnie suspendue ou abonnement expiré),
`404` (aucune compagnie associée à l'admin).

## GET `/api/v1/company/agents/{id}/`

Détail d'un agent de sa compagnie. Erreurs : `401`, `403`, `404`.

## PATCH `/api/v1/company/agents/{id}/`

Modification, **activation / désactivation** (`is_active`).

| Champ       | Type   | Obligatoire | Notes                                              |
|-------------|--------|-------------|-----------------------------------------------------|
| `prenom`    | string | non         |                                                     |
| `nom`       | string | non         |                                                     |
| `email`     | string | non         |                                                     |
| `is_active` | bool   | non         | `false` = agent désactivé (ne peut plus se connecter) |
| `role`      | string | non         | `agent_guichet` \| `controleur` (met à jour `agent_type`) |
| `station`   | int    | non         | doit appartenir à la compagnie                      |

**200 OK** : objet agent mis à jour.

## DELETE `/api/v1/company/agents/{id}/`

**204** si l'agent n'a aucune activité.

**400** dès qu'il a produit de l'activité (réservations saisies, encaissements,
embarquements validés, synchronisations hors ligne) :

```json
{"detail": ["Cet agent a de l'activite enregistree : desactivez-le (is_active=false) au lieu de le supprimer."]}
```

→ utiliser `PATCH {"is_active": false}`.

## POST `/api/v1/company/agents/{id}/reset-password/`

Génère un nouveau mot de passe temporaire et l'envoie par SMS à l'agent. Corps vide.

**200 OK**
```json
{"detail": "Un mot de passe temporaire a ete envoye par SMS a l'agent."}
```

Erreurs : `400` (agent sans téléphone), `401`, `403`, `404` (agent d'une autre compagnie).

## POST `/api/v1/company/agents/invite/`

Envoie par SMS un **lien de création de compte** portant un jeton signé
(`django.core.signing`, validité `AGENT_INVITE_MAX_AGE_HOURS`, 48 h par défaut). Aucun
compte n'est créé à ce stade.

| Champ    | Type   | Obligatoire | Notes                           |
|----------|--------|-------------|---------------------------------|
| `phone`  | string | oui         | unique, format BF               |
| `role`   | string | oui         | `agent_guichet` \| `controleur` |
| `prenom` | string | non         | pré-remplit le formulaire       |
| `nom`    | string | non         | pré-remplit le formulaire       |

**201 Created**
```json
{
  "detail": "Invitation envoyee par SMS.",
  "phone": "+22670000101",
  "role": "controleur",
  "invite_url": "https://app.transbooking.bf/agents/invitation/<token>",
  "expires_in_hours": 48
}
```

Erreurs : `400` (téléphone déjà utilisé ou invalide, rôle non-agent), `401`, `403`.

> **TODO** : la route de consommation du jeton
> (`POST /api/v1/auth/agent/invitation/{token}/`, création effective du compte + choix du
> mot de passe) reste à spécifier côté parcours front.
