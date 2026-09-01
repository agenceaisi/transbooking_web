# API — App `geography`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Isolation multi-tenant stricte : un `company_admin` n'accède qu'aux gares de **sa propre**
compagnie (résolue via `request.user.administered_company`). Sans compagnie associée → `404`.

---

## Villes

### GET `/api/v1/cities/`

Liste publique des villes desservies. Aucune authentification. Réponse **mise en cache 1h**.
Pas de pagination (liste complète).

```bash
curl "https://api.transbooking.bf/api/v1/cities/"
```

**200 OK**
```json
[
  {"id": 1, "name": "Bobo-Dioulasso", "region": "Hauts-Bassins"},
  {"id": 2, "name": "Ouagadougou", "region": "Centre"}
]
```

### POST `/api/v1/super/cities/`

Ajoute une ville (super admin uniquement).

| Champ    | Type   | Obligatoire | Notes                         |
|----------|--------|-------------|-------------------------------|
| `name`   | string | oui         | unique (insensible à la casse)|
| `region` | string | non         |                               |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/super/cities/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"name": "Koudougou", "region": "Centre-Ouest"}'
```

**201 Created** — `{"id": 3, "name": "Koudougou", "region": "Centre-Ouest"}`
Erreurs : `400` (nom déjà existant), `401`, `403` (pas super admin).

---

## Gares — `IsCompanyAdmin`

CRUD filtré par la compagnie de l'utilisateur courant. La `company` est déduite
automatiquement, jamais fournie par le client.

### GET `/api/v1/company/stations/`

Liste paginée des gares de la compagnie.

### POST `/api/v1/company/stations/`

| Champ          | Type    | Obligatoire | Notes                          |
|----------------|---------|-------------|--------------------------------|
| `city`         | integer | oui         | id d'une `City`                |
| `name`         | string  | oui         |                                |
| `address`      | string  | non         |                                |
| `localisation` | string  | non         | coordonnées GPS texte libre    |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/company/stations/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"city": 2, "name": "Gare centrale", "address": "Av. de la Nation"}'
```

**201 Created**
```json
{
  "id": 5, "city": 2, "city_name": "Ouagadougou",
  "name": "Gare centrale", "address": "Av. de la Nation",
  "localisation": "", "created_at": "...", "updated_at": "..."
}
```

### GET/PATCH/DELETE `/api/v1/company/stations/{id}/`

Détail / modification / suppression d'une gare de la compagnie.
Erreurs : `401`, `403` (pas company admin), `404` (gare d'une autre compagnie ou inexistante).
