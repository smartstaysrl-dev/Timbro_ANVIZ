# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""Collaudo del motore delle presenze sui casi che contano davvero:
turno notturno, turno spezzato, doppioni, timbrature mancanti, rettifiche.
"""
import datetime as dt
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import anviz
import presenze


def archivio():
    db = anviz.apri_db(":memory:")
    presenze.prepara(db)
    return db


def punzona(db, codice, quando_testo, stato=0, metodo="badge"):
    """Inserisce una timbratura come la scriverebbe davvero il collettore.

    L'istante UTC va calcolato dal fuso, non copiato dall'ora locale: se il
    banco di prova barasse su questo, i casi del cambio d'ora passerebbero
    sempre e non proverebbero nulla.
    """
    q = dt.datetime.fromisoformat(quando_testo)
    utc = presenze._istante(q)
    eid = f"{codice}-{q.isoformat()}"
    db.execute(
        "INSERT OR IGNORE INTO raw_events (source_event_id, device_serial, "
        "employee_code, occurred_at_local, occurred_at_utc, device_seconds, "
        "event_type_raw, event_type, metodo, work_code, raw_payload, imported_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, "prova", codice, q.isoformat(sep=" "), utc.isoformat(sep=" "),
         0, stato, stato, metodo, 0, "00", "2026-09-01"))
    db.commit()
    return eid


def sola(elenco, data):
    trovate = [g for g in elenco if g.data == dt.date.fromisoformat(data)]
    assert len(trovate) == 1, f"{data}: {len(trovate)} giornate invece di 1"
    return trovate[0]


esiti = []


def prova(nome):
    def decoratore(f):
        try:
            f()
            esiti.append((nome, None))
        except AssertionError as e:
            esiti.append((nome, str(e)))
        return f
    return decoratore


# --------------------------------------------------------------------------
@prova("turno semplice 9-17 = 8 ore")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 17:00:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 480, g.minuti_lavorati
    assert g.ore == "8:00", g.ore
    assert not g.anomalie, g.anomalie


@prova("turno spezzato pranzo+cena = 4 timbrature, 2 turni")
def _():
    db = archivio()
    for o in ("11:30", "15:00", "18:30", "23:00"):
        punzona(db, 1, f"2026-09-01 {o}:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert len(g.turni) == 2, len(g.turni)
    assert g.minuti_lavorati == 210 + 270, g.minuti_lavorati
    assert not g.anomalie, g.anomalie


@prova("serata che sfora l'inizio giornata: la notte resta intera")
def _():
    # Difetto trovato in revisione il 2/09: l'uscita alle 05:15 cadeva nel
    # giorno dopo, entrata e uscita finivano in due gruppi diversi, e nove ore
    # e un quarto valevano ZERO minuti con due anomalie. Con l'uscita alle
    # 04:45 invece funzionava: la soglia era l'unica difesa.
    db = archivio()
    punzona(db, 1, "2026-09-01 20:00:00")
    punzona(db, 1, "2026-09-02 05:15:00")
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    assert len(elenco) == 1, [(g.data, g.minuti_lavorati) for g in elenco]
    g = sola(elenco, "2026-09-01")
    assert g.minuti_lavorati == 555, g.minuti_lavorati
    assert not g.anomalie, g.anomalie


@prova("uscita dimenticata ieri: NON si ricuce col rientro di stamattina")
def _():
    # Il rovescio della medaglia: se si ricucisse qualunque cosa, l'entrata
    # delle 09:00 diventerebbe l'uscita della sera prima e la giornata di ieri
    # varrebbe tredici ore mai lavorate.
    db = archivio()
    punzona(db, 1, "2026-09-01 20:00:00")
    punzona(db, 1, "2026-09-02 09:00:00")
    punzona(db, 1, "2026-09-02 17:00:00")
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    ieri = sola(elenco, "2026-09-01")
    oggi = sola(elenco, "2026-09-02")
    assert ieri.minuti_lavorati == 0 and ieri.anomalie, (ieri.minuti_lavorati,
                                                         ieri.anomalie)
    assert oggi.minuti_lavorati == 480, oggi.minuti_lavorati


@prova("la coda di notte si puo' spegnere, e allora si torna al taglio secco")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 20:00:00")
    punzona(db, 1, "2026-09-02 05:15:00")
    elenco = presenze.giornate(db, presenze.Regole(minuti_coda_notte=0),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    assert len(elenco) == 2, [(g.data, g.minuti_lavorati) for g in elenco]


@prova("pausa d'ufficio: un turno monco in mezzo non vale come pausa presa")
def _():
    # Il buco fra le 12:00 e le 17:30 non e' una pausa di cinque ore: dentro
    # c'e' un'entrata senza uscita. Misurandolo come pausa, la trattenuta
    # sparirebbe del tutto.
    db = archivio()
    for ora in ("09:00:00", "12:00:00", "12:05:00", "17:30:00", "22:00:00"):
        punzona(db, 1, f"2026-09-01 {ora}")
    regole = presenze.Regole(pausa_automatica_minuti=30, pausa_oltre_ore=6.0)
    g = sola(presenze.giornate(db, regole, dt.date(2026, 9, 1),
                               dt.date(2026, 9, 1)), "2026-09-01")
    grezzi = sum(t.minuti for t in g.turni)
    # Pausa vera timbrata: cinque minuti. Se ne devono togliere altri 25.
    assert g.minuti_lavorati == grezzi - 25, (g.minuti_lavorati, grezzi)


@prova("turno notturno: uscita dopo mezzanotte resta sul giorno prima")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 22:30:00")
    punzona(db, 1, "2026-09-02 02:15:00")
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    g = sola(elenco, "2026-09-01")
    assert g.minuti_lavorati == 225, g.minuti_lavorati
    assert not g.anomalie, g.anomalie
    # Il 2 settembre non deve esistere: quelle ore sono gia' contate il giorno 1.
    assert not [x for x in elenco if x.data == dt.date(2026, 9, 2)], \
        "il turno notturno e' stato contato due volte"


@prova("doppione entro 90 secondi: scartato e segnalato")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 09:00:40")     # dito passato due volte
    punzona(db, 1, "2026-09-01 17:00:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 480, g.minuti_lavorati
    assert len(g.scartati) == 1, g.scartati
    assert any("doppione" in a for a in g.anomalie), g.anomalie


@prova("uscita dimenticata: ore a zero ma la presenza resta segnalata")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert len(g.turni) == 1 and not g.turni[0].completo
    assert any("manca l'uscita" in a for a in g.anomalie), g.anomalie
    assert g.prima_entrata is not None, "l'entrata deve restare visibile"


@prova("turno assurdo di 20 ore: tenuto ma marcato da verificare")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 08:00:00")
    punzona(db, 2, "2026-09-01 08:00:00")     # collega, per non restare soli
    punzona(db, 1, "2026-09-02 04:00:00")
    g = sola([x for x in presenze.giornate(db, presenze.Regole(),
                                           dt.date(2026, 9, 1), dt.date(2026, 9, 1))
              if x.employee_code == 1], "2026-09-01")
    assert g.minuti_lavorati == 20 * 60, g.minuti_lavorati
    assert any("dimenticata" in a for a in g.anomalie), g.anomalie


@prova("stati del terminale: IN/OUT vincono sull'alternanza")
def _():
    db = archivio()
    # Sequenza che con l'alternanza verrebbe letta male: due entrate di fila
    # perche' la prima uscita e' stata dimenticata, poi una uscita vera.
    punzona(db, 1, "2026-09-01 09:00:00", stato=0)   # IN
    punzona(db, 1, "2026-09-01 14:00:00", stato=0)   # IN di nuovo
    punzona(db, 1, "2026-09-01 18:00:00", stato=1)   # OUT
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.criterio == "stati del terminale", g.criterio
    assert g.minuti_lavorati == 240, g.minuti_lavorati   # 14:00 -> 18:00
    assert any("manca l'uscita delle 09:00" in a for a in g.anomalie), g.anomalie


@prova("tutti gli stati a zero: si ripiega sull'alternanza")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00", stato=0)
    punzona(db, 1, "2026-09-01 17:00:00", stato=0)
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.criterio == "alternanza", g.criterio
    assert g.minuti_lavorati == 480, g.minuti_lavorati


@prova("stato del terminale rimasto su OUT: gli stati non si prendono alla lettera")
def _():
    # Caso vero del 2 settembre 2026. A meta' mattina qualcuno ha commutato
    # il tasto IN/OUT del terminale e da li' in poi ogni timbratura, di
    # chiunque, e' uscita con stato 1. Letti alla lettera: un'entrata senza
    # uscita e un'uscita senza entrata. Letti per alternanza: due turni puliti.
    db = archivio()
    punzona(db, 1, "2026-09-02 09:11:28", stato=0)
    punzona(db, 1, "2026-09-02 09:53:53", stato=0)
    punzona(db, 1, "2026-09-02 10:46:47", stato=1)
    punzona(db, 1, "2026-09-02 13:14:14", stato=1)
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 2), dt.date(2026, 9, 2)),
             "2026-09-02")
    assert g.criterio.startswith("alternanza"), g.criterio
    assert "incoerenti" in g.criterio, g.criterio
    assert g.minuti_lavorati == 42 + 147, g.minuti_lavorati
    assert not g.anomalie, g.anomalie


@prova("stato rimasto su OUT, molte timbrature: niente raffica di 'manca l'entrata'")
def _():
    # Il collega dello stesso 2 settembre: una a stato 0 e poi sette a stato 1,
    # piu' un doppione. Prima della correzione: 1 minuto lavorato e sei
    # anomalie. Il doppione resta segnalato, perche' lo e' davvero.
    db = archivio()
    punzona(db, 5, "2026-09-02 09:53:20", stato=0)
    punzona(db, 5, "2026-09-02 09:54:58", stato=1, metodo="password")
    punzona(db, 5, "2026-09-02 10:46:17", stato=1)
    punzona(db, 5, "2026-09-02 10:50:40", stato=1)
    punzona(db, 5, "2026-09-02 11:38:25", stato=1)
    punzona(db, 5, "2026-09-02 11:53:05", stato=1)
    punzona(db, 5, "2026-09-02 11:59:11", stato=1)
    punzona(db, 5, "2026-09-02 13:14:08", stato=1, metodo="password")
    punzona(db, 5, "2026-09-02 13:14:39", stato=1)
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 2), dt.date(2026, 9, 2)),
             "2026-09-02")
    assert g.criterio.startswith("alternanza"), g.criterio
    assert len(g.turni) == 4 and all(t.completo for t in g.turni), g.turni
    assert g.minuti_lavorati == 1 + 4 + 14 + 74, g.minuti_lavorati
    assert not any("manca" in a for a in g.anomalie), g.anomalie
    assert any("doppione" in a for a in g.anomalie), g.anomalie


@prova("stati usati bene: a parita' di anomalie vincono sull'alternanza")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00", stato=0)
    punzona(db, 1, "2026-09-01 13:00:00", stato=1)
    punzona(db, 1, "2026-09-01 14:00:00", stato=0)
    punzona(db, 1, "2026-09-01 18:00:00", stato=1)
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.criterio == "stati del terminale", g.criterio
    assert g.minuti_lavorati == 480, g.minuti_lavorati
    assert not g.anomalie, g.anomalie


@prova("verso 'stati' scelto a mano: il programma non lo scavalca")
def _():
    # Se il titolare ha deciso che valgono gli stati, valgono anche quando
    # producono anomalie: e' lui a dover vedere il problema, non il
    # programma a nasconderglielo con una deduzione.
    db = archivio()
    punzona(db, 1, "2026-09-02 09:11:28", stato=0)
    punzona(db, 1, "2026-09-02 09:53:53", stato=0)
    punzona(db, 1, "2026-09-02 10:46:47", stato=1)
    punzona(db, 1, "2026-09-02 13:14:14", stato=1)
    g = sola(presenze.giornate(db, presenze.Regole(verso="stati"),
                               dt.date(2026, 9, 2), dt.date(2026, 9, 2)),
             "2026-09-02")
    assert g.criterio == "stati del terminale", g.criterio
    assert len([a for a in g.anomalie if "manca" in a]) == 2, g.anomalie


@prova("rettifica: l'uscita mancante si aggiunge senza toccare il grezzo")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    presenze.aggiungi_timbratura(db, 1, dt.datetime(2026, 9, 1, 17, 0),
                                 "uscita", "uscita dimenticata", "Nicola")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 480, g.minuti_lavorati
    assert not [a for a in g.anomalie if "manca" in a], g.anomalie
    grezzi = db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    assert grezzi == 1, "il grezzo e' stato alterato: non deve succedere mai"


@prova("annullamento: la timbratura sbagliata sparisce dal calcolo, non dal DB")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    sbagliata = punzona(db, 1, "2026-09-01 12:00:00")
    punzona(db, 1, "2026-09-01 17:00:00")
    presenze.annulla_timbratura(db, 1, sbagliata, "badge passato per errore",
                                "Nicola")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 480, g.minuti_lavorati
    assert db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 3


@prova("arrotondamento a 15 minuti nelle tre direzioni")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 17:07:00")                  # 8h07 = 487 minuti
    atteso = {"vicino": 480, "su": 495, "giu": 480}
    for verso, minuti in atteso.items():
        r = presenze.Regole(arrotondamento_minuti=15, arrotondamento_verso=verso)
        g = sola(presenze.giornate(db, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
                 "2026-09-01")
        assert g.minuti_lavorati == minuti, f"{verso}: {g.minuti_lavorati}"

    # 8h08 = 488: "vicino" deve salire, mentre "giu" resta sotto.
    db2 = archivio()
    punzona(db2, 1, "2026-09-01 09:00:00")
    punzona(db2, 1, "2026-09-01 17:08:00")
    r = presenze.Regole(arrotondamento_minuti=15, arrotondamento_verso="vicino")
    g = sola(presenze.giornate(db2, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 495, g.minuti_lavorati


@prova("pausa automatica oltre le 6 ore")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 17:00:00")
    r = presenze.Regole(pausa_automatica_minuti=30, pausa_oltre_ore=6)
    g = sola(presenze.giornate(db, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 450, g.minuti_lavorati


@prova("straordinario oltre le 8 ore")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 19:30:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
             "2026-09-01")
    assert g.minuti_lavorati == 630, g.minuti_lavorati
    assert g.minuti_straordinario == 150, g.minuti_straordinario


@prova("export CSV")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-01 09:00:00")
    punzona(db, 1, "2026-09-01 17:00:00")
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 1), dt.date(2026, 9, 1))
    percorso = pathlib.Path(tempfile.mkdtemp()) / "prova.csv"
    n = presenze.esporta_csv(str(percorso), elenco, {1: "Mario Rossi"})
    testo = percorso.read_text(encoding="utf-8-sig")
    assert n == 1 and "Mario Rossi" in testo and "8:00" in testo, testo


@prova("un annullamento si puo' togliere: la timbratura torna a contare")
def _():
    db = archivio()
    punzona(db, 1, "2026-09-03 09:00:00")
    punzona(db, 1, "2026-09-03 17:00:00")
    giorno = dt.date(2026, 9, 3)
    evento = db.execute("SELECT source_event_id FROM raw_events "
                        "ORDER BY occurred_at_local DESC").fetchone()[0]
    presenze.annulla_timbratura(db, 1, evento, "prova", "io")
    g = sola(presenze.giornate(db, presenze.Regole(), giorno, giorno),
             "2026-09-03")
    assert g.minuti_lavorati == 0, g.minuti_lavorati
    assert presenze.togli_annullamento(db, evento)
    assert not presenze.togli_annullamento(db, evento), "gia' tolto"
    g = sola(presenze.giornate(db, presenze.Regole(), giorno, giorno),
             "2026-09-03")
    assert g.minuti_lavorati == 480, g.minuti_lavorati


@prova("export CSV: pranzo e cena, tutte e quattro le timbrature")
def _():
    db = archivio()
    for ora in ("11:00", "15:00", "18:30", "23:30"):
        punzona(db, 1, f"2026-09-02 {ora}:00")
    punzona(db, 2, "2026-09-02 10:00:00")          # una sola, senza uscita
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 2), dt.date(2026, 9, 2))
    righe = presenze.testo_csv(elenco, {1: "Mario Rossi"}).splitlines()
    intestazione = righe[0].split(";")
    assert intestazione[3:9] == ["entrata_1", "uscita_1", "entrata_2",
                                 "uscita_2", "entrata_3", "uscita_3"],         intestazione
    mario = next(r.split(";") for r in righe if "Mario Rossi" in r)
    assert mario[3:7] == ["11:00", "15:00", "18:30", "23:30"], mario
    altro = next(r.split(";") for r in righe[1:] if "Mario" not in r)
    assert altro[3:9] == ["10:00", "", "", "", "", ""], altro
    assert len(altro) == len(intestazione)


@prova("cartellino Excel: riepilogo + un foglio per dipendente, ore come numeri")
def _():
    import re
    import zipfile
    db = archivio()
    for giorno in ("2026-09-07", "2026-09-08"):
        punzona(db, 1, f"{giorno} 09:00:00")
        punzona(db, 1, f"{giorno} 17:30:00")           # 8h30 al giorno
    punzona(db, 2, "2026-09-07 18:00:00")
    punzona(db, 2, "2026-09-07 23:00:00")              # 5h
    dal, al = dt.date(2026, 9, 7), dt.date(2026, 9, 9)
    elenco = presenze.giornate(db, presenze.Regole(), dal, al)
    percorso = pathlib.Path(tempfile.mkdtemp()) / "cartellino.xlsx"
    n = presenze.esporta_xlsx(str(percorso), elenco,
                              {1: "Mario Rossi", 2: "Anna Bianchi"}, dal, al)
    assert n == 2
    with zipfile.ZipFile(percorso) as z:
        libro = z.read("xl/workbook.xml").decode()
        fogli = re.findall(r'<sheet name="([^"]+)"', libro)
        assert fogli == ["Riepilogo", "Anna Bianchi", "Mario Rossi"], fogli
        riepilogo = z.read("xl/worksheets/sheet1.xml").decode()
        mario = z.read("xl/worksheets/sheet3.xml").decode()
    # 22 ore = 22/24 di giorno: il totale e' un numero che Excel somma.
    assert f"<v>{22 * 60 / 1440}</v>" in riepilogo, riepilogo[-600:]
    # Tutti i giorni del periodo, anche il 9 senza timbrature.
    for giorno in ("Lu 07/09/2026", "Ma 08/09/2026", "Me 09/09/2026"):
        assert giorno in mario, giorno
    assert f"<v>{17 * 60 / 1440}</v>" in mario           # monte ore di Mario
    assert "TOTALE" in mario


@prova("export CSV: monte ore per persona e per tutto il periodo")
def _():
    db = archivio()
    for giorno in ("2026-09-07", "2026-09-08"):
        punzona(db, 1, f"{giorno} 09:00:00")
        punzona(db, 1, f"{giorno} 17:30:00")           # 8h30 al giorno
    punzona(db, 2, "2026-09-07 18:00:00")
    punzona(db, 2, "2026-09-07 23:00:00")              # 5h
    elenco = presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 9, 7), dt.date(2026, 9, 8))
    righe = [r.split(";") for r in presenze.testo_csv(
        elenco, {1: "Mario Rossi", 2: "Anna Bianchi"}).splitlines()]
    colonne = righe[0]
    ore, minuti = colonne.index("ore"), colonne.index("minuti")
    totali = {r[0]: r for r in righe if r and r[0].startswith("TOTALE")}
    assert totali["TOTALE Mario Rossi"][ore] == "17:00", totali
    assert totali["TOTALE Anna Bianchi"][ore] == "5:00"
    assert totali["TOTALE PERIODO"][ore] == "22:00"
    assert totali["TOTALE PERIODO"][minuti] == "1320"
    assert "2 giorni lavorati" in totali["TOTALE Mario Rossi"][-1]
    assert all(len(r) == len(colonne) for r in totali.values())


@prova("ora legale, notte in cui si dorme un'ora in piu': il turno dura 7 ore")
def _():
    # 25 ottobre 2026: alle 03:00 CEST l'orologio torna alle 02:00 CET.
    # Sull'orologio a muro il turno sembra di 6 ore, in realta' e' di 7.
    db = archivio()
    punzona(db, 1, "2026-10-24 22:00:00")
    punzona(db, 1, "2026-10-25 04:00:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 10, 24), dt.date(2026, 10, 25)),
             "2026-10-24")
    assert g.minuti_lavorati == 420, f"{g.minuti_lavorati} invece di 420 (7 ore)"


@prova("ora legale, notte in cui si perde un'ora: il turno dura 5 ore")
def _():
    # 29 marzo 2026: alle 02:00 CET l'orologio salta alle 03:00 CEST.
    db = archivio()
    punzona(db, 1, "2026-03-28 22:00:00")
    punzona(db, 1, "2026-03-29 04:00:00")
    g = sola(presenze.giornate(db, presenze.Regole(),
                               dt.date(2026, 3, 28), dt.date(2026, 3, 29)),
             "2026-03-28")
    assert g.minuti_lavorati == 300, f"{g.minuti_lavorati} invece di 300 (5 ore)"


@prova("pausa d'ufficio: non si scala a chi l'ha gia' timbrata")
def _():
    r = presenze.Regole(pausa_automatica_minuti=30, pausa_oltre_ore=6)

    # A timbra la pausa: 4 + 4 ore di lavoro, un'ora di stacco gia' fuori conto.
    a = archivio()
    for o in ("09:00", "13:00", "14:00", "18:00"):
        punzona(a, 1, f"2026-09-01 {o}:00")
    ga = sola(presenze.giornate(a, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
              "2026-09-01")
    assert ga.minuti_lavorati == 480, \
        f"a chi timbra la pausa: {ga.minuti_lavorati} invece di 480"

    # B non la timbra: 9 ore filate, la mezz'ora va tolta d'ufficio.
    b = archivio()
    punzona(b, 2, "2026-09-01 09:00:00")
    punzona(b, 2, "2026-09-01 18:00:00")
    gb = sola(presenze.giornate(b, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
              "2026-09-01")
    assert gb.minuti_lavorati == 510, \
        f"a chi non la timbra: {gb.minuti_lavorati} invece di 510"

    # C ne timbra solo dieci minuti: se ne tolgono i venti mancanti.
    c = archivio()
    punzona(c, 3, "2026-09-01 09:00:00")
    punzona(c, 3, "2026-09-01 13:00:00")
    punzona(c, 3, "2026-09-01 13:10:00")
    punzona(c, 3, "2026-09-01 18:10:00")
    gc = sola(presenze.giornate(c, r, dt.date(2026, 9, 1), dt.date(2026, 9, 1)),
              "2026-09-01")
    assert gc.minuti_lavorati == 520, \
        f"a chi ne timbra dieci: {gc.minuti_lavorati} invece di 520"


@prova("deriva dell'orologio: stimata solo sugli intervalli liberi")
def _():
    import gestione
    percorso = pathlib.Path(tempfile.mkdtemp()) / "deriva.db"
    db = gestione.apri_archivio(str(percorso))

    def misura(quando, scarto, riallineato=0):
        db.execute("INSERT INTO importazioni (quando, esito, scarto_s, "
                   "riallineato) VALUES (?, 'ok', ?, ?)",
                   (quando, scarto, riallineato))

    assert gestione.deriva_orologio(db) is None, "senza dati non deve inventare"

    # Date relative a oggi: la stima guarda solo gli ultimi giorni, e una data
    # fissa prima o poi esce dalla finestra (e' successo il 22 ottobre 2026).
    ieri = (dt.date.today() - dt.timedelta(days=1)).isoformat()

    # Perde 1 secondo ogni ora: fanno 24 secondi al giorno.
    for n in range(6):
        misura(f"{ieri} {8+n:02d}:00:00", -float(n))
    db.commit()
    al_giorno, ore, campioni = gestione.deriva_orologio(db)
    assert abs(al_giorno + 24) < 0.5, al_giorno
    assert campioni == 5 and abs(ore - 5) < 0.1, (campioni, ore)

    # Un riallineamento in mezzo non deve essere scambiato per un salto
    # dell'orologio: quell'intervallo va saltato.
    db2 = gestione.apri_archivio(":memory:")
    def m2(quando, scarto, riallineato=0):
        db2.execute("INSERT INTO importazioni (quando, esito, scarto_s, "
                    "riallineato) VALUES (?, 'ok', ?, ?)",
                    (quando, scarto, riallineato))
    # Deriva costante di -1 s/ora; al quarto giro l'orologio viene rimesso,
    # quindi lo scarto torna a zero. Quel salto NON e' deriva.
    m2(f"{ieri} 08:00:00", 0.0)
    m2(f"{ieri} 09:00:00", -1.0)
    m2(f"{ieri} 10:00:00", -2.0)
    m2(f"{ieri} 11:00:00", -3.0, riallineato=1)    # misura, poi rimette l'ora
    m2(f"{ieri} 12:00:00", 0.0)                    # ripartito da zero
    m2(f"{ieri} 13:00:00", -1.0)
    db2.commit()
    al_giorno2, _, campioni2 = gestione.deriva_orologio(db2)
    assert campioni2 == 4, f"intervalli usati: {campioni2} invece di 4"
    assert abs(al_giorno2 + 24) < 0.5, al_giorno2
    # Senza saltare l'intervallo del riallineamento verrebbe -4 s/giorno
    # invece di -24: e' esattamente l'errore che questa prova sorveglia.
    db.close()
    db2.close()


@prova("cambio d'ora col terminale non riallineato: TIMBRA corregge da sola")
def _():
    import gestione
    db = gestione.apri_archivio(":memory:")

    def timbra(codice, segnata, scaricata):
        eid = punzona(db, codice, segnata)
        db.execute("UPDATE raw_events SET imported_at = ? WHERE "
                   "source_event_id = ?", (scaricata, eid))
        return eid

    def scarico(quando, scarto):
        db.execute("INSERT INTO importazioni (quando, esito, scarto_s, "
                   "riallineato) VALUES (?, 'ok', ?, 0)", (quando, scarto))

    # Notte del 25 ottobre 2026, programma spento. Il terminale resta in
    # ora legale: dopo le 02:00 vere (la seconda volta) segna un'ora in piu'.
    timbra(1, "2026-10-24 20:00:00", "2026-10-24T20:05:00+02:00")
    scarico("2026-10-24T20:05:01", 0.0)
    timbra(1, "2026-10-25 05:00:00", "2026-10-25T10:05:00+01:00")   # 04:00
    timbra(2, "2026-10-25 03:30:00", "2026-10-25T10:05:00+01:00")   # 02:30
    timbra(2, "2026-10-25 05:30:00", "2026-10-25T10:05:00+01:00")   # 04:30
    scarico("2026-10-25T10:05:01", 3600.0)          # misura e riallinea
    # Dopo il riallineamento l'ora e' giusta: questa non si tocca.
    timbra(3, "2026-10-25 11:00:00", "2026-10-25T11:05:00+01:00")
    timbra(3, "2026-10-25 15:00:00", "2026-10-25T15:05:00+01:00")
    scarico("2026-10-25T15:05:01", 0.0)
    db.commit()

    regole = presenze.Regole()
    adesso = dt.datetime(2026, 10, 25, 16, 0)
    def ore(codice):
        return sum(g.minuti_lavorati for g in presenze.giornate(
            db, regole, dt.date(2026, 10, 24), dt.date(2026, 10, 25))
            if g.employee_code == codice)

    assert ore(1) == 600, f"prima: {ore(1)} (il terminale conta 10 ore)"
    assert gestione.correggi_cambio_ora(db, regole, adesso=adesso) == 3
    # 20:00 ora legale -> 04:00 ora solare: 9 ore vere, una piu' del muro.
    assert ore(1) == 540, f"Mario: {ore(1)} invece di 540"
    # Entrata alle 02:30 della seconda volta, uscita alle 04:30: 2 ore. Col
    # terminale avanti l'uscita (05:30) cadeva perfino nel giorno dopo.
    assert ore(2) == 120, f"Luca: {ore(2)} invece di 120"
    assert db.execute("SELECT COUNT(*) FROM rettifiche WHERE quando_locale "
                      "= '2026-10-25 02:30:00+01:00'").fetchone()[0] == 1
    assert ore(3) == 240, f"dopo il riallineamento: {ore(3)} invece di 240"
    motivi = {r[0] for r in db.execute("SELECT motivo FROM rettifiche")}
    assert motivi == {gestione.MOTIVO_CAMBIO_ORA}, motivi
    # Rifarla non cambia nulla: ogni giro di scarico la richiama.
    assert gestione.correggi_cambio_ora(db, regole, adesso=adesso) == 0
    assert ore(1) == 540 and ore(2) == 120
    # Fuori dalla finestra del cambio d'ora non guarda nemmeno.
    assert gestione.correggi_cambio_ora(
        db, regole, adesso=dt.datetime(2026, 9, 1)) == 0
    db.close()


@prova("cambio d'ora: la deriva non scambia il salto di un'ora per deriva")
def _():
    import gestione
    db = gestione.apri_archivio(":memory:")
    ieri = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    for n, s in enumerate([0.0, -1.0, -2.0, 3597.0, 3596.0, 3595.0]):
        db.execute("INSERT INTO importazioni (quando, esito, scarto_s, "
                   "riallineato) VALUES (?, 'ok', ?, 0)",
                   (f"{ieri} {8+n:02d}:00:00", s))
    db.commit()
    al_giorno, _, campioni = gestione.deriva_orologio(db)
    assert campioni == 4 and abs(al_giorno + 24) < 0.5, (al_giorno, campioni)
    db.close()


# --------------------------------------------------------------------------
falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
