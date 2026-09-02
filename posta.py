#!/usr/bin/env python3
"""
Il report mensile via email: quando spedirlo, cosa scriverci dentro, e come.

Due scelte da spiegare.

Il grafico dentro la mail e' fatto di celle di tabella colorate, non di
un'immagine. Un'immagine allegata i client di posta la nascondono finche' non
premi "mostra contenuti", e su iPhone quel bottone non lo preme nessuno; le
tabelle si vedono sempre, ovunque, anche su Outlook che disegna le pagine col
motore di Word. Costa piu' codice e vale la pena.

L'orario di partenza e' spostato di qualche minuto, sempre gli stessi per quel
mese. Un messaggio che parte alle 08:00:00 spaccate ogni mese e' un timbro da
automa, e i provider di posta guardano anche quello.

Questo modulo non conosce l'applicazione: riceve le giornate gia' calcolate e
il titolo del periodo, e restituisce testo. Cosi' si puo' collaudare senza
aprire una finestra e senza toccare un archivio.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import smtplib
import ssl
from email.message import EmailMessage

import sicurezza

PREDEFINITE = {
    "attivo": False,
    "server": "",
    "porta": 465,
    "sicurezza": "ssl",          # "ssl" | "starttls" | "nessuna"
    "utente": "",
    "password": "",             # offuscata, vedi sicurezza.offusca
    "mittente": "",
    "destinatari": "",          # anche piu' d'uno, separati da virgola
    "giorno": 1,                # giorno del mese in cui arriva il report
    "ora": "08:00",
    "ultimo_inviato": "",       # "2026-08" = il mese di agosto e' gia' partito
}

# Server piu' comuni, per non far digitare "smtp.gmail.com" col dito a un
# ristoratore. Non sono tutti: c'e' sempre la voce "a mano".
PROVIDER = [
    ("Gmail / Google Workspace", "smtp.gmail.com", 465, "ssl"),
    ("Outlook / Microsoft 365", "smtp.office365.com", 587, "starttls"),
    ("Aruba", "smtps.aruba.it", 465, "ssl"),
    ("Register.it", "smtps.register.it", 465, "ssl"),
    ("Libero", "smtp.libero.it", 465, "ssl"),
    ("Tiscali", "smtp.tiscali.it", 465, "ssl"),
]

MASSIMI_ARRETRATI = 24          # paracadute: non si spediscono anni di storia


# --- Impostazioni -------------------------------------------------------------
def impostazioni(cfg: dict) -> dict:
    """Le impostazioni della posta, con i buchi riempiti dai valori di serie."""
    fuori = dict(PREDEFINITE)
    fuori.update(cfg.get("posta") or {})
    return fuori


def destinatari(imp: dict) -> list[str]:
    grezzo = imp.get("destinatari") or ""
    return [x for x in re.split(r"[,;\s]+", grezzo.strip()) if x]


def configurata(imp: dict) -> bool:
    return bool(imp.get("server") and imp.get("mittente") and destinatari(imp))


# --- Quando spedire -----------------------------------------------------------
def etichetta(anno: int, mese: int) -> str:
    return f"{anno:04d}-{mese:02d}"


def _mese_dopo(anno: int, mese: int) -> tuple[int, int]:
    return (anno + 1, 1) if mese == 12 else (anno, mese + 1)


def _mese_prima(anno: int, mese: int) -> tuple[int, int]:
    return (anno - 1, 12) if mese == 1 else (anno, mese - 1)


def estremi(anno: int, mese: int) -> tuple[dt.date, dt.date]:
    return (dt.date(anno, mese, 1),
            dt.date(anno, mese, calendar.monthrange(anno, mese)[1]))


def scadenza(anno: int, mese: int, giorno: int) -> dt.date:
    """Quando va spedito il report del mese indicato.

    E' il giorno scelto del mese SUCCESSIVO, perche' un mese si racconta
    quando e' finito. Se quel mese e' piu' corto del giorno chiesto — il 31 a
    febbraio — si arretra all'ultimo giorno che esiste, invece di saltare il
    mese come farebbe un confronto ingenuo.
    """
    a, m = _mese_dopo(anno, mese)
    return dt.date(a, m, min(max(1, giorno), calendar.monthrange(a, m)[1]))


def mesi_da_inviare(oggi: dt.date, giorno: int, ultimo: str) -> list:
    """I mesi ancora da spedire, dal piu' vecchio al piu' recente.

    Se il computer e' rimasto spento due mesi, qui ne escono due: saltarli
    vorrebbe dire accorgersi a fine anno che mancano dei report, ed e'
    esattamente il guasto che nessuno nota finche' non serve.
    """
    partenza = None
    if ultimo:
        try:
            partenza = (int(ultimo[:4]), int(ultimo[5:7]))
            dt.date(partenza[0], partenza[1], 1)      # convalida
        except (ValueError, IndexError):
            partenza = None
    if partenza is None:
        # Prima configurazione: si parte dal mese appena chiuso, non da quando
        # ha aperto il locale. Nessuno vuole dodici mail tutte insieme.
        partenza = _mese_prima(*_mese_prima(oggi.year, oggi.month))

    anno, mese = partenza
    fuori = []
    while len(fuori) < MASSIMI_ARRETRATI:
        anno, mese = _mese_dopo(anno, mese)
        if scadenza(anno, mese, giorno) > oggi:
            break
        fuori.append((anno, mese))
    return fuori


def sfasamento(chiave: str) -> int:
    """Minuti di ritardo, sempre gli stessi per quella chiave.

    Deterministico apposta: se cambiasse a ogni controllo, l'ora limite
    ballerebbe avanti e indietro e il report partirebbe quando capita.
    """
    return sum(ord(c) for c in chiave) % 19


def _ora_limite(imp: dict, chiave: str) -> dt.time:
    testo = (imp.get("ora") or "08:00").strip()
    try:
        ore, minuti = (int(x) for x in testo.split(":")[:2])
    except ValueError:
        ore, minuti = 8, 0
    totale = min(ore * 60 + minuti + sfasamento(chiave), 23 * 60 + 59)
    return dt.time(totale // 60, totale % 60)


def tocca_inviare(imp: dict, adesso: dt.datetime):
    """Il mese da spedire adesso, oppure None. Uno per volta, il piu' vecchio."""
    if not imp.get("attivo") or not configurata(imp):
        return None
    try:
        giorno = int(imp.get("giorno") or 1)
    except (TypeError, ValueError):
        giorno = 1
    pendenti = mesi_da_inviare(adesso.date(), giorno,
                               imp.get("ultimo_inviato") or "")
    if not pendenti:
        return None
    anno, mese = pendenti[0]
    dovuto = scadenza(anno, mese, giorno)
    if adesso.date() > dovuto:
        return (anno, mese)          # in ritardo: appena si puo', a ogni ora
    if adesso.time() >= _ora_limite(imp, etichetta(anno, mese)):
        return (anno, mese)
    return None


