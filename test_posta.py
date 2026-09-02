"""Collaudo del report mensile via email.

La parte delicata non e' spedire: e' decidere QUANDO. Un mese saltato in
silenzio si scopre a fine anno, e a quel punto il dato per rifarlo c'e' ancora
ma nessuno se n'e' accorto. Percio' qui si insiste su: mesi corti, computer
spento per settimane, prima configurazione, e sul fatto che un invio fallito
non venga mai segnato come riuscito.
"""
import datetime as dt
import pathlib
import smtplib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import posta
import presenze
import sicurezza

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


def config(**extra):
    imp = dict(posta.PREDEFINITE)
    imp.update({"attivo": True, "server": "smtp.esempio.it",
                "mittente": "locale@esempio.it",
                "destinatari": "locale@esempio.it"})
    imp.update(extra)
    return imp


def punzone(quando):
    return presenze.Punzone(employee_code=1, quando=quando,
                            istante=presenze._istante(quando), stato=0,
                            metodo="badge", origine="terminale", evento_id="x")


def giornata(codice, data, ore, anomalie=()):
    e = dt.datetime.combine(data, dt.time(11, 0))
    u = e + dt.timedelta(hours=ore)
    t = presenze.Turno(entrata=punzone(e), uscita=punzone(u))
    g = presenze.Giornata(employee_code=codice, data=data, turni=[t])
    g.minuti_lavorati = t.minuti
    g.anomalie = list(anomalie)
    return g


# --- quando spedire ----------------------------------------------------------
@prova("il mese si racconta quando e' finito: scadenza nel mese dopo")
def _():
    assert posta.scadenza(2026, 8, 1) == dt.date(2026, 9, 1)
    assert posta.scadenza(2026, 12, 5) == dt.date(2027, 1, 5)


@prova("giorno 31 su un mese che non ce l'ha: arretra, non salta")
def _():
    # Il report di gennaio andrebbe spedito il 31 febbraio, che non esiste.
    assert posta.scadenza(2027, 1, 31) == dt.date(2027, 2, 28)
    assert posta.scadenza(2028, 1, 31) == dt.date(2028, 2, 29), "anno bisestile"
    assert posta.scadenza(2026, 3, 31) == dt.date(2026, 4, 30)
    # E un giorno assurdo non deve far esplodere niente.
    assert posta.scadenza(2026, 3, 99) == dt.date(2026, 4, 30)
    assert posta.scadenza(2026, 3, 0) == dt.date(2026, 4, 1)


@prova("prima configurazione: parte dal mese chiuso, non dalla preistoria")
def _():
    mesi = posta.mesi_da_inviare(dt.date(2026, 9, 5), 1, "")
    assert mesi == [(2026, 8)], mesi
    # Se il giorno scelto non e' ancora arrivato, non si spedisce nulla.
    assert posta.mesi_da_inviare(dt.date(2026, 9, 5), 28, "") == []


@prova("computer spento per mesi: escono tutti gli arretrati, in ordine")
def _():
    mesi = posta.mesi_da_inviare(dt.date(2026, 9, 5), 1, "2026-05")
    assert mesi == [(2026, 6), (2026, 7), (2026, 8)], mesi
    # E non si torna indietro all'infinito: c'e' un tetto.
    tanti = posta.mesi_da_inviare(dt.date(2026, 9, 5), 1, "2000-01")
    assert len(tanti) <= posta.MASSIMI_ARRETRATI, len(tanti)


@prova("passaggio d'anno: dicembre si spedisce a gennaio")
def _():
    mesi = posta.mesi_da_inviare(dt.date(2027, 1, 3), 1, "2026-11")
    assert mesi == [(2026, 12)], mesi


@prova("gia' spedito: non si ripete")
def _():
    assert posta.mesi_da_inviare(dt.date(2026, 9, 15), 1, "2026-08") == []


@prova("ultimo_inviato illeggibile: si riparte, non si esplode")
def _():
    for rotto in ("boh", "2026", "2026-13", "0000-00", "----"):
        mesi = posta.mesi_da_inviare(dt.date(2026, 9, 5), 1, rotto)
        assert mesi == [(2026, 8)], f"{rotto!r} -> {mesi}"


