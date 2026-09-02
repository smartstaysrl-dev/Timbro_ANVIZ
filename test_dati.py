# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""Collaudo del trasloco dei dati fuori dalla cartella del codice.

È il pezzo che rende possibile aggiornare il programma senza perdere niente:
il codice sta in una cartella sostituibile, l'archivio delle timbrature in
un'altra che non si tocca mai. Qui si verifica che il trasloco porti via
tutto, che non sovrascriva niente, e soprattutto che la configurazione smetta
di indicare il vecchio posto — è il difetto trovato provandolo su
un'installazione vera: i file erano di là, ma il programma continuava a
cercarli di qua e si creava un archivio nuovo, vuoto.
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gestione

esiti = []


def prova(nome):
    def decoratore(f):
        try:
            f()
            esiti.append((nome, None))
        except AssertionError as e:
            esiti.append((nome, str(e) or "asserzione fallita"))
        except Exception as e:                                   # noqa: BLE001
            esiti.append((nome, f"{type(e).__name__}: {e}"))
        return f
    return decoratore


class Finzione:
    """Sposta per un attimo le due cartelle del modulo su una copia finta."""

    def __init__(self, codice, dati):
        self.codice, self.dati = codice, dati

    def __enter__(self):
        self.veri = (gestione.CARTELLA, gestione.CARTELLA_DATI)
        gestione.CARTELLA = self.codice
        gestione.CARTELLA_DATI = self.dati
        return self

    def __exit__(self, *a):
        gestione.CARTELLA, gestione.CARTELLA_DATI = self.veri


def installazione_vecchia(quanti_file=True):
    """Come sta su disco un'installazione fatta prima della separazione."""
    radice = tempfile.mkdtemp()
    codice = os.path.join(radice, "app")
    os.makedirs(codice)
    if quanti_file:
        for nome in ("timbrature.db", "timbrature.db-wal", "timbrature.db-shm",
                     "configurazione.json", "regole.json"):
            with open(os.path.join(codice, nome), "w", encoding="ascii") as f:
                f.write(nome)
        os.makedirs(os.path.join(codice, "copie"))
        with open(os.path.join(codice, "copie", "timbrature-2026-08-01.db"),
                  "w", encoding="ascii") as f:
            f.write("copia")
    return radice, codice, os.path.join(radice, "dati")


@prova("il trasloco porta via archivio, configurazione e copie")
def _():
    radice, codice, dati = installazione_vecchia()
    with Finzione(codice, dati):
        traslocati = gestione.prepara_cartella_dati()
    assert "timbrature.db" in traslocati, traslocati
    assert "copie" in traslocati, traslocati
    for nome in ("timbrature.db", "timbrature.db-wal", "timbrature.db-shm",
                 "configurazione.json", "regole.json"):
        assert os.path.exists(os.path.join(dati, nome)), f"non arrivato: {nome}"
        assert not os.path.exists(os.path.join(codice, nome)), \
            f"rimasto col codice: {nome}"
    assert os.path.isdir(os.path.join(dati, "copie"))
    shutil.rmtree(radice, ignore_errors=True)


@prova("i file di appoggio del database viaggiano con lui")
def _():
    # I -wal e -shm contengono le ultime scritture non ancora consolidate.
    # Lasciandoli indietro si perdono le timbrature dell'ultimo scarico, e il
    # database che arriva di la' e' piu' vecchio di quello che si e' lasciato.
    radice, codice, dati = installazione_vecchia()
    with Finzione(codice, dati):
        traslocati = gestione.prepara_cartella_dati()
    assert "timbrature.db-wal" in traslocati and "timbrature.db-shm" in traslocati, \
        traslocati
    shutil.rmtree(radice, ignore_errors=True)


@prova("il trasloco non sovrascrive quello che c'e' gia' di la'")
def _():
    radice, codice, dati = installazione_vecchia()
    os.makedirs(dati)
    buono = os.path.join(dati, "timbrature.db")
    with open(buono, "w", encoding="ascii") as f:
        f.write("QUESTO E' L'ARCHIVIO BUONO")
    with Finzione(codice, dati):
        gestione.prepara_cartella_dati()
    assert open(buono, encoding="ascii").read() == "QUESTO E' L'ARCHIVIO BUONO", \
        "il trasloco ha schiacciato un archivio gia' presente"
    shutil.rmtree(radice, ignore_errors=True)


@prova("secondo avvio: non c'e' piu' niente da traslocare")
def _():
    radice, codice, dati = installazione_vecchia()
    with Finzione(codice, dati):
        primo = gestione.prepara_cartella_dati()
        secondo = gestione.prepara_cartella_dati()
    assert primo and not secondo, (primo, secondo)
    shutil.rmtree(radice, ignore_errors=True)


@prova("la configurazione smette di indicare il vecchio posto")
def _():
    # Il difetto vero: i file traslocati, ma dentro configurazione.json
    # l'archivio ha ancora il percorso assoluto di prima. Il programma ci va,
    # non lo trova, e se ne fabbrica uno nuovo vuoto accanto al codice.
    radice, codice, dati = installazione_vecchia()
    cfg = {"archivio": os.path.join(codice, "timbrature.db")}
    with Finzione(codice, dati):
        gestione.prepara_cartella_dati()
        cambiato = gestione.raddrizza_percorsi(cfg)
    assert cambiato, "il percorso non e' stato corretto"
    assert cfg["archivio"] == os.path.join(dati, "timbrature.db"), cfg["archivio"]
    shutil.rmtree(radice, ignore_errors=True)


@prova("un archivio messo apposta altrove non si tocca")
def _():
    # Chi lo ha spostato su un disco di rete lo ha fatto di proposito.
    radice, codice, dati = installazione_vecchia(quanti_file=False)
    altrove = os.path.join(tempfile.mkdtemp(), "presenze.db")
    cfg = {"archivio": altrove}
    with Finzione(codice, dati):
        cambiato = gestione.raddrizza_percorsi(cfg)
    assert not cambiato and cfg["archivio"] == altrove, cfg["archivio"]
    shutil.rmtree(radice, ignore_errors=True)


@prova("senza separazione (sorgenti) non si trasloca e non si raddrizza nulla")
def _():
    radice, codice, _ = installazione_vecchia()
    cfg = {"archivio": os.path.join(codice, "timbrature.db")}
    with Finzione(codice, codice):          # dati e codice nello stesso posto
        assert gestione.prepara_cartella_dati() == []
        assert not gestione.raddrizza_percorsi(cfg)
    assert cfg["archivio"] == os.path.join(codice, "timbrature.db")
    shutil.rmtree(radice, ignore_errors=True)


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
