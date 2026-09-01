# docs/specs/business_rules.md
# Règles métier — TransBooking BF
# Référencé par CLAUDE.md — charger uniquement quand pertinent

---

## 1. Réservations & Billets

### Génération du ticket_number
```
Format : BF + YYYY + séquence à 6 chiffres
Exemple : BF2026001234
Implémentation : utiliser une séquence DB PostgreSQL (SERIAL) formatée, pas uuid
```

### Attribution des sièges
```python
# OBLIGATOIRE : select_for_update() pour éviter les surréservations concurrentes
def assign_seat(trip_id: int) -> str:
    with transaction.atomic():
        trip = Trip.objects.select_for_update().get(id=trip_id)
        if trip.available_seats <= 0:
            raise ValidationError("Ce voyage est complet.")
        seat = get_next_available_seat(trip)
        trip.available_seats -= 1
        trip.save(update_fields=['available_seats', 'updated_at'])
        return seat
```

### Statuts d'une réservation
```
pending   → créée, paiement non confirmé
paid      → paiement confirmé
cancelled → annulée par le voyageur ou l'admin
refunded  → remboursée (processus manuel par admin)
```

### Règle d'annulation
- Le voyageur peut annuler si `trip.departure_time > now() + 2h`
- Au-delà → annulation refusée côté API (HTTP 409)
- L'admin peut annuler sans restriction

---

## 2. Paiements

### Mobile Money (mode actuel : manuel)
```
L'agent demande verbalement la référence de transaction au client.
L'agent saisit transaction_ref dans le formulaire.
Le système NE vérifie PAS en temps réel — l'agent est responsable.
# TODO: remplacer par appel API Orange/Moov quand disponible
```

### Calcul de la commission
```python
commission = booking.amount * company.commission_rate / 100
# Si company.commission_rate est NULL → utiliser global_settings['global_commission_rate']
```

### Génération du reçu PDF
Contenu obligatoire : numéro de transaction, montant, date, compagnie, trajet, passager, QR code

---

## 3. Colis

### Génération du tracking_number
```
Format : COL + YYYY + séquence à 6 chiffres
Exemple : COL2026000456
```

### Calcul du tarif colis
```python
def calculate_tariff(weight_kg: Decimal, distance_km: Decimal, company: Company) -> Decimal:
    """
    Calcule le tarif de transport d'un colis.

    Args:
        weight_kg: Poids en kilogrammes.
        distance_km: Distance entre ville départ et destination.
        company: Compagnie transporteuse (pour récupérer la grille tarifaire).

    Returns:
        Tarif total en FCFA.
    """
    config = company.parcel_pricing_config  # JSON stocké sur Company
    # Déterminer la tranche de distance
    if distance_km < 100:
        price_per_kg = config['tier_short']['price_per_kg']
        fixed_fee = config['tier_short']['fixed_fee']
    elif distance_km <= 300:
        price_per_kg = config['tier_medium']['price_per_kg']
        fixed_fee = config['tier_medium']['fixed_fee']
    else:
        price_per_kg = config['tier_long']['price_per_kg']
        fixed_fee = config['tier_long']['fixed_fee']
    return Decimal(weight_kg * price_per_kg + fixed_fee).quantize(Decimal('1'))
```

### Statuts d'un colis
```
registered → enregistré à la gare de départ
in_transit → chargé dans le bus, en route
arrived    → à la gare de destination
notified   → destinataire prévenu (SMS ou appel)
collected  → remis au destinataire
```

### Règle anti-doublon SMS
```python
# Avant d'envoyer un SMS, vérifier :
already_sent = ParcelNotification.objects.filter(
    parcel=parcel, method='sms'
).exists()
if already_sent:
    raise ValidationError("Un SMS a déjà été envoyé pour ce colis.")
```

---

## 4. Avis clients

### Conditions pour déposer un avis
```python
def can_review(user, trip) -> bool:
    return (
        trip.status == Trip.Status.COMPLETED
        and Booking.objects.filter(
            user=user,
            trip=trip,
            status=Booking.Status.PAID
        ).exists()
    )
```

### Signalement d'un avis
- L'admin de compagnie peut signaler (`is_flagged = True`)
- Seul le super admin peut supprimer
- L'admin NE PEUT PAS supprimer directement → HTTP 403 si tentative

---

## 5. Réclamations

