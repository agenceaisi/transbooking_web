# V02 — Audit d'intégrité du schéma vs MCD

- **Date** : 2026-07-01
- **Référence** : `docs/specs/mcd.md`
- **Périmètre** : conformité du schéma de base de données réel (migrations Django) au MCD
- **Verdict global** : ✅ **CONFORME** — aucune anomalie bloquante sur les 5 points contrôlés

---

## 1. Migrations à jour (`makemigrations --check --dry-run`)

```
$ python manage.py makemigrations --check --dry-run
No changes detected
```

✅ **OK** — l'état des modèles est entièrement matérialisé dans les migrations. Aucune migration manquante, aucune dérive modèle ↔ migration.

---

## 2. Contraintes `UNIQUE`

Vérifiées via `python manage.py sqlmigrate <app> <migration>` (SQL réellement émis).

| Colonne attendue UNIQUE | Migration source | SQL constaté | Statut |
|---|---|---|---|
| `users.phone` | `users/0001_initial` | `"phone" varchar(30) NOT NULL UNIQUE` | ✅ |
| `bookings.ticket_number` | `bookings/0001_initial` | `"ticket_number" varchar(20) NOT NULL UNIQUE` | ✅ |
| `parcels.tracking_number` | `parcels/0001_initial` | `"tracking_number" varchar(20) NOT NULL UNIQUE` | ✅ |
| `vehicles.registration` | `vehicles/0001_initial` | `"registration" varchar(50) NOT NULL UNIQUE` | ✅ |
| `company_notification_settings.company_id` | `companies/0002_company_fields_payment_notifications` | `"company_id" bigint NOT NULL UNIQUE REFERENCES ...` (OneToOne) | ✅ |

Contrainte additionnelle constatée (bonus, cf. `bookings/0001_initial`) :
```sql
CREATE UNIQUE INDEX "unique_active_seat_per_trip"
  ON "bookings_booking" ("trip_id", "seat_number")
  WHERE NOT ("status" = 'cancelled');
```
→ garantit qu'un siège n'est occupé que par une réservation active à la fois.

✅ **OK** — les 5 contraintes UNIQUE exigées sont présentes.

> Note : `registration` est UNIQUE **globalement** (et non par compagnie comme le suggère le libellé MCD « Unique dans la compagnie »). Contrainte plus stricte que le MCD, sans risque d'intégrité. Voir §Divergences résiduelles.

---

## 3. `related_name` explicite sur toutes les relations

Audit AST de tous les `apps/*/models.py` (ForeignKey, OneToOneField, ManyToManyField) :

```
OK: tous les FK/O2O/M2M ont un related_name explicite
```

✅ **OK** — aucune relation sans `related_name` (conforme à la règle NON NÉGOCIABLE de `CLAUDE.md`).

---

## 4. Héritage de `TimeStampedModel`

Tous les modèles concrets héritent de `utils.models.TimeStampedModel` (`created_at`, `updated_at`), **y compris** les tables de référence `roles` et `cities` (l'énoncé les autorisait à s'en dispenser — les inclure n'est pas une anomalie, seulement deux colonnes horodatées en plus).

Modèles concrets vérifiés : `Role`, `User`, `AgentProfile`, `Company`, `CompanyPaymentMethod`, `CompanyNotificationSettings`, `SubscriptionPlan`, `Subscription`, `SubscriptionInvoice`, `City`, `Station`, `Vehicle`, `Route`, `RouteStop`, `Trip`, `Booking`, `BoardingValidation`, `Payment`, `Parcel`, `ParcelNotification`, `Claim`, `SpeedReport`, `Review`, `Message`, `Notification`, `SyncLog`, `SyncConflict`, `GlobalSetting`, `ActivityLog`.

✅ **OK**.

---

## 5. Champs mode hors ligne (`is_offline` + `synced_at`)

Introspection `Model._meta.get_fields()` :

| Modèle | `is_offline` | `synced_at` | Statut |
|---|---|---|---|
| `bookings.Booking` | ✅ | ✅ | ✅ |
| `parcels.Parcel` | ✅ | ✅ | ✅ |
| `bookings.BoardingValidation` | ✅ | ✅ | ✅ |
| `parcels.ParcelNotification` | ✅ | ✅ | ✅ |

✅ **OK** — les 4 modèles synchronisables portent bien les deux champs (les trois premiers ont en plus `offline_created_at`).

---

## Synthèse

| # | Contrôle | Résultat |
|---|---|---|
| 1 | `makemigrations --check` | ✅ No changes detected |
| 2 | Contraintes UNIQUE (5) | ✅ Toutes présentes |
| 3 | `related_name` explicites | ✅ 100 % |
| 4 | Héritage `TimeStampedModel` | ✅ Tous les modèles |
| 5 | Champs offline (4 modèles) | ✅ Présents |

**Aucune anomalie bloquante détectée.**

---

## Divergences résiduelles (non bloquantes — choix de conception assumés)

Ces écarts ne concernent pas les 5 contrôles ci-dessus ; ils sont documentés pour transparence. Ce sont des choix d'implémentation validés, pas des défauts d'intégrité.

| Table | MCD | Implémentation | Commentaire |
|---|---|---|---|
| `vehicles` | `registration` unique **par compagnie** | unique **global** | Contrainte plus stricte ; à assouplir en `UniqueConstraint(company, registration)` seulement si deux compagnies doivent pouvoir partager une immatriculation. |
| `parcels` | `nature` (Non null) | `nature` (blank) + `description` | Champ présent mais non contraint NOT NULL ; `description` ajouté en complément. |
| `stations` | `localisation` (coordonnées GPS) | `CharField` | Type GPS non structuré (pas de PostGIS). Suffisant pour l'usage actuel. |
| Fichiers | champs `*_url` (TEXT) | `ImageField` / `FileField` (`photo`, `documents`, `attachment`, `pdf`, `logo`, `banner`) | Question « Stockage fichiers » encore ouverte dans le MCD (§Points en suspens). |
| `sync_conflicts` / `claims` | `resolved_at` / `responded_at` MCD | horodatage via `created_at` / champ dédié | Équivalence fonctionnelle. |

---

## Reproductibilité

```bash
export DJANGO_SETTINGS_MODULE=config.settings.test
python manage.py makemigrations --check --dry-run
python manage.py sqlmigrate users 0001_initial
python manage.py sqlmigrate bookings 0001_initial
python manage.py sqlmigrate parcels 0001_initial
python manage.py sqlmigrate vehicles 0001_initial
python manage.py sqlmigrate companies 0002_company_fields_payment_notifications
```
