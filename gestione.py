#!/usr/bin/env python3
# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
Gestione presenze — applicazione touch per terminale Anviz.

Doppio clic e resta aperta: dentro c'e' lo scheduler che interroga il terminale
da solo. Nessun browser, nessun server, nessun servizio da installare.

    python gestione.py

Le cinque schermate:
  Oggi          chi c'e' adesso, calcolato col motore delle presenze
  Presenze      giorno per giorno: turni, ore, anomalie, rettifiche
  Timbrature    il grezzo come arriva dal terminale, senza interpretazioni
  Dipendenti    anagrafica completa, scritta sul terminale
  Impostazioni  collegamento, regole del locale, manutenzione
"""

from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import os
import queue
import shutil
import sqlite3
import sys
import threading
import time
import tkinter as tk

import aggiorna
import anviz
import copie
import guida
import logo
import posta
import presenze
import sicurezza
from interfaccia import (
    ALTEZZA_TOCCO, BG, BLU, CARD, CARD_CHIARA, F_ENORME, F_GRANDE, F_MONO,
    F_NORMALE, F_PICCOLO, F_TITOLO, GIALLO, ROSSO, TESTO, TESTO_TENUE, VERDE,
    VIOLA, Attesa, Avviso, Bottone, Conferma, Dialogo, Interruttore,
    ListaScorrevole, Scelta, SceltaOra, TastieraTouch, TastierinoNumerico,
    abilita_dpi,
)

CARTELLA = os.path.dirname(os.path.abspath(__file__))


def _cartella_dati() -> str:
    """Dove vivono archivio, configurazione e copie: MAI insieme al codice.

    Aggiornare il programma vuol dire sostituire la cartella del codice. Se li'
    dentro ci fossero anche le timbrature, la mossa istintiva — copio la
    cartella nuova sopra la vecchia — cancellerebbe l'archivio di tutto
    l'anno. Tenerli separati e' l'unica cosa che rende l'aggiornamento una
    faccenda noiosa invece che un rischio.

    Nel pacchetto consegnato il codice sta nella cartella "app" e i dati
    nella cartella "dati", fratelle. Fuori dal pacchetto — quando si lavora sui sorgenti — i dati
    stanno in `dati/` dentro la cartella del progetto. La variabile
    d'ambiente TIMBRA_DATI vince su tutto: serve per farci girare le prove.
    """
    scelta = os.environ.get("TIMBRA_DATI")
    if scelta:
        return os.path.abspath(scelta)
    if os.path.basename(CARTELLA).lower() == "app":
        return os.path.join(os.path.dirname(CARTELLA), "dati")
    return os.path.join(CARTELLA, "dati")


CARTELLA_DATI = _cartella_dati()
VERSIONE = aggiorna.versione_installata(CARTELLA)
FILE_CONFIG = os.path.join(CARTELLA_DATI, "configurazione.json")
FILE_REGOLE = os.path.join(CARTELLA_DATI, "regole.json")

# Nomi dei file che, in una installazione fatta prima della separazione,
# stanno ancora accanto al codice e vanno portati di la'.
DA_TRASLOCARE = ("timbrature.db", "timbrature.db-wal", "timbrature.db-shm",
                 "configurazione.json", "regole.json")


def prepara_cartella_dati() -> list[str]:
    """Crea `dati/` e ci porta dentro quello che era rimasto col codice.

    Si chiama PRIMA di aprire qualunque cosa: spostare un database SQLite
    mentre qualcuno lo tiene aperto lascia indietro i file -wal e -shm, e con
    loro le ultime timbrature scaricate.
    """
    os.makedirs(CARTELLA_DATI, exist_ok=True)
    if os.path.abspath(CARTELLA_DATI) == os.path.abspath(CARTELLA):
        return []
    traslocati = []
    for nome in DA_TRASLOCARE:
        vecchio = os.path.join(CARTELLA, nome)
        nuovo = os.path.join(CARTELLA_DATI, nome)
        if os.path.exists(vecchio) and not os.path.exists(nuovo):
            try:
                shutil.move(vecchio, nuovo)
                traslocati.append(nome)
            except OSError:
                pass
    vecchie_copie = os.path.join(CARTELLA, "copie")
    nuove_copie = os.path.join(CARTELLA_DATI, "copie")
    if os.path.isdir(vecchie_copie) and not os.path.isdir(nuove_copie):
        try:
            shutil.move(vecchie_copie, nuove_copie)
            traslocati.append("copie")
        except OSError:
            pass
    return traslocati


def raddrizza_percorsi(cfg: dict) -> bool:
    """Rimette il percorso dell'archivio dentro `dati`, se era rimasto indietro.

    Il trasloco sposta i FILE, ma la configurazione si porta dentro il percorso
    assoluto di dove stava l'archivio: riletta com'e', il programma va a
    cercarlo dove non c'e' piu' e si crea un archivio nuovo, VUOTO, accanto al
    codice. Le timbrature non si perdono — sono di la' — ma il locale si
    ritrova la storia sparita, e alla prima copia di sicurezza si porta dietro
    il vuoto. Difetto trovato provando il trasloco su un'installazione vera.

    Si tocca solo se l'archivio stava insieme al codice: chi l'ha messo di
    proposito su un disco di rete se lo tiene dov'e'.
    """
    if os.path.abspath(CARTELLA_DATI) == os.path.abspath(CARTELLA):
        return False
    vecchio = os.path.abspath(cfg.get("archivio") or "")
    if os.path.dirname(vecchio) != os.path.abspath(CARTELLA):
        return False
    cfg["archivio"] = os.path.join(CARTELLA_DATI, os.path.basename(vecchio))
    return True

CONFIG_PREDEFINITA = {
    "terminale_ip": "192.168.0.218",
    "terminale_porta": 5010,
    "minuti_fra_scarichi": 5,
    "allinea_orologio": True,
    "tolleranza_orologio_s": 30,
    "archivio": os.path.join(CARTELLA_DATI, "timbrature.db"),
    "operatore": "segreteria",
    # Il seriale letto dal terminale, tenuto anche qui: e' il codice con cui
    # si recupera il PIN, e deve funzionare pure a terminale staccato.
    "terminale_seriale": "",
    "posta": dict(posta.PREDEFINITE),
}

# Le sezioni che si aprono solo col PIN. Guardare non fa danni; cambiare i
# dipendenti sul terminale o le regole con cui si contano le ore, si'.
SEZIONI_PROTETTE = ("Dipendenti", "Impostazioni")

# Il titolo della finestra e' anche la chiave con cui la seconda copia
# ritrova la prima per portarla avanti: si cambia qui e basta.
TITOLO_FINESTRA = "TIMBRA — presenze"

# Il terminale regge una conversazione alla volta: se lo scheduler sta
# scaricando e nel frattempo l'interfaccia gli chiede il seriale, una delle due
# va in timeout. Tutti gli accessi passano da qui.
LUCCHETTO_TERMINALE = threading.Lock()

MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNI = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato",
          "domenica"]


def data_lunga(d: dt.date) -> str:
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month]} {d.year}"


# Se la configurazione risulta illeggibile, il file rotto viene messo da parte
# con questo nome invece di essere sovrascritto dai valori di fabbrica.
FILE_CONFIG_ROTTA = FILE_CONFIG + ".rotta"

# Cosa e' andato storto leggendo la configurazione, se e' andato storto
# qualcosa. Lo legge l'interfaccia per dirlo, invece di ripartire in silenzio
# col PIN di fabbrica e il report spento.
guasto_configurazione: str | None = None


def carica_config() -> dict:
    """La configurazione, coi buchi riempiti dai valori di serie.

    Copia PROFONDA dei valori predefiniti: `dict()` da sola condividerebbe il
    sottodizionario della posta con la costante del modulo, e la prima
    modifica lo cambierebbe per tutti.
    """
    global guasto_configurazione
    guasto_configurazione = None
    cfg = copy.deepcopy(CONFIG_PREDEFINITA)
    if not os.path.exists(FILE_CONFIG):
        return cfg
    try:
        with open(FILE_CONFIG, encoding="utf-8") as f:
            letto = json.load(f)
        if not isinstance(letto, dict):
            raise ValueError("il file non contiene una configurazione")
        cfg.update(letto)
        return cfg
    except (OSError, ValueError) as e:
        # Ripartire zitti dai valori di fabbrica vorrebbe dire: PIN di nuovo
        # 12345, report mensile spento, password della posta persa — e nessuno
        # se ne accorge. Il file rotto si mette da parte prima che il primo
        # salvataggio lo cancelli per sempre.
        guasto_configurazione = f"{type(e).__name__}: {e}"
        try:
            os.replace(FILE_CONFIG, FILE_CONFIG_ROTTA)
        except OSError:
            pass
    return cfg


def salva_config(cfg: dict) -> None:
    """Scrittura atomica: prima un file a parte, poi il rinomino.

    `open(..., "w")` tronca subito. Un calo di corrente in mezzo — su un PC di
    cucina spento dall'interruttore — lascerebbe un JSON tagliato a meta', e al
    riavvio si ripartirebbe dai valori di fabbrica.
    """
    provvisorio = f"{FILE_CONFIG}.{os.getpid()}.tmp"
    with open(provvisorio, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(provvisorio, FILE_CONFIG)


# --- Archivio ----------------------------------------------------------------
SCHEMA_LOCALE = """
CREATE TABLE IF NOT EXISTS dipendenti (
    employee_code INTEGER PRIMARY KEY,
    nome          TEXT    NOT NULL,
    badge         INTEGER,
    attivo        INTEGER NOT NULL DEFAULT 1,
    aggiornato    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS importazioni (
    quando    TEXT    NOT NULL,
    esito     TEXT    NOT NULL,
    lette     INTEGER NOT NULL DEFAULT 0,
    nuove     INTEGER NOT NULL DEFAULT 0,
    dettaglio TEXT
);
"""

# Colonne aggiunte dopo: si migrano a mano perche' SQLite non ha
# "ADD COLUMN IF NOT EXISTS".
COLONNE_NUOVE = {
    "scarto_s": "REAL",          # scarto dell'orologio del terminale, in secondi
    "riallineato": "INTEGER",    # 1 se in questo giro l'orologio e' stato rimesso
}


def apri_archivio(percorso: str) -> sqlite3.Connection:
    db = anviz.apri_db(percorso)
    db.executescript(SCHEMA_LOCALE)
    presenze.prepara(db)
    esistenti = {r[1] for r in db.execute("PRAGMA table_info(importazioni)")}
    for nome, tipo in COLONNE_NUOVE.items():
        if nome not in esistenti:
            db.execute(f"ALTER TABLE importazioni ADD COLUMN {nome} {tipo}")
    db.commit()
    return db


GIORNI_DERIVA = 14          # finestra su cui si stima la deriva dell'orologio
GIORNI_REGISTRO = 120       # per quanto si tiene il registro degli scarichi


def deriva_orologio(db, giorni: int = GIORNI_DERIVA) -> tuple[float, float, int] | None:
    """Stima quanto perde o guadagna il terminale, in secondi al giorno.

    Si guardano solo le coppie di misure consecutive fra le quali NON c'e'
    stato un riallineamento: dentro quegli intervalli l'orologio corre libero,
    e la differenza fra i due scarti diviso il tempo trascorso e' la deriva.
    Cosi' la stima non viene falsata dai riallineamenti stessi.

    Ritorna (secondi al giorno, ore osservate, numero di intervalli) oppure
    None se non ci sono ancora abbastanza misure.
    """
    # Si guarda solo l'ultimo periodo: la deriva di due anni fa non dice nulla
    # su quella di adesso, e leggere tutto il registro costerebbe sempre di piu'
    # (uno scarico ogni cinque minuti fa centomila righe l'anno).
    da = (dt.datetime.now() - dt.timedelta(days=giorni)).isoformat(timespec="seconds")
    righe = list(db.execute(
        "SELECT quando, scarto_s, riallineato FROM importazioni "
        "WHERE esito = 'ok' AND scarto_s IS NOT NULL AND quando >= ? "
        "ORDER BY quando", (da,)))
    somma_scarto = somma_tempo = 0.0
    intervalli = 0
    for (q1, s1, r1), (q2, s2, _) in zip(righe, righe[1:]):
        if r1:                      # in mezzo c'e' stato un riallineamento
            continue
        secondi = (dt.datetime.fromisoformat(q2)
                   - dt.datetime.fromisoformat(q1)).total_seconds()
        if secondi < 120:           # intervalli troppo corti: solo rumore
            continue
        somma_scarto += s2 - s1
        somma_tempo += secondi
        intervalli += 1
    if intervalli < 2 or somma_tempo < 3600:
        return None
    return (somma_scarto / somma_tempo * 86400, somma_tempo / 3600, intervalli)


def pota_registro(db, giorni: int = GIORNI_REGISTRO) -> int:
    """Toglie dal registro degli scarichi le righe piu' vecchie di N giorni.

    Le timbrature non si toccano MAI: qui si pota solo il diario tecnico degli
    scarichi, che altrimenti crescerebbe di centomila righe l'anno senza che
    nessuno lo guardi.
    """
    limite = (dt.datetime.now() - dt.timedelta(days=giorni)).isoformat(
        timespec="seconds")
    cur = db.execute("DELETE FROM importazioni WHERE quando < ?", (limite,))
    db.commit()
    return cur.rowcount


def _quando_o_niente(testo):
    """Una data scritta in archivio o in configurazione, o None se illeggibile."""
    if not testo:
        return None
    try:
        return dt.datetime.fromisoformat(str(testo))
    except (TypeError, ValueError):
        return None


def nomi_dipendenti(db) -> dict[int, str]:
    return {r[0]: r[1] for r in db.execute(
        "SELECT employee_code, nome FROM dipendenti")}


# --- Servizio di raccolta -----------------------------------------------------
class Servizio(threading.Thread):
    """Interroga il terminale a intervalli e riporta gli esiti in coda."""

    def __init__(self, cfg: dict, coda: queue.Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.coda = coda
        self.stop = threading.Event()
        self.sveglia = threading.Event()
        self.in_corso = threading.Lock()
        # Il report vive fuori dal lucchetto dello scarico, e "Aggiorna" fa
        # partire un secondo thread: senza questo, il tasto premuto mentre lo
        # scheduler sta spedendo manderebbe lo stesso mese due volte, perche'
        # "gia' inviato" si segna solo a spedizione finita.
        self.report_in_corso = threading.Lock()
        # Identita' del dispositivo negli archivi: il seriale, non l'indirizzo.
        # L'indirizzo puo' cambiare (DHCP, trasloco di rete) e cambierebbe la
        # chiave degli eventi; il seriale e' inciso nel terminale.
        self.seriale: str | None = None

    def run(self):
        """Ciclo dello scheduler.

        Qualunque cosa esploda, il ciclo continua. Un'eccezione che sfuggisse
        da qui ucciderebbe il thread e la raccolta automatica non ripartirebbe
        piu' fino al riavvio dell'applicazione, senza che nulla lo segnali:
        e' il guasto peggiore possibile per un raccoglitore di presenze.
        Anche il gestore d'errore di _scarica puo' fallire, per esempio se
        l'archivio e' occupato quando prova a registrare l'errore.
        """
        while not self.stop.is_set():
            try:
                self.un_giro()
            except Exception as e:                               # noqa: BLE001
                try:
                    self.coda.put(("errore", {
                        "messaggio": f"guasto interno: {type(e).__name__}: {e}",
                        "quando": dt.datetime.now()}))
                except Exception:
                    pass
            self.sveglia.wait(self._pausa())
            self.sveglia.clear()

    def _pausa(self) -> int:
        """Secondi fra un giro e l'altro. Sta fuori dal try di sopra, quindi
        NON puo' permettersi di sollevare: un valore scritto male nel file
        ucciderebbe il thread in silenzio, e la raccolta si fermerebbe per
        sempre senza che niente lo segnali."""
        try:
            return max(60, int(self.cfg["minuti_fra_scarichi"]) * 60)
        except (KeyError, TypeError, ValueError):
            return 300

    def un_giro(self):
        if not self.in_corso.acquire(blocking=False):
            return
        try:
            self._scarica()
        finally:
            self.in_corso.release()
        # Fuori dal blocco dello scarico apposta: il report mensile non ha
        # bisogno del terminale, legge dall'archivio. Se stesse dentro, un cavo
        # staccato smetterebbe di far arrivare le mail senza che nessuno colleghi
        # le due cose — e ce ne si accorgerebbe a fine anno.
        self._forse_report()
        self._forse_allarme()

    # --- l'avviso che il terminale tace --------------------------------
    def _forse_allarme(self):
        """Manda una mail se il terminale non risponde da giorni.

        Serve perche' altrimenti non se ne accorge nessuno: le timbrature non
        si perdono — restano nel dispositivo — ma un cavo staccato il 3 del
        mese si scopre il 31, e a quel punto mancano anche le ore di chi ha
        cambiato turno e non se lo ricorda piu'.

        Si avvisa UNA volta ogni tanti giorni quanti sono quelli di soglia:
        una mail al giorno per due settimane la si impara a cestinare, e poi
        si cestina anche quella che contava.
        """
        try:
            self._allarme()
        except Exception as e:                                   # noqa: BLE001
            self.coda.put(("report_fallito", {
                "messaggio": f"avviso di guasto non spedito: "
                             f"{type(e).__name__}: {e}"}))

    def _allarme(self):
        imp = posta.impostazioni(self.cfg)
        if not imp.get("attivo") or not posta.configurata(imp):
            return
        try:
            giorni = float(imp.get("allarme_giorni") or 0)
        except (TypeError, ValueError):
            giorni = 0
        if giorni <= 0:
            return                       # avviso spento di proposito

        db = apri_archivio(self.cfg["archivio"])
        try:
            riga = db.execute(
                "SELECT MAX(quando) FROM importazioni WHERE esito = 'ok'"
            ).fetchone()
            mai = db.execute("SELECT COUNT(*) FROM importazioni").fetchone()[0]
        finally:
            db.close()
        ultima = riga[0] if riga else None
        if not mai:
            return          # installazione appena nata: non c'e' niente da dire

        adesso = dt.datetime.now()
        soglia = dt.timedelta(days=giorni)
        quando_ok = _quando_o_niente(ultima)
        if quando_ok is not None and adesso - quando_ok < soglia:
            # Tutto a posto: si dimentica l'allarme, cosi' se ricapita si
            # riparte puliti invece di aspettare la scadenza vecchia.
            if imp.get("ultimo_allarme"):
                self._segna_allarme("")
            return

        gia = _quando_o_niente(imp.get("ultimo_allarme"))
        if gia is not None and adesso - gia < soglia:
            return                       # gia' avvisato di recente

        fermo = (adesso - quando_ok).total_seconds() / 86400 \
            if quando_ok is not None else giorni
        oggetto, testo = posta.testo_allarme(
            fermo, ultima or "",
            f"{self.cfg['terminale_ip']}:{self.cfg['terminale_porta']}")
        posta.invia(imp, oggetto, testo)
        self._segna_allarme(adesso.isoformat(timespec="seconds"))
        self.coda.put(("allarme", {"giorni": int(fermo)}))

    def _segna_allarme(self, quando: str):
        fresche = posta.impostazioni(self.cfg)
        fresche["ultimo_allarme"] = quando
        self.cfg["posta"] = fresche
        self.coda.put(("salva_config", None))

    def _forse_report(self):
        if not self.report_in_corso.acquire(blocking=False):
            return                       # ne sta gia' partendo uno
        try:
            self._report()
        finally:
            self.report_in_corso.release()

    def _report(self):
        imp = posta.impostazioni(self.cfg)
        try:
            bersaglio = posta.tocca_inviare(imp, dt.datetime.now())
        except Exception as e:                                   # noqa: BLE001
            self.coda.put(("report_fallito", {
                "messaggio": f"impostazioni della posta illeggibili: {e}"}))
            return
        if not bersaglio:
            return
        anno, mese = bersaglio
        db = None
        try:
            dal, al = posta.estremi(anno, mese)
            regole = presenze.Regole.carica(FILE_REGOLE)
            db = apri_archivio(self.cfg["archivio"])
            nomi = nomi_dipendenti(db)
            elenco = presenze.giornate(db, regole, dal, al)
            titolo = f"{MESI[mese]} {anno}"
            posta.invia(
                imp,
                oggetto=f"Ore lavorate — {titolo}",
                testo=posta.testo_semplice(elenco, nomi, titolo),
                html=posta.corpo_html(elenco, nomi, titolo, dal, al),
                allegati=[(f"ore-{posta.etichetta(anno, mese)}.csv",
                           presenze.byte_csv(elenco, nomi), "text/csv")])
        except Exception as e:                                   # noqa: BLE001
            # NON si segna come inviato: al prossimo giro ci riprova. Meglio
            # insistere che perdere un mese in silenzio.
            self.coda.put(("report_fallito", {
                "messaggio": f"{MESI[mese]} {anno}: {type(e).__name__}: {e}"}))
            return
        finally:
            if db is not None:
                db.close()
        # Segnato solo adesso, a spedizione avvenuta. Si rilegge invece di
        # riscrivere la copia di prima: nel frattempo il titolare potrebbe
        # aver cambiato il destinatario, e ributtargli dentro lo scatto
        # vecchio glielo cancellerebbe.
        aggiornate = posta.impostazioni(self.cfg)
        aggiornate["ultimo_inviato"] = posta.etichetta(anno, mese)
        self.cfg["posta"] = aggiornate
        self.coda.put(("salva_config", None))
        self.coda.put(("report", {"mese": f"{MESI[mese]} {anno}",
                                  "quante": len(elenco),
                                  "a": ", ".join(posta.destinatari(imp))}))

    def _scarica(self):
        ip, porta = self.cfg["terminale_ip"], self.cfg["terminale_porta"]
        db = None
        try:
            with LUCCHETTO_TERMINALE, anviz.Terminale(ip, porta, timeout=10) as t:
                # Lo scarto si misura sempre, anche se non si riallinea: e' la
                # serie storica che permette di stimare la deriva.
                scarto = (t.orologio() - dt.datetime.now()).total_seconds()
                riallineato = False
                if (self.cfg["allinea_orologio"]
                        and abs(scarto) >= self.cfg["tolleranza_orologio_s"]):
                    t.imposta_orologio()
                    riallineato = True

                if self.seriale is None:
                    try:
                        self.seriale = t.seriale()
                    except Exception:                            # noqa: BLE001
                        pass          # si ripiega sull'indirizzo, e si riprova
                dispositivo = self.seriale or ip
                if self.seriale and self.cfg.get("terminale_seriale") != self.seriale:
                    # Tenuto anche nella configurazione: e' il codice con cui
                    # si recupera il PIN, e quel giorno il terminale potrebbe
                    # essere proprio la cosa che non funziona.
                    self.cfg["terminale_seriale"] = self.seriale
                    self.coda.put(("salva_config", None))

                righe = list(t.timbrature(solo_nuove=True))
                db = apri_archivio(self.cfg["archivio"])
                nuove = anviz.salva(db, dispositivo, righe) if righe else 0
                # Il flag "nuova" si azzera SOLO dopo il salvataggio su disco:
                # meglio un doppione, che il DB scarta, di una timbratura persa.
                if righe:
                    t.marca_nuove_scaricate(len(righe))

                stato = {
                    "conteggi": t.conteggi(),
                    "utenti": t.utenti(),
                    "orologio": t.orologio(),
                    "stati_ta": t.stati_ta(),
                }
            self._registra(db, "ok", len(righe), nuove, None,
                           scarto, riallineato)
            self._manutenzione(db)
            stato.update({"lette": len(righe), "nuove": nuove,
                          "seriale": self.seriale,
                          "quando": dt.datetime.now()})
            self.coda.put(("ok", stato))
        except Exception as e:                                   # noqa: BLE001
            if db is None:
                try:
                    db = apri_archivio(self.cfg["archivio"])
                except Exception:
                    db = None
            self._registra(db, "errore", 0, 0, f"{type(e).__name__}: {e}")
            self.coda.put(("errore", {"messaggio": str(e),
                                      "quando": dt.datetime.now()}))
        finally:
            if db is not None:
                db.close()

    def _manutenzione(self, db):
        """Una volta al giorno: copia di sicurezza e potatura del registro.

        Vive dentro lo scheduler apposta: non c'e' nessun servizio esterno da
        installare, e se il programma gira la copia si fa. Un guasto qui non
        deve fermare la raccolta, che e' la cosa piu' importante.
        """
        try:
            if not copie.serve_oggi(self.cfg["archivio"]):
                return
            pota_registro(db)
            esito = copie.esegui(self.cfg["archivio"])
            self.coda.put(("copia", esito))
        except Exception as e:                                   # noqa: BLE001
            self.coda.put(("copia_fallita", {"messaggio": f"{type(e).__name__}: {e}"}))

    @staticmethod
    def _registra(db, esito, lette, nuove, dettaglio,
                  scarto=None, riallineato=False):
        if db is None:
            return
        db.execute("INSERT INTO importazioni (quando, esito, lette, nuove, "
                   "dettaglio, scarto_s, riallineato) VALUES (?,?,?,?,?,?,?)",
                   (dt.datetime.now().isoformat(timespec="seconds"), esito,
                    lette, nuove, dettaglio, scarto, 1 if riallineato else 0))
        db.commit()


# --- Dialoghi dell'applicazione ----------------------------------------------
# La specifica del 2019 mappa 0=cinese semplificato, 1=cinese tradizionale,
# 3=inglese, 4=spagnolo, 5=portoghese — e gia' li' manca il 2, segno che la
# tabella e' incompleta. Su questo firmware NON torna: il terminale e' stato
# impostato in italiano e legge 0. Finche' non e' verificata sul campo si
# mostra il numero e basta, invece di scrivere a schermo una cosa falsa.
LINGUE_SPEC = {0: "cinese semplificato", 1: "cinese tradizionale",
               3: "inglese", 4: "spagnolo", 5: "portoghese"}

MODI_VERIFICA = {
    0: "come da gruppo", 1: "solo impronta", 2: "solo password",
    3: "solo tessera", 4: "impronta o password", 5: "impronta o tessera",
    6: "impronta, password o tessera",
}


class Guida(Dialogo):
    """Il manuale, dentro il programma.

    Un PDF finisce in una cartella e non lo apre piu' nessuno. La guida deve
    stare dove serve, a un dito di distanza dalla schermata che si sta
    guardando: si apre col «?» in alto a destra.
    """

    LARGA_INDICE = 300

    def __init__(self, padre, capitolo=0):
        super().__init__(padre, "Guida")
        larghezza = min(1040, padre.winfo_screenwidth() - 60)
        altezza = min(740, padre.winfo_screenheight() - 90)
        self.geometry(f"{larghezza}x{altezza}")
        self.resizable(True, True)

        testata = tk.Frame(self, bg=BG)
        testata.pack(fill="x", padx=24, pady=(18, 8))
        tk.Label(testata, text="Guida", bg=BG, fg=TESTO,
                 font=F_TITOLO).pack(side="left")
        Bottone(testata, "Chiudi", self.destroy, font=F_NORMALE, altezza=52,
                larghezza=150).pack(side="right")

        corpo = tk.Frame(self, bg=BG)
        corpo.pack(fill="both", expand=True, padx=16, pady=(0, 18))

        colonna = tk.Frame(corpo, bg=BG, width=self.LARGA_INDICE)
        colonna.pack(side="left", fill="y")
        colonna.pack_propagate(False)
        self.indice = ListaScorrevole(colonna)
        self.indice.pack(fill="both", expand=True)

        self.testo = ListaScorrevole(corpo)
        self.testo.pack(side="left", fill="both", expand=True, padx=(12, 0))

        self._immagini = []
        self.bottoni = []
        for n, (titolo, _) in enumerate(guida.CAPITOLI):
            b = Bottone(self.indice.interno, titolo,
                        lambda i=n: self.apri(i), font=F_NORMALE,
                        altezza=64, larghezza=self.LARGA_INDICE - 16)
            b.etichetta.config(wraplength=self.LARGA_INDICE - 40,
                               justify="left", anchor="w")
            b.pack(fill="x", pady=2, padx=4)
            self.bottoni.append(b)
        self.apri(capitolo)

    def apri(self, n):
        for i, b in enumerate(self.bottoni):
            acceso = i == n
            b.tinta(BLU if acceso else CARD, BG if acceso else TESTO)
        self.testo.svuota()
        self._immagini.clear()
        titolo, blocchi = guida.CAPITOLI[n]
        tk.Label(self.testo.interno, text=titolo, bg=BG, fg=TESTO,
                 font=F_TITOLO, anchor="w", justify="left",
                 wraplength=620).pack(fill="x", padx=8, pady=(4, 12))
        for blocco in blocchi:
            if blocco.startswith("# "):
                tk.Label(self.testo.interno, text=blocco[2:], bg=BG, fg=BLU,
                         font=F_GRANDE, anchor="w", justify="left",
                         wraplength=620).pack(fill="x", padx=8, pady=(14, 4))
            elif blocco.startswith("- "):
                riga = tk.Frame(self.testo.interno, bg=BG)
                riga.pack(fill="x", padx=8)
                tk.Label(riga, text="•", bg=BG, fg=VERDE,
                         font=F_NORMALE).pack(side="left", anchor="n", padx=(6, 8))
                tk.Label(riga, text=blocco[2:], bg=BG, fg=TESTO,
                         font=F_NORMALE, anchor="w", justify="left",
                         wraplength=580).pack(side="left", fill="x", expand=True)
            elif blocco.startswith("! "):
                self._figura(blocco[2:])
            else:
                tk.Label(self.testo.interno, text=blocco, bg=BG, fg=TESTO,
                         font=F_NORMALE, anchor="w", justify="left",
                         wraplength=620).pack(fill="x", padx=8, pady=4)
        self.testo.segui_trascinamento(self.testo.interno)
        self.testo.tela.yview_moveto(0)

    def _figura(self, riga):
        """Una schermata del programma, con la sua didascalia.

        Le immagini si tengono in una lista: Tk NON conserva un riferimento
        alle PhotoImage, e se le lascia raccogliere dal garbage collector il
        riquadro resta vuoto senza dare nessun errore.
        """
        nome, _, didascalia = riga.partition("|")
        percorso = os.path.join(CARTELLA, "guida", nome.strip())
        try:
            immagine = tk.PhotoImage(file=percorso)
        except tk.TclError:
            tk.Label(self.testo.interno,
                     text=f"(figura mancante: {nome.strip()} — si rifanno con "
                          f"scatti_guida.py)", bg=BG, fg=TESTO_TENUE,
                     font=F_PICCOLO, anchor="w").pack(fill="x", padx=8, pady=6)
            return
        self._immagini.append(immagine)
        cornice = tk.Frame(self.testo.interno, bg=CARD_CHIARA)
        cornice.pack(anchor="w", padx=8, pady=(10, 2))
        tk.Label(cornice, image=immagine, bg=CARD_CHIARA, bd=0).pack(padx=2,
                                                                    pady=2)
        if didascalia.strip():
            tk.Label(self.testo.interno, text=didascalia.strip(), bg=BG,
                     fg=TESTO_TENUE, font=F_PICCOLO, anchor="w",
                     justify="left", wraplength=620).pack(fill="x", padx=10,
                                                          pady=(0, 10))

    @staticmethod
    def mostra(padre, capitolo=0):
        Guida(padre, capitolo).concludi()


class ChiediPin(Dialogo):
    """Il PIN delle sezioni pericolose.

    Cinque tentativi sbagliati e si aspetta mezzo minuto: non ferma nessuno
    che sia deciso — cinque cifre si provano tutte — ma toglie la voglia a chi
    sta pasticciando col tablet mentre aspetta il conto.

    Il recupero e' nascosto apposta: si tiene premuto il lucchetto per tre
    secondi. Non e' un segreto crittografico, e' un comando che non si trova
    per caso col dito, cosi' non compare in una schermata che il titolare
    mostra a tutti quando dice "guarda com'e' fatto".
    """

    TENTATIVI = 5
    PAUSA_S = 30

    def __init__(self, padre, serratura, titolo="Sezione protetta",
                 spiegazione=None):
        super().__init__(padre, titolo)
        self.serratura = serratura
        self.pin = ""
        self.sbagliati = 0
        self._attesa = 0
        self._premuto_da = None

        self.lucchetto = tk.Label(self, text="🔒", bg=BG, fg=GIALLO,
                                  font=("Segoe UI", 30), cursor="hand2")
        self.lucchetto.pack(pady=(22, 0))
        self.lucchetto.bind("<ButtonPress-1>", self._giu)
        self.lucchetto.bind("<ButtonRelease-1>", self._su)
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(
            pady=(4, 2), padx=40)
        tk.Label(self, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO, wraplength=380,
                 justify="center",
                 text=spiegazione or "Serve il PIN per entrare qui. Poi resta "
                                     f"aperta {sicurezza.MINUTI_SBLOCCO} "
                                     f"minuti.").pack(padx=40, pady=(0, 10))

        self.schermo = tk.Label(self, text="", bg=CARD, fg=TESTO,
                                font=("Consolas", 26), width=12, height=1)
        self.schermo.pack(padx=30, pady=(0, 6), ipady=8)
        self.messaggio = tk.Label(self, text="", bg=BG, fg=ROSSO,
                                  font=F_PICCOLO, wraplength=380)
        self.messaggio.pack(padx=30, pady=(0, 8))

        griglia = tk.Frame(self, bg=BG)
        griglia.pack(padx=30, pady=(0, 8))
        for riga in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9"),
                     ("canc", "0", "ok")):
            f = tk.Frame(griglia, bg=BG)
            f.pack(pady=4)
            for ch in riga:
                if ch == "canc":
                    b = Bottone(f, "←", self._cancella, font=F_TITOLO,
                                altezza=64, larghezza=104)
                elif ch == "ok":
                    b = Bottone(f, "✓", self._conferma, colore=VERDE,
                                colore_testo=BG, font=F_TITOLO, altezza=64,
                                larghezza=104)
                else:
                    b = Bottone(f, ch, lambda c=ch: self._cifra(c),
                                font=F_TITOLO, altezza=64, larghezza=104)
                b.pack(side="left", padx=4)
        Bottone(self, "Annulla", self.destroy, altezza=60,
                larghezza=200).pack(pady=(0, 20))

    # -- tastierino --
    def _cifra(self, c):
        if self._attesa:
            return
        if len(self.pin) < sicurezza.CIFRE_MAX:
            self.pin += c
            self._disegna()

    def _cancella(self):
        self.pin = self.pin[:-1]
        self._disegna()

    def _disegna(self):
        self.schermo.config(text="●" * len(self.pin))

    def _conferma(self):
        if self._attesa:
            return
        if self.serratura.verifica(self.pin):
            self.serratura.sblocca()
            self.risultato = True
            self.destroy()
            return
        self.pin = ""
        self._disegna()
        self.sbagliati += 1
        if self.sbagliati >= self.TENTATIVI:
            self.sbagliati = 0
            self._attesa = self.PAUSA_S
            self._conto_alla_rovescia()
        else:
            resta = self.TENTATIVI - self.sbagliati
            self.messaggio.config(
                text=f"PIN sbagliato. Ancora {resta} "
                     f"{'tentativo' if resta == 1 else 'tentativi'}.")

    def _conto_alla_rovescia(self):
        if not self.winfo_exists():
            return
        if self._attesa <= 0:
            self.messaggio.config(text="")
            return
        self.messaggio.config(text=f"Troppi tentativi. Riprova fra "
                                   f"{self._attesa} secondi.")
        self._attesa -= 1
        self.after(1000, self._conto_alla_rovescia)

    # -- recupero nascosto --
    def _giu(self, _):
        self._premuto_da = self.after(3000, self._recupero)

    def _su(self, _):
        if self._premuto_da is not None:
            self.after_cancel(self._premuto_da)
            self._premuto_da = None

    def _recupero(self):
        self._premuto_da = None
        if not self.winfo_exists():
            return          # finestra chiusa mentre il dito era ancora giu'
        if not self.serratura.codice_di_recupero_disponibile():
            Avviso.mostra(
                self, "Recupero non disponibile",
                "Il numero di serie del terminale non e' ancora stato letto, "
                "e senza quello non c'e' codice di recupero.\n\n"
                "Per rimettere il PIN di fabbrica: chiudi il programma, apri "
                "configurazione.json e togli le due righe che cominciano per "
                "\"pin_\".", GIALLO)
            return
        codice = TastierinoNumerico.chiedi(
            self, "Codice di recupero", "",
            "Sono le ultime sei cifre del numero di serie stampato "
            "sull'etichetta dietro il terminale. Il PIN torna a quello di "
            "fabbrica.")
        if not codice:
            return
        if not self.serratura.recupera(codice):
            self.messaggio.config(text="Codice di recupero sbagliato.")
            return
        Avviso.mostra(self, "PIN riportato a quello di fabbrica",
                      f"Adesso si entra con {sicurezza.PIN_PREDEFINITO}. "
                      f"Cambialo appena puoi, da Impostazioni.", VERDE)

    @staticmethod
    def chiedi(padre, serratura, titolo="Sezione protetta", spiegazione=None):
        return ChiediPin(padre, serratura, titolo, spiegazione).concludi()


class LetturaTessera(Dialogo):
    """Fa leggere il numero di una tessera al terminale, da qui.

    Sul dispositivo si iscrive una tessera avvicinandola al lettore. Lo stesso
    si puo' fare da remoto: il terminale tiene da parte l'ultimo numero letto e
    lo consegna col comando 0x7E. Cosi' non serve copiare a mano il numero
    stampato sul badge — che spesso non c'e' nemmeno, o non corrisponde.

    Il collegamento resta aperto per tutta l'attesa, col lucchetto in mano:
    il terminale regge una conversazione sola, e aprirne una nuova a ogni
    interrogazione significherebbe litigare con lo scheduler ogni mezzo secondo.
    """

    SECONDI = 30
    PAUSA = 0.4

    def __init__(self, padre, app):
        super().__init__(padre, "Avvicina la tessera")
        self.app = app
        self.errore = None
        self._ferma = threading.Event()
        # Il conto alla rovescia non deve partire finche' il collegamento non
        # e' aperto: se lo scheduler sta scaricando tiene il lucchetto del
        # terminale, e i trenta secondi finirebbero in attesa, col dialogo che
        # poi dice "non ho letto niente, riappoggia il badge" — una diagnosi
        # falsa che fa riprovare all'infinito.
        self._collegato = threading.Event()
        self._esito = {}

        tk.Label(self, text="Avvicina la tessera al lettore", bg=BG, fg=TESTO,
                 font=F_TITOLO).pack(padx=44, pady=(26, 8))
        tk.Label(self, bg=BG, fg=TESTO_TENUE, font=F_NORMALE, wraplength=460,
                 justify="center",
                 text="Appoggia il badge sul terminale: il numero arriva qui "
                      "da solo. Se la tessera e' gia' di qualcuno, il "
                      "terminale registra anche una timbratura — si annulla "
                      "dalla schermata Timbrature.").pack(padx=44)
        self.avanzamento = tk.Label(self, text="in attesa", bg=BG, fg=BLU,
                                    font=F_GRANDE)
        self.avanzamento.pack(pady=(16, 6))
        self.nota = tk.Label(self, text="", bg=BG, fg=TESTO_TENUE,
                             font=F_PICCOLO, wraplength=460, justify="center")
        self.nota.pack(padx=44)
        Bottone(self, "Annulla", self._annulla, altezza=64,
                larghezza=200).pack(pady=(18, 26))

        self.protocol("WM_DELETE_WINDOW", self._annulla)
        threading.Thread(target=self._lavora, daemon=True).start()
        self._scade = self.SECONDI
        self._batti()

    def _lavora(self):
        try:
            with LUCCHETTO_TERMINALE, anviz.Terminale(
                    self.app.cfg["terminale_ip"],
                    self.app.cfg["terminale_porta"], timeout=5) as t:
                self._collegato.set()
                # Prima lettura buttata via: il terminale conserva l'ultima
                # tessera passata, che puo' essere di ore fa. Senza questo
                # svuotamento si iscriverebbe il badge di chi e' entrato prima.
                t.numero_tessera()
                while not self._ferma.wait(self.PAUSA):
                    numero = t.numero_tessera()
                    if numero:
                        self._esito = {"numero": numero}
                        return
        except Exception as e:                                   # noqa: BLE001
            self._esito = {"errore": e}
        finally:
            self._ferma.set()

    def destroy(self):
        # Comunque la si chiuda — bottone, croce, chiusura dall'esterno — il
        # thread deve fermarsi: tiene aperto il collegamento e IL LUCCHETTO,
        # e uno dimenticato li' blocca lo scheduler per sempre.
        self._ferma.set()
        super().destroy()

    def _batti(self):
        if not self.winfo_exists():
            return
        if self._esito.get("errore") is not None:
            self.errore = self._esito["errore"]
            self.risultato = None
            self.destroy()
            return
        if self._esito.get("numero"):
            self.risultato = self._esito["numero"]
            self.destroy()
            return
        if not self._collegato.is_set():
            self.avanzamento.config(text="attendo il terminale", fg=GIALLO)
            self.nota.config(text="Sta finendo di scaricare le timbrature. "
                                  "Fra un attimo tocca a noi.")
            self.after(400, self._batti)
            return
        if self._scade <= 0:
            self._ferma.set()
            self.avanzamento.config(text="nessuna tessera", fg=GIALLO)
            self.nota.config(
                text="Il terminale non ha letto niente. Riprova appoggiando "
                     "bene il badge, oppure scrivi il numero a mano.")
            # Registrato sul padre: distruggersi dentro un proprio `after`
            # lascia Tkinter a ripulire un oggetto gia' sparito.
            self.master.after(1600, self.destroy)
            return
        self.avanzamento.config(text=f"{self._scade} s", fg=BLU)
        if self.nota.cget("text"):
            self.nota.config(text="")   # toglie l'avviso dell'attesa
        self._scade -= 1
        self.after(1000, self._batti)

    def _annulla(self):
        self._ferma.set()
        self.risultato = None
        self.destroy()

    @staticmethod
    def chiedi(padre, app) -> int | None:
        d = LetturaTessera(padre, app)
        numero = d.concludi()
        if d.errore is not None:
            Avviso.errore(padre, f"Il terminale non risponde.\n\n{d.errore}")
        return numero


class ModuloUtente(Dialogo):
    """Anagrafica completa di un utente, scritta sul terminale."""

    def __init__(self, padre, app, utente: anviz.Utente | None,
                 nome_locale: str = ""):
        nuovo = utente is None
        super().__init__(padre, "Nuovo dipendente" if nuovo else "Modifica")
        self.app = app
        self.nuovo = nuovo
        # Copia, non l'oggetto vivo: anviz.Utente e' mutabile ed e' lo stesso
        # che sta in app.utenti. Modificandolo sul posto, premere Annulla non
        # annullerebbe niente e l'elenco mostrerebbe una tessera che sul
        # terminale non e' mai stata scritta.
        self.u = copy.copy(utente) if utente is not None else anviz.Utente(
            user_id=app.prossimo_id_libero(), badge=None, ha_password=False,
            nome="", reparto=0, gruppo=1, modo=6, impronte=0,
            amministratore=False)
        self.nome_locale = nome_locale or self.u.nome

        tk.Label(self, text="Nuovo dipendente" if nuovo else f"Utente {self.u.user_id}",
                 bg=BG, fg=TESTO, font=F_TITOLO).pack(pady=(20, 4), padx=30)
        tk.Label(self, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO, wraplength=520,
                 justify="left",
                 text="Tessera e PIN si impostano da qui: la tessera puo' "
                      "leggerla il terminale, basta avvicinarla al lettore. "
                      "Solo le impronte vanno iscritte sul dispositivo, "
                      "perche' richiedono il dito.").pack(padx=30, pady=(0, 14))

        # I bottoni si impacchettano PRIMA e in basso: su un registratore di
        # cassa da 1024x600 questa finestra chiedeva 786 pixel di altezza e
        # Salva finiva fuori dallo schermo, cioe' il dipendente non si poteva
        # salvare. Il resto scorre.
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(side="bottom", fill="x", padx=30, pady=(12, 20))
        self.scorrevole = ListaScorrevole(self)
        self.scorrevole.pack(fill="both", expand=True)
        self.scorrevole.tela.configure(
            height=max(220, min(500, self.winfo_screenheight() - 320)))
        self.campi = tk.Frame(self.scorrevole.interno, bg=BG)
        self.campi.pack(fill="x", padx=30)
        self.righe = {}
        self._riga("Nome", "nome", self._cambia_nome)
        self._riga("ID sul terminale", "id", self._cambia_id)
        self._riga("Tessera", "badge", self._cambia_badge)
        self._riga("PIN / password", "pin", self._cambia_pin)
        self._riga("Reparto", "reparto", self._cambia_reparto)
        self._riga("Gruppo", "gruppo", self._cambia_gruppo)
        self._riga("Come si identifica", "modo", self._cambia_modo)

        # Il permesso di amministratore NON e' scrivibile da rete: provato sul
        # dispositivo con tre codifiche diverse (0xC0 e 0x03 sul byte dei
        # permessi, 0xC0 sul byte riservato) e il terminale rilegge sempre
        # "utente normale". Mostrarlo come interruttore sarebbe un comando che
        # finge di funzionare, quindi si mostra e basta.
        f = tk.Frame(self.campi, bg=CARD, height=ALTEZZA_TOCCO)
        f.pack(fill="x", pady=3)
        f.pack_propagate(False)
        tk.Label(f, text="solo dal menu del terminale", bg=CARD, fg=TESTO_TENUE,
                 font=F_PICCOLO).pack(side="right", padx=14)
        tk.Label(f, text="Amministratore", bg=CARD, fg=TESTO_TENUE,
                 font=F_NORMALE, width=17, anchor="w").pack(side="left", padx=16)
        tk.Label(f, text="si" if self.u.amministratore else "no", bg=CARD,
                 fg=VERDE if self.u.amministratore else TESTO,
                 font=F_NORMALE, anchor="w").pack(side="left", fill="x",
                                                  expand=True)

        self.stato_impronte = tk.Label(self.scorrevole.interno, bg=BG,
                                       fg=TESTO_TENUE, font=F_PICCOLO,
                                       anchor="w")
        self.stato_impronte.pack(fill="x", padx=30, pady=(10, 12))

        Bottone(azioni, "Annulla", self.destroy, altezza=64,
                larghezza=170).pack(side="left")
        if not nuovo:
            Bottone(azioni, "Elimina", self._elimina, colore=ROSSO,
                    colore_testo=BG, altezza=64, larghezza=170).pack(side="left",
                                                                     padx=10)
        Bottone(azioni, "Salva", self._salva, colore=VERDE, colore_testo=BG,
                altezza=64, larghezza=170).pack(side="right")
        self._disegna()
        # Rete di sicurezza: se anche cosi' la finestra sfora lo schermo — DPI
        # diverso, caratteri di sistema piu' grandi — si accorcia e si lascia
        # scorrere, invece di nascondere il bottone Salva sotto il bordo.
        self.limita_allo_schermo()

    def _riga(self, etichetta, chiave, comando):
        f = tk.Frame(self.campi, bg=CARD, height=ALTEZZA_TOCCO)
        f.pack(fill="x", pady=3)
        f.pack_propagate(False)
        # Il bottone si impacchetta PER PRIMO: pack da' lo spazio in ordine,
        # e con lo schermo ingrandito (DPI al 150-200%) l'ultimo arrivato
        # finiva fuori dal bordo — "cambia" spariva e il campo non si poteva
        # piu' modificare. Per lo stesso motivo tutta la riga e' toccabile.
        Bottone(f, "cambia", comando, font=F_PICCOLO, altezza=44,
                larghezza=110).pack(side="right", padx=10)
        nome = tk.Label(f, text=etichetta, bg=CARD, fg=TESTO_TENUE,
                        font=F_NORMALE, width=17, anchor="w")
        nome.pack(side="left", padx=16)
        valore = tk.Label(f, text="", bg=CARD, fg=TESTO, font=F_NORMALE,
                          anchor="w")
        valore.pack(side="left", fill="x", expand=True)
        for w in (f, nome, valore):
            w.bind("<Button-1>", lambda _e: comando())
        self.righe[chiave] = valore

    def _disegna(self):
        self.righe["nome"].config(
            text=self.nome_locale or "— da compilare —",
            fg=TESTO if self.nome_locale else GIALLO)
        self.righe["id"].config(text=str(self.u.user_id))
        self.righe["badge"].config(
            text=str(self.u.badge) if self.u.badge else "nessuna",
            fg=TESTO if self.u.badge else TESTO_TENUE)
        # Il PIN si mostra in chiaro: chi apre questa schermata sta gia'
        # amministrando il terminale, e un PIN che non si puo' rileggere e' un
        # PIN che il titolare finisce per scrivere su un foglietto.
        self.righe["pin"].config(
            text=self.u.password if self.u.password else "nessuno",
            fg=TESTO if self.u.password else TESTO_TENUE)
        self.righe["reparto"].config(text=str(self.u.reparto))
        self.righe["gruppo"].config(text=str(self.u.gruppo))
        self.righe["modo"].config(
            text=MODI_VERIFICA.get(self.u.modo, f"codice {self.u.modo}"))
        pezzi = []
        pezzi.append(f"{self.u.impronte} impronte iscritte")
        pezzi.append("password impostata" if self.u.ha_password
                     else "nessuna password")
        self.stato_impronte.config(text="Sul terminale: " + " · ".join(pezzi))

    def _cambia_nome(self):
        v = TastieraTouch.chiedi(self, "Nome del dipendente", self.nome_locale)
        if v is not None:
            self.nome_locale = v
            self._disegna()

    def _cambia_id(self):
        if not self.nuovo:
            Avviso.mostra(self, "Non si cambia",
                          "L'ID identifica l'utente sul terminale e lo lega "
                          "alle timbrature gia' registrate. Per cambiarlo si "
                          "crea un nuovo utente e si disattiva questo.", GIALLO)
            return
        v = TastierinoNumerico.chiedi(self, "ID sul terminale",
                                      str(self.u.user_id),
                                      "Numero con cui il terminale conosce "
                                      "questa persona.")
        if v and v.isdigit() and int(v) > 0:
            self.u.user_id = int(v)
            self._disegna()

    def _cambia_badge(self):
        scelta = Scelta.chiedi(
            self, "Tessera",
            [("Leggila dal terminale", "leggi"),
             ("Scrivi il numero a mano", "mano"),
             ("Togli la tessera", "togli")],
            "Il numero stampato sul badge spesso non corrisponde a quello che "
            "il lettore vede davvero: farlo leggere al terminale e' la strada "
            "sicura.")
        if scelta is None:
            return
        if scelta == "togli":
            self.u.badge = None
        elif scelta == "mano":
            v = TastierinoNumerico.chiedi(
                self, "Numero della tessera", str(self.u.badge or ""),
                "Lascia vuoto per togliere la tessera.")
            if v is None:
                return
            numero = int(v) if v.isdigit() and int(v) > 0 else None
            padrone = self._gia_di_chi(numero) if numero else None
            if padrone is not None:
                Avviso.mostra(
                    self, "Tessera gia' assegnata",
                    f"Il numero {numero} e' la tessera di "
                    f"«{padrone.nome or padrone.user_id}». Due persone con la "
                    f"stessa tessera non si distinguono.", ROSSO)
                return
            self.u.badge = numero
        else:
            numero = LetturaTessera.chiedi(self, self.app)
            if not numero:
                return
            padrone = self._gia_di_chi(numero)
            if padrone is not None:
                Avviso.mostra(
                    self, "Tessera gia' assegnata",
                    f"Il numero {numero} e' la tessera di "
                    f"«{padrone.nome or padrone.user_id}» (utente "
                    f"{padrone.user_id}). Due persone con la stessa tessera "
                    f"non si distinguono: togliela prima all'altro.", ROSSO)
                return
            self.u.badge = numero
        self._disegna()

    def _gia_di_chi(self, numero: int):
        for altro in (self.app.utenti or []):
            if altro.badge == numero and altro.user_id != self.u.user_id:
                return altro
        return None

    def _cambia_pin(self):
        v = TastierinoNumerico.chiedi(
            self, "PIN / password", self.u.password or "",
            "Solo cifre, al massimo otto. E' quello che la persona digita sul "
            "tastierino del terminale. Lascia vuoto per togliere il PIN.")
        if v is None:
            return
        try:
            self.u.imposta_password(v)
        except ValueError as e:
            Avviso.mostra(self, "PIN non valido", str(e), GIALLO)
            return
        # Chi ha solo il PIN e nessuna tessera va messo in "solo password",
        # altrimenti il terminale continua a chiedergli il badge.
        # I modi che accettano gia' la password sono 2 "solo password", 4
        # "impronta o password" e 6 "impronta, password o tessera". Lo 0 e'
        # "come da gruppo" e non garantisce nulla, quindi si offre lo stesso.
        if (self.u.password and not self.u.badge
                and self.u.modo not in (2, 4, 6)):
            if Conferma.chiedi(
                    self, "Lo mettiamo a solo password?",
                    "Questa persona non ha tessera. Se resta impostata su "
                    f"«{MODI_VERIFICA.get(self.u.modo, self.u.modo)}» il "
                    "terminale continuera' a chiederle il badge."):
                self.u.modo = 2
        self._disegna()

    def _cambia_reparto(self):
        v = TastierinoNumerico.chiedi(self, "Reparto", str(self.u.reparto))
        if v is not None and v.isdigit():
            self.u.reparto = int(v) & 0xFF
            self._disegna()

    def _cambia_gruppo(self):
        v = TastierinoNumerico.chiedi(self, "Gruppo", str(self.u.gruppo))
        if v is not None and v.isdigit():
            self.u.gruppo = int(v) & 0xFF
            self._disegna()

    def _cambia_modo(self):
        v = Scelta.chiedi(self, "Come si identifica",
                          [(t, c) for c, t in MODI_VERIFICA.items()],
                          "Su questo modello esistono solo tessera e password: "
                          "le voci con l'impronta non hanno effetto.")
        if v is not None:
            self.u.modo = v
            self._disegna()

    def _salva(self):
        if not self.nome_locale:
            Avviso.mostra(self, "Manca il nome",
                          "Senza nome, nelle presenze compare solo un numero.",
                          GIALLO)
            return
        self.u.nome = self.nome_locale
        if self.nuovo:
            # L'ID e' stato scelto all'apertura della finestra: nel frattempo
            # qualcuno puo' aver iscritto una persona dal terminale con quello
            # stesso numero, e salvare la sovrascriverebbe, impronte comprese.
            altri = {u.user_id for u in (self.app.utenti or [])}
            if self.u.user_id in altri:
                libero = self.app.prossimo_id_libero()
                Avviso.mostra(
                    self, "Numero gia' preso",
                    f"Mentre compilavi, il numero {self.u.user_id} e' stato "
                    f"assegnato a qualcun altro sul terminale. "
                    f"Uso il {libero}.", GIALLO)
                self.u.user_id = libero
                self._disegna()
                return

        esito, errore = Attesa.esegui(
            self, "Scrivo sul terminale...",
            lambda: self.app.con_terminale(
                lambda t: t.salva_utenti([self.u])))
        if errore:
            Avviso.errore(self, f"Il terminale non ha accettato la modifica.\n\n{errore}")
            return
        if esito:
            Avviso.errore(self, f"Il terminale ha rifiutato gli utenti: {esito}")
            return

        db = apri_archivio(self.app.cfg["archivio"])
        try:
            db.execute(
                "INSERT INTO dipendenti (employee_code, nome, badge, attivo, "
                "aggiornato) VALUES (?,?,?,1,?) "
                "ON CONFLICT(employee_code) DO UPDATE SET nome=excluded.nome, "
                "badge=excluded.badge, aggiornato=excluded.aggiornato",
                (self.u.user_id, self.nome_locale, self.u.badge,
                 dt.datetime.now().isoformat(timespec="seconds")))
            db.commit()
        finally:
            db.close()
        self.risultato = True
        self.destroy()
        self.app.scarica_adesso()

    def _elimina(self):
        if not Conferma.chiedi(
                self, "Eliminare il dipendente?",
                f"«{self.nome_locale or self.u.user_id}» viene cancellato dal "
                f"terminale con tessera e impronte.\n\n"
                f"Le timbrature gia' registrate restano in archivio: la storia "
                f"non si perde.", pericoloso=True):
            return
        esito, errore = Attesa.esegui(
            self, "Cancello dal terminale...",
            lambda: self.app.con_terminale(
                lambda t: t.elimina_utente(self.u.user_id)))
        if errore:
            Avviso.errore(self, str(errore))
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            db.execute("UPDATE dipendenti SET attivo = 0 WHERE employee_code = ?",
                       (self.u.user_id,))
            db.commit()
        finally:
            db.close()
        self.risultato = True
        self.destroy()
        self.app.scarica_adesso()


class DettaglioGiornata(Dialogo):
    """I punzoni di una persona in un giorno, con le rettifiche."""

    def __init__(self, padre, app, giornata: presenze.Giornata, nome: str):
        super().__init__(padre, "Dettaglio giornata")
        self.app = app
        self.g = giornata
        self.nome = nome
        self.geometry(f"640x{min(720, self.winfo_screenheight() - 90)}")
        self.resizable(False, True)

        tk.Label(self, text=nome, bg=BG, fg=TESTO, font=F_TITOLO).pack(
            pady=(20, 2), padx=30)
        tk.Label(self, text=data_lunga(giornata.data), bg=BG, fg=TESTO_TENUE,
                 font=F_NORMALE).pack(padx=30)

        riepilogo = tk.Frame(self, bg=CARD)
        riepilogo.pack(fill="x", padx=24, pady=16, ipady=14)
        tk.Label(riepilogo, text=giornata.ore, bg=CARD, fg=VERDE,
                 font=F_ENORME).pack()
        dettaglio = f"{len([t for t in giornata.turni if t.completo])} turni"
        if giornata.minuti_straordinario:
            dettaglio += f" · {giornata.minuti_straordinario} min di straordinario"
        dettaglio += f" · verso dedotto per {getattr(giornata, 'criterio', '?')}"
        tk.Label(riepilogo, text=dettaglio, bg=CARD, fg=TESTO_TENUE,
                 font=F_PICCOLO).pack()

        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=24)

        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=24, pady=16)
        Bottone(azioni, "Aggiungi timbratura", self._aggiungi, colore=BLU,
                colore_testo=BG, altezza=64).pack(fill="x", pady=(0, 6))
        Bottone(azioni, "Chiudi", self.destroy, altezza=60).pack(fill="x")
        self._disegna()

    def _disegna(self):
        self.lista.svuota()
        tutti = sorted(
            [p for t in self.g.turni for p in (t.entrata, t.uscita) if p]
            + list(self.g.scartati), key=lambda p: p.quando)
        for p in tutti:
            riga = tk.Frame(self.lista.interno, bg=CARD)
            riga.pack(fill="x", pady=3, ipady=12)
            colore = (TESTO_TENUE if p.scartato
                      else VERDE if p.verso == "entrata" else GIALLO)
            tk.Label(riga, text=f"{p.quando:%H:%M}", bg=CARD, fg=colore,
                     font=("Consolas", 18), width=7).pack(side="left", padx=(14, 6))
            testi = tk.Frame(riga, bg=CARD)
            testi.pack(side="left", fill="x", expand=True)
            etichetta = (p.scartato or (p.verso or "?").upper())
            tk.Label(testi, text=etichetta, bg=CARD, fg=colore, font=F_NORMALE,
                     anchor="w").pack(fill="x")
            tk.Label(testi, text=f"{p.metodo} · {p.origine}", bg=CARD,
                     fg=TESTO_TENUE, font=F_PICCOLO, anchor="w").pack(fill="x")
            if p.origine == "terminale" and not p.scartato:
                Bottone(riga, "annulla", lambda x=p: self._annulla(x),
                        font=F_PICCOLO, altezza=44,
                        larghezza=110).pack(side="right", padx=12)
            elif p.origine == "rettifica":
                # Una correzione sbagliata va potuta correggere: senza questo,
                # un'uscita messa alle 23:00 invece che alle 22:00 resterebbe
                # li' per sempre.
                Bottone(riga, "togli", lambda x=p: self._togli(x),
                        font=F_PICCOLO, altezza=44,
                        larghezza=110).pack(side="right", padx=12)

        for a in self.g.anomalie:
            tk.Label(self.lista.interno, text="⚠  " + a, bg=BG, fg=GIALLO,
                     font=F_PICCOLO, anchor="w", wraplength=540,
                     justify="left").pack(fill="x", pady=2, padx=4)

    RETTIFICA = ("Le rettifiche cambiano le ore che poi si pagano: "
                 "guardarle e' libero, correggerle no.")

    def _aggiungi(self):
        if not self.app.sbloccata(self, self.RETTIFICA):
            return
        ora = SceltaOra.chiedi(self, "Ora della timbratura")
        if ora is None:
            return
        verso = Scelta.chiedi(self, "Entrata o uscita?",
                              [("Entrata", "entrata"), ("Uscita", "uscita")])
        if verso is None:
            return
        motivo = TastieraTouch.chiedi(self, "Perche' la aggiungi?")
        if not motivo:
            Avviso.mostra(self, "Serve il motivo",
                          "Ogni correzione deve restare spiegata: senza motivo "
                          "non si sa piu' perche' quel giorno e' cambiato.",
                          GIALLO)
            return
        quando = dt.datetime.combine(self.g.data, ora)
        # Un'ora piccola su un turno notturno appartiene al giorno dopo.
        if ora < self.app.regole.ora_inizio:
            quando += dt.timedelta(days=1)
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            presenze.aggiungi_timbratura(db, self.g.employee_code, quando,
                                         verso, motivo,
                                         self.app.cfg["operatore"])
        finally:
            db.close()
        self.risultato = True
        self.destroy()

    def _togli(self, punzone):
        if not self.app.sbloccata(self, self.RETTIFICA):
            return
        if not Conferma.chiedi(
                self, "Togliere questa aggiunta?",
                f"La timbratura delle {punzone.quando:%H:%M} era stata "
                f"inserita a mano. Toglierla la fa sparire del tutto: non e' "
                f"un dato del terminale, e' una correzione.", pericoloso=True):
            return
        try:
            numero = int(str(punzone.evento_id).split(":")[1])
        except (AttributeError, IndexError, ValueError):
            Avviso.errore(self, "Non riesco a risalire a questa correzione.")
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            tolta = presenze.togli_aggiunta(db, numero)
        finally:
            db.close()
        if not tolta:
            Avviso.errore(self, "La correzione non c'e' piu'.")
            return
        self.risultato = True
        self.destroy()

    def _annulla(self, punzone):
        if not self.app.sbloccata(self, self.RETTIFICA):
            return
        if not Conferma.chiedi(
                self, "Annullare questa timbratura?",
                f"La timbratura delle {punzone.quando:%H:%M} non verra' piu' "
                f"contata.\n\nResta comunque in archivio: si annulla il "
                f"conteggio, non il dato."):
            return
        motivo = TastieraTouch.chiedi(self, "Perche' la annulli?")
        if not motivo:
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            presenze.annulla_timbratura(db, self.g.employee_code,
                                        punzone.evento_id, motivo,
                                        self.app.cfg["operatore"])
        finally:
            db.close()
        self.risultato = True
        self.destroy()


# --- Schermate ----------------------------------------------------------------
class Schermata(tk.Frame):
    titolo = ""

    def __init__(self, padre, app):
        super().__init__(padre, bg=BG)
        self.app = app
        self.costruisci()

    def costruisci(self):
        pass

    def entra(self):
        pass

    def intestazione(self, testo, bottoni=()):
        barra = tk.Frame(self, bg=BG)
        barra.pack(fill="x", padx=24, pady=(18, 6))
        tk.Label(barra, text=testo, bg=BG, fg=TESTO, font=F_TITOLO).pack(side="left")
        for etichetta, comando, colore in reversed(bottoni):
            Bottone(barra, etichetta, comando, colore=colore,
                    colore_testo=BG if colore != CARD else TESTO,
                    font=F_NORMALE, altezza=52,
                    larghezza=max(130, 12 * len(etichetta))).pack(side="right",
                                                                  padx=(8, 0))
        return barra


class SchermataOggi(Schermata):
    titolo = "Oggi"

    def costruisci(self):
        self.intestazione("Presenze di oggi",
                          [("Aggiorna", self.app.scarica_adesso, BLU)])
        self.sottotitolo = tk.Label(self, text="", bg=BG, fg=TESTO_TENUE,
                                    font=F_PICCOLO, anchor="w")
        self.sottotitolo.pack(fill="x", padx=24, pady=(0, 10))
        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def entra(self):
        self.lista.svuota()
        # Il giorno OPERATIVO, non la data del calendario: per un ristorante
        # che chiude alle due di notte, all'una e mezza "oggi" e' ancora la
        # serata di ieri. Chiedendo date.today() lo schermo direbbe "nessuna
        # timbratura oggi" con la cucina al completo.
        oggi = presenze.giorno_operativo(dt.datetime.now(), self.app.regole)
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            nomi = nomi_dipendenti(db)
            elenco = presenze.giornate(db, self.app.regole, oggi, oggi)
        finally:
            db.close()

        if not elenco:
            tk.Label(self.lista.interno, text="Nessuna timbratura oggi.",
                     bg=BG, fg=TESTO_TENUE, font=F_GRANDE).pack(pady=50)
            self.sottotitolo.config(text=data_lunga(oggi))
            return

        dentro = 0
        for g in sorted(elenco, key=lambda x: (x.prima_entrata or dt.datetime.min),
                        reverse=True):
            aperto = any(t.entrata and not t.uscita for t in g.turni)
            dentro += 1 if aperto else 0
            nome = nomi.get(g.employee_code, f"Utente {g.employee_code}")
            riquadro = tk.Frame(self.lista.interno, bg=CARD)
            riquadro.pack(fill="x", pady=4, padx=8, ipady=14)
            tk.Frame(riquadro, bg=VERDE if aperto else TESTO_TENUE,
                     width=8).pack(side="left", fill="y")
            testi = tk.Frame(riquadro, bg=CARD)
            testi.pack(side="left", fill="both", expand=True, padx=16)
            tk.Label(testi, text=nome, bg=CARD, fg=TESTO, font=F_GRANDE,
                     anchor="w").pack(fill="x")
            pezzi = []
            if g.prima_entrata:
                pezzi.append(f"dalle {g.prima_entrata:%H:%M}")
            if g.ultima_uscita and not aperto:
                pezzi.append(f"alle {g.ultima_uscita:%H:%M}")
            if g.anomalie:
                pezzi.append(f"{len(g.anomalie)} da verificare")
            tk.Label(testi, text=" · ".join(pezzi) or "—", bg=CARD,
                     fg=GIALLO if g.anomalie else TESTO_TENUE,
                     font=F_PICCOLO, anchor="w").pack(fill="x")
            destra = tk.Frame(riquadro, bg=CARD)
            destra.pack(side="right", padx=20)
            tk.Label(destra, text=g.ore, bg=CARD, fg=TESTO, font=F_GRANDE).pack()
            tk.Label(destra, text="al lavoro" if aperto else "uscito", bg=CARD,
                     fg=VERDE if aperto else TESTO_TENUE, font=F_PICCOLO).pack()
            self.lista.segui_trascinamento(riquadro)

        totale = sum(g.minuti_lavorati for g in elenco)
        self.sottotitolo.config(
            text=f"{data_lunga(oggi)} · {dentro} al lavoro su {len(elenco)} · "
                 f"{totale // 60}h{totale % 60:02d} complessive")


def ore_e_minuti(minuti: int) -> str:
    return f"{minuti // 60}:{minuti % 60:02d}"


def _sfuma(da: str, a: str, quanto: float) -> str:
    """Tinta intermedia fra due colori: piu' ore, piu' acceso."""
    quanto = max(0.0, min(1.0, quanto))
    inizio = [int(da[i:i + 2], 16) for i in (1, 3, 5)]
    fine = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * quanto):02x}"
                         for x, y in zip(inizio, fine))


class GraficoPresenze(tk.Canvas):
    """Le presenze in figura, sotto l'elenco.

    A giorno: una riga per persona e la barra che va dall'entrata all'uscita,
    con le ore scritte sopra. I turni spezzati diventano due barre con il buco
    della pausa in mezzo, e il turno ancora aperto e' giallo e arriva fino
    adesso. A settimana e a mese: una colonna per giorno, alta quanto le ore
    fatte — la forma della settimana si legge in un secondo, cosa che una
    colonna di numeri non permette. Toccando una colonna si apre quel giorno.

    Disegnato a mano su una tela Tk: una libreria di grafici sarebbero
    megabyte di dipendenze per una manciata di rettangoli, e su un
    registratore di cassa ogni dipendenza in piu' e' un'installazione che puo'
    andare storta.
    """

    NOMI = 130           # colonna dei nomi, a sinistra
    TOTALI = 84          # colonna delle ore totali, a destra
    RIGHELLO = 26        # spazio in alto per le ore o le date
    PIEDE = 12
    ALTEZZE = {"giorno": 56, "settimana": 78, "mese": 48}
    TAP = 8              # oltre questi pixel e' un trascinamento, non un tocco

    def __init__(self, padre, al_giorno=None, **kw):
        super().__init__(padre, bg=BG, highlightthickness=0, height=1, **kw)
        self.al_giorno = al_giorno
        self._dati = None
        self._giorni = []
        self._x0 = self._passo = 0
        self._premuto_a = None
        self._larghezza_disegnata = 0
        self._regole = presenze.Regole()
        self.bind("<Configure>", self._ridisposto)
        self.bind("<ButtonPress-1>", self._giu, add="+")
        self.bind("<ButtonRelease-1>", self._su, add="+")

    def mostra(self, elenco, nomi, modo, dal, al, regole=None):
        self._regole = regole or presenze.Regole()
        self._dati = (elenco, nomi, modo, dal, al)
        self._larghezza_disegnata = 0
        self._disegna()

    # --- disposizione ---------------------------------------------------
    def _ridisposto(self, evento):
        # Ridisegnare a ogni pixel di ridimensionamento fa sfarfallare e non
        # serve: si ridisegna solo se la larghezza e' cambiata davvero.
        if abs(evento.width - self._larghezza_disegnata) < 2:
            return
        self._disegna()

    def _disegna(self):
        self.delete("all")
        self._giorni = []
        if not self._dati:
            return
        elenco, nomi, modo, dal, al = self._dati
        larghezza = self.winfo_width()
        if larghezza < 260:
            return                      # non ancora disposto: tornera' un Configure
        self._larghezza_disegnata = larghezza
        persone = self._per_persona(elenco, nomi)
        if not persone:
            return
        riga = self.ALTEZZE[modo]
        altezza = self.RIGHELLO + riga * len(persone) + self.PIEDE
        if self.winfo_reqheight() != altezza:
            self.configure(height=altezza)
        if modo == "giorno":
            self._giornata(persone, larghezza, riga)
        else:
            self._calendario(persone, dal, al, larghezza, riga, modo)

    @staticmethod
    def _per_persona(elenco, nomi):
        gruppi = {}
        for g in elenco:
            gruppi.setdefault(g.employee_code, []).append(g)
        fuori = []
        for codice, giornate in gruppi.items():
            giornate.sort(key=lambda x: x.data)
            fuori.append({
                "codice": codice,
                "nome": nomi.get(codice, f"Utente {codice}"),
                "giornate": giornate,
                "minuti": sum(x.minuti_lavorati for x in giornate),
                "anomalie": sum(len(x.anomalie) for x in giornate),
            })
        fuori.sort(key=lambda p: p["nome"].lower())
        return fuori

    @staticmethod
    def _corto(testo, quante):
        return testo if len(testo) <= quante else testo[:quante - 1] + "…"

    # --- il giorno: una barra dall'entrata all'uscita --------------------
    # I quattro modi in cui un turno puo' finire in figura.
    CHIUSO, IN_CORSO, SENZA_USCITA, SENZA_ENTRATA = range(4)

    @staticmethod
    def _segmenti(persona):
        """Tutti i turni della persona in ordine di orario, buchi compresi.

        Si tengono anche i turni monchi — quelli con la sola uscita — perche'
        sono un'anomalia che va vista: se sparissero dalla figura, il nome in
        giallo direbbe "c'e' qualcosa che non va" e il grafico sotto non
        mostrerebbe niente di strano.
        """
        segmenti = [(g, t) for g in persona["giornate"] for t in g.turni
                    if t.entrata or t.uscita]
        segmenti.sort(key=lambda gt: (gt[1].entrata or gt[1].uscita).quando)
        return segmenti

    @classmethod
    def _come_finisce(cls, giornata, turno, adesso, ultimo, oggi=None):
        """(inizio, fine, genere). `fine` e' None quando la barra e' un moncone.

        Un turno senza uscita significa tre cose diverse.
        E' l'ultimo di oggi: la persona e' dentro adesso, e la barra cresce
        fino all'ora corrente.
        E' l'ultimo di un giorno passato: l'uscita non e' mai stata timbrata, e
        tirare la barra fino a stasera racconterebbe una giornata di sedici ore
        mai lavorata.
        NON e' l'ultimo — dopo di lui la stessa persona ha timbrato ancora:
        allora quel turno e' finito di sicuro, solo che nessuno sa quando.
        Disegnarlo "in corso" lo farebbe passare sotto ai turni successivi, e
        si vedrebbero tre pezzi colorati al posto di uno: e' il difetto che il
        titolare ha visto sullo schermo il 2 settembre.
        """
        if turno.entrata and turno.uscita:
            return turno.entrata.quando, turno.uscita.quando, cls.CHIUSO
        if not turno.entrata:
            return turno.uscita.quando, None, cls.SENZA_ENTRATA
        # Il confronto e' col giorno OPERATIVO, non con la data del calendario:
        # all'una di notte date.today() e' gia' domani, e il cuoco entrato alle
        # dieci di sera diventerebbe un'uscita mancante mentre sta lavorando.
        if (ultimo and giornata.data == (oggi or dt.date.today())
                and adesso > turno.entrata.quando):
            return turno.entrata.quando, adesso, cls.IN_CORSO
        return turno.entrata.quando, None, cls.SENZA_USCITA

    def _giornata(self, persone, larghezza, riga):
        adesso = dt.datetime.now()
        oggi = presenze.giorno_operativo(adesso, self._regole)
        momenti = []
        for p in persone:
            segmenti = self._segmenti(p)
            for i, (g, t) in enumerate(segmenti):
                inizio, fine, _ = self._come_finisce(
                    g, t, adesso, i == len(segmenti) - 1, oggi)
                momenti.append(inizio)
                if fine:
                    momenti.append(fine)
        if not momenti:
            return

        # Finestra oraria adattiva: un ristorante lavora dalle 11 a
        # mezzanotte, disegnare le ventiquattro ore vorrebbe dire sprecare
        # meta' figura per mostrare che di notte non c'era nessuno.
        primo = min(momenti).replace(minute=0, second=0, microsecond=0)
        grezzo = max(momenti)
        ultimo = grezzo.replace(minute=0, second=0, microsecond=0)
        if ultimo < grezzo:
            ultimo += dt.timedelta(hours=1)
        if ultimo - primo < dt.timedelta(hours=4):
            ultimo = primo + dt.timedelta(hours=4)

        x0, x1 = self.NOMI, larghezza - self.TOTALI
        if x1 - x0 < 140:
            return
        secondi = (ultimo - primo).total_seconds()

        def ics(quando):
            frazione = (quando - primo).total_seconds() / secondi
            return x0 + (x1 - x0) * max(0.0, min(1.0, frazione))

        ore = max(1, int(secondi // 3600))
        passo = 1
        while passo < 6 and (x1 - x0) / max(1, ore / passo) < 54:
            passo += 1

        fondo = self.RIGHELLO + riga * len(persone)
        istante = primo
        while istante <= ultimo:
            x = ics(istante)
            self.create_line(x, self.RIGHELLO - 4, x, fondo, fill=CARD)
            self.create_text(x, 11, text=f"{istante:%H:%M}", fill=TESTO_TENUE,
                             font=F_PICCOLO)
            istante += dt.timedelta(hours=passo)

        for i, p in enumerate(persone):
            cima = self.RIGHELLO + riga * i
            centro = cima + 21
            self.create_text(8, centro, text=self._corto(p["nome"], 15),
                             anchor="w", font=F_NORMALE,
                             fill=GIALLO if p["anomalie"] else TESTO)
            self.create_rectangle(x0, centro - 12, x1, centro + 12,
                                  fill=CARD, outline="")
            provvisori = 0
            segmenti = self._segmenti(p)
            for i, (g, t) in enumerate(segmenti):
                inizio, fine, genere = self._come_finisce(
                    g, t, adesso, i == len(segmenti) - 1, oggi)
                xa = ics(inizio)
                if fine is None:
                    # Manca meta' del turno: un moncone e la scritta, non una
                    # barra che finge una durata che nessuno conosce.
                    manca = ("manca l'uscita" if genere == self.SENZA_USCITA
                             else "manca l'entrata")
                    self.create_rectangle(xa - 6, centro - 12, xa + 6,
                                          centro + 12, fill=ROSSO, outline="")
                    # Se il moncone e' il momento piu' tardo della giornata
                    # cade sul bordo destro e la scritta uscirebbe dalla tela:
                    # in quel caso la si ancora dall'altra parte.
                    a_destra = xa + 150 > x1
                    self.create_text(xa + (-11 if a_destra else 11),
                                     centro + 21,
                                     anchor="e" if a_destra else "w",
                                     text=f"{inizio:%H:%M} · {manca}",
                                     fill=ROSSO, font=F_PICCOLO)
                    continue
                in_corso = genere == self.IN_CORSO
                xb = max(ics(fine), xa + 3)
                self.create_rectangle(xa, centro - 12, xb, centro + 12,
                                      fill=GIALLO if in_corso else VERDE,
                                      outline="")
                # Il turno ancora aperto si misura sull'orologio a muro: e' un
                # conteggio provvisorio che serve a occhio, il motore delle
                # presenze non conta i turni non chiusi.
                minuti = t.minuti
                if in_corso:
                    minuti = max(0, int((adesso - inizio).total_seconds() // 60))
                    provvisori += minuti
                if xb - xa >= 44:
                    self.create_text((xa + xb) / 2, centro,
                                     text=ore_e_minuti(minuti), fill=BG,
                                     font=F_PICCOLO)
                if xb - xa >= 78:
                    self.create_text(xa + 5, centro + 21, anchor="w",
                                     text=f"{inizio:%H:%M}", fill=TESTO_TENUE,
                                     font=F_PICCOLO)
                    self.create_text(xb - 5, centro + 21, anchor="e",
                                     text=("in corso" if in_corso
                                           else f"{fine:%H:%M}"),
                                     fill=GIALLO if in_corso else TESTO_TENUE,
                                     font=F_PICCOLO)
            # Il totale e' quello del motore delle presenze, che i turni
            # ancora aperti NON li conta. Se qualcuno e' dentro adesso, le sue
            # ore in corso si dicono a parte: cosi' un totale a zero accanto a
            # una barra lunga smette di sembrare un errore.
            self.create_text(larghezza - 10, centro - (7 if provvisori else 0),
                             anchor="e", text=ore_e_minuti(p["minuti"]),
                             fill=TESTO, font=F_GRANDE)
            if provvisori:
                self.create_text(larghezza - 10, centro + 13, anchor="e",
                                 text=f"+{ore_e_minuti(provvisori)}",
                                 fill=GIALLO, font=F_PICCOLO)

    # --- settimana e mese: una colonna per giorno ------------------------
    def _calendario(self, persone, dal, al, larghezza, riga, modo):
        giorni = [dal + dt.timedelta(days=i) for i in range((al - dal).days + 1)]
        x0, x1 = self.NOMI, larghezza - self.TOTALI
        if not giorni or x1 - x0 < 140:
            return
        passo = (x1 - x0) / len(giorni)
        massimo = max((g.minuti_lavorati for p in persone
                       for g in p["giornate"]), default=0) or 1
        self._giorni, self._x0, self._passo = giorni, x0, passo

        ogni = 1 if passo >= 30 else (2 if passo >= 18 else 5)
        for i, giorno in enumerate(giorni):
            if i % ogni and giorno.day != 1:
                continue
            testo = (f"{GIORNI[giorno.weekday()][:3]} {giorno.day}"
                     if passo >= 44 else str(giorno.day))
            self.create_text(x0 + passo * (i + 0.5), 11, text=testo,
                             font=F_PICCOLO,
                             fill=BLU if giorno.weekday() >= 5 else TESTO_TENUE)

        for k, p in enumerate(persone):
            cima = self.RIGHELLO + riga * k
            base = cima + riga - (26 if modo == "settimana" else 12)
            spazio = base - cima - 8
            self.create_text(8, cima + 18, text=self._corto(p["nome"], 15),
                             anchor="w", font=F_NORMALE,
                             fill=GIALLO if p["anomalie"] else TESTO)
            self.create_line(x0, base, x1, base, fill=CARD_CHIARA)
            per_data = {g.data: g for g in p["giornate"]}
            for i, giorno in enumerate(giorni):
                x = x0 + passo * i
                g = per_data.get(giorno)
                if g is None or not g.minuti_lavorati:
                    # Il giorno senza ore resta visibile come tacca: un buco
                    # vuoto si confonde con "non c'era ancora il dipendente".
                    self.create_rectangle(x + 2, base - 3, x + passo - 2, base,
                                          fill=CARD, outline="")
                    continue
                quota = g.minuti_lavorati / massimo
                alto = max(5, spazio * quota)
                self.create_rectangle(
                    x + 2, base - alto, x + passo - 2, base, outline="",
                    fill=GIALLO if g.anomalie
                    else _sfuma(CARD_CHIARA, VERDE, 0.3 + 0.7 * quota))
                if passo >= 36:
                    dentro = alto >= 18
                    self.create_text(
                        x + passo / 2, base - alto + (10 if dentro else -8),
                        text=ore_e_minuti(g.minuti_lavorati), font=F_PICCOLO,
                        fill=BG if dentro else TESTO)
                if modo == "settimana" and passo >= 62:
                    entrata = (f"{g.prima_entrata:%H:%M}"
                               if g.prima_entrata else "—")
                    uscita = (f"{g.ultima_uscita:%H:%M}"
                              if g.ultima_uscita else "…")
                    self.create_text(x + passo / 2, base + 13,
                                     text=f"{entrata}→{uscita}",
                                     fill=TESTO_TENUE, font=F_PICCOLO)
            self.create_text(larghezza - 10, cima + 18, anchor="e",
                             text=ore_e_minuti(p["minuti"]), fill=TESTO,
                             font=F_GRANDE)

    # --- tocco su una colonna --------------------------------------------
    def _giu(self, evento):
        self._premuto_a = evento.y_root

    def _su(self, evento):
        partenza, self._premuto_a = self._premuto_a, None
        if partenza is None or abs(evento.y_root - partenza) > self.TAP:
            return                      # stava scorrendo, non toccando
        if not (self.al_giorno and self._giorni and self._passo):
            return
        i = int((evento.x - self._x0) // self._passo)
        if 0 <= i < len(self._giorni):
            self.al_giorno(self._giorni[i])


class SchermataPresenze(Schermata):
    titolo = "Presenze"

    PERIODI = (("Giorno", "giorno"), ("Settimana", "settimana"),
               ("Mese", "mese"), ("Dal… al…", "intervallo"))
    NOMI_PERIODO = {"giorno": "il giorno", "settimana": "la settimana",
                    "mese": "il mese", "intervallo": "il periodo"}

    def costruisci(self):
        self.giorno = dt.date.today()
        self.periodo = "giorno"
        # Le date di "Dal... al...": le paghe non seguono sempre il mese di
        # calendario (dal 16 al 15, una quindicina, un contratto a termine).
        self.dal = self.al = self.giorno
        barra = self.intestazione("Presenze")
        self.b_esporta = Bottone(barra, "Esporta il mese", self._esporta,
                                 colore=VIOLA, colore_testo=BG, font=F_NORMALE,
                                 altezza=52, larghezza=200)
        self.b_esporta.pack(side="right")

        filtro = tk.Frame(self, bg=BG)
        filtro.pack(fill="x", padx=24, pady=(0, 8))
        self.bottoni_periodo = {}
        for etichetta, chiave in self.PERIODI:
            b = Bottone(filtro, etichetta, lambda c=chiave: self._periodo(c),
                        font=F_NORMALE, altezza=52, larghezza=140)
            b.pack(side="left", padx=(0, 8))
            self.bottoni_periodo[chiave] = b

        navigatore = tk.Frame(self, bg=BG)
        navigatore.pack(fill="x", padx=24, pady=(0, 10))
        Bottone(navigatore, "◀", lambda: self._sposta(-1), font=F_TITOLO,
                altezza=56, larghezza=90).pack(side="left")
        self.etichetta_giorno = tk.Label(navigatore, text="", bg=BG, fg=TESTO,
                                         font=F_GRANDE)
        self.etichetta_giorno.pack(side="left", expand=True)
        Bottone(navigatore, "▶", lambda: self._sposta(1), font=F_TITOLO,
                altezza=56, larghezza=90).pack(side="right")
        Bottone(navigatore, "oggi", self._oggi, font=F_NORMALE, altezza=56,
                larghezza=110).pack(side="right", padx=10)

        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # --- periodo mostrato -------------------------------------------------
    def _periodo(self, chiave):
        if chiave == "intervallo":
            scelta = Calendario.chiedi_intervallo(
                self, "Tocca il primo e l'ultimo giorno", *self._intervallo())
            if scelta is None:
                return
            self.dal, self.al = scelta
        self.periodo = chiave
        self.entra()

    def _intervallo(self) -> tuple[dt.date, dt.date]:
        if self.periodo == "intervallo":
            return self.dal, self.al
        if self.periodo == "giorno":
            return self.giorno, self.giorno
        if self.periodo == "settimana":
            indietro = (self.giorno.weekday()
                        - self.app.regole.inizio_settimana) % 7
            primo = self.giorno - dt.timedelta(days=indietro)
            return primo, primo + dt.timedelta(days=6)
        primo = self.giorno.replace(day=1)
        return primo, primo.replace(
            day=calendar.monthrange(primo.year, primo.month)[1])

    def _titolo_periodo(self, dal, al) -> str:
        if self.periodo == "intervallo":
            giorni = (al - dal).days + 1
            return (f"dal {dal.day} {MESI[dal.month]} {dal.year} al {al.day} "
                    f"{MESI[al.month]} {al.year} · {giorni} giorni")
        if self.periodo == "giorno":
            return data_lunga(dal)
        if self.periodo == "settimana":
            if dal.month == al.month:
                return f"{dal.day} – {al.day} {MESI[al.month]} {al.year}"
            return (f"{dal.day} {MESI[dal.month]} – {al.day} {MESI[al.month]} "
                    f"{al.year}")
        return f"{MESI[dal.month]} {dal.year}"

    def _sposta(self, passi):
        if self.periodo == "intervallo":
            # Le frecce spostano tutto il periodo della sua lunghezza: dal
            # 16/09-15/10 si passa al 16/10-14/11, lungo uguale.
            durata = dt.timedelta(days=(self.al - self.dal).days + 1)
            self.dal += durata * passi
            self.al += durata * passi
            return self.entra()
        if self.periodo == "giorno":
            self.giorno += dt.timedelta(days=passi)
        elif self.periodo == "settimana":
            self.giorno += dt.timedelta(weeks=passi)
        else:
            # I mesi non sono lunghi uguale: si cammina di primo in primo,
            # altrimenti dal 31 gennaio si finirebbe al 3 marzo.
            primo = self.giorno.replace(day=1)
            for _ in range(abs(passi)):
                primo = ((primo + dt.timedelta(days=32)).replace(day=1)
                         if passi > 0
                         else (primo - dt.timedelta(days=1)).replace(day=1))
            ultimo = calendar.monthrange(primo.year, primo.month)[1]
            self.giorno = primo.replace(day=min(self.giorno.day, ultimo))
        self.entra()

    def _oggi(self):
        self.giorno = dt.date.today()
        if self.periodo == "intervallo":
            # Stessa lunghezza, ma che finisca oggi.
            self.dal += self.giorno - self.al
            self.al = self.giorno
        self.entra()

    # --- contenuto ---------------------------------------------------------
    def entra(self):
        self.lista.svuota()
        dal, al = self._intervallo()
        self.etichetta_giorno.config(text=self._titolo_periodo(dal, al))
        self.b_esporta.testo(f"Esporta {self.NOMI_PERIODO[self.periodo]}")
        for chiave, b in self.bottoni_periodo.items():
            acceso = chiave == self.periodo
            b.tinta(BLU if acceso else CARD, BG if acceso else TESTO)

        db = apri_archivio(self.app.cfg["archivio"])
        try:
            nomi = nomi_dipendenti(db)
            elenco = presenze.giornate(db, self.app.regole, dal, al)
        finally:
            db.close()

        if not elenco:
            tk.Label(self.lista.interno,
                     text="Nessuna presenza in questo periodo.",
                     bg=BG, fg=TESTO_TENUE, font=F_GRANDE).pack(pady=50)
            return

        if self.periodo == "giorno" or (self.periodo == "intervallo"
                                        and dal == al):
            self._schede_giorno(elenco, nomi)
        else:
            self._schede_periodo(elenco, nomi)

        totale = sum(g.minuti_lavorati for g in elenco)
        quante = len({g.employee_code for g in elenco})
        piede = tk.Frame(self.lista.interno, bg=BG)
        piede.pack(fill="x", pady=(14, 4), padx=8)
        tk.Label(piede,
                 text=f"Totale: {totale // 60}h{totale % 60:02d} su "
                      f"{quante} persone",
                 bg=BG, fg=TESTO_TENUE, font=F_NORMALE).pack(anchor="e")

        self._grafico(elenco, nomi, dal, al)

    def _schede_giorno(self, elenco, nomi):
        for g in elenco:
            nome = nomi.get(g.employee_code, f"Utente {g.employee_code}")
            riquadro = tk.Frame(self.lista.interno, bg=CARD)
            riquadro.pack(fill="x", pady=4, padx=8, ipady=12)
            tk.Frame(riquadro, bg=GIALLO if g.anomalie else VERDE,
                     width=8).pack(side="left", fill="y")
            testi = tk.Frame(riquadro, bg=CARD)
            testi.pack(side="left", fill="both", expand=True, padx=16)
            tk.Label(testi, text=nome, bg=CARD, fg=TESTO, font=F_GRANDE,
                     anchor="w").pack(fill="x")
            orari = " → ".join(filter(None, [
                f"{g.prima_entrata:%H:%M}" if g.prima_entrata else None,
                f"{g.ultima_uscita:%H:%M}" if g.ultima_uscita else None]))
            righe = [orari or "—"]
            if g.anomalie:
                righe.append(g.anomalie[0]
                             + (f" (+{len(g.anomalie)-1})" if len(g.anomalie) > 1
                                else ""))
            tk.Label(testi, text=" · ".join(righe), bg=CARD,
                     fg=GIALLO if g.anomalie else TESTO_TENUE, font=F_PICCOLO,
                     anchor="w", justify="left").pack(fill="x")
            tk.Label(riquadro, text=g.ore, bg=CARD, fg=TESTO,
                     font=F_GRANDE).pack(side="right", padx=(0, 12))
            Bottone(riquadro, "dettaglio",
                    lambda gg=g, nn=nome: self._dettaglio(gg, nn),
                    font=F_PICCOLO, altezza=48, larghezza=120).pack(side="right",
                                                                    padx=12)
            self.lista.segui_trascinamento(testi)

    def _schede_periodo(self, elenco, nomi):
        """A settimana e a mese la scheda e' per persona, non per giornata:
        quindici righe al giorno per quattordici dipendenti sarebbero
        quattrocento righe da scorrere per capire chi ha fatto piu' ore."""
        for p in GraficoPresenze._per_persona(elenco, nomi):
            lavorati = sum(1 for g in p["giornate"] if g.minuti_lavorati)
            straordinario = sum(g.minuti_straordinario for g in p["giornate"])
            riquadro = tk.Frame(self.lista.interno, bg=CARD)
            riquadro.pack(fill="x", pady=4, padx=8, ipady=12)
            tk.Frame(riquadro, bg=GIALLO if p["anomalie"] else VERDE,
                     width=8).pack(side="left", fill="y")
            testi = tk.Frame(riquadro, bg=CARD)
            testi.pack(side="left", fill="both", expand=True, padx=16)
            tk.Label(testi, text=p["nome"], bg=CARD, fg=TESTO, font=F_GRANDE,
                     anchor="w").pack(fill="x")
            pezzi = ["1 giorno lavorato" if lavorati == 1
                     else f"{lavorati} giorni lavorati"]
            if lavorati:
                pezzi.append(f"media {ore_e_minuti(p['minuti'] // lavorati)}"
                             f" al giorno")
            if straordinario:
                pezzi.append(f"{ore_e_minuti(straordinario)} di straordinario")
            if p["anomalie"]:
                pezzi.append(f"{p['anomalie']} da verificare")
            tk.Label(testi, text=" · ".join(pezzi), bg=CARD,
                     fg=GIALLO if p["anomalie"] else TESTO_TENUE,
                     font=F_PICCOLO, anchor="w").pack(fill="x")
            tk.Label(riquadro, text=ore_e_minuti(p["minuti"]), bg=CARD,
                     fg=TESTO, font=F_GRANDE).pack(side="right", padx=(0, 20))
            self.lista.segui_trascinamento(testi)

    def _grafico(self, elenco, nomi, dal, al):
        cornice = tk.Frame(self.lista.interno, bg=BG)
        cornice.pack(fill="x", padx=8, pady=(10, 20))
        titoli = {"giorno": "La giornata a colpo d'occhio",
                  "settimana": "La settimana a colpo d'occhio",
                  "mese": "Il mese a colpo d'occhio",
                  "intervallo": "Il periodo a colpo d'occhio"}
        tk.Label(cornice, text=titoli[self.periodo], bg=BG, fg=TESTO,
                 font=F_NORMALE, anchor="w").pack(fill="x", pady=(0, 2))
        if self.periodo == "giorno":
            voci = [(VERDE, "turno chiuso"),
                    (GIALLO, "ancora al lavoro"),
                    (ROSSO, "manca l'entrata o l'uscita")]
            coda = ("La barra e' il tempo fra le due timbrature; il totale a "
                    "destra e' al netto di pause e arrotondamenti.")
        else:
            voci = [(VERDE, "giornata lavorata"),
                    (GIALLO, "c'e' qualcosa da verificare"),
                    (CARD, "riposo o locale chiuso")]
            coda = ("Colonna piu' alta = piu' ore. Tocca un giorno per "
                    "aprirlo.")
        legenda = tk.Frame(cornice, bg=BG)
        legenda.pack(fill="x", pady=(0, 6))
        for colore, testo in voci:
            gruppo = tk.Frame(legenda, bg=BG)
            gruppo.pack(side="left", padx=(0, 18))
            tk.Frame(gruppo, bg=colore, width=16, height=16).pack(
                side="left", pady=2)
            tk.Label(gruppo, text=testo, bg=BG, fg=TESTO_TENUE,
                     font=F_PICCOLO).pack(side="left", padx=6)
        tk.Label(legenda, text=coda, bg=BG, fg=TESTO_TENUE,
                 font=F_PICCOLO).pack(side="left")
        grafico = GraficoPresenze(cornice, al_giorno=self._apri_giorno)
        grafico.pack(fill="x")
        self.lista.segui_trascinamento(grafico)
        # Il grafico conosce solo giorno, settimana e mese: un periodo scelto
        # a mano si disegna come l'uno o l'altro secondo quanto e' lungo.
        modo = self.periodo
        if modo == "intervallo":
            modo = "settimana" if (al - dal).days < 7 else "mese"
        grafico.mostra(elenco, nomi, modo, dal, al, self.app.regole)

    def _apri_giorno(self, giorno):
        self.giorno = giorno
        self.periodo = "giorno"
        self.entra()

    def _dettaglio(self, g, nome):
        if DettaglioGiornata(self, self.app, g, nome).concludi():
            self.entra()

    def _esporta(self):
        dal, al = self._intervallo()
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            nomi = nomi_dipendenti(db)
            elenco = presenze.giornate(db, self.app.regole, dal, al)
        finally:
            db.close()
        if not elenco:
            Avviso.mostra(self, "Niente da esportare",
                          "Nessuna presenza nel periodo mostrato.", GIALLO)
            return
        nome_file = (f"presenze-{dal:%Y-%m}.csv" if self.periodo == "mese"
                     else f"presenze-{dal:%Y-%m-%d}.csv" if dal == al
                     else f"presenze-{dal:%Y-%m-%d}_{al:%Y-%m-%d}.csv")
        percorso = os.path.join(CARTELLA_DATI, nome_file)
        try:
            presenze.esporta_csv(percorso, elenco, nomi)
        except OSError as e:
            # Il caso vero: il file di prima e' ancora aperto in Excel. Senza
            # questo il bottone sembra semplicemente non fare niente.
            Avviso.errore(
                self, f"Non sono riuscito a scrivere il file.\n\n{e}\n\n"
                      f"Se lo hai aperto in Excel, chiudilo e riprova.")
            return
        anomale = sum(1 for g in elenco if g.anomalie)
        Avviso.mostra(
            self, "Esportato",
            f"{len(elenco)} giornate salvate in:\n\n{percorso}\n\n"
            + (f"Attenzione: {anomale} giornate hanno anomalie aperte. "
               f"Conviene sistemarle prima di mandarlo alle paghe."
               if anomale else "Nessuna anomalia aperta."),
            GIALLO if anomale else VERDE)


class Calendario(Dialogo):
    """Il calendario del mese, da toccare col dito.

    Con intervallo=True si toccano due giorni, il primo e l'ultimo, e quelli
    in mezzo si colorano: si vede subito quanti giorni si stanno prendendo.
    Un terzo tocco ricomincia da capo.
    """

    INTESTAZIONE = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]

    def __init__(self, padre, titolo, dal: dt.date, al: dt.date | None = None,
                 intervallo=False):
        super().__init__(padre, titolo)
        self.intervallo = intervallo
        self.dal, self.al = dal, (al or dal)
        self._secondo = False          # il prossimo tocco e' il giorno finale?
        self.mese = self.dal.replace(day=1)
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(
            pady=(16, 6), padx=24)

        testa = tk.Frame(self, bg=BG)
        testa.pack(fill="x", padx=24)
        Bottone(testa, "◀", lambda: self._mese(-1), font=F_TITOLO,
                altezza=52, larghezza=80).pack(side="left")
        Bottone(testa, "▶", lambda: self._mese(1), font=F_TITOLO,
                altezza=52, larghezza=80).pack(side="right")
        self.titolo_mese = tk.Label(testa, text="", bg=BG, fg=TESTO,
                                    font=F_GRANDE)
        self.titolo_mese.pack(side="left", expand=True)

        griglia = tk.Frame(self, bg=BG)
        griglia.pack(padx=24, pady=(10, 4))
        for c, nome in enumerate(self.INTESTAZIONE):
            tk.Label(griglia, text=nome, bg=BG,
                     fg=BLU if c >= 5 else TESTO_TENUE,
                     font=F_PICCOLO).grid(row=0, column=c, pady=(0, 4))
        self.celle = []
        for r in range(6):
            for c in range(7):
                cella = tk.Label(griglia, text="", width=4, bg=CARD, fg=TESTO,
                                 font=F_NORMALE, pady=12)
                cella.grid(row=r + 1, column=c, padx=2, pady=2)
                cella.bind("<Button-1>", lambda _e, i=len(self.celle):
                           self._tocca(i))
                self.celle.append(cella)

        self.riepilogo = tk.Label(self, text="", bg=BG, fg=TESTO_TENUE,
                                  font=F_NORMALE)
        self.riepilogo.pack(pady=(6, 0))
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=24, pady=(12, 18))
        Bottone(azioni, "Annulla", self.destroy, altezza=60,
                larghezza=180).pack(side="left")
        Bottone(azioni, "Conferma", self._conferma, colore=VERDE,
                colore_testo=BG, altezza=60, larghezza=180).pack(side="right")
        self._disegna()

    def _giorni_mostrati(self):
        primo = self.mese - dt.timedelta(days=self.mese.weekday())
        return [primo + dt.timedelta(days=i) for i in range(42)]

    def _mese(self, passo):
        self.mese = ((self.mese + dt.timedelta(days=32)).replace(day=1)
                     if passo > 0
                     else (self.mese - dt.timedelta(days=1)).replace(day=1))
        self._disegna()

    def _tocca(self, i):
        giorno = self._giorni_mostrati()[i]
        if not self.intervallo:
            self.dal = self.al = giorno
        elif not self._secondo:
            self.dal = self.al = giorno
            self._secondo = True
        else:
            self.dal, self.al = min(self.dal, giorno), max(self.dal, giorno)
            self._secondo = False
        if giorno.month != self.mese.month:
            self.mese = giorno.replace(day=1)
        self._disegna()

    def _disegna(self):
        self.titolo_mese.config(
            text=f"{MESI[self.mese.month]} {self.mese.year}".capitalize())
        oggi = dt.date.today()
        for cella, giorno in zip(self.celle, self._giorni_mostrati()):
            fuori = giorno.month != self.mese.month
            if giorno in (self.dal, self.al):
                sfondo, testo = BLU, BG
            elif self.dal < giorno < self.al:
                sfondo, testo = "#3E5585", TESTO     # blu spento: i giorni presi
            else:
                sfondo = BG if fuori else CARD
                testo = (GIALLO if giorno == oggi
                         else TESTO_TENUE if fuori else TESTO)
            cella.config(text=str(giorno.day), bg=sfondo, fg=testo)
        if not self.intervallo:
            self.riepilogo.config(text=data_lunga(self.dal))
        elif self._secondo:
            self.riepilogo.config(
                text=f"dal {data_lunga(self.dal)} — ora tocca l'ultimo giorno")
        else:
            giorni = (self.al - self.dal).days + 1
            self.riepilogo.config(
                text=f"dal {self.dal:%d/%m/%Y} al {self.al:%d/%m/%Y} · "
                     f"{giorni} giorn{'o' if giorni == 1 else 'i'}")

    def _conferma(self):
        self.risultato = ((self.dal, self.al) if self.intervallo
                          else self.dal)
        self.destroy()

    @staticmethod
    def chiedi_intervallo(padre, titolo, dal, al):
        return Calendario(padre, titolo, dal, al, intervallo=True).concludi()