# --- Il contenuto -------------------------------------------------------------
def _ore(minuti: int) -> str:
    return f"{minuti // 60}:{minuti % 60:02d}"


def _per_persona(elenco, nomi) -> list:
    gruppi = {}
    for g in elenco:
        gruppi.setdefault(g.employee_code, []).append(g)
    fuori = []
    for codice, giornate in gruppi.items():
        giornate.sort(key=lambda x: x.data)
        fuori.append({
            "nome": nomi.get(codice, f"Utente {codice}"),
            "giornate": giornate,
            "per_data": {x.data: x for x in giornate},
            "minuti": sum(x.minuti_lavorati for x in giornate),
            "straordinario": sum(x.minuti_straordinario for x in giornate),
            "lavorati": sum(1 for x in giornate if x.minuti_lavorati),
            "anomalie": sum(len(x.anomalie) for x in giornate),
        })
    fuori.sort(key=lambda p: p["nome"].lower())
    return fuori


def testo_semplice(elenco, nomi, titolo: str) -> str:
    """La versione senza grafica, per chi legge la posta in solo testo."""
    persone = _per_persona(elenco, nomi)
    righe = [f"Ore lavorate — {titolo}", ""]
    if not persone:
        righe.append("Nessuna timbratura nel periodo.")
        return "\n".join(righe)
    larghezza = max(len(p["nome"]) for p in persone)
    for p in persone:
        pezzi = [f"{p['nome']:<{larghezza}}  {_ore(p['minuti']):>8}",
                 f"{p['lavorati']} giorni"]
        if p["straordinario"]:
            pezzi.append(f"{_ore(p['straordinario'])} straordinario")
        if p["anomalie"]:
            pezzi.append(f"{p['anomalie']} da verificare")
        righe.append("  ·  ".join(pezzi))
    totale = sum(p["minuti"] for p in persone)
    anomalie = sum(p["anomalie"] for p in persone)
    righe += ["", f"Totale: {_ore(totale)} su {len(persone)} persone."]
    if anomalie:
        righe.append(f"Attenzione: {anomalie} giornate hanno anomalie aperte. "
                     f"Conviene sistemarle prima di mandarlo alle paghe.")
    righe += ["", "Il dettaglio giorno per giorno e' nel file allegato.",
              "Messaggio automatico della gestione presenze."]
    return "\n".join(righe)


