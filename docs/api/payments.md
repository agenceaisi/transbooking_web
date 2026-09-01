# API — App `payments`

Préfixe global : `/api/v1/`. Authentification via JWT (`Authorization: Bearer <access>`).

Gestion des paiements de réservations. **Mobile Money par OTP** : le paiement ouvre une
transaction chez l'opérateur, un code à usage unique est envoyé au payeur, puis le paiement
est confirmé par la saisie de ce code. La confirmation passe la réservation à `paid`.

- Le siège est déjà réservé à la **création** de la réservation (décrément de `available_seats`
  sous verrou ligne, cf. `apps.bookings.services.create_booking`). La confirmation du paiement
  ne re-décrémente donc pas : elle marque seulement la réservation `paid`.
- **OTP** : 6 chiffres, valable **5 min**, **3 tentatives**, **1 renvoi / 30 s**. Le code n'est
  **jamais** stocké en clair (HMAC dérivé de `SECRET_KEY`), ni journalisé, ni renvoyé par l'API.
- `transaction_ref` (référence opérateur, conservée pour la réconciliation) et `phone` sont des
  **données sensibles** : masquées dans les logs et les réponses API (`****` + 4 derniers
  caractères).
- Commission plateforme figée à la confirmation : `montant × company.commission_rate / 100`
  (taux global `COMMISSION_RATE_DEFAULT` si `commission_rate` est NULL).
- `method` : `cash · orange_money · moov_money · coris_money · telecel_money · card`.
  - `cash` → encaissement guichet en une étape, **sans** OTP.
  - `orange_money · moov_money · coris_money · telecel_money` → flux OTP.
  - `card` → **hors périmètre** pour l'instant (`400`).
  - Un moyen désactivé par le super admin (`/api/v1/super/settings/payment-methods/`) renvoie `400`.
- `status` : `pending · otp_required · paid · failed · refunded`.

> **Colis** : le paiement de colis (`parcel_id`) sera disponible après l'implémentation du
> module `parcels` (PROMPT 07). Actuellement, fournir `parcel_id` renvoie `400`.

---

## Fournisseurs Mobile Money — `apps/payments/providers.py`

L'API opérateur est encapsulée derrière l'interface `PaymentProvider` :
`initiate(payment) -> provider_ref` · `send_otp(payment, code)` · `confirm_otp(payment, otp)`.

| Implémentation                                                    | `generates_otp` | État                                    |
|-------------------------------------------------------------------|-----------------|-----------------------------------------|
| `MockPaymentProvider`                                             | `False`         | Sandbox — opérationnel, aucun débit réel |
| `OrangeMoneyProvider` · `MoovMoneyProvider` · `CorisMoneyProvider` · `TelecelMoneyProvider` | `True` | Squelettes — en attente de l'agrégateur |

- `generates_otp = False` : la **plateforme** tire le code, n'en stocke que le hash
  (`payments.PaymentOtp`) et gère expiration + tentatives.
- `generates_otp = True` : le code est tiré et vérifié **côté opérateur** ; la plateforme ne
  suit que l'état de la transaction et relaie la saisie à `confirm_otp`.

Sélection (`get_payment_provider`) :
`PAYMENT_SANDBOX=True` → `MockPaymentProvider` pour **tous** les moyens ; sinon le provider est
résolu depuis `PAYMENT_PROVIDER` s'il est épinglé, à défaut depuis le `method` du paiement.

