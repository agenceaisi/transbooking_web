# TransBooking BF

> Plateforme de gestion du transport interurbain au Burkina Faso — API REST Django

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.x-green)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/DRF-3.15-red)](https://www.django-rest-framework.org)
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey)]()

---

## Présentation

TransBooking BF est une solution web/mobile permettant aux compagnies de transport burkinabè de gérer leurs voyages, billets, colis et agents. Elle offre un mode **hors ligne** pour les agents en zone à faible connectivité, avec synchronisation automatique au retour de la connexion.

**5 acteurs** : Super Administrateur · Admin Compagnie · Agent Guichet · Contrôleur · Voyageur

---

## Stack technique

| Composant | Choix |
|-----------|-------|
| Backend | Django 5.x + Django REST Framework |
| Auth | SimpleJWT (access + refresh tokens) |
| Base de données | PostgreSQL 16 |
| Cache / Broker | Redis |
| Tâches async | Celery + Celery Beat |
| Paiement | Orange Money · Moov Money · Coris Money · Telecel Money · Espèces |
| SMS | Abstraction provider (configurable) |
| Export | ReportLab (PDF) · openpyxl (Excel) |
| QR Code | `qrcode` lib → base64 PNG |

---

## Structure du projet

```
transbooking/
├── config/                   # Paramètres, URLs, Celery
│   └── settings/
│       ├── base.py
│       ├── dev.py
│       └── prod.py
├── apps/
│   ├── users/                # Utilisateurs, rôles, profils agents
│   ├── companies/            # Compagnies, paiements, notifications
│   ├── subscriptions/        # Forfaits, abonnements, factures
│   ├── geography/            # Villes, gares
│   ├── vehicles/             # Véhicules, plan des sièges
│   ├── routes/               # Trajets, escales
│   ├── trips/                # Voyages planifiés
│   ├── bookings/             # Réservations, billets, embarquement
│   ├── payments/             # Paiements
│   ├── parcels/              # Colis, notifications destinataire
│   ├── claims/               # Réclamations clients
│   ├── reviews/              # Avis clients
│   ├── speed_reports/        # Signalements excès de vitesse
│   ├── messaging/            # Messagerie agent ↔ client
│   ├── notifications/        # Notifications in-app
│   ├── sync/                 # Synchronisation hors ligne
│   └── dashboard/            # Statistiques & tableaux de bord
└── utils/
    ├── permissions.py        # Classes de permissions par rôle
    ├── pagination.py
    ├── sms.py
    └── qr.py
```

---

## Installation

### Prérequis

- Python 3.12+
- PostgreSQL 16+
- Redis 7+

### Démarrage rapide

```bash
# 1. Cloner le repo
git clone https://github.com/<org>/transbooking-bf.git
cd transbooking-bf

# 2. Environnement virtuel
python -m venv venv
source venv/bin/activate

# 3. Dépendances
pip install -r requirements.txt

# 4. Variables d'environnement
cp .env.example .env
# Éditer .env avec vos valeurs

# 5. Base de données
python manage.py migrate

# 6. Super administrateur initial
python manage.py createsuperuser

# 7. Jeu de données de démonstration (optionnel, voir plus bas)
python manage.py seed_demo

# 8. Lancer le serveur
python manage.py runserver
```

### Jeu de données de démonstration (`seed_demo`)

Peuple la base avec un jeu de données réaliste (contexte burkinabè, montants en
FCFA) afin de tester le front sur **tous les rôles et tous les écrans** sans
tomber sur des listes vides.

> 📄 **Référence complète des données créées, de leur rôle et des identifiants :**
> [`docs/donnees-demo.md`](docs/donnees-demo.md)

```bash
python manage.py seed_demo                 # crée le jeu de données
python manage.py seed_demo --reset         # purge les données de démo puis recrée
python manage.py seed_demo --seed 7        # autre graine aléatoire (défaut : 42)
python manage.py seed_demo --password Xyz  # autre mot de passe (défaut : Demo1234!)
python manage.py seed_demo --force         # autorise l'exécution si DEBUG=False
```

**Garde-fous**

