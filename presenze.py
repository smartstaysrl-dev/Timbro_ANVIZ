#!/usr/bin/env python3
# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
Motore delle presenze: da timbrature grezze a ore lavorate.

Principio non negoziabile: gli eventi grezzi in `raw_events` non si toccano
mai. Le correzioni vivono in `rettifiche` e vengono applicate al volo quando si
calcola. Cosi' si puo' sempre rispondere alla domanda "perche' quel giorno
risulta cosi'?" risalendo al dato originale e a chi lo ha corretto.

Il calcolo e' in tre passaggi separati, apposta:
  1. si raccolgono i punzoni (grezzi + rettifiche)
  2. si assegnano al giorno operativo e si accoppiano entrata/uscita
  3. si sommano le ore applicando le regole del locale
Ogni passaggio si puo' ispezionare da solo, e le anomalie non interrompono il
calcolo: vengono segnalate accanto al risultato.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
from dataclasses import dataclass, field, asdict

# Un solo fuso per tutto il programma, definito in anviz.py insieme al suo
# ripiego per quando Windows non ha il database dei fusi. Averne due copie
# sarebbe il modo migliore per farle divergere.
from anviz import FUSO

# --- Regole del locale -------------------------------------------------------
@dataclass
class Regole:
    """Le nove decisioni del titolare, in un posto solo."""

    # A che ora finisce la giornata: un punzone prima di quest'ora appartiene
    # al giorno precedente. E' cio' che fa funzionare i turni notturni.
    inizio_giornata: str = "05:00"

    # Come si capisce se un punzone e' entrata o uscita:
    #   "stati"     - lo dice il terminale (tasto IN/OUT premuto dal dipendente)
    #   "alternanza"- si alternano: primo entrata, secondo uscita, ...
    #   "automatico"- usa gli stati se il terminale li ha davvero differenziati
    #                 E se letti alla lettera reggono; altrimenti alternanza
    verso: str = "automatico"

    # Due timbrature della stessa persona entro questi secondi sono la stessa:
    # il dito che passa due volte sul lettore.
    secondi_doppione: int = 90

    # Oltre questa durata un turno non e' credibile: quasi sempre e' un'uscita
    # dimenticata. Non si cancella niente, si segnala.
    ore_massime_turno: float = 13.0

    # Arrotondamento delle ore giornaliere, in minuti (0 = nessuno).
    # La direzione non e' un dettaglio tecnico ma una scelta retributiva:
    # "vicino" e' neutro, "su" favorisce il dipendente, "giu" il datore.
    # Va decisa dal titolare e messa per iscritto, non lasciata al caso.
    arrotondamento_minuti: int = 0
    arrotondamento_verso: str = "vicino"      # "vicino" | "su" | "giu"

    # Pausa tolta d'ufficio oltre una certa durata (0 = nessuna).
    pausa_automatica_minuti: int = 0
    pausa_oltre_ore: float = 6.0

    # Un turno che finisce poco dopo l'inizio della giornata operativa
    # appartiene ancora alla notte prima. Vedi _ricuci_notte.
    minuti_coda_notte: int = 120

    # Da qui in su e' straordinario.
    minuti_ordinari: int = 480

    @staticmethod
    def carica(percorso: str) -> "Regole":
        if os.path.exists(percorso):
            try:
                with open(percorso, encoding="utf-8") as f:
                    return Regole(**{k: v for k, v in json.load(f).items()
                                     if k in Regole.__dataclass_fields__})
            except (OSError, ValueError, TypeError):
                pass
        return Regole()

    def salva(self, percorso: str) -> None:
        with open(percorso, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @property
    def ora_inizio(self) -> dt.time:
        ore, minuti = (self.inizio_giornata.split(":") + ["0"])[:2]
        return dt.time(int(ore), int(minuti))


# --- Rettifiche --------------------------------------------------------------
SCHEMA_RETTIFICHE = """
CREATE TABLE IF NOT EXISTS rettifiche (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo           TEXT    NOT NULL,   -- 'aggiunta' | 'annullamento'
    employee_code  INTEGER NOT NULL,
    quando_locale  TEXT,               -- per le aggiunte
    verso          TEXT,               -- 'entrata' | 'uscita' | NULL
    evento_annullato TEXT,             -- source_event_id, per gli annullamenti
    motivo         TEXT    NOT NULL,
    autore         TEXT    NOT NULL,
    creata_il      TEXT    NOT NULL
);
"""


def prepara(db) -> None:
    db.executescript(SCHEMA_RETTIFICHE)


def aggiungi_timbratura(db, employee_code: int, quando: dt.datetime,
                        verso: str | None, motivo: str, autore: str) -> None:
    db.execute(
        "INSERT INTO rettifiche (tipo, employee_code, quando_locale, verso, "
        "motivo, autore, creata_il) VALUES ('aggiunta',?,?,?,?,?,?)",
        (employee_code, quando.isoformat(sep=" ", timespec="seconds"), verso,
         motivo, autore, dt.datetime.now().isoformat(timespec="seconds")))
    db.commit()


def togli_aggiunta(db, rettifica_id: int) -> bool:
    """Cancella una timbratura AGGIUNTA a mano.

    Serve perche' una correzione sbagliata va potuta correggere: senza questo,
    un'uscita inserita alle 23:00 invece che alle 22:00 resterebbe li' per
    sempre e l'unica strada sarebbe aprire il database a mano.

    Si cancella solo la riga della rettifica: il grezzo del terminale non si
    tocca mai, ne' qui ne' altrove.
    """
    cur = db.execute("DELETE FROM rettifiche WHERE id = ? AND tipo = 'aggiunta'",
                     (rettifica_id,))
    db.commit()
    return cur.rowcount > 0


def annulla_timbratura(db, employee_code: int, source_event_id: str,
                       motivo: str, autore: str) -> None:
    db.execute(
        "INSERT INTO rettifiche (tipo, employee_code, evento_annullato, "
        "motivo, autore, creata_il) VALUES ('annullamento',?,?,?,?,?)",
        (employee_code, source_event_id, motivo, autore,
         dt.datetime.now().isoformat(timespec="seconds")))
    db.commit()


# --- Punzoni -----------------------------------------------------------------
@dataclass
class Punzone:
    employee_code: int
    quando: dt.datetime         # ora locale: serve per il giorno e per mostrarla
    istante: dt.datetime        # istante assoluto (UTC): serve per le durate
    stato: int | None           # nibble basso del record, None se aggiunto a mano
    metodo: str
    origine: str                # 'terminale' | 'rettifica'
    evento_id: str | None
    verso: str | None = None    # riempito dall'accoppiamento
    scartato: str | None = None # motivo dello scarto (doppione, annullato)


def _quando(testo: str) -> dt.datetime:
    return dt.datetime.fromisoformat(testo)


def _istante(locale: dt.datetime) -> dt.datetime:
    """Da ora locale a istante assoluto.

    Nell'ora che si ripete al ritorno all'ora solare si sceglie la prima
    occorrenza (fold=0), come fa anche l'archivio quando salva.
    """
    return locale.replace(tzinfo=FUSO, fold=0).astimezone(dt.timezone.utc)


def punzoni(db, dal: dt.date, al: dt.date) -> list[Punzone]:
    """Eventi grezzi del periodo, con le rettifiche gia' applicate.

    Si allarga di un giorno da entrambi i lati: un turno notturno iniziato il
    31 finisce il 1, e va accoppiato lo stesso.

    Di ogni punzone si tiene sia l'ora locale sia l'istante assoluto. Servono
    tutti e due e per motivi diversi: il giorno operativo si decide sull'ora
    locale, perche' e' quella che legge il dipendente sull'orologio a muro; le
    durate si misurano sull'istante, altrimenti nelle due notti del cambio
    d'ora un turno risulterebbe di un'ora piu' lungo o piu' corto del vero.
    """
    inizio = (dal - dt.timedelta(days=1)).isoformat()
    fine = (al + dt.timedelta(days=2)).isoformat()

    annullati = {r[0] for r in db.execute(
        "SELECT evento_annullato FROM rettifiche WHERE tipo = 'annullamento'")}

    fuori: list[Punzone] = []
    for eid, codice, quando, utc, stato, metodo in db.execute(
            "SELECT source_event_id, employee_code, occurred_at_local, "
            "occurred_at_utc, event_type, metodo FROM raw_events "
            "WHERE occurred_at_local >= ? AND occurred_at_local < ?",
            (inizio, fine)):
        locale = _quando(quando)
        # Gli archivi piu' vecchi potrebbero non avere l'istante: si ricava.
        assoluto = _quando(utc) if utc else _istante(locale)
        if assoluto.tzinfo is None:
            assoluto = assoluto.replace(tzinfo=dt.timezone.utc)
        p = Punzone(codice, locale, assoluto, stato, metodo, "terminale", eid)
        if eid in annullati:
            p.scartato = "annullata a mano"
        fuori.append(p)

    for rid, codice, quando, verso in db.execute(
            "SELECT id, employee_code, quando_locale, verso FROM rettifiche "
            "WHERE tipo = 'aggiunta' AND quando_locale >= ? AND quando_locale < ?",
            (inizio, fine)):
        locale = _quando(quando)
        # L'identificativo porta dentro il numero della rettifica: e' quello
        # che permette di toglierla, se e' stata inserita per sbaglio.
        fuori.append(Punzone(codice, locale, _istante(locale), None,
                             "inserita a mano", "rettifica",
                             f"rettifica:{rid}", verso=verso))

    # Si ordina sull'istante: nella notte del ritorno all'ora solare due
    # punzoni possono avere la stessa ora locale ma essere a un'ora di distanza.
    fuori.sort(key=lambda p: (p.employee_code, p.istante))
    return fuori


# --- Turni e giornate --------------------------------------------------------
@dataclass
class Turno:
    entrata: Punzone | None
    uscita: Punzone | None

    @property
    def minuti(self) -> int:
        """Durata vera del turno.

        Si sottraggono gli ISTANTI, non le ore locali: nella notte in cui
        l'ora torna indietro un turno 22:00 -> 04:00 dura sette ore, non sei,
        e sull'orologio a muro non si vede.
        """
        if not self.entrata or not self.uscita:
            return 0
        return max(0, int((self.uscita.istante - self.entrata.istante)
                          .total_seconds() // 60))

    @property
    def completo(self) -> bool:
        return self.entrata is not None and self.uscita is not None


@dataclass
class Giornata:
    employee_code: int
    data: dt.date
    turni: list[Turno] = field(default_factory=list)
    scartati: list[Punzone] = field(default_factory=list)
    anomalie: list[str] = field(default_factory=list)
    minuti_lavorati: int = 0
    minuti_straordinario: int = 0

    @property
    def ore(self) -> str:
        return f"{self.minuti_lavorati // 60}:{self.minuti_lavorati % 60:02d}"

    @property
    def prima_entrata(self) -> dt.datetime | None:
        for t in self.turni:
            if t.entrata:
                return t.entrata.quando
        return None

    @property
    def ultima_uscita(self) -> dt.datetime | None:
        for t in reversed(self.turni):
            if t.uscita:
                return t.uscita.quando
        return None


def giorno_operativo(quando: dt.datetime, regole: Regole) -> dt.date:
    """Un punzone prima dell'ora di inizio appartiene al giorno prima.

    Pubblica perche' serve anche all'interfaccia: "oggi" per un ristorante che
    chiude alle due di notte NON e' la data del calendario. Chiedere
    date.today() all'una e mezza vuol dire cercare le presenze di un giorno che
    non e' ancora cominciato, e trovare lo schermo vuoto con la cucina piena.
    """
    return (quando.date() - dt.timedelta(days=1)
            if quando.time() < regole.ora_inizio else quando.date())


# Il vecchio nome resta: e' usato nelle prove e non costa nulla tenerlo.
_giorno_operativo = giorno_operativo


def _ricuci_notte(per_giorno: dict, regole: Regole) -> None:
    """Ricuce il turno che finisce poco DOPO l'ora di inizio giornata.

    Il giorno operativo si decide punzone per punzone: chi entra alle 20:00 ed
    esce alle 04:45 sta tutto nella notte prima, ma se la serata sfora e si
    esce alle 05:15 l'uscita casca nel giorno dopo. Entrata e uscita finiscono
    in due gruppi diversi, nessuno dei due sa dell'altro, e la notte vale ZERO
    minuti con due anomalie invece di nove ore e un quarto. In un ristorante
    una chiusura che sfora le cinque succede.

    Si sposta indietro il primo punzone del giorno dopo quando: il giorno
    prima ha un numero DISPARI di punzoni vivi (cioe' qualcosa e' rimasto
    aperto), il punzone cade entro la coda di notte concessa, e non e' passato
    piu' di un turno massimo dall'ultimo. La finestra stretta e' quello che
    distingue "la serata e' finita alle 05:15" da "ieri si e' dimenticato di
    timbrare l'uscita e stamattina e' rientrato alle nove".
    """
    coda = dt.timedelta(minutes=max(0, regole.minuti_coda_notte))
    if not coda:
        return
    for data in sorted(per_giorno):
        prima = [p for p in per_giorno.get(data, []) if not p.scartato]
        dopo_data = data + dt.timedelta(days=1)
        dopo = [p for p in per_giorno.get(dopo_data, []) if not p.scartato]
        if not prima or not dopo or len(prima) % 2 == 0:
            continue
        candidato = dopo[0]
        confine = dt.datetime.combine(dopo_data, regole.ora_inizio)
        if candidato.quando > confine + coda:
            continue
        if candidato.istante - prima[-1].istante > dt.timedelta(
                hours=regole.ore_massime_turno):
            continue
        per_giorno[dopo_data].remove(candidato)
        per_giorno[data].append(candidato)
        per_giorno[data].sort(key=lambda p: p.quando)
        if not per_giorno[dopo_data]:
            del per_giorno[dopo_data]


def _togli_doppioni(lista: list[Punzone], regole: Regole) -> None:
    """Marca come doppione un punzone troppo vicino al precedente."""
    ultimo: Punzone | None = None
    for p in lista:
        if p.scartato:
            continue
        if (ultimo is not None
                and (p.istante - ultimo.istante).total_seconds()
                    < regole.secondi_doppione):
            p.scartato = f"doppione (entro {regole.secondi_doppione}s)"
        else:
            ultimo = p


def _applica_verso(vivi: list[Punzone], modo: str) -> None:
    """Riempie il verso dei punzoni che non ce l'hanno gia'.

    Chi ce l'ha gia' e' una rettifica in cui l'operatore ha dichiarato
    entrata o uscita: quella parola vale piu' di qualunque deduzione.
    """
    if modo == "stati":
        for p in vivi:
            if p.verso is None:
                p.verso = "uscita" if p.stato == 1 else "entrata"
        return

    atteso = "entrata"
    for p in vivi:
        if p.verso is None:
            p.verso = atteso
        atteso = "uscita" if p.verso == "entrata" else "entrata"


def _stati_credibili(vivi: list[Punzone], regole: Regole) -> bool:
    """Gli stati IN/OUT valgono solo se raccontano una giornata che sta in piedi.

    Il tasto entrata/uscita del terminale non e' un dato per timbratura: e' uno
    stato che RESTA. Se qualcuno lo commuta una volta, tutte le timbrature
    successive, di tutti, escono con quello stato, per giorni. Nella giornata
    della commutazione compaiono entrambi i valori, e prenderli per buoni
    produce entrate senza uscita e uscite senza entrata a raffica: e' successo
    il 2 settembre 2026, sul dispositivo vero, al secondo giorno di prova.

    Si leggono i punzoni in tutti e due i modi e si tiene quello con meno
    anomalie. A parita' vincono gli stati: sono una dichiarazione del
    dipendente, l'alternanza e' solo una deduzione.
    """
    dichiarati = [p.verso for p in vivi]  # le rettifiche, da non toccare
    anomalie = {}
    for modo in ("stati", "alternanza"):
        for p, v in zip(vivi, dichiarati):
            p.verso = v
        _applica_verso(vivi, modo)
        anomalie[modo] = len(_accoppia(vivi, regole)[1])
    for p, v in zip(vivi, dichiarati):
        p.verso = v
    return anomalie["stati"] <= anomalie["alternanza"]


def _assegna_verso(lista: list[Punzone], regole: Regole) -> str:
    """Decide entrata/uscita per ogni punzone. Ritorna il criterio usato."""
    vivi = [p for p in lista if not p.scartato]
    stati = {p.stato for p in vivi if p.stato is not None}

    modo, criterio = regole.verso, None
    if modo == "automatico":
        # Gli stati servono solo se il terminale ne ha davvero registrati di
        # diversi (se tutti valgono 0, nessuno ha mai premuto il tasto) E se
        # letti alla lettera non producono una giornata assurda.
        if len(stati) <= 1:
            modo = "alternanza"
        elif _stati_credibili(vivi, regole):
            modo = "stati"
        else:
            modo, criterio = "alternanza", "alternanza (stati del terminale incoerenti)"

    _applica_verso(vivi, modo)
    if criterio:
        return criterio
    return "stati del terminale" if modo == "stati" else "alternanza"


def _accoppia(lista: list[Punzone], regole: Regole) -> tuple[list[Turno], list[str]]:
    turni, anomalie = [], []
    aperto: Punzone | None = None
    for p in [x for x in lista if not x.scartato]:
        if p.verso == "entrata":
            if aperto is not None:
                turni.append(Turno(aperto, None))
                anomalie.append(f"manca l'uscita delle {aperto.quando:%H:%M}")
            aperto = p
        else:
            if aperto is None:
                turni.append(Turno(None, p))
                anomalie.append(f"manca l'entrata prima delle {p.quando:%H:%M}")
            else:
                turno = Turno(aperto, p)
                if turno.minuti > regole.ore_massime_turno * 60:
                    anomalie.append(
                        f"turno di {turno.minuti // 60}h dalle "
                        f"{aperto.quando:%H:%M}: uscita dimenticata?")
                turni.append(turno)
                aperto = None
    if aperto is not None:
        turni.append(Turno(aperto, None))
        anomalie.append(f"manca l'uscita delle {aperto.quando:%H:%M}")
    return turni, anomalie


def _applica_regole(g: Giornata, regole: Regole) -> None:
    completi = [t for t in g.turni if t.completo]
    minuti = sum(t.minuti for t in completi)
    if regole.pausa_automatica_minuti and minuti > regole.pausa_oltre_ore * 60:
        # Chi la pausa l'ha timbrata l'ha gia' pagata: quel tempo e' fuori dal
        # conteggio perche' sta fra due turni. Togliere di nuovo l'intera pausa
        # la scalerebbe due volte, e chi timbra diligentemente si ritroverebbe
        # meno ore di chi non timbra. Si garantisce solo il minimo: si toglie
        # quanto manca a quello che si e' gia' preso.
        # Il buco si conta solo fra due turni chiusi ADIACENTI. Se in mezzo
        # c'e' un turno monco — un'entrata senza uscita — quel buco non e' una
        # pausa: e' un pezzo di giornata di cui non si sa nulla, e misurarlo
        # come pausa (magari cinque ore) annullerebbe la trattenuta.
        gia_prese = 0
        for prima, dopo in zip(g.turni, g.turni[1:]):
            if not (prima.completo and dopo.completo):
                continue
            gia_prese += max(0, int(
                (dopo.entrata.istante - prima.uscita.istante).total_seconds() // 60))
        minuti = max(0, minuti - max(0, regole.pausa_automatica_minuti - gia_prese))
    passo = regole.arrotondamento_minuti
    if passo > 1 and minuti % passo:
        if regole.arrotondamento_verso == "su":
            minuti = ((minuti // passo) + 1) * passo
        elif regole.arrotondamento_verso == "giu":
            minuti = (minuti // passo) * passo
        else:
            minuti = int(round(minuti / passo) * passo)
    g.minuti_lavorati = minuti
    g.minuti_straordinario = max(0, minuti - regole.minuti_ordinari)


def giornate(db, regole: Regole, dal: dt.date, al: dt.date) -> list[Giornata]:
    """Calcola le giornate del periodo, persona per persona."""
    tutti = punzoni(db, dal, al)

    per_persona: dict[int, list[Punzone]] = {}
    for p in tutti:
        per_persona.setdefault(p.employee_code, []).append(p)

    fuori: list[Giornata] = []
    for codice, lista in per_persona.items():
        _togli_doppioni(lista, regole)

        per_giorno: dict[dt.date, list[Punzone]] = {}
        for p in lista:
            per_giorno.setdefault(giorno_operativo(p.quando, regole), []).append(p)
        _ricuci_notte(per_giorno, regole)

        for data, del_giorno in sorted(per_giorno.items()):
            if not (dal <= data <= al):
                continue        # giorni di contorno, servivano solo ad accoppiare
            g = Giornata(codice, data)
            criterio = _assegna_verso(del_giorno, regole)
            g.turni, g.anomalie = _accoppia(del_giorno, regole)
            g.scartati = [p for p in del_giorno if p.scartato]
            for p in g.scartati:
                g.anomalie.append(f"{p.quando:%H:%M} {p.scartato}")
            _applica_regole(g, regole)
            g.criterio = criterio
            fuori.append(g)

    fuori.sort(key=lambda g: (g.data, g.employee_code))
    return fuori


# --- Esportazione ------------------------------------------------------------
def testo_csv(elenco: list[Giornata], nomi: dict[int, str]) -> str:
    """Il foglio come testo. Separatore punto e virgola perche' e' quello che
    Excel si aspetta con le impostazioni italiane: con la virgola finisce
    tutto in una colonna sola e qualcuno lo rifa' a mano."""
    buffer = io.StringIO()
    w = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    w.writerow(["data", "codice", "dipendente", "entrata", "uscita",
                "turni", "ore", "minuti", "straordinario_min", "anomalie"])
    for g in elenco:
        w.writerow([
            g.data.isoformat(), g.employee_code,
            nomi.get(g.employee_code, f"Utente {g.employee_code}"),
            f"{g.prima_entrata:%H:%M}" if g.prima_entrata else "",
            f"{g.ultima_uscita:%H:%M}" if g.ultima_uscita else "",
            len([t for t in g.turni if t.completo]),
            g.ore, g.minuti_lavorati, g.minuti_straordinario,
            " | ".join(g.anomalie),
        ])
    return buffer.getvalue()


def byte_csv(elenco: list[Giornata], nomi: dict[int, str]) -> bytes:
    """Come sopra, pronto da allegare a una mail. Il BOM serve a Excel per
    riconoscere l'UTF-8: senza, i cognomi con gli accenti escono storpiati."""
    return testo_csv(elenco, nomi).encode("utf-8-sig")


def esporta_csv(percorso: str, elenco: list[Giornata],
                nomi: dict[int, str]) -> int:
    with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
        f.write(testo_csv(elenco, nomi))
    return len(elenco)