| Setting (env)                   | Défaut     | Rôle                                                |
|---------------------------------|------------|-----------------------------------------------------|
| `PAYMENT_SANDBOX`               | `True`     | Mode bac à sable : aucun appel opérateur, aucun débit |
| `PAYMENT_PROVIDER`              | `mock`     | Provider épinglé hors sandbox                        |
| `PAYMENT_SANDBOX_OTP`           | `123456`   | Code de test accepté en sandbox                      |
| `PAYMENT_SANDBOX_FORCE_FAILURE` | `False`    | Simule un refus opérateur                            |
| `PAYMENT_API_BASE_URL/_KEY/_SECRET/_MERCHANT_ID` | `""` | Identifiants agrégateur — **jamais en dur** |
| `OTP_CODE_LENGTH`               | `6`        | Longueur du code                                     |
| `OTP_EXPIRY_MINUTES`            | `5`        | Durée de validité                                    |
| `OTP_MAX_ATTEMPTS`              | `3`        | Tentatives avant échec                               |
| `OTP_RESEND_INTERVAL_SECONDS`   | `30`       | Délai minimal entre deux envois                      |

> Aucun identifiant d'agrégateur n'est codé en dur. Tant que le contrat n'est pas signé, un
> provider réel lève `503` (`PaymentProviderNotConfigured`) si les identifiants manquent, et le
> paiement passe `failed` avec un `400` si l'intégration n'est pas branchée.

---

## Voyageur / authentifié

`get_queryset()` est filtré par périmètre : le voyageur ne voit que les paiements de **ses**
réservations ; l'agent/admin uniquement ceux de **sa** compagnie ; le super admin voit tout.

### POST `/api/v1/payments/`

Initie un paiement. Mobile Money → `otp_required` (code envoyé au payeur) ;
espèces → `pending` jusqu'à l'encaissement guichet.

| Champ        | Type   | Obligatoire | Notes                                              |
|--------------|--------|-------------|----------------------------------------------------|
| `booking_id` | int    | oui*        | FK `bookings.Booking` (\*ou `parcel_id`)           |
| `parcel_id`  | int    | non         | Non encore supporté → `400`                        |
| `method`     | string | oui         | un des moyens de paiement (`card` → `400`)         |
| `phone`      | string | cond.       | **requis** pour un moyen Mobile Money              |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/payments/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"booking_id": 42, "method": "orange_money", "phone": "+22670000001"}'
```

**201 Created**
```json
{
  "id": 7,
  "ticket_number": "BF2026001234",
  "amount": "5000.00",
  "method": "orange_money",
  "method_display": "Orange Money",
  "status": "otp_required",
  "status_display": "Code de confirmation attendu",
  "transaction_ref": "",
  "phone": "****0001",
  "otp_expires_at": "2026-07-21T09:17:00Z",
  "otp_attempts_remaining": 3,
  "receipt_url": "",
  "paid_at": null,
  "created_at": "2026-07-21T09:12:00Z"
}
```

Erreurs : `400` (champ manquant, `phone` absent, `card`, moyen désactivé, `parcel_id`),
`401`, `409` (réservation déjà réglée), `503` (fournisseur non configuré).

### GET `/api/v1/payments/`

Liste **paginée** des paiements du périmètre de l'utilisateur — pour le voyageur, le
sous-onglet « Paiements » de l'écran « Mon profil » (référence, moyen, date, montant).
Items dérivés de `PaymentRead` (`transaction_ref` et `phone` masqués). Tri par date
décroissante (`-created_at`).

| Query param | Type | Défaut | Notes                       |
|-------------|------|--------|-----------------------------|
| `page`      | int  | 1      | Pagination `PageNumber`     |
| `page_size` | int  | —      | Taille de page              |

```bash
curl "https://api.transbooking.bf/api/v1/payments/" \
  -H "Authorization: Bearer <access>"
