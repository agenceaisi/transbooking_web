# TransBooking BF — API Endpoints (Django REST Framework)

> **Convention** : `[auth]` = JWT requis | `[admin]` = company_admin | `[super]` = super_admin | `[agent]` = agent_guichet ou controleur | `[public]` = sans authentification

---

## 1. Authentification & Utilisateurs

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/auth/register/` | public | Inscription voyageur |
| POST | `/api/auth/login/` | public | Connexion (retourne JWT access + refresh) |
| POST | `/api/auth/token/refresh/` | public | Rafraîchissement du token JWT |
| POST | `/api/auth/logout/` | auth | Révocation du refresh token |
| POST | `/api/auth/password/change/` | auth | Changement de mot de passe |
| GET | `/api/users/me/` | auth | Profil de l'utilisateur connecté |
| PATCH | `/api/users/me/` | auth | Mise à jour du profil (téléphone, email) |

---

## 2. Compagnies

### 2.1 Super Admin — Gestion des compagnies

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/companies/` | super | Liste toutes les compagnies (filtres : statut, date) |
| POST | `/api/super/companies/` | super | Créer une compagnie |
| GET | `/api/super/companies/{id}/` | super | Détail d'une compagnie |
| PATCH | `/api/super/companies/{id}/` | super | Modifier les infos d'une compagnie |
| DELETE | `/api/super/companies/{id}/` | super | Supprimer une compagnie |
| POST | `/api/super/companies/{id}/activate/` | super | Activer une compagnie |
| POST | `/api/super/companies/{id}/suspend/` | super | Suspendre une compagnie |

### 2.2 Demandes d'inscription compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/auth/company/register/` | public | Soumettre une demande de création de compte compagnie |
| GET | `/api/super/company-requests/` | super | Liste des demandes en attente (`status=pending`) |
| POST | `/api/super/company-requests/{id}/approve/` | super | Approuver la demande |
| POST | `/api/super/company-requests/{id}/reject/` | super | Rejeter la demande |
| POST | `/api/super/company-requests/{id}/request-info/` | super | Demander des informations complémentaires |

### 2.3 Admin Compagnie — Paramètres

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/settings/` | admin | Lire les paramètres de la compagnie |
| PATCH | `/api/company/settings/` | admin | Mettre à jour (logo, couleur, message d'accueil, bannière) |
| GET | `/api/company/settings/payment-methods/` | admin | Lire les moyens de paiement activés |
| PATCH | `/api/company/settings/payment-methods/` | admin | Activer/désactiver des moyens de paiement |
| GET | `/api/company/settings/notifications/` | admin | Lire les paramètres de notifications SMS |
| PATCH | `/api/company/settings/notifications/` | admin | Activer/désactiver les SMS automatiques |

---

## 3. Abonnements

### 3.1 Super Admin

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/subscription-plans/` | super | Liste des forfaits disponibles |
| POST | `/api/super/subscription-plans/` | super | Créer un forfait |
| PATCH | `/api/super/subscription-plans/{id}/` | super | Modifier un forfait |
| DELETE | `/api/super/subscription-plans/{id}/` | super | Archiver un forfait |
| GET | `/api/super/subscriptions/` | super | Liste des abonnements (filtres : statut, expiration) |
| POST | `/api/super/subscriptions/` | super | Attribuer un abonnement à une compagnie |
| PATCH | `/api/super/subscriptions/{id}/` | super | Modifier un abonnement (renouvellement, annulation) |
| GET | `/api/super/subscriptions/expiring-soon/` | super | Abonnements expirant dans les 7 jours |

### 3.2 Admin Compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/subscription/` | admin | Voir l'abonnement actif de la compagnie |
| GET | `/api/company/subscription/invoices/` | admin | Liste des factures |
| GET | `/api/company/subscription/invoices/{id}/download/` | admin | Télécharger une facture PDF |

---

## 4. Géographie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/cities/` | public | Liste de toutes les villes desservies |
| POST | `/api/super/cities/` | super | Ajouter une ville |
| GET | `/api/company/stations/` | admin | Liste des gares de la compagnie |
| POST | `/api/company/stations/` | admin | Ajouter une gare |
| PATCH | `/api/company/stations/{id}/` | admin | Modifier une gare |
| DELETE | `/api/company/stations/{id}/` | admin | Supprimer une gare |

---

