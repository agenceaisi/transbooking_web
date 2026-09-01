# docs/specs/security.md
# Exigences de sécurité — TransBooking BF
# Référencé par CLAUDE.md — charger pour toute tâche touchant à l'auth, permissions, ou données sensibles

---

## 1. Authentification

### JWT Configuration (SimpleJWT)
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,  # nécessite rest_framework_simplejwt.token_blacklist
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
}
```

### Champ d'identification
- Identifiant principal : numéro de téléphone (`phone`)
- Email optionnel — jamais utilisé comme identifiant de connexion
- Mots de passe agents : générés automatiquement (8 chars, envoyés par SMS), changement forcé à la 1ère connexion

---

## 2. Permissions par rôle

```python
# utils/permissions.py

class IsSuperAdmin(BasePermission):
    """Accès réservé au super administrateur de la plateforme."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name == 'super_admin'
        )

class IsCompanyAdmin(BasePermission):
    """Accès réservé aux administrateurs de compagnie."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name == 'company_admin'
            and hasattr(request.user, 'company_admin_profile')
            and request.user.company_admin_profile.company.status == 'active'
        )

class IsAgentGuichet(BasePermission):
    """Accès réservé aux agents guichet actifs."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name == 'agent_guichet'
            and request.user.is_active
        )

class IsControleur(BasePermission):
    """Accès réservé aux contrôleurs actifs."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name == 'controleur'
            and request.user.is_active
        )

class IsAgent(BasePermission):
    """Accès pour agent_guichet OU controleur."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name in ('agent_guichet', 'controleur')
            and request.user.is_active
        )

class IsVoyageur(BasePermission):
    """Accès réservé aux voyageurs connectés."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role.name == 'voyageur'
        )
```

---

## 3. Isolation multi-tenant

### Règle absolue
Chaque requête d'un `company_admin` ou `agent` doit filtrer les données par sa compagnie.
Aucune donnée d'une autre compagnie ne doit être accessible, même avec un ID valide.

### Pattern d'implémentation
```python
class CompanyBookingViewSet(ModelViewSet):
    def get_queryset(self):
        # Récupérer la compagnie de l'utilisateur courant
        company = self.request.user.company_admin_profile.company
        return Booking.objects.filter(
            trip__route__company=company
        ).select_related('trip', 'user')

    def get_object(self):
        obj = super().get_object()
        # Double vérification au niveau de l'objet
        if obj.trip.route.company != self.request.user.company_admin_profile.company:
            raise PermissionDenied()
        return obj
```

---

## 4. Rate Limiting

```python
# settings/base.py
RATELIMIT_USE_CACHE = 'default'

# Appliquer sur les vues critiques
from django_ratelimit.decorators import ratelimit

# Auth endpoints — 10 tentatives/minute par IP
@ratelimit(key='ip', rate='10/m', method='POST', block=True)

# Recherche publique — 60 requêtes/minute par IP
@ratelimit(key='ip', rate='60/m', method='GET', block=True)

# Scan QR — 120/minute par agent (token)
@ratelimit(key='user', rate='120/m', method='POST', block=True)

# Sync hors ligne — 10/heure par agent
@ratelimit(key='user', rate='10/h', method='POST', block=True)
```

---

## 5. Validation des entrées

### Numéro de téléphone
```python
import re

def validate_phone_bf(value):
    """Valide un numéro de téléphone burkinabè (+226XXXXXXXX ou 0XXXXXXXX)."""
    pattern = r'^(\+226|0)[0-9]{8}$'
    if not re.match(pattern, value):
        raise ValidationError(
            "Numéro de téléphone invalide. Format attendu : +22670000000 ou 070000000"
        )
```

### Montants
```python
def validate_amount(value):
    if value <= 0:
        raise ValidationError("Le montant doit être supérieur à zéro.")
    if value > Decimal('10000000'):  # 10 millions FCFA
        raise ValidationError("Montant anormalement élevé — vérifier la saisie.")
```

### Upload de fichiers
```python
ALLOWED_FILE_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
MAX_FILE_SIZE_MB = 5

def validate_upload(file):
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise ValidationError("Format de fichier non autorisé.")
    if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValidationError(f"Fichier trop volumineux (max {MAX_FILE_SIZE_MB} Mo).")
```

---

## 6. Protection des données sensibles

### Champs à ne jamais exposer dans les réponses API
- `password` (évident)
- `transaction_ref` complet → masquer : `****` + 4 derniers chars
- `id_number` (CNIB/Passeport) → exclure des exports et des listes
- `commission_rate` → visible uniquement par `company_admin` et `super_admin`
- `sms_api_key` → jamais dans les réponses

### Logs — données à exclure
```python
# settings/base.py
LOGGING = {
    'filters': {
        'sensitive_filter': {
            '()': 'utils.logging.SensitiveDataFilter',
            # Masquer : password, token, transaction_ref, api_key
        }
    }
}
```

---

## 7. Headers de sécurité

Configurer dans `settings/base.py` via `django-security` ou manuellement :
```python
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# En production uniquement :
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

---

## 8. Checklist sécurité avant chaque PR

- [ ] Toutes les vues ont `permission_classes` explicite
- [ ] `get_queryset()` filtre par compagnie pour les vues admin/agent
- [ ] Aucun ID séquentiel exposé dans les URLs publiques
- [ ] `select_for_update()` utilisé pour toute modification de `available_seats`
- [ ] Validation du téléphone appliquée sur tous les champs `phone`
- [ ] Aucun champ sensible dans les serializers de liste
- [ ] Tests d'autorisation écrits (accès refusé pour mauvais rôle)
- [ ] Rate limiting appliqué sur les endpoints d'auth et publics
