"""Tournage : Chrome piloté sur la carte servie par la skill, écran enregistré image par image (Page.startScreencast).

Le scénario agit comme un utilisateur (aller, viser, cliquer, taper, défiler) et note dans un journal ce que le montage
ajoute ensuite : curseur, clics, légendes, zooms, surlignages, cartons. Le projet cartographié est cloné dans
video/build/ (DEPOT_DEMO), puis servi par `analyser.py --serveur`.
"""
import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

VIDEO = Path(__file__).resolve().parent
BUILD = VIDEO / "build"
ANALYSEUR = VIDEO.parent / "skills" / "carte-projet" / "scripts" / "analyser.py"
DEPOT_DEMO = "https://github.com/django/djangoproject.com.git"
PROJET = BUILD / "djangoproject.com"
PORT = 8790
LARGEUR, HAUTEUR = 1600, 900  # fenêtre en pixels CSS (16:9)
ECHELLE = 2  # images de 3200 × 1800 : les zooms restent nets


def _port_ouvert(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class Serveur:
    """Serveur de la carte (analyser.py --serveur) sur le projet de démonstration, le temps du tournage."""

    def __enter__(self):
        if not PROJET.exists():
            BUILD.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "-q", "--depth", "1", DEPOT_DEMO, str(PROJET)], check=True)
        if _port_ouvert(PORT):
            raise RuntimeError(f"Le port {PORT} est déjà occupé.")
        self.processus = subprocess.Popen(
            [sys.executable, str(ANALYSEUR), str(PROJET), "--serveur", "--sans-navigateur", "--port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if _port_ouvert(PORT):
                return self
            time.sleep(0.1)
        raise RuntimeError("Le serveur de la carte ne répond pas.")

    def __exit__(self, *exc):
        self.processus.terminate()
        self.processus.wait(10)


class Tournage:
    def __init__(self, nom):
        self.nom = nom
        self.dossier = BUILD / nom
        self.images = []  # [(instant, octets jpeg)]
        self.journal = []
        self.souris = (LARGEUR * 0.62, HAUTEUR * 0.55)

    # --- Déroulement --------------------------------------------------------------------------------------

    async def __aenter__(self):
        if self.dossier.exists():
            shutil.rmtree(self.dossier)
        (self.dossier / "images").mkdir(parents=True)
        self._serveur = Serveur().__enter__()
        self._pw = await async_playwright().start()
        self._navigateur = await self._pw.chromium.launch(
            channel="chrome", headless=True, args=[f"--force-device-scale-factor={ECHELLE}"])
        self._contexte = await self._navigateur.new_context(
            viewport={"width": LARGEUR, "height": HAUTEUR}, device_scale_factor=ECHELLE, locale="fr-FR",
            color_scheme="light")
        self.page = await self._contexte.new_page()
        self.page.set_default_timeout(15000)
        return self

    async def __aexit__(self, *exc):
        try:
            if exc[0] is None:
                await self._arreter_enregistrement()
                self._ecrire()
            else:
                await self.page.screenshot(path=str(self.dossier / "erreur.png"))
                print(f"Échec : copie d'écran dans {self.dossier / 'erreur.png'} ({self.page.url})")
        finally:
            await self._navigateur.close()
            await self._pw.stop()
            self._serveur.__exit__()

    async def ouvrir(self, chemin="/"):
        """Ouvre la carte hors enregistrement, puis démarre l'enregistrement."""
        await self.page.goto(self.url(chemin))
        await self.page.wait_for_load_state("networkidle")
        await self._demarrer_enregistrement()

    def url(self, chemin):
        return f"http://127.0.0.1:{PORT}{chemin}"

    async def _demarrer_enregistrement(self):
        self._cdp = await self._contexte.new_cdp_session(self.page)

        def image(parametres):
            self.images.append((parametres["metadata"]["timestamp"], base64.b64decode(parametres["data"])))
            asyncio.ensure_future(accuser(parametres["sessionId"]))

        async def accuser(session):
            try:
                await self._cdp.send("Page.screencastFrameAck", {"sessionId": session})
            except Exception:  # page fermée entre-temps
                pass

        self._cdp.on("Page.screencastFrame", image)
        await self._cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": 92, "maxWidth": LARGEUR * ECHELLE, "maxHeight": HAUTEUR * ECHELLE,
            "everyNthFrame": 1,
        })
        self.debut = time.time()
        await self.page.evaluate("document.body.style.outline = '0px solid transparent'")
        await asyncio.sleep(0.3)

    async def _arreter_enregistrement(self):
        await asyncio.sleep(0.5)
        self.fin = time.time()
        await self._cdp.send("Page.stopScreencast")

    def _ecrire(self):
        images = []
        for rang, (instant, octets) in enumerate(self.images):
            nom = f"{rang:06d}.jpg"
            (self.dossier / "images" / nom).write_bytes(octets)
            images.append({"t": round(instant - self.debut, 3), "fichier": nom})
        donnees = {"nom": self.nom, "duree": round(self.fin - self.debut, 3), "echelle": ECHELLE,
                   "largeur": LARGEUR, "hauteur": HAUTEUR, "images": images, "journal": self.journal}
        (self.dossier / "tournage.json").write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{self.nom} : {len(images)} images, {donnees['duree']:.1f} s")

    # --- Journal pour le montage ------------------------------------------------------------------------

    def _noter(self, type_, **champs):
        self.journal.append({"t": round(time.time() - self.debut, 3), "type": type_, **champs})

    def legende(self, texte, etape=""):
        """Légende en bas de l'écran, jusqu'à la suivante ou `sans_legende()`."""
        self._noter("legende", texte=texte, etape=etape)

    def sans_legende(self):
        self._noter("legende", texte="")

    async def carton(self, titre, sous_titre="", duree=3.5, points=(), code=False):
        """Carton plein écran (titre, sous-titre, liste de points ; `code` : points en police à chasse fixe)."""
        self._noter("carton", titre=titre, sous_titre=sous_titre, duree=duree, points=list(points), code=code)
        await asyncio.sleep(duree)

    async def _boite(self, cible):
        localisation = self.page.locator(cible) if isinstance(cible, str) else cible
        boite = await localisation.first.bounding_box()
        if boite is None:
            raise RuntimeError(f"Élément invisible : {cible}")
        return boite

    async def zoom(self, cible, marge=40, duree=0.9):
        """Rapproche la caméra de l'élément (sélecteur ou boîte {x, y, width, height} en pixels CSS)."""
        boite = cible if isinstance(cible, dict) else await self._boite(cible)
        self._noter("zoom", boite=[boite["x"] - marge, boite["y"] - marge, boite["width"] + 2 * marge,
                                   boite["height"] + 2 * marge], duree=duree)

    def dezoom(self, duree=0.9):
        self._noter("zoom", boite=None, duree=duree)

    async def surligner(self, cible, marge=8):
        """Assombrit l'écran autour de l'élément, jusqu'à `sans_surlignage()`."""
        boite = await self._boite(cible)
        self._noter("surlignage", boite=[boite["x"] - marge, boite["y"] - marge, boite["width"] + 2 * marge,
                                         boite["height"] + 2 * marge])

    def sans_surlignage(self):
        self._noter("surlignage", boite=None)

    # --- Actions ------------------------------------------------------------------------------------------

    async def pause(self, secondes):
        await asyncio.sleep(secondes)

    async def viser(self, cible, duree=0.9):
        """Déplace le curseur jusqu'au centre de l'élément, après l'avoir fait défiler à l'écran s'il n'y est pas."""
        boite = await self._boite(cible)
        if boite["y"] < 60 or boite["y"] + boite["height"] > HAUTEUR - 20:
            await self.defiler_vers(cible)
            boite = await self._boite(cible)
        x, y = boite["x"] + min(boite["width"] / 2, 120), boite["y"] + boite["height"] / 2
        await self.viser_point(x, y, duree)

    async def viser_point(self, x, y, duree=0.9):
        self._noter("curseur", de=list(self.souris), vers=[x, y], duree=duree)
        await self.page.mouse.move(x, y, steps=max(2, int(duree * 20)))
        self.souris = (x, y)
        await asyncio.sleep(duree)

    async def cliquer(self, cible, duree=0.9, pause=0.6):
        await self.viser(cible, duree)
        self._noter("clic", position=list(self.souris))
        await asyncio.sleep(0.15)
        await self.page.mouse.down()
        await self.page.mouse.up()
        await asyncio.sleep(pause)

    async def taper(self, cible, texte, delai=0.11):
        """Clique dans le champ, efface, puis tape le texte lettre par lettre."""
        await self.cliquer(cible, pause=0.2)
        await self.page.keyboard.press("Meta+A")
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)
        await self.page.keyboard.type(texte, delay=delai * 1000)
        await asyncio.sleep(0.8)

    async def defiler_vers(self, cible, position="center", pause=1.1):
        """Défilement doux jusqu'à l'élément."""
        localisation = self.page.locator(cible) if isinstance(cible, str) else cible
        await localisation.first.evaluate(f"e => e.scrollIntoView({{behavior: 'smooth', block: '{position}'}})")
        await asyncio.sleep(pause)

    async def defiler(self, pixels, pause=1.0, dans="window"):
        await self.page.evaluate(f"{dans}.scrollBy({{top: {pixels}, behavior: 'smooth'}})")
        await asyncio.sleep(pause)
