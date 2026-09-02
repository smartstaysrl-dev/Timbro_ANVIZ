#!/usr/bin/env python3
"""
Mattoni dell'interfaccia touch: bottoni, liste trascinabili, tastiere a
schermo, finestre di attesa. Tenuti separati dalle schermate perche' sono
codice di libreria, non logica dell'applicazione.

Regole rispettate ovunque qui dentro:
  - nessun bersaglio piu' piccolo di 60 pixel;
  - nessuna funzione raggiungibile solo con doppio clic, tasto destro o hover:
    col dito non esistono;
  - il riscontro visivo e' legato alla pressione, non al passaggio del mouse;
  - qualunque campo di testo si puo' riempire senza tastiera fisica.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import tkinter as tk

# --- Tavolozza ---------------------------------------------------------------
BG = "#1E1E2E"
CARD = "#313244"
CARD_CHIARA = "#45475A"
TESTO = "#CDD6F4"
TESTO_TENUE = "#9399B2"
VERDE = "#A6E3A1"
ROSSO = "#F38BA8"
GIALLO = "#F9E2AF"
BLU = "#89B4FA"
VIOLA = "#CBA6F7"

F_ENORME = ("Segoe UI", 26, "bold")
F_TITOLO = ("Segoe UI", 20, "bold")
F_GRANDE = ("Segoe UI", 15)
F_NORMALE = ("Segoe UI", 12)
F_PICCOLO = ("Segoe UI", 10)
F_MONO = ("Consolas", 11)

ALTEZZA_TOCCO = 60


def abilita_dpi() -> None:
    """Senza questo, su uno schermo touch moderno l'interfaccia esce sfocata."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# --- Bottone -----------------------------------------------------------------
class Bottone(tk.Frame):
    def __init__(self, padre, testo, comando, colore=CARD, colore_testo=TESTO,
                 font=F_GRANDE, altezza=ALTEZZA_TOCCO, larghezza=None,
                 attivo=True):
        super().__init__(padre, bg=colore, height=altezza)
        self.pack_propagate(False)
        if larghezza:
            self.config(width=larghezza)
        self.colore = colore
        self.comando = comando
        self.attivo = attivo
        self.etichetta = tk.Label(self, text=testo, bg=colore,
                                  fg=colore_testo if attivo else TESTO_TENUE,
                                  font=font, cursor="hand2", wraplength=0)
        self.etichetta.pack(expand=True, fill="both")
        for w in (self, self.etichetta):
            w.bind("<ButtonPress-1>", self._premuto)
            w.bind("<ButtonRelease-1>", self._rilasciato)

    def _premuto(self, _):
        if self.attivo:
            self.config(bg=CARD_CHIARA)
            self.etichetta.config(bg=CARD_CHIARA)

    def _rilasciato(self, _):
        self.config(bg=self.colore)
        self.etichetta.config(bg=self.colore)
        if self.attivo:
            self.comando()

    def testo(self, nuovo):
        self.etichetta.config(text=nuovo)

    def tinta(self, colore, colore_testo=None):
        self.colore = colore
        self.config(bg=colore)
        self.etichetta.config(bg=colore)
        if colore_testo:
            self.etichetta.config(fg=colore_testo)


class Interruttore(tk.Frame):
    """Acceso/spento. Un solo tocco, stato sempre visibile senza hover."""

    def __init__(self, padre, testo, valore=False, al_cambio=None):
        super().__init__(padre, bg=CARD, height=ALTEZZA_TOCCO)
        self.pack_propagate(False)
        self.valore = bool(valore)
        self.al_cambio = al_cambio
        tk.Label(self, text=testo, bg=CARD, fg=TESTO, font=F_NORMALE,
                 anchor="w").pack(side="left", padx=16)
        self.spia = tk.Label(self, text="", bg=CARD, font=F_NORMALE, width=10)
        self.spia.pack(side="right", padx=16)
        for w in (self, self.spia):
            w.bind("<ButtonRelease-1>", self._premuto)
        self._disegna()

    def _premuto(self, _):
        self.valore = not self.valore
        self._disegna()
        if self.al_cambio:
            self.al_cambio(self.valore)

    def _disegna(self):
        self.spia.config(text="SI" if self.valore else "no",
                         fg=VERDE if self.valore else TESTO_TENUE)


