# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""Collaudo del grafico delle presenze.

Non si fotografa la figura: si controlla la logica che decide COSA disegnare,
che e' dove stanno gli errori che raccontano bugie. Il caso che conta e' il
turno senza uscita: oggi vuol dire "e' dentro adesso", ieri vuol dire "l'uscita
non e' mai stata timbrata", e disegnarli allo stesso modo fa apparire giornate
di sedici ore mai lavorate.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import gestione
import presenze

G = gestione.GraficoPresenze
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


def punzone(quando: dt.datetime) -> presenze.Punzone:
    return presenze.Punzone(
        employee_code=1, quando=quando, istante=presenze._istante(quando),
        stato=0, metodo="badge", origine="terminale", evento_id="x")


def giornata(data: dt.date, coppie) -> presenze.Giornata:
    """coppie: lista di (entrata, uscita|None) come orari locali."""
    turni = [presenze.Turno(entrata=punzone(e),
                            uscita=punzone(u) if u else None)
             for e, u in coppie]
    g = presenze.Giornata(employee_code=1, data=data, turni=turni)
    g.secondi_lavorati = sum(t.secondi for t in turni)
    return g


OGGI = dt.date.today()
IERI = OGGI - dt.timedelta(days=1)
ADESSO = dt.datetime.combine(OGGI, dt.time(14, 30))


@prova("turno chiuso: la barra finisce all'uscita")
def _():
    e = dt.datetime.combine(IERI, dt.time(11, 0))
    u = dt.datetime.combine(IERI, dt.time(15, 0))
    g = giornata(IERI, [(e, u)])
    inizio, fine, genere = G._come_finisce(g, g.turni[0], ADESSO, True)
    assert (inizio, fine) == (e, u), (inizio, fine)
    assert genere == G.CHIUSO


@prova("uscita mai timbrata su un giorno passato: nessuna barra inventata")
def _():
    e = dt.datetime.combine(IERI, dt.time(11, 44))
    g = giornata(IERI, [(e, None)])
    _, fine, genere = G._come_finisce(g, g.turni[0], ADESSO, True)
    assert fine is None, \
        f"la barra arriva fino a {fine}: racconta ore mai lavorate"
    assert genere == G.SENZA_USCITA


@prova("turno aperto oggi: la barra cresce fino adesso")
def _():
    e = dt.datetime.combine(OGGI, dt.time(11, 10))
    g = giornata(OGGI, [(e, None)])
    _, fine, genere = G._come_finisce(g, g.turni[0], ADESSO, True)
    assert fine == ADESSO, fine
    assert genere == G.IN_CORSO


@prova("entrata nel futuro (orologio sballato): non si disegna all'indietro")
def _():
    e = dt.datetime.combine(OGGI, dt.time(23, 50))
    g = giornata(OGGI, [(e, None)])
    _, fine, genere = G._come_finisce(g, g.turni[0], ADESSO, True)
    assert fine is None and genere == G.SENZA_USCITA, (fine, genere)


@prova("turno aperto ma NON l'ultimo: e' un'uscita mancante, non 'in corso'")
def _():
    # Caso vero, visto sullo schermo il 2/09: NICOLA entra alle 09:11 e non
    # timbra l'uscita, poi rientra alle 09:53 ed esce alle 10:46. Il primo
    # turno non e' "ancora al lavoro": e' finito, solo che nessuno sa quando.
    # Disegnandolo fino adesso finiva SOTTO al turno successivo, e si vedevano
    # tre pezzi colorati al posto di uno.
    e1 = dt.datetime.combine(OGGI, dt.time(9, 11))
    e2 = dt.datetime.combine(OGGI, dt.time(9, 53))
    u2 = dt.datetime.combine(OGGI, dt.time(10, 46))
    g = giornata(OGGI, [(e1, None), (e2, u2)])
    persona = {"giornate": [g]}
    segmenti = G._segmenti(persona)
    assert len(segmenti) == 2
    generi = [G._come_finisce(gg, tt, ADESSO, i == len(segmenti) - 1)[2]
              for i, (gg, tt) in enumerate(segmenti)]
    assert generi == [G.SENZA_USCITA, G.CHIUSO], generi
    # E le barre non si sovrappongono piu': la prima e' un moncone.
    inizio, fine, _ = G._come_finisce(*segmenti[0], ADESSO, False)
    assert fine is None, f"la barra del turno monco arriva fino a {fine}"


