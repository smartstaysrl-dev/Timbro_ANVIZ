#!/usr/bin/env python3
"""
Rifà le figure della guida.

Si lancia a mano quando l'interfaccia cambia:

    python scatti_guida.py

Le figure NON si fanno mai sui dati veri. Un manuale con dentro i nomi e gli
orari dei dipendenti è un documento che gira per il locale, finisce per mail
al consulente e si stampa: qui dentro ci vanno nomi di fantasia e un archivio
inventato, così si può mostrare a chiunque.

Serve Pillow, ma SOLO per fare le figure: il programma vero non lo usa e non
lo richiede. Se manca, lo dice e si ferma senza rompere niente.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sys
import time
import tkinter as tk

CARTELLA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CARTELLA)
FIGURE = os.path.join(CARTELLA, "guida")
LARGHEZZA_FIGURA = 620

# Nomi di fantasia. Nessuno di questi lavora davvero da nessuna parte.
NOMI = ["Marco Bianchi", "Giulia Ferrari", "Ahmed Belhadj", "Sara Conti",
        "Luca Ricci", "Elena Moretti", "Paolo Gallo", "Chiara Rizzo",
        "Ivan Popescu", "Marta Villa", "Diego Sanna", "Anna Greco",
        "Youssef Karim", "Irene Fabbri"]


def archivio_finto(percorso: str, giorni: int = 75, seme: int = 7) -> int:
    """Un ristorante inventato: turno spezzato, chiuso il lunedì, qualche
    riposo e qualche uscita dimenticata — perché la guida deve mostrare anche
    le anomalie, non solo il caso in cui va tutto bene."""
    import anviz
    import gestione

    for coda in ("", "-wal", "-shm"):
        p = percorso + coda
        if os.path.exists(p):
            os.remove(p)

    caso = random.Random(seme)
    db = gestione.apri_archivio(percorso)
    adesso = dt.datetime.now().isoformat(timespec="seconds")
    for i, nome in enumerate(NOMI, start=1):
        db.execute("INSERT INTO dipendenti (employee_code, nome, badge, "
                   "attivo, aggiornato) VALUES (?,?,?,1,?)",
                   (i, nome, 12660000 + i, adesso))

    def scrivi(codice, quando):
        utc = quando.replace(tzinfo=anviz.FUSO).astimezone(dt.timezone.utc)
        db.execute(
            "INSERT OR IGNORE INTO raw_events (source_event_id, device_serial, "
            "employee_code, occurred_at_local, occurred_at_utc, device_seconds, "
            "event_type_raw, event_type, metodo, work_code, raw_payload, "
            "imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"f{codice}-{quando:%Y%m%d%H%M}", "FINTO", codice,
             quando.isoformat(sep=" ", timespec="seconds"),
             utc.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),
             int((quando - anviz.EPOCA_DEFAULT).total_seconds()),
             0, 0, "badge", 0, "00", "finto"))

    oggi = dt.date.today()
    quante = 0
    giorno = oggi - dt.timedelta(days=giorni)
    while giorno <= oggi:
        if giorno.weekday() == 0:                  # lunedì chiuso
            giorno += dt.timedelta(days=1)
            continue
        for i in range(1, len(NOMI) + 1):
            if caso.random() < 0.18:               # riposo
                continue
            spezzato = i % 3 != 0
            fasce = ([(11, 20, 15, 0), (18, 30, 23, 40)] if spezzato
                     else [(18, 20, 23, 50)])
            for oe, me, ou, mu in fasce:
                entrata = dt.datetime.combine(giorno, dt.time(oe, me)) \
                    + dt.timedelta(minutes=caso.randint(-12, 14))
                uscita = dt.datetime.combine(giorno, dt.time(ou, mu)) \
                    + dt.timedelta(minutes=caso.randint(-10, 35))
                if giorno == oggi and entrata > dt.datetime.now():
                    continue
                scrivi(i, entrata)
                quante += 1
                if caso.random() < 0.04:           # uscita dimenticata
                    continue
                if giorno == oggi and uscita > dt.datetime.now():
                    continue                       # ancora al lavoro adesso
                scrivi(i, uscita)
                quante += 1
        giorno += dt.timedelta(days=1)
    db.commit()
    db.close()
    return quante


def utenti_finti():
    import anviz
    fuori = []
    for i, nome in enumerate(NOMI, start=1):
        u = anviz.Utente(user_id=i, badge=12660000 + i, ha_password=i % 4 == 0,
                         nome=nome.split()[0].upper(), reparto=0, gruppo=1,
                         modo=6, impronte=0, amministratore=False)
        if i % 4 == 0:
            u.password = "1234"
        fuori.append(u)
    return fuori


def ritaglia(percorso: str) -> None:
    """Riduce la figura alla larghezza della guida."""
    from PIL import Image
    with Image.open(percorso) as img:
        if img.width <= LARGHEZZA_FIGURA:
            return
        altezza = round(img.height * LARGHEZZA_FIGURA / img.width)
        img.resize((LARGHEZZA_FIGURA, altezza),
                   Image.LANCZOS).save(percorso, optimize=True)


def main() -> int:
    try:
        from PIL import ImageGrab                              # noqa: F401
    except ImportError:
        print("Per rifare le figure serve Pillow:  pip install pillow")
        print("(il programma vero non lo usa: e' solo per questo strumento)")
        return 1
    from PIL import ImageGrab

    import gestione
    import presenze
    from interfaccia import abilita_dpi

    os.makedirs(FIGURE, exist_ok=True)
    finto = os.path.join(FIGURE, "_finto.db")
    print(f"archivio inventato: {archivio_finto(finto)} timbrature")

    abilita_dpi()
    # La configurazione vera non si tocca: qui dentro si lavora su una copia
    # con dati inventati, e il salvataggio su disco viene messo a riposo.
    # Senza questo, un messaggio rimasto in coda scriverebbe nel file vero il
    # percorso dell'archivio finto.
    gestione.salva_config = lambda cfg: None

    app = gestione.App()
    app.servizio.stop.set()          # niente terminale: si guarda solo la figura
    app.cfg = dict(app.cfg)
    app.cfg["archivio"] = finto
    app.cfg["posta"] = {
        "attivo": True, "server": "smtp.gmail.com", "porta": 465,
        "sicurezza": "ssl", "utente": "ristorante@esempio.it",
        "password": "off:xxx", "mittente": "ristorante@esempio.it",
        "destinatari": "ristorante@esempio.it", "giorno": 3, "ora": "08:00",
        "ultimo_inviato": "",
    }
    app.serratura.sblocca()
    app.utenti = utenti_finti()
    app.stati_ta = {0: "IN", 1: "OUT"}
    app.dati_terminale = {
        "modello": "W1C Pro", "seriale": "0690200024380174",
        "firmware": "03.52.CT",
        "orologio": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "conteggi": {"timbrature": 2480, "utenti": len(NOMI)},
        "capacita": {"utenti": 3000, "timbrature": 100000},
    }
    app.geometry("1180x760+30+30")
    app.attributes("-topmost", True)
    app.lift()
    app.update()

    def calma(giri=10):
        import queue as _q
        for _ in range(giri):
            while True:
                try:
                    app.coda.get_nowait()
                except _q.Empty:
                    break
            app.update()
            time.sleep(0.05)

    def scatta(finestra, nome, ritaglio=None):
        finestra.attributes("-topmost", True)
        finestra.lift()
        calma(6)
        time.sleep(0.45)
        x, y = finestra.winfo_rootx(), finestra.winfo_rooty()
        w, h = finestra.winfo_width(), finestra.winfo_height()
        riquadro = ritaglio or (x, y, x + w, y + h)
        percorso = os.path.join(FIGURE, nome)
        ImageGrab.grab(bbox=riquadro).save(percorso)
        ritaglia(percorso)
        print("  " + nome)

    def dialogo(costruttore, nome):
        d = costruttore()
        d.update_idletasks()
        d.geometry(f"+{app.winfo_rootx() + 120}+{app.winfo_rooty() + 60}")
        scatta(d, nome)
        d.destroy()
        calma(3)

    print("figure:")
    # --- le schermate ---------------------------------------------------
    for sezione, nome in (("Oggi", "oggi.png"),
                          ("Timbrature", "timbrature.png"),
                          ("Dipendenti", "dipendenti.png")):
        app.mostra(sezione)
        calma()
        scatta(app, nome)

    schermata = app.schermate["Presenze"]
    app.mostra("Presenze")
    ieri = dt.date.today() - dt.timedelta(days=1)
    if ieri.weekday() == 0:
        ieri -= dt.timedelta(days=1)
    schermata.giorno = ieri
    for periodo, nome in (("giorno", "presenze-giorno.png"),
                          ("mese", "presenze-mese.png")):
        if periodo == "mese":
            # Il mese in corso ha solo i primi giorni: una figura quasi vuota
            # non mostra niente di quello che la didascalia promette. Si prende
            # il mese appena chiuso, che e' pieno.
            primo = dt.date.today().replace(day=1)
            schermata.giorno = primo - dt.timedelta(days=15)
        schermata._periodo(periodo)
        calma()
        scatta(app, nome)
        schermata.lista.tela.yview_moveto(1.0)
        calma(4)
        scatta(app, nome.replace(".png", "-grafico.png"))
    schermata._periodo("giorno")
    calma()

    # --- i dialoghi -----------------------------------------------------
    db = gestione.apri_archivio(finto)
    try:
        nomi = gestione.nomi_dipendenti(db)
        elenco = presenze.giornate(db, app.regole, ieri, ieri)
    finally:
        db.close()
    con_anomalia = next((g for g in elenco if g.anomalie), elenco[0])
    dialogo(lambda: gestione.DettaglioGiornata(
        app, app, con_anomalia,
        nomi.get(con_anomalia.employee_code, "Dipendente")), "dettaglio.png")

    app.mostra("Dipendenti")
    calma()
    dialogo(lambda: gestione.ModuloUtente(app, app, app.utenti[0],
                                          NOMI[0]), "dipendente.png")
    dialogo(lambda: gestione.ChiediPin(app, app.serratura), "pin.png")

    # La lettura tessera parla col terminale: si fotografa e si chiude subito,
    # il thread si ferma da solo alla distruzione della finestra.
    dialogo(lambda: gestione.LetturaTessera(app, app), "tessera.png")

    # --- le impostazioni, a pezzi ---------------------------------------
    app.mostra("Impostazioni")
    calma(14)
    imp = app.schermate["Impostazioni"]
    for frazione, nome in ((0.0, "impostazioni.png"),
                           (0.50, "impostazioni-regole.png"),
                           (0.63, "impostazioni-copie.png"),
                           (0.75, "impostazioni-posta.png"),
                           (0.93, "impostazioni-sicurezza.png")):
        for _ in range(6):
            imp.lista.tela.yview_moveto(frazione)
            calma(2)
        time.sleep(0.4)
        scatta(app, nome)

    app.destroy()
    for coda in ("", "-wal", "-shm"):
        try:
            os.remove(finto + coda)
        except OSError:
            pass
    print("fatto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