# --- Lista scorrevole col dito ------------------------------------------------
class ListaScorrevole(tk.Frame):
    def __init__(self, padre, **kw):
        super().__init__(padre, bg=BG, **kw)
        self.tela = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.tela.pack(fill="both", expand=True)
        self.interno = tk.Frame(self.tela, bg=BG)
        self.finestra = self.tela.create_window((0, 0), window=self.interno,
                                                anchor="nw")
        self.interno.bind("<Configure>", self._ridimensiona)
        self.tela.bind("<Configure>", self._adatta_larghezza)
        self._y0 = 0
        self.tela.bind("<ButtonPress-1>", self._inizio, add="+")
        self.tela.bind("<B1-Motion>", self._trascina, add="+")
        self.tela.bind("<MouseWheel>", self._rotella)
        self.tela.bind("<Enter>",
                       lambda _: self.tela.bind_all("<MouseWheel>", self._rotella))
        self.tela.bind("<Leave>",
                       lambda _: self.tela.unbind_all("<MouseWheel>"))

    def _ridimensiona(self, _):
        self.tela.configure(scrollregion=self.tela.bbox("all"))

    def _adatta_larghezza(self, evento):
        self.tela.itemconfig(self.finestra, width=evento.width)

    def _inizio(self, evento):
        self._y0 = evento.y_root

    def _trascina(self, evento):
        delta = self._y0 - evento.y_root
        self._y0 = evento.y_root
        self.tela.yview_scroll(int(delta / 2), "units")

    def _rotella(self, evento):
        try:
            self.tela.yview_scroll(int(-evento.delta / 60), "units")
        except tk.TclError:
            pass

    def segui_trascinamento(self, widget):
        """Rende trascinabile anche il contenuto, non solo lo sfondo."""
        widget.bind("<ButtonPress-1>", self._inizio, add="+")
        widget.bind("<B1-Motion>", self._trascina, add="+")
        for figlio in widget.winfo_children():
            self.segui_trascinamento(figlio)

    def svuota(self):
        for w in self.interno.winfo_children():
            w.destroy()
        self.tela.yview_moveto(0)


# --- Finestre di dialogo ------------------------------------------------------
class Dialogo(tk.Toplevel):
    """Base comune: modale, scura, centrata sul genitore."""

    def __init__(self, padre, titolo):
        super().__init__(padre)
        self.title(titolo)
        self.configure(bg=BG)
        self.transient(padre)
        self.risultato = None
        self.resizable(False, False)

    def concludi(self):
        self.update_idletasks()
        p = self.master
        x = p.winfo_rootx() + (p.winfo_width() - self.winfo_width()) // 2
        y = p.winfo_rooty() + (p.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.wait_window(self)
        return self.risultato


class TastieraTouch(Dialogo):
    RIGHE = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]

    def __init__(self, padre, titolo, iniziale=""):
        super().__init__(padre, titolo)
        self.maiuscolo = True
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(pady=(18, 8))
        self.variabile = tk.StringVar(value=iniziale)
        tk.Entry(self, textvariable=self.variabile, font=("Segoe UI", 22),
                 bg=CARD, fg=TESTO, relief="flat", justify="center",
                 insertbackground=TESTO).pack(fill="x", padx=24, ipady=12,
                                              pady=(0, 14))
        tasti = tk.Frame(self, bg=BG)
        tasti.pack(padx=16, pady=(0, 10))
        self.tasti_lettera = []
        for riga in self.RIGHE:
            f = tk.Frame(tasti, bg=BG)
            f.pack(pady=3)
            for ch in riga:
                b = Bottone(f, ch, lambda c=ch: self._aggiungi(c),
                            font=F_GRANDE, altezza=56, larghezza=56)
                b.pack(side="left", padx=3)
                self.tasti_lettera.append((b, ch))
        ultima = tk.Frame(tasti, bg=BG)
        ultima.pack(pady=3)
        Bottone(ultima, "maiusc", self._cambia_maiuscolo, font=F_NORMALE,
                altezza=56, larghezza=96).pack(side="left", padx=3)
        Bottone(ultima, "spazio", lambda: self._aggiungi(" "), font=F_NORMALE,
                altezza=56, larghezza=200).pack(side="left", padx=3)
        Bottone(ultima, "cancella", self._cancella, font=F_NORMALE,
                altezza=56, larghezza=120).pack(side="left", padx=3)
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=24, pady=(6, 20))
        Bottone(azioni, "Annulla", self.destroy, altezza=64,
                larghezza=200).pack(side="left")
        Bottone(azioni, "Conferma", self._conferma, colore=VERDE,
                colore_testo=BG, altezza=64, larghezza=200).pack(side="right")

    def _aggiungi(self, ch):
        self.variabile.set(self.variabile.get() +
                           (ch if self.maiuscolo else ch.lower()))

    def _cancella(self):
        self.variabile.set(self.variabile.get()[:-1])

    def _cambia_maiuscolo(self):
        self.maiuscolo = not self.maiuscolo
        for b, ch in self.tasti_lettera:
            b.testo(ch if self.maiuscolo else ch.lower())

    def _conferma(self):
        self.risultato = self.variabile.get().strip()
        self.destroy()

    @staticmethod
    def chiedi(padre, titolo, iniziale=""):
        return TastieraTouch(padre, titolo, iniziale).concludi()


