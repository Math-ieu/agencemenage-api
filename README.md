# Agence Ménage - API Backend

Cette application est l'interface programmable (API) qui alimente l'écosystème Agence Ménage. Elle est construite avec **Django** et **Django REST Framework (DRF)**.

## 🛠 Stack Technique
- **Framework** : Django 5.1
- **API** : Django REST Framework (DRF)
- **Authentification** : JWT (JSON Web Token) via `djangorestframework-simplejwt`
- **Base de données** : SQLite (par défaut pour le développement)

## 📁 Structure du Projet
- **`accounts/`** : Gestion des utilisateurs, profils et authentification personnalisée.
- **`clients/`** : Gestion des entités clients (Particuliers et Entreprises).
- **`agents/`** : Gestion des intervenants (femmes de ménage, auxiliaires).
- **`demandes/`** : Cœur du système - gestion des réservations, statuts (en attente, validé, NRP) et logs d'actions.
- **`missions/`** : Planification des interventions une fois les demandes validées.
- **`finance/`** : Suivi des factures, paiements, acomptes et gestion de la caisse.
- **`config/`** : Paramètres globaux de Django et routage API.

## ⚙️ Installation & Configuration

1. **Environnement virtuel** :
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

2. **Dépendances** :
   ```bash
   pip install -r requirements.txt
   ```

3. **Variables d'environnement** :
   Copiez le fichier `.env.example` en `.env` et ajustez les variables (SECRET_KEY, DEBUG, DATABASE_URL).

4. **Migrations & Superuser** :
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```

## 📡 Endpoints Principaux
- `POST /api/auth/login/` : Connexion et récupération des tokens JWT.
- `GET /api/demandes/` : Liste des demandes (supporte les filtres `statut`, `segment`, `service`).
- `PATCH /api/demandes/{id}/valider/` : Action personnalisée pour valider une demande.

## 🔍 Audit & Logs
Le système inclut un `AuditLog` qui enregistre chaque action critique (création, modification de statut) effectuée par les administrateurs pour une traçabilité totale.