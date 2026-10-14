# wikimasters-farm

Bot de farm multi-comptes pour [WikiMasters](https://www.wiki-masters.com).

> **Note / Statut** : Le bot est actuellement détecté dans son état actuel (pris dans une ban wave pour *"Comptes automatisés"*), mais ce n'est pas hyper compliqué de le rendre indétectable. Je lâche le projet en l'état car je n'y trouve plus trop d'intérêt avec la hype du jeu qui retombe énormément.
>
> ### Pourquoi c'est détecté
> - **Patterns trop mécaniques** : ouvertures de packs à intervalles réguliers, timing constant, exactement 1 échange par jour par bot au plafond (50 cartes et 700 WB).
> - **Empreinte réseau** : 40 comptes exécutés depuis la même adresse IP sans rotation de proxies résidentiels.
> - **Graphe d'échanges évident** : structure en étoile parfaite où 40 bots n'échangent qu'avec un seul et même compte cible.
>
> Pour le fiabiliser : randomiser les heures d'exécution, intégrer des proxies rotatifs (1 IP par bot), ajouter du jitter sur chaque action et simuler de l'activité humaine passive.

## Fonctionnalités

Automatise les routines quotidiennes sur les comptes secondaires et transfère les gains vers le compte principal :
- Ouverture automatique des boosters quotidiens (gestion du captcha Cloudflare Turnstile via Camoufox)
- Récupération des récompenses de succès (WikiBidous / WB)
- Recyclage en masse des doublons (Communes, Peu Communes, Rares en double) en WikiBidous
- Envoi automatique d'offres de troc vers le compte principal avec les cartes manquantes et les WB
- Acceptation sécurisée des trocs entrants sur le compte principal

## Prérequis

- Python 3.10+
- Dépendances Firefox pour Camoufox

## Installation

```bash
git clone https://github.com/votre-user/wikimasters-farm.git
cd wikimasters-farm

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Télécharger les binaires du navigateur Camoufox
camoufox fetch
```

## Configuration

Créer un fichier `accounts.json` à la racine :

```json
[
  {
    "email": "principal@example.com",
    "password": "mot_de_passe",
    "is_target": true
  },
  {
    "email": "bot1@example.com",
    "password": "mot_de_passe",
    "is_target": false
  },
  {
    "email": "bot2@example.com",
    "password": "mot_de_passe",
    "is_target": false
  }
]
```

- Un seul compte doit avoir `"is_target": true` (le compte principal qui reçoit les cartes et WB).
- Tous les autres comptes sont les bots de farm.

## Utilisation

Lancer la pipeline complète :

```bash
python run.py
```

### Options CLI

| Option | Description |
|---|---|
| `--limit N`, `-l N` | Limite l'exécution à N comptes de farm |
| `--accounts email ...`, `-a ...` | Exécute uniquement sur des comptes spécifiques |
| `--concurrency N`, `-c N` | Nombre de comptes traités en parallèle (défaut: 3) |
| `--skip-packs` | Ne pas ouvrir les boosters |
| `--skip-trades` | Ne pas envoyer/accepter d'échanges |
| `--accept-only` | Uniquement accepter les trocs en attente sur le compte principal |
| `--sync-target` | Rafraîchir le cache de la collection du compte principal |
| `--force-trade` | Forcer l'envoi des trocs même si le quota du jour est atteint |
| `--debug` | Activer les logs de debug détaillés |

### Exemples

```bash
# Test rapide sur 2 bots
python run.py --limit 2

# Exécution sans boosters (uniquement recyclage + trocs)
python run.py --skip-packs

# Accepter les trocs en attente sur le compte principal
python run.py --accept-only
```

## Fonctionnement

1. **Initialisation du compte cible** : Connexion, acceptation des demandes d'amis des bots, ouverture de ses boosters et mise en cache locale des cartes possédées.
2. **Farm en parallèle** :
   - Chaque bot se connecte via requêtes HTTP en réutilisant les sessions JWT Supabase en cache.
   - Si un challenge Turnstile apparaît, Camoufox est lancé en headless pour le valider.
   - Les boosters sont ouverts (avec gestion du backoff en cas de rate-limit).
   - Les succès débloqués sont réclamés.
   - Les cartes communes et doublons sont recyclées en WikiBidous.
   - Un échange est créé en proposant en priorité les cartes manquantes au compte principal, les WB et une carte commune de contrepartie.
3. **Récolte des échanges** : Le compte principal vérifie que l'émetteur du troc est bien un bot autorisé, valide les contraintes de sécurité et accepte les échanges.

## Licence

Distribué sous licence MIT. Voir `LICENSE` pour plus d'informations.
