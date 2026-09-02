"""Collaudo delle copie di sicurezza: la copia deve essere consistente anche
se qualcuno sta scrivendo, deve essere verificata, e la rotazione non deve
buttare via quello che serve."""
import datetime as dt
import os
import pathlib
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import anviz
import copie
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


def archivio_con(n_timbrature: int) -> str:
    percorso = str(pathlib.Path(tempfile.mkdtemp()) / "timbrature.db")
    db = gestione.apri_archivio(percorso)
    for i in range(n_timbrature):
        q = dt.datetime(2026, 9, 1, 8, 0) + dt.timedelta(minutes=i)
        db.execute(
            "INSERT INTO raw_events (source_event_id, device_serial, "
            "employee_code, occurred_at_local, occurred_at_utc, device_seconds, "
            "event_type_raw, event_type, metodo, work_code, raw_payload, "
            "imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"e{i}", "SN", 1, q.isoformat(sep=" "), q.isoformat(sep=" "),
             i, 0, 0, "badge", 0, "00", "x"))
    db.commit()
    db.close()
    return percorso


@prova("la copia contiene tutte le timbrature ed e' integra")
def _():
    a = archivio_con(500)
    esito = copie.esegui(a)
    assert esito["timbrature"] == 500, esito
    assert os.path.exists(esito["percorso"])
    # Riaperta da zero deve leggersi e superare il controllo di integrita'.
    con = sqlite3.connect(esito["percorso"])
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 500
    finally:
        con.close()


@prova("copia mentre un altro thread scrive: resta consistente")
def _():
    a = archivio_con(200)
    ferma = threading.Event()
    scritte = []

    def scrittore():
        db = gestione.apri_archivio(a)
        i = 1000
        while not ferma.is_set():
            q = dt.datetime(2026, 9, 2, 8, 0) + dt.timedelta(minutes=i)
            db.execute(
                "INSERT INTO raw_events (source_event_id, device_serial, "
                "employee_code, occurred_at_local, occurred_at_utc, "
                "device_seconds, event_type_raw, event_type, metodo, work_code, "
                "raw_payload, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"x{i}", "SN", 2, q.isoformat(sep=" "), q.isoformat(sep=" "),
                 i, 0, 0, "badge", 0, "00", "x"))
            db.commit()
            scritte.append(i)
            i += 1
            time.sleep(0.001)
        db.close()

    th = threading.Thread(target=scrittore)
    th.start()
    time.sleep(0.15)
    try:
        esito = copie.esegui(a)
    finally:
        ferma.set()
        th.join(timeout=5)
    # Non si pretende un numero preciso: si pretende che la copia si apra,
    # superi il controllo di integrita' e contenga almeno il punto di partenza.
    assert esito["timbrature"] >= 200, esito
    assert len(scritte) > 0, "il thread non ha scritto: la prova non prova nulla"


@prova("due copie insieme: una sola vince, nessuna delle due fallisce")
def _():
    # La copia automatica dello scheduler e quella chiesta a mano dalle
    # Impostazioni possono partire nello stesso secondo. Prima della
    # correzione una delle due moriva su os.replace con PermissionError,
    # perche' il nome del file provvisorio era lo stesso per tutte e due, e
    # l'utente vedeva "copia NON riuscita" mentre la copia c'era.
    a = archivio_con(300)
    esiti, errori = [], []
    partenza = threading.Barrier(2)

    def fai():
        partenza.wait()
        try:
            esiti.append(copie.esegui(a))
        except Exception as e:                                   # noqa: BLE001
            errori.append(e)

    fili = [threading.Thread(target=fai) for _ in range(2)]
    for t in fili:
        t.start()
    for t in fili:
        t.join(timeout=30)
    assert not errori, f"una delle due copie e' fallita: {errori}"
    assert len(esiti) == 2, esiti
    cartella = copie.cartella_copie(a)
    residui = [f for f in os.listdir(cartella) if f.endswith(".parziale")]
    assert not residui, f"file parziali lasciati in giro: {residui}"
    con = sqlite3.connect(esiti[0]["percorso"])
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