@prova("l'ora: prima non parte, dopo si')")
def _():
    imp = config(giorno=1, ora="08:00")
    chiave = posta.etichetta(2026, 8)
    sfasa = posta.sfasamento(chiave)
    assert 0 <= sfasa < 19
    limite = dt.datetime(2026, 9, 1, 8, sfasa)
    assert posta.tocca_inviare(imp, limite - dt.timedelta(minutes=1)) is None
    assert posta.tocca_inviare(imp, limite) == (2026, 8)
    # Lo sfasamento e' sempre lo stesso per quel mese: se ballasse, l'ora
    # limite si sposterebbe a ogni controllo e il report partirebbe a caso.
    assert posta.sfasamento(chiave) == sfasa


@prova("in ritardo si spedisce a qualunque ora, senza aspettare domani")
def _():
    imp = config(giorno=1, ora="23:30")
    # Il 3 settembre siamo gia' oltre la scadenza del 1: si parte subito.
    assert posta.tocca_inviare(
        imp, dt.datetime(2026, 9, 3, 0, 5)) == (2026, 8)


@prova("ora di invio a tarda sera: lo sfasamento non la fa scivolare a domani")
def _():
    imp = config(giorno=1, ora="23:55")
    limite = posta._ora_limite(imp, posta.etichetta(2026, 8))
    assert limite <= dt.time(23, 59), limite
    assert posta.tocca_inviare(imp, dt.datetime(2026, 9, 1, 23, 59, 30)) \
        == (2026, 8)


@prova("spento o non configurato: non parte niente")
def _():
    assert posta.tocca_inviare(config(attivo=False),
                               dt.datetime(2026, 9, 15, 12)) is None
    assert posta.tocca_inviare(config(server=""),
                               dt.datetime(2026, 9, 15, 12)) is None
    assert posta.tocca_inviare(config(destinatari=""),
                               dt.datetime(2026, 9, 15, 12)) is None
    assert posta.tocca_inviare(config(mittente=""),
                               dt.datetime(2026, 9, 15, 12)) is None


@prova("giorno scritto male nella configurazione: si ripiega sull'uno")
def _():
    for storto in ("", None, "boh", 0):
        imp = config(giorno=storto)
        assert posta.tocca_inviare(imp, dt.datetime(2026, 9, 15, 12)) \
            == (2026, 8), f"giorno {storto!r}"


# --- destinatari --------------------------------------------------------------
@prova("destinatari: virgole, punti e virgola, spazi")
def _():
    assert posta.destinatari({"destinatari": "a@b.it"}) == ["a@b.it"]
    assert posta.destinatari({"destinatari": "a@b.it, c@d.it"}) \
        == ["a@b.it", "c@d.it"]
    assert posta.destinatari({"destinatari": " a@b.it ; c@d.it\n"}) \
        == ["a@b.it", "c@d.it"]
    assert posta.destinatari({"destinatari": ""}) == []
    assert posta.destinatari({}) == []


# --- contenuto ----------------------------------------------------------------
@prova("il corpo della mail contiene nomi, ore e totale")
def _():
    elenco = [giornata(1, dt.date(2026, 8, 3), 8),
              giornata(1, dt.date(2026, 8, 4), 6),
              giornata(2, dt.date(2026, 8, 3), 5, ["manca l'uscita"])]
    nomi = {1: "Marta Villa", 2: "Ivan Popescu"}
    dal, al = posta.estremi(2026, 8)
    html = posta.corpo_html(elenco, nomi, "agosto 2026", dal, al)
    testo = posta.testo_semplice(elenco, nomi, "agosto 2026")
    for atteso in ("Marta Villa", "Ivan Popescu", "14:00", "agosto 2026"):
        assert atteso in html, f"manca dall'HTML: {atteso}"
        assert atteso in testo, f"manca dal testo: {atteso}"
    assert "da verificare" in html and "da verificare" in testo
    # Il grafico ha una colonna per ogni giorno del mese, per ogni persona.
    assert html.count("bgcolor=") >= 31 * 2, "il grafico non copre il mese"


@prova("un nome con caratteri strani non rompe l'HTML")
def _():
    elenco = [giornata(1, dt.date(2026, 8, 3), 8)]
    html = posta.corpo_html(elenco, {1: '<script>"O\'Brien" & Figli'},
                            "agosto 2026", *posta.estremi(2026, 8))
    assert "<script>" not in html, "iniezione HTML dal nome del dipendente"
    assert "&lt;script&gt;" in html


@prova("mese senza timbrature: la mail parte lo stesso e lo dice")
def _():
    dal, al = posta.estremi(2026, 8)
    html = posta.corpo_html([], {}, "agosto 2026", dal, al)
    testo = posta.testo_semplice([], {}, "agosto 2026")
    assert "Nessuna timbratura" in html and "Nessuna timbratura" in testo


