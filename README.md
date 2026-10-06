# carte-projet

**English** · [Français](#français)

A skill for [Claude Code](https://claude.com/claude-code) that builds a **linked map of a code project**: every folder,
file, class, function, view, model, route, template and script, with its location, its URL, its role and its
interactions (imports, calls, inheritance, `extends`/`include`, `{% url %}`…). It produces a self-contained HTML page
with search, a linked outline and a graph of links. The page is in English or French (browser language, or the FR/EN
button).

## Install

### As a plugin (recommended)

In Claude Code:

```
/plugin marketplace add caphils/carte-projet
/plugin install carte-projet@carte-projet
```

### Manually

```bash
git clone https://github.com/caphils/carte-projet.git
cp -R carte-projet/skills/carte-projet ~/.claude/skills/
```

For a single project, copy the folder into `<project>/.claude/skills/` instead.

## Use

Just ask Claude: “map this project”, “where is the invoice form handled?”, “which view serves `/reports/`?”, “who calls
this function?”. The skill triggers on its own.

The analyzer also runs on its own (Python 3.9+, no dependencies):

```bash
python3 skills/carte-projet/scripts/analyser.py <project root>              # writes .carte-projet/carte.html and carte.json
python3 skills/carte-projet/scripts/analyser.py <root> --serveur            # local server: search the code, edit files
python3 skills/carte-projet/scripts/analyser.py <root> --chercher "keyword" # best matching elements and their links
python3 skills/carte-projet/scripts/analyser.py <root> --noeud "app/views.py::my_view"
python3 skills/carte-projet/scripts/analyser.py <root> --manquants          # elements without a written role
```

Hand-written roles go in `<project>/.carte-projet/roles.json` (`{ "identifier": "role" }`).

## Coverage

- **Python**: definitions, imports, calls, inheritance.
- **Django**: `path`/`include` routes from `ROOT_URLCONF`, views, models and relations, forms, admin, commands, tests.
- **Templates**: `extends`, `include`, `{% url %}`, `{% static %}`.
- **JS, CSS**: role taken from the header comment; **Markdown**: documents.
- Other frameworks (Flask, FastAPI, Express, Next.js): tree, Python imports and roles, without routes.

Dynamic links are not detected: template chosen by a variable, `getattr`, registries, signals.

## Local server security

`--serveur` listens on `127.0.0.1` only, requires the page token, writes only the project's text files and refuses to
save a file that changed on disk in the meantime.

## Video

A presentation video is produced by program in [`video/`](video/LISEZMOI.md) (English and French).

## License

MIT

---

## Français

Skill pour [Claude Code](https://claude.com/claude-code) qui dresse la **carte reliée d'un projet de code** : chaque
dossier, fichier, classe, fonction, vue, modèle, route, gabarit et script, avec son emplacement, sa route, son rôle et
ses interactions (imports, appels, héritage, `extends`/`include`, `{% url %}`…). Elle produit une page HTML autonome
avec recherche, plan relié et graphe des liens, en français ou en anglais (langue du navigateur, ou bouton FR/EN).

### Installation

Comme plugin, dans Claude Code :

```
/plugin marketplace add caphils/carte-projet
/plugin install carte-projet@carte-projet
```

À la main :

```bash
git clone https://github.com/caphils/carte-projet.git
cp -R carte-projet/skills/carte-projet ~/.claude/skills/
```

Pour un seul projet, copiez plutôt le dossier dans `<projet>/.claude/skills/`.

### Utilisation

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

### Couverture

- **Python** : définitions, imports, appels, héritage.
- **Django** : routes `path`/`include` depuis `ROOT_URLCONF`, vues, modèles et relations, formulaires, admin, commandes,
  tests.
- **Gabarits** : `extends`, `include`, `{% url %}`, `{% static %}`.
- **JS, CSS** : rôle tiré du commentaire d'en-tête ; **Markdown** : documents.
- Autres frameworks (Flask, FastAPI, Express, Next.js) : arborescence, imports Python et rôles, sans routes.

Liens dynamiques non détectés : gabarit choisi par une variable, `getattr`, registres, signaux.

### Sécurité du serveur

Le mode `--serveur` n'écoute que sur `127.0.0.1`, exige le jeton de la page, n'écrit que les fichiers texte du projet et
refuse un enregistrement si le fichier a changé sur le disque entre-temps.

### Licence

MIT
