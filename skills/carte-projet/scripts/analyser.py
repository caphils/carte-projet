#!/usr/bin/env python3
"""Carte de projet : analyse un dépôt (Python, Django, gabarits, JS, CSS) et produit une carte reliée de ses éléments.

Chaque élément (dossier, fichier, classe, fonction, route, gabarit…) reçoit un type, un emplacement, un rôle et ses
interactions avec les autres (importe, appelle, utilise, affiche le gabarit, servie par la route…).

Sorties dans <projet>/.carte-projet/ :
  carte.json  l'index complet, lisible par une machine ;
  carte.html  la page interactive (arborescence, routes, recherche, graphe des liens), autonome et hors ligne.

Les rôles viennent, par ordre de priorité, de .carte-projet/roles.json (rôles écrits à la main ou par Claude), des
docstrings et commentaires d'en-tête, des tableaux de CLAUDE.md, puis d'une déduction d'après le type.

Usage :
  analyser.py [racine]                     analyse et écrit carte.json et carte.html
  analyser.py [racine] --chercher "texte"  cherche dans la carte (la régénère si besoin)
  analyser.py [racine] --noeud ID          détail d'un élément et toutes ses interactions
  analyser.py [racine] --manquants         éléments dont le rôle n'est que déduit (à décrire dans roles.json)
  analyser.py [racine] --serveur           sert la page en local (127.0.0.1) : recherche dans le code, modification

Aucune dépendance : bibliothèque standard de Python 3.8+.
"""
import argparse
import ast
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.setrecursionlimit(20000)

DOSSIER_SORTIE = ".carte-projet"
IGNORES = {".git", ".venv", "venv", "env", ".env", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox",
           "dist", "build", DOSSIER_SORTIE, ".idea", ".vscode", "staticfiles", "media", ".next", ".nuxt", "coverage",
           "htmlcov", ".ruff_cache", "site-packages"}
RESSOURCES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
              ".mp4", ".mp3", ".wav", ".m4a", ".mov", ".webm", ".zip", ".gz", ".tar", ".sqlite3", ".sqlite", ".db", ".bak",
              ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pyc", ".so", ".dylib", ".bin", ".pkl", ".npy"}
CONFIGS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".lock", ".env", ".example", ".properties"}
NOMS_CONFIG = {"Dockerfile", "Procfile", "Makefile", ".gitignore", ".dockerignore", ".editorconfig", "requirements.txt"}
SCRIPTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".sh", ".bash", ".zsh"}
STYLES = {".css", ".scss", ".sass", ".less"}
DOCUMENTS = {".md", ".rst", ".txt", ".adoc"}
GABARITS = {".html", ".htm", ".jinja", ".jinja2", ".j2", ".djhtml"}

BASES = {
    "Model": "modele", "AbstractUser": "modele", "AbstractBaseUser": "modele", "PermissionsMixin": "modele",
    "Form": "formulaire", "ModelForm": "formulaire", "BaseInlineFormSet": "formulaire", "BaseFormSet": "formulaire",
    "BaseModelFormSet": "formulaire", "Serializer": "formulaire", "ModelSerializer": "formulaire",
    "ModelAdmin": "admin", "TabularInline": "admin", "StackedInline": "admin", "SimpleHistoryAdmin": "admin",
    "TestCase": "test", "SimpleTestCase": "test", "TransactionTestCase": "test", "LiveServerTestCase": "test",
    "StaticLiveServerTestCase": "test",
    "View": "vue", "TemplateView": "vue", "ListView": "vue", "DetailView": "vue", "CreateView": "vue", "UpdateView": "vue",
    "DeleteView": "vue", "FormView": "vue", "RedirectView": "vue", "APIView": "vue", "GenericAPIView": "vue",
    "ViewSet": "vue", "ModelViewSet": "vue", "LoginView": "vue", "LogoutView": "vue",
    "BaseCommand": "commande", "AppConfig": "config", "Migration": "migration",
}
FONCTIONS_URL = {"reverse", "reverse_lazy", "redirect", "resolve_url", "url_for"}
FONCTIONS_RELATION = {"ForeignKey", "OneToOneField", "ManyToManyField", "ParentalKey"}
TYPES_SYMBOLE = {"classe", "modele", "vue", "formulaire", "admin", "test", "commande", "config", "fonction", "methode",
                 "migration"}
TYPES_A_DECRIRE = {"module", "gabarit", "script", "style", "classe", "modele", "vue", "formulaire", "admin", "commande",
                   "fonction", "dossier"}


def normaliser(texte):
    texte = unicodedata.normalize("NFD", texte or "").lower()
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


def resume(texte, longueur=400):
    """Premier paragraphe d'une docstring ou d'un commentaire, sur une ligne."""
    if not texte:
        return ""
    paragraphe = re.split(r"\n\s*\n", texte.strip(), maxsplit=1)[0]
    paragraphe = re.sub(r"\s+", " ", paragraphe).strip()
    return paragraphe if len(paragraphe) <= longueur else paragraphe[:longueur - 1].rstrip() + "…"


