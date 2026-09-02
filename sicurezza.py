#!/usr/bin/env python3
# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
Le chiavi di casa: il PIN che protegge le schermate pericolose, l'offuscamento
della password della posta, e la guardia contro due copie dell'applicazione
aperte insieme.

Onesta' su cosa questo modulo NON e'. Non e' sicurezza informatica:
  - il PIN ferma il cameriere che tocca il tablet in sala mentre passa, non
    chi ha accesso al disco: cinque cifre si provano tutte in un secondo;
  - l'offuscamento della password ferma l'occhiata di passaggio a
    configurazione.json aperto sul monitor, non chi ha in mano questo file.
Difendersi da chi siede al computer del titolare non e' il problema che
stiamo risolvendo. Fingere di farlo sarebbe peggio che non farlo, perche'
qualcuno ci metterebbe dentro roba che merita davvero una cassaforte.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import sys
import threading
import time

# Il PIN di fabbrica. Sta nel codice apposta: e' quello con cui si entra la
# prima volta e quello a cui si torna col codice di recupero.
PIN_PREDEFINITO = "12345"
MINUTI_SBLOCCO = 15
CIFRE_MIN, CIFRE_MAX = 4, 8


def _impronta(pin: str, sale: str) -> str:
    return hashlib.sha256((sale + "|" + pin).encode("utf-8")).hexdigest()


class Serratura:
    """Il PIN delle sezioni pericolose, e per quanto resta aperta.

    Lo stato vive in memoria: chiudendo l'applicazione si richiude tutto.
    Sul disco finisce solo l'impronta del PIN, mai il PIN.
    """

    def __init__(self, cfg: dict, al_salvataggio=None, orologio=time.monotonic):
        self.cfg = cfg
        self.al_salvataggio = al_salvataggio
        # Orologio MONOTONO, non l'ora di parete: il passaggio all'ora solare
        # o una correzione dell'ora di sistema sposterebbero indietro l'ora e
        # allungherebbero la finestra oltre i minuti dichiarati. Un orologio
        # che non torna mai indietro non ha quel problema.
        self._orologio = orologio
        self._scade_a: float | None = None
        self._lucchetto = threading.Lock()

    # --- il PIN --------------------------------------------------------
    def personalizzato(self) -> bool:
        """Vero se il titolare ha cambiato il PIN di fabbrica."""
        return bool(self.cfg.get("pin_impronta") and self.cfg.get("pin_sale"))

    def verifica(self, pin: str) -> bool:
        pin = (pin or "").strip()
        if not self.personalizzato():
            return pin == PIN_PREDEFINITO
        return _impronta(pin, self.cfg["pin_sale"]) == self.cfg["pin_impronta"]

    def cambia(self, nuovo: str) -> None:
        """Scrive il nuovo PIN. Chi chiama ha gia' verificato il vecchio."""
        nuovo = (nuovo or "").strip()
        if not nuovo.isdigit():
            raise ValueError("il PIN puo' contenere solo cifre")
        if not CIFRE_MIN <= len(nuovo) <= CIFRE_MAX:
            raise ValueError(f"il PIN deve avere da {CIFRE_MIN} a "
                             f"{CIFRE_MAX} cifre")
        sale = base64.b16encode(os.urandom(8)).decode("ascii")
        self.cfg["pin_sale"] = sale
        self.cfg["pin_impronta"] = _impronta(nuovo, sale)
        self._salva()

    def ripristina(self) -> None:
        """Torna al PIN di fabbrica. Chi chiama ha gia' verificato il codice."""
        self.cfg.pop("pin_sale", None)
        self.cfg.pop("pin_impronta", None)
        self._salva()

    # --- il recupero ---------------------------------------------------
    def codice_di_recupero_disponibile(self) -> bool:
        return bool(self.cfg.get("terminale_seriale"))

    def recupera(self, codice: str) -> bool:
        """Il codice di recupero e' il numero di serie del terminale.

        Non e' una porta di servizio universale — quella sarebbe la stessa su
        tutte le installazioni, e basterebbe che circolasse una volta. Qui
        serve avere in mano IL terminale: il seriale e' stampato sull'etichetta
        dietro il dispositivo, e chi non e' mai entrato nel locale non ce l'ha.
        Si accettano il seriale intero o le sue ultime sei cifre, perche' e'
        lungo sedici e lo si digita col dito su un tastierino.
        """
        seriale = (self.cfg.get("terminale_seriale") or "").strip()
        codice = (codice or "").strip()
        if not seriale or not codice:
            return False
        # Il seriale intero vale sempre, anche se corto: pretendere sei cifre
        # su un seriale da quattro renderebbe il recupero impossibile mentre
        # l'applicazione continua a dire che e' disponibile.
        if codice == seriale:
            self.ripristina()
            return True
        if len(seriale) >= 6 and codice == seriale[-6:]:
            self.ripristina()
            return True
        return False

    # --- la finestra di sblocco ----------------------------------------
    def sblocca(self) -> None:
        with self._lucchetto:
            self._scade_a = self._orologio() + MINUTI_SBLOCCO * 60

    def chiudi(self) -> None:
        with self._lucchetto:
            self._scade_a = None

    def aperta(self) -> bool:
        with self._lucchetto:
            if self._scade_a is None:
                return False
            if self._orologio() >= self._scade_a:
                self._scade_a = None            # scaduta: si richiude da sola
                return False
            return True

    def minuti_rimasti(self) -> int:
        with self._lucchetto:
            if self._scade_a is None:
                return 0
            resta = self._scade_a - self._orologio()
            if resta <= 0:
                return 0
            # Arrotondato per eccesso: con un minuto esatto davanti si dice
            # "1", non "2". Chi legge "2 minuti" e ne ha uno si sente preso in
            # giro dal programma.
            return -(-int(resta) // 60)

    def _salva(self):
        if self.al_salvataggio:
            self.al_salvataggio()


# --- Offuscamento -------------------------------------------------------------
# Non e' cifratura: la chiave e' qui sotto, in chiaro, e chiunque abbia questo
# file rilegge tutto. Serve solo a non avere la password della posta leggibile
# a occhio nudo in configurazione.json, che qualcuno prima o poi aprira' per
# guardare l'indirizzo IP.
_CHIAVE = b"timbratrice-anviz-non-e-una-cassaforte"
_PREFISSO = "off:"


def offusca(testo: str) -> str:
    if not testo:
        return ""
    crudo = testo.encode("utf-8")
    mescolato = bytes(b ^ _CHIAVE[i % len(_CHIAVE)]
                      for i, b in enumerate(crudo))
    return _PREFISSO + base64.b64encode(mescolato).decode("ascii")


def svela(testo: str) -> str:
    if not testo:
        return ""
    if not testo.startswith(_PREFISSO):
        return testo          # scritta a mano nel file: si prende com'e'
    try:
        mescolato = base64.b64decode(testo[len(_PREFISSO):])
    except Exception:                                            # noqa: BLE001
        return ""
    return bytes(b ^ _CHIAVE[i % len(_CHIAVE)]
                 for i, b in enumerate(mescolato)).decode("utf-8", "replace")


# --- Una sola copia dell'applicazione ----------------------------------------
# L'handle del mutex resta di proprieta' del processo e Windows lo rilascia
# all'uscita: si tiene qui solo per poterlo ispezionare e per rendere esplicito
# che il mutex vive quanto il programma.
_MUTEX = None
_FILE_BLOCCO = None


def istanza_unica(titolo_finestra: str,
                  chiave: str = "GestionePresenzeAnviz") -> bool:
    """Vero se siamo i primi. Se no, porta avanti la finestra gia' aperta.

    Due copie non farebbero danni all'archivio (SQLite in WAL regge piu'
    scrittori), ma farebbero due scheduler che si contendono il terminale, che
    di conversazioni TCP ne regge UNA: a ogni giro una delle due andrebbe in
    timeout e la barra di stato mostrerebbe errori inventati.
    """
    if sys.platform == "win32":
        return _unica_windows(titolo_finestra, chiave)
    return _unica_file(chiave)


def _unica_windows(titolo: str, chiave: str) -> bool:
    global _MUTEX
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                 wintypes.LPCWSTR]
    # "Local\\": per sessione di accesso, che e' esattamente il perimetro
    # giusto. "Global\\" servirebbe fra utenti diversi e in certe sessioni
    # richiede privilegi che qui non abbiamo motivo di chiedere.
    _MUTEX = k32.CreateMutexW(None, False, "Local\\" + chiave)
    errore = ctypes.get_last_error()
    if not _MUTEX:
        # Il mutex non si e' potuto creare per un motivo suo (permessi, nome
        # occupato da un oggetto di altro tipo). Non e' una prova che ci sia
        # gia' un'istanza: meglio partire che rifiutarsi di aprire.
        return True
    if errore != 183:                             # ERROR_ALREADY_EXISTS
        return True
    porta_avanti(titolo)
    return False


