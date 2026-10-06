"""Vidéo de présentation de la skill carte-projet, tournée sur la carte du site officiel de Django.

    python video/scenario.py        (avec l'environnement des vidéos : playwright, pillow, imageio-ffmpeg)

Chaque légende et chaque carton reçoit une réplique de voix off dans voix.py (REPLIQUES, dans le même ordre).
"""
import asyncio

from tournage import Tournage

NOM = "carte_projet"


def nombre(n):
    return f"{n:,}".replace(",", " ")


async def main():
    async with Tournage(NOM) as t:
        await t.ouvrir("/")
        await t.carton("carte-projet", "La carte reliée de votre code · skill pour Claude Code", duree=4)
        await t.carton("Vous découvrez un projet…", "", duree=6, points=[
            "Où est géré ce modèle ?",
            "Quelle vue sert cette adresse ?",
            "Qui appelle cette fonction ? Que casse-t-on en la modifiant ?",
        ])
        await t.carton("Demandez simplement à Claude", "", duree=4.5, code=True, points=[
            "« Fais la carte du projet. »",
        ])

        # Accueil : chiffres de l'analyse (lus sur la page : ils suivent le dépôt cloné)
        elements, liens = await t.page.evaluate(
            "[...document.querySelector('#meta').textContent.matchAll(/\\d+/g)].slice(0, 2).map(m => +m[0])")
        t.legende(f"Exemple : le site officiel de Django. {nombre(elements)} éléments, {nombre(liens)} liens, "
                  "analysés en moins d'une seconde.")
        await t.zoom(".tuiles", marge=30)
        await t.pause(4.5)
        t.dezoom()
        await t.pause(0.8)

        # Plan relié
        await t.defiler_vers("#zone-plan", position="start", pause=1.4)
        t.legende("Le plan relié : tout le projet, avec les liens tracés entre ses parties.")
        await t.pause(2.5)
        await t.cliquer(".pl-ligne[data-id='blog/'] .pl-etiquette .nom")
        t.legende("Un clic sur le blog : on voit aussitôt ce qu'il utilise, et qui l'utilise.")
        await t.pause(3.5)

        # Recherche → fiche d'un modèle
        await t.taper("#q", "Entry")
        t.legende("La recherche trouve modèles, vues, gabarits, routes… et les lignes de code.")
        await t.defiler_vers(".resultats", position="start", pause=1.2)
        await t.pause(2.2)
        await t.cliquer(".resultats li[data-id='blog/models.py::Entry'] .titre", pause=1.0)
        t.legende("Chaque élément a sa fiche : emplacement exact, rôle, et son code.")
        await t.pause(3.5)
        await t.defiler_vers("#avec-contenu", position="start", pause=1.5)
        t.legende("Et toutes ses interactions : la route qu'il sert, ce qu'il appelle, qui l'utilise.")
        await t.zoom(".groupes", marge=20)
        await t.pause(4.5)
        t.dezoom()
        await t.pause(0.6)

        # Routes
        await t.cliquer("[role=tab]:has-text('Routes')")
        await t.taper("#filtre-routes", "weblog")
        t.legende("L'onglet Routes : chaque adresse du site, et la vue qui la sert.")
        await t.zoom(".liste-routes", marge=20)
        await t.pause(3.5)
        t.dezoom()
        await t.cliquer(".liste-routes .ligne[data-id^='route:/weblog/#'] .r", pause=1.2)
        t.legende("Un clic sur une adresse mène à sa vue, à son gabarit, à son code.")
        await t.pause(3.5)

        # Recherche dans le code, puis modification
        await t.taper("#q", "def get_absolute_url")
        t.legende("Avec le serveur local, la recherche parcourt aussi chaque ligne de code.")
        await t.pause(3)
        await t.cliquer(".ligne-code[data-f^='blog/models.py']", pause=1.4)
        t.legende("Un clic ouvre le fichier à la bonne ligne, dans la bonne fonction.")
        await t.pause(3)
        await t.cliquer("[data-action=modifier]", pause=1.0)
        t.legende("« Modifier » : on corrige sur place, ⌘S enregistre, et la carte se met à jour.")
        await t.pause(4)
        t.sans_legende()

        await t.carton("Pourquoi carte-projet ?", "", duree=8, points=[
            "Aucune dépendance : Python seul, une seconde d'analyse.",
            "Django compris : routes, vues, modèles, formulaires, gabarits.",
            "Tout reste sur votre machine : serveur local, rien n'est envoyé.",
            "Claude s'en sert pour répondre : où est-ce, à quoi ça sert, qui l'utilise.",
        ])
        await t.carton("Installez-la dans Claude Code", "github.com/caphils/carte-projet", duree=7, code=True, points=[
            "/plugin marketplace add caphils/carte-projet",
            "/plugin install carte-projet@carte-projet",
        ])


if __name__ == "__main__":
    asyncio.run(main())
