#!/usr/bin/env python3
"""
Prepara la cartella da copiare in sede: TIMBRA che parte con un doppio clic,
senza installare niente sul computer del cliente.

    python crea_pacchetto.py

Dentro ci finisce un Python "incorporato" — la distribuzione ufficiale
ridotta, scaricata da python.org — più i sorgenti. Il ristoratore vede solo
un collegamento con l'icona.

**Perché non un .exe.** Un eseguibile fatto con PyInstaller e non firmato
digitalmente viene BLOCCATO da Smart App Control, che è acceso di serie sulle
installazioni pulite di Windows 11: non l'avviso che si scavalca con «esegui
comunque», proprio bloccato. In più gli antivirus lo segnalano come falso
positivo, perché la tecnica di impacchettamento è la stessa dei malware.
Questa cartella non ha nessuno dei due problemi, e per chi la usa è identica:
si fa doppio clic su un'icona. Il giorno che serve davvero un eseguibile
singolo, la strada è il certificato di firma, non un altro impacchettatore.

**Il Python incorporato non ha Tkinter**: la distribuzione ridotta lascia
fuori tcl/tk. Si copiano a mano dal Python installato qui — sono gli stessi
file, stessa versione, stessa architettura.
"""

from __future__ import annotations

import os
import shutil
import sys
import urllib.request
import zipfile

CARTELLA = os.path.dirname(os.path.abspath(__file__))
USCITA = os.path.join(CARTELLA, "pacchetto")
NOME = "TIMBRA"

# Quello che serve al programma. Le prove e gli strumenti da banco restano
# fuori: in sede non servono, e uno strumento che rifà le figure della guida
# accanto ai dati veri è solo un modo per fare danni.
SORGENTI = ["anviz.py", "presenze.py", "interfaccia.py", "gestione.py",
            "copie.py", "posta.py", "sicurezza.py", "guida.py", "logo.py",
            "bootstrap_dhcp.py"]
CARTELLE = ["guida", "logo"]

TKINTER = [("DLLs", "_tkinter.pyd"), ("DLLs", "tcl86t.dll"),
           ("DLLs", "tk86t.dll"), ("DLLs", "zlib1.dll")]


def scarica_python(destinazione: str) -> None:
    v = sys.version_info
    nome = f"python-{v.major}.{v.minor}.{v.micro}-embed-amd64.zip"
    url = f"https://www.python.org/ftp/python/{v.major}.{v.minor}.{v.micro}/{nome}"
    zip_locale = os.path.join(USCITA, nome)
    if not os.path.exists(zip_locale):
        print(f"  scarico {nome}...")
        os.makedirs(USCITA, exist_ok=True)
        urllib.request.urlretrieve(url, zip_locale)
    print("  scompatto...")
    with zipfile.ZipFile(zip_locale) as z:
        z.extractall(destinazione)


def aggiungi_tkinter(destinazione: str) -> None:
    base = sys.base_prefix
    for pezzi in TKINTER:
        sorgente = os.path.join(base, *pezzi)
        if os.path.exists(sorgente):
            shutil.copy2(sorgente, destinazione)
    # La libreria standard di Tkinter e i file di tcl/tk.
    shutil.copytree(os.path.join(base, "Lib", "tkinter"),
                    os.path.join(destinazione, "tkinter"), dirs_exist_ok=True)
    shutil.copytree(os.path.join(base, "tcl"),
                    os.path.join(destinazione, "tcl"), dirs_exist_ok=True)


def scrivi_percorsi(destinazione: str) -> None:
    """Il file _pth dice al Python incorporato dove cercare i moduli."""
    v = sys.version_info
    percorso = os.path.join(destinazione, f"python{v.major}{v.minor}._pth")
    with open(percorso, "w", encoding="ascii") as f:
        f.write(f"python{v.major}{v.minor}.zip\n")
        f.write(".\n")
        f.write("..\\app\n")           # i nostri moduli
        f.write("import site\n")