class SceltaGiorno:
    """Un giorno solo, dal calendario."""

    @staticmethod
    def chiedi(padre, titolo, iniziale):
        return Calendario(padre, titolo, iniziale).concludi()


class SceltaDipendente(Dialogo):
    """Come Scelta, ma scorre: i dipendenti possono essere piu' di quanti
    bottoni stanno su uno schermo da 1024x600."""

    def __init__(self, padre, nomi: dict[int, str]):
        super().__init__(padre, "Chi?")
        tk.Label(self, text="Di chi e' la timbratura?", bg=BG, fg=TESTO,
                 font=F_TITOLO).pack(pady=(18, 10), padx=30)
        alto = min(440, self.winfo_screenheight() - 260)
        lista = ListaScorrevole(self)
        lista.tela.config(height=alto, width=460)
        lista.pack(fill="both", expand=True, padx=30)
        for codice, nome in sorted(nomi.items(), key=lambda x: x[1].lower()):
            b = Bottone(lista.interno, f"{nome}   ·   {codice}",
                        lambda c=codice: self._scegli(c), font=F_NORMALE,
                        altezza=60)
            b.pack(fill="x", pady=3)
            lista.segui_trascinamento(b)
        Bottone(self, "Annulla", self.destroy, altezza=60,
                larghezza=200).pack(pady=(14, 20))

    def _scegli(self, codice):
        self.risultato = codice
        self.destroy()

    @staticmethod
    def chiedi(padre, nomi):
        return SceltaDipendente(padre, nomi).concludi()