@prova("turno con la sola uscita: si vede, non sparisce")
def _():
    # Se sparisse, il nome in giallo direbbe "c'e' un'anomalia" e il grafico
    # sotto non mostrerebbe niente di strano.
    u = dt.datetime.combine(OGGI, dt.time(10, 46))
    t = presenze.Turno(entrata=None, uscita=punzone(u))
    g = presenze.Giornata(employee_code=1, data=OGGI, turni=[t])
    segmenti = G._segmenti({"giornate": [g]})
    assert len(segmenti) == 1, "il turno monco e' stato buttato via"
    inizio, fine, genere = G._come_finisce(g, t, ADESSO, True)
    assert (inizio, fine, genere) == (u, None, G.SENZA_ENTRATA)


@prova("i segmenti escono in ordine di orario, anche fra piu' giornate")
def _():
    a = dt.datetime.combine(IERI, dt.time(19, 0))
    b = dt.datetime.combine(OGGI, dt.time(9, 0))
    c = dt.datetime.combine(OGGI, dt.time(18, 0))
    g1 = giornata(OGGI, [(c, None)])
    g2 = giornata(IERI, [(a, a + dt.timedelta(hours=2))])
    g3 = giornata(OGGI, [(b, b + dt.timedelta(hours=1))])
    ordine = [(g[1].entrata or g[1].uscita).quando
              for g in G._segmenti({"giornate": [g1, g2, g3]})]
    assert ordine == sorted(ordine), ordine
    assert ordine == [a, b, c], ordine


@prova("il totale della riga resta quello del motore, non quello disegnato")
def _():
    # Un turno aperto vale zero minuti per il motore: se un giorno lo si
    # cambiasse, il grafico direbbe una cosa e l'esportazione un'altra.
    e = dt.datetime.combine(OGGI, dt.time(9, 0))
    g = giornata(OGGI, [(e, None)])
    assert g.turni[0].secondi == 0, "il motore ha iniziato a contare i turni aperti"


@prova("raggruppamento per persona: somme, anomalie e ordine alfabetico")
def _():
    def g_di(codice, data, ore, anomalie=()):
        e = dt.datetime.combine(data, dt.time(9, 0))
        u = e + dt.timedelta(hours=ore)
        g = giornata(data, [(e, u)])
        g.employee_code = codice
        g.anomalie = list(anomalie)
        return g

    elenco = [
        g_di(2, IERI, 4), g_di(2, OGGI, 6, ["manca l'uscita"]),
        g_di(1, OGGI, 8),
    ]
    nomi = {1: "Zoe Vitali", 2: "Anna Greco"}
    persone = G._per_persona(elenco, nomi)
    assert [p["nome"] for p in persone] == ["Anna Greco", "Zoe Vitali"], \
        "le persone non sono in ordine alfabetico"
    anna = persone[0]
    assert anna["secondi"] == 600 * 60, anna["secondi"]
    assert anna["anomalie"] == 1, anna["anomalie"]
    assert [g.data for g in anna["giornate"]] == [IERI, OGGI], \
        "le giornate della persona non sono in ordine di data"
    # Chi non e' in anagrafica non sparisce: compare col suo numero.
    senza_nome = G._per_persona([g_di(9, OGGI, 3)], {})
    assert senza_nome[0]["nome"] == "Utente 9", senza_nome[0]["nome"]