def scrivi_avvio(radice: str) -> None:
    """Due modi per partire: il collegamento (senza finestra nera) e un file
    di comandi di scorta, per quando il collegamento si perde in una copia."""
    with open(os.path.join(radice, f"{NOME}.bat"), "w", encoding="ascii") as f:
        f.write("@echo off\r\n")
        f.write('cd /d "%~dp0"\r\n')
        f.write('start "" "python\\pythonw.exe" "app\\gestione.py"\r\n')

    with open(os.path.join(radice, "LEGGIMI.txt"), "w",
              encoding="utf-8") as f:
        f.write(
            "TIMBRA — presenze\n"
            "=================\n\n"
            "Per partire: doppio clic su TIMBRA (l'icona con la spirale).\n"
            "Se il collegamento si perde, va bene anche TIMBRA.bat.\n\n"
            "Non serve installare niente: il Python sta dentro la cartella\n"
            "python\\ e non tocca il resto del computer.\n\n"
            "Cosa c'e' dentro:\n"
            "  app\\     il programma. Si sostituisce per aggiornare.\n"
            "  dati\\    archivio delle timbrature, impostazioni, copie di\n"
            "           sicurezza. QUESTA NON SI TOCCA MAI.\n"
            "  python\\  il motore. Non serve guardarci dentro.\n\n"
            "Per aggiornare: si chiude il programma, si sostituisce la sola\n"
            "cartella app\\ con quella nuova, si riapre. I dati restano.\n\n"
            "Per il backup: si copia tutta la cartella TIMBRA, o almeno\n"
            "dati\\ che e' quella che conta.\n\n"
            "La cartella si puo' spostare dove si vuole, basta spostarla\n"
            "INTERA.\n\n"
            "La guida sta dentro il programma, col «?» in alto a destra.\n")


def crea_collegamento(radice: str) -> None:
    """Il collegamento con l'icona. Si usa pythonw.exe, non python.exe:
    altrimenti a ogni avvio compare anche una finestra nera di console che
    resta li' finche' il programma e' aperto, e che qualcuno prima o poi
    chiude credendo di chiudere una cosa inutile."""
    if sys.platform != "win32":
        print("  (il collegamento si crea solo su Windows)")
        return
    import subprocess
    lnk = os.path.join(radice, f"{NOME}.lnk")
    icona = os.path.join(radice, "app", "logo", "timbra.ico")
    comandi = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$l = $ws.CreateShortcut('{lnk}'); "
        f"$l.TargetPath = '{os.path.join(radice, 'python', 'pythonw.exe')}'; "
        "$l.Arguments = 'gestione.py'; "
        f"$l.WorkingDirectory = '{os.path.join(radice, 'app')}'; "
        f"$l.IconLocation = '{icona}'; "
        "$l.Description = 'TIMBRA - presenze'; "
        "$l.Save()")
    esito = subprocess.run(["powershell", "-NoProfile", "-Command", comandi],
                           capture_output=True, text=True)
    if esito.returncode or not os.path.exists(lnk):
        print("  ATTENZIONE: collegamento non creato:",
              (esito.stderr or "").strip()[:200])
        print("  resta comunque TIMBRA.bat, che funziona uguale.")
    else:
        print(f"  collegamento: {os.path.basename(lnk)}")


def main() -> int:
    radice = os.path.join(USCITA, NOME)
    if os.path.exists(radice):
        print(f"tolgo il pacchetto vecchio: {radice}")
        shutil.rmtree(radice)
    os.makedirs(radice)

    print("Python incorporato:")
    dentro_python = os.path.join(radice, "python")
    scarica_python(dentro_python)
    print("  aggiungo Tkinter (la distribuzione ridotta non ce l'ha)")
    aggiungi_tkinter(dentro_python)
    scrivi_percorsi(dentro_python)

    print("sorgenti:")
    app = os.path.join(radice, "app")
    os.makedirs(app)
    for nome in SORGENTI:
        shutil.copy2(os.path.join(CARTELLA, nome), app)
    for cartella in CARTELLE:
        sorgente = os.path.join(CARTELLA, cartella)
        if os.path.isdir(sorgente):
            shutil.copytree(sorgente, os.path.join(app, cartella),
                            ignore=shutil.ignore_patterns("_finto.db*"))
    print(f"  {len(SORGENTI)} file + {len(CARTELLE)} cartelle")

    # La cartella dei dati nasce vuota, accanto al codice e non dentro:
    # aggiornare vuol dire sostituire "app", e quello che sta li' dentro deve
    # poter sparire senza portarsi via un anno di timbrature.
    os.makedirs(os.path.join(radice, "dati"), exist_ok=True)

    scrivi_avvio(radice)
    crea_collegamento(radice)
    peso = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(radice) for f in fs)
    print(f"pronto: {radice}  ({peso / 1_000_000:.0f} MB)")
    print("Si copia questa cartella INTERA sul computer del locale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
