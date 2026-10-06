"""Voix off de la vidéo et montage resserré sur la voix (repris du studio vidéo de LabManager).

Voix : par défaut la voix clonée de l'échantillon ECHANTILLON (cloner.py, calculée sur cette machine, dans
l'environnement PYTHON_CLONE) ; VOIX=<nom edge-tts> pour une voix neuronale Microsoft (seul le texte part en ligne).
Chaque réplique de REPLIQUES ouvre un segment de la vidéo, ramené à la durée de la réplique plus une courte pause.

    python video/sonoriser.py

Écrit video/sortie/carte_projet_voix.mp4 et ses sous-titres carte_projet_voix.srt ; répliques en cache dans
video/build/voix/.
"""
import array
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg

DOSSIER = Path(__file__).resolve().parent
BUILD = DOSSIER / "build"
CACHE = BUILD / "voix"
SORTIE = DOSSIER / "sortie"
LABMANAGER = Path(os.environ.get("LABMANAGER", Path.home() / "Documents" / "App_LabManager"))
PYTHON_CLONE = Path(os.environ.get("PYTHON_CLONE", LABMANAGER / ".venv-clone" / "bin" / "python"))
ECHANTILLONS = [Path(os.environ["ECHANTILLON"])] if "ECHANTILLON" in os.environ else sorted(
    (LABMANAGER / "videos" / "voix").glob("ma voix.*"))
NOM, TITRE = "carte_projet", "carte-projet : la carte reliée de votre code"
AVANCE = 0.2  # la voix démarre un peu après l'apparition de la légende

# Une réplique par carton et par légende, dans l'ordre du tournage (scenario.py)
REPLIQUES = [
    "carte-projet : la carte reliée de votre code, une skill pour Claude Code.",
    "Vous découvrez un projet. Où est géré ce modèle ? Quelle vue sert cette adresse ? Qui appelle cette fonction ?",
    "Il suffit de demander à Claude : fais la carte du projet.",
    "Exemple : le site officiel de Django. Plus de deux mille cinq cents éléments, analysés en moins d'une seconde.",
    "Le plan relié montre tout le projet, avec les liens entre ses parties.",
    "Un clic sur le blog : on voit aussitôt ce qu'il utilise, et qui l'utilise.",
    "La recherche trouve les modèles, les vues, les gabarits, les routes, et les lignes de code.",
    "Chaque élément a sa fiche : son emplacement exact, son rôle, et son code.",
    "Et toutes ses interactions : la route qu'il sert, ce qu'il appelle, qui l'utilise.",
    "L'onglet Routes liste chaque adresse du site, et la vue qui la sert.",
    "Un clic sur une adresse mène à sa vue, à ses gabarits, à son code.",
    "Avec le serveur local, la recherche parcourt aussi chaque ligne de code.",
    "Un clic ouvre le fichier à la bonne ligne, dans la bonne fonction.",
    "On peut même corriger sur place : Commande S enregistre, et la carte se met à jour.",
    "Aucune dépendance, Django bien compris, tout reste sur votre machine. Et Claude s'en sert pour vous répondre.",
    "Installez-la dans Claude Code en deux commandes. Le lien est sur GitHub : caphils, carte-projet.",
]


def horodatage(secondes, srt=False):
    minutes, reste = divmod(secondes, 60)
    if srt:
        heures, minutes = divmod(int(minutes), 60)
        return f"{heures:02d}:{minutes:02d}:{int(reste):02d},{round((reste % 1) * 1000):03d}".replace(",1000", ",999")
    return f"{int(minutes):02d}:{reste:04.1f}"


