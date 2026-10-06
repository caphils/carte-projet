"""Serveur local de la carte : la page, plus la recherche dans le code et la modification des fichiers.

N'écoute que sur 127.0.0.1. Chaque appel à l'API porte le jeton intégré dans la page servie (en-tête X-Jeton) et l'hôte
doit être local : une autre page ouverte dans le navigateur ne peut ni lire ni écrire les fichiers. Seuls les fichiers
texte du projet présents dans la carte sont lisibles et modifiables ; une modification est refusée si le fichier a changé
sur le disque depuis sa lecture (empreinte).
"""
import hashlib
import json
import re
import secrets
import socket
import threading
import webbrowser
from bisect import bisect_right
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TYPES_TEXTE = {"module", "migration", "gabarit", "script", "style", "document", "config"}
MAX_RESULTATS = 400
MAX_OCTETS = 2_000_000


def empreinte(octets):
    return hashlib.sha1(octets).hexdigest()


class Etat:
    """Carte courante, recalculée après chaque enregistrement."""

    def __init__(self, racine, analyser, ecrire, page):
        self.racine, self._analyser, self._ecrire, self._page = racine, analyser, ecrire, page
        self.jeton = secrets.token_urlsafe(24)
        self.verrou = threading.Lock()
        self.recalculer()

    def recalculer(self):
        carte = self._analyser(self.racine)
        self.donnees = carte.donnees()
        self._ecrire(carte, self.donnees)
        self.fichiers = {n["id"]: n for n in self.donnees["noeuds"] if n["type"] in TYPES_TEXTE}
        symboles = {}
        for noeud in self.donnees["noeuds"]:
            if noeud.get("ligne") and noeud.get("fin") and "::" in noeud["id"]:
                symboles.setdefault(noeud["chemin"], []).append((noeud["ligne"], noeud["fin"], noeud["id"], noeud["nom"]))
        self.symboles = {chemin: sorted(liste) for chemin, liste in symboles.items()}

    def html(self):
        return self._page(self.donnees, {"jeton": self.jeton})

    def chemin_sur(self, chemin):
        """Chemin absolu d'un fichier texte de la carte, ou None (hors projet, inconnu, binaire)."""
        if chemin not in self.fichiers:
            return None
        absolu = (self.racine / chemin).resolve()
        try:
            absolu.relative_to(self.racine)
        except ValueError:
            return None
        return absolu if absolu.is_file() else None

    def symbole_de(self, chemin, ligne):
        """Fonction ou classe la plus intérieure qui contient la ligne."""
        liste = self.symboles.get(chemin, [])
        meilleur = None
        for debut, fin, id_, nom in liste[:bisect_right(liste, (ligne, float("inf")))]:
            if debut <= ligne <= fin and (meilleur is None or debut >= meilleur[0]):
                meilleur = (debut, id_, nom)
        return {"id": meilleur[1], "nom": meilleur[2]} if meilleur else None

    def chercher_code(self, requete, regex=False, casse=False):
        if not requete:
            return {"resultats": [], "tronque": False}
        try:
            motif = re.compile(requete if regex else re.escape(requete), 0 if casse else re.I)
        except re.error as erreur:
            return refus(f"Expression régulière invalide : {erreur}", f"Invalid regular expression: {erreur}")
        resultats = []
        for chemin in sorted(self.fichiers):
            if ".min." in chemin:
                continue
            absolu = self.chemin_sur(chemin)
            if not absolu or absolu.stat().st_size > MAX_OCTETS:
                continue
            try:
                texte = absolu.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for numero, ligne in enumerate(texte.splitlines(), 1):
                trouve = motif.search(ligne)
                if trouve:
                    resultats.append({"chemin": chemin, "ligne": numero, "texte": ligne[:400],
                                      "debut": trouve.start(), "fin": trouve.end(),
                                      "symbole": self.symbole_de(chemin, numero)})
                    if len(resultats) >= MAX_RESULTATS:
                        return {"resultats": resultats, "tronque": True}
        return {"resultats": resultats, "tronque": False}

    def lire(self, chemin):
        absolu = self.chemin_sur(chemin)
        if not absolu:
            return None
        octets = absolu.read_bytes()
        if len(octets) > MAX_OCTETS:
            return refus("Fichier trop volumineux pour l'éditeur.", "File too large for the editor.")
        try:
            texte = octets.decode("utf-8")
        except UnicodeDecodeError:
            return refus("Fichier non UTF-8 : modifiez-le dans votre éditeur.", "Not a UTF-8 file: edit it in your editor.")
        return {"chemin": chemin, "contenu": texte.replace("\r\n", "\n"), "empreinte": empreinte(octets),
                "crlf": "\r\n" in texte}

    def enregistrer(self, chemin, contenu, empreinte_lue):
        with self.verrou:
            absolu = self.chemin_sur(chemin)
            if not absolu:
                return 404, refus("Fichier inconnu ou hors du projet.", "Unknown file, or outside the project.")
            actuel = absolu.read_bytes()
            if empreinte(actuel) != empreinte_lue:
                return 409, refus("Le fichier a changé sur le disque depuis son ouverture. Rechargez-le avant de modifier (vos "
                             "changements sont encore dans l'éditeur : copiez-les).",
                             "The file changed on disk since it was opened. Reload it before editing (your changes "
                             "are still in the editor: copy them).")
            if b"\r\n" in actuel:
                contenu = contenu.replace("\r\n", "\n").replace("\n", "\r\n")
            octets = contenu.encode("utf-8")
            absolu.write_bytes(octets)
            try:
                self.recalculer()
                recalcul = recalcul_en = None
            except Exception as erreur:  # la carte reste l'ancienne ; l'enregistrement, lui, est fait
                recalcul, recalcul_en = f"Carte non recalculée : {erreur}", f"Map not recomputed: {erreur}"
            return 200, {"empreinte": empreinte(octets), "recalcul": recalcul, "recalcul_en": recalcul_en,
                         "genere_le": self.donnees["genere_le"]}