class TastierinoNumerico(Dialogo):
    def __init__(self, padre, titolo, iniziale="", nota=""):
        super().__init__(padre, titolo)
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(pady=(18, 4))
        if nota:
            tk.Label(self, text=nota, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                     wraplength=380).pack(pady=(0, 8))
        self.variabile = tk.StringVar(value=str(iniziale or ""))
        tk.Entry(self, textvariable=self.variabile, font=("Consolas", 28),
                 bg=CARD, fg=TESTO, relief="flat", justify="center",
                 insertbackground=TESTO).pack(fill="x", padx=24, ipady=14,
                                              pady=(0, 14))
        griglia = tk.Frame(self, bg=BG)
        griglia.pack(padx=24, pady=(0, 10))
        for r, riga in enumerate((("1", "2", "3"), ("4", "5", "6"),
                                  ("7", "8", "9"), ("vuoto", "0", "canc"))):
            f = tk.Frame(griglia, bg=BG)
            f.pack(pady=4)
            for ch in riga:
                if ch == "vuoto":
                    b = Bottone(f, "azzera", lambda: self.variabile.set(""),
                                font=F_NORMALE, altezza=64, larghezza=110)
                elif ch == "canc":
                    b = Bottone(f, "←", self._cancella, font=F_TITOLO,
                                altezza=64, larghezza=110)
                else:
                    b = Bottone(f, ch, lambda c=ch: self._aggiungi(c),
                                font=F_TITOLO, altezza=64, larghezza=110)
                b.pack(side="left", padx=4)
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=24, pady=(6, 20))
        Bottone(azioni, "Annulla", self.destroy, altezza=64,
                larghezza=170).pack(side="left")
        Bottone(azioni, "Conferma", self._conferma, colore=VERDE,
                colore_testo=BG, altezza=64, larghezza=170).pack(side="right")

    def _aggiungi(self, ch):
        self.variabile.set(self.variabile.get() + ch)

    def _cancella(self):
        self.variabile.set(self.variabile.get()[:-1])

    def _conferma(self):
        self.risultato = self.variabile.get().strip()
        self.destroy()

    @staticmethod
    def chiedi(padre, titolo, iniziale="", nota=""):
        return TastierinoNumerico(padre, titolo, iniziale, nota).concludi()


class SceltaOra(Dialogo):
    """Ora e minuti con bottoni grandi: scriverla a mano col dito e' peggio."""

    def __init__(self, padre, titolo, iniziale: dt.time | None = None):
        super().__init__(padre, titolo)
        base = iniziale or dt.datetime.now().time()
        self.ora, self.minuto = base.hour, base.minute
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(pady=(18, 10))
        quadro = tk.Frame(self, bg=BG)
        quadro.pack(padx=30, pady=6)
        self.display = tk.Label(quadro, text="", bg=CARD, fg=TESTO,
                                font=("Consolas", 44), width=7)
        self.display.pack(pady=(0, 10), ipady=10)
        riga = tk.Frame(quadro, bg=BG)
        riga.pack()
        for testo, do, dm in (("ora −", -1, 0), ("ora +", 1, 0),
                              ("min −", 0, -1), ("min +", 0, 1)):
            Bottone(riga, testo, lambda a=do, b=dm: self._muovi(a, b),
                    font=F_NORMALE, altezza=64, larghezza=110).pack(side="left", padx=4)
        riga2 = tk.Frame(quadro, bg=BG)
        riga2.pack(pady=(8, 0))
        for testo, dm in (("−15", -15), ("−5", -5), ("+5", 5), ("+15", 15)):
            Bottone(riga2, testo, lambda b=dm: self._muovi(0, b),
                    font=F_NORMALE, altezza=56, larghezza=110).pack(side="left", padx=4)
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=30, pady=(16, 20))
        Bottone(azioni, "Annulla", self.destroy, altezza=64,
                larghezza=200).pack(side="left")
        Bottone(azioni, "Conferma", self._conferma, colore=VERDE,
                colore_testo=BG, altezza=64, larghezza=200).pack(side="right")
        self._disegna()

    def _muovi(self, do, dm):
        totale = (self.ora * 60 + self.minuto + do * 60 + dm) % (24 * 60)
        self.ora, self.minuto = divmod(totale, 60)
        self._disegna()

    def _disegna(self):
        self.display.config(text=f"{self.ora:02d}:{self.minuto:02d}")

    def _conferma(self):
        self.risultato = dt.time(self.ora, self.minuto)
        self.destroy()

    @staticmethod
    def chiedi(padre, titolo, iniziale=None):
        return SceltaOra(padre, titolo, iniziale).concludi()