class SchermataTimbrature(Schermata):
    titolo = "Timbrature"
    PER_PAGINA = 40
    RETTIFICA = ("Le correzioni cambiano le ore che poi si pagano: "
                 "guardarle e' libero, correggerle no.")

    # Le timbrature del terminale e quelle aggiunte a mano, in un elenco
    # solo. Il grezzo non si tocca: correggere un'ora vuol dire annullare
    # la timbratura del terminale (che resta in archivio, barrata) e
    # aggiungerne una a mano con l'ora giusta e il motivo.
    ELENCO = """
        SELECT 'terminale', source_event_id, employee_code,
               occurred_at_local, metodo, event_type, NULL,
               source_event_id IN (SELECT evento_annullato FROM rettifiche
                                   WHERE tipo = 'annullamento'), NULL
          FROM raw_events
        UNION ALL
        SELECT 'mano', 'rettifica:' || id, employee_code, quando_locale,
               'a mano', NULL, verso, 0, motivo
          FROM rettifiche WHERE tipo = 'aggiunta'
    """

    def costruisci(self):
        self.pagina = 0
        barra = self.intestazione("Timbrature", [
            ("+ Aggiungi timbratura", self._aggiungi, BLU)])
        self.etichetta_pagina = tk.Label(barra, text="", bg=BG, fg=TESTO_TENUE,
                                         font=F_NORMALE)
        self.etichetta_pagina.pack(side="right", padx=16)
        tk.Label(self, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO, anchor="w",
                 justify="left", wraplength=900,
                 text="Tocca una timbratura per correggerla. Quella del "
                      "terminale non si cancella mai: si annulla e resta "
                      "in archivio, barrata, accanto alla correzione."
                 ).pack(fill="x", padx=24, pady=(0, 8))
        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=16)
        piede = tk.Frame(self, bg=BG)
        piede.pack(fill="x", padx=24, pady=14)
        Bottone(piede, "◀  Precedenti", self._precedente,
                larghezza=220).pack(side="left")
        Bottone(piede, "Successive  ▶", self._successiva,
                larghezza=220).pack(side="right")

    def _precedente(self):
        if self.pagina > 0:
            self.pagina -= 1
            self.entra()

    def _successiva(self):
        self.pagina += 1
        self.entra()

    def entra(self):
        self.lista.svuota()
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            self.nomi = nomi_dipendenti(db)
            totale = db.execute(
                f"SELECT COUNT(*) FROM ({self.ELENCO})").fetchone()[0]
            righe = list(db.execute(
                f"{self.ELENCO} ORDER BY 4 DESC LIMIT ? OFFSET ?",
                (self.PER_PAGINA, self.pagina * self.PER_PAGINA)))
        finally:
            db.close()

        if not righe and self.pagina > 0:
            self.pagina -= 1
            return self.entra()

        pagine = max(1, -(-totale // self.PER_PAGINA))
        self.etichetta_pagina.config(
            text=f"{totale} in archivio · pagina {self.pagina + 1} di {pagine}")

        if not righe:
            tk.Label(self.lista.interno, text="Archivio vuoto.", bg=BG,
                     fg=TESTO_TENUE, font=F_GRANDE).pack(pady=50)
            return

        stati = self.app.stati_ta or {}
        for voce in righe:
            origine, evento, codice, quando, metodo, stato, verso, \
                annullata, motivo = voce
            if annullata:
                colore, accanto = TESTO_TENUE, "annullata"
            elif origine == "mano":
                colore, accanto = BLU, (verso or "?").upper()
            else:
                colore, accanto = TESTO, stati.get(stato, f"stato {stato}")
            riga = tk.Frame(self.lista.interno, bg=CARD)
            riga.pack(fill="x", pady=2, padx=8, ipady=10)
            pezzi = [
                tk.Label(riga, text=quando[:16], bg=CARD, fg=colore,
                         font=F_MONO + (("overstrike",) if annullata else ()),
                         width=17, anchor="w"),
                tk.Label(riga, text=self.nomi.get(codice, f"Utente {codice}")
                         + (f"   ·   {motivo}" if motivo else ""), bg=CARD,
                         fg=colore, font=F_NORMALE, anchor="w"),
                tk.Label(riga, text=accanto, bg=CARD, fg=colore,
                         font=F_PICCOLO, width=9),
                tk.Label(riga, text=metodo, bg=CARD, fg=TESTO_TENUE,
                         font=F_PICCOLO, width=10),
            ]
            pezzi[0].pack(side="left", padx=(14, 8))
            pezzi[2].pack(side="right")
            pezzi[3].pack(side="right", padx=8)
            pezzi[1].pack(side="left", fill="x", expand=True)
            self.lista.segui_trascinamento(riga)
            for w in [riga, *pezzi]:
                w.bind("<ButtonPress-1>", self._premuto, add="+")
                w.bind("<ButtonRelease-1>",
                       lambda e, v=voce: self._tocca(e, v), add="+")

    # -- correzioni --
    def _premuto(self, evento):
        self._y_premuto = evento.y_root

    def _tocca(self, evento, voce):
        # Un trascinamento per scorrere l'elenco non e' un tocco.
        if abs(evento.y_root - getattr(self, "_y_premuto", evento.y_root)) > 12:
            return
        origine, ev, codice, quando, _metodo, _stato, verso, annullata, _ = voce
        quando = dt.datetime.fromisoformat(quando)
        chi = self.nomi.get(codice, f"Utente {codice}")
        titolo = f"{chi}, {quando:%d/%m %H:%M}"
        if origine == "mano":
            scelta = Scelta.chiedi(self, titolo, [
                ("Cambia l'ora", "ora"), ("Togli questa timbratura", "togli")],
                "Questa timbratura e' stata aggiunta a mano.")
        elif annullata:
            scelta = Scelta.chiedi(self, titolo, [
                ("Rimettila nel conteggio", "ripristina")],
                "Questa timbratura del terminale e' annullata: non conta "
                "nelle ore.")
        else:
            scelta = Scelta.chiedi(self, titolo, [
                ("Correggi l'ora", "ora"), ("Annullala (non contarla)",
                                            "annulla")],
                "Il dato del terminale resta in archivio in ogni caso.")
        if not scelta or not self.app.sbloccata(self, self.RETTIFICA):
            return

        if scelta == "ripristina":
            db = apri_archivio(self.app.cfg["archivio"])
            try:
                presenze.togli_annullamento(db, ev)
            finally:
                db.close()
            return self._fatto()

        if scelta == "ora":
            ora = SceltaOra.chiedi(self, "Ora giusta", quando.time())
            if ora is None:
                return
            nuovo_verso = Scelta.chiedi(self, "Entrata o uscita?", [
                ("Entrata", "entrata"), ("Uscita", "uscita")])
            if nuovo_verso is None:
                return
        motivo = self._motivo("Perche' la correggi?")
        if not motivo:
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            if origine == "mano":
                presenze.togli_aggiunta(db, int(ev.split(":")[1]))
            else:
                presenze.annulla_timbratura(db, codice, ev, motivo,
                                            self.app.cfg["operatore"])
            if scelta == "ora":
                presenze.aggiungi_timbratura(
                    db, codice, dt.datetime.combine(quando.date(), ora),
                    nuovo_verso, motivo, self.app.cfg["operatore"])
        finally:
            db.close()
        self._fatto()

    def _aggiungi(self):
        if not self.app.sbloccata(self, self.RETTIFICA):
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            nomi = nomi_dipendenti(db)
        finally:
            db.close()
        for u in self.app.utenti or []:
            nomi.setdefault(u.user_id, u.nome or f"Utente {u.user_id}")
        if not nomi:
            Avviso.mostra(self, "Nessun dipendente",
                          "Prima si crea il dipendente, da Dipendenti.",
                          GIALLO)
            return
        codice = SceltaDipendente.chiedi(self, nomi)
        if codice is None:
            return
        oggi = presenze.giorno_operativo(dt.datetime.now(), self.app.regole)
        giorno = SceltaGiorno.chiedi(self, "Che giorno?", oggi)
        if giorno is None:
            return
        ora = SceltaOra.chiedi(self, "A che ora?")
        if ora is None:
            return
        verso = Scelta.chiedi(self, "Entrata o uscita?", [
            ("Entrata", "entrata"), ("Uscita", "uscita")])
        if verso is None:
            return
        motivo = self._motivo("Perche' la aggiungi?")
        if not motivo:
            return
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            presenze.aggiungi_timbratura(
                db, codice, dt.datetime.combine(giorno, ora), verso, motivo,
                self.app.cfg["operatore"])
        finally:
            db.close()
        self._fatto()

    def _motivo(self, titolo):
        motivo = TastieraTouch.chiedi(self, titolo)
        if not motivo:
            Avviso.mostra(self, "Serve il motivo",
                          "Ogni correzione deve restare spiegata: senza motivo "
                          "non si sa piu' perche' quel giorno e' cambiato.",
                          GIALLO)
        return motivo

    def _fatto(self):
        self.entra()


class SchermataDipendenti(Schermata):
    titolo = "Dipendenti"

    def costruisci(self):
        self.intestazione("Dipendenti", [
            ("Nuovo", self._nuovo, VERDE),
            ("Rileggi", self.app.scarica_adesso, BLU),
        ])
        tk.Label(self, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO, anchor="w",
                 wraplength=900, justify="left",
                 text="Nome, tessera e PIN si scrivono da qui, direttamente "
                      "sul terminale; la tessera puo' leggerla il lettore. "
                      "Solo le impronte vanno iscritte sul dispositivo, e il "
                      "permesso di amministratore si cambia dal suo menu."
                 ).pack(fill="x", padx=24, pady=(0, 10))
        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def entra(self):
        self.lista.svuota()
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            salvati = {r[0]: {"nome": r[1], "attivo": r[3]} for r in db.execute(
                "SELECT employee_code, nome, badge, attivo FROM dipendenti")}
        finally:
            db.close()

        sul_terminale = {u.user_id: u for u in (self.app.utenti or [])}
        if not sul_terminale and not salvati:
            tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_GRANDE,
                     justify="center",
                     text="Nessun dipendente.\n\nPremi «Nuovo» per crearne uno,\n"
                          "oppure iscrivi un badge sul terminale e premi "
                          "«Rileggi».").pack(pady=50)
            return

        for codice in sorted(set(salvati) | set(sul_terminale)):
            u = sul_terminale.get(codice)
            info = salvati.get(codice, {})
            nome = info.get("nome") or (u.nome if u and u.nome else "")
            sparito = u is None
            # Chi e' stato eliminato di proposito e non e' piu' sul terminale
            # non e' un guasto da segnalare: e' una persona che non lavora
            # piu' qui. Le sue timbrature restano in archivio, la sua riga no.
            if sparito and info and not info.get("attivo", 1):
                continue

            riquadro = tk.Frame(self.lista.interno, bg=CARD)
            riquadro.pack(fill="x", pady=4, padx=8, ipady=12)
            tk.Frame(riquadro, bg=TESTO_TENUE if sparito else VERDE,
                     width=8).pack(side="left", fill="y")
            testi = tk.Frame(riquadro, bg=CARD)
            testi.pack(side="left", fill="both", expand=True, padx=16)
            tk.Label(testi, text=nome or "— senza nome —", bg=CARD,
                     fg=TESTO if nome else GIALLO, font=F_GRANDE,
                     anchor="w").pack(fill="x")
            pezzi = [f"ID {codice}"]
            if u:
                pezzi.append(f"tessera {u.badge}" if u.badge else "nessuna tessera")
                if u.impronte:
                    pezzi.append(f"{u.impronte} impronte")
                if u.ha_password:
                    pezzi.append("password")
                if u.amministratore:
                    pezzi.append("amministratore")
            else:
                pezzi.append("non piu' sul terminale")
            tk.Label(testi, text=" · ".join(pezzi), bg=CARD, fg=TESTO_TENUE,
                     font=F_PICCOLO, anchor="w").pack(fill="x")
            if u is not None:
                Bottone(riquadro, "modifica",
                        lambda uu=u, nn=nome: self._modifica(uu, nn),
                        font=F_PICCOLO, altezza=48,
                        larghezza=130).pack(side="right", padx=16)
            self.lista.segui_trascinamento(testi)

    def _modifica(self, utente, nome):
        if ModuloUtente(self, self.app, utente, nome).concludi():
            self.entra()

    def _nuovo(self):
        if not self.app.utenti and not self.app.collegato:
            Avviso.mostra(self, "Terminale non raggiungibile",
                          "Per creare un dipendente serve il collegamento: "
                          "l'anagrafica vive sul terminale.", GIALLO)
            return
        if ModuloUtente(self, self.app, None).concludi():
            self.entra()


class SchermataImpostazioni(Schermata):
    titolo = "Impostazioni"

    def costruisci(self):
        self.intestazione("Impostazioni")
        self.lista = ListaScorrevole(self)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _sezione(self, testo):
        tk.Label(self.lista.interno, text=testo, bg=BG, fg=BLU, font=F_NORMALE,
                 anchor="w").pack(fill="x", padx=8, pady=(16, 6))

    def _voce(self, etichetta, valore, comando=None, nota=None):
        f = tk.Frame(self.lista.interno, bg=CARD, height=ALTEZZA_TOCCO)
        f.pack(fill="x", pady=2, padx=8)
        f.pack_propagate(False)
        # Bottone per primo e riga toccabile: vedi ModuloUtente._riga.
        if comando:
            Bottone(f, "cambia", comando, font=F_PICCOLO, altezza=44,
                    larghezza=110).pack(side="right", padx=10)
        nome = tk.Label(f, text=etichetta, bg=CARD, fg=TESTO_TENUE,
                        font=F_NORMALE, width=28, anchor="w")
        nome.pack(side="left", padx=16)
        testo = tk.Label(f, text=str(valore), bg=CARD, fg=TESTO,
                         font=F_NORMALE, anchor="w")
        testo.pack(side="left", fill="x", expand=True)
        if comando:
            for w in (f, nome, testo):
                w.bind("<Button-1>", lambda _e: comando())
        if nota:
            tk.Label(self.lista.interno, text=nota, bg=BG, fg=TESTO_TENUE,
                     font=F_PICCOLO, anchor="w", wraplength=880,
                     justify="left").pack(fill="x", padx=20, pady=(0, 4))

    def entra(self):
        self.lista.svuota()
        cfg, r = self.app.cfg, self.app.regole
        d = self.app.dati_terminale

        self._sezione("COLLEGAMENTO")
        self._voce("Indirizzo del terminale", f"{cfg['terminale_ip']}:{cfg['terminale_porta']}",
                   self._cambia_ip)
        self._voce("Minuti fra uno scarico e l'altro", cfg["minuti_fra_scarichi"],
                   self._cambia_intervallo)
        interruttore = Interruttore(
            self.lista.interno, "Riallinea l'orologio del terminale",
            cfg["allinea_orologio"], self._cambia_orologio)
        interruttore.pack(fill="x", pady=2, padx=8)
        tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                 anchor="w", wraplength=880, justify="left",
                 text="Su questo esemplare l'orologio perde una manciata di "
                      "secondi al minuto dopo un riavvio: conviene lasciarlo "
                      "acceso, perche' l'ora la mette il terminale e se sbaglia "
                      "sbagliano tutte le timbrature."
                 ).pack(fill="x", padx=20, pady=(0, 4))

        self._sezione("IL TERMINALE")
        if d.get("errore_identita"):
            self._voce("Non riesco a leggere il dispositivo",
                       d["errore_identita"],
                       nota="Modello, seriale e capienza restano vuoti finche' "
                            "il terminale non risponde a queste domande. Le "
                            "timbrature possono arrivare lo stesso.")
        self._voce("Modello", d.get("modello", "?"))
        self._voce("Numero di serie", d.get("seriale", "?"))
        self._voce("Firmware", d.get("firmware")
                   or (d.get("configurazione") or {}).get("firmware") or "?")
        self._voce("Orologio", d.get("orologio", "?"))
        c = d.get("conteggi") or {}
        if c:
            self._voce("In memoria", f"{c.get('timbrature', '?')} timbrature, "
                                     f"{c.get('utenti', '?')} utenti")
        cap = d.get("capacita") or {}
        if cap:
            self._voce("Capienza", f"{cap['utenti']} utenti, "
                                   f"{cap['timbrature']} timbrature")
        self._sezione("PARAMETRI DEL DISPOSITIVO")
        conf = d.get("configurazione")
        if not conf:
            tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                     anchor="w", text="Non ancora letti dal terminale."
                     ).pack(fill="x", padx=20, pady=4)
        else:
            self._voce("Volume", f"{conf['volume']} su 5"
                       + (" (muto)" if conf["volume"] == 0 else ""),
                       self._cambia_volume)
            self._voce("Va in sospensione dopo",
                       "mai" if not conf["sospensione_min"]
                       else f"{conf['sospensione_min']} minuti",
                       self._cambia_sospensione)
            self._voce("Formato dell'ora",
                       "12 ore (AM/PM)" if conf["ore_12"] else "24 ore",
                       self._cambia_formato)
            stati = self.app.stati_ta or {}
            self._voce("Stato predefinito",
                       stati.get(conf["stato_predefinito"],
                                 f"numero {conf['stato_predefinito']}"),
                       self._cambia_stato_predefinito,
                       "E' lo stato che il terminale assegna a chi passa il "
                       "badge senza premere nessun tasto.")
            self._voce("Etichette a display",
                       ", ".join(stati.values()) if stati else "nessuna",
                       self._rinomina_stati,
                       "Sono le scritte che il dipendente vede sul terminale "
                       "quando sceglie entrata o uscita.")
            c2 = d.get("configurazione2") or {}
            if c2:
                self._voce("Ignora ripetute entro",
                           "mai (registra ogni passata)"
                           if not c2["ignora_ripetute_min"]
                           else f"{c2['ignora_ripetute_min']} minuti",
                           self._cambia_ripetute,
                           "Se e' a zero il terminale registra anche il badge "
                           "passato due volte di fila. Alzandolo, i doppioni "
                           "spariscono alla fonte invece di doverli scartare "
                           "dopo.")
                self._voce("Correzione dell'orologio",
                           "nessuna" if not c2["correzione_orologio_s"]
                           else f"{c2['correzione_orologio_s']:+d} secondi al giorno",
                           self._cambia_correzione,
                           "Compensa la deriva dell'RTC direttamente sul "
                           "terminale, cosi' l'ora e' giusta anche quando "
                           "questo computer e' spento.")
                self._voce("Deriva misurata", self._testo_deriva(),
                           nota="Misurata da sola, confrontando l'orologio del "
                                "terminale col nostro a ogni scarico. Non "
                                "impostare la correzione a occhio: conviene "
                                "aspettare almeno un giorno di misure.")
                self._voce("Avviso memoria quasi piena",
                           "spento" if not c2["avviso_memoria"]
                           else f"sotto {c2['avviso_memoria']} timbrature libere",
                           self._cambia_avviso)
                self._voce("Spinge le timbrature in tempo reale",
                           "si" if c2["tempo_reale"] else "no",
                           self._cambia_tempo_reale,
                           "Da spenta, il terminale aspetta di essere "
                           "interrogato. Accesa, annuncia ogni timbratura "
                           "appena avviene.")
            self._voce("Lingua del terminale", f"codice {conf['lingua']}",
                       self._cambia_lingua,
                       "Il firmware restituisce un numero, e la tabella della "
                       "specifica non corrisponde a quello che il terminale "
                       "mostra davvero. Cambiala solo guardando lo schermo del "
                       "dispositivo, e segnati il codice di partenza.")

        self._sezione("REGOLE DEL LOCALE")
        self._voce("La giornata comincia alle", r.inizio_giornata,
                   self._cambia_inizio,
                   "Una timbratura prima di quest'ora conta sul giorno "
                   "precedente: e' cio' che tiene insieme i turni notturni.")
        self._voce("Entrata e uscita", {
            "automatico": "automatico (stati se coerenti, altrimenti alternanza)",
            "stati": "come li marca il terminale",
            "alternanza": "alternanza",
        }.get(r.verso, r.verso), self._cambia_verso)
        self._voce("Doppioni entro", f"{r.secondi_doppione} secondi",
                   self._cambia_doppioni)
        self._voce("Turno oltre il quale segnalare", f"{r.ore_massime_turno} ore",
                   self._cambia_massimo)
        self._voce("Arrotondamento",
                   "nessuno" if not r.arrotondamento_minuti
                   else f"{r.arrotondamento_minuti} minuti, "
                        f"per {r.arrotondamento_verso}",
                   self._cambia_arrotondamento,
                   "La direzione non e' un dettaglio tecnico: «su» favorisce il "
                   "dipendente, «giu» il datore. Va decisa dal titolare.")
        self._voce("Pausa tolta d'ufficio",
                   "nessuna" if not r.pausa_automatica_minuti
                   else f"{r.pausa_automatica_minuti} min oltre "
                        f"{r.pausa_oltre_ore} ore",
                   self._cambia_pausa)
        self._voce("Straordinario oltre", f"{r.minuti_ordinari // 60} ore",
                   self._cambia_ordinarie)
        self._voce("La settimana comincia di",
                   GIORNI[r.inizio_settimana % 7],
                   self._cambia_inizio_settimana,
                   "Vale per la vista Settimana delle Presenze e per la sua "
                   "esportazione.")

        self._sezione("COPIE DI SICUREZZA")
        elenco = copie.elenco(cfg["archivio"])
        if not elenco:
            self._voce("Ultima copia", "nessuna ancora")
        else:
            data, percorso, byte = elenco[0]
            giorni = (dt.date.today() - data).days
            quando = ("oggi" if giorni == 0 else "ieri" if giorni == 1
                      else f"{giorni} giorni fa")
            self._voce("Ultima copia", f"{data} ({quando}), {byte / 1024:.0f} KB")
            self._voce("Copie conservate", f"{len(elenco)} in {copie.cartella_copie(cfg['archivio'])}")
        tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                 anchor="w", wraplength=880, justify="left",
                 text="Una copia al giorno, in automatico, verificata subito "
                      "dopo averla fatta. Si tengono le ultime sette piu' la "
                      "prima di ogni mese. E comunque le timbrature restano "
                      "anche dentro al terminale: sono tre copie, non una."
                 ).pack(fill="x", padx=20, pady=(0, 6))
        Bottone(self.lista.interno, "Fai una copia adesso", self._copia_adesso,
                colore=BLU, colore_testo=BG).pack(fill="x", padx=8, pady=4)

        self._sezione("REPORT MENSILE VIA EMAIL")
        imp = posta.impostazioni(cfg)
        acceso = Interruttore(self.lista.interno,
                              "Manda il report tutti i mesi",
                              imp["attivo"], self._cambia_posta_attivo)
        acceso.pack(fill="x", pady=2, padx=8)
        tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                 anchor="w", wraplength=880, justify="left",
                 text="Arriva il riepilogo delle ore del mese appena chiuso, "
                      "col foglio da aprire in Excel allegato. Mittente e "
                      "destinatario possono essere la stessa casella."
                 ).pack(fill="x", padx=20, pady=(0, 4))
        self._voce("Casella di posta (provider)",
                   imp["server"] or "da scegliere",
                   self._scegli_provider)
        self._voce("Server SMTP", imp["server"] or "—", self._cambia_smtp_server)
        self._voce("Porta e sicurezza",
                   f"{imp['porta']} · {imp['sicurezza']}",
                   self._cambia_smtp_porta)
        self._voce("Utente", imp["utente"] or "—", self._cambia_smtp_utente)
        self._voce("Password", "••••••••" if imp["password"] else "—",
                   self._cambia_smtp_password,
                   "Sta nel file di configurazione, offuscata. Non e' una "
                   "cassaforte: chi apre questo programma la rilegge. Meglio "
                   "una password per app, o una casella dedicata.")
        self._voce("Mittente", imp["mittente"] or "—", self._cambia_mittente)
        self._voce("Destinatario", imp["destinatari"] or "—",
                   self._cambia_destinatari,
                   "Piu' d'uno si scrive separandoli con una virgola.")
        self._voce("Giorno di arrivo", f"il {imp['giorno']} del mese",
                   self._cambia_giorno_report,
                   "Se il mese e' piu' corto — il 31 a febbraio — arriva "
                   "l'ultimo giorno che c'e'.")
        self._voce("Ora", imp["ora"], self._cambia_ora_report)
        self._voce("Ultimo mese spedito", imp["ultimo_inviato"] or "nessuno")
        self._voce("Avvisa se il terminale tace",
                   "no" if not imp["allarme_giorni"]
                   else f"dopo {imp['allarme_giorni']} giorni",
                   self._cambia_allarme,
                   "Una mail quando il terminale non risponde da un po'. Le "
                   "timbrature non si perdono comunque, ma un cavo staccato "
                   "il 3 del mese si scopre il 31.")
        azioni_posta = tk.Frame(self.lista.interno, bg=BG)
        azioni_posta.pack(fill="x", padx=8, pady=4)
        Bottone(azioni_posta, "Manda una prova adesso", self._prova_posta,
                colore=BLU, colore_testo=BG).pack(fill="x", pady=3)
        Bottone(azioni_posta, "Manda adesso il report del mese scorso",
                self._report_adesso).pack(fill="x", pady=3)

        self._sezione("SICUREZZA")
        self._voce("PIN delle sezioni protette",
                   "personalizzato" if self.app.serratura.personalizzato()
                   else f"quello di fabbrica ({sicurezza.PIN_PREDEFINITO})",
                   self._cambia_pin,
                   "Serve per entrare in Dipendenti e in Impostazioni, e per "
                   "correggere una timbratura. Una volta dato, resta aperto "
                   f"{sicurezza.MINUTI_SBLOCCO} minuti.")
        Bottone(self.lista.interno, "Richiudi adesso", self._richiudi).pack(
            fill="x", padx=8, pady=4)

        self._sezione("PROGRAMMA")
        self._voce("Versione in uso", VERSIONE)
        self._voce("Ultima pubblicata",
                   self.app.ultima_versione or "non ancora controllata",
                   nota="Si controlla all'apertura e poi ogni sei ore. "
                        "Quando c'e' una versione nuova compare un bottone "
                        "verde in basso.")
        self._voce("Aggiornamento automatico all'apertura",
                   "acceso" if self.app.cfg.get("aggiorna_da_solo", True)
                   else "spento", self._cambia_aggiorna_da_solo,
                   "Acceso: aprendo TIMBRA, se c'e' una versione nuova si "
                   "aggiorna da sola (prima fa la copia dei dati). Se la "
                   "versione nuova non parte, torna da sola a quella di "
                   "prima e non ci riprova."
                   + (f" Scartata: la {aggiorna.scartata(CARTELLA_DATI)}."
                      if aggiorna.scartata(CARTELLA_DATI) else ""))
        Bottone(self.lista.interno, "Cerca aggiornamenti adesso",
                self._cerca_aggiornamenti).pack(fill="x", padx=8, pady=4)
        if self.app.c_e_aggiornamento():
            Bottone(self.lista.interno,
                    f"Aggiorna adesso alla {self.app.ultima_versione}",
                    self.app.aggiorna_programma, colore=VERDE,
                    colore_testo=BG).pack(fill="x", padx=8, pady=4)

        self._sezione("MANUTENZIONE")
        azioni = tk.Frame(self.lista.interno, bg=BG)
        azioni.pack(fill="x", padx=8, pady=4)
        Bottone(azioni, "Cerca il terminale in rete", self._cerca).pack(
            fill="x", pady=3)
        Bottone(azioni, "Allinea adesso l'orologio", self._allinea).pack(
            fill="x", pady=3)
        Bottone(azioni, "Svuota la memoria del terminale", self._svuota,
                colore=ROSSO, colore_testo=BG).pack(fill="x", pady=3)
        tk.Label(self.lista.interno, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                 anchor="w", wraplength=880, justify="left", pady=10,
                 text="Indirizzo IP, maschera e DHCP non si cambiano da qui: "
                      "questo firmware rifiuta il comando, sia via rete sia "
                      "via broadcast. Si toccano dal menu del terminale, "
                      "oppure con una prenotazione DHCP sul router."
                 ).pack(fill="x", padx=20, pady=(8, 20))

    # -- posta --
    def _salva_posta(self, modifiche: dict):
        """Scrive SOLO le chiavi cambiate, su una rilettura fresca.

        I dialoghi restano aperti minuti interi mentre si digita col dito.
        Ributtando dentro la fotografia presa prima di aprirli si cancellerebbe
        quello che lo scheduler ha scritto nel frattempo — per esempio "il
        report di agosto e' partito", che tornerebbe indietro e farebbe
        rispedire lo stesso mese al giro dopo.
        """
        fresche = posta.impostazioni(self.app.cfg)
        fresche.update(modifiche)
        self.app.cfg["posta"] = fresche
        self._salva_cfg()

    def _scegli_provider(self):
        imp = posta.impostazioni(self.app.cfg)
        scelta = Scelta.chiedi(
            self, "Che casella di posta usi?",
            [(nome, i) for i, (nome, _, _, _) in enumerate(posta.PROVIDER)]
            + [("Un altro server (a mano)", -1)],
            "Compila server, porta e sicurezza al posto tuo. Utente e "
            "password restano da mettere.")
        if scelta is None:
            return
        if scelta >= 0:
            _, server, porta, sic = posta.PROVIDER[scelta]
            modifiche = {"server": server, "porta": porta, "sicurezza": sic}
            if not imp["utente"]:
                modifiche["utente"] = imp["mittente"]
            self._salva_posta(modifiche)
            return
        self._cambia_smtp_server()

    def _cambia_smtp_server(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastieraTouch.chiedi(self, "Server SMTP", imp["server"])
        if v is not None:
            self._salva_posta({"server": v.strip().lower()})

    def _cambia_smtp_porta(self):
        imp = posta.impostazioni(self.app.cfg)
        sic = Scelta.chiedi(
            self, "Come si collega",
            [("SSL diretto (porta 465)", ("ssl", 465)),
             ("STARTTLS (porta 587)", ("starttls", 587)),
             ("In chiaro (porta 25)", ("nessuna", 25)),
             ("Porta a mano", "mano")],
            "Nel dubbio: SSL sulla 465. In chiaro solo su un server interno.")
        if sic is None:
            return                      # annullato
        if isinstance(sic, tuple):
            self._salva_posta({"sicurezza": sic[0], "porta": sic[1]})
            return
        v = TastierinoNumerico.chiedi(self, "Porta", str(imp["porta"]))
        if v and v.isdigit() and 0 < int(v) < 65536:
            self._salva_posta({"porta": int(v)})

    def _cambia_smtp_utente(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastieraTouch.chiedi(self, "Utente della casella", imp["utente"])
        if v is not None:
            self._salva_posta({"utente": v.strip()})

    def _cambia_smtp_password(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastieraTouch.chiedi(self, "Password della casella", "",
                                 mascherata=True)
        if v is None:
            return
        self._salva_posta({"password": sicurezza.offusca(v.strip())})

    def _cambia_mittente(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastieraTouch.chiedi(self, "Indirizzo che spedisce",
                                 imp["mittente"])
        if v is not None:
            modifiche = {"mittente": v.strip()}
            if not imp["destinatari"]:
                modifiche["destinatari"] = v.strip()
            self._salva_posta(modifiche)

    def _cambia_destinatari(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastieraTouch.chiedi(self, "Chi riceve il report",
                                 imp["destinatari"])
        if v is not None:
            self._salva_posta({"destinatari": v.strip()})

    def _cambia_giorno_report(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastierinoNumerico.chiedi(self, "Giorno del mese",
                                      str(imp["giorno"]),
                                      "Da 1 a 31.")
        if v and v.isdigit() and 1 <= int(v) <= 31:
            self._salva_posta({"giorno": int(v)})

    def _cambia_ora_report(self):
        imp = posta.impostazioni(self.app.cfg)
        try:
            ore, minuti = (int(x) for x in str(imp["ora"]).split(":")[:2])
            iniziale = dt.time(ore, minuti)
        except (AttributeError, TypeError, ValueError):
            iniziale = dt.time(8, 0)
        v = SceltaOra.chiedi(self, "A che ora", iniziale)
        if v is not None:
            self._salva_posta({"ora": f"{v.hour:02d}:{v.minute:02d}"})

    def _cambia_allarme(self):
        imp = posta.impostazioni(self.app.cfg)
        v = TastierinoNumerico.chiedi(
            self, "Dopo quanti giorni avvisare", str(imp["allarme_giorni"]),
            "Zero per non avvisare mai.")
        if v is not None and v.isdigit():
            self._salva_posta({"allarme_giorni": int(v)})

    def _cambia_posta_attivo(self, valore):
        imp = posta.impostazioni(self.app.cfg)
        if valore and not posta.configurata(imp):
            Avviso.mostra(self, "Manca qualcosa",
                          "Prima servono almeno il server, il mittente e il "
                          "destinatario.", GIALLO)
            return self.entra()
        self._salva_posta({"attivo": bool(valore)})

    def _prova_posta(self):
        imp = posta.impostazioni(self.app.cfg)
        if not posta.configurata(imp):
            Avviso.mostra(self, "Manca qualcosa",
                          "Servono almeno il server, il mittente e il "
                          "destinatario.", GIALLO)
            return
        adesso = dt.datetime.now()
        _, errore = Attesa.esegui(
            self, "Spedisco la prova...",
            lambda: posta.invia(
                imp, "Prova della gestione presenze",
                f"Se leggi questo messaggio la posta e' configurata bene.\n\n"
                f"Mandato il {adesso:%d/%m/%Y alle %H:%M} dal computer della "
                f"gestione presenze."))
        if errore:
            Avviso.errore(self, f"Non e' partita.\n\n{errore}")
            return
        Avviso.mostra(self, "Partita",
                      f"Controlla la casella {imp['destinatari']}. "
                      f"Se non arriva, guarda anche nella posta "
                      f"indesiderata.", VERDE)

    def _report_adesso(self):
        imp = posta.impostazioni(self.app.cfg)
        if not posta.configurata(imp):
            Avviso.mostra(self, "Manca qualcosa",
                          "Servono almeno il server, il mittente e il "
                          "destinatario.", GIALLO)
            return
        oggi = dt.date.today()
        anno, mese = (oggi.year - 1, 12) if oggi.month == 1 \
            else (oggi.year, oggi.month - 1)
        dal, al = posta.estremi(anno, mese)
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            nomi = nomi_dipendenti(db)
            elenco = presenze.giornate(db, self.app.regole, dal, al)
        finally:
            db.close()
        titolo = f"{MESI[mese]} {anno}"
        _, errore = Attesa.esegui(
            self, f"Spedisco {titolo}...",
            lambda: posta.invia(
                imp, f"Ore lavorate — {titolo}",
                posta.testo_semplice(elenco, nomi, titolo),
                posta.corpo_html(elenco, nomi, titolo, dal, al),
                [(f"ore-{posta.etichetta(anno, mese)}.csv",
                  presenze.byte_csv(elenco, nomi), "text/csv")]))
        if errore:
            Avviso.errore(self, f"Non e' partita.\n\n{errore}")
            return
        Avviso.mostra(self, "Partita",
                      f"{titolo}: {len(elenco)} giornate spedite a "
                      f"{imp['destinatari']}.\n\nQuesto invio a mano non conta "
                      f"come quello automatico: il report del mese arrivera' "
                      f"lo stesso al giorno stabilito.", VERDE)

    # -- sicurezza --
    def _cambia_pin(self):
        if not ChiediPin.chiedi(self, self.app.serratura, "Il PIN di adesso",
                                "Per cambiarlo, prima quello attuale."):
            return
        nuovo = TastierinoNumerico.chiedi(
            self, "Nuovo PIN", "",
            f"Da {sicurezza.CIFRE_MIN} a {sicurezza.CIFRE_MAX} cifre. "
            f"Se lo dimentichi si recupera col numero di serie del terminale.")
        if not nuovo:
            return
        ripetuto = TastierinoNumerico.chiedi(self, "Ripetilo", "")
        if ripetuto is None:
            return                      # annullato: non e' un errore
        if ripetuto != nuovo:
            Avviso.mostra(self, "Non coincidono",
                          "Il PIN non e' stato cambiato.", GIALLO)
            return
        try:
            self.app.serratura.cambia(nuovo)
        except ValueError as e:
            Avviso.mostra(self, "PIN non valido", str(e), GIALLO)
            return
        Avviso.mostra(self, "PIN cambiato",
                      "Da adesso si entra col nuovo.", VERDE)
        self.entra()

    def _richiudi(self):
        self.app.serratura.chiudi()
        self.app.mostra("Oggi")

    # -- modifiche alla configurazione --
    def _salva_cfg(self):
        salva_config(self.app.cfg)
        self.entra()

    def _salva_regole(self):
        self.app.regole.salva(FILE_REGOLE)
        self.entra()

    def _cambia_ip(self):
        v = TastieraTouch.chiedi(self, "Indirizzo del terminale",
                                 self.app.cfg["terminale_ip"])
        if v:
            self.app.cfg["terminale_ip"] = v.lower().strip()
            self._salva_cfg()
            self.app.scarica_adesso()

    def _cambia_intervallo(self):
        v = TastierinoNumerico.chiedi(self, "Minuti fra gli scarichi",
                                      str(self.app.cfg["minuti_fra_scarichi"]),
                                      "Minimo un minuto. Cinque va benissimo.")
        if v and v.isdigit() and int(v) >= 1:
            self.app.cfg["minuti_fra_scarichi"] = int(v)
            self._salva_cfg()
            # Altrimenti la modifica ha effetto al prossimo risveglio, che con
            # l'intervallo vecchio puo' essere fra un'ora.
            self.app.servizio.sveglia.set()

    def _cambia_orologio(self, valore):
        self.app.cfg["allinea_orologio"] = valore
        salva_config(self.app.cfg)

    def _cambia_inizio_settimana(self):
        v = Scelta.chiedi(self, "La settimana comincia di",
                          [(nome, n) for n, nome
                           in enumerate(GIORNI)])
        if v is not None:
            self.app.regole.inizio_settimana = v
            self._salva_regole()

    def _cambia_inizio(self):
        v = SceltaOra.chiedi(self, "La giornata comincia alle",
                             self.app.regole.ora_inizio)
        if v:
            self.app.regole.inizio_giornata = f"{v.hour:02d}:{v.minute:02d}"
            self._salva_regole()

    def _cambia_verso(self):
        v = Scelta.chiedi(
            self, "Come si capisce entrata e uscita",
            [("Automatico", "automatico"),
             ("Come li marca il terminale", "stati"),
             ("Alternanza: primo dentro, secondo fuori", "alternanza")],
            "Il terminale conosce gli stati IN e OUT, ma li registra solo se "
            "il dipendente preme il tasto prima di passare il badge. "
            "«Automatico» usa gli stati quando ci sono davvero.")
        if v:
            self.app.regole.verso = v
            self._salva_regole()

    def _cambia_doppioni(self):
        v = TastierinoNumerico.chiedi(self, "Doppioni entro quanti secondi",
                                      str(self.app.regole.secondi_doppione))
        if v and v.isdigit():
            self.app.regole.secondi_doppione = int(v)
            self._salva_regole()

    def _cambia_massimo(self):
        v = TastierinoNumerico.chiedi(self, "Ore oltre le quali segnalare",
                                      str(int(self.app.regole.ore_massime_turno)))
        if v and v.isdigit() and int(v) > 0:
            self.app.regole.ore_massime_turno = float(int(v))
            self._salva_regole()

    def _cambia_arrotondamento(self):
        passo = Scelta.chiedi(self, "Arrotondamento",
                              [("Nessuno", 0), ("5 minuti", 5),
                               ("10 minuti", 10), ("15 minuti", 15)])
        if passo is None:
            return
        self.app.regole.arrotondamento_minuti = passo
        if passo:
            verso = Scelta.chiedi(
                self, "In che direzione",
                [("Al piu' vicino", "vicino"), ("Sempre in su", "su"),
                 ("Sempre in giu", "giu")],
                "«Su» favorisce il dipendente, «giu» il datore di lavoro. "
                "Sceglierlo in modo consapevole, e metterlo per iscritto.")
            if verso:
                self.app.regole.arrotondamento_verso = verso
        self._salva_regole()

    def _cambia_pausa(self):
        v = TastierinoNumerico.chiedi(
            self, "Minuti di pausa tolti d'ufficio",
            str(self.app.regole.pausa_automatica_minuti),
            "Zero per non toglierne nessuna.")
        if v is None or not v.isdigit():
            return
        self.app.regole.pausa_automatica_minuti = int(v)
        if int(v):
            o = TastierinoNumerico.chiedi(self, "Solo oltre quante ore",
                                          str(int(self.app.regole.pausa_oltre_ore)))
            if o and o.isdigit():
                self.app.regole.pausa_oltre_ore = float(int(o))
        self._salva_regole()

    def _cambia_ordinarie(self):
        v = TastierinoNumerico.chiedi(self, "Ore ordinarie al giorno",
                                      str(self.app.regole.minuti_ordinari // 60))
        if v and v.isdigit():
            self.app.regole.minuti_ordinari = int(v) * 60
            self._salva_regole()

    # -- parametri del dispositivo --
    def _scrivi_dispositivo(self, testo, azione):
        esito, errore = Attesa.esegui(
            self, testo, lambda: self.app.con_terminale(azione))
        if errore:
            Avviso.errore(self, f"Il terminale ha rifiutato la modifica.\n\n{errore}")
            return False
        self.app.rileggi_configurazione()
        return True

    def _cambia_volume(self):
        v = Scelta.chiedi(self, "Volume del terminale",
                          [("Muto", 0)] + [(f"{n} su 5", n) for n in range(1, 6)],
                          "In una cucina rumorosa il 4 o il 5 sono d'obbligo: "
                          "se il dipendente non sente il bip, timbra due volte.")
        if v is not None:
            self._scrivi_dispositivo(
                "Cambio il volume...",
                lambda t: t.imposta_configurazione(volume=v))

    def _cambia_sospensione(self):
        v = TastierinoNumerico.chiedi(
            self, "Minuti prima della sospensione",
            str((self.app.dati_terminale.get("configurazione") or {})
                .get("sospensione_min", 10)),
            "Zero = non si sospende mai.")
        if v is not None and v.isdigit():
            self._scrivi_dispositivo(
                "Cambio la sospensione...",
                lambda t: t.imposta_configurazione(sospensione_min=int(v)))

    def _cambia_formato(self):
        v = Scelta.chiedi(self, "Formato dell'ora",
                          [("24 ore", False), ("12 ore con AM/PM", True)])
        if v is not None:
            self._scrivi_dispositivo(
                "Cambio il formato...",
                lambda t: t.imposta_configurazione(ore_12=v))

    def _cambia_stato_predefinito(self):
        stati = self.app.stati_ta or {0: "IN", 1: "OUT"}
        v = Scelta.chiedi(self, "Stato predefinito",
                          [(f"{n} — {testo}", n) for n, testo in stati.items()],
                          "Chi passa il badge senza premere nessun tasto viene "
                          "registrato con questo stato.")
        if v is not None:
            self._scrivi_dispositivo(
                "Cambio lo stato predefinito...",
                lambda t: t.imposta_configurazione(stato_predefinito=v))

    def _rinomina_stati(self):
        stati = dict(self.app.stati_ta or {0: "IN", 1: "OUT"})
        quale = Scelta.chiedi(
            self, "Quale etichetta cambiare",
            [(f"{n} — {testo}", n) for n, testo in stati.items()]
            + [("Rimetti IN e OUT", -2),
               ("Scrivi Entrata e Uscita", -1)])
        if quale is None:
            return
        if quale == -1:
            nuovi = {0: "Entrata", 1: "Uscita"}
        elif quale == -2:
            nuovi = {0: "IN", 1: "OUT"}
        else:
            testo = TastieraTouch.chiedi(self, f"Etichetta dello stato {quale}",
                                         stati.get(quale, ""))
            if not testo:
                return
            nuovi = {quale: testo[:10]}
        self._scrivi_dispositivo("Riscrivo le etichette...",
                                 lambda t: t.imposta_stati_ta(nuovi))

    def _cambia_ripetute(self):
        v = TastierinoNumerico.chiedi(
            self, "Ignora ripetute entro quanti minuti",
            str((self.app.dati_terminale.get("configurazione2") or {})
                .get("ignora_ripetute_min", 0)),
            "Zero = registra ogni passata di badge. Un valore basso, uno o due "
            "minuti, toglie i doppioni senza rischiare di perdere una "
            "timbratura vera.")
        if v is not None and v.isdigit():
            self._scrivi_dispositivo(
                "Cambio la soglia...",
                lambda t: t.imposta_configurazione2(ignora_ripetute_min=int(v)))

    def _testo_deriva(self):
        db = apri_archivio(self.app.cfg["archivio"])
        try:
            misura = deriva_orologio(db)
        finally:
            db.close()
        if misura is None:
            return "non ancora misurabile: servono piu' ore di osservazione"
        al_giorno, ore, campioni = misura
        return (f"{al_giorno:+.0f} secondi al giorno "
                f"({abs(al_giorno) / 86400 * 1e6:.0f} ppm) "
                f"su {ore:.1f} ore, {campioni} intervalli")

    def _cambia_correzione(self):
        v = Scelta.chiedi(
            self, "Correzione dell'orologio",
            [("Nessuna", 0), ("+5 secondi al giorno", 5),
             ("+15 secondi al giorno", 15), ("+30 secondi al giorno", 30),
             ("−5 secondi al giorno", -5), ("−15 secondi al giorno", -15),
             ("−30 secondi al giorno", -30)],
            "Se il terminale resta indietro, si compensa in piu'. Serve solo "
            "se questo computer non e' sempre acceso a riallinearlo.")
        if v is not None:
            self._scrivi_dispositivo(
                "Cambio la correzione...",
                lambda t: t.imposta_configurazione2(correzione_orologio_s=v))

    def _cambia_avviso(self):
        v = TastierinoNumerico.chiedi(
            self, "Avvisa sotto quante timbrature libere",
            str((self.app.dati_terminale.get("configurazione2") or {})
                .get("avviso_memoria", 1000)),
            "Zero per non avvisare. Massimo 5000.")
        if v is not None and v.isdigit():
            self._scrivi_dispositivo(
                "Cambio l'avviso...",
                lambda t: t.imposta_configurazione2(avviso_memoria=int(v)))

    def _cambia_tempo_reale(self):
        attuale = (self.app.dati_terminale.get("configurazione2") or {}).get(
            "tempo_reale", False)
        v = Scelta.chiedi(self, "Timbrature in tempo reale",
                          [("No, solo quando lo interroghiamo", False),
                           ("Si, le annuncia appena avvengono", True)],
                          f"Adesso e' {'acceso' if attuale else 'spento'}. "
                          f"Con lo scarico ogni pochi minuti non serve: e' "
                          f"utile se un domani si vuole un tabellone che si "
                          f"aggiorna all'istante.")
        if v is not None and v != attuale:
            self._scrivi_dispositivo(
                "Cambio la modalita'...",
                lambda t: t.imposta_configurazione2(tempo_reale=v))

    def _cambia_lingua(self):
        attuale = (self.app.dati_terminale.get("configurazione") or {}).get(
            "lingua", 0)
        opzioni = [(f"codice {n}" + (f" — da specifica {LINGUE_SPEC[n]}"
                                     if n in LINGUE_SPEC else ""), n)
                   for n in range(6)]
        v = Scelta.chiedi(
            self, "Lingua del terminale", opzioni,
            f"Adesso e' il codice {attuale}. I nomi accanto vengono dalla "
            f"specifica del 2019 e su questo firmware NON corrispondono: "
            f"vanno presi come tentativi. Cambia un codice alla volta "
            f"guardando lo schermo del terminale, e se peggiora rimetti "
            f"{attuale}.")
        if v is not None and v != attuale:
            self._scrivi_dispositivo(
                "Cambio la lingua...",
                lambda t: t.imposta_configurazione(lingua=v))

    # -- copie --
    def _cambia_aggiorna_da_solo(self):
        v = Scelta.chiedi(self, "Aggiornamento automatico all'apertura",
                          [("Acceso", True), ("Spento", False)])
        if v is not None:
            self.app.cfg["aggiorna_da_solo"] = v
            salva_config(self.app.cfg)
            self.entra()

    def _cerca_aggiornamenti(self):
        etichetta, errore = Attesa.esegui(
            self, "Guardo se c'e' una versione nuova...",
            aggiorna.ultima_disponibile)
        if errore:
            Avviso.errore(self, f"Non riesco a controllare: serve la "
                                f"connessione a internet.\n\n{errore}")
            return
        self.app.annuncia_versione(etichetta)
        if not aggiorna.installabile(CARTELLA):
            Avviso.mostra(self, "Copia di sviluppo",
                          f"Ultima pubblicata: {etichetta or 'nessuna'}. "
                          f"Questa copia gira dai sorgenti e non si aggiorna "
                          f"da qui.")
        elif not self.app.c_e_aggiornamento():
            Avviso.mostra(self, "Gia' aggiornato",
                          f"La {VERSIONE} e' l'ultima versione.", VERDE)

    def _copia_adesso(self):
        esito, errore = Attesa.esegui(
            self, "Copio l'archivio...",
            lambda: copie.esegui(self.app.cfg["archivio"]))
        if errore:
            Avviso.errore(self, f"La copia non e' riuscita.\n\n{errore}")
            return
        Avviso.mostra(
            self, "Copia fatta e verificata",
            f"{esito['timbrature']} timbrature copiate, "
            f"{esito['byte'] / 1024:.0f} KB.\n\n{esito['percorso']}\n\n"
            f"La copia e' stata riaperta e controllata: e' integra.", VERDE)
        self.entra()

    # -- manutenzione --
    def _cerca(self):
        esito, errore = Attesa.esegui(
            self, "Cerco il terminale...",
            lambda: anviz.cerca_udp(anviz.sorgenti_locali(), 4.0))
        if errore:
            Avviso.errore(self, str(errore))
            return
        if not esito:
            Avviso.mostra(self, "Nessuna risposta",
                          "Nessun terminale ha risposto alla ricerca.\n\n"
                          "Se e' rimasto senza indirizzo, per esempio dopo un "
                          "riavvio con il DHCP acceso, usa bootstrap_dhcp.py.",
                          GIALLO)
            return
        d = esito[0]
        if d["ip"] != self.app.cfg["terminale_ip"] and Conferma.chiedi(
                self, "Indirizzo diverso",
                f"Trovato {d['modello']} all'indirizzo {d['ip']}, ma qui e' "
                f"impostato {self.app.cfg['terminale_ip']}.\n\n"
                f"Uso il nuovo indirizzo?"):
            self.app.cfg["terminale_ip"] = d["ip"]
            salva_config(self.app.cfg)
            self.app.scarica_adesso()
        Avviso.mostra(self, "Terminale trovato",
                      f"{d['modello']} · seriale {d['seriale']}\n"
                      f"firmware {d['firmware']}\nMAC {d['mac']}\n"
                      f"indirizzo {d['ip']} porta {d['porta']}")
        self.entra()

    def _allinea(self):
        def lavoro():
            with LUCCHETTO_TERMINALE, anviz.Terminale(
                    self.app.cfg["terminale_ip"],
                    self.app.cfg["terminale_porta"], timeout=10) as t:
                prima = t.orologio()
                t.imposta_orologio()
                return prima, t.orologio()
        esito, errore = Attesa.esegui(self, "Allineo l'orologio...", lavoro)
        if errore:
            Avviso.errore(self, str(errore))
            return
        prima, dopo = esito
        Avviso.mostra(self, "Orologio allineato",
                      f"Era {prima:%H:%M:%S}, ora {dopo:%H:%M:%S}.")
        self.app.scarica_adesso()

    def _svuota(self):
        if not Conferma.chiedi(
                self, "Svuotare la memoria del terminale?",
                "Le timbrature vengono prima scaricate e messe in archivio, "
                "poi cancellate dal terminale.\n\nNon si perde nulla: "
                "l'archivio resta.", pericoloso=True):
            return

        def lavoro():
            with LUCCHETTO_TERMINALE, anviz.Terminale(
                    self.app.cfg["terminale_ip"],
                    self.app.cfg["terminale_porta"], timeout=15) as t:
                righe = list(t.timbrature())
                if righe:
                    db = apri_archivio(self.app.cfg["archivio"])
                    try:
                        # La stessa identita' che usa lo scheduler. Salvare
                        # con l'indirizzo IP darebbe una chiave diversa per lo
                        # stesso evento, l'INSERT OR IGNORE non scarterebbe
                        # niente, e ogni timbratura della storia entrerebbe in
                        # archivio una seconda volta.
                        anviz.salva(db, self.app.identita_dispositivo(), righe)
                    finally:
                        db.close()
                t.azzera_timbrature()
                return len(righe)

        esito, errore = Attesa.esegui(self, "Metto al sicuro e cancello...", lavoro)
        if errore:
            Avviso.errore(self, str(errore))
            return
        Avviso.mostra(self, "Fatto",
                      f"{esito} timbrature archiviate e cancellate dal terminale.")
        self.app.scarica_adesso()


# --- Applicazione --------------------------------------------------------------
SCHERMATE = (SchermataOggi, SchermataPresenze, SchermataTimbrature,
             SchermataDipendenti, SchermataImpostazioni)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # Il marchio mentre il programma si prepara. Aprire l'archivio,
        # calcolare le presenze e far partire lo scheduler prende qualche
        # istante: uno schermo vuoto in quel momento fa pensare che il doppio
        # clic non abbia funzionato, e qualcuno ne apre un secondo.
        # Prima di qualunque apertura: se l'installazione e' nata prima della
        # separazione, archivio e configurazione stanno ancora accanto al
        # codice e vanno portati in `dati`. Sta qui e non solo in main()
        # perche' anche i banchi di prova costruiscono App() direttamente, e
        # senza il trasloco troverebbero un archivio vuoto.
        prepara_cartella_dati()
        self.withdraw()
        splash = logo.Splash(self)
        splash.apri()                    # dissolvenza in entrata
        splash.scrivi("leggo la configurazione...")
        self.cfg = carica_config()
        if raddrizza_percorsi(self.cfg):
            salva_config(self.cfg)
        self.regole = presenze.Regole.carica(FILE_REGOLE)
        self.coda: queue.Queue = queue.Queue()
        self.utenti: list = []
        self.stati_ta: dict = {}
        self.dati_terminale: dict = {}
        self.collegato = False
        self.ultima_copia: dict | None = None
        self.ultima_versione: str | None = None   # l'ultima pubblicata
        self.esito_aggiornamento = aggiorna.ultimo_esito(CARTELLA_DATI)
        self.serratura = sicurezza.Serratura(self.cfg,
                                             lambda: salva_config(self.cfg))

        self.title(TITOLO_FINESTRA)
        self.configure(bg=BG)
        # Gli schermi dei registratori di cassa sono piccoli: 1024x768, a volte
        # 1024x600. Una misura minima fissa piu' grande dello schermo lascia i
        # bottoni in fondo fuori dalla finestra, irraggiungibili. Ci si adatta,
        # e sotto una certa taglia si parte direttamente a pieno schermo.
        schermo_l = self.winfo_screenwidth()
        schermo_a = self.winfo_screenheight()
        self.geometry(f"{min(1100, schermo_l)}x{min(760, schermo_a - 60)}")
        self.minsize(min(900, schermo_l), min(560, schermo_a - 60))
        if schermo_l <= 1024 or schermo_a <= 720:
            self.attributes("-fullscreen", True)
        self.bind("<F11>", self._schermo_intero)
        self.bind("<Escape>", lambda _: self.attributes("-fullscreen", False))
        self.protocol("WM_DELETE_WINDOW", self._chiudi)

        self._barra_sezioni()
        self._corpo()
        self._barra_stato()

        splash.scrivi("avvio la raccolta...")
        self.servizio = Servizio(self.cfg, self.coda)
        self.servizio.start()
        self.after(300, self._svuota_coda)
        self.mostra("Oggi")

        # Il marchio compie i suoi tre secondi e si sfuma via da solo. La
        # finestra vera si mostra subito sotto: quando la dissolvenza finisce
        # il programma e' gia' li', senza uno stacco.
        self.deiconify()
        self.lift()
        splash.congeda(self._dopo_avvio)

    def _dopo_avvio(self):
        """Finita la dissolvenza, la finestra vera va davvero davanti.

        Windows non porta in primo piano una finestra che si e' mostrata da
        sola mentre il fuoco era altrove: senza questa spinta il programma
        parte, funziona, e resta dietro al browser — sembra non essersi
        aperto. Il "sempre in primo piano" si accende e si spegne subito
        dopo, altrimenti resterebbe sopra a tutto per sempre.
        """
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except tk.TclError:
            pass
        if guasto_configurazione:
            self._avvisa_configurazione()
        if self.esito_aggiornamento:
            riuscito = self.esito_aggiornamento.endswith(" aggiornato")
            Avviso.mostra(
                self, "Aggiornamento fatto" if riuscito
                else "Aggiornamento non riuscito",
                f"Versione in uso: {VERSIONE}.\n\n{self.esito_aggiornamento}",
                VERDE if riuscito else GIALLO)
        # Sono in piedi: lo si dice al sostituto, se c'e' un aggiornamento
        # in prova. Senza questo segno, fra un minuto e mezzo rimetterebbe
        # la versione di prima.
        aggiorna.segna_partenza(CARTELLA_DATI, VERSIONE)
        # Il primo controllo e' quello che puo' aggiornare da solo: subito,
        # prima che qualcuno cominci a lavorare. Qualche secondo di attesa
        # perche' appena acceso il computer la rete spesso non c'e' ancora.
        self.after(4_000, lambda: self._controlla_aggiornamenti(True))

    def _avvisa_configurazione(self):
        Avviso.mostra(
            self, "Configurazione illeggibile",
            f"Il file delle impostazioni non si leggeva "
            f"({guasto_configurazione}) e sono ripartito da quelle di "
            f"fabbrica: codice di sblocco 12345, report mensile spento.\n\n"
            f"Il file com'era e' stato messo da parte come "
            f"{os.path.basename(FILE_CONFIG_ROTTA)}, cosi' si puo' ancora "
            f"recuperare quello che c'era scritto.", GIALLO)

    # -- struttura --
    def _schermo_intero(self, _=None):
        self.attributes("-fullscreen", not self.attributes("-fullscreen"))

    def _chiudi(self):
        self.servizio.stop.set()
        self.servizio.sveglia.set()
        self.destroy()

    def _barra_sezioni(self):
        barra = tk.Frame(self, bg=CARD, height=ALTEZZA_TOCCO + 12)
        barra.pack(fill="x")
        barra.pack_propagate(False)
        self.bottoni_sezione = {}
        for classe in SCHERMATE:
            nome = classe.titolo
            b = Bottone(barra, nome, lambda n=nome: self.mostra(n), colore=CARD,
                        font=F_GRANDE, altezza=ALTEZZA_TOCCO + 12, larghezza=200)
            b.pack(side="left")
            self.bottoni_sezione[nome] = b
        Bottone(barra, "?", lambda: Guida.mostra(self), colore=CARD,
                font=F_TITOLO, altezza=ALTEZZA_TOCCO + 12,
                larghezza=90).pack(side="right")

    def _corpo(self):
        self.contenitore = tk.Frame(self, bg=BG)
        self.contenitore.pack(fill="both", expand=True)
        self.schermate = {c.titolo: c(self.contenitore, self) for c in SCHERMATE}
        self.attuale = None

    def _barra_stato(self):
        barra = tk.Frame(self, bg=CARD, height=46)
        barra.pack(fill="x", side="bottom")
        barra.pack_propagate(False)
        self.spia = tk.Label(barra, text="●", bg=CARD, fg=TESTO_TENUE,
                             font=("Segoe UI", 16))
        self.spia.pack(side="left", padx=(16, 8))
        self.stato = tk.Label(barra, text="Avvio...", bg=CARD, fg=TESTO_TENUE,
                              font=F_PICCOLO, anchor="w")
        self.stato.pack(side="left", fill="x", expand=True)
        tk.Label(barra, text="F11 schermo intero", bg=CARD, fg=TESTO_TENUE,
                 font=F_PICCOLO).pack(side="right", padx=16)
        # Compare solo quando c'e' una versione nuova da installare.
        self.bottone_aggiorna = Bottone(
            barra, "Aggiorna", self.aggiorna_programma, colore=VERDE,
            colore_testo=BG, font=F_PICCOLO, altezza=38, larghezza=260)

    def mostra(self, nome):
        if nome in SEZIONI_PROTETTE and not self.sbloccata():
            # Si resta dove si e': la sezione non si apre nemmeno per un
            # istante, cosi' non c'e' un lampo di contenuto da leggere.
            self._segna_sezione(self.attuale.titolo if self.attuale else "Oggi")
            return
        if self.attuale is not None:
            self.attuale.pack_forget()
        self._segna_sezione(nome)
        self.attuale = self.schermate[nome]
        self.attuale.pack(fill="both", expand=True)
        self.attuale.entra()

    def _segna_sezione(self, nome):
        for n, b in self.bottoni_sezione.items():
            scelto = n == nome
            b.tinta(CARD_CHIARA if scelto else CARD,
                    TESTO if scelto else TESTO_TENUE)

    def sbloccata(self, padre=None, spiegazione=None) -> bool:
        """Vero se il PIN e' gia' stato dato di recente, o se lo si da' adesso."""
        if self.serratura.aperta():
            return True
        return bool(ChiediPin.chiedi(padre or self, self.serratura,
                                     spiegazione=spiegazione))

    # -- terminale --
    def con_terminale(self, azione, timeout=10):
        with LUCCHETTO_TERMINALE, anviz.Terminale(
                self.cfg["terminale_ip"], self.cfg["terminale_porta"],
                timeout=timeout) as t:
            return azione(t)

    def identita_dispositivo(self) -> str:
        """La chiave con cui le timbrature entrano in archivio.

        Il seriale, non l'indirizzo: l'indirizzo cambia (DHCP, trasloco di
        rete) e cambierebbe la chiave degli eventi, facendo rientrare in
        archivio tutta la storia sotto una seconda identita'.
        """
        return (self.servizio.seriale or self.cfg.get("terminale_seriale")
                or self.cfg["terminale_ip"])

    def prossimo_id_libero(self) -> int:
        """Il primo numero libero, guardando ANCHE lo storico.

        Non basta guardare chi e' sul terminale adesso: un dipendente
        licenziato e cancellato lascia le sue timbrature in archivio col suo
        numero. Riusandolo, tutte le sue giornate passate prenderebbero il
        nome del nuovo assunto — nelle presenze, nel grafico e nel foglio che
        va alle paghe.
        """
        usati = {u.user_id for u in (self.utenti or [])}
        try:
            db = apri_archivio(self.cfg["archivio"])
            try:
                usati |= {r[0] for r in db.execute(
                    "SELECT employee_code FROM dipendenti "
                    "UNION SELECT DISTINCT employee_code FROM raw_events")}
            finally:
                db.close()
        except sqlite3.Error:
            pass                # senza archivio si ripiega sul solo terminale
        n = 1
        while n in usati:
            n += 1
        return n

    def scarica_adesso(self):
        self.stato.config(text="Interrogo il terminale...")
        self.spia.config(fg=GIALLO)
        threading.Thread(target=self.servizio.un_giro, daemon=True).start()

    def _svuota_coda(self):
        """Svuota la coda e SI RIPROGRAMMA SEMPRE.

        Se un'eccezione sfuggisse da qui, il riarmo non avverrebbe piu' e
        l'applicazione resterebbe viva ma sorda: finestra aperta, barra di
        stato ferma, nessun aggiornamento, e nessun errore visibile. Percio'
        il riarmo sta nel finally e ogni messaggio viene lavorato per conto
        suo: uno che esplode non trascina gli altri.
        """
        try:
            while True:
                try:
                    tipo, dati = self.coda.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._applica(tipo, dati)
                except Exception as e:                           # noqa: BLE001
                    self.spia.config(fg=GIALLO)
                    self.stato.config(
                        text=f"Errore nell'aggiornare la schermata: "
                             f"{type(e).__name__}: {e}")
        finally:
            self._sorveglia_serratura()
            self.after(500, self._svuota_coda)

    def _sorveglia_serratura(self):
        """Scaduti i quindici minuti si esce dalla sezione protetta.

        Controllare il PIN solo all'ingresso vuol dire che chi resta fermo su
        Impostazioni ce l'ha aperto per sempre: il tablet lasciato acceso in
        sala e' esattamente lo scenario da cui il PIN dovrebbe difendere.
        Qui si NAVIGA VIA e basta, non si apre nessuna finestra: aprire una
        modale dentro il drenaggio della coda bloccherebbe il riarmo e
        l'applicazione resterebbe viva ma sorda.
        """
        if (self.attuale is not None
                and self.attuale.titolo in SEZIONI_PROTETTE
                and not self.serratura.aperta()):
            self.mostra("Oggi")

    def _applica(self, tipo, dati):
        if tipo == "chiamata":
            funzione, args = dati
            funzione(*args)
            return
        if tipo == "copia":
            self.ultima_copia = dati
            self.stato.config(
                text=f"Copia di sicurezza fatta e verificata: "
                     f"{dati['timbrature']} timbrature in {dati['percorso']}")
            return
        if tipo == "copia_fallita":
            self.spia.config(fg=GIALLO)
            self.stato.config(text="Copia di sicurezza NON riuscita: "
                                   + dati["messaggio"])
            return
        if tipo == "salva_config":
            # La configurazione la scrive solo il thread dell'interfaccia:
            # due scritture in contemporanea sullo stesso file lascerebbero
            # un JSON troncato, e al riavvio si ripartirebbe dai valori di
            # fabbrica senza che nessuno se ne accorga.
            salva_config(self.cfg)
            return
        if tipo == "report":
            self.stato.config(text=f"Report di {dati['mese']} spedito a "
                                   f"{dati['a']} ({dati['quante']} giornate)")
            return
        if tipo == "allarme":
            self.spia.config(fg=ROSSO)
            self.stato.config(
                text=f"Il terminale non risponde da {dati['giorni']} giorni: "
                     f"mandato un avviso per email")
            return
        if tipo == "report_fallito":
            self.spia.config(fg=GIALLO)
            self.stato.config(text="Report mensile NON spedito: "
                                   + dati["messaggio"])
            return
        if tipo == "ok":
            self.collegato = True
            self.utenti = dati.get("utenti") or []
            self.stati_ta = dati.get("stati_ta") or {}
            self.dati_terminale["conteggi"] = dati.get("conteggi")
            if dati.get("orologio"):
                self.dati_terminale["orologio"] = \
                    dati["orologio"].strftime("%Y-%m-%d %H:%M:%S")
            self.spia.config(fg=VERDE)
            self.stato.config(
                text=f"Collegato · ultimo scarico alle "
                     f"{dati['quando']:%H:%M:%S} · {dati['nuove']} nuove")
            self._leggi_identita()
        else:
            self.collegato = False
            self.spia.config(fg=ROSSO)
            self.stato.config(
                text=f"Terminale non raggiungibile dalle "
                     f"{dati['quando']:%H:%M:%S} — {dati['messaggio']}")
        if self.attuale is not None:
            self.attuale.entra()

    def _leggi_identita(self):
        """Modello, seriale e capienza cambiano di rado: si leggono una volta."""
        if self.dati_terminale.get("seriale"):
            return
        # Due messaggi "ok" drenati nello stesso giro passerebbero entrambi la
        # guardia qui sopra, perche' il seriale arriva solo dopo, via coda: due
        # thread, due giri di comandi e due scansioni broadcast che si rubano
        # le risposte a vicenda.
        if getattr(self, "_identita_in_corso", False):
            return
        self._identita_in_corso = True

        def lavoro():
            info = {}
            try:
                with LUCCHETTO_TERMINALE, anviz.Terminale(
                        self.cfg["terminale_ip"], self.cfg["terminale_porta"],
                        timeout=8) as t:
                    info["modello"] = t.modello()
                    info["seriale"] = t.seriale()
                    info["capacita"] = t.capacita()
                    info["configurazione"] = t.configurazione()
                    info["configurazione2"] = t.configurazione2()
            except Exception as e:                               # noqa: BLE001
                # Non si tace: un dato che non arriva senza spiegazione manda
                # a caccia di fantasmi. Il motivo finisce a schermo.
                info["errore_identita"] = f"{type(e).__name__}: {e}"
            try:
                for d in anviz.cerca_udp(anviz.sorgenti_locali(), 3.0):
                    if d["ip"] == self.cfg["terminale_ip"]:
                        info["firmware"] = d["firmware"]
                        info["mac"] = d["mac"]
            except Exception:                                    # noqa: BLE001
                pass
            finally:
                self._identita_in_corso = False
            self._pianifica(self._aggiorna_dati, info)

        threading.Thread(target=lavoro, daemon=True).start()

    # -- aggiornamenti --
    def _controlla_aggiornamenti(self, all_apertura=False):
        """Guarda su GitHub se c'e' una versione nuova: all'apertura e poi
        ogni sei ore.

        In sottofondo e in silenzio: senza rete non succede niente e si
        riprova al giro dopo. Se c'e' qualcosa compare il bottone verde; al
        controllo dell'apertura, se l'interruttore e' acceso, si aggiorna
        anche da solo (vedi aggiorna.py per il ritorno indietro).
        """
        def lavoro():
            try:
                etichetta = aggiorna.ultima_disponibile()
            except Exception:                                    # noqa: BLE001
                return
            self._pianifica(self.annuncia_versione, etichetta, all_apertura)

        threading.Thread(target=lavoro, daemon=True).start()
        self.after(6 * 3600 * 1000, self._controlla_aggiornamenti)

    def c_e_aggiornamento(self) -> bool:
        return (aggiorna.installabile(CARTELLA)
                and aggiorna.piu_nuova(self.ultima_versione, VERSIONE))

    def annuncia_versione(self, etichetta, all_apertura=False):
        """Gira sul thread principale. Nessuna finestra qui: arriva dal
        drenaggio della coda, e una modale lo bloccherebbe — l'aggiornamento
        da solo parte con after(), fuori dal drenaggio."""
        self.ultima_versione = etichetta
        if self.c_e_aggiornamento():
            self.bottone_aggiorna.testo(f"Aggiorna alla {etichetta}")
            self.bottone_aggiorna.pack(side="right", padx=4, pady=4)
            if (all_apertura and self.cfg.get("aggiorna_da_solo", True)
                    and etichetta != aggiorna.scartata(CARTELLA_DATI)
                    and not self.grab_current()):
                self.after(200, lambda: self._esegui_aggiornamento(
                    etichetta, da_solo=True))
        else:
            self.bottone_aggiorna.pack_forget()
        if isinstance(self.attuale, SchermataImpostazioni):
            self.attuale.entra()

    def aggiorna_programma(self):
        etichetta = self.ultima_versione
        if not self.c_e_aggiornamento():
            return
        if not self.sbloccata(spiegazione="Per aggiornare il programma "
                                          "serve il PIN."):
            return
        if not Conferma.chiedi(
                self, f"Aggiornare alla {etichetta}?",
                f"Adesso c'e' la {VERSIONE}. TIMBRA si chiude e si riapre da "
                f"sola, in meno di un minuto.\n\nArchivio, impostazioni e "
                f"copie non si toccano. Il terminale intanto continua a "
                f"registrare: le timbrature arrivano alla riapertura."):
            return
        self._esegui_aggiornamento(etichetta)

    def _esegui_aggiornamento(self, etichetta, da_solo=False):
        if da_solo and (self.grab_current() or not self.c_e_aggiornamento()):
            return      # qualcuno ha gia' aperto una finestra: non si disturba
        # Prima una copia dell'archivio: costa un secondo, e se la versione
        # nuova avesse un difetto che tocca i dati c'e' da dove ripartire.
        _, errore = Attesa.esegui(self, "Copia di sicurezza...",
                                  lambda: copie.esegui(self.cfg["archivio"]))
        if errore:
            Avviso.errore(self, f"Non aggiorno: la copia di sicurezza non e' "
                                f"riuscita, e senza non si rischia.\n\n{errore}")
            return
        pronta, errore = Attesa.esegui(
            self, f"Aggiorno da solo alla {etichetta}..." if da_solo
            else f"Scarico la {etichetta}...",
            lambda: aggiorna.prepara(etichetta, CARTELLA_DATI))
        if errore:
            Avviso.errore(self, f"Aggiornamento non riuscito: il programma "
                                f"resta com'era.\n\n{errore}")
            return
        try:
            aggiorna.avvia_sostituzione(CARTELLA, pronta, CARTELLA_DATI,
                                        etichetta)
        except OSError as e:
            Avviso.errore(self, f"Aggiornamento non riuscito: il programma "
                                f"resta com'era.\n\n{e}")
            return
        self._chiudi()

    def _pianifica(self, funzione, *args):
        """Fa eseguire qualcosa al thread principale.

        NON si usa after() da un thread di lavoro: Tkinter non e' thread-safe e
        il callback viene registrato ma non eseguito mai — un guasto silenzioso
        che si manifesta come un dato che non arriva. Si passa invece dalla
        stessa coda dello scheduler, che il thread principale svuota.
        """
        self.coda.put(("chiamata", (funzione, args)))

    def rileggi_configurazione(self):
        """Dopo aver scritto un parametro si rilegge: non si da' per scontato
        che il terminale abbia fatto quello che gli si e' chiesto."""
        def lavoro():
            try:
                with LUCCHETTO_TERMINALE, anviz.Terminale(
                        self.cfg["terminale_ip"], self.cfg["terminale_porta"],
                        timeout=8) as t:
                    # Anche gli stati passano dalla coda: pubblicarli qui,
                    # dal thread di lavoro, li farebbe comparire prima del
                    # resto e un "ok" dello scheduler in arrivo con la
                    # fotografia vecchia li rimetterebbe come erano.
                    nuovi = {"configurazione": t.configurazione(),
                             "configurazione2": t.configurazione2(),
                             "stati_ta": t.stati_ta()}
            except Exception as e:                               # noqa: BLE001
                nuovi = {"errore_identita": f"{type(e).__name__}: {e}"}
            self._pianifica(self._aggiorna_dati, nuovi)

        threading.Thread(target=lavoro, daemon=True).start()

    def _aggiorna_dati(self, nuovi: dict):
        if "stati_ta" in nuovi:
            self.stati_ta = nuovi.pop("stati_ta")
        self.dati_terminale.update(nuovi)
        if isinstance(self.attuale, SchermataImpostazioni):
            self.attuale.entra()


def main() -> int:
    if not sicurezza.istanza_unica(TITOLO_FINESTRA):
        print("TIMBRA era gia' aperta: portata in primo piano.")
        return 0
    traslocati = prepara_cartella_dati()
    if traslocati:
        print("dati spostati in", CARTELLA_DATI, "->", ", ".join(traslocati))
    abilita_dpi()
    try:
        App().mainloop()
    finally:
        sicurezza.rilascia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
