# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
L'aggiornatore.

Due modi. Col bottone verde, quando lo preme qualcuno. E da solo, ma SOLO
all'apertura del programma (interruttore in Impostazioni, acceso di
partenza): e' il momento in cui nessuno lo sta usando e qualcuno e' davanti
allo schermo. Mai di notte, mai mentre gira: un aggiornamento andato storto
alle tre, a locale chiuso, lo scopre il primo cameriere che timbra la
mattina.

Da solo si puo' perche' c'e' il ritorno indietro: se la versione nuova non
parte entro un minuto e mezzo, il sostituto rimette quella di prima, la
segna come scartata (cosi' all'apertura dopo non ci riprova) e lo dice.

**Cosa conta come versione nuova.** Non ogni modifica pubblicata su GitHub:
solo le *etichette* (tag git) col formato di una data, `2026.10.22`, o
`2026.10.22.2` per la seconda dello stesso giorno. Il lavoro in corso sul ramo
principale non arriva al locale finche' qualcuno non decide che e' pronto e
lo etichetta:

    git tag 2026.10.22 && git push origin 2026.10.22

Il repository e' pubblico: per leggere le etichette e scaricare il pacchetto
non serve nessuna credenziale, e quindi non ce n'e' nessuna da custodire sul
computer del cliente.

**Come si sostituisce un programma che sta girando.** Non si puo' da dentro:
Windows non lascia rinominare la cartella `app` finche' il programma ci sta
lavorando dentro. Quindi si prepara la versione nuova in `dati/aggiornamento`,
si lancia un piccolo sostituto che aspetta la chiusura, sposta la vecchia in
`app.precedente` (per tornare indietro a mano, se servisse), mette la nuova al
suo posto e riapre TIMBRA. La cartella `dati` non viene mai toccata.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

REPO = "smartstaysrl-dev/Timbro_ANVIZ"
FILE_VERSIONE = "VERSIONE"
# Stanno in dati/ e non in dati/aggiornamento: quella cartella la cancella
# la versione nuova appena parte, leggendo l'esito.
PARTITA = "aggiornamento_partito"      # la versione nuova scrive: sono viva
SCARTATA = "aggiornamento_scartato"    # la versione che non partiva
SECONDI_PER_PARTIRE = 90

# Quello che serve al programma, e quindi quello che un aggiornamento porta.
# Sta qui e non in crea_pacchetto.py perche' le due liste DEVONO coincidere:
# un file aggiunto al pacchetto e dimenticato qui sparirebbe al primo
# aggiornamento, e il programma non ripartirebbe piu'.
SORGENTI = ["anviz.py", "presenze.py", "interfaccia.py", "gestione.py",
            "copie.py", "posta.py", "sicurezza.py", "guida.py", "logo.py",
            "bootstrap_dhcp.py", "aggiorna.py"]
CARTELLE = ["guida", "logo"]

_FORMATO = re.compile(r"^v?(\d+(?:\.\d+)+)$")


