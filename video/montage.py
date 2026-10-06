"""Montage d'un tournage (video/build/<nom>/tournage.json) en vidéo MP4 1920 × 1080 : curseur, clics, zooms,
surlignages, légendes, cartons, barre de progression et adresse du dépôt.

    python video/montage.py carte_projet
"""
import bisect
import json
import math
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

VIDEO = Path(__file__).resolve().parent
BUILD = VIDEO / "build"
SORTIE = VIDEO / "sortie"
POLICES = VIDEO / "polices"
DEPOT = "github.com/caphils/carte-projet"
L, H, IPS = 1920, 1080, 30

# Couleurs de la page de la carte (skills/carte-projet/scripts/page.html, --accent #1f6feb)
ACCENT = (31, 111, 235)
ACCENT_CLAIR = (190, 214, 252)
NUIT = (16, 28, 52)
RUBAN = [(14, 33, 74), (19, 52, 120), (25, 82, 182), (31, 111, 235)]
BLANC = (255, 255, 255)


# --- Outils ---------------------------------------------------------------------------------------------------

def police(taille, graisse=400, mono=False):
    return _police(taille, graisse, mono)


@lru_cache(maxsize=64)
def _police(taille, graisse, mono):
    if mono:
        return ImageFont.truetype(str(POLICES / "ibm-plex-mono-600.ttf"), taille)
    p = ImageFont.truetype(str(POLICES / "ibm-plex-sans.ttf"), taille)
    p.set_variation_by_axes([graisse])
    return p


