# carte-projet

Skill pour [Claude Code](https://claude.com/claude-code) qui dresse la **carte reliée d'un projet de code** : chaque
dossier, fichier, classe, fonction, vue, modèle, route, gabarit et script, avec son emplacement, sa route, son rôle et
ses interactions (imports, appels, héritage, `extends`/`include`, `{% url %}`…). Elle produit une page HTML autonome
avec recherche, plan relié et graphe des liens.

*A Claude Code skill that builds a linked map of a code project (Python, Django, templates, JS, CSS) with an
interactive, searchable HTML page. Interface and messages are in French.*

## Installation

### Comme plugin (recommandé)

Dans Claude Code :

```
/plugin marketplace add caphils/carte-projet
/plugin install carte-projet@carte-projet
```

### À la main

```bash
git clone https://github.com/caphils/carte-projet.git
cp -R carte-projet/skills/carte-projet ~/.claude/skills/
```

Pour un seul projet, copiez plutôt le dossier dans `<projet>/.claude/skills/`.

## Utilisation

Demandez simplement à Claude : « fais la carte du projet », « où est géré le bordereau d'envoi ? », « quelle vue sert
`/rapports/` ? », « qui appelle cette fonction ? ». La skill se déclenche d'elle-même.

L'analyseur s'utilise aussi seul (Python 3.9+, aucune dépendance) :

```bash
python3 skills/carte-projet/scripts/analyser.py <racine du projet>              # écrit .carte-projet/carte.html et carte.json
python3 skills/carte-projet/scripts/analyser.py <racine> --serveur              # serveur local : recherche dans le code, édition
python3 skills/carte-projet/scripts/analyser.py <racine> --chercher "mot clé"   # meilleurs éléments et leurs liens
python3 skills/carte-projet/scripts/analyser.py <racine> --noeud "app/views.py::ma_vue"
python3 skills/carte-projet/scripts/analyser.py <racine> --manquants            # éléments sans rôle écrit
```

Les rôles écrits à la main se placent dans `<projet>/.carte-projet/roles.json` (`{ "identifiant": "rôle" }`).

## Couverture

- **Python** : définitions, imports, appels, héritage.
- **Django** : routes `path`/`include` depuis `ROOT_URLCONF`, vues, modèles et relations, formulaires, admin, commandes,
  tests.
- **Gabarits** : `extends`, `include`, `{% url %}`, `{% static %}`.
- **JS, CSS** : rôle tiré du commentaire d'en-tête ; **Markdown** : documents.
- Autres frameworks (Flask, FastAPI, Express, Next.js) : arborescence, imports Python et rôles, sans routes.

Liens dynamiques non détectés : gabarit choisi par une variable, `getattr`, registres, signaux.

## Sécurité du serveur

Le mode `--serveur` n'écoute que sur `127.0.0.1`, exige le jeton de la page, n'écrit que les fichiers texte du projet et
refuse un enregistrement si le fichier a changé sur le disque entre-temps.

## Licence

MIT