# --- spedizione ---------------------------------------------------------------
class FintoSMTP:
    ultimo = None

    def __init__(self, host, porta=0, *a, **k):
        FintoSMTP.ultimo = self
        self.host, self.porta = host, porta
        self.azioni = []
        self.messaggi = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.azioni.append("chiuso")

    def ehlo(self, *a):
        self.azioni.append("ehlo")

    def starttls(self, *a, **k):
        self.azioni.append("starttls")

    def login(self, utente, password):
        self.azioni.append(("login", utente, password))

    def send_message(self, msg):
        self.azioni.append("inviato")
        self.messaggi.append(msg)


def con_finto_smtp(f):
    veri = (smtplib.SMTP, smtplib.SMTP_SSL)
    smtplib.SMTP = smtplib.SMTP_SSL = FintoSMTP
    try:
        return f()
    finally:
        smtplib.SMTP, smtplib.SMTP_SSL = veri


@prova("SSL: si collega alla porta giusta, fa il login con la password vera")
def _():
    imp = config(sicurezza="ssl", porta=465, utente="locale@esempio.it",
                 password=sicurezza.offusca("segreto!"))
    con_finto_smtp(lambda: posta.invia(imp, "Prova", "ciao"))
    s = FintoSMTP.ultimo
    assert (s.host, s.porta) == ("smtp.esempio.it", 465), (s.host, s.porta)
    assert ("login", "locale@esempio.it", "segreto!") in s.azioni, s.azioni
    assert "starttls" not in s.azioni, "starttls su una connessione gia' SSL"
    assert "inviato" in s.azioni


@prova("STARTTLS: prima ehlo, poi starttls, poi di nuovo ehlo, poi login")
def _():
    imp = config(sicurezza="starttls", porta=587, utente="u",
                 password=sicurezza.offusca("p"))
    con_finto_smtp(lambda: posta.invia(imp, "Prova", "ciao"))
    a = FintoSMTP.ultimo.azioni
    assert a.index("starttls") > a.index("ehlo"), a
    assert a.count("ehlo") == 2, f"manca l'ehlo dopo starttls: {a}"
    assert a.index(("login", "u", "p")) > a.index("starttls"), \
        "credenziali mandate prima di alzare il TLS"


@prova("senza utente non si tenta il login")
def _():
    imp = config(sicurezza="nessuna", porta=25, utente="", password="")
    con_finto_smtp(lambda: posta.invia(imp, "Prova", "ciao"))
    assert not any(isinstance(x, tuple) and x[0] == "login"
                   for x in FintoSMTP.ultimo.azioni)


@prova("il messaggio ha testo, HTML e l'allegato col nome giusto")
def _():
    imp = config()
    elenco = [giornata(1, dt.date(2026, 8, 3), 8)]
    nomi = {1: "Marta Villa"}
    dal, al = posta.estremi(2026, 8)
    con_finto_smtp(lambda: posta.invia(
        imp, "Ore lavorate — agosto 2026",
        posta.testo_semplice(elenco, nomi, "agosto 2026"),
        posta.corpo_html(elenco, nomi, "agosto 2026", dal, al),
        [("ore-2026-08.csv", presenze.byte_csv(elenco, nomi), "text/csv")]))
    msg = FintoSMTP.ultimo.messaggi[0]
    assert msg["Subject"] == "Ore lavorate — agosto 2026"
    assert msg["To"] == "locale@esempio.it"
    tipi = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in tipi and "text/html" in tipi, tipi
    allegati = [p for p in msg.iter_attachments()
                if p.get_filename() == "ore-2026-08.csv"]
    assert allegati, [p.get_filename() for p in msg.iter_attachments()]
    contenuto = allegati[0].get_payload(decode=True)
    assert contenuto.startswith(b"\xef\xbb\xbf"), \
        "manca il BOM: Excel storpia gli accenti"
    assert b"Marta Villa" in contenuto


@prova("posta non configurata: invia() si rifiuta invece di provarci")
def _():
    try:
        con_finto_smtp(lambda: posta.invia(config(server=""), "x", "y"))
        assert False, "ha provato a spedire senza server"
    except ValueError:
        pass


