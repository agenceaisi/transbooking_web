# V03 — Audit d'isolation multi-tenant

- **Date** : 2026-07-02
- **Référence** : `docs/specs/security.md` §3 « Isolation multi-tenant » + CLAUDE.md
- **Périmètre** : preuve qu'aucune donnée d'une compagnie n'est accessible depuis
  le compte d'une autre compagnie, même en connaissant un `id` valide.
- **Test** : `apps/bookings/tests/test_tenant_isolation.py` (6 cas, tous verts)
- **Verdict global** : ✅ **AUCUNE FUITE** — toute tentative croisée renvoie 403 ou 404,
  jamais 200 avec les données d'une autre compagnie.

---

## 1. Méthode

Deux « mondes » complets et étanches sont construits via les fabriques
(`build_world`), chacun avec un `company_admin`, un `agent_guichet`, un
`controleur`, une gare, un trajet, un véhicule, un voyage, une réservation et un
colis. L'authentification passe par un **vrai jeton JWT** (`/api/v1/auth/login/`)
et non `force_authenticate` : l'en-tête `Authorization` est ainsi présent, ce qui
est indispensable pour tester correctement le cache des tableaux de bord
(`cache_page` + `vary_on_headers("Authorization")`).

Chaque assertion croisée vérifie **deux choses** :
1. le code HTTP est `403` ou `404` (jamais `200`) ;
2. aucun marqueur unique de la Compagnie B (immatriculation, nº de suivi, nom du
   passager, nom de gare…) n'apparaît dans le corps de la réponse.

Des **contrôles positifs** (accès intra-compagnie renvoyant `200`) garantissent
que le `404` traduit bien l'isolation et non une panne globale.

---

## 2. Surface testée — `company_admin` (Compagnie A → objets de B)

| Endpoint | Méthodes testées | Résultat | Mécanisme |
|---|---|---|---|
| `/api/v1/company/routes/{B_id}/` | GET · PATCH · DELETE | 404 | `get_queryset()` filtre `company=administered_company` |
| `/api/v1/company/vehicles/{B_id}/` | GET · PATCH · DELETE | 404 | idem (filtre `company`) |
| `/api/v1/company/trips/{B_id}/` | GET · PATCH · DELETE | 404 | filtre `route__company` (DELETE = annulation, bloquée avant) |
| `/api/v1/company/stations/{B_id}/` | GET · PATCH · DELETE | 404 | filtre `company` |
| `/api/v1/company/parcels/{B_id}/` | GET · PATCH | 404 | filtre `company` |
| `/api/v1/company/bookings/` (liste) | GET | 200 sans B | filtre `trip__route__company` |
| `/api/v1/company/bookings/{B_id}/` (détail) | GET | 404 | viewset liste seule (pas de route détail) |
| `/api/v1/company/dashboard/` | GET | chiffres de A uniquement | agrégations scopées `company` |

**Tableau de bord** — scénario : A = 3 paiements (15 000 FCFA), B = 2 paiements
(10 000 FCFA). Réponse de A : `bookings_count == 3`, `revenue_total == 15000.0`.
Les chiffres de B ne fuitent jamais.

---

## 3. Surface testée — `agent_guichet` (agent de A → données de B)

| Endpoint | Résultat | Mécanisme |
|---|---|---|
| `/api/v1/agent/parcels/{B_id}/` | 404 | `get_queryset()` filtre `company_id=agent_profile.company_id` |
| `/api/v1/agent/bookings/{B_ticket}/` | 404 | filtre `trip__route__company_id` (lookup par `ticket_number`) |
| `/api/v1/company/stations/{B_id}/` | 403 | endpoint réservé `IsCompanyAdmin` (mauvais rôle) |
| `/api/v1/company/vehicles/{B_id}/` | 403 | endpoint réservé `IsCompanyAdmin` (mauvais rôle) |

Contrôle positif : `/api/v1/agent/parcels/{A_id}/` → `200`.

---

## 4. Surface testée — `controleur` (contrôleur de A → données de B)

| Endpoint | Résultat | Mécanisme |
|---|---|---|
| `POST /api/v1/agent/scan/` (billet de B) | 404 | `scan_qr()` filtre `trip__route__company_id` puis `Booking.DoesNotExist → 404` |
| `POST /api/v1/agent/trips/{B_id}/boarding/validate/` | 404 | `get_trip()` filtre `route__company_id` |
| `POST /api/v1/agent/trips/{B_id}/boarding/{B_booking}/` | 404 | idem (voyage hors périmètre) |

Contrôle positif : scan du billet de A par le contrôleur de A → `200`.

---

## 5. Observation — endpoint `/company/agents/`

Le scénario d'audit demandait de tester `/api/v1/company/agents/{B_agent_id}/`.
**Cet endpoint n'existe pas** dans le routage actuel : la gestion des agents par le
`company_admin` n'est pas encore exposée en API (aucun `ViewSet` enregistré dans
`apps/users/urls.py` ni `apps/companies/urls.py`). L'URL ne résout donc pas
(`404`) : aucune surface d'attaque, donc aucune fuite possible pour l'instant.

⚠️ **À surveiller** : le jour où un endpoint de gestion des agents sera ajouté,
il devra impérativement filtrer par `company` (via `agent_profile.company` /
`administered_company`) et être couvert par ce test. Le cas
`test_company_agents_management_endpoint_is_absent` sert de sentinelle.

---

## 6. Résultat d'exécution

```
$ python -m pytest apps/bookings/tests/test_tenant_isolation.py -v

test_admin_cannot_touch_other_company_resources ............... PASSED
test_company_bookings_list_never_shows_other_company .......... PASSED
test_company_agents_management_endpoint_is_absent ............. PASSED
test_company_dashboard_reflects_only_own_figures .............. PASSED
test_agent_guichet_cannot_reach_other_company_data ............ PASSED
test_controleur_cannot_scan_or_board_other_company ............ PASSED

6 passed
```

---

## 7. Conclusion

Aucune fuite inter-compagnie détectée sur l'ensemble des ressources scopées
(`routes`, `vehicles`, `trips`, `stations`, `parcels`, `bookings`, `dashboard`)
ni sur les surfaces `agent_guichet` et `controleur`. L'isolation repose
systématiquement sur `get_queryset()` (jamais sur le seul filtrage côté
serializer), conforme à `docs/specs/security.md` §3 et à la checklist §8.

**Recommandation unique** : couvrir tout futur endpoint `/company/agents/` par ce
même test avant sa mise en production.