class Scelta(Dialogo):
    """Un elenco di opzioni, una per bottone."""

    def __init__(self, padre, titolo, opzioni: list[tuple[str, object]],
                 nota=""):
        super().__init__(padre, titolo)
        tk.Label(self, text=titolo, bg=BG, fg=TESTO, font=F_TITOLO).pack(
            pady=(18, 4), padx=30)
        if nota:
            tk.Label(self, text=nota, bg=BG, fg=TESTO_TENUE, font=F_PICCOLO,
                     wraplength=460, justify="left").pack(padx=30, pady=(0, 10))
        corpo = tk.Frame(self, bg=BG)
        corpo.pack(fill="x", padx=30)
        for etichetta, valore in opzioni:
            Bottone(corpo, etichetta, lambda v=valore: self._scegli(v),
                    font=F_NORMALE, altezza=64).pack(fill="x", pady=4)
        Bottone(self, "Annulla", self.destroy, altezza=60,
                larghezza=200).pack(pady=(14, 20))

    def _scegli(self, valore):
        self.risultato = valore
        self.destroy()

    @staticmethod
    def chiedi(padre, titolo, opzioni, nota=""):
        return Scelta(padre, titolo, opzioni, nota).concludi()


class Conferma(Dialogo):
    def __init__(self, padre, titolo, testo, pericoloso=False):
        super().__init__(padre, titolo)
        tk.Label(self, text=titolo, bg=BG, fg=ROSSO if pericoloso else TESTO,
                 font=F_TITOLO).pack(pady=(20, 8), padx=36)
        tk.Label(self, text=testo, bg=BG, fg=TESTO, font=F_NORMALE,
                 wraplength=460, justify="left").pack(padx=36, pady=(0, 18))
        azioni = tk.Frame(self, bg=BG)
        azioni.pack(fill="x", padx=36, pady=(0, 22))
        Bottone(azioni, "No, annulla", self.destroy, altezza=64,
                larghezza=210).pack(side="left")
        Bottone(azioni, "Si, procedi", self._si,
                colore=ROSSO if pericoloso else VERDE, colore_testo=BG,
                altezza=64, larghezza=210).pack(side="right")

    def _si(self):
        self.risultato = True
        self.destroy()

    @staticmethod
    def chiedi(padre, titolo, testo, pericoloso=False):
        return bool(Conferma(padre, titolo, testo, pericoloso).concludi())


class Avviso(Dialogo):
    def __init__(self, padre, titolo, testo, colore=TESTO):
        super().__init__(padre, titolo)
        tk.Label(self, text=titolo, bg=BG, fg=colore, font=F_TITOLO).pack(
            pady=(20, 8), padx=36)
        tk.Label(self, text=testo, bg=BG, fg=TESTO, font=F_NORMALE,
                 wraplength=520, justify="left").pack(padx=36, pady=(0, 18))
        Bottone(self, "Ho capito", self.destroy, altezza=64,
                larghezza=240).pack(pady=(0, 22))

    @staticmethod
    def mostra(padre, titolo, testo, colore=TESTO):
        Avviso(padre, titolo, testo, colore).concludi()

    @staticmethod
    def errore(padre, testo):
        Avviso(padre, "Non ha funzionato", testo, ROSSO).concludi()


class Attesa(Dialogo):
    """Esegue un lavoro lento senza congelare l'interfaccia."""

    def __init__(self, padre, testo, lavoro):
        super().__init__(padre, "Attendere")
        self.overrideredirect(True)
        tk.Label(self, text=testo, bg=BG, fg=TESTO, font=F_GRANDE).pack(
            padx=48, pady=(30, 10))
        self.puntini = tk.Label(self, text="", bg=BG, fg=BLU, font=F_TITOLO)
        self.puntini.pack(pady=(0, 30))
        self._lavoro = lavoro
        self._esito = None
        self._errore = None
        self._finito = threading.Event()
        self._n = 0
        threading.Thread(target=self._esegui, daemon=True).start()
        self.after(120, self._batti)

    def _esegui(self):
        try:
            self._esito = self._lavoro()
        except Exception as e:                      # noqa: BLE001
            self._errore = e
        finally:
            self._finito.set()

    def _batti(self):
        if self._finito.is_set():
            self.risultato = (self._esito, self._errore)
            self.destroy()
            return
        self._n = (self._n + 1) % 4
        self.puntini.config(text="•" * self._n)
        self.after(220, self._batti)

    @staticmethod
    def esegui(padre, testo, lavoro):
        """Ritorna (esito, errore). L'errore non viene sollevato: si sceglie."""
        esito = Attesa(padre, testo, lavoro).concludi()
        return esito if esito else (None, None)