# --- il giro completo dentro lo scheduler -------------------------------------
def scheduler_finto(quando_mese, **posta_extra):
    """Un Servizio vero, con un archivio vero, e l'SMTP finto."""
    import queue
    import tempfile
    import gestione

    cartella = tempfile.mkdtemp()
    archivio = str(pathlib.Path(cartella) / "timbrature.db")
    db = gestione.apri_archivio(archivio)
    db.execute("INSERT INTO dipendenti (employee_code, nome, badge, attivo, "
               "aggiornato) VALUES (1, 'Marta Villa', 1, 1, 'x')")
    anno, mese = quando_mese
    for giorno in (3, 4, 5):
        for ora, etichetta in ((11, "e"), (19, "u")):
            q = dt.datetime(anno, mese, giorno, ora, 0)
            db.execute(
                "INSERT INTO raw_events (source_event_id, device_serial, "
                "employee_code, occurred_at_local, occurred_at_utc, "
                "device_seconds, event_type_raw, event_type, metodo, "
                "work_code, raw_payload, imported_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{etichetta}{giorno}", "SN", 1,
                 q.isoformat(sep=" "), q.isoformat(sep=" "), 0, 0, 0,
                 "badge", 0, "00", "x"))
    db.commit()
    db.close()

    imp = config(**posta_extra)
    cfg = dict(gestione.CONFIG_PREDEFINITA)
    cfg.update({"archivio": archivio, "posta": imp})
    coda = queue.Queue()
    return gestione.Servizio(cfg, coda), cfg, coda


@prova("giro completo: il report parte, e il mese si segna come spedito")
def _():
    oggi = dt.date.today()
    scorso = (oggi.year - 1, 12) if oggi.month == 1 else (oggi.year,
                                                          oggi.month - 1)
    servizio, cfg, coda = scheduler_finto(scorso, giorno=1, ora="00:01")
    con_finto_smtp(servizio._forse_report)
    messaggi = FintoSMTP.ultimo.messaggi
    assert messaggi, "non e' partito niente"
    assert cfg["posta"]["ultimo_inviato"] == posta.etichetta(*scorso), \
        cfg["posta"]["ultimo_inviato"]
    tipi = []
    while not coda.empty():
        tipi.append(coda.get_nowait()[0])
    assert "salva_config" in tipi and "report" in tipi, tipi

    # Al secondo giro non si ripete.
    FintoSMTP.ultimo = None
    con_finto_smtp(servizio._forse_report)
    assert FintoSMTP.ultimo is None, "ha spedito lo stesso mese due volte"


@prova("SMTP che rifiuta: NON si segna come spedito, e si riprova")
def _():
    oggi = dt.date.today()
    scorso = (oggi.year - 1, 12) if oggi.month == 1 else (oggi.year,
                                                          oggi.month - 1)
    servizio, cfg, coda = scheduler_finto(scorso, giorno=1, ora="00:01")

    def rifiuta(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"password sbagliata")

    veri = (smtplib.SMTP, smtplib.SMTP_SSL)
    smtplib.SMTP = smtplib.SMTP_SSL = rifiuta
    try:
        servizio._forse_report()
    finally:
        smtplib.SMTP, smtplib.SMTP_SSL = veri

    assert not cfg["posta"]["ultimo_inviato"], \
        "segnato come spedito nonostante l'errore: quel mese e' perso"
    tipi = []
    while not coda.empty():
        tipi.append(coda.get_nowait()[0])
    assert tipi == ["report_fallito"], tipi

    # Rimessa a posto la password, al giro dopo parte davvero.
    con_finto_smtp(servizio._forse_report)
    assert FintoSMTP.ultimo.messaggi, "non ha riprovato"
    assert cfg["posta"]["ultimo_inviato"] == posta.etichetta(*scorso)


@prova("due giri insieme non spediscono lo stesso mese due volte")
def _():
    import threading
    oggi = dt.date.today()
    scorso = (oggi.year - 1, 12) if oggi.month == 1 else (oggi.year,
                                                          oggi.month - 1)
    servizio, cfg, _ = scheduler_finto(scorso, giorno=1, ora="00:01")
    spediti = []
    partiti = threading.Barrier(2)

    class Lento(FintoSMTP):
        def send_message(self, msg):
            spediti.append(msg)
            time.sleep(0.25)

    veri = (smtplib.SMTP, smtplib.SMTP_SSL)
    smtplib.SMTP = smtplib.SMTP_SSL = Lento

    def giro():
        partiti.wait()
        servizio._forse_report()

    try:
        thread = [threading.Thread(target=giro) for _ in range(2)]
        for t in thread:
            t.start()
        for t in thread:
            t.join(timeout=10)
    finally:
        smtplib.SMTP, smtplib.SMTP_SSL = veri
    assert len(spediti) == 1, f"{len(spediti)} copie dello stesso report"


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