def nom_simple(noeud):
    """Dernier nom d'une expression : models.Model → Model, views.accueil → accueil."""
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return noeud.attr
    if isinstance(noeud, ast.Call):
        return nom_simple(noeud.func)
    if isinstance(noeud, ast.Subscript):
        return nom_simple(noeud.value)
    return ""


def chaine(noeud):
    return noeud.value if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) else None


def lire(chemin):
    try:
        return chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class Contexte:
    """Ce qu'un module Python voit : ses définitions et ses imports."""

    def __init__(self, fichier, module, paquet, arbre):
        self.fichier, self.module, self.paquet, self.arbre = fichier, module, paquet, arbre
        self.definitions = {}  # nom → id du symbole défini dans le module
        self.alias = {}  # nom importé → id (fichier ou symbole)


class Carte:
    def __init__(self, racine):
        self.racine = Path(racine).resolve()
        self.noeuds = {}
        self.liens_bruts = []  # (source, cible, type) ; type None : « appelle » ou « utilise », décidé à la fin
        self.modules = {}  # nom de module → id du fichier
        self.module_de = {}  # id du fichier → nom de module
        self.contextes = {}
        self.gabarits = {}  # clé (« bacterio/envoi.html ») → id
        self.statiques = {}  # clé (« js/htmx.min.js ») → id
        self.routes_par_nom = defaultdict(list)
        self.refs_url = []  # (source, nom d'URL)
        self.chaines = []  # (source, chaîne) : gabarits cités dans le code
        self.roles_ecrits = {}

    # ------------------------------------------------------------------ nœuds et liens
    def ajouter(self, id_, type_, nom, chemin, parent, ligne=None, role="", source="", doc="", **extra):
        noeud = {"id": id_, "type": type_, "nom": nom, "chemin": chemin, "parent": parent}
        if ligne:
            noeud["ligne"] = ligne
        if role:
            noeud["role"], noeud["source"] = role, source
        if doc:
            noeud["doc"] = doc[:3000]
        noeud.update({cle: valeur for cle, valeur in extra.items() if valeur})
        self.noeuds[id_] = noeud
        return noeud

    def lier(self, source, cible, type_=None):
        if source and cible and source != cible:
            self.liens_bruts.append((source, cible, type_))

    # ------------------------------------------------------------------ fichiers
    def lister_fichiers(self):
        fichiers = []
        try:
            sortie = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=self.racine,
                                    capture_output=True, text=True, check=True).stdout.splitlines()
            fichiers = [f for f in sortie if f and (self.racine / f).is_file()]
        except (OSError, subprocess.CalledProcessError):
            pass
        if not fichiers:
            for dossier, sous_dossiers, noms in os.walk(self.racine):
                sous_dossiers[:] = sorted(d for d in sous_dossiers if d not in IGNORES and not d.startswith("."))
                for nom in noms:
                    fichiers.append(str((Path(dossier) / nom).relative_to(self.racine)))
        return sorted({f.replace(os.sep, "/") for f in fichiers
                       if not any(partie in IGNORES for partie in Path(f).parts[:-1])})

    def type_fichier(self, chemin):
        p = Path(chemin)
        ext = p.suffix.lower()
        if ext == ".py":
            return "migration" if "migrations" in p.parts and p.name != "__init__.py" else "module"
        if ext in GABARITS or (ext == ".txt" and "templates" in p.parts):
            return "gabarit"
        if ext in SCRIPTS:
            return "script"
        if ext in STYLES:
            return "style"
        if p.name in NOMS_CONFIG or p.name.startswith("requirements") or ext in CONFIGS or p.name.startswith(".env"):
            return "config"
        if ext in DOCUMENTS:
            return "document"
        return "ressource"

    def construire_arborescence(self, fichiers):
        self.ajouter(".", "dossier", self.racine.name, "", None)
        for chemin in fichiers:
            parties = chemin.split("/")
            parent = "."
            for rang in range(1, len(parties)):
                id_dossier = "/".join(parties[:rang]) + "/"
                if id_dossier not in self.noeuds:
                    self.ajouter(id_dossier, "dossier", parties[rang - 1], id_dossier[:-1], parent)
                parent = id_dossier
            self.ajouter(chemin, self.type_fichier(chemin), parties[-1], chemin, parent)
            if "templates" in parties[:-1] and self.noeuds[chemin]["type"] == "gabarit":
                rang = len(parties) - 1 - parties[:-1][::-1].index("templates")
                self.gabarits.setdefault("/".join(parties[rang:]), chemin)
            if "static" in parties[:-1]:
                rang = len(parties) - 1 - parties[:-1][::-1].index("static")
                self.statiques.setdefault("/".join(parties[rang:]), chemin)

    # ------------------------------------------------------------------ Python : définitions
    def nom_module(self, chemin):
        parties = chemin[:-3].split("/")
        if parties[-1] == "__init__":
            parties = parties[:-1]
        return ".".join(parties)

    def analyser_python(self):
        for id_, noeud in list(self.noeuds.items()):
            if noeud["type"] not in ("module", "migration"):
                continue
            module = self.nom_module(id_)
            self.modules[module] = id_
            if module.startswith("src."):
                self.modules.setdefault(module[4:], id_)
            self.module_de[id_] = module
            texte = lire(self.racine / id_)
            try:
                arbre = ast.parse(texte)
            except (SyntaxError, ValueError):
                continue
            doc = ast.get_docstring(arbre)
            if doc:
                noeud.update(role=resume(doc), source="doc", doc=doc[:3000])
            paquet = module if id_.endswith("__init__.py") else module.rpartition(".")[0]
            ctx = self.contextes[id_] = Contexte(id_, module, paquet, arbre)
            if noeud["type"] == "migration":
                continue
            test = self.est_fichier_test(id_)
            for definition in arbre.body:
                self.definir(ctx, definition, id_, test)

    def est_fichier_test(self, chemin):
        nom = Path(chemin).name
        return nom.startswith("test") or nom.endswith("_test.py") or "/tests/" in "/" + chemin

    def definir(self, ctx, definition, parent, test, classe=None):
        if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        nom = definition.name
        id_ = f"{parent}.{nom}" if classe else f"{ctx.fichier}::{nom}"
        doc = ast.get_docstring(definition) or ""
        if isinstance(definition, ast.ClassDef):
            bases = [nom_simple(base) for base in definition.bases]
            type_ = "test" if test and any(b.endswith("TestCase") for b in bases) else next(
                (BASES[b] for b in bases if b in BASES), "classe")
            aide = next((chaine(instr.value) for instr in definition.body if isinstance(instr, ast.Assign)
                         and any(nom_simple(c) == "help" for c in instr.targets)), None)
            self.ajouter(id_, type_, nom, ctx.fichier, parent, definition.lineno, resume(doc or aide or ""),
                         "doc" if doc or aide else "", doc, bases=[b for b in bases if b],
                         fin=getattr(definition, "end_lineno", None))
            if classe is None:
                ctx.definitions[nom] = id_
            for interieur in definition.body:
                if isinstance(interieur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.definir(ctx, interieur, id_, test, classe=id_)
        else:
            type_ = "methode" if classe else "fonction"
            if test and nom.startswith("test"):
                type_ = "test"
            self.ajouter(id_, type_, nom, ctx.fichier, parent, definition.lineno, resume(doc), "doc" if doc else "", doc,
                         fin=getattr(definition, "end_lineno", None))
            if classe is None:
                ctx.definitions[nom] = id_

    # ------------------------------------------------------------------ Python : imports
    def module_absolu(self, ctx, instruction):
        if not instruction.level:
            return instruction.module or ""
        base = ctx.paquet.split(".") if ctx.paquet else []
        if instruction.level > 1:
            base = base[:len(base) - (instruction.level - 1)]
        return ".".join(base + ([instruction.module] if instruction.module else []))

    def analyser_imports(self):
        for id_, ctx in self.contextes.items():
            for instruction in ast.walk(ctx.arbre):
                if isinstance(instruction, ast.Import):
                    for alias in instruction.names:
                        if alias.asname:
                            cible = self.modules.get(alias.name)
                            if cible:
                                ctx.alias[alias.asname] = cible
                        else:
                            tete = alias.name.split(".")[0]
                            if tete in self.modules:
                                ctx.alias[tete] = self.modules[tete]
                            cible = self.modules.get(alias.name)
                        if cible:
                            self.lier(id_, cible, "importe")
                elif isinstance(instruction, ast.ImportFrom):
                    module = self.module_absolu(ctx, instruction)
                    fichier = self.modules.get(module)
                    for alias in instruction.names:
                        if alias.name == "*":
                            continue
                        cible = self.modules.get(f"{module}.{alias.name}")
                        if not cible and fichier:
                            symbole = f"{fichier}::{alias.name}"
                            cible = symbole if symbole in self.noeuds else self.reexport(fichier, alias.name) or fichier
                        if cible:
                            ctx.alias[alias.asname or alias.name] = cible
                            self.lier(id_, cible if "::" not in cible else cible.split("::")[0], "importe")

    def reexport(self, fichier, nom):
        """Un nom importé depuis un paquet qui le réexporte (from .models import X dans __init__.py)."""
        ctx = self.contextes.get(fichier)
        return ctx.alias.get(nom) if ctx else None

    # ------------------------------------------------------------------ Python : références
    def resoudre(self, ctx, expression, classe):
        if isinstance(expression, ast.Name):
            if expression.id in ("self", "cls") and classe:
                return classe
            return ctx.definitions.get(expression.id) or ctx.alias.get(expression.id)
        if isinstance(expression, ast.Attribute):
            base = self.resoudre(ctx, expression.value, classe)
            return self.membre(base, expression.attr) if base else None
        return None

    def membre(self, base, attr):
        noeud = self.noeuds.get(base)
        if not noeud:
            return None
        if noeud["type"] in ("module", "migration"):
            symbole = f"{base}::{attr}"
            if symbole in self.noeuds:
                return symbole
            sous_module = self.modules.get(f"{self.module_de.get(base, '')}.{attr}")
            return sous_module or self.reexport(base, attr) or base
        if f"{base}.{attr}" in self.noeuds:
            return f"{base}.{attr}"
        return base

    def analyser_references(self):
        for id_, ctx in self.contextes.items():
            if self.noeuds[id_]["type"] == "migration":
                continue
            for instruction in ctx.arbre.body:
                self.parcourir_definition(ctx, instruction, id_, None)

    def parcourir_definition(self, ctx, instruction, parent, classe):
        if isinstance(instruction, ast.ClassDef):
            id_ = f"{parent}.{instruction.name}" if classe else f"{ctx.fichier}::{instruction.name}"
            if id_ not in self.noeuds:  # classe imbriquée (Meta…) : rattachée à la classe englobante
                self.visiter(ctx, instruction, parent, classe)
                return
            for base in instruction.bases:
                cible = self.resoudre(ctx, base, None)
                if cible:
                    self.lier(id_, cible, "herite")
            for decorateur in instruction.decorator_list:
                self.visiter(ctx, decorateur, id_, id_)
            for interieur in instruction.body:
                if isinstance(interieur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.parcourir_definition(ctx, interieur, id_, id_)
                else:
                    self.visiter(ctx, interieur, id_, id_)
        elif isinstance(instruction, (ast.FunctionDef, ast.AsyncFunctionDef)):
            id_ = f"{parent}.{instruction.name}" if classe else f"{ctx.fichier}::{instruction.name}"
            for decorateur in instruction.decorator_list:
                self.visiter(ctx, decorateur, id_, classe)
            for interieur in instruction.body:
                self.visiter(ctx, interieur, id_, classe)
        else:
            self.visiter(ctx, instruction, parent, classe)

    def visiter(self, ctx, noeud, source, classe):
        if isinstance(noeud, ast.Call):
            fonction = nom_simple(noeud.func)
            cible = self.resoudre(ctx, noeud.func, classe)
            if cible:
                self.lier(source, cible, "appel")
            else:
                self.visiter(ctx, noeud.func, source, classe)
            arguments = list(noeud.args)
            if fonction in FONCTIONS_URL and arguments and chaine(arguments[0]):
                self.refs_url.append((source, chaine(arguments[0])))
            if fonction in FONCTIONS_RELATION and arguments:
                premier = arguments.pop(0)
                cible = self.resoudre(ctx, premier, classe) if not chaine(premier) else self.modele_par_nom(chaine(premier))
                if cible:
                    self.lier(source, cible, "relation")
            for argument in arguments:
                self.visiter(ctx, argument, source, classe)
            for mot_cle in noeud.keywords:
                if mot_cle.arg == "to" and fonction in FONCTIONS_RELATION:
                    cible = self.resoudre(ctx, mot_cle.value, classe) or self.modele_par_nom(chaine(mot_cle.value))
                    if cible:
                        self.lier(source, cible, "relation")
                        continue
                self.visiter(ctx, mot_cle.value, source, classe)
            return
        if isinstance(noeud, (ast.Name, ast.Attribute)):
            cible = self.resoudre(ctx, noeud, classe)
            if cible:
                self.lier(source, cible, None)
            elif isinstance(noeud, ast.Attribute):
                self.visiter(ctx, noeud.value, source, classe)
            return
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            if len(noeud.value) < 200:
                self.chaines.append((source, noeud.value))
            return
        for enfant in ast.iter_child_nodes(noeud):
            self.visiter(ctx, enfant, source, classe)

    def modele_par_nom(self, texte):
        if not texte:
            return None
        nom = texte.split(".")[-1]
        candidats = [i for i, n in self.noeuds.items() if n["type"] == "modele" and n["nom"] == nom]
        return candidats[0] if len(candidats) == 1 else None

    # ------------------------------------------------------------------ Django : routes
    def analyser_routes(self):
        racine_conf = None
        for ctx in self.contextes.values():
            for instruction in ctx.arbre.body:
                if isinstance(instruction, ast.Assign) and any(nom_simple(c) == "ROOT_URLCONF" for c in instruction.targets):
                    racine_conf = chaine(instruction.value) or racine_conf
        vus = set()
        if racine_conf and racine_conf in self.modules:
            self.routes_du_fichier(self.modules[racine_conf], "", "", vus)
        for id_ in sorted(self.contextes):
            if Path(id_).name == "urls.py" and id_ not in vus:
                self.routes_du_fichier(id_, "", "", vus)

    def routes_du_fichier(self, fichier, prefixe, espace, vus):
        if fichier in vus or fichier not in self.contextes:
            return
        vus.add(fichier)
        ctx = self.contextes[fichier]
        for instruction in ctx.arbre.body:
            if isinstance(instruction, ast.Assign) and any(nom_simple(c) == "app_name" for c in instruction.targets):
                espace = chaine(instruction.value) or espace
        listes = []
        for instruction in ctx.arbre.body:
            cibles = instruction.targets if isinstance(instruction, ast.Assign) else [instruction.target] if isinstance(
                instruction, ast.AugAssign) else []
            if any(nom_simple(c) == "urlpatterns" for c in cibles) and isinstance(instruction.value, (ast.List, ast.Tuple)):
                listes.extend(instruction.value.elts)
        for element in listes:
            if not isinstance(element, ast.Call) or nom_simple(element.func) not in ("path", "re_path", "url"):
                continue
            arguments = {mot.arg: mot.value for mot in element.keywords}
            motif = chaine(element.args[0]) if element.args else chaine(arguments.get("route"))
            vue = element.args[1] if len(element.args) > 1 else arguments.get("view")
            if motif is None or vue is None:
                continue
            complet = prefixe + motif
            nom = chaine(element.args[2]) if len(element.args) > 2 else chaine(arguments.get("name"))
            if isinstance(vue, ast.Call) and nom_simple(vue.func) == "include":
                cible = chaine(vue.args[0]) if vue.args else None
                sous_espace = chaine(next((m.value for m in vue.keywords if m.arg == "namespace"), None))
                if cible and cible in self.modules:
                    self.routes_du_fichier(self.modules[cible], complet, sous_espace or "", vus)
                continue
            self.creer_route(ctx, fichier, element.lineno, complet, nom, espace, vue)

    def creer_route(self, ctx, fichier, ligne, complet, nom, espace, vue):
        nom_url = f"{espace}:{nom}" if espace and nom else nom or ""
        id_ = f"route:/{complet}" + (f"#{nom_url}" if nom_url else "")
        texte_vue = ast.unparse(vue) if hasattr(ast, "unparse") else ""
        externe = texte_vue.endswith(".urls") or texte_vue.endswith("site.urls")
        self.ajouter(id_, "route", "/" + complet, fichier, fichier, ligne,
                     "Administration Django" if externe else "", "deduit" if externe else "", nom_url=nom_url,
                     vue_texte=texte_vue)
        if nom_url:
            self.routes_par_nom[nom_url].append(id_)
            if nom:
                self.routes_par_nom.setdefault(nom, [])
                if id_ not in self.routes_par_nom[nom]:
                    self.routes_par_nom[nom].append(id_)
        appel = vue if not (isinstance(vue, ast.Call) and nom_simple(vue.func) == "as_view") else vue.func.value
        cible = self.resoudre(ctx, appel, None)
        if cible:
            self.lier(id_, cible, "sert")
        if isinstance(vue, ast.Call):
            for mot in vue.keywords:
                gabarit = self.gabarits.get(chaine(mot.value) or "")
                if gabarit:
                    self.lier(id_, gabarit, "rend")

    # ------------------------------------------------------------------ gabarits, scripts, styles, documents
    def analyser_textes(self):
        for id_, noeud in self.noeuds.items():
            type_ = noeud["type"]
            if type_ not in ("gabarit", "script", "style", "document"):
                continue
            texte = lire(self.racine / id_)
            if type_ == "gabarit":
                self.analyser_gabarit(id_, noeud, texte)
            elif type_ in ("script", "style"):
                if ".min." in noeud["nom"]:
                    noeud.update(role="Bibliothèque externe (fichier minifié)", source="deduit")
                    continue
                commentaire = re.match(r"\s*(?:/\*+(.*?)\*/|((?:\s*//[^\n]*\n?)+)|((?:\s*#(?!!)[^\n]*\n?)+))", texte,
                                       re.S)
                if not commentaire and texte.startswith("#!"):
                    commentaire = re.match(r"#![^\n]*\n((?:\s*#[^\n]*\n?)+)", texte)
                if commentaire:
                    brut = next(g for g in commentaire.groups() if g)
                    brut = re.sub(r"^\s*(?://|#|\*)\s?", "", brut, flags=re.M)
                    noeud.update(role=resume(brut), source="commentaire", doc=brut.strip()[:3000])
            elif type_ == "document":
                titre = re.search(r"^#\s+(.+)$", texte, re.M)
                paragraphe = re.search(r"^(?!#|\||\s*[-*>`]|\s*$)(.+(?:\n(?!#|\s*$).+)*)", texte, re.M)
                role = " — ".join(p for p in (titre and titre.group(1).strip(), paragraphe and resume(paragraphe.group(1), 300)) if p)
                if role:
                    noeud.update(role=role, source="commentaire")

    def analyser_gabarit(self, id_, noeud, texte):
        debut = texte[:3000]
        commentaire = re.search(r"\{#(.*?)#\}|\{%\s*comment\s*%\}(.*?)\{%\s*endcomment\s*%\}|<!--(.*?)-->", debut, re.S)
        if commentaire:
            brut = next(g for g in commentaire.groups() if g is not None)
            noeud.update(role=resume(brut), source="commentaire", doc=brut.strip()[:3000])
        for genre, cle in re.findall(r"\{%\s*(extends|include)\s+[\"']([^\"']+)[\"']", texte):
            cible = self.gabarits.get(cle)
            if cible:
                self.lier(id_, cible, "etend" if genre == "extends" else "inclut")
        for nom in re.findall(r"\{%\s*url\s+[\"']([^\"']+)[\"']", texte):
            self.refs_url.append((id_, nom))
        for cle in re.findall(r"\{%\s*static\s+[\"']([^\"']+)[\"']", texte):
            cible = self.statiques.get(cle)
            if cible:
                self.lier(id_, cible, "charge")

    def lier_chaines(self):
        for source, texte in self.chaines:
            cible = self.gabarits.get(texte)
            if cible:
                self.lier(source, cible, "rend")
            elif texte in self.statiques:
                self.lier(source, self.statiques[texte], "charge")
        for source, nom in self.refs_url:
            for route in self.routes_par_nom.get(nom) or self.routes_par_nom.get(nom.split(":")[-1], []):
                self.lier(source, route, "lien_url")

    # ------------------------------------------------------------------ classification et rôles
    def classer(self):
        # Les sous-classes d'une classe du projet prennent son type (un modèle abstrait, une vue de base…)
        for _ in range(5):
            for source, cible, type_ in self.liens_bruts:
                if type_ == "herite" and self.noeuds.get(source, {}).get("type") == "classe":
                    type_parent = self.noeuds.get(cible, {}).get("type")
                    if type_parent in ("modele", "formulaire", "vue", "admin", "test", "commande"):
                        self.noeuds[source]["type"] = type_parent
        for source, cible, type_ in self.liens_bruts:
            if type_ == "sert" and self.noeuds.get(cible, {}).get("type") in ("fonction", "classe"):
                self.noeuds[cible]["type"] = "vue"
        for noeud in self.noeuds.values():
            if noeud["type"] in ("methode", "fonction") and "/management/commands/" in "/" + noeud["chemin"] \
                    and noeud["nom"] == "handle":
                noeud["type"] = "commande"

    def finaliser_liens(self):
        ancetres = {}

        def lignee(id_):
            if id_ not in ancetres:
                parent = self.noeuds.get(id_, {}).get("parent")
                ancetres[id_] = ({parent} | lignee(parent)) if parent and parent in self.noeuds else set()
            return ancetres[id_]

        liens = {}
        for source, cible, type_ in self.liens_bruts:
            if source not in self.noeuds or cible not in self.noeuds or source == cible:
                continue
            if cible in lignee(source) or source in lignee(cible):
                continue  # une méthode qui utilise sa classe, un module qui contient sa fonction
            type_cible = self.noeuds[cible]["type"]
            if type_ is None and Path(source).name == "urls.py":
                continue  # urls.py cite ses vues : le lien « route → vue » le dit déjà
            if type_ in (None, "appel"):
                type_ = "appelle" if type_ == "appel" and type_cible in ("fonction", "methode", "vue", "commande") \
                    else "utilise"
            fichier_source = self.noeuds[source]["chemin"]
            if self.est_fichier_test(fichier_source) and type_ in ("appelle", "utilise", "lien_url", "importe"):
                type_ = "teste"
            cle = (source, cible)
            rang = ["importe", "utilise", "teste", "appelle", "lien_url", "charge", "inclut", "etend", "rend", "relation",
                    "herite", "sert"]
            if cle not in liens or rang.index(type_) > rang.index(liens[cle]):
                liens[cle] = type_
        self.liens = sorted([s, c, t] for (s, c), t in liens.items())
        routes = defaultdict(list)
        for source, cible, type_ in self.liens:
            if type_ == "sert":
                routes[cible].append(self.noeuds[source]["nom"])
        for id_, liste in routes.items():
            self.noeuds[id_]["routes"] = sorted(set(liste))

    def roles_claude_md(self):
        roles = {}
        for nom in ("CLAUDE.md", "README.md", "AGENTS.md"):
            texte = lire(self.racine / nom)
            for cellule, role in re.findall(r"^\|\s*`?([^`|]+?)`?\s*\|\s*([^|]+?)\s*\|", texte, re.M):
                cellule = cellule.strip().rstrip("/")
                for candidat in (cellule + "/", cellule):
                    if candidat in self.noeuds and candidat not in roles:
                        roles[candidat] = role.strip()
        return roles

    def deduire_role(self, noeud):
        type_, nom, chemin = noeud["type"], noeud["nom"], noeud["chemin"]
        dossier = Path(chemin).parent.name or self.racine.name
        if type_ == "module":
            for motif, role in (("views", "Vues de {d} : pages et actions"), ("models", "Modèles de données de {d}"),
                                ("urls", "Routes (adresses) de {d}"), ("forms", "Formulaires de {d}"),
                                ("admin", "Administration Django de {d}"), ("apps", "Configuration de l'application {d}"),
                                ("settings", "Réglages du projet"), ("signals", "Signaux de {d}"),
                                ("serializers", "Sérialiseurs de {d}"), ("tasks", "Tâches de fond de {d}"),
                                ("wsgi", "Point d'entrée du serveur web (WSGI)"), ("asgi", "Point d'entrée du serveur (ASGI)"),
                                ("manage", "Commandes Django (manage.py)"), ("__init__", "Paquet {d}"),
                                ("test", "Tests de {d}")):
                if Path(nom).stem.startswith(motif):
                    return role.format(d=dossier)
            if "/management/commands/" in "/" + chemin:
                return f"Commande manage.py {Path(nom).stem}"
            return ""
        return {
            "migration": "Migration de la base de données",
            "route": "Adresse servie par {v}".format(v=noeud.get("vue_texte", "une vue")),
            "modele": "Modèle de données (table)", "formulaire": "Formulaire", "admin": "Écran d'administration",
            "test": "Test automatique", "commande": "Commande manage.py", "config": "Configuration",
            "vue": "Vue : page ou action servie par " + ", ".join(noeud.get("routes", [])[:3]) if noeud.get("routes") else "",
            "ressource": "Fichier de ressource", "dossier": "",
        }.get(type_, "")

    def appliquer_roles(self):
        chemin_roles = self.racine / DOSSIER_SORTIE / "roles.json"
        try:
            self.roles_ecrits = json.loads(lire(chemin_roles) or "{}")
        except json.JSONDecodeError:
            print(f"roles.json illisible : {chemin_roles}", file=sys.stderr)
        claude_md = self.roles_claude_md()
        for id_, noeud in self.noeuds.items():
            if id_ in self.roles_ecrits and self.roles_ecrits[id_]:
                noeud.update(role=self.roles_ecrits[id_], source="ecrit")
            elif noeud.get("role"):
                continue
            elif id_ in claude_md:
                noeud.update(role=claude_md[id_], source="claude_md")
            else:
                role = self.deduire_role(noeud)
                if role:
                    noeud.update(role=role, source="deduit")
            if noeud["type"] == "route" and not noeud.get("role"):
                noeud.update(role=f"Adresse servie par {noeud.get('vue_texte', '')}", source="deduit")
        # une route reprend le rôle de sa vue
        for source, cible, type_ in self.liens:
            if type_ == "sert" and self.noeuds[cible].get("role") and self.noeuds[source].get("source") == "deduit":
                self.noeuds[source].update(role=self.noeuds[cible]["role"], source="vue")

    # ------------------------------------------------------------------ ensemble
    def analyser(self):
        self.construire_arborescence(self.lister_fichiers())
        self.analyser_python()
        self.analyser_imports()
        self.analyser_references()
        self.analyser_routes()
        self.analyser_textes()
        self.lier_chaines()
        self.classer()
        self.finaliser_liens()
        self.appliquer_roles()
        return self

    def donnees(self):
        types = defaultdict(int)
        for noeud in self.noeuds.values():
            types[noeud["type"]] += 1
        noeuds = []
        for noeud in self.noeuds.values():
            noeud = dict(noeud)
            noeud.pop("bases", None)
            noeuds.append(noeud)
        return {"projet": self.racine.name, "racine": str(self.racine),
                "genere_le": datetime.datetime.now().isoformat(timespec="seconds"),
                "types": dict(sorted(types.items())), "noeuds": noeuds, "liens": self.liens}


# ---------------------------------------------------------------------- recherche (même règle que la page)
POIDS = (("nom", 10), ("routes_texte", 6), ("nom_url", 6), ("chemin", 4), ("role", 3), ("doc", 1))
LIBELLES = {
    "importe": ("importe", "importé par"), "appelle": ("appelle", "appelé par"), "utilise": ("utilise", "utilisé par"),
    "herite": ("hérite de", "parent de"), "sert": ("affiche la vue", "servie par la route"),
    "rend": ("affiche le gabarit", "affiché par"), "inclut": ("inclut", "inclus dans"), "etend": ("étend", "étendu par"),
    "lien_url": ("mène à la route", "lien depuis"), "relation": ("relation vers", "référencé par"),
    "charge": ("charge", "chargé par"), "teste": ("teste", "testé par"),
}


def chercher(donnees, requete, limite=15):
    mots = normaliser(requete).split()
    if not mots:
        return []
    resultats = []
    for noeud in donnees["noeuds"]:
        champs = dict(noeud, routes_texte=" ".join(noeud.get("routes", [])))
        score = 0
        for mot in mots:
            meilleur = 0
            for champ, poids in POIDS:
                valeur = normaliser(str(champs.get(champ, "")))
                if mot in valeur:
                    meilleur = max(meilleur, poids * (3 if valeur == mot else 2 if valeur.startswith(mot) else 1))
            if not meilleur:
                break
            score += meilleur
        else:
            if noeud["type"] in ("methode", "test", "migration"):
                score *= 0.6
            if noeud["type"] in ("ressource", "document", "config"):
                score *= 0.4
            resultats.append((score, noeud))
    resultats.sort(key=lambda r: (-r[0], len(r[1]["id"])))
    return [noeud for _, noeud in resultats[:limite]]


def interactions(donnees, id_):
    sortants, entrants = defaultdict(list), defaultdict(list)
    for source, cible, type_ in donnees["liens"]:
        if source == id_:
            sortants[type_].append(cible)
        elif cible == id_:
            entrants[type_].append(source)
    return sortants, entrants


def emplacement(noeud):
    return noeud["chemin"] + (f":{noeud['ligne']}" if noeud.get("ligne") else "")


def afficher(donnees, noeud, complet=False):
    print(f"[{noeud['type']}] {noeud['nom']}  —  {emplacement(noeud)}")
    print(f"    id : {noeud['id']}")
    if noeud.get("routes"):
        print(f"    routes : {', '.join(noeud['routes'])}")
    if noeud.get("nom_url"):
        print(f"    nom d'URL : {noeud['nom_url']}")
    if noeud.get("role"):
        print(f"    rôle : {noeud['role']}" + ("  (déduit)" if noeud.get("source") == "deduit" else ""))
    index = {n["id"]: n for n in donnees["noeuds"]}
    sortants, entrants = interactions(donnees, noeud["id"])
    limite = None if complet else 4
    for groupe, sens in ((sortants, 0), (entrants, 1)):
        for type_, ids in sorted(groupe.items()):
            noms = [index[i]["nom"] if index[i]["type"] not in ("module", "gabarit") else index[i]["chemin"] for i in ids]
            reste = f" (+{len(noms) - limite})" if limite and len(noms) > limite else ""
            print(f"    {LIBELLES[type_][sens]} : {', '.join(noms[:limite])}{reste}")
    if complet and noeud.get("doc"):
        print("\n" + noeud["doc"])


def manquants(donnees):
    """Éléments dont le rôle n'est que déduit ou absent : dossiers de premier niveau, fichiers et symboles publics."""
    def a_decrire(noeud):
        if noeud["type"] == "dossier":
            return noeud["id"].count("/") == 1 and not noeud.get("role")
        return noeud["type"] in TYPES_A_DECRIRE and noeud.get("source") in (None, "deduit") \
            and not noeud["nom"].startswith("_")
    return [noeud for noeud in donnees["noeuds"] if a_decrire(noeud)]


# ---------------------------------------------------------------------- sorties
def page(donnees, serveur=None):
    """La page autonome, données intégrées ; `serveur` ({jeton}) active la recherche dans le code et la modification."""
    modele = (Path(__file__).resolve().parent / "page.html").read_text(encoding="utf-8")
    integrer = lambda valeur: json.dumps(valeur, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return modele.replace("/*__DONNEES__*/null", integrer(donnees)).replace("/*__SERVEUR__*/null", integrer(serveur))


def ecrire(carte, donnees):
    sortie = carte.racine / DOSSIER_SORTIE
    sortie.mkdir(exist_ok=True)
    (sortie / "carte.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "carte.html").write_text(page(donnees), encoding="utf-8")
    ignore = sortie / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Carte régénérée à la demande ; roles.json (rôles écrits) se garde dans le dépôt\ncarte.json\n"
                          "carte.html\n", encoding="utf-8")
    return sortie


def charger(racine, regenerer=False):
    chemin = Path(racine).resolve() / DOSSIER_SORTIE / "carte.json"
    if regenerer or not chemin.exists():
        carte = Carte(racine).analyser()
        donnees = carte.donnees()
        ecrire(carte, donnees)
        return donnees
    return json.loads(chemin.read_text(encoding="utf-8"))


def principal():
    analyseur = argparse.ArgumentParser(description="Carte reliée d'un projet : éléments, routes, rôles, interactions.")
    analyseur.add_argument("racine", nargs="?", default=".")
    analyseur.add_argument("--chercher", metavar="TEXTE")
    analyseur.add_argument("--noeud", metavar="ID")
    analyseur.add_argument("--manquants", action="store_true")
    analyseur.add_argument("--limite", type=int, default=15)
    analyseur.add_argument("--regenerer", action="store_true", help="réanalyser avant de chercher")
    analyseur.add_argument("--serveur", action="store_true",
                           help="servir la page en local : recherche dans le code et modification des fichiers")
    analyseur.add_argument("--port", type=int, default=8765)
    analyseur.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    options = analyseur.parse_args()

    if options.serveur:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from serveur import servir
        servir(Path(options.racine).resolve(), lambda racine: Carte(racine).analyser(), ecrire, page, options.port,
               not options.sans_navigateur)
        return

    if options.chercher or options.noeud or options.manquants:
        donnees = charger(options.racine, options.regenerer)
        if options.chercher:
            resultats = chercher(donnees, options.chercher, options.limite)
            if not resultats:
                print("Aucun élément ne correspond.")
            for noeud in resultats:
                afficher(donnees, noeud)
                print()
        if options.noeud:
            noeud = next((n for n in donnees["noeuds"] if n["id"] == options.noeud), None)
            if noeud:
                afficher(donnees, noeud, complet=True)
            else:
                print(f"Élément introuvable : {options.noeud}")
        if options.manquants:
            liste = manquants(donnees)
            print(f"{len(liste)} élément(s) au rôle seulement déduit ou absent :")
            for noeud in liste:
                print(f"{noeud['id']}\t[{noeud['type']}]\t{noeud.get('role', '')}")
        return

    carte = Carte(options.racine).analyser()
    donnees = carte.donnees()
    sortie = ecrire(carte, donnees)
    resume_types = ", ".join(f"{n} {t}" for t, n in sorted(donnees["types"].items(), key=lambda x: -x[1]))
    print(f"Carte de {donnees['projet']} : {len(donnees['noeuds'])} éléments, {len(donnees['liens'])} liens ({resume_types}).")
    print(f"Rôles à décrire : {len(manquants(donnees))} (voir --manquants).")
    print(f"Page : {sortie / 'carte.html'}")


if __name__ == "__main__":
    principal()