@prova("una copia che non si apre viene buttata e non sostituisce la buona")
def _():
    a = archivio_con(10)
    buona = copie.esegui(a)
    contenuto_buono = open(buona["percorso"], "rb").read()

    # Si sabota il controllo per simulare una copia venuta male.
    vero = copie._verifica
    copie._verifica = lambda p: (_ for _ in ()).throw(RuntimeError("copia corrotta"))
    try:
        try:
            copie.esegui(a, quando=dt.date.today())
            assert False, "avrebbe dovuto sollevare"
        except RuntimeError:
            pass
    finally:
        copie._verifica = vero

    assert open(buona["percorso"], "rb").read() == contenuto_buono, \
        "la copia buona e' stata sovrascritta da una rotta"
    cartella = copie.cartella_copie(a)
    residui = [f for f in os.listdir(cartella) if f.endswith(".parziale")]
    assert not residui, f"file parziali lasciati in giro: {residui}"


@prova("rotazione: tiene le ultime sette e la prima di ogni mese")
def _():
    a = archivio_con(5)
    cartella = copie.cartella_copie(a)
    os.makedirs(cartella, exist_ok=True)
    # Novanta giorni di copie finte.
    oggi = dt.date(2026, 9, 1)
    for n in range(90):
        d = oggi - dt.timedelta(days=n)
        open(os.path.join(cartella, f"timbrature-{d.isoformat()}.db"), "wb").write(b"x")
    copie.pota(a)
    rimaste = sorted(d for d, _, _ in copie.elenco(a))

    ultime7 = {oggi - dt.timedelta(days=n) for n in range(7)}
    assert ultime7 <= set(rimaste), "mancano copie fra le ultime sette"

    # Nessun mese va perso: da giugno a settembre deve restare una traccia.
    mesi = {(d.year, d.month) for d in rimaste}
    assert mesi == {(2026, 6), (2026, 7), (2026, 8), (2026, 9)}, mesi

    # Nei mesi interamente fuori dalla finestra dei sette giorni deve restare
    # esattamente la prima copia del mese, non una a caso.
    for anno, mese, atteso in ((2026, 6, dt.date(2026, 6, 4)),
                               (2026, 7, dt.date(2026, 7, 1))):
        del_mese = [d for d in rimaste if (d.year, d.month) == (anno, mese)]
        assert del_mese == [atteso], f"mese {mese}: {del_mese} invece di [{atteso}]"

    # Agosto ne tiene sei perche' cadono dentro la finestra, piu' la sua prima.
    assert dt.date(2026, 8, 1) in rimaste, "persa la prima copia di agosto"
    assert len(rimaste) == 10, f"{len(rimaste)} copie rimaste invece di 10"
    # Novanta copie ridotte a dieci: la potatura lavora davvero.
    assert len(rimaste) < 90


@prova("serve_oggi: vero senza copie, falso dopo averne fatta una")
def _():
    a = archivio_con(3)
    assert copie.serve_oggi(a), "senza copie deve chiederne una"
    copie.esegui(a)
    assert not copie.serve_oggi(a), "dopo la copia di oggi non ne serve un'altra"


@prova("potatura del registro: tocca gli scarichi, mai le timbrature")
def _():
    a = archivio_con(50)
    db = gestione.apri_archivio(a)
    adesso = dt.datetime.now()
    for giorni in (400, 200, 130, 100, 10, 1):
        db.execute("INSERT INTO importazioni (quando, esito) VALUES (?, 'ok')",
                   ((adesso - dt.timedelta(days=giorni)).isoformat(timespec="seconds"),))
    db.commit()
    prima_timbrature = db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    tolte = gestione.pota_registro(db, giorni=120)
    assert tolte == 3, f"tolte {tolte} righe invece di 3"
    assert db.execute("SELECT COUNT(*) FROM importazioni").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == prima_timbrature, \
        "la potatura ha toccato le timbrature: non deve MAI succedere"
    db.close()


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