def adoucir(x):
    """Accélération puis décélération (0 → 1)."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def sortie_douce(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def melange(a, b, x):
    return a + (b - a) * x


def couper(texte, fonte, largeur):
    """Lignes de `texte` qui tiennent dans `largeur` pixels."""
    lignes, ligne = [], ""
    for mot in texte.split():
        essai = f"{ligne} {mot}".strip()
        if fonte.getlength(essai) <= largeur or not ligne:
            ligne = essai
        else:
            lignes.append(ligne)
            ligne = mot
    return lignes + ([ligne] if ligne else [])


@lru_cache(maxsize=4)
def degrade(couleurs, largeur=L, hauteur=H):
    """Dégradé diagonal (en haut à gauche → en bas à droite) entre les `couleurs`."""
    petit = Image.new("RGB", (64, 36))
    pixels = petit.load()
    n = len(couleurs) - 1
    for x in range(64):
        for y in range(36):
            u = min(max((x / 63) * 0.75 + (y / 35) * 0.25, 0), 1) * n
            i = min(int(u), n - 1)
            f = u - i
            pixels[x, y] = tuple(int(melange(couleurs[i][c], couleurs[i + 1][c], f)) for c in range(3))
    return petit.resize((largeur, hauteur), Image.BICUBIC)


@lru_cache(maxsize=1)
def logo(hauteur=84):
    """Pictogramme de la carte (trois nœuds reliés) et nom de la skill."""
    fonte = police(46, 700)
    largeur = int(hauteur * 1.1 + 24 + fonte.getlength("carte-projet"))
    image = Image.new("RGBA", (largeur, hauteur), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    h = hauteur
    noeuds = [(h * 0.2, h * 0.25), (h * 0.85, h * 0.4), (h * 0.35, h * 0.8)]
    for a, b in ((0, 1), (1, 2), (0, 2)):
        d.line((*noeuds[a], *noeuds[b]), fill=ACCENT, width=5)
    for x, y in noeuds:
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=ACCENT, outline=BLANC, width=3)
    d.text((h * 1.1 + 12, h / 2), "carte-projet", font=fonte, fill=NUIT, anchor="lm")
    return image


# --- Curseur ----------------------------------------------------------------------------------------------------

@lru_cache(maxsize=2)
def fleche(echelle=1.0):
    """Flèche de souris blanche à contour sombre, avec une ombre douce."""
    t = 34 * echelle
    points = [(0, 0), (0, t), (t * 0.28, t * 0.76), (t * 0.46, t * 1.12), (t * 0.62, t * 1.04), (t * 0.45, t * 0.69),
              (t * 0.78, t * 0.69)]
    taille = (int(t * 1.3) + 12, int(t * 1.4) + 12)
    ombre = Image.new("RGBA", taille, (0, 0, 0, 0))
    ImageDraw.Draw(ombre).polygon([(x + 5, y + 7) for x, y in points], fill=(0, 0, 0, 90))
    ombre = ombre.filter(ImageFilter.GaussianBlur(3))
    image = Image.new("RGBA", taille, (0, 0, 0, 0))
    image.alpha_composite(ombre)
    dessin = ImageDraw.Draw(image)
    dessin.polygon([(x + 3, y + 3) for x, y in points], fill=BLANC, outline=(20, 20, 30), width=max(2, int(2.2 * echelle)))
    return image


# --- Lecture du tournage ---------------------------------------------------------------------------------------------

class Tournage:
    def __init__(self, nom):
        self.dossier = BUILD / nom
        donnees = json.loads((self.dossier / "tournage.json").read_text(encoding="utf-8"))
        self.nom = nom
        self.duree = donnees["duree"]
        self.echelle = donnees["echelle"]
        self.largeur, self.hauteur = donnees["largeur"], donnees["hauteur"]
        self.images = donnees["images"]
        self.instants = [image["t"] for image in self.images]
        journal = donnees["journal"]
        self.legendes = [e for e in journal if e["type"] == "legende"]
        self.cartons = [e for e in journal if e["type"] == "carton"]
        self.curseurs = [e for e in journal if e["type"] == "curseur"]
        self.clics = [e for e in journal if e["type"] == "clic"]
        self.surlignages = [e for e in journal if e["type"] == "surlignage"]
        self._cameras(e for e in journal if e["type"] == "zoom")
        self._image = (None, None)

    # Caméra : rectangle de la page (pixels CSS) affiché à l'écran
    def _cadre(self, boite):
        if boite is None:
            return (0.0, 0.0, float(self.largeur), float(self.hauteur))
        x, y, l, h = boite
        rapport = self.largeur / self.hauteur
        l = max(l, h * rapport, self.largeur / 2.4)
        h = l / rapport
        l, h = min(l, self.largeur), min(h, self.hauteur)
        cx, cy = x + boite[2] / 2, y + boite[3] / 2
        x0 = min(max(cx - l / 2, 0), self.largeur - l)
        y0 = min(max(cy - h / 2, 0), self.hauteur - h)
        return (x0, y0, l, h)

    def _cameras(self, zooms):
        self.mouvements = []
        courant = self._cadre(None)
        for e in zooms:
            cible = self._cadre(e["boite"])
            self.mouvements.append((e["t"], e["duree"], courant, cible))
            courant = cible

    def camera(self, t):
        cadre = self._cadre(None)
        for debut, duree, de, vers in self.mouvements:
            if t < debut:
                break
            x = adoucir((t - debut) / duree)
            cadre = tuple(melange(a, b, x) for a, b in zip(de, vers))
        return cadre

    def image(self, t):
        rang = max(0, bisect.bisect_right(self.instants, t) - 1)
        if self._image[0] != rang:
            self._image = (rang, Image.open(self.dossier / "images" / self.images[rang]["fichier"]).convert("RGB"))
        return self._image[1]

    def souris(self, t):
        if not self.curseurs:
            return None
        position = self.curseurs[0]["de"]
        for e in self.curseurs:
            if t < e["t"]:
                break
            x = adoucir((t - e["t"]) / e["duree"])
            position = [melange(a, b, x) for a, b in zip(e["de"], e["vers"])]
        return position

    def dernier(self, evenements, t):
        courant = None
        for e in evenements:
            if e["t"] > t:
                break
            courant = e
        return courant


# --- Dessin d'une image -------------------------------------------------------------------------------------------------

def vers_ecran(point, camera):
    x0, y0, l, h = camera
    return ((point[0] - x0) * L / l, (point[1] - y0) * H / h)


def dessiner_surlignage(image, boite, camera, opacite):
    (x0, y0), (x1, y1) = vers_ecran(boite[:2], camera), vers_ecran((boite[0] + boite[2], boite[1] + boite[3]), camera)
    voile = Image.new("RGBA", (L, H), (15, 12, 40, int(120 * opacite)))
    masque = Image.new("L", (L, H), 255)
    ImageDraw.Draw(masque).rounded_rectangle((x0, y0, x1, y1), radius=14, fill=0)
    calque = Image.new("RGBA", (L, H), (0, 0, 0, 0))
    calque.paste(voile, (0, 0), masque)
    ImageDraw.Draw(calque).rounded_rectangle((x0, y0, x1, y1), radius=14, outline=(*ACCENT, int(255 * opacite)), width=5)
    image.alpha_composite(calque)


def dessiner_legende(image, legende, t):
    texte = legende["texte"]
    if not texte:
        return
    apparition = sortie_douce((t - legende["t"]) / 0.45)
    fonte = police(38, 500)
    etiquette = legende.get("etape", "")
    fonte_etape = police(26, 650)
    largeur_etape = fonte_etape.getlength(etiquette) + 36 if etiquette else 0
    lignes = couper(texte, fonte, 1180 - largeur_etape)
    hauteur = 46 * len(lignes) + 44
    largeur = max(fonte.getlength(ligne) for ligne in lignes) + largeur_etape + 72
    x0 = (L - largeur) / 2
    y0 = H - 70 - hauteur + (1 - apparition) * 40
    calque = Image.new("RGBA", (L, H), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(calque)
    alpha = int(255 * apparition)
    dessin.rounded_rectangle((x0 + 4, y0 + 8, x0 + largeur + 4, y0 + hauteur + 8), radius=22, fill=(0, 0, 0, int(60 * apparition)))
    calque = calque.filter(ImageFilter.GaussianBlur(8))
    dessin = ImageDraw.Draw(calque)
    dessin.rounded_rectangle((x0, y0, x0 + largeur, y0 + hauteur), radius=22, fill=(*NUIT, int(236 * apparition)))
    x = x0 + 36
    if etiquette:
        dessin.rounded_rectangle((x, y0 + 26, x + largeur_etape - 14, y0 + 68), radius=21, fill=(*ACCENT, alpha))
        dessin.text((x + 11, y0 + 47), etiquette, font=fonte_etape, fill=(*BLANC, alpha), anchor="lm")
        x += largeur_etape
    for rang, ligne in enumerate(lignes):
        dessin.text((x, y0 + 22 + 46 * rang), ligne, font=fonte, fill=(*BLANC, alpha))
    image.alpha_composite(calque)


def dessiner_mention(image):
    fonte = police(21, 500)
    texte = DEPOT
    largeur = fonte.getlength(texte) + 30
    calque = Image.new("RGBA", (L, H), (0, 0, 0, 0))
    dessin = ImageDraw.Draw(calque)
    dessin.rounded_rectangle((L - largeur - 24, H - 58, L - 24, H - 24), radius=17, fill=(255, 255, 255, 215),
                             outline=(*ACCENT_CLAIR, 255), width=2)
    dessin.text((L - largeur - 9, H - 41), texte, font=fonte, fill=(*ACCENT, 255), anchor="lm")
    image.alpha_composite(calque)


def dessiner_carton(image, carton, opacite, titre_video):
    fond = degrade(tuple(RUBAN)).convert("RGBA")
    dessin = ImageDraw.Draw(fond)
    # Cercles décoratifs discrets
    for cx, cy, r, a in ((1650, 180, 420, 18), (1780, 980, 300, 14), (140, 1010, 220, 10)):
        cercle = Image.new("RGBA", (L, H), (0, 0, 0, 0))
        ImageDraw.Draw(cercle).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, a))
        fond.alpha_composite(cercle)
    dessin = ImageDraw.Draw(fond)
    carte = Image.new("RGBA", (logo().width + 36, logo().height + 28), (255, 255, 255, 255))
    masque = Image.new("L", carte.size, 0)
    ImageDraw.Draw(masque).rounded_rectangle((0, 0, *carte.size), radius=18, fill=255)
    carte.alpha_composite(logo(), (18, 14))
    fond.paste(carte, (140, 110), masque)
    y = 250 if carton["points"] else 420
    for ligne in couper(carton["titre"], police(78, 700), 1500):
        dessin.text((140, y), ligne, font=police(78, 700), fill=BLANC)
        y += 94
    if carton["sous_titre"]:
        dessin.text((140, y + 14), carton["sous_titre"], font=police(40, 500), fill=ACCENT_CLAIR)
        y += 90
    for point in carton["points"]:
        y += 20
        if carton.get("code"):  # commande à taper : bloc sombre, police à chasse fixe
            fonte = police(36, mono=True)
            dessin.rounded_rectangle((140, y - 4, 160 + fonte.getlength(point) + 40, y + 62), radius=12,
                                     fill=(*NUIT, 255))
            dessin.text((170, y + 29), point, font=fonte, fill=BLANC, anchor="lm")
            y += 72
            continue
        dessin.ellipse((148, y + 15, 164, y + 31), fill=ACCENT_CLAIR)
        for rang, ligne in enumerate(couper(point, police(35, 450), 1500)):
            dessin.text((190, y), ligne, font=police(35, 450), fill=BLANC)
            y += 47
    dessin.text((140, H - 110), f"Skill pour Claude Code · {DEPOT}", font=police(28, 500),
                fill=(*ACCENT_CLAIR, 255))
    if titre_video and titre_video != carton["titre"]:
        dessin.text((L - 140, H - 110), titre_video, font=police(28, 500), fill=(*ACCENT_CLAIR, 255), anchor="ra")
    fond.putalpha(int(255 * opacite))
    image.alpha_composite(fond)


def composer(tournage, t, titre_video):
    camera = tournage.camera(t)
    x0, y0, l, h = camera
    e = tournage.echelle
    image = tournage.image(t).resize((L, H), Image.BICUBIC, box=(x0 * e, y0 * e, (x0 + l) * e, (y0 + h) * e)).convert("RGBA")

    surlignage = tournage.dernier(tournage.surlignages, t)
    if surlignage and surlignage["boite"]:
        dessiner_surlignage(image, surlignage["boite"], camera, sortie_douce((t - surlignage["t"]) / 0.35))
    elif surlignage:  # disparition
        rang = tournage.surlignages.index(surlignage)
        precedent = tournage.surlignages[rang - 1] if rang else None
        reste = 1 - (t - surlignage["t"]) / 0.3
        if precedent and precedent["boite"] and reste > 0:
            dessiner_surlignage(image, precedent["boite"], camera, reste)

    # Clics : onde qui s'élargit
    for clic in tournage.clics:
        age = t - clic["t"]
        if 0 <= age <= 0.55:
            cx, cy = vers_ecran(clic["position"], camera)
            r = 14 + 46 * sortie_douce(age / 0.55)
            calque = Image.new("RGBA", (L, H), (0, 0, 0, 0))
            dessin = ImageDraw.Draw(calque)
            alpha = int(170 * (1 - age / 0.55))
            dessin.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*ACCENT, alpha // 3), outline=(*ACCENT, alpha), width=4)
            image.alpha_composite(calque)

    souris = tournage.souris(t)
    if souris:
        cx, cy = vers_ecran(souris, camera)
        appui = any(0 <= t - clic["t"] <= 0.18 for clic in tournage.clics)
        fleche_ = fleche(0.88 if appui else 1.0)
        if -40 < cx < L and -40 < cy < H:
            image.alpha_composite(fleche_, (int(cx - 3), int(cy - 3)))

    dessiner_legende(image, tournage.dernier(tournage.legendes, t) or {"texte": ""}, t)
    dessiner_mention(image)

    # Barre de progression
    ImageDraw.Draw(image).rectangle((0, H - 7, int(L * t / tournage.duree), H), fill=(*ACCENT, 255))

    for carton in tournage.cartons:
        debut, fin = carton["t"], carton["t"] + carton["duree"]
        if debut - 0.01 <= t <= fin + 0.4:
            entree = 1.0 if debut < 0.8 else (t - debut) / 0.35  # carton d'ouverture : présent dès la première image
            opacite = max(0.0, min(1.0, entree, (fin + 0.4 - t) / 0.4))
            dessiner_carton(image, carton, opacite, titre_video)
    return image.convert("RGB")


def monter(nom, titre_video="", debut=0.0):
    tournage = Tournage(nom)
    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / f"{nom}.mp4"
    commande = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{L}x{H}", "-r", str(IPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(chemin)]
    encodeur = subprocess.Popen(commande, stdin=subprocess.PIPE)
    total = math.floor((tournage.duree - debut) * IPS)
    for rang in range(total):
        t = debut + rang / IPS
        encodeur.stdin.write(composer(tournage, t, titre_video).tobytes())
        if rang % (IPS * 10) == 0:
            print(f"  {nom} : {t:.0f} s / {tournage.duree:.0f} s", flush=True)
    encodeur.stdin.close()
    encodeur.wait()
    print(f"Vidéo écrite : {chemin} ({chemin.stat().st_size / 1e6:.1f} Mo, {total / IPS:.0f} s)")
    return chemin


if __name__ == "__main__":
    monter(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
