TeryLivraison — MISE EN LIGNE PERMANENTE (PythonAnywhere gratuit)
===============================================================

Le site a besoin d'un vrai backend (base de données, réservations), donc
pas de simple hébergement de fichiers statiques. PythonAnywhere = hébergement
Python GRATUIT avec domaine permanent : tonpseudo.pythonanywhere.com

ÉTAPE 0 — L'essayer tout de suite (optionnel)
  Pendant que ton PC est allumé, le site est déjà en ligne via tunnel :
  l'URL est dans le chat Hermes (lhr.life). Elle change à chaque redémarrage
  du tunnel. Pour le permanent, suis les étapes ci-dessous.

ÉTAPE 1 — Créer le compte gratuit (2 min)
  1. Va sur https://www.pythonanywhere.com
  2. "Pricing" → onglet "Free" → "Create a Free Account"
  3. Choisis un nom d'utilisateur (ce sera ton domaine), email + mot de passe
  4. Confirme l'email reçu
  Note : si le site ne s'ouvre pas depuis la Chine, utilise un VPN ou fais-le
  depuis un autre accès — une seule fois.

ÉTAPE 2 — Créer la web app vide
  1. Console → onglet "Web" → "Add a new web app" → Next
  2. Choisis "Manual configuration" (PAS Flask automatique) → Python 3.12 → Next
  3. La web app est créée à https://TONPSEUDO.pythonanywhere.com

ÉTAPE 3 — Uploader le projet
  1. Console → onglet "Files" → ouvre le dossier /home/TONPSEUDO/
  2. Upload le fichier : delivery-booking.zip (sur ton Bureau/Downloads)
  3. Console → onglet "Consoles" → "Bash" → colle :
       cd ~ && unzip -o delivery-booking.zip -d delivery-booking
       mkvirtualenv --python=python3.12 kargo
       pip install -r delivery-booking/requirements.txt

ÉTAPE 4 — Brancher le WSGI
  1. Console → onglet "Web" → ta web app → section "Code"
  2. Dans "WSGI configuration file", remplace TOUT le contenu par :
       import sys
       sys.path.insert(0, "/home/TONPSEUDO/delivery-booking")
       from wsgi import application
     (remplace TONPSEUDO par ton vrai nom)
  3. Plus bas : "Virtualenv" → mets  /home/TONPSEUDO/.virtualenvs/kargo
  4. Bouton vert "Reload" en haut de la page

ÉTAPE 5 — C'est en ligne !
  Ouvre https://TONPSEUDO.pythonanywhere.com
  Admin : /admin  (compte admin@kargo.com / admin123)

CE QUI FONCTIONNE EN LIGNE
  Vitrine (nom, service, adresse, courriel, téléphone en grand, disponibilité
  temps réel, zone Québec), connexion simple nom + téléphone (email optionnel),
  réservation (tarifs par type de véhicule, heure de prise exacte), dispo temps
  réel, admin, sons, chat auto-ouvert.

CE QUI NE FONCTIONNE PAS ENCORE EN LIGNE
  Le chat IA : il se connecte à Hermes API qui tourne sur TON PC (127.0.0.1:8642).
  Sur PythonAnywhere, le bot répondra "service indisponible" — le client peut
  alors appeler directement le numéro de l'entreprise affiché sur le site.
  Pour un chat IA en ligne, il faudra héberger Hermes (ex. sur le VPS prévu)
  et mettre son URL dans config.json → hermes_api_url.

  Le tunnel de secours localhost.run : URL temporaire tant que ton PC est allumé.
