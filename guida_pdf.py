#!/usr/bin/env python3
"""
Stampa la guida in PDF, per chi la vuole su carta o da mandare per mail.

    python guida_pdf.py

Il testo e le figure sono gli STESSI della guida dentro il programma: si
leggono da `guida.CAPITOLI`, non si riscrivono. Se un giorno si divaricassero,
il manuale stampato racconterebbe un programma che non esiste più — ed è il
genere di errore che nessuno nota finché non è in mano al cliente.

Si compone una pagina HTML e la si fa stampare a Microsoft Edge in modalità
senza finestra. Nessuna libreria da installare: Edge c'è su ogni Windows, e
impagina bene. Se un domani Edge non ci fosse, la pagina HTML resta comunque
lì accanto e si stampa da qualunque browser.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys

CARTELLA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CARTELLA)

import guida                                                   # noqa: E402

FIGURE = os.path.join(CARTELLA, "guida")
USCITA_HTML = os.path.join(CARTELLA, "guida", "_guida.html")
USCITA_PDF = os.path.join(CARTELLA, "TIMBRA - guida.pdf")

EDGE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _esc(testo: str) -> str:
    return (str(testo).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _immagine(nome: str) -> str:
    """L'immagine murata dentro la pagina, non collegata: così il file HTML
    si può spostare, mandare e archiviare da solo."""
    percorso = os.path.join(FIGURE, nome)
    if not os.path.exists(percorso):
        return ""
    with open(percorso, "rb") as f:
        dati = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{dati}"


def _logo() -> str:
    percorso = os.path.join(CARTELLA, "logo", "timbra-segno.png")
    dato = ""
    if os.path.exists(percorso):
        with open(percorso, "rb") as f:
            dato = base64.b64encode(f.read()).decode("ascii")
    if not dato:
        return ""
    return (f'<img class="segno" src="data:image/png;base64,{dato}" '
            f'alt="TIMBRA">')


STILE = """
@page { size: A4; margin: 18mm 16mm 16mm 16mm; }
* { box-sizing: border-box; }
body { font: 11.5pt/1.55 "Segoe UI", Arial, sans-serif; color: #1d1f20;
       margin: 0; }
h1 { font-size: 21pt; margin: 0 0 4pt; color: #1d1f20; }
h2 { font-size: 15pt; margin: 22pt 0 6pt; color: #3f5c7a;
     page-break-after: avoid; }
p { margin: 0 0 9pt; }
ul { margin: 0 0 10pt; padding-left: 18pt; }
li { margin: 0 0 4pt; }
li::marker { color: #5980a6; }
figure { margin: 12pt 0 14pt; page-break-inside: avoid; }
figure img { max-width: 100%; border: 1px solid #c9ced6; border-radius: 3px;
             display: block; }
figcaption { font-size: 9pt; color: #6b7280; margin-top: 4pt; }
.capitolo { page-break-before: always; }
.copertina { text-align: center; padding-top: 40mm; }
.copertina .segno { width: 34mm; margin: 0 auto 8mm; display: block; }
.copertina .nome { font-size: 40pt; font-weight: 700; letter-spacing: 3pt;
                   margin: 0; }
.copertina .sotto { font-size: 13pt; letter-spacing: 6pt; color: #3f5c7a;
                    margin: 2mm 0 0; }
.copertina .riga { font-size: 11pt; color: #55585a; margin-top: 14mm; }
.indice { page-break-before: always; }
.indice ol { padding-left: 20pt; }
.indice li { margin-bottom: 6pt; font-size: 12pt; }
.piede { margin-top: 16mm; font-size: 9pt; color: #6b7280;
         border-top: 1px solid #e0e3e8; padding-top: 4mm; }
"""


def componi_html() -> str:
    pezzi = [
        "<!doctype html><html lang='it'><head><meta charset='utf-8'>",
        "<title>TIMBRA — guida</title>",
        f"<style>{STILE}</style></head><body>",
        "<section class='copertina'>",
        _logo(),
        "<p class='nome'>TIMBRA</p>",
        "<p class='sotto'>P R E S E N Z E</p>",
        "<p class='riga'>Guida per chi la usa</p>",
        "<p class='riga' style='margin-top:4mm'>Nicola Bonazzi &middot; "
        "Andrea D'Aniello</p>",
        "</section>",
        "<section class='indice'><h1>Cosa c'è dentro</h1><ol>",
    ]
    for titolo, _ in guida.CAPITOLI:
        pezzi.append(f"<li>{_esc(titolo)}</li>")
    pezzi.append("</ol>")
    pezzi.append(
        "<p class='piede'>Le figure di questa guida sono fatte su un "
        "archivio inventato: i nomi non sono di nessuno. La stessa guida è "
        "dentro il programma, col «?» in alto a destra.</p></section>")

    for titolo, blocchi in guida.CAPITOLI:
        pezzi.append(f"<section class='capitolo'><h1>{_esc(titolo)}</h1>")
        elenco_aperto = False
        for blocco in blocchi:
            if blocco.startswith("- "):
                if not elenco_aperto:
                    pezzi.append("<ul>")
                    elenco_aperto = True
                pezzi.append(f"<li>{_esc(blocco[2:])}</li>")
                continue
            if elenco_aperto:
                pezzi.append("</ul>")
                elenco_aperto = False
            if blocco.startswith("# "):
                pezzi.append(f"<h2>{_esc(blocco[2:])}</h2>")
            elif blocco.startswith("! "):
                nome, _, didascalia = blocco[2:].partition("|")
                sorgente = _immagine(nome.strip())
                if not sorgente:
                    continue
                pezzi.append(f"<figure><img src='{sorgente}' alt=''>")
                if didascalia.strip():
                    pezzi.append(
                        f"<figcaption>{_esc(didascalia.strip())}</figcaption>")
                pezzi.append("</figure>")
            else:
                pezzi.append(f"<p>{_esc(blocco)}</p>")
        if elenco_aperto:
            pezzi.append("</ul>")
        pezzi.append("</section>")

    pezzi.append("</body></html>")
    return "".join(pezzi)


def stampa(html: str) -> int:
    with open(USCITA_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"pagina: {USCITA_HTML}  ({os.path.getsize(USCITA_HTML)/1024:.0f} KB)")

    edge = next((e for e in EDGE if os.path.exists(e)), None)
    if edge is None:
        print("Microsoft Edge non trovato: la pagina HTML e' pronta, si "
              "stampa in PDF da qualunque browser.")
        return 1
    if os.path.exists(USCITA_PDF):
        os.remove(USCITA_PDF)
    esito = subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={USCITA_PDF}",
         "file:///" + USCITA_HTML.replace("\\", "/")],
        capture_output=True, text=True, timeout=180)
    if not os.path.exists(USCITA_PDF):
        print("stampa non riuscita:", (esito.stderr or "")[-400:])
        return 1
    print(f"PDF   : {USCITA_PDF}  "
          f"({os.path.getsize(USCITA_PDF)/1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(stampa(componi_html()))