```

**200 OK**
```json
{
  "count": 1, "next": null, "previous": null,
  "results": [
    {
      "id": 7, "ticket_number": "BF2026001234", "amount": "5000.00",
      "method": "orange_money", "method_display": "Orange Money",
      "status": "paid", "status_display": "Payé",
      "transaction_ref": "****ABCD", "phone": "****0001",
      "otp_expires_at": null, "otp_attempts_remaining": null,
      "receipt_url": "", "paid_at": "2026-07-21T09:17:30Z",
      "created_at": "2026-07-21T09:12:00Z"
    }
  ]
}
```

Erreurs : `401`.

### GET `/api/v1/payments/{id}/`

Renvoie le statut d'un paiement. `404` si hors périmètre de l'utilisateur.
`otp_expires_at` et `otp_attempts_remaining` valent `null` hors statut `otp_required`.

### POST `/api/v1/payments/{id}/verify-otp/`

Confirme un paiement Mobile Money avec le code reçu. En cas de succès :
`status = "paid"`, `transaction_ref` opérateur enregistrée (masquée), reçu généré,
`booking.status = "paid"`, commission figée.

| Champ | Type   | Obligatoire | Notes                    |
|-------|--------|-------------|--------------------------|
| `otp` | string | oui         | 4 à 8 chiffres (6 en prod) |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/payments/7/verify-otp/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"otp": "123456"}'
```

**200 OK** → paiement `paid` (`transaction_ref` masquée : `****ABCD`).

**400 Bad Request** — code erroné (le compteur de tentatives est incrémenté) :
```json
{
  "otp": ["Code incorrect. Il vous reste 2 tentative(s)."],
  "attempts_remaining": 2
}
```

Autres `400` : code expiré, tentatives épuisées (le paiement passe alors `failed` — il faut
relancer un paiement), refus de l'opérateur.
Erreurs : `400`, `401`, `404` (hors périmètre), `409` (déjà confirmé).

### POST `/api/v1/payments/{id}/resend-otp/`

Émet un nouveau code (corps vide). Limité à **1 envoi / 30 s** (`OTP_RESEND_INTERVAL_SECONDS`).

**200 OK** → paiement `otp_required` avec un nouvel `otp_expires_at`.

Erreurs : `400` (le paiement n'attend pas de code), `401`, `404`,
`429` (`{"detail": "Patientez 27 seconde(s) avant de demander un nouveau code."}`).

### POST `/api/v1/payments/{id}/verify/`

Confirmation **manuelle** — réservée aux paiements hors Mobile Money (espèces). Un paiement
Mobile Money renvoie `400` avec l'URL `/verify-otp/` à utiliser.

| Champ             | Type   | Obligatoire | Notes                                   |
|-------------------|--------|-------------|-----------------------------------------|
| `transaction_ref` | string | cond.       | Obligatoire si `method ≠ cash`          |

Erreurs : `400` (réf manquante, ou paiement Mobile Money), `401`, `404`, `409` (déjà confirmé).

### GET `/api/v1/payments/{id}/receipt/`

Télécharge le reçu PDF (`application/pdf`) : n° de transaction, montant, date, compagnie,
trajet, passager, QR code.

---

## Agent guichet — `IsAgentGuichet`

### POST `/api/v1/agent/payments/`

Encaisse au guichet. **Espèces** : initie **et** confirme en une étape (`201` → `paid`).
**Mobile Money** : initie le flux OTP (`201` → `otp_required`), le client confirme ensuite avec
son code via `POST /api/v1/payments/{id}/verify-otp/`.
Isolation multi-tenant : la réservation doit appartenir à la compagnie de l'agent (`404` sinon).

| Champ             | Type   | Obligatoire | Notes                                          |
|-------------------|--------|-------------|------------------------------------------------|
| `booking_id`      | int    | oui         | FK `bookings.Booking` de sa compagnie          |
| `method`          | string | oui         | `cash` ou un moyen Mobile Money (`card` → `400`) |
| `transaction_ref` | string | cond.       | Espèces uniquement — ignoré en Mobile Money    |
| `phone`           | string | cond.       | **requis** pour un moyen Mobile Money          |

```bash
curl -X POST "https://api.transbooking.bf/api/v1/agent/payments/" \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"booking_id": 42, "method": "cash"}'
```

**201 Created** → espèces : paiement `paid`, réservation `paid` ; Mobile Money : `otp_required`.

Erreurs : `400` (moyen hors périmètre, `phone` manquant), `401`, `403` (rôle),
`404` (réservation hors compagnie).
