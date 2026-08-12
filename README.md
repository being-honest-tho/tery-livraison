# TeryLivraison

Location de véhicules de livraison partout au Québec — site de réservation en ligne (camions et fourgonnettes).

## Fonctionnalités

- Vitrine : identité de l'entreprise, parc en temps réel, zone Québec
- Réservation en ligne : véhicule, durée (2 h = une seule journée, journée complète = plusieurs jours), colis (type, poids), adresses avec calcul de distance GPS automatique, date/heure de récupération, paiement sur place
- Espace client : connexion simple nom + téléphone (sans mot de passe), suivi des réservations
- Panneau admin séparé (app distincte, port 8778) : gestion des réservations, validation/refus, parc
- Chat assistant intégré (proxifié vers une API Hermes)

## Stack

- Python 3 + Flask (app utilisateur sur le port 8777, app admin sur 8778)
- SQLite (base `delivery.db`, créée automatiquement au premier démarrage)
- GPS : Photon (géocodage) + OSRM (distance)

## Lancer

```bash
python3 app.py        # app utilisateur  -> http://127.0.0.1:8777
python3 admin_app.py  # app admin       -> http://127.0.0.1:8778
```

La base et le `config.json` (secret_key, clé API Hermes) sont générés automatiquement au premier démarrage — ils ne sont pas versionnés.

## Tests

```bash
python3 check_ui_copy.py          # audit UI (vitrine + formulaire) via Playwright
python3 scripts/verify_booking_flow.py  # flux complet de réservation (apps démarrées)
```

## Aperçu statique (GitHub Pages)

La branche `gh-pages` contient un aperçu statique de la vitrine (généré depuis l'app, parc et disponibilités figés au moment de la génération). GitHub Pages ne fait pas tourner Flask : la réservation en ligne, le chat et la disponibilité temps réel nécessitent le serveur (déploiement permanent prévu sur PythonAnywhere).