def refus(fr, en):
    """Message d'erreur dans les deux langues de la page (erreur : français, error : anglais)."""
    return {"erreur": fr, "error": en}


def gestionnaire(etat):
    class Gestionnaire(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def repondre(self, statut, corps, type_="application/json; charset=utf-8"):
            octets = corps if isinstance(corps, bytes) else json.dumps(corps, ensure_ascii=False).encode("utf-8")
            self.send_response(statut)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(octets)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(octets)

        def autorise(self):
            hote = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return hote in ("127.0.0.1", "localhost", "[::1]") and \
                secrets.compare_digest(self.headers.get("X-Jeton", ""), etat.jeton)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self.repondre(200, etat.html().encode("utf-8"), "text/html; charset=utf-8")
            if not url.path.startswith("/api/"):
                return self.repondre(404, refus("Introuvable", "Not found"))
            if not self.autorise():
                return self.repondre(403, refus("Accès refusé", "Access denied"))
            params = {cle: valeurs[0] for cle, valeurs in parse_qs(url.query).items()}
            if url.path == "/api/fichier":
                resultat = etat.lire(params.get("chemin", ""))
                return self.repondre(404 if resultat is None else 200, resultat or refus("Fichier inconnu.", "Unknown file."))
            if url.path == "/api/code":
                return self.repondre(200, etat.chercher_code(params.get("q", ""), params.get("regex") == "1",
                                                             params.get("casse") == "1"))
            return self.repondre(404, refus("Introuvable", "Not found"))

        def do_POST(self):
            if urlparse(self.path).path != "/api/fichier":
                return self.repondre(404, refus("Introuvable", "Not found"))
            if not self.autorise():
                return self.repondre(403, refus("Accès refusé", "Access denied"))
            try:
                longueur = int(self.headers.get("Content-Length", "0"))
                corps = json.loads(self.rfile.read(min(longueur, MAX_OCTETS * 2)).decode("utf-8"))
                statut, resultat = etat.enregistrer(corps["chemin"], corps["contenu"], corps["empreinte"])
            except (ValueError, KeyError, TypeError):
                statut, resultat = 400, refus("Requête invalide.", "Invalid request.")
            return self.repondre(statut, resultat)

    return Gestionnaire


def port_libre(prefere):
    for port in [prefere] + list(range(prefere + 1, prefere + 30)):
        with socket.socket() as essai:
            if essai.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def servir(racine, analyser, ecrire, page, port=8765, navigateur=True):
    etat = Etat(racine, analyser, ecrire, page)
    serveur = ThreadingHTTPServer(("127.0.0.1", port_libre(port)), gestionnaire(etat))
    adresse = f"http://127.0.0.1:{serveur.server_address[1]}/"
    print(f"Carte de {etat.donnees['projet']} servie sur {adresse}  (Ctrl+C pour arrêter)", flush=True)
    if navigateur:
        webbrowser.open(adresse)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