## 5. Véhicules

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/vehicles/` | admin | Liste des véhicules de la compagnie |
| POST | `/api/company/vehicles/` | admin | Ajouter un véhicule |
| GET | `/api/company/vehicles/{id}/` | admin | Détail d'un véhicule |
| PATCH | `/api/company/vehicles/{id}/` | admin | Modifier un véhicule |
| DELETE | `/api/company/vehicles/{id}/` | admin | Supprimer un véhicule |
| POST | `/api/company/vehicles/{id}/maintenance/` | admin | Passer en maintenance |
| POST | `/api/company/vehicles/{id}/activate/` | admin | Remettre en service |
| GET | `/api/company/vehicles/{id}/seat-plan/` | admin | Lire le plan des sièges |
| PUT | `/api/company/vehicles/{id}/seat-plan/` | admin | Configurer le plan des sièges |

---

## 6. Trajets (Routes)

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/routes/` | admin | Liste des trajets de la compagnie |
| POST | `/api/company/routes/` | admin | Créer un nouveau trajet |
| GET | `/api/company/routes/{id}/` | admin | Détail d'un trajet |
| PATCH | `/api/company/routes/{id}/` | admin | Modifier un trajet |
| DELETE | `/api/company/routes/{id}/` | admin | Supprimer un trajet (vérifie les voyages futurs) |
| POST | `/api/company/routes/{id}/duplicate/` | admin | Dupliquer en trajet inverse |
| GET | `/api/company/routes/{id}/stops/` | admin | Liste des escales d'un trajet |
| POST | `/api/company/routes/{id}/stops/` | admin | Ajouter une escale |
| PATCH | `/api/company/routes/{id}/stops/{stop_id}/` | admin | Modifier une escale |
| DELETE | `/api/company/routes/{id}/stops/{stop_id}/` | admin | Supprimer une escale |

---

## 7. Horaires & Voyages (Trips)

### 7.1 Création et gestion (Admin)

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/trips/` | admin | Liste des voyages (filtres : route, date, statut) |
| POST | `/api/company/trips/` | admin | Créer un voyage individuel |
| GET | `/api/company/trips/{id}/` | admin | Détail d'un voyage |
| PATCH | `/api/company/trips/{id}/` | admin | Modifier un voyage (véhicule, heure, prix) |
| DELETE | `/api/company/trips/{id}/` | admin | Annuler un voyage (notifie les passagers) |
| POST | `/api/company/trips/generate/` | admin | Générer des voyages à partir d'horaires types (7/15/30/90 jours) |

### 7.2 Recherche publique

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/trips/search/` | public | Rechercher des voyages (départ, arrivée, date, nb passagers, prix min/max, direct/escale) |
| GET | `/api/trips/{id}/` | public | Détail d'un voyage + places disponibles |

### 7.3 Agent — Programme du jour

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/agent/trips/today/` | agent | Voyages du jour de la gare/véhicule de l'agent |
| GET | `/api/agent/trips/{id}/passengers/` | agent | Liste des passagers d'un voyage |

---

## 8. Réservations & Billets

### 8.1 Voyageur

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/bookings/` | auth | Créer une réservation |
| GET | `/api/bookings/` | auth | Mes réservations (filtres : statut, date) |
| GET | `/api/bookings/{id}/` | auth | Détail d'une réservation |
| POST | `/api/bookings/{id}/cancel/` | auth | Annuler une réservation |
| GET | `/api/bookings/{id}/ticket/` | auth | Télécharger le billet PDF (avec QR code) |

### 8.2 Agent guichet

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/agent/bookings/` | agent | Enregistrer un passager au guichet (fonctionne hors ligne) |
| GET | `/api/agent/bookings/{ticket_number}/` | agent | Rechercher un billet par numéro |
| POST | `/api/agent/bookings/{id}/print/` | agent | Générer le billet imprimable |

### 8.3 Contrôleur — Embarquement

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/agent/scan/` | agent | Scanner un QR code et valider le billet |
| POST | `/api/agent/trips/{id}/boarding/{booking_id}/` | agent | Cocher manuellement un passager comme embarqué |
| POST | `/api/agent/trips/{id}/boarding/all/` | agent | Embarquer tous les passagers d'un coup |
| POST | `/api/agent/trips/{id}/boarding/validate/` | agent | Valider définitivement l'embarquement |
| GET | `/api/agent/scan/history/` | agent | Historique des 50 derniers QR codes scannés |

### 8.4 Admin Compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/bookings/` | admin | Toutes les réservations de la compagnie (filtres multiples) |
| GET | `/api/company/bookings/export/` | admin | Export PDF/Excel des réservations |

---

