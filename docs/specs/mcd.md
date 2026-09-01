# docs/specs/mcd.md
# Modèle Conceptuel de Données — TransBooking BF
# Source : TransBooking_BF_MCD.docx
# Référencé par CLAUDE.md — charger uniquement pour les tâches liées aux modèles DB

---

## Vue d'ensemble des tables (15 groupes)

| # | Groupe | Tables |
|---|--------|--------|
| 1 | Utilisateurs & Auth | `roles`, `users`, `agent_profiles` |
| 2 | Compagnies | `companies`, `company_payment_methods`, `company_notification_settings` |
| 3 | Abonnements | `subscription_plans`, `company_subscriptions`, `subscription_invoices` |
| 4 | Géographie | `cities`, `stations` |
| 5 | Véhicules | `vehicles` |
| 6 | Trajets & Horaires | `routes`, `route_stops`, `trips` |
| 7 | Réservations & Billets | `bookings`, `payments`, `boarding_validations` |
| 8 | Colis | `parcels`, `parcel_notifications` |
| 9 | Réclamations | `claims` |
| 10 | Signalements vitesse | `speed_reports` |
| 11 | Avis clients | `reviews` |
| 12 | Messagerie | `messages` |
| 13 | Notifications | `notifications` |
| 14 | Sync hors ligne | `sync_logs`, `sync_conflicts` |
| 15 | Config & Audit | `global_settings`, `activity_logs` |

---

## 1. Utilisateurs & Authentification

### `roles`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| name | VARCHAR(50) | Non | `super_admin` · `company_admin` · `agent_guichet` · `controleur` · `voyageur` |

### `users`
Modèle central. `phone` = identifiant principal. `email` optionnel.

| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| prenom | VARCHAR(100) | Non | Affiché sur le billet |
| nom | VARCHAR(100) | Non | En majuscules à l'impression |
| email | VARCHAR(150) | **Oui** | Optionnel |
| phone | VARCHAR(20) | Non | **Unique** — identifiant de connexion |
| password | VARCHAR(255) | Non | Hashé (bcrypt) |
| role_id | INTEGER FK | Non | → `roles.id` |
| is_active | BOOLEAN | Non | Défaut : TRUE |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

### `agent_profiles`
Complète le profil d'un agent. `station_id` OU `vehicle_id` selon le type.

| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Non | → `users.id` |
| company_id | INTEGER FK | Non | Compagnie d'appartenance |
| agent_type | VARCHAR(20) | Non | `guichet` · `controleur` |
| station_id | INTEGER FK | **Oui** | Gare (agent guichet) |
| vehicle_id | INTEGER FK | **Oui** | Véhicule (contrôleur) |

---

## 2. Compagnies

### `companies`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| name | VARCHAR(150) | Non | Raison sociale |
| responsible_name | VARCHAR(150) | Oui | |
| phone | VARCHAR(20) | Oui | |
| email | VARCHAR(150) | Oui | |
| address | TEXT | Oui | |
| city | VARCHAR(100) | Oui | |
| status | VARCHAR(20) | Non | `pending` · `active` · `suspended` · `rejected` |
| commission_rate | NUMERIC(5,2) | Oui | Taux spécifique (sinon → `global_settings`) |
| primary_color | VARCHAR(7) | Oui | Format `#RRGGBB` |
| welcome_message | TEXT | Oui | |
| banner_url | TEXT | Oui | |
| documents_url | TEXT | Oui | Docs administratifs soumis |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

### `company_payment_methods`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| method | VARCHAR(30) | Non | `cash` · `orange_money` · `moov_money` · `coris_money` · `telecel_money` · `card` |
| is_active | BOOLEAN | Non | Défaut : TRUE |

### `company_notification_settings`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | **UNIQUE** → `companies.id` |
| sms_departure_reminder | BOOLEAN | Non | Défaut : TRUE |
| sms_parcel_arrival | BOOLEAN | Non | Défaut : TRUE |
| sms_claim_response | BOOLEAN | Non | Défaut : TRUE |