### Délai de réponse
```python
# Annoter is_overdue à la requête — ne pas stocker en DB
from django.utils import timezone
from datetime import timedelta

queryset = Claim.objects.annotate(
    is_overdue=Case(
        When(
            status='submitted',
            created_at__lt=timezone.now() - timedelta(hours=48),
            then=True
        ),
        default=False,
        output_field=BooleanField()
    )
)
```

### Types de réclamation
```
retard · perte_bagage · bagage_endommage · comportement · surcharge · remboursement · autre
```

---

## 6. Synchronisation hors ligne

### Payload de synchronisation
```json
POST /api/v1/agent/sync/
{
  "bookings": [
    {
      "ticket_number": "BF2026001234",
      "trip_id": 42,
      "first_name": "Aminata",
      "last_name": "TRAORE",
      "phone": "+22670000001",
      "seat_number": "A3",
      "amount": "5000.00",
      "payment_method": "cash",
      "is_offline": true,
      "offline_created_at": "2026-06-01T08:23:00Z"
    }
  ],
  "parcels": [...],
  "validations": [...]
}
```

### Réponse attendue
```json
{
  "synced": {
    "bookings": 3,
    "parcels": 1,
    "validations": 5
  },
  "conflicts": [
    {
      "type": "seat_conflict",
      "ticket_number": "BF2026001234",
      "original_seat": "A3",
      "assigned_seat": "B7",
      "message": "Siège A3 déjà attribué. Nouveau siège assigné : B7."
    }
  ],
  "errors": []
}
```

### Résolution des conflits
```
seat_conflict    → attribuer le prochain siège libre, notifier l'agent
trip_full        → rejeter la réservation, retourner dans errors[]
booking_cancelled → la réservation a été annulée pendant la déconnexion → informer l'agent
```

---

## 7. Sécurité — exigences minimales

### Isolation multi-tenant
```python
# TOUJOURS dans get_queryset() pour les vues company_admin
def get_queryset(self):
    return super().get_queryset().filter(
        company=self.request.user.company_admin_profile.company
    )
```

### Rate limiting
```python
# Sur les endpoints d'authentification
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
# Sur la recherche publique de trajets
@ratelimit(key='ip', rate='60/m', method='GET', block=True)
```

### Données sensibles
- Jamais de mot de passe, token ou clé API dans les logs
- `transaction_ref` Mobile Money → masquer dans les logs (`****` sauf 4 derniers caractères)
- `id_number` (CNIB/Passeport) → champ sensible, exclure des exports publics

### Headers de sécurité (à configurer dans Nginx + Django)
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Strict-Transport-Security: max-age=31536000
Content-Security-Policy: default-src 'self'
```

---

## 8. Documentation des endpoints — template

Pour chaque endpoint, produire ce bloc dans `docs/api/<app>.md` :

```markdown
### POST /api/v1/agent/bookings/

**Description** : Enregistre un passager au guichet. Fonctionne en mode hors ligne.

**Auth** : JWT requis — rôle `agent_guichet`

**Body (JSON)**
| Champ | Type | Obligatoire | Description |
|-------|------|-------------|-------------|
| trip_id | int | Oui | ID du voyage |
| first_name | string | Oui | Prénom du passager |
| last_name | string | Oui | Nom du passager |
| phone | string | Oui | Téléphone (format +226XXXXXXXX) |
| payment_method | string | Oui | cash · orange_money · moov_money · coris_money |
| transaction_ref | string | Cond. | Obligatoire si payment_method ≠ cash |
| is_offline | bool | Non | True si saisi sans connexion (défaut : false) |
| offline_created_at | datetime | Cond. | Obligatoire si is_offline = true |

**Exemple de requête**
curl -X POST https://api.transbooking.bf/api/v1/agent/bookings/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "trip_id": 42,
    "first_name": "Aminata",
    "last_name": "TRAORE",
    "phone": "+22670000001",
    "payment_method": "cash",
    "amount": 5000
  }'

**Réponse succès (201)**
{
  "ticket_number": "BF2026001234",
  "qr_code": "data:image/png;base64,...",
  "seat_number": "A3",
  "status": "paid",
  "trip": { "departure_time": "2026-06-15T06:00:00Z", "destination": "Bobo-Dioulasso" }
}

**Erreurs**
| Code | Cas |
|------|-----|
| 400 | Champ manquant ou invalide |
| 403 | Rôle non autorisé |
| 409 | Voyage complet (available_seats = 0) |
| 410 | Voyage annulé ou terminé |
```
