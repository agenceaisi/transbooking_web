# API — App `reviews`

Préfixe global : `/api/v1/`. Authentification via JWT, sauf la liste publique.

Avis déposés par un voyageur sur un voyage terminé.

- `rating` : entier `1..5`. `comment` facultatif.
- Conditions de dépôt (`business_rules.md §4`) : `trip.status == completed` ET le voyageur
  possède une réservation **payée** sur ce voyage. Un seul avis par couple (voyageur, voyage).
- `is_flagged` : signalé par l'admin de compagnie ; masqué de la liste publique. Seul le super
  admin peut supprimer (l'admin ne le peut pas → `DELETE` renvoie `405`).

---

## Public — `AllowAny`

### GET `/api/v1/reviews/?company_id={id}`

Avis publics (non signalés) d'une compagnie.

| Paramètre    | Type | Emplacement | Notes                          |
|--------------|------|-------------|--------------------------------|
| `company_id` | int  | query       | Filtre par compagnie           |

```bash
curl https://api.transbooking.bf/api/v1/reviews/?company_id=1
```

Réponse `200` (paginée) : liste d'avis `{id, company, company_name, trip, author, rating,
comment, response, responded_at, is_flagged, created_at}`. `author` = prénom + initiale du nom.

---

## Voyageur — `IsVoyageur`

### POST `/api/v1/reviews/`

Dépose un avis (validation métier appliquée côté service).

| Champ     | Type | Obligatoire | Description              |
|-----------|------|-------------|--------------------------|
| `trip`    | int  | Oui         | Voyage terminé           |
| `rating`  | int  | Oui         | Note `1..5`              |
| `comment` | str  | Non         | Commentaire              |

```bash
curl -X POST https://api.transbooking.bf/api/v1/reviews/ \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"trip": 42, "rating": 5, "comment": "Excellent voyage."}'
```

Réponse `201` : l'avis créé. Erreurs : `400` (voyage non terminé, pas de réservation payée,
avis déjà déposé), `401`, `403`.

---

## Admin compagnie — `IsCompanyAdmin`

`get_queryset()` filtré sur la compagnie de l'admin (avis signalés inclus).

### GET `/api/v1/company/reviews/` · GET `/api/v1/company/reviews/{id}/`

Liste / détail des avis de la compagnie.

### POST | PATCH `/api/v1/company/reviews/{id}/respond/`

Répond (ou modifie la réponse) à un avis.

| Champ      | Type | Obligatoire | Description |
|------------|------|-------------|-------------|
| `response` | str  | Oui         | Réponse     |

### POST `/api/v1/company/reviews/{id}/flag/`

Signale un avis inapproprié au super admin (`is_flagged = true`).

### GET `/api/v1/company/reviews/word-cloud/`

Fréquence des mots des commentaires (mots vides et tokens courts exclus).

```json
{"chauffeur": 12, "ponctuel": 9, "confortable": 7}
```

### DELETE `/api/v1/company/reviews/{id}/`

Interdit : `405` (seul le super admin peut supprimer un avis).

Erreurs communes : `401`, `403`, `404`.


---

## Public — témoignages de la page d'accueil — `AllowAny`

### GET `/api/v1/public/testimonials/`

Avis **mis en avant par le super admin** (`is_testimonial=true`) et non signalés.
Paginé. Query param optionnel : `company_id`.

```bash
curl "https://api.transbooking.bf/api/v1/public/testimonials/?company_id=3"
```

**200 OK**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 12,
      "company": 3,
      "company_name": "Transport Sahel",
      "author": "Awa O.",
      "rating": 5,
      "comment": "Service impeccable, bus à l'heure.",
      "created_at": "2026-07-10T08:00:00Z"
    }
  ]
}
```

L'auteur n'est jamais exposé en entier (prénom + initiale du nom).

---

## Super admin — curation — `IsSuperAdmin`

### GET `/api/v1/super/reviews/` · GET `/api/v1/super/reviews/{id}/`

Tous les avis de la plateforme. Filtres : `company`, `rating`, `is_flagged`,
`is_testimonial`. Paginé.

### POST `/api/v1/super/reviews/{id}/testimonial/`

Met un avis en avant sur la page d'accueil publique (ou l'en retire). La curation est
volontairement réservée à la plateforme : une compagnie ne peut pas se mettre elle-même en
vitrine.

| Champ            | Type | Obligatoire | Notes                              |
|------------------|------|-------------|------------------------------------|
| `is_testimonial` | bool | non (défaut `true`) | `false` = retirer de la vitrine |

**200 OK** — l'avis (`ReviewReadSerializer`, champ `is_testimonial` à jour).

Erreurs : `400` (avis signalé — un `is_flagged=true` ne peut pas être promu), `401`,
`403` (rôle ≠ super_admin), `404`.

Action journalisée dans l'audit : `review.testimonial`.