# Tinte chiare: la posta si legge su fondo bianco, non sul tema scuro
# dell'applicazione.
_SFONDO = "#ffffff"
_RIGA = "#f4f5f7"
_INCHIOSTRO = "#1f2430"
_TENUE = "#6b7280"
_VERDE = "#3f9c5a"
_VERDE_TENUE = "#cbe6d3"
_AMBRA = "#c98a1b"


def _colonna_giorno(giorno: dt.date, minuti: int, anomala: bool,
                    massimo: int, alto: int, largo: int) -> str:
    """Una colonna del grafico: tabella annidata, l'unica cosa che tutti i
    client di posta disegnano davvero allo stesso modo."""
    quota = (minuti / massimo) if massimo else 0
    pieno = max(3, round(alto * quota)) if minuti else 2
    vuoto = max(0, alto - pieno)
    colore = (_AMBRA if anomala else _VERDE if minuti else "#dcdee3")
    festivo = giorno.weekday() >= 5
    return (
        f'<td valign="bottom" style="padding:0 1px;'
        f'background:{"#fafbfc" if festivo else _SFONDO}">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="{largo}">'
        f'<tr><td height="{vuoto}" style="font-size:1px;line-height:1px">'
        f'&nbsp;</td></tr>'
        f'<tr><td height="{pieno}" bgcolor="{colore}" '
        f'style="font-size:1px;line-height:1px">&nbsp;</td></tr>'
        f'</table></td>')


def _grafico(persone, dal: dt.date, al: dt.date) -> str:
    giorni = [dal + dt.timedelta(days=i) for i in range((al - dal).days + 1)]
    massimo = max((g.minuti_lavorati for p in persone
                   for g in p["giornate"]), default=0)
    largo, alto = 14, 46
    pezzi = ['<table cellpadding="0" cellspacing="0" border="0" '
             'style="border-collapse:collapse;margin-top:6px">']
    # righello dei giorni
    pezzi.append(f'<tr><td style="width:150px"></td>')
    for g in giorni:
        pezzi.append(
            f'<td align="center" style="font:10px Arial,sans-serif;'
            f'color:{_TENUE};padding:0 1px">{g.day}</td>')
    pezzi.append('<td></td></tr>')
    for p in persone:
        pezzi.append(
            f'<tr><td style="font:13px Arial,sans-serif;color:{_INCHIOSTRO};'
            f'padding:6px 10px 6px 0;white-space:nowrap">{_esc(p["nome"])}</td>')
        for g in giorni:
            giornata = p["per_data"].get(g)
            pezzi.append(_colonna_giorno(
                g, giornata.minuti_lavorati if giornata else 0,
                bool(giornata and giornata.anomalie), massimo, alto, largo))
        pezzi.append(
            f'<td style="font:bold 13px Arial,sans-serif;'
            f'color:{_INCHIOSTRO};padding-left:10px;white-space:nowrap">'
            f'{_ore(p["minuti"])}</td></tr>')
    pezzi.append('</table>')
    return "".join(pezzi)