---

## 3. Abonnements

### `subscription_plans`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| name | VARCHAR(50) | Non | Ex : `Mensuel Standard` |
| duration_months | INTEGER | Non | `1` = mensuel · `12` = annuel |
| price | NUMERIC(12,2) | Non | En FCFA |
| features | JSONB | Oui | Avantages inclus (flexible) |
| is_active | BOOLEAN | Non | Plan encore proposé |

### `company_subscriptions`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| plan_id | INTEGER FK | Non | → `subscription_plans.id` |
| status | VARCHAR(20) | Non | `active` · `expired` · `cancelled` |
| started_at | DATE | Non | |
| expires_at | DATE | Non | **Alerte 7j avant** |
| auto_renew | BOOLEAN | Non | Défaut : FALSE |
| created_at | TIMESTAMPTZ | Non | |

### `subscription_invoices`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| subscription_id | INTEGER FK | Non | → `company_subscriptions.id` |
| amount | NUMERIC(12,2) | Non | En FCFA |
| paid_at | TIMESTAMPTZ | Oui | NULL = en attente |
| pdf_url | TEXT | Oui | Lien vers la facture PDF |
| created_at | TIMESTAMPTZ | Non | |

---

## 4. Géographie

### `cities`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| name | VARCHAR(100) | Non | Ex : `Ouagadougou` |
| region | VARCHAR(100) | Oui | Région administrative |

### `stations`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| city_id | INTEGER FK | Non | → `cities.id` |
| name | VARCHAR(150) | Non | Ex : `Gare principale de Ouaga` |
| address | TEXT | Oui | |
| localisation | — | Oui | Coordonnées GPS |

---

## 5. Véhicules

### `vehicles`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| registration | VARCHAR(50) | Non | **Unique** dans la compagnie |
| brand | VARCHAR(50) | Oui | Ex : `Mercedes`, `Scania` |
| model | VARCHAR(50) | Oui | |
| vehicle_type | VARCHAR(30) | Oui | `bus` · `minibus` · `4x4` |
| total_seats | INTEGER | Non | **Capacité** — conditionne les réservations |
| status | VARCHAR(20) | Non | `active` · `maintenance` · `inactive` |
| created_at | TIMESTAMPTZ | Non | |

> **Règle** : `status = maintenance` → véhicule non assignable à un voyage.

---

## 6. Trajets & Horaires

### `routes`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| origin_city_id | INTEGER FK | Non | → `cities.id` |
| dest_city_id | INTEGER FK | Non | → `cities.id` |
| distance_km | NUMERIC(8,2) | Oui | Pour calcul tarif colis |
| base_price | NUMERIC(12,2) | Non | Prix de référence en FCFA |
| is_active | BOOLEAN | Non | |
| created_at | TIMESTAMPTZ | Non | |

### `route_stops`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| route_id | INTEGER FK | Non | → `routes.id` |
| city_id | INTEGER FK | Non | → `cities.id` |
| stop_order | INTEGER | Non | Ordre de passage (1, 2, 3…) |
| nom_ville_stop | TEXT | Oui | Nom affiché |
| stop_price | NUMERIC(12,2) | Oui | Prix depuis le départ jusqu'à cet arrêt |

### `trips`
Un voyage = instance réelle d'une route à une date/heure précise.

| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| route_id | INTEGER FK | Non | → `routes.id` |
| vehicle_id | INTEGER FK | Non | → `vehicles.id` |
| driver_name | VARCHAR(150) | Oui | |
| departure_time | TIMESTAMPTZ | Non | Date et heure de départ |
| arrival_time | TIMESTAMPTZ | Oui | |
| status | VARCHAR(20) | Non | `scheduled` · `in_progress` · `delayed` · `cancelled` · `completed` |
| delay_minutes | INTEGER | Non | Défaut : 0 |
| available_seats | INTEGER | Non | ⚠️ Décrémenté avec `select_for_update()` |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