def videos():
    """[(nom, titre, durée, [(début, texte)])] : les répliques calées sur les cartons et légendes du tournage."""
    donnees = json.loads((BUILD / NOM / "tournage.json").read_text(encoding="utf-8"))
    reperes = [e for e in donnees["journal"] if (e["type"] == "legende" and e["texte"]) or e["type"] == "carton"]
    if len(reperes) != len(REPLIQUES):
        raise SystemExit(f"{len(reperes)} légendes et cartons au tournage, {len(REPLIQUES)} répliques : les accorder.")
    return [(NOM, TITRE, donnees["duree"], [(e["t"] + AVANCE, texte) for e, texte in zip(reperes, REPLIQUES)])]
VOIX = os.environ.get("VOIX", "clone" if ECHANTILLONS else "fr-FR-VivienneMultilingualNeural")
REFERENCE = (9.8, 9.6)  # passage de l'échantillon imité : début et durée en secondes (une phrase entière, nette)
TEMPO = 1.08 if VOIX == "clone" else 1.0  # la voix clonée, un peu posée, est légèrement accélérée
FREQUENCE = 24000
IPS = 30
PAUSE = 0.4  # silence entre deux répliques
FIN = 1.5  # dernière image tenue après la dernière réplique
VITESSE_MAX = 2.5
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# Prononciation : le texte affiché reste inchangé, seule la voix lit ces variantes.
PRONONCIATION = {
    "carte-projet": "carte projet",
    "Django": "Djan-go",
    "caphils": "cap-hils",
}


def a_dire(texte):
    for ecrit, dit in PRONONCIATION.items():
        texte = texte.replace(ecrit, dit)
    return texte.replace("« ", "").replace(" »", "")


def ffmpeg(*arguments):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *map(str, arguments)], check=True)


def en_pcm(source, brut):
    """Silences de début et de fin retirés, tempo appliqué, 16 bits mono."""
    ffmpeg("-i", source, "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
           f"silenceremove=start_periods=1:start_threshold=-50dB,areverse,atempo={TEMPO}",
           "-f", "s16le", "-ac", "1", "-ar", FREQUENCE, brut)


def reference():
    """Passage de l'échantillon imité par la voix clonée, et son empreinte (un nouvel échantillon refait tout)."""
    echantillon = ECHANTILLONS[0]
    empreinte = hashlib.sha1(echantillon.read_bytes() + repr(REFERENCE).encode()).hexdigest()[:10]
    chemin = CACHE / f"reference_{empreinte}.wav"
    if not chemin.exists():
        ffmpeg("-i", echantillon, "-ss", REFERENCE[0], "-t", REFERENCE[1], "-ac", "1", "-ar", FREQUENCE, chemin)
    return chemin, empreinte


async def edge(texte, mp3):
    import edge_tts
    for essai in range(4):
        try:
            await edge_tts.Communicate(texte, VOIX).save(str(mp3))
            return
        except Exception:
            if essai == 3:
                raise
            await asyncio.sleep(3)


async def synthetiser(textes):
    """{texte: échantillons 16 bits mono} ; cache par voix, échantillon, tempo et texte."""
    CACHE.mkdir(parents=True, exist_ok=True)
    ref, empreinte = reference() if VOIX == "clone" else (None, "")
    fichiers = {}
    for texte in textes:
        cle = hashlib.sha1(f"{VOIX}|{empreinte}|{a_dire(texte)}".encode()).hexdigest()[:16]
        fichiers[texte] = CACHE / f"{cle}.{'wav' if VOIX == 'clone' else 'mp3'}"
    if VOIX == "clone":
        commandes = CACHE / "commandes.json"
        commandes.write_text(json.dumps([{"texte": a_dire(t), "chemin": str(f)} for t, f in fichiers.items()],
                                        ensure_ascii=False), encoding="utf-8")
        subprocess.run([PYTHON_CLONE, DOSSIER / "cloner.py", ref, commandes], check=True)
    else:
        for texte, mp3 in fichiers.items():
            if not mp3.exists():
                await edge(a_dire(texte), mp3)
    sons = {}
    for texte, source in fichiers.items():
        brut = source.with_name(f"{source.stem}_{TEMPO}.pcm")
        if not brut.exists():
            en_pcm(source, brut)
        sons[texte] = array.array("h")
        sons[texte].frombytes(brut.read_bytes())
    return sons