def _esc(testo: str) -> str:
    return (str(testo).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def corpo_html(elenco, nomi, titolo: str, dal: dt.date, al: dt.date) -> str:
    persone = _per_persona(elenco, nomi)
    stile_cella = (f'style="font:13px Arial,sans-serif;color:{_INCHIOSTRO};'
                   f'padding:8px 12px;border-bottom:1px solid #e6e8ec"')
    righe = []
    for p in persone:
        note = []
        if p["straordinario"]:
            note.append(f"{_ore(p['straordinario'])} di straordinario")
        if p["anomalie"]:
            note.append(f'<span style="color:{_AMBRA}">{p["anomalie"]} '
                        f'da verificare</span>')
        righe.append(
            f'<tr><td {stile_cella}>{_esc(p["nome"])}</td>'
            f'<td {stile_cella} align="right">{p["lavorati"]}</td>'
            f'<td {stile_cella} align="right"><b>{_ore(p["minuti"])}</b></td>'
            f'<td {stile_cella} style="font:12px Arial,sans-serif;'
            f'color:{_TENUE};padding:8px 12px;'
            f'border-bottom:1px solid #e6e8ec">{" · ".join(note)}</td></tr>')

    totale = sum(p["minuti"] for p in persone)
    anomalie = sum(p["anomalie"] for p in persone)
    avviso = ""
    if anomalie:
        avviso = (f'<p style="font:13px Arial,sans-serif;color:{_AMBRA};'
                  f'margin:14px 0 0">{anomalie} giornate hanno anomalie '
                  f'aperte: conviene sistemarle prima di mandare il file '
                  f'alle paghe.</p>')

    if not persone:
        centro = (f'<p style="font:14px Arial,sans-serif;color:{_TENUE}">'
                  f'Nessuna timbratura in questo periodo.</p>')
    else:
        centro = (
            f'<table cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:collapse;width:100%;max-width:660px">'
            f'<tr>'
            f'<th align="left" style="font:11px Arial,sans-serif;'
            f'color:{_TENUE};padding:0 12px 6px;letter-spacing:.5px">'
            f'DIPENDENTE</th>'
            f'<th align="right" style="font:11px Arial,sans-serif;'
            f'color:{_TENUE};padding:0 12px 6px">GIORNI</th>'
            f'<th align="right" style="font:11px Arial,sans-serif;'
            f'color:{_TENUE};padding:0 12px 6px">ORE</th>'
            f'<th align="left" style="font:11px Arial,sans-serif;'
            f'color:{_TENUE};padding:0 12px 6px">NOTE</th>'
            f'</tr>{"".join(righe)}</table>'
            f'<p style="font:13px Arial,sans-serif;color:{_INCHIOSTRO};'
            f'margin:16px 0 0"><b>Totale {_ore(totale)}</b> su '
            f'{len(persone)} persone.</p>{avviso}'
            f'<h3 style="font:14px Arial,sans-serif;color:{_INCHIOSTRO};'
            f'margin:26px 0 0">Il mese giorno per giorno</h3>'
            f'<p style="font:12px Arial,sans-serif;color:{_TENUE};'
            f'margin:2px 0 0">Colonna alta = piu\' ore. In ambra i giorni con '
            f'qualcosa da verificare.</p>'
            f'{_grafico(persone, dal, al)}')

    return (
        f'<div style="background:{_RIGA};padding:22px;'
        f'font-family:Arial,Helvetica,sans-serif">'
        f'<div style="background:{_SFONDO};border-radius:10px;padding:24px;'
        f'max-width:900px;margin:0 auto">'
        f'<h2 style="font:600 20px Arial,sans-serif;color:{_INCHIOSTRO};'
        f'margin:0">Ore lavorate</h2>'
        f'<p style="font:14px Arial,sans-serif;color:{_TENUE};'
        f'margin:2px 0 20px">{_esc(titolo)}</p>'
        f'{centro}'
        f'<p style="font:12px Arial,sans-serif;color:{_TENUE};'
        f'margin:26px 0 0;border-top:1px solid #e6e8ec;padding-top:12px">'
        f'Il dettaglio giorno per giorno e\' nel file allegato, gia\' pronto '
        f'per il foglio di calcolo. Messaggio automatico della gestione '
        f'presenze.</p>'
        f'</div></div>')


# --- Spedizione ---------------------------------------------------------------
def componi(imp: dict, oggetto: str, testo: str, html: str | None = None,
            allegati=()) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = oggetto
    msg["From"] = imp["mittente"]
    msg["To"] = ", ".join(destinatari(imp))
    msg.set_content(testo)
    if html:
        msg.add_alternative(html, subtype="html")
    for nome, dati, tipo in allegati:
        maggiore, _, minore = tipo.partition("/")
        msg.add_attachment(dati, maintype=maggiore, subtype=minore or "plain",
                           filename=nome)
    return msg


def invia(imp: dict, oggetto: str, testo: str, html: str | None = None,
          allegati=()) -> None:
    """Spedisce. Solleva se qualcosa va storto: chi chiama decide che farne."""
    if not configurata(imp):
        raise ValueError("posta non configurata: mancano server, mittente o "
                         "destinatario")
    msg = componi(imp, oggetto, testo, html, allegati)
    modo = (imp.get("sicurezza") or "ssl").lower()
    porta = int(imp.get("porta") or (465 if modo == "ssl" else 587))
    contesto = ssl.create_default_context()
    if modo == "ssl":
        with smtplib.SMTP_SSL(imp["server"], porta, context=contesto,
                              timeout=45) as s:
            _accedi(s, imp)
            s.send_message(msg)
        return
    with smtplib.SMTP(imp["server"], porta, timeout=45) as s:
        s.ehlo()
        if modo == "starttls":
            s.starttls(context=contesto)
            s.ehlo()
        _accedi(s, imp)
        s.send_message(msg)


def _accedi(sessione, imp: dict) -> None:
    utente = (imp.get("utente") or "").strip()
    if not utente:
        return                      # server interno che non chiede credenziali
    sessione.login(utente, sicurezza.svela(imp.get("password") or ""))