---

## 7. Réservations & Billets

### `bookings`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| trip_id | INTEGER FK | Non | → `trips.id` |
| user_id | INTEGER FK | **Oui** | NULL = réservation guichet sans compte |
| agent_id | INTEGER FK | **Oui** | Agent guichet ayant saisi |
| ticket_number | VARCHAR(20) | Non | **Unique** — format `BF2026XXXXXX` |
| first_name | VARCHAR(100) | Non | |
| last_name | VARCHAR(100) | Non | |
| phone | VARCHAR(20) | Non | SMS de confirmation |
| gender | CHAR(1) | Oui | `M` / `F` |
| id_type | VARCHAR(20) | Oui | `CNIB` · `passeport` |
| id_number | VARCHAR(50) | Oui | ⚠️ Champ sensible — exclure des listes |
| seat_number | VARCHAR(10) | Oui | Ex : `A3` |
| origin_city_id | INTEGER FK | Oui | Ville de montée (peut différer du départ) |
| dest_city_id | INTEGER FK | Oui | Ville de descente |
| has_luggage | BOOLEAN | Non | Défaut : FALSE |
| luggage_qty | INTEGER | Oui | |
| amount | NUMERIC(12,2) | Non | Montant payé en FCFA |
| discount_code | VARCHAR(30) | Oui | Code de réduction appliqué |
| status | VARCHAR(20) | Non | `pending` · `paid` · `cancelled` · `refunded` |
| qr_code | TEXT | Oui | Base64 PNG — encode `ticket_number` |
| is_offline | BOOLEAN | Non | Défaut : FALSE |
| synced_at | TIMESTAMPTZ | Oui | NULL = pas encore synchronisé |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

### `payments`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| booking_id | INTEGER FK | Oui | NULL si paiement colis |
| parcel_id | INTEGER FK | Oui | NULL si paiement réservation |
| method | VARCHAR(30) | Non | `cash` · `orange_money` · `moov_money` · `coris_money` · `card` |
| phone | VARCHAR(20) | Oui | Numéro Mobile Money |
| transaction_ref | VARCHAR(100) | Oui | ⚠️ Référence Mobile Money (saisie manuelle) |
| amount | NUMERIC(12,2) | Non | |
| status | VARCHAR(20) | Non | `pending` · `paid` · `failed` · `refunded` |
| paid_at | TIMESTAMPTZ | Oui | |
| receipt_url | TEXT | Oui | |
| created_at | TIMESTAMPTZ | Non | |

### `boarding_validations`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| booking_id | INTEGER FK | Non | → `bookings.id` |
| agent_id | INTEGER FK | Non | Contrôleur ayant validé |
| validated_at | TIMESTAMPTZ | Non | Heure exacte du scan |
| is_offline | BOOLEAN | Non | |
| synced_at | TIMESTAMPTZ | Oui | |

---

## 8. Colis

### `parcels`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| company_id | INTEGER FK | Non | → `companies.id` |
| trip_id | INTEGER FK | Oui | Voyage transporteur |
| agent_id | INTEGER FK | Non | Agent guichet |
| tracking_number | VARCHAR(20) | Non | **Unique** — format `COL2026XXXXXX` |
| sender_name | VARCHAR(150) | Non | |
| sender_phone | VARCHAR(20) | Non | |
| sender_city_id | INTEGER FK | Non | → `cities.id` |
| recipient_name | VARCHAR(150) | Non | Sur bordereau et SMS |
| recipient_phone | VARCHAR(20) | Non | Reçoit le SMS d'arrivée |
| recipient_city_id | INTEGER FK | Non | → `cities.id` |
| nature | VARCHAR(100) | Non | Ex : `vêtements`, `documents` |
| weight_kg | NUMERIC(8,2) | Non | Sert au calcul du tarif |
| length_cm | NUMERIC(8,2) | Oui | |
| width_cm | NUMERIC(8,2) | Oui | |
| height_cm | NUMERIC(8,2) | Oui | |
| declared_value | NUMERIC(12,2) | Non | En FCFA — couverture perte/dommage |
| is_fragile | BOOLEAN | Non | Mention FRAGILE sur étiquette si TRUE |
| photo_url | TEXT | Oui | |
| tariff | NUMERIC(12,2) | Non | Calculé automatiquement |
| status | VARCHAR(20) | Non | `registered` · `in_transit` · `arrived` · `notified` · `collected` |
| qr_code | TEXT | Oui | Suivi public — encode `tracking_number` |
| is_offline | BOOLEAN | Non | |
| synced_at | TIMESTAMPTZ | Oui | |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

