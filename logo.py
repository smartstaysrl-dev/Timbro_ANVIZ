#!/usr/bin/env python3
"""
Il marchio TIMBRA, disegnato a mano su una tela Tk.

L'originale è un SVG (`logo/timbra-logo.svg`), ma Tkinter l'SVG non lo sa
leggere e le librerie che lo convertono sono megabyte di dipendenze — su un
registratore di cassa ogni dipendenza in più è un'installazione che può andare
storta. Le due curve sono cubiche di Bézier, e la tela Tk le disegna native
con `smooth="raw"`: stessi punti dell'SVG, stesse tinte, nitido a qualunque
ingrandimento perché non è un'immagine, è un disegno.

Se il carattere del logo (Barlow Condensed) non è installato — e su Windows
non lo è quasi mai — si ripiega su quello di sistema: cambia il disegno delle
lettere, non il marchio.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

# Le tinte dell'originale.
AZZURRO = "#5980a6"
BLU = "#3f5c7a"
NERO = "#1d1f20"
GRIGIO = "#55585a"
FONDO = "#ffffff"

# I due tratti del segno, presi dai `path` dell'SVG. In `smooth="raw"` la
# tela vuole i punti nell'ordine: partenza, due controlli, arrivo, e cosi'
# via — esattamente come li scrive un comando C dell'SVG.
ARCO_CHIARO = [
    (8, 42), (8, 23.3), (25.5, 12), (42, 12),
    (58.5, 12), (67, 28.25), (67, 42),
    (67, 55.75), (52.45, 61), (42, 61),
    (31.55, 61), (29, 49.15), (29, 42),
    (29, 34.85), (38.15, 35), (42, 35),
]
ARCO_SCURO = ARCO_CHIARO[:7]

SPESSORE = 11
SCALA_SEGNO = 1.55
LARGO, ALTO = 700, 270          # il riquadro dell'originale

TITOLO = "TIMBRA"
SOTTOTITOLO = "PRESENZE"
FIRMA = "Nicola Bonazzi - Andrea D'Aniello"


def _carattere(dimensione: int, grassetto: bool = False):
    """Barlow Condensed se c'e', altrimenti il carattere di sistema."""
    disponibili = set(tkfont.families())
    for nome in ("Barlow Condensed", "Barlow", "Segoe UI Semibold", "Segoe UI"):
        if nome in disponibili:
            return (nome, dimensione, "bold" if grassetto else "normal")
    return ("TkDefaultFont", dimensione, "bold" if grassetto else "normal")


def disegna(tela: tk.Canvas, scala: float = 1.0, dx: float = 0.0,
            dy: float = 0.0) -> None:
    """Disegna il marchio sulla tela, in scala."""
    def punti(elenco, tx, ty, s):
        fuori = []
        for x, y in elenco:
            fuori += [dx + (tx + x * s) * scala, dy + (ty + y * s) * scala]
        return fuori

    for tratto, colore in ((ARCO_CHIARO, AZZURRO), (ARCO_SCURO, BLU)):
        tela.create_line(
            *punti(tratto, 40, 62, SCALA_SEGNO), fill=colore,
            width=max(1, SPESSORE * SCALA_SEGNO * scala), smooth="raw",
            splinesteps=48, capstyle="round")

    tela.create_text(dx + 228 * scala, dy + 116 * scala, anchor="sw",
                     text=TITOLO, fill=NERO,
                     font=_carattere(max(8, round(86 * scala)), True))
    tela.create_text(dx + 230 * scala, dy + 152 * scala, anchor="sw",
                     text=" ".join(SOTTOTITOLO), fill=BLU,
                     font=_carattere(max(6, round(24 * scala))))
    tela.create_text(dx + 231 * scala, dy + 205 * scala, anchor="sw",
                     text=FIRMA, fill=GRIGIO,
                     font=_carattere(max(6, round(22 * scala))))


class Marchio(tk.Canvas):
    """Il logo come widget, su fondo chiaro."""

    def __init__(self, padre, scala: float = 1.0, fondo: str = FONDO, **kw):
        super().__init__(padre, bg=fondo, highlightthickness=0,
                         width=round(LARGO * scala),
                         height=round(ALTO * scala), **kw)
        disegna(self, scala)


class Splash(tk.Toplevel):
    """La finestrella che si vede mentre il programma si prepara.

    Non e' decorazione fine a se stessa: aprire l'archivio, calcolare le
    presenze e far partire lo scheduler prende qualche istante, e uno schermo
    nero in quel momento fa pensare che il doppio clic non abbia funzionato —
    col risultato che qualcuno ne apre un secondo.
    """

    def __init__(self, padre, scala: float = 0.62):
        super().__init__(padre)
        self.overrideredirect(True)
        self.configure(bg=FONDO)
        cornice = tk.Frame(self, bg=FONDO, highlightthickness=1,
                           highlightbackground=BLU)
        cornice.pack(fill="both", expand=True)
        Marchio(cornice, scala).pack(padx=26, pady=(20, 6))
        self.stato = tk.Label(cornice, text="apertura in corso...", bg=FONDO,
                              fg=GRIGIO, font=_carattere(12))
        self.stato.pack(pady=(0, 18))
        self.update_idletasks()
        larghezza, altezza = self.winfo_reqwidth(), self.winfo_reqheight()
        x = (self.winfo_screenwidth() - larghezza) // 2
        y = (self.winfo_screenheight() - altezza) // 3
        self.geometry(f"{larghezza}x{altezza}+{max(0, x)}+{max(0, y)}")
        self.attributes("-topmost", True)
        self.update()

    def scrivi(self, testo: str) -> None:
        try:
            self.stato.config(text=testo)
            self.update_idletasks()
        except tk.TclError:
            pass


if __name__ == "__main__":                       # anteprima: python logo.py
    radice = tk.Tk()
    radice.title("TIMBRA — marchio")
    radice.configure(bg=FONDO)
    Marchio(radice, 1.0).pack(padx=20, pady=20)
    radice.mainloop()
