"""Vidéo de présentation de la skill carte-projet, tournée sur la carte du site officiel de Django.

    python video/scenario.py                (français)
    LANGUE=en python video/scenario.py      (anglais : page de la carte en anglais, textes anglais)

Chaque légende et chaque carton reçoit une réplique de voix off dans sonoriser.py (REPLIQUES, dans le même ordre).
"""
import asyncio
import os

from tournage import Tournage

LANGUE = os.environ.get("LANGUE", "fr")
NOM = "carte_projet" + ("_en" if LANGUE == "en" else "")

TEXTES = {
    "fr": {
        "titre": ("carte-projet", "La carte reliée de votre code · skill pour Claude Code"),
        "probleme": ("Vous découvrez un projet…", ["Où est géré ce modèle ?", "Quelle vue sert cette adresse ?",
                                                  "Qui appelle cette fonction ? Que casse-t-on en la modifiant ?"]),
        "demande": ("Demandez simplement à Claude", "« Fais la carte du projet. »"),
        "chiffres": "Exemple : le site officiel de Django. {e} éléments, {l} liens, analysés en moins d'une seconde.",
        "plan": "Le plan relié : tout le projet, avec les liens tracés entre ses parties.",
        "clic_plan": "Un clic sur le blog : on voit aussitôt ce qu'il utilise, et qui l'utilise.",
        "recherche": "La recherche trouve modèles, vues, gabarits, routes… et les lignes de code.",
        "fiche": "Chaque élément a sa fiche : emplacement exact, rôle, et son code.",
        "interactions": "Et toutes ses interactions : la route qu'il sert, ce qu'il appelle, qui l'utilise.",
        "routes": "L'onglet Routes : chaque adresse du site, et la vue qui la sert.",
        "clic_route": "Un clic sur une adresse mène à sa vue, à son gabarit, à son code.",
        "code": "Avec le serveur local, la recherche parcourt aussi chaque ligne de code.",
        "fichier": "Un clic ouvre le fichier à la bonne ligne, dans la bonne fonction.",
        "modifier": "« Modifier » : on corrige sur place, ⌘S enregistre, et la carte se met à jour.",
        "avantages": ("Pourquoi carte-projet ?", [
            "Aucune dépendance : Python seul, une seconde d'analyse.",
            "Django compris : routes, vues, modèles, formulaires, gabarits.",
            "Tout reste sur votre machine : serveur local, rien n'est envoyé.",
            "Claude s'en sert pour répondre : où est-ce, à quoi ça sert, qui l'utilise."]),
        "installer": "Installez-la dans Claude Code",
        "separateur": " ",
    },
    "en": {
        "titre": ("carte-projet", "The linked map of your code · a Claude Code skill"),
        "probleme": ("You're new to a project…", ["Where is this model handled?", "Which view serves this URL?",
                                                 "Who calls this function? What breaks if I change it?"]),
        "demande": ("Just ask Claude", "“Map this project.”"),
        "chiffres": "Example: the official Django website. {e} elements, {l} links, analyzed in under a second.",
        "plan": "The linked outline: the whole project, with links drawn between its parts.",
        "clic_plan": "Click the blog: you instantly see what it uses, and what uses it.",
        "recherche": "Search finds models, views, templates, routes… and lines of code.",
        "fiche": "Every element has its card: exact location, role, and its code.",
        "interactions": "And all its interactions: the route it serves, what it calls, who uses it.",
        "routes": "The Routes tab: every URL of the site, and the view that serves it.",
        "clic_route": "Click a URL to reach its view, its templates, its code.",
        "code": "With the local server, search also scans every line of code.",
        "fichier": "One click opens the file at the right line, in the right function.",
        "modifier": "“Edit”: fix it in place, ⌘S saves, and the map updates.",
        "avantages": ("Why carte-projet?", [
            "No dependencies: plain Python, one-second analysis.",
            "Understands Django: routes, views, models, forms, templates.",
            "Everything stays on your machine: local server, nothing is sent.",
            "Claude uses it to answer: where is it, what is it for, who uses it."]),
        "installer": "Install it in Claude Code",
        "separateur": ",",
    },
}[LANGUE]


def nombre(n):
    return f"{n:,}".replace(",", TEXTES["separateur"])


async def main():
    x = TEXTES
    async with Tournage(NOM) as t:
        await t.ouvrir(f"/?lang={LANGUE}")
        await t.carton(*x["titre"], duree=4)
        await t.carton(x["probleme"][0], "", duree=6, points=x["probleme"][1])
        await t.carton(x["demande"][0], "", duree=4.5, code=True, points=[x["demande"][1]])

        # Accueil : chiffres de l'analyse (lus sur la page : ils suivent le dépôt cloné)
        elements, liens = await t.page.evaluate(
            "[...document.querySelector('#meta').textContent.matchAll(/\\d+/g)].slice(0, 2).map(m => +m[0])")
        t.legende(x["chiffres"].format(e=nombre(elements), l=nombre(liens)))
        await t.zoom(".tuiles", marge=30)
        await t.pause(4.5)
        t.dezoom()
        await t.pause(0.8)

        # Plan relié
        await t.defiler_vers("#zone-plan", position="start", pause=1.4)
        t.legende(x["plan"])
        await t.pause(2.5)
        await t.cliquer(".pl-ligne[data-id='blog/'] .pl-etiquette .nom")
        t.legende(x["clic_plan"])
        await t.pause(3.5)

        # Recherche → fiche d'un modèle
        await t.taper("#q", "Entry")
        t.legende(x["recherche"])
        await t.defiler_vers(".resultats", position="start", pause=1.2)
        await t.pause(2.2)
        await t.cliquer(".resultats li[data-id='blog/models.py::Entry'] .titre", pause=1.0)
        t.legende(x["fiche"])
        await t.pause(3.5)
        await t.defiler_vers("#avec-contenu", position="start", pause=1.5)
        t.legende(x["interactions"])
        await t.zoom(".groupes", marge=20)
        await t.pause(4.5)
        t.dezoom()
        await t.pause(0.6)

        # Routes
        await t.cliquer("[role=tab][data-onglet=routes]")
        await t.taper("#filtre-routes", "weblog")
        t.legende(x["routes"])
        await t.zoom(".liste-routes", marge=20)
        await t.pause(3.5)
        t.dezoom()
        await t.cliquer(".liste-routes .ligne[data-id^='route:/weblog/#'] .r", pause=1.2)
        t.legende(x["clic_route"])
        await t.pause(3.5)

        # Recherche dans le code, puis modification
        await t.taper("#q", "def get_absolute_url")
        t.legende(x["code"])
        await t.pause(3)
        await t.cliquer(".ligne-code[data-f^='blog/models.py']", pause=1.4)
        t.legende(x["fichier"])
        await t.pause(3)
        await t.cliquer("[data-action=modifier]", pause=1.0)
        t.legende(x["modifier"])
        await t.pause(4)
        t.sans_legende()

        await t.carton(x["avantages"][0], "", duree=8, points=x["avantages"][1])
        await t.carton(x["installer"], "github.com/caphils/carte-projet", duree=7, code=True, points=[
            "/plugin marketplace add caphils/carte-projet",
            "/plugin install carte-projet@carte-projet",
        ])


if __name__ == "__main__":
    asyncio.run(main())