### `parcel_notifications`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| parcel_id | INTEGER FK | Non | → `parcels.id` |
| agent_id | INTEGER FK | Non | |
| method | VARCHAR(20) | Non | `sms` · `call_manual` |
| notified_at | TIMESTAMPTZ | Non | |
| is_offline | BOOLEAN | Non | |
| synced_at | TIMESTAMPTZ | Oui | |

> **Règle** : maximum 1 SMS par colis. Vérifier avant envoi.

---

## 9. Réclamations

### `claims`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Non | → `users.id` |
| company_id | INTEGER FK | Non | → `companies.id` |
| booking_id | INTEGER FK | Oui | |
| ticket_number | VARCHAR(20) | Oui | Saisi manuellement si pas de compte |
| claim_type | VARCHAR(50) | Non | `retard` · `perte_bagage` · `bagage_endommage` · `comportement` · `surcharge` · `remboursement` · `autre` |
| description | TEXT | Non | |
| travel_date | DATE | Oui | |
| attachment_url | TEXT | Oui | |
| status | VARCHAR(20) | Non | `submitted` · `in_progress` · `resolved` |
| admin_response | TEXT | Oui | |
| responded_at | TIMESTAMPTZ | Oui | |
| created_at | TIMESTAMPTZ | Non | |
| updated_at | TIMESTAMPTZ | Non | |

> **Règle** : réclamation sans réponse après 48h → annoter `is_overdue=True` en queryset (ne pas stocker).

---

## 10. Signalements excès de vitesse

### `speed_reports`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Non | Voyageur |
| trip_id | INTEGER FK | Oui | |
| company_id | INTEGER FK | Non | |
| description | TEXT | Oui | |
| latitude | NUMERIC(10,7) | Oui | GPS optionnel |
| longitude | NUMERIC(10,7) | Oui | |
| reported_at | TIMESTAMPTZ | Non | Auto-horodatage |
| status | VARCHAR(20) | Non | `pending` · `reviewed` · `closed` |

---

## 11. Avis Clients

### `reviews`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Non | → `users.id` |
| company_id | INTEGER FK | Non | → `companies.id` |
| trip_id | INTEGER FK | Oui | |
| rating | SMALLINT | Non | 1 à 5 étoiles |
| comment | TEXT | Oui | |
| admin_response | TEXT | Oui | Réponse publique |
| responded_at | TIMESTAMPTZ | Oui | |
| is_flagged | BOOLEAN | Non | Signalé pour modération super admin |
| created_at | TIMESTAMPTZ | Non | |

> **Règle** : avis possible uniquement si `trip.status = completed` ET booking `paid` pour cet utilisateur.

---

## 12. Messagerie

### `messages`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| sender_id | INTEGER FK | Non | → `users.id` |
| recipient_id | INTEGER FK | Non | → `users.id` |
| subject | VARCHAR(200) | Oui | Objet / motif |
| body | TEXT | Non | |
| is_read | BOOLEAN | Non | Défaut : FALSE |
| created_at | TIMESTAMPTZ | Non | |

---

## 13. Notifications in-app