@prova("sfumatura: estremi esatti, niente colori fuori scala")
def _():
    assert gestione._sfuma("#000000", "#ffffff", 0) == "#000000"
    assert gestione._sfuma("#000000", "#ffffff", 1) == "#ffffff"
    assert gestione._sfuma("#000000", "#ffffff", 0.5) == "#808080"
    # Fuori dall'intervallo si aggancia agli estremi invece di produrre un
    # colore illegale che farebbe morire Tk in disegno.
    assert gestione._sfuma("#000000", "#ffffff", -3) == "#000000"
    assert gestione._sfuma("#000000", "#ffffff", 12) == "#ffffff"
    for q in (i / 37 for i in range(38)):
        colore = gestione._sfuma(gestione.CARD_CHIARA, gestione.VERDE, q)
        assert len(colore) == 7 and colore.startswith("#"), colore
        int(colore[1:], 16)


@prova("giornata disegnata: ogni barra sta sotto i suoi orari")
def _():
    # Novembre 2026: la durata del turno chiamata come l'ampiezza della
    # finestra oraria spostava tutte le barre dopo la prima sul bordo destro.
    try:
        radice = gestione.tk.Tk()
    except gestione.tk.TclError:
        return                          # niente schermo: non si puo' disegnare
    try:
        radice.withdraw()
        tela = G(radice)
        g = giornata(IERI, [
            (dt.datetime.combine(IERI, dt.time(11, 0)),
             dt.datetime.combine(IERI, dt.time(15, 0))),
            (dt.datetime.combine(IERI, dt.time(18, 0)),
             dt.datetime.combine(IERI, dt.time(23, 0)))])
        tela._giornata(G._per_persona([g], {1: "Anna"}), 1000, 56)
        x0, x1 = G.NOMI, 1000 - G.TOTALI
        barre = sorted(tela.coords(i)[0] for i in tela.find_all()
                       if tela.type(i) == "rectangle"
                       and tela.itemcget(i, "fill") == gestione.VERDE)
        # Righello dalle 11 alle 23: dodici ore.
        attese = [x0, x0 + (x1 - x0) * 7 / 12]
        assert len(barre) == 2, barre
        for vera, attesa in zip(barre, attese):
            assert abs(vera - attesa) < 2, (barre, attese)
    finally:
        radice.destroy()


@prova("le ore della mail sono scritte come quelle del programma")
def _():
    for secondi in (0, 59, 8 * 3600, 205 * 3600 + 45 * 60 + 7):
        assert gestione.posta._ore(secondi) == presenze.durata(secondi), secondi


@prova("ora della timbratura: dopo la mezzanotte va sulla mattina dopo")
def _():
    import tkinter as tk
    radice = tk.Tk()
    radice.withdraw()
    try:
        venti = dt.date(2026, 11, 20)
        cinque = dt.time(5, 0)
        S = gestione.SceltaOraTimbratura
        # Uscita dimenticata dalla cena del 20: 00:35 e' il 21, non il 20.
        d = S(radice, "A che ora?", venti, cinque,
              dt.datetime(2026, 11, 20, 23, 50))
        assert not d.notte and d._quando() == dt.datetime(2026, 11, 20, 23, 50)
        d._muovi(1, 0)                                  # 00:50
        d._muovi(0, -15)                                # 00:35
        assert d.notte and d.casella.valore, "la casella non si e' spuntata"
        assert d._quando() == dt.datetime(2026, 11, 21, 0, 35), d._quando()
        assert "sabato 21 novembre" in d.esito.cget("text"), d.esito.cget("text")
        # Chi tocca la casella decide lui: muovere l'ora non la cambia piu'.
        d._casella(False)
        d._muovi(0, 5)
        assert not d.notte and d._quando() == dt.datetime(2026, 11, 20, 0, 40)
        d.destroy()
        # Correggere una timbratura gia' dopo mezzanotte: la casella parte
        # spuntata e la data resta quella vera.
        d = S(radice, "Ora giusta", venti, cinque,
              dt.datetime(2026, 11, 21, 0, 35))
        assert d.notte and d._quando() == dt.datetime(2026, 11, 21, 0, 35)
        # Su una cassa da 1024x600 il dialogo deve stare in 510 pixel (600
        # meno la barra): prima Annulla e Conferma finivano tagliati.
        d.compatta()
        d.update_idletasks()
        assert d.winfo_reqheight() <= 510, d.winfo_reqheight()
        d.destroy()
    finally:
        radice.destroy()


C = gestione.SchermataPresenze._righe_cartellino
NOV = dt.date(2026, 11, 1), dt.date(2026, 11, 30)


def persona(*giornate):
    return G._per_persona(list(giornate), {1: "Mario Rossi"})[0]


@prova("cartellino: una riga per ogni giorno del mese, anche senza timbrature")
def _():
    g = giornata(dt.date(2026, 11, 3),
                 [(dt.datetime(2026, 11, 3, 11, 19, 16),
                   dt.datetime(2026, 11, 3, 15, 5, 56))])
    coppie, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert len(righe) == 30, len(righe)
    assert [r["data"].day for r in righe] == list(range(1, 31))
    assert righe[0]["giorno"] == "Do 1", righe[0]["giorno"]
    assert [righe[i]["giorno"] for i in (1, 3, 4)] == ["Lu 2", "Me 4", "Gi 5"]
    vuota = righe[0]
    assert vuota["giornata"] is None and vuota["lavorate"] == ""
    assert vuota["orari"] == [("", "")] * 4, vuota["orari"]
    piena = righe[2]
    assert piena["giornata"] is g
    assert piena["orari"][:2] == [("11:19:16", ""), ("15:05:56", "")]
    assert piena["lavorate"] == "3:46:40", piena["lavorate"]


@prova("cartellino: due coppie di colonne, tre se qualcuno fa tre turni")
def _():
    g = giornata(dt.date(2026, 11, 3),
                 [(dt.datetime(2026, 11, 3, 8), dt.datetime(2026, 11, 3, 10)),
                  (dt.datetime(2026, 11, 3, 12), dt.datetime(2026, 11, 3, 14)),
                  (dt.datetime(2026, 11, 3, 19), dt.datetime(2026, 11, 3, 23))])
    coppie, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert coppie == 3, coppie
    assert all(len(r["orari"]) == 6 for r in righe)
    assert righe[2]["orari"][4:] == [("19:00:00", ""), ("23:00:00", "")]


@prova("cartellino: il turno dopo mezzanotte resta sul giorno in cui e' iniziato")
def _():
    g = giornata(dt.date(2026, 11, 2),
                 [(dt.datetime(2026, 11, 2, 19, 29, 50),
                   dt.datetime(2026, 11, 3, 0, 16, 10))])
    _, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert righe[1]["orari"][:2] == [("19:29:50", ""), ("00:16:10", "")]
    assert righe[2]["giornata"] is None


@prova("cartellino: uscita mancante ieri da verificare, oggi 'in corso'")
def _():
    ieri = giornata(IERI, [(dt.datetime.combine(IERI, dt.time(19)), None)])
    ieri.anomalie = ["manca l'uscita"]
    oggi = giornata(OGGI, [(dt.datetime.combine(OGGI, dt.time(11)), None)])
    p = persona(ieri, oggi)
    _, righe = C(p, IERI, OGGI, ADESSO, OGGI)
    assert righe[0]["orari"][1] == ("—", "manca"), righe[0]["orari"]
    assert righe[0]["note"] == "manca l'uscita"
    assert righe[1]["orari"][1] == ("in corso", "in_corso"), righe[1]["orari"]
    # Il giorno dopo la stessa uscita mancante non e' piu' "in corso".
    domani = OGGI + dt.timedelta(days=1)
    _, righe = C(p, IERI, OGGI, ADESSO + dt.timedelta(days=1), domani)
    assert righe[1]["orari"][1] == ("—", "manca"), righe[1]["orari"]


@prova("cartellino: chi e' al lavoro adesso non e' 'da verificare'")
def _():
    # Il motore segna "manca l'uscita" anche sul turno aperto di oggi: nella
    # griglia c'e' gia' "in corso", e la nota gialla accanto la smentirebbe.
    entrata = dt.datetime.combine(OGGI, dt.time(11, 3, 40))
    oggi = giornata(OGGI, [(entrata, None)])
    oggi.anomalie = [presenze.manca_uscita(entrata)]
    p = persona(oggi)
    _, righe = C(p, OGGI, OGGI, ADESSO, OGGI)
    assert righe[0]["orari"][1] == ("in corso", "in_corso"), righe[0]["orari"]
    assert righe[0]["note"] == "" and righe[0]["da_verificare"] == 0, righe[0]
    # Passata la giornata, la stessa uscita mancante torna da verificare.
    domani = OGGI + dt.timedelta(days=1)
    _, righe = C(p, OGGI, OGGI, ADESSO + dt.timedelta(days=1), domani)
    assert righe[0]["note"] == presenze.manca_uscita(entrata), righe[0]
    assert righe[0]["da_verificare"] == 1


@prova("cartellino: cambiando mese resta aperta la persona scelta")
def _():
    scegli = gestione.SchermataPresenze._chi_mostrare
    nomi = {1: "Mario Rossi", 2: "Anna Bianchi", 3: "Zeno Verdi"}
    persone = G._per_persona(
        [giornata(dt.date(2026, 10, 3), [(dt.datetime(2026, 10, 3, 9),
                                          dt.datetime(2026, 10, 3, 17))])],
        nomi)
    # Zeno a ottobre non ha timbrato: resta lui, col mese vuoto, e compare
    # nell'elenco al suo posto in ordine alfabetico.
    elenco, aperta = scegli(persone, 3, nomi)
    assert aperta["codice"] == 3 and aperta["giornate"] == [], aperta
    assert [x["nome"] for x in elenco] == ["Mario Rossi", "Zeno Verdi"], elenco
    elenco, aperta = scegli(persone, 1, nomi)
    assert aperta is persone[0] and elenco == persone
    elenco, aperta = scegli(persone, None, nomi)
    assert aperta is persone[0]


@prova("cartellino: senza entrata si vede il trattino, non un buco")
def _():
    g = giornata(dt.date(2026, 11, 3),
                 [(dt.datetime(2026, 11, 3, 11), dt.datetime(2026, 11, 3, 15))])
    g.turni.append(presenze.Turno(
        entrata=None, uscita=punzone(dt.datetime(2026, 11, 3, 23, 40))))
    _, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert righe[2]["orari"] == [("11:00:00", ""), ("15:00:00", ""),
                                 ("—", "manca"), ("23:40:00", "")], \
        righe[2]["orari"]


@prova("cartellino: ordinarie + straordinario = lavorate, al secondo")
def _():
    g = giornata(dt.date(2026, 11, 5),
                 [(dt.datetime(2026, 11, 5, 9), dt.datetime(2026, 11, 5, 17, 0, 45))])
    g.secondi_straordinario = 45
    _, righe = C(persona(g), *NOV, ADESSO, OGGI)
    r = righe[4]
    assert (r["lavorate"], r["ordinarie"], r["straordinario"]) == \
        ("8:00:45", "8:00:00", "0:00:45"), r
    assert righe[5]["straordinario"] == ""


@prova("cartellino: in una giornata confermata il trattino e' grigio")
def _():
    g = giornata(dt.date(2026, 11, 3),
                 [(dt.datetime(2026, 11, 3, 19), None)])
    _, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert righe[2]["orari"][1] == ("—", "manca"), righe[2]["orari"]
    g.confermata_da = "segreteria"
    _, righe = C(persona(g), *NOV, ADESSO, OGGI)
    assert righe[2]["orari"][1] == ("—", "confermata"), righe[2]["orari"]


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