## 9. Paiements

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/payments/` | auth | Initier un paiement Mobile Money (booking ou colis) |
| GET | `/api/payments/{id}/` | auth | Statut d'un paiement |
| POST | `/api/payments/{id}/verify/` | auth | Vérifier/confirmer un paiement (OTP ou ref transaction) |
| GET | `/api/payments/{id}/receipt/` | auth | Télécharger le reçu PDF |
| POST | `/api/agent/payments/` | agent | Enregistrer un paiement espèces ou Mobile Money au guichet |

---

## 10. Colis

### 10.1 Agent guichet

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/agent/parcels/` | agent | Enregistrer un colis (hors ligne possible) |
| GET | `/api/agent/parcels/arrivals/` | agent | Colis arrivés en attente de notification |
| POST | `/api/agent/parcels/{id}/notify/` | agent | Envoyer SMS ou marquer comme appelé |

### 10.2 Suivi public

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/parcels/track/{tracking_number}/` | public | Suivi d'un colis par numéro |

### 10.3 Admin Compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/parcels/` | admin | Tous les colis de la compagnie (filtres : statut, période, destination) |
| GET | `/api/company/parcels/{id}/` | admin | Détail et historique d'un colis |
| PATCH | `/api/company/parcels/{id}/` | admin | Modifier les infos d'un colis |
| POST | `/api/company/parcels/{id}/status/` | admin | Changer le statut manuellement |
| POST | `/api/company/parcels/{id}/notify-again/` | admin | Renvoyer SMS au destinataire |
| GET | `/api/company/parcels/export/` | admin | Export Excel/PDF |

---

## 11. Réclamations

### 11.1 Voyageur

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/claims/` | auth | Déposer une réclamation |
| GET | `/api/claims/` | auth | Mes réclamations |
| GET | `/api/claims/{id}/` | auth | Détail d'une réclamation + réponse |

### 11.2 Admin Compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/claims/` | admin | Liste des réclamations reçues (filtres : statut, type) |
| GET | `/api/company/claims/{id}/` | admin | Détail d'une réclamation |
| POST | `/api/company/claims/{id}/respond/` | admin | Répondre et changer le statut |
| GET | `/api/company/claims/stats/` | admin | Taux de résolution, délai moyen de réponse |

### 11.3 Super Admin

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/claims/unresolved/` | super | Réclamations non traitées toutes compagnies |
| POST | `/api/super/claims/{id}/escalate/` | super | Relancer la compagnie concernée |
| POST | `/api/super/claims/{id}/close/` | super | Clôturer directement |

---

## 12. Signalements d'excès de vitesse

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/speed-reports/` | auth | Signaler un excès de vitesse (avec horodatage + GPS) |
| GET | `/api/company/speed-reports/` | admin | Signalements reçus par la compagnie |
| GET | `/api/super/speed-reports/` | super | Tous les signalements de la plateforme |
| PATCH | `/api/super/speed-reports/{id}/` | super | Changer le statut (pending → reviewed → closed) |

---

## 13. Avis Clients

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/reviews/` | auth | Déposer un avis (après voyage terminé) |
| GET | `/api/reviews/` | public | Avis publics d'une compagnie (`?company_id=`) |
| GET | `/api/company/reviews/` | admin | Tous les avis de la compagnie + statistiques |
| POST | `/api/company/reviews/{id}/respond/` | admin | Répondre à un avis |
| PATCH | `/api/company/reviews/{id}/respond/` | admin | Modifier la réponse |
| POST | `/api/company/reviews/{id}/flag/` | admin | Signaler un avis inapproprié au super admin |
| GET | `/api/company/reviews/word-cloud/` | admin | Données pour le nuage de mots |

---

## 14. Messagerie Agent ↔ Client

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/messages/` | auth | Liste des messages reçus/envoyés |
| POST | `/api/messages/` | auth | Envoyer un message (objet + corps) |
| GET | `/api/messages/{id}/` | auth | Lire un message (le marque comme lu) |
| GET | `/api/agent/trips/{id}/passenger-list/` | agent | Liste des passagers d'un voyage (pour choix destinataire) |

---

## 15. Notifications

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/notifications/` | auth | Liste des notifications in-app |
| POST | `/api/notifications/{id}/read/` | auth | Marquer comme lue |
| POST | `/api/notifications/read-all/` | auth | Tout marquer comme lu |

---

## 16. Agents (Admin Compagnie)

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/agents/` | admin | Liste des agents de la compagnie |
| POST | `/api/company/agents/` | admin | Créer un agent (génère mot de passe temporaire par SMS) |
| GET | `/api/company/agents/{id}/` | admin | Détail d'un agent + dernière activité |
| PATCH | `/api/company/agents/{id}/` | admin | Modifier nom, rôle, téléphone |
| POST | `/api/company/agents/{id}/deactivate/` | admin | Désactiver un agent |
| POST | `/api/company/agents/{id}/activate/` | admin | Réactiver un agent |
| POST | `/api/company/agents/{id}/reset-password/` | admin | Réinitialiser le mot de passe (SMS) |
| POST | `/api/company/agents/invite/` | admin | Inviter par SMS (lien création de compte) |
| DELETE | `/api/company/agents/{id}/` | admin | Supprimer (seulement si aucune activité) |

