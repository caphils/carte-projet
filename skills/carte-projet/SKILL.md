---
name: carte-projet
description: Carte reliée d'un projet de code — chaque élément (dossier, fichier, classe, fonction, vue, modèle, route, gabarit, script) avec son emplacement, sa route, son rôle et ses interactions, plus une page HTML interactive avec recherche. À utiliser quand l'utilisateur veut visualiser ou cartographier le projet, comprendre son architecture, ou demande où se trouve quelque chose, à quoi sert un élément, quelle vue sert une URL, qui appelle ou utilise quoi, quel gabarit une page affiche.
---

# Carte du projet

L'analyseur `scripts/analyser.py` (dans le dossier de cette skill) parcourt le projet, sans dépendance, et écrit dans
`<projet>/.carte-projet/` :

- `carte.json` : l'index (éléments, liens typés) ;
- `carte.html` : la page autonome à ouvrir dans un navigateur (arborescence, onglet Routes, recherche, graphe des liens) ;
- `.gitignore` qui exclut ces deux fichiers régénérables ;
- `roles.json` (s'il existe) : rôles écrits à la main ou par toi, à garder dans le dépôt.

Couvert : Python (définitions, imports, appels, héritage), Django (routes `path`/`include` depuis `ROOT_URLCONF`, vues,
modèles et relations, formulaires, admin, commandes, tests), gabarits (`extends`, `include`, `{% url %}`, `{% static %}`),
JS et CSS (rôle tiré du commentaire d'en-tête), documents Markdown. Les autres fichiers apparaissent dans l'arborescence.

Dans les commandes ci-dessous, `ANALYSEUR` est le chemin absolu de `scripts/analyser.py` dans le dossier de cette skill.

## Générer ou rafraîchir la carte

```bash
python3 ANALYSEUR <racine du projet>
```

Puis donne à l'utilisateur le chemin de `.carte-projet/carte.html` (sur macOS, `open` l'ouvre dans le navigateur). Régénère
après des modifications de code : l'analyse prend environ une seconde pour quelques centaines de fichiers.

## Ouvrir la carte pour l'utilisateur (recherche dans le code et modification)

Quand l'utilisateur veut parcourir la carte, retrouver une ligne de code ou la modifier, lance le serveur local en
arrière-plan (il recalcule la carte au démarrage et après chaque enregistrement) :

```bash
python3 ANALYSEUR <racine> --serveur          # ouvre http://127.0.0.1:8765/ dans le navigateur ; --port, --sans-navigateur
```

Dans la page servie : la recherche montre aussi les **lignes de code** contenant le texte (casse, expression régulière) ;
un clic ouvre le fichier à cette ligne, avec la fonction qui la contient ; « Modifier » (ou double-clic sur une ligne)
ouvre l'éditeur, ⌘S / Ctrl+S enregistre. Le serveur n'écoute que sur 127.0.0.1, exige le jeton de la page, n'écrit que
les fichiers texte du projet et refuse un enregistrement si le fichier a changé sur le disque entre-temps. La page
ouverte directement (`carte.html`, sans serveur) reste en lecture : carte, plan, fiches.

L'accueil montre le **plan relié** : l'arborescence dépliable jusqu'aux fonctions, avec les liens tracés entre ses
lignes (les liens d'un élément replié remontent sur son dossier ou son fichier) ; un clic sur une ligne isole ses liens
sortants (trait plein) et entrants (pointillé).

## Répondre à « où est… ? », « à quoi sert… ? », « qui utilise… ? »

```bash
python3 ANALYSEUR <racine> --chercher "bordereau envoi"   # meilleurs éléments, rôle, routes, interactions principales
python3 ANALYSEUR <racine> --noeud "bacterio/views.py::envoi"  # un élément : toutes ses interactions et sa docstring
```

Ajoute `--regenerer` si le code a changé depuis la dernière carte. La carte est un point de départ : lis ensuite le code
aux emplacements indiqués (`chemin:ligne`) avant d'affirmer un comportement. Les identifiants sont : `chemin` pour un
fichier, `chemin/` pour un dossier, `chemin::Nom` pour une classe ou fonction, `chemin::Classe.methode`, et
`route:/adresse/#nom_url` pour une route.

## Compléter les rôles (seulement si l'utilisateur le demande)

1. `python3 ANALYSEUR <racine> --manquants` liste les éléments dont le rôle n'est que déduit ou absent.
2. Commence par les plus utiles : dossiers de premier niveau, vues, modèles, modules, gabarits de page. Lis le code de
   chacun avant d'écrire.
3. Écris `<racine>/.carte-projet/roles.json` : un objet `{ "identifiant": "rôle en une phrase" }`, dans la langue du
   projet, qui dit à quoi sert l'élément pour l'utilisateur ou dans le circuit (pas une paraphrase du nom). Fusionne avec
   le fichier existant sans écraser les rôles déjà écrits.
4. Régénère la carte. Un rôle écrit l'emporte sur la docstring ; mieux vaut, quand c'est possible, proposer d'ajouter la
   docstring ou le commentaire d'en-tête dans le code lui-même.

## Limites à signaler si elles comptent

- Liens dynamiques non vus : gabarit choisi par une variable, `getattr`, registres de points d'extension, signaux.
- Les appels sont résolus par les imports : un appel sur une variable (`objet.methode()`) n'est relié que si l'objet est
  `self`, une classe ou un module connus.
- Autres frameworks (Flask, FastAPI, Express, Next.js) : arborescence, imports Python et rôles seulement, sans routes.