def numero(versione: str | None) -> tuple[int, ...]:
    """'2026.10.22' -> (2026, 10, 22). Quello che non e' una versione vale
    (0,): una copia fatta dai sorgenti senza etichetta e' sempre la piu'
    vecchia, cosi' la prima versione vera la sostituisce."""
    m = _FORMATO.match((versione or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def versione_installata(cartella_app: str) -> str:
    try:
        with open(os.path.join(cartella_app, FILE_VERSIONE),
                  encoding="utf-8") as f:
            return f.read().strip() or "sconosciuta"
    except OSError:
        return "sviluppo"


def installabile(cartella_app: str) -> bool:
    """Si aggiorna solo il pacchetto consegnato (codice in `app`, dati
    accanto). Sulla cartella dei sorgenti un aggiornamento cancellerebbe
    il lavoro in corso."""
    return os.path.basename(os.path.abspath(cartella_app)).lower() == "app"


def _leggi(url: str, timeout: float) -> bytes:
    richiesta = urllib.request.Request(url, headers={
        "User-Agent": "TIMBRA-aggiornatore",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(richiesta, timeout=timeout) as r:
        return r.read()


def ultima_disponibile(timeout: float = 10) -> str | None:
    """L'etichetta piu' recente pubblicata, o None se non ce n'e' nessuna.

    Le eccezioni di rete salgono: chi chiama decide se dirlo (bottone
    "cerca") o tacere (controllo di sottofondo, con la rete che va e viene).
    """
    dati = json.loads(_leggi(
        f"https://api.github.com/repos/{REPO}/tags?per_page=100", timeout))
    etichette = [t["name"] for t in dati if _FORMATO.match(t.get("name", ""))]
    return max(etichette, key=numero) if etichette else None


def piu_nuova(disponibile: str | None, installata: str) -> bool:
    return bool(disponibile) and numero(disponibile) > numero(installata)


def prepara(etichetta: str, cartella_dati: str, timeout: float = 60) -> str:
    """Scarica la versione e la mette pronta in dati/aggiornamento/app-<tag>.

    Ritorna il percorso della cartella pronta. Se manca un file o un
    sorgente non si compila, si ferma QUI, prima di toccare la versione che
    gira: meglio un aggiornamento rifiutato che un programma che non riparte.
    """
    lavoro = os.path.join(cartella_dati, "aggiornamento")
    if os.path.isdir(lavoro):
        shutil.rmtree(lavoro, ignore_errors=True)
    os.makedirs(lavoro, exist_ok=True)

    archivio = os.path.join(lavoro, f"{etichetta}.zip")
    contenuto = _leggi(f"https://codeload.github.com/{REPO}/zip/refs/tags/"
                       f"{etichetta}", timeout)
    with open(archivio, "wb") as f:
        f.write(contenuto)

    scompattato = os.path.join(lavoro, "scompattato")
    with zipfile.ZipFile(archivio) as z:
        z.extractall(scompattato)
    radici = os.listdir(scompattato)
    if len(radici) != 1:
        raise RuntimeError("il pacchetto scaricato non ha la forma attesa")
    sorgente = os.path.join(scompattato, radici[0])

    pronta = os.path.join(lavoro, f"app-{etichetta}")
    os.makedirs(pronta)
    for nome in SORGENTI:
        origine = os.path.join(sorgente, nome)
        if not os.path.isfile(origine):
            raise RuntimeError(f"nella versione {etichetta} manca {nome}")
        with open(origine, encoding="utf-8") as f:
            compile(f.read(), nome, "exec")    # SyntaxError = si ferma qui
        shutil.copy2(origine, pronta)
    for cartella in CARTELLE:
        origine = os.path.join(sorgente, cartella)
        if os.path.isdir(origine):
            shutil.copytree(origine, os.path.join(pronta, cartella),
                            ignore=shutil.ignore_patterns("_finto.db*"))
    with open(os.path.join(pronta, FILE_VERSIONE), "w", encoding="utf-8") as f:
        f.write(etichetta + "\n")
    shutil.rmtree(scompattato, ignore_errors=True)
    os.remove(archivio)
    return pronta


def segna_partenza(cartella_dati: str, versione: str) -> None:
    """La versione appena partita lo dice al sostituto che aspetta."""
    try:
        with open(os.path.join(cartella_dati, PARTITA), "w",
                  encoding="utf-8") as f:
            f.write(versione + "\n")
    except OSError:
        pass


def scartata(cartella_dati: str) -> str | None:
    try:
        with open(os.path.join(cartella_dati, SCARTATA),
                  encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


# Il sostituto: gira DOPO che TIMBRA si e' chiusa, con un Python a parte.
# Volutamente senza import dal programma: deve funzionare anche se la
# versione nuova o quella vecchia hanno un problema.
SOSTITUTO = r'''
import os, shutil, subprocess, sys, time
app, pronta, esito, etichetta, dati = sys.argv[1:6]
precedente = app + ".precedente"
partita = os.path.join(dati, "{PARTITA}")
attesa = {SECONDI_PER_PARTIRE}

def scrivi(testo):
    os.makedirs(os.path.dirname(esito), exist_ok=True)
    with open(esito, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + testo + "\n")

pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.exists(pythonw):
    pythonw = sys.executable

def apri():
    return subprocess.Popen([pythonw, "gestione.py"], cwd=app,
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))

def sposta(da, a):
    for _ in range(40):
        try:
            os.rename(da, a)
            return
        except OSError:
            time.sleep(0.5)
    os.rename(da, a)

# Aspetta che TIMBRA si chiuda: finche' gira, Windows non lascia spostare
# la sua cartella. Un minuto abbondante, poi si rinuncia senza danni.
spostata = False
for _ in range(120):
    try:
        if os.path.isdir(precedente):
            shutil.rmtree(precedente)
        os.rename(app, precedente)
        spostata = True
        break
    except OSError:
        time.sleep(0.5)

if not spostata:
    scrivi("NON aggiornato: la cartella del programma era ancora in uso")
    apri()
    sys.exit()
try:
    os.rename(pronta, app)
except OSError as e:
    os.rename(precedente, app)            # si rimette la versione di prima
    scrivi(f"NON aggiornato, rimessa la versione di prima: {e}")
    apri()
    sys.exit()

scrivi("aggiornato")
try:
    os.remove(partita)
except OSError:
    pass
nuova = apri()
# La versione nuova, appena in piedi, scrive il file "partita". Se non
# arriva — si e' chiusa da sola o si e' piantata — si torna indietro.
viva = False
for _ in range(attesa * 2):
    if os.path.exists(partita):
        viva = True
        break
    if nuova.poll() is not None:
        break
    time.sleep(0.5)
if not viva:
    try:
        nuova.kill()
    except OSError:
        pass
    time.sleep(1)
    guasta = app + ".guasta"
    shutil.rmtree(guasta, ignore_errors=True)
    sposta(app, guasta)
    sposta(precedente, app)
    with open(os.path.join(dati, "{SCARTATA}"), "w", encoding="utf-8") as f:
        f.write(etichetta + "\n")
    scrivi(f"NON aggiornato: la {etichetta} non partiva, rimessa la "
           f"versione di prima. La nuova e' in app.guasta.")
    apri()
'''


def avvia_sostituzione(cartella_app: str, pronta: str,
                       cartella_dati: str, etichetta: str = "") -> None:
    """Lancia il sostituto. Subito dopo, chi chiama deve chiudere TIMBRA."""
    lavoro = os.path.join(cartella_dati, "aggiornamento")
    script = os.path.join(lavoro, "sostituisci.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(SOSTITUTO.replace("{PARTITA}", PARTITA)
                .replace("{SCARTATA}", SCARTATA)
                .replace("{SECONDI_PER_PARTIRE}", str(SECONDI_PER_PARTIRE)))
    esito = os.path.join(lavoro, "esito.txt")
    eseguibile = sys.executable
    if os.path.basename(eseguibile).lower() == "pythonw.exe":
        pass                              # gia' senza finestra nera
    else:
        accanto = os.path.join(os.path.dirname(eseguibile), "pythonw.exe")
        if os.path.exists(accanto):
            eseguibile = accanto
    # cwd fuori da `app`: un processo con la cartella corrente li' dentro
    # impedirebbe di spostarla, cioe' bloccherebbe proprio se stesso.
    etichetta = etichetta or versione_installata(pronta)
    subprocess.Popen([eseguibile, script, os.path.abspath(cartella_app),
                      os.path.abspath(pronta), esito, etichetta,
                      os.path.abspath(cartella_dati)], cwd=lavoro,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def ultimo_esito(cartella_dati: str) -> str | None:
    """Com'e' andato l'ultimo aggiornamento, letto (e consumato) al riavvio."""
    percorso = os.path.join(cartella_dati, "aggiornamento", "esito.txt")
    try:
        with open(percorso, encoding="utf-8") as f:
            testo = f.read().strip()
    except OSError:
        return None
    shutil.rmtree(os.path.dirname(percorso), ignore_errors=True)
    return testo
