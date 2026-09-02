"""Collaudo del PIN, del recupero e dell'offuscamento.

Non si sta collaudando una cassaforte — vedi il commento in testa a
sicurezza.py — ma le promesse che il modulo fa devono valere tutte: il PIN in
chiaro non finisce su disco, la finestra di sblocco scade davvero, e il codice
di recupero non si azzecca per caso.
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
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


class Cronometro:
    """Un orologio monotono finto, per far scadere la finestra a comando."""

    def __init__(self):
        self.secondi = 1000.0

    def __call__(self):
        return self.secondi

    def avanti(self, minuti):
        self.secondi += minuti * 60

    def indietro(self, minuti):
        self.secondi -= minuti * 60


def serratura(**extra):
    cfg = dict(extra)
    salvataggi = []
    s = sicurezza.Serratura(cfg, lambda: salvataggi.append(dict(cfg)))
    return s, cfg, salvataggi


@prova("PIN di fabbrica: entra con 12345 e con nient'altro")
def _():
    s, _, _ = serratura()
    assert s.verifica("12345")
    for sbagliato in ("1234", "123456", "", "  ", "54321", None):
        assert not s.verifica(sbagliato), f"accettato {sbagliato!r}"
    assert not s.personalizzato()


@prova("PIN cambiato: vale il nuovo, non piu' il vecchio")
def _():
    s, cfg, salvataggi = serratura()
    s.cambia("90210")
    assert s.personalizzato()
    assert s.verifica("90210")
    assert not s.verifica("12345"), "il PIN di fabbrica apre ancora"
    assert salvataggi, "il cambio non e' stato salvato"


@prova("il PIN in chiaro non finisce mai nella configurazione")
def _():
    s, cfg, _ = serratura()
    s.cambia("86420")
    scritto = repr(cfg)
    assert "86420" not in scritto, f"il PIN si legge in chiaro: {scritto}"
    assert cfg["pin_sale"] and cfg["pin_impronta"]
    # Due installazioni con lo stesso PIN non devono avere la stessa impronta,
    # altrimenti basta un confronto per sapere chi ha lasciato quello di serie.
    s2, cfg2, _ = serratura()
    s2.cambia("86420")
    assert cfg["pin_impronta"] != cfg2["pin_impronta"], "il sale non serve a nulla"


@prova("PIN non validi: rifiutati, e il vecchio resta buono")
def _():
    s, _, _ = serratura()
    s.cambia("11111")
    for cattivo in ("123", "1" * 9, "12a45", "12 45", "", "  "):
        try:
            s.cambia(cattivo)
            assert False, f"accettato {cattivo!r}"
        except ValueError:
            pass
    assert s.verifica("11111"), "un PIN rifiutato ha comunque cambiato quello buono"


@prova("recupero col numero di serie: intero o ultime sei cifre")
def _():
    seriale = "0690200024380174"
    s, cfg, _ = serratura(terminale_seriale=seriale)
    s.cambia("77777")
    assert not s.recupera("000000"), "codice sbagliato accettato"
    assert s.verifica("77777"), "un recupero fallito ha cambiato il PIN"
    assert s.recupera(seriale[-6:]), "le ultime sei cifre non funzionano"
    assert s.verifica(sicurezza.PIN_PREDEFINITO)
    assert not s.personalizzato()

    s2, _, _ = serratura(terminale_seriale=seriale)
    s2.cambia("77777")
    assert s2.recupera(seriale), "il seriale intero non funziona"


@prova("recupero: niente scorciatoie con codici corti o parziali")
def _():
    seriale = "0690200024380174"
    s, _, _ = serratura(terminale_seriale=seriale)
    s.cambia("77777")
    for cattivo in ("", "0", "069020", "38017", "380174 ", "0174",
                    seriale[:6], seriale[-7:], seriale + "0"):
        if cattivo.strip() == seriale[-6:] or cattivo.strip() == seriale:
            continue                       # questi due DEVONO funzionare
        assert not s.recupera(cattivo), f"accettato {cattivo!r}"
    assert s.verifica("77777"), "il PIN e' stato azzerato da un codice sbagliato"


@prova("senza seriale non c'e' recupero, e il PIN resta quello che era")
def _():
    s, _, _ = serratura()
    s.cambia("55555")
    assert not s.codice_di_recupero_disponibile()
    assert not s.recupera("0690200024380174")
    assert s.verifica("55555")


@prova("la finestra di sblocco scade da sola")
def _():
    orologio = Cronometro()
    s = sicurezza.Serratura({}, None, orologio)
    assert not s.aperta(), "nasce aperta"
    s.sblocca()
    assert s.aperta()
    orologio.avanti(sicurezza.MINUTI_SBLOCCO - 1)
    assert s.aperta(), "chiusa prima del tempo"
    assert s.minuti_rimasti() == 1, s.minuti_rimasti()
    orologio.avanti(2)
    assert not s.aperta(), "non e' scaduta"
    assert s.minuti_rimasti() == 0, s.minuti_rimasti()


@prova("l'ora di sistema spostata indietro NON allunga la finestra")
def _():
    # Alla fine dell'ora legale l'orologio a muro torna indietro di un'ora:
    # misurando la scadenza su quello, il PIN resterebbe aperto per settanta
    # minuti invece di quindici. Si usa un orologio che non torna indietro.
    orologio = Cronometro()
    s = sicurezza.Serratura({}, None, orologio)
    s.sblocca()
    orologio.avanti(sicurezza.MINUTI_SBLOCCO + 1)
    assert not s.aperta()
    orologio.indietro(60)
    assert not s.aperta(), "un salto all'indietro l'ha riaperta"


@prova("recupero con un seriale corto: il seriale intero deve bastare")
def _():
    s, _, _ = serratura(terminale_seriale="1234")
    s.cambia("99999")
    assert s.codice_di_recupero_disponibile()
    assert s.recupera("1234"),         "recupero dichiarato disponibile ma nessun codice puo' funzionare"
    assert s.verifica(sicurezza.PIN_PREDEFINITO)


@prova("richiudere a mano funziona subito")
def _():
    s, _, _ = serratura()
    s.sblocca()
    assert s.aperta()
    s.chiudi()
    assert not s.aperta()
    assert s.minuti_rimasti() == 0


@prova("offuscamento: torna identico, e non si legge a occhio")
def _():
    for testo in ("password", "pàsswòrd con àccenti", "1234!\"£$%&/()=",
                  "x" * 200, "off:non-e-davvero-offuscata"):
        nascosto = sicurezza.offusca(testo)
        assert sicurezza.svela(nascosto) == testo, f"perso: {testo!r}"
        assert testo not in nascosto, f"si legge in chiaro: {nascosto}"
    assert sicurezza.offusca("") == ""
    assert sicurezza.svela("") == ""
    # Una password scritta a mano nel file, senza prefisso, si prende com'e':
    # altrimenti chi corregge il JSON a mano non riesce piu' a spedire.
    assert sicurezza.svela("scritta-a-mano") == "scritta-a-mano"
    # Spazzatura dopo il prefisso non deve far esplodere l'invio.
    assert sicurezza.svela("off:@@@non-base64@@@") == ""


falliti = [(n, e) for n, e in esiti if e]
for nome, errore in esiti:
    print(("  OK   " if not errore else "  FALLITO ") + nome
          + (f"\n          {errore}" if errore else ""))
print(f"\n{len(esiti) - len(falliti)}/{len(esiti)} prove superate")
sys.exit(1 if falliti else 0)