def porta_avanti(titolo: str) -> bool:
    """Ripesca la finestra gia' aperta e la mette davanti."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    # Senza restype esplicito ctypes tronca l'handle a 32 bit e su un sistema
    # a 64 bit la finestra "non si trova" a caso.
    u32.FindWindowW.restype = wintypes.HWND
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.BringWindowToTop.argtypes = [wintypes.HWND]
    finestra = u32.FindWindowW(None, titolo)
    if not finestra:
        return False
    u32.ShowWindow(finestra, 9)          # SW_RESTORE: la tira su se e' a icona
    u32.BringWindowToTop(finestra)
    u32.SetForegroundWindow(finestra)
    return True


def _unica_file(chiave: str) -> bool:
    """Ripiego per sistemi non Windows: un file col numero del processo."""
    global _FILE_BLOCCO
    import tempfile
    percorso = os.path.join(tempfile.gettempdir(), chiave + ".pid")
    if os.path.exists(percorso):
        try:
            with open(percorso, encoding="ascii") as f:
                altro = int(f.read().strip())
            os.kill(altro, 0)            # esiste ancora?
            return False
        except (OSError, ValueError):
            pass                         # file rimasto da un processo morto
    try:
        with open(percorso, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
        _FILE_BLOCCO = percorso
    except OSError:
        return True                      # non si riesce a bloccare: si parte
    return True


def rilascia() -> None:
    if _FILE_BLOCCO and os.path.exists(_FILE_BLOCCO):
        try:
            os.remove(_FILE_BLOCCO)
        except OSError:
            pass
