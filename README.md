# Polymarket Telegram Bot

Bot Telegram qui surveille les marchés Polymarket et envoie des alertes pour les mouvements significatifs.

## Fonctionnalités

- **Surveillance automatique** : Poll les marchés Polymarket toutes les 3 minutes (configurable)
- **Alertes intelligentes** :
  - Nouveaux marchés avec volume significatif
  - Changements de prix importants (>10% par défaut)
  - Pics de volume (>50% d'augmentation)
- **Commandes Telegram** :
  - `/status` - État du bot et statistiques
  - `/trending` - Top 5 marchés par volume
  - `/help` - Aide
- **Endpoint santé** : `/health` pour monitoring Railway
- **Robuste** : Retry automatique avec backoff exponentiel, ne crash pas sur erreurs

---

## Déploiement Railway (Guide détaillé pour débutants)

### Étape 1 : Créer ton bot Telegram

1. Ouvre Telegram et cherche **@BotFather**
2. Envoie `/newbot`
3. Donne un nom à ton bot (ex: "Mon Polymarket Bot")
4. Donne un username unique terminant par `bot` (ex: `mon_polymarket_bot`)
5. **BotFather te donne un token** qui ressemble à : `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
6. **GARDE CE TOKEN PRÉCIEUSEMENT** - c'est ton `TELEGRAM_BOT_TOKEN`

### Étape 2 : Obtenir ton Chat ID

1. Ouvre Telegram et cherche **@userinfobot**
2. Clique sur "Start" ou envoie `/start`
3. Le bot te répond avec ton ID, un nombre comme `123456789`
4. C'est ton `TELEGRAM_CHAT_ID`

### Étape 3 : Mettre le code sur GitHub

1. Va sur [github.com](https://github.com) et connecte-toi (ou crée un compte)
2. Clique sur le **+** en haut à droite → **New repository**
3. Nom : `polymarket-bot`
4. Laisse en **Public** (ou Private si tu préfères)
5. **NE COCHE PAS** "Add a README" (on en a déjà un)
6. Clique **Create repository**

GitHub te montre les commandes à exécuter. Dans ton terminal :

```bash
cd ~/Desktop/polymarket-bot

# Initialiser git
git init

# Ajouter tous les fichiers
git add .

# Premier commit
git commit -m "Initial commit - Polymarket Telegram Bot"

# Connecter à GitHub (remplace TON_USERNAME par ton nom GitHub)
git remote add origin https://github.com/TON_USERNAME/polymarket-bot.git

# Envoyer le code
git branch -M main
git push -u origin main
```

### Étape 4 : Créer un compte Railway

1. Va sur [railway.app](https://railway.app)
2. Clique **Login** → **Login with GitHub**
3. Autorise Railway à accéder à ton GitHub

### Étape 5 : Déployer sur Railway

1. Une fois connecté, clique **New Project**
2. Choisis **Deploy from GitHub repo**
3. Sélectionne `polymarket-bot`
4. Railway commence à détecter le projet...

### Étape 6 : Configurer les variables d'environnement

C'est l'étape la plus importante !

1. Dans Railway, clique sur ton projet déployé
2. Va dans l'onglet **Variables**
3. Clique **+ New Variable** et ajoute :

| Variable | Valeur |
|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Le token de BotFather (ex: `7123456789:AAHxxx...`) |
| `TELEGRAM_CHAT_ID` | Ton ID de userinfobot (ex: `123456789`) |

4. (Optionnel) Tu peux aussi ajouter :
   - `POLL_INTERVAL_SECONDS` = `180` (vérifier toutes les 3 minutes)
   - `VOLUME_THRESHOLD_USD` = `10000` (alertes pour marchés > $10k)

### Étape 7 : Vérifier le déploiement

1. Railway redéploie automatiquement après l'ajout des variables
2. Clique sur l'onglet **Deployments** pour voir les logs
3. Tu devrais voir :
   ```
   Starting Polymarket Telegram Bot...
   Telegram bot started and listening for commands
   Starting market monitoring loop
   ```

4. **Sur Telegram**, envoie `/start` à ton bot - il devrait répondre !

### Étape 8 : Vérifier que tout fonctionne

- Envoie `/status` à ton bot → il affiche l'état
- Envoie `/trending` → il affiche les marchés populaires
- Visite `https://ton-app.railway.app/health` → tu vois `{"status": "healthy"}`

### Dépannage

**Le bot ne répond pas ?**
- Vérifie les logs dans Railway (onglet Deployments)
- Vérifie que les variables d'environnement sont bien configurées
- Assure-toi d'avoir démarré une conversation avec `/start`

**Erreur "TELEGRAM_BOT_TOKEN required" ?**
- Tu as oublié d'ajouter les variables d'environnement dans Railway

**Le déploiement échoue ?**
- Vérifie les logs d'erreur
- Assure-toi que tous les fichiers sont bien sur GitHub

### Coûts

Railway offre **$5 de crédit gratuit par mois** - largement suffisant pour ce bot qui consomme très peu de ressources.

---

## Variables d'environnement

| Variable | Requis | Défaut | Description |
|----------|--------|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | Oui | - | Token du bot Telegram |
| `TELEGRAM_CHAT_ID` | Oui | - | ID du chat pour les notifications |
| `POLL_INTERVAL_SECONDS` | Non | 180 | Intervalle de polling en secondes |
| `PORT` | Non | 8080 | Port pour le serveur health |
| `VOLUME_THRESHOLD_USD` | Non | 10000 | Seuil de volume pour alertes |
| `PRICE_CHANGE_THRESHOLD` | Non | 0.10 | Seuil de changement de prix (0.10 = 10%) |
| `WATCHED_TAGS` | Non | - | Tags à surveiller (séparés par virgules) |

## Licence

MIT