---

## 17. Tableaux de Bord & Statistiques

### 17.1 Voyageur

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/dashboard/traveler/` | auth | Prochain voyages, nb réservations actives, statuts, notifications récentes |

### 17.2 Agent

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/agent/dashboard/` | agent | Résumé : prochains départs, alertes, connexion status |

### 17.3 Admin Compagnie

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/company/dashboard/` | admin | KPIs : CA, taux de remplissage, réservations, note moyenne (filtre période) |
| GET | `/api/company/dashboard/revenue-chart/` | admin | Données graphique évolution CA |
| GET | `/api/company/dashboard/fill-rate-by-route/` | admin | Taux de remplissage par trajet |
| GET | `/api/company/dashboard/payment-breakdown/` | admin | Répartition moyens de paiement |
| GET | `/api/company/dashboard/top-routes/` | admin | Top 5 des trajets les plus rentables |
| GET | `/api/company/dashboard/agent-activity/` | admin | Activité des agents du jour |
| GET | `/api/company/dashboard/alerts/` | admin | Alertes actives (réclamations non traitées, colis non remis, signalements) |
| GET | `/api/company/dashboard/export/` | admin | Export PDF/Excel du rapport |

### 17.4 Super Admin

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/dashboard/` | super | Vue globale : nb compagnies, réservations, CA commissions, utilisateurs actifs |
| GET | `/api/super/dashboard/revenue-by-company/` | super | Répartition des revenus par compagnie |
| GET | `/api/super/dashboard/bookings-chart/` | super | Évolution des réservations |

---

## 18. Synchronisation Hors Ligne

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| POST | `/api/agent/sync/` | agent | Synchroniser les données hors ligne (bookings, parcels, validations) |
| GET | `/api/agent/sync/logs/` | agent | Historique des synchronisations de l'agent |
| GET | `/api/agent/sync/conflicts/` | agent | Liste des conflits résolus lors de la dernière sync |
| GET | `/api/agent/offline-data/` | agent | Télécharger les données du jour pour le mode hors ligne |

---

## 19. Configuration Globale (Super Admin)

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/settings/` | super | Lire tous les paramètres globaux |
| PATCH | `/api/super/settings/` | super | Modifier les paramètres (taux de commission global, SMS provider, mode maintenance) |
| GET | `/api/super/settings/commissions/` | super | Lire le taux de commission global + taux spécifiques par compagnie |
| PATCH | `/api/super/settings/commissions/` | super | Modifier les taux |
| GET | `/api/super/settings/payment-methods/` | super | Activer/désactiver les moyens de paiement au niveau plateforme |
| PATCH | `/api/super/settings/payment-methods/` | super | Modifier |

---

## 20. Journal d'Activités & Audit

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/super/activity-logs/` | super | Journal d'audit global (filtres : user, action, date) |
| GET | `/api/super/notifications/` | super | Notifications admin (nouvelles inscriptions, abonnements expirés, incidents) |

---

## 21. Pages Publiques

| Méthode | Endpoint | Auth | Description |
|---------|----------|------|-------------|
| GET | `/api/public/companies/` | public | Liste des compagnies partenaires (page d'accueil) |
| GET | `/api/public/companies/{id}/` | public | Fiche publique d'une compagnie (avis, note, contact) |
| GET | `/api/public/testimonials/` | public | Témoignages pour la page d'accueil |

---

## Notes d'implémentation

- **Offline** : les endpoints `POST /api/agent/bookings/`, `POST /api/agent/parcels/`, `POST /api/agent/scan/` et `POST /api/agent/trips/{id}/boarding/{booking_id}/` doivent accepter un champ `is_offline: true` + `offline_created_at` pour dater la saisie hors ligne.
- **Pagination** : tous les endpoints `GET` retournant des listes utilisent `PageNumberPagination` avec `?page=` et `?page_size=`.
- **Filtres** : utiliser `django-filter` pour les filtres sur statut, période, destination, etc.
- **Export** : les endpoints `/export/` génèrent un fichier PDF (ReportLab/WeasyPrint) ou Excel (openpyxl) selon le paramètre `?format=pdf|excel`.
- **Permissions Django** : créer une `BasePermission` par rôle (`IsSuperAdmin`, `IsCompanyAdmin`, `IsAgent`, `IsVoyageur`) basée sur `user.role.name`.
