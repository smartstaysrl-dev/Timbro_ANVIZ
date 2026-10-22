# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""Prove dell'aggiornatore, senza rete: GitHub e' sostituito da un finto.

L'ultima prova fa la sostituzione vera, su una cartella di prova: un
programma che "gira" dentro app, il sostituto che aspetta che si chiuda,
scambia le cartelle e riapre la versione nuova.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

import aggiorna

esiti = []


def prova(nome):
    def decoratore(f):
        try:
            f()
            esiti.append((nome, None))
        except Exception as e:                       # noqa: BLE001
            esiti.append((nome, f"{type(e).__name__}: {e}"))
        return f
    return decoratore


def finto_zip(etichetta, togli=None, rotto=None):
    """Lo zip che darebbe GitHub per quell'etichetta."""
    buf = io.BytesIO()
    radice = f"Timbro_ANVIZ-{etichetta}/"
    with zipfile.ZipFile(buf, "w") as z:
        for nome in aggiorna.SORGENTI:
            if nome == togli:
                continue
            testo = "x = (\n" if nome == rotto else f"# {nome} {etichetta}\n"
            z.writestr(radice + nome, testo)
        z.writestr(radice + "guida/oggi.png", b"png")
        z.writestr(radice + "logo/timbra.ico", b"ico")
        z.writestr(radice + "test_presenze.py", "# resta fuori\n")
        z.writestr(radice + "guida/_finto.db", b"no")
    return buf.getvalue()


def con_github(etichette, zip_per=None):
    def leggi(url, timeout):
        if url.startswith("https://api.github.com/"):
            return json.dumps([{"name": e} for e in etichette]).encode()
        return zip_per(url.rsplit("/", 1)[1])
    aggiorna._leggi = leggi


@prova("le versioni si confrontano come numeri, non come testo")
def _():
    assert aggiorna.numero("2026.10.22") == (2026, 10, 22)
    assert aggiorna.numero("v2026.10.22.2") == (2026, 10, 22, 2)
    assert aggiorna.numero("sviluppo") == (0,)
    assert aggiorna.piu_nuova("2026.11.2", "2026.10.30")    # "11.2" > "10.30"
    assert aggiorna.piu_nuova("2026.10.22.2", "2026.10.22")
    assert not aggiorna.piu_nuova("2026.10.22", "2026.10.22")
    assert not aggiorna.piu_nuova(None, "sviluppo")
    assert aggiorna.piu_nuova("2026.10.22", "sviluppo")


@prova("l'ultima disponibile ignora le etichette che non sono versioni")
def _():
    con_github(["prova", "2026.9.30", "2026.10.22", "2026.10.3", "v-rotta"])
    assert aggiorna.ultima_disponibile() == "2026.10.22"
    con_github(["prova"])
    assert aggiorna.ultima_disponibile() is None


@prova("prepara: porta solo i file del programma, e scrive la versione")
def _():
    con_github([], lambda e: finto_zip(e))
    dati = tempfile.mkdtemp()
    pronta = aggiorna.prepara("2026.10.22", dati)
    nomi = set(os.listdir(pronta))
    assert set(aggiorna.SORGENTI) <= nomi, nomi
    assert "test_presenze.py" not in nomi, "le prove non vanno in sede"
    assert os.path.exists(os.path.join(pronta, "guida", "oggi.png"))
    assert not os.path.exists(os.path.join(pronta, "guida", "_finto.db"))
    assert aggiorna.versione_installata(pronta) == "2026.10.22"


@prova("prepara: si ferma se manca un file o un sorgente non si compila")
def _():
    for guasto in ({"togli": "gestione.py"}, {"rotto": "presenze.py"}):
        con_github([], lambda e: finto_zip(e, **guasto))
        try:
            aggiorna.prepara("2026.10.22", tempfile.mkdtemp())
        except (RuntimeError, SyntaxError):
            continue
        raise AssertionError(f"accettata una versione guasta: {guasto}")


@prova("si aggiorna solo il pacchetto, mai la cartella dei sorgenti")
def _():
    assert aggiorna.installabile(r"C:\TIMBRA\app")
    assert not aggiorna.installabile(os.path.dirname(aggiorna.__file__))


@prova("sostituzione vera: aspetta la chiusura, scambia, riapre")
def _():
    radice = tempfile.mkdtemp()
    app = os.path.join(radice, "app")
    dati = os.path.join(radice, "dati")
    os.makedirs(app)
    os.makedirs(dati)
    with open(os.path.join(dati, "timbrature.db"), "w") as f:
        f.write("archivio")
    with open(os.path.join(app, "VERSIONE"), "w") as f:
        f.write("2026.10.1\n")
    # Il programma "vecchio": resta aperto con la cartella corrente in app,
    # come TIMBRA vera, finche' non lo si chiude.
    vecchio = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(4)"], cwd=app)
    # La versione nuova: il suo gestione.py lascia un segno quando parte.
    con_github([], lambda e: finto_zip(e))
    pronta = aggiorna.prepara("2026.10.22", dati)
    with open(os.path.join(pronta, "gestione.py"), "w") as f:
        f.write("import os\nopen(os.path.join('..', 'dati', 'ripartita'),"
                " 'w').write(open('VERSIONE').read())\n")
    aggiorna.avvia_sostituzione(app, pronta, dati)

    vecchio.wait()
    segno = os.path.join(dati, "ripartita")
    for _ in range(60):
        if os.path.exists(segno):
            break
        time.sleep(0.5)
    time.sleep(0.5)
    assert os.path.exists(segno), "la versione nuova non e' ripartita"
    assert open(segno).read().strip() == "2026.10.22"
    assert aggiorna.versione_installata(app) == "2026.10.22"
    assert aggiorna.versione_installata(app + ".precedente") == "2026.10.1"
    assert open(os.path.join(dati, "timbrature.db")).read() == "archivio"
    esito = aggiorna.ultimo_esito(dati)
    assert esito and esito.endswith(" aggiornato"), esito
    assert aggiorna.ultimo_esito(dati) is None, "l'esito si legge una volta"


# --------------------------------------------------------------------------
falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