### `notifications`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Non | → `users.id` |
| type | VARCHAR(50) | Non | `booking_confirmed` · `parcel_arrived` · `claim_response` … |
| title | VARCHAR(200) | Oui | |
| body | TEXT | Oui | |
| is_read | BOOLEAN | Non | Défaut : FALSE |
| reference_id | INTEGER | Oui | ID de l'entité liée |
| reference_type | VARCHAR(50) | Oui | `booking` · `parcel` · `claim` … |
| created_at | TIMESTAMPTZ | Non | |

---

## 14. Synchronisation hors ligne

### `sync_logs`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| agent_id | INTEGER FK | Non | → `users.id` |
| synced_at | TIMESTAMPTZ | Non | |
| bookings_sent | INTEGER | Non | |
| parcels_sent | INTEGER | Non | |
| validations_sent | INTEGER | Non | |
| conflicts | INTEGER | Non | |
| status | VARCHAR(20) | Non | `success` · `partial` · `error` |
| error_details | TEXT | Oui | |

### `sync_conflicts`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| sync_log_id | INTEGER FK | Non | → `sync_logs.id` |
| entity_type | VARCHAR(50) | Non | `booking` · `parcel` |
| entity_ref | VARCHAR(50) | Oui | Ex : numéro de billet |
| conflict_type | VARCHAR(50) | Non | `seat_conflict` · `trip_full` · `booking_cancelled` |
| resolution | TEXT | Oui | Description en français de la solution |
| resolved_at | TIMESTAMPTZ | Non | |

---

## 15. Configuration globale & Audit

### `global_settings`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| key | VARCHAR(100) | Non | **Unique** — ex : `global_commission_rate` |
| value | TEXT | Non | Ex : `5.00` |
| description | TEXT | Oui | |
| updated_at | TIMESTAMPTZ | Non | |

Clés prévues : `global_commission_rate` · `sms_provider` · `sms_api_key` · `platform_maintenance_mode`

### `activity_logs`
| Attribut | Type | Nullable | Notes |
|----------|------|----------|-------|
| id | SERIAL PK | Non | |
| user_id | INTEGER FK | Oui | NULL = action système |
| action | VARCHAR(100) | Non | Ex : `company_suspended` · `booking_cancelled` |
| entity_type | VARCHAR(50) | Oui | |
| entity_id | INTEGER | Oui | |
| details | JSONB | Oui | Avant/après modification |
| ip_address | VARCHAR(45) | Oui | |
| created_at | TIMESTAMPTZ | Non | |

---

## Résumé des relations clés

| Table A | Table B | Cardinalité | Description |
|---------|---------|-------------|-------------|
| companies | users (agents) | 1 — N | Une compagnie emploie plusieurs agents |
| companies | routes | 1 — N | Une compagnie opère plusieurs lignes |
| companies | vehicles | 1 — N | Une compagnie possède plusieurs véhicules |
| companies | company_subscriptions | 1 — N | Historique des abonnements |
| routes | trips | 1 — N | Une ligne → plusieurs voyages planifiés |
| trips | bookings | 1 — N | Un voyage → plusieurs réservations |
| trips | parcels | 1 — N | Un voyage → plusieurs colis |
| bookings | payments | 1 — 1 | Une réservation → un paiement |
| bookings | boarding_validations | 1 — 1 | Un billet → une validation d'embarquement |
| users | bookings | 1 — N | Un voyageur → plusieurs réservations |
| users | claims | 1 — N | Un voyageur → plusieurs réclamations |
| users | reviews | 1 — N | Un voyageur → plusieurs avis |
| users (agent) | sync_logs | 1 — N | Un agent → plusieurs sessions de sync |

---

## Points discutés

| Sujet | Question |Reponse|
|-------|----------|-------|
| Codes de réduction | Table dédiée avec validité et usage unique ? | oui|
| Stockage fichiers | S3 / Cloudinary / local ? | S3 |
| Mobile Money | API directe ou saisie manuelle (actuel : manuelle) | en entente |
| Multi-admins | Plusieurs admins par compagnie (ex : directeur + comptable) ? | oui |
| Rétention logs | sync_logs : 30j ? activity_logs : 1 an ? | optimum|
