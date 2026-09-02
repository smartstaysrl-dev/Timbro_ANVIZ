#!/usr/bin/env python3
"""
Copie di sicurezza dell'archivio.

Si usa l'API di copia online di SQLite, non `shutil.copy`: copiare a mano un
database mentre qualcuno ci scrive dentro produce un file incoerente, e il
guaio si scopre il giorno che serve. `Connection.backup()` invece lavora a
programma acceso e restituisce sempre un file consistente.

Ogni copia viene subito **riaperta e controllata** con `PRAGMA integrity_check`
e con un conteggio delle timbrature: una copia corrotta deve saltare fuori
adesso, non fra sei mesi.

Rotazione: si tengono le ultime copie giornaliere e la prima di ogni mese. Le
mensili non si cancellano: sono l'unica difesa contro un guasto che nessuno
nota per settimane, per esempio qualcuno che cancella una persona per sbaglio.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3

GIORNALIERE_DA_TENERE = 7
NOME = re.compile(r"^timbrature-(\d{4})-(\d{2})-(\d{2})\.db$")


def cartella_copie(archivio: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(archivio)), "copie")


def elenco(archivio: str) -> list[tuple[dt.date, str, int]]:
    """Le copie esistenti: (data, percorso, byte), dalla piu' recente."""
    cartella = cartella_copie(archivio)
    if not os.path.isdir(cartella):
        return []
    fuori = []
    for nome in os.listdir(cartella):
        m = NOME.match(nome)
        if not m:
            continue
        percorso = os.path.join(cartella, nome)
        try:
            data = dt.date(int(m[1]), int(m[2]), int(m[3]))
            fuori.append((data, percorso, os.path.getsize(percorso)))
        except (ValueError, OSError):
            continue
    fuori.sort(reverse=True)
    return fuori


def ultima(archivio: str) -> tuple[dt.date, str, int] | None:
    e = elenco(archivio)
    return e[0] if e else None


def _verifica(percorso: str) -> int:
    """Riapre la copia e la controlla. Ritorna quante timbrature contiene."""
    con = sqlite3.connect(percorso)
    try:
        esito = con.execute("PRAGMA integrity_check").fetchone()[0]
        if esito != "ok":
            raise RuntimeError(f"copia corrotta: {esito}")
        return con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0]
    finally:
        con.close()


def esegui(archivio: str, quando: dt.date | None = None) -> dict:
    """Fa la copia di oggi (o della data indicata) e la verifica.

    Ritorna un riepilogo con percorso, peso, numero di timbrature copiate e
    quante copie vecchie sono state tolte.
    """
    giorno = quando or dt.date.today()
    cartella = cartella_copie(archivio)
    os.makedirs(cartella, exist_ok=True)
    destinazione = os.path.join(cartella, f"timbrature-{giorno.isoformat()}.db")
    provvisorio = destinazione + ".parziale"

    sorgente = sqlite3.connect(archivio, timeout=30)
    copia = sqlite3.connect(provvisorio)
    try:
        sorgente.backup(copia)          # copia online, a programma acceso
    finally:
        copia.close()
        sorgente.close()

    try:
        quante = _verifica(provvisorio)
    except Exception:
        os.remove(provvisorio)          # una copia che non si apre non si tiene
        raise

    # Solo adesso prende il nome buono: se qualcosa fosse andato storto, la
    # copia di ieri sarebbe rimasta al suo posto invece di essere sostituita
    # da un file rotto.
    os.replace(provvisorio, destinazione)
    tolte = pota(archivio)
    return {
        "percorso": destinazione,
        "byte": os.path.getsize(destinazione),
        "timbrature": quante,
        "tolte": tolte,
    }


def pota(archivio: str) -> int:
    """Toglie le giornaliere vecchie, tiene la prima copia di ogni mese."""
    tutte = elenco(archivio)
    da_tenere = {d for d, _, _ in tutte[:GIORNALIERE_DA_TENERE]}
    prima_del_mese: dict[tuple[int, int], dt.date] = {}
    for data, _, _ in tutte:
        chiave = (data.year, data.month)
        if chiave not in prima_del_mese or data < prima_del_mese[chiave]:
            prima_del_mese[chiave] = data
    da_tenere |= set(prima_del_mese.values())

    tolte = 0
    for data, percorso, _ in tutte:
        if data not in da_tenere:
            try:
                os.remove(percorso)
                tolte += 1
            except OSError:
                pass
    return tolte


def serve_oggi(archivio: str) -> bool:
    u = ultima(archivio)
    return u is None or u[0] < dt.date.today()


if __name__ == "__main__":
    import sys
    percorso = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "timbrature.db")
    esito = esegui(percorso)
    print(f"copia: {esito['percorso']}")
    print(f"       {esito['byte'] / 1024:.0f} KB, {esito['timbrature']} timbrature, "
          f"{esito['tolte']} vecchie rimosse")
    for data, p, byte in elenco(percorso):
        print(f"  {data}  {byte / 1024:8.0f} KB")
