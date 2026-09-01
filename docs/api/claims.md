# API — App `claims`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Réclamations déposées par un voyageur à l'encontre d'une compagnie.

- `claim_type` : `retard · perte_bagage · bagage_endommage · comportement · surcharge · remboursement · autre`.
- `status` : `submitted → in_progress → resolved → closed`, plus `escalated` (super admin).
- `is_overdue` : annoté à la requête (réclamation `submitted` créée il y a plus de 48h,
  cf. `business_rules.md §5`). Jamais stocké en base.
- Isolation multi-tenant : un admin ne voit que les réclamations de sa compagnie ; un voyageur
  ne voit que les siennes.

---

## Voyageur — `IsVoyageur`

### POST `/api/v1/claims/`

Dépose une réclamation. La compagnie est fournie directement, ou déduite de la réservation
référencée (qui doit appartenir au voyageur).

| Champ         | Type | Obligatoire | Description                                         |
|---------------|------|-------------|-----------------------------------------------------|
| `company`     | int  | Cond.       | Obligatoire si `booking` absent                     |
| `booking`     | int  | Non         | Réservation concernée (déduit la compagnie)         |
| `claim_type`  | str  | Oui         | Type de réclamation                                 |
| `subject`     | str  | Oui         | Objet court                                         |
| `description` | str  | Oui         | Détail                                              |
| `attachment`  | file | Non         | Pièce jointe facultative (`multipart/form-data`)    |

Une pièce jointe (`attachment`) peut accompagner le dépôt en `multipart/form-data` :
**PDF ou image** (JPEG, PNG, WebP), **10 Mo maximum**. Elle est enregistrée comme une
`ClaimAttachment` et ressort dans `attachments[]` de la réponse.

```bash
curl -X POST https://api.transbooking.bf/api/v1/claims/ \
  -H "Authorization: Bearer <token>" \
  -F company=1 -F claim_type=retard -F subject="Retard important" \
  -F description="Deux heures de retard." -F attachment=@recu.pdf
```

Réponse `201` (sérialiseur de lecture) :

```json
{
  "id": 12, "company": 1, "company_name": "STAF", "booking": null, "ticket_number": null,
  "claim_type": "retard", "claim_type_display": "Retard", "subject": "Retard important",
  "status": "submitted", "status_display": "Soumise", "response": "", "responded_at": null,
  "is_overdue": false,
  "attachments": [
    {"id": 3, "file": "/media/claims/attachments/recu.pdf", "original_name": "recu.pdf",
     "content_type": "application/pdf", "size": 20480, "created_at": "2026-06-30T08:00:00Z"}
  ],
  "created_at": "2026-06-30T08:00:00Z"
}
```

Erreurs : `400` (champ manquant, réservation d'un autre voyageur, pièce jointe > 10 Mo ou
type non supporté), `401`, `403` (rôle).

### POST `/api/v1/claims/{id}/attachment/`

Ajoute une pièce jointe à une réclamation existante (`multipart/form-data`). Même contrainte :
PDF/image, 10 Mo max. Une réclamation peut porter plusieurs pièces jointes.

| Champ  | Type | Obligatoire | Description                       |
|--------|------|-------------|-----------------------------------|
| `file` | file | Oui         | PDF ou image, 10 Mo max           |

```bash
curl -X POST https://api.transbooking.bf/api/v1/claims/12/attachment/ \
  -H "Authorization: Bearer <token>" -F file=@photo.jpg
```

Réponse `201` : la réclamation à jour (avec `attachments[]`). Erreurs : `400` (type/taille),
`401`, `403`, `404`.

### GET `/api/v1/claims/` · GET `/api/v1/claims/{id}/`

Liste / détail des réclamations du voyageur courant (avec `is_overdue` et `attachments[]`).

---

## Admin compagnie — `IsCompanyAdmin`

`get_queryset()` filtré sur la compagnie de l'admin ; réclamations non traitées en premier.

### GET `/api/v1/company/claims/`

Liste des réclamations reçues. Filtres : `?status=`, `?claim_type=`.

### GET `/api/v1/company/claims/{id}/`

Détail d'une réclamation.

### POST `/api/v1/company/claims/{id}/respond/`

Répond et change le statut.

| Champ      | Type | Obligatoire | Description                                       |
|------------|------|-------------|---------------------------------------------------|
| `response` | str  | Oui         | Réponse au voyageur                               |
| `status`   | str  | Non         | `in_progress · resolved · closed` (défaut `resolved`) |

Réponse `200` : la réclamation mise à jour. Erreurs : `400` (statut invalide), `403`, `404`.

### GET `/api/v1/company/claims/stats/`

Statistiques de résolution.

```json
{"total": 10, "resolved": 7, "resolution_rate": 70.0, "avg_response_hours": 6.5}
```

---

## Super admin — `IsSuperAdmin`

### GET `/api/v1/super/claims/unresolved/`

Réclamations non traitées (`submitted · in_progress · escalated`) toutes compagnies.

### POST `/api/v1/super/claims/{id}/escalate/`

Escalade la réclamation (`status = escalated`) pour relancer la compagnie.

### POST `/api/v1/super/claims/{id}/close/`

Clôture directement (`status = closed`).

Erreurs communes : `401`, `403` (rôle non super admin), `404`.