| Règle | Comportement |
|-------|--------------|
| `DEBUG=False` | La commande **refuse** de s'exécuter, sauf `--force`. Jamais sur une base de production. |
| Purge | Uniquement avec `--reset`. Une exécution normale n'efface rien. |
| Idempotence | Les objets sont créés sur des clés naturelles stables (téléphone, nom de compagnie, immatriculation, couple ligne/horaire) : relancer sans `--reset` ne crée aucun doublon. |
| Reproductibilité | À graine et date égales, le jeu produit est identique (`--seed`). |
| Bloc réservé | Les numéros `+22670000xxx` sont réservés aux comptes de démo : `--reset` purge tous les comptes non-superutilisateur de ce bloc. |

Les voyages sont ancrés sur des **créneaux horaires fixes** de la journée
courante : relancer la commande le même jour est sans effet, la relancer un
autre jour fait glisser la fenêtre J-30 → J+15. Aucune date n'est codée en dur.

#### Comptes de test

Mot de passe commun : **`Demo1234!`** — connexion via
`POST /api/v1/auth/login/` avec `{"phone": "...", "password": "Demo1234!"}`.

| Rôle | Identifiant | Nom | Usage |
|------|-------------|-----|-------|
| `super_admin` | `+22670000001` | Awa Konseiga | Supervision plateforme, demandes d'inscription, journal d'audit |
| `company_admin` | `+22670000010` | Boukary Ouedraogo | Compagnie principale (Rakieta Transport) |
| `agent_guichet` | `+22670000011` | Salimata Kabore | Gare de Ouagadougou Patte d'Oie |
| `agent_guichet` | `+22670000012` | Rasmane Sawadogo | Gare de Bobo-Dioulasso Centre |
| `controleur` | `+22670000013` | Issa Traore | Scan des billets, embarquement |
| `company_admin` | `+22670000020` | Mariam Sana | 2ᵉ compagnie (test d'isolation multi-tenant) |
| `agent_guichet` | `+22670000021` | Adama Zongo | 2ᵉ compagnie |
| `voyageur` | `+22670000030` | Ibrahim Compaore | **Historique complet** : voyages passés/à venir, annulation, colis, avis, réclamations |
| `voyageur` | `+22670000031` à `+22670000034` | — | 4 autres voyageurs, historique plus léger |

La compagnie **STAF Voyages** est volontairement *suspendue* (abonnement
expiré) : elle sert à tester l'écran « compte suspendu » et les réponses 403.

#### Ce qui est créé

| Domaine | Contenu |
|---------|---------|
| Géographie | 10 villes réelles du Burkina + 2 villes d'escale |
| Compagnies | 2 actives (une complète, une petite) + 1 suspendue + 3 demandes d'inscription (2 `pending`, 1 `info_requested`) |
| Abonnements | 3 forfaits (mensuels + annuel) ; un abonnement actif, un expirant sous 5 jours, un expiré |
| Flotte | 7 véhicules avec plan de sièges, dont **1 en maintenance** (jamais affecté à un voyage) |
| Lignes | 10 lignes avec distances, durées et tarifs cohérents, plus des escales |
| Voyages | ~49 voyages de J-30 à J+15, dont **8 aujourd'hui** couvrant tous les statuts : terminé, en cours, retardé, annulé, et un **voyage complet** |
| Réservations | ~1 200 billets au format `BF<année><séquence>` avec QR code, remplissage variable (30 % → 100 %) |
| Paiements | Les 5 statuts (`paid` majoritaire, `pending`, `otp_required`, `failed`, `refunded`) et les 5 moyens de paiement |
| Embarquements | ~650 validations + traces de scan, dont des embarquements partiels sur les voyages du jour |
| Colis | 15 colis `COL<année><séquence>` dans les 5 statuts, dont **4 arrivés non notifiés** à la gare de Ouagadougou |
| Relation client | 23 avis notés de 1 à 5 (certains avec réponse), 9 réclamations dont **4 hors délai de 48 h**, 4 signalements d'excès de vitesse géolocalisés |
| Supervision | Notifications in-app et journal d'activités du super admin |

La commande affiche en fin d'exécution un récapitulatif complet : tous les
comptes créés (rôle, identifiant, mot de passe) et les volumes par type d'objet.

> Le code vit dans [`apps/core/management/commands/seed_demo.py`](apps/core/management/commands/seed_demo.py)
> (logique, découpée par domaine : `seed_geography`, `seed_companies`,
> `seed_users`, `seed_fleet`, `seed_trips`, `seed_bookings`, `seed_parcels`,
> `seed_feedback`) et `_seed_data.py` (données de référence). Les billets, QR
> codes, numéros de suivi et tarifs colis sont produits par les **services
> métier existants**, jamais réimplémentés.

### Variables d'environnement (`.env`)

```env
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=postgres://user:password@localhost:5432/transbooking
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# SMS
SMS_PROVIDER=console          # console | orange | moov
SMS_API_KEY=
SMS_SENDER_ID=TransBookingBF

# Stockage fichiers
STORAGE_BACKEND=local         # local | s3
AWS_BUCKET_NAME=

# Commission par défaut (%)
COMMISSION_RATE_DEFAULT=5.00
```

### Lancer Celery

```bash
# Worker
celery -A config worker -l info

# Scheduler (tâches planifiées)
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## Acteurs & permissions

| Rôle | Préfixe API | Accès principal |
|------|-------------|-----------------|
| `super_admin` | `/api/v1/super/` | Gestion globale de la plateforme |
| `company_admin` | `/api/v1/company/` | Sa compagnie uniquement |
| `agent_guichet` | `/api/v1/agent/` | Enregistrement passagers & colis |
| `controleur` | `/api/v1/agent/` | Scan QR, embarquement |
| `voyageur` | `/api/v1/` | Réservations, colis, réclamations |

---

## Fonctionnalités clés

### Mode hors ligne (agents)
Les agents peuvent travailler sans connexion internet. Les données sont stockées localement et synchronisées automatiquement au retour de la connexion via `POST /api/v1/agent/sync/`. Les conflits de sièges sont résolus automatiquement.

### QR Code billets
Chaque réservation génère un numéro unique (`BF2026XXXXXX`) et un QR code. Le contrôleur scanne ce QR à l'embarquement pour valider en moins d'une seconde.

### Suivi de colis
Chaque colis reçoit un numéro de suivi (`COL2026XXXXXX`). Le destinataire est notifié par SMS à l'arrivée. Le suivi est public : pas de compte requis.

### Tableaux de bord
L'admin compagnie accède à : chiffre d'affaires, taux de remplissage par trajet, répartition des paiements, top 5 des lignes, activité des agents — filtrables par période.

---

## API — Aperçu des endpoints

La documentation complète est disponible dans [`docs/api_endpoints.md`](docs/api_endpoints.md).

```
/api/v1/auth/          # Authentification (login, register, refresh)
/api/v1/users/         # Profil utilisateur
/api/v1/trips/         # Recherche de voyages (public)
/api/v1/bookings/      # Réservations voyageur
/api/v1/parcels/track/ # Suivi colis (public)
/api/v1/agent/         # Interface agents (guichet + contrôleur)
/api/v1/company/       # Interface admin compagnie
/api/v1/super/         # Interface super administrateur
```

> L'API intègre Swagger UI — accessible en dev sur `/api/v1/docs/`

---

## Tests

```bash
# Lancer tous les tests
pytest

# Avec couverture
pytest --cov=apps --cov-report=html

# Une app spécifique
pytest apps/bookings/

# Jeu de données de démonstration (volumétrie réduite automatiquement)
pytest apps/core/tests/test_seed_demo.py
```

Couverture cible : **≥ 70%**

---

## Données métier importantes

- `Trip.available_seats` est décrémenté avec `select_for_update()` pour éviter les surréservations.
- Le tarif colis = `poids_kg × prix_par_kg + frais_fixes` selon la tranche de distance.
- La commission TransBooking = `montant × taux_commission / 100` prélevée par réservation.
- Un avis ne peut être déposé qu'après un voyage au statut `completed`.
- Les réclamations sans réponse après 48h sont signalées automatiquement au super admin.

---

## Équipe & contact

Développé par **Agence Internationale de Statistique et de l'Informatique** — Juin 2026