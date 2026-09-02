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
    g.minuti_lavorati = sum(t.minuti for t in turni)
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
    assert g.turni[0].minuti == 0, "il motore ha iniziato a contare i turni aperti"


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
    assert anna["minuti"] == 600, anna["minuti"]
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


@prova("ore e minuti: formato costante anche oltre le ventiquattro")
def _():
    assert gestione.ore_e_minuti(0) == "0:00"
    assert gestione.ore_e_minuti(59) == "0:59"
    assert gestione.ore_e_minuti(480) == "8:00"
    assert gestione.ore_e_minuti(12345) == "205:45"


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
