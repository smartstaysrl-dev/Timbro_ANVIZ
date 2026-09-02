#!/usr/bin/env python3
"""
Fa l'icona di TIMBRA (`logo/timbra.ico`) dal segno del marchio.

    python crea_icona.py

Il segno si disegna su una tela Tk — le stesse curve del logo — e poi si
fotografa. Serve Pillow, ma SOLO qui: il programma non lo usa. L'icona si
rifà una volta sola e finisce sotto git, quindi in sede non serve niente.

Perché non si converte l'SVG: le librerie che lo fanno sono megabyte di
dipendenze per un disegno di due curve che sappiamo già disegnare.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk

CARTELLA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CARTELLA)

import logo                                                    # noqa: E402

LATO = 512                      # si disegna grande e si rimpicciolisce
BORDO = 0.14                    # aria intorno al segno
MISURE = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
          (256, 256)]


def main() -> int:
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Per rifare l'icona serve Pillow:  pip install pillow")
        print("(il programma vero non lo usa: e' solo per questo strumento)")
        return 1

    x0, y0, x1, y1 = logo.RIQUADRO_SEGNO
    largo, alto = x1 - x0, y1 - y0
    utile = LATO * (1 - 2 * BORDO)
    scala = utile / max(largo, alto)
    dx = (LATO - largo * scala) / 2 - x0 * scala
    dy = (LATO - alto * scala) / 2 - y0 * scala

    radice = tk.Tk()
    radice.overrideredirect(True)
    radice.attributes("-topmost", True)
    radice.geometry(f"{LATO}x{LATO}+40+40")
    tela = tk.Canvas(radice, width=LATO, height=LATO, bg=logo.FONDO,
                     highlightthickness=0)
    tela.pack()
    logo.disegna_segno(tela, scala, dx, dy)
    radice.update()
    radice.geometry(f"+40+40")
    radice.update()
    time.sleep(0.5)

    x, y = radice.winfo_rootx(), radice.winfo_rooty()
    immagine = ImageGrab.grab(bbox=(x, y, x + LATO, y + LATO))
    radice.destroy()

    os.makedirs(os.path.join(CARTELLA, "logo"), exist_ok=True)
    percorso = os.path.join(CARTELLA, "logo", "timbra.ico")
    immagine.convert("RGB").save(percorso, format="ICO", sizes=MISURE)
    anteprima = os.path.join(CARTELLA, "logo", "timbra-segno.png")
    immagine.save(anteprima)
    print(f"icona: {percorso}  ({os.path.getsize(percorso) / 1024:.0f} KB)")
    print(f"segno: {anteprima}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