def plan(duree, repliques, sons):
    """[(début source, durée source, durée montée, texte)] : l'ouverture, puis un segment par réplique."""
    debuts = [round(debut * IPS) / IPS for debut, _ in repliques] + [duree]
    segments = [(0.0, debuts[0], debuts[0], None)]
    for rang, (_, texte) in enumerate(repliques):
        source = debuts[rang + 1] - debuts[rang]
        voulu = len(sons[texte]) / FREQUENCE + (FIN if rang == len(repliques) - 1 else PAUSE)
        segments.append((debuts[rang], source, max(voulu, source / VITESSE_MAX), texte))
    return segments


def instant_source(segments, t):
    """Instant de la vidéo muette montré à l'instant t de la vidéo resserrée."""
    for debut, source, monte, _ in segments:
        if t < monte:
            return debut + (t * source / monte if monte <= source else min(t, source))
        t -= monte
    return segments[-1][0] + segments[-1][1]


def sonoriser(nom, titre, duree, repliques, sons):
    segments = plan(duree, repliques, sons)
    total = sum(s[2] for s in segments)
    piste = array.array("h", bytes(2 * int(total * FREQUENCE + FREQUENCE)))
    srt, depart = [], 0.0
    for debut, source, monte, texte in segments:
        if texte:
            son = sons[texte]
            position = int(depart * FREQUENCE)
            piste[position:position + len(son)] = son
            fin = depart + len(son) / FREQUENCE
            srt += [str(len(srt) // 4 + 1), f"{horodatage(depart, True)} --> {horodatage(fin, True)}", texte, ""]
            print(f"  {horodatage(debut)} → {horodatage(depart)}  {source:4.1f} s → {monte:4.1f} s"
                  + (f"  (×{source / monte:.1f})" if monte < source - 0.05 else "")
                  + ("  (image tenue)" if monte > source + 0.05 else ""))
        depart += monte
    chemin_wav = CACHE / f"{nom}.wav"
    with wave.open(str(chemin_wav), "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(FREQUENCE)
        sortie.writeframes(piste[:int(total * FREQUENCE)].tobytes())

    # Images : pour chaque image de la vidéo resserrée, la dernière image muette à l'instant correspondant
    lecture = imageio_ffmpeg.read_frames(str(SORTIE / f"{nom}.mp4"))
    meta = next(lecture)
    largeur, hauteur = meta["size"]
    resultat = SORTIE / f"{nom}_voix.mp4"
    encodage = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{largeur}x{hauteur}",
         "-r", str(IPS), "-i", "-", "-i", str(chemin_wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
         "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-shortest", "-movflags", "+faststart", str(resultat)],
        stdin=subprocess.PIPE)
    rang_lu, image = -1, None
    for n in range(int(total * IPS)):
        voulu = min(int(instant_source(segments, n / IPS) * IPS + 1e-6), int(duree * IPS) - 1)
        while rang_lu < voulu:
            try:
                image = next(lecture)
            except StopIteration:
                break
            rang_lu += 1
        encodage.stdin.write(image)
    encodage.stdin.close()
    if encodage.wait():
        raise SystemExit(f"{nom} : échec de l'encodage")
    (SORTIE / f"{nom}_voix.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"Vidéo écrite : {resultat} ({resultat.stat().st_size / 1e6:.1f} Mo, {horodatage(duree)} → "
          f"{horodatage(total)})")


async def main(noms):
    choisies = [v for v in videos() if not noms or v[0] in noms]
    print(f"Voix : {VOIX}" + (f" (échantillon {ECHANTILLONS[0].name})" if VOIX == "clone" else ""))
    sons = await synthetiser([texte for *_, repliques in choisies for _, texte in repliques])
    for nom, titre, duree, repliques in choisies:
        print(nom)
        sonoriser(nom, titre, duree, repliques, sons)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
