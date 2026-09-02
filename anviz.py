#!/usr/bin/env python3
# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
Client per terminali Anviz — protocollo TC_B su TCP porta 5010.

Riferimento: "ANVIZ TC_B Communication Protocol User Manual" v2.5 (docs/).
Nessuna dipendenza esterna: solo libreria standard.

    python anviz.py cerca 192.168.1.0/24
    python anviz.py info 192.168.1.50
    python anviz.py scarica 192.168.1.50 --nuove
    python anviz.py ascolta 192.168.1.50
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import ipaddress
import socket
import sqlite3
import sys
import time
from dataclasses import dataclass, field


# --- Fuso orario --------------------------------------------------------------
# Windows NON porta con se' il database dei fusi orari: `zoneinfo.TZPATH` e'
# vuoto e ZoneInfo("Europe/Rome") fallisce, a meno che qualcuno non abbia
# installato il pacchetto `tzdata`. Su un registratore di cassa con Python
# appena installato l'applicazione non partirebbe nemmeno.
# Percio': si usa zoneinfo quando c'e', altrimenti si ripiega su una regola
# scritta a mano. La regola europea e' fissata per direttiva e stabile dal 1996:
# ora legale dall'ultima domenica di marzo all'ultima domenica di ottobre,
# CET = UTC+1, CEST = UTC+2. Le due strade danno gli stessi risultati, e c'e'
# una prova che li confronta anno per anno.
def _ultima_domenica(anno: int, mese: int) -> dt.date:
    ultimo = dt.date(anno, mese, 31)          # marzo e ottobre hanno 31 giorni
    return ultimo - dt.timedelta(days=(ultimo.weekday() + 1) % 7)


class FusoItalia(dt.tzinfo):
    """CET/CEST calcolato a mano, per quando manca il database dei fusi."""

    def _e_ora_legale(self, quando: dt.datetime) -> bool:
        # Confini in ora locale di parete. A marzo il confine e' alle 03:00,
        # non alle 02:00: fra le 02:00 e le 03:00 di quella domenica c'e' un'ora
        # che non esiste, l'orologio salta. Trattarla come ora solare e' quello
        # che fa anche zoneinfo, ed e' l'unico punto in cui le due strade
        # potrebbero divergere.
        inizio = dt.datetime.combine(_ultima_domenica(quando.year, 3),
                                     dt.time(3, 0))
        fine = dt.datetime.combine(_ultima_domenica(quando.year, 10),
                                   dt.time(3, 0))
        nudo = quando.replace(tzinfo=None)
        return inizio <= nudo < fine

    def utcoffset(self, quando):
        if quando is None:
            return dt.timedelta(hours=1)
        return dt.timedelta(hours=2 if self._e_ora_legale(quando) else 1)

    def dst(self, quando):
        if quando is None:
            return dt.timedelta(0)
        return dt.timedelta(hours=1) if self._e_ora_legale(quando) else dt.timedelta(0)

    def tzname(self, quando):
        return "CEST" if quando and self._e_ora_legale(quando) else "CET"

    def __repr__(self):
        return "FusoItalia()"


def _scegli_fuso():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Rome")
    except Exception:                                            # noqa: BLE001
        return FusoItalia()


FUSO = _scegli_fuso()
FUSO_DI_RISERVA = isinstance(FUSO, FusoItalia)

PORTA_DEFAULT = 5010
STX = 0xA5

# Il terminale risponde a chiunque quando il device code (CH) e' zero.
# Spec, Parte I: "All devices will response to following Commands, when CH is zero."
CH_BROADCAST = 0

# --- Comandi (Parte II della specifica) -------------------------------------
CMD_GET_CONFIG1 = 0x30
CMD_SET_CONFIG1 = 0x31
CMD_GET_CONFIG2 = 0x32
CMD_SET_CONFIG2 = 0x33
CMD_GET_DATETIME = 0x38
CMD_SET_DATETIME = 0x39
CMD_GET_NETWORK = 0x3A
CMD_SET_NETWORK = 0x3B
CMD_GET_RECORD_INFO = 0x3C
CMD_DOWNLOAD_RECORDS = 0x40
# Scarico utenti: la specifica dice 0x42, ma il W1C Pro non risponde e vuole
# 0x72 (la spec lo cita come variante per alcune piattaforme). Verificato:
# 0x42 e 0x22 vanno in timeout, 0x72 risponde.
CMD_DOWNLOAD_USERS = 0x72
CMD_DOWNLOAD_USERS_SPEC = 0x42
CMD_UPLOAD_USERS = 0x73          # la coppia di 0x72, non lo 0x43 della spec
CMD_GET_DEVICE_ID = 0x46
CMD_GET_MODEL = 0x48
CMD_DELETE_USER = 0x4C
CMD_ERASE_RECORDS = 0x4E
CMD_GET_CAPACITY = 0x5D
CMD_GET_TA_STATUS = 0x70
CMD_SET_TA_STATUS = 0x71
CMD_GET_SERIAL = 0x24
CMD_GET_CARD = 0x7E
CMD_REALTIME = 0x5F  # solo in risposta: il terminale spinge, non si interroga

# Ricerca e configurazione via broadcast UDP. Funzionano anche se il terminale
# non ha un indirizzo IP utilizzabile: e' cosi' che lo si ripesca quando e'
# rimasto in DHCP su una rete che non distribuisce indirizzi.
CMD_UDP_CERCA = 0x02
CMD_UDP_IMPOSTA = 0x03
UDP_PORTA_DISPOSITIVO = 5050
UDP_PORTA_PC = 5060

# --- Valori di ritorno (RET) ------------------------------------------------
RET = {
    0x00: "OK",
    0x01: "operazione fallita",
    0x04: "utenti esauriti",
    0x05: "nessun utente",
    0x06: "utente inesistente",
    0x08: "timeout acquisizione",
    0x0A: "utente gia' esistente",
    0x0B: "impronta gia' esistente",
    0x0F: "USB bloccata",
}

# L'orologio del terminale conta i secondi trascorsi da un istante di partenza.
# La specifica ufficiale dice 2000-01-01 00:00, ma E' SBAGLIATA: tarato il
# 1 set 2026 su W1C Pro firmware 03.52.CT con una timbratura a un'ora nota
# (0x32282c2e a fronte di 2026-09-01 12:12:30), l'epoca vera e' il 2 gennaio.
# Con quella della specifica si sbaglia di un giorno esatto, all'indietro.
EPOCA_SPEC = dt.datetime(2000, 1, 1, 0, 0, 0)   # da specifica: NON usare
EPOCA_VERA = dt.datetime(2000, 1, 2, 0, 0, 0)   # verificata sul dispositivo
EPOCA_DEFAULT = EPOCA_VERA

# Il PIN sta in 28 bit (20 nel record piu' un byte alto in coda), quindi il
# valore piu' grande rappresentabile e' 268.435.455: otto cifre ci stanno
# sempre, la nona no. Il terminale di suo ne accetta di meno (i menu ne
# propongono sei), ma qui si limita solo cio' che la codifica non regge.
MAX_CIFRE_PIN = 8


# --- CRC16 ------------------------------------------------------------------
def _tabella_crc(poly: int = 0x8408) -> list[int]:
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        tab.append(c)
    return tab


_CRC_TAB = _tabella_crc()
assert _CRC_TAB[1] == 0x1189 and _CRC_TAB[16] == 0x1081, "tabella CRC corrotta"


def crc16(dati: bytes) -> int:
    """CRC-16 riflesso (poly 0x8408), init 0xFFFF, nessun XOR finale."""
    c = 0xFFFF
    for b in dati:
        c ^= b
        c = (c >> 8) ^ _CRC_TAB[c & 0xFF]
    return c


class ErroreAnviz(Exception):
    pass


# --- Timbratura -------------------------------------------------------------
BACKUP = {0: "impronta 1", 1: "impronta 2", 2: "password", 3: "badge"}


@dataclass
class Timbratura:
    user_id: int
    quando: dt.datetime  # ora locale, come la mostra il terminale
    secondi: int  # valore grezzo, indipendente dall'epoca scelta
    backup: int  # bitmask: bit0 FP1, bit1 FP2, bit2 password, bit3 badge
    tipo: int  # bit7 = porta apribile; nibble basso = stato presenza
    work_code: int
    raw: bytes = field(default=b"", repr=False)  # i 14 byte originali, intoccati

    @property
    def metodo(self) -> str:
        for bit, nome in BACKUP.items():
            if self.backup & (1 << bit):
                return nome
        return f"sconosciuto ({self.backup})"

    @property
    def stato(self) -> int:
        return self.tipo & 0x0F

    @property
    def apre_porta(self) -> bool:
        return bool(self.tipo & 0x80)

    @property
    def quando_utc(self) -> dt.datetime:
        """L'istante normalizzato, per ordinare e per l'ora legale.

        Il terminale conosce solo l'ora locale. Nell'ora che si ripete al
        ritorno all'ora solare la conversione e' ambigua: si sceglie la prima
        occorrenza (fold=0). L'ora locale grezza resta comunque salvata, quindi
        la scelta e' sempre rivedibile.
        """
        return self.quando.replace(tzinfo=FUSO, fold=0).astimezone(dt.timezone.utc)

    def id_evento(self, dispositivo: str) -> str:
        """Identificativo deterministico: stesso evento -> stessa chiave."""
        return hashlib.sha1(dispositivo.encode() + b"|" + self.raw).hexdigest()

    @staticmethod
    def da_bytes(raw: bytes, epoca: dt.datetime) -> "Timbratura":
        if len(raw) != 14:
            raise ErroreAnviz(f"record di {len(raw)} byte invece di 14")
        secondi = int.from_bytes(raw[5:9], "big")
        return Timbratura(
            user_id=int.from_bytes(raw[0:5], "big"),
            quando=epoca + dt.timedelta(seconds=secondi),
            secondi=secondi,
            backup=raw[9],
            tipo=raw[10],
            work_code=int.from_bytes(raw[11:14], "big"),
            raw=bytes(raw),
        )


@dataclass
class Utente:
    """Un utente iscritto sul terminale.

    Esistono due formati. Quello da specifica e' 27 byte (comando 0x42), ma il
    W1C Pro non risponde a 0x42: risponde a 0x72 e restituisce record da
    40 byte, con la tessera su 4 byte invece di 3 e il nome in UTF-16 su 20
    byte invece di 10 in ASCII. Si riconoscono dalla lunghezza.

    Della coda del record da 40 byte (reparto, gruppo, modo, impronte) siamo
    sicuri solo in parte: e' dedotta da un singolo utente reale. Per questo si
    conserva sempre `raw`, cosi' si puo' rileggere tutto quando ci saranno piu'
    utenti iscritti con cui confrontare.
    """
    user_id: int
    badge: int | None      # None se non ha tessera
    ha_password: bool
    nome: str
    reparto: int
    gruppo: int
    modo: int
    impronte: int          # quante impronte iscritte (0-2)
    amministratore: bool
    # Il PIN come lo digita la persona, zeri iniziali compresi ("0042" e' un
    # PIN diverso da "42"): sul filo il numero di cifre viaggia a parte, nel
    # nibble alto del byte 5, quindi lo zero iniziale si puo' rappresentare.
    password: str | None = None
    raw: bytes = field(default=b"", repr=False)
    # Il PIN si riscrive solo se lo si cambia davvero: i suoi byte sono
    # sparsi (5-7 piu' il byte alto in coda) e toccarli quando si modifica
    # tutt'altro e' il modo per cancellare la password a qualcuno per sbaglio.
    _cambia_password: bool = field(default=False, repr=False)

    def imposta_password(self, pin: str | int | None) -> None:
        """Imposta o toglie il PIN. Sara' scritto al prossimo salvataggio."""
        testo = "" if pin is None else str(pin).strip()
        if testo and not testo.isdigit():
            raise ValueError("il PIN puo' contenere solo cifre")
        if len(testo) > MAX_CIFRE_PIN:
            raise ValueError(f"il PIN non puo' superare {MAX_CIFRE_PIN} cifre")
        self.password = testo or None
        self.ha_password = self.password is not None
        self._cambia_password = True

    @staticmethod
    def da_bytes(raw: bytes) -> "Utente":
        pwd = raw[5:8]
        senza_password = pwd == b"\xff\xff\xff"
        if len(raw) == 40:            # formato esteso del W1C Pro
            # Coda del record, dalla specifica (0x72, versione ANSI da 30 byte,
            # qui con il nome a 20 byte invece di 10, quindi tutto slittato di
            # +10): 26-27 stato impronte, 28 byte ALTO della password,
            # 29 riservato, 30 special info. In base zero: 35-36, 37, 38, 39.
            # Il byte dei permessi e' l'ULTIMO, non il 37: quello e' password.
            card = raw[8:12]
            vuota = b"\xff\xff\xff\xff"
            nome = raw[12:32].decode("utf-16-be", "replace")
            reparto, gruppo, modo = raw[32], raw[33], raw[34]
            fp = int.from_bytes(raw[35:37], "big")
            speciale = raw[39]
            byte_alto_pin = raw[37]
        elif len(raw) == 27:          # formato da specifica
            card = raw[8:11]
            vuota = b"\xff\xff\xff"
            nome = raw[11:21].decode("ascii", "replace")
            reparto, gruppo, modo = raw[21], raw[22], raw[23]
            fp = int.from_bytes(raw[24:26], "big")
            speciale = raw[26]
            byte_alto_pin = 0
        else:
            raise ErroreAnviz(f"utente di {len(raw)} byte: formato sconosciuto")
        # Il PIN: nibble alto del byte 5 = quante cifre, i 20 bit rimanenti
        # piu' il byte alto in coda = il valore. Gli zeri iniziali si
        # ricostruiscono dal numero di cifre, altrimenti "0042" tornerebbe "42".
        cifre = 0 if senza_password else (pwd[0] >> 4)
        pin = None
        if cifre:
            valore = (byte_alto_pin << 20) | (int.from_bytes(pwd, "big") & 0xFFFFF)
            pin = str(valore).zfill(min(cifre, MAX_CIFRE_PIN))

        return Utente(
            user_id=int.from_bytes(raw[0:5], "big"),
            badge=None if card == vuota else int.from_bytes(card, "big"),
            ha_password=cifre > 0,
            password=pin,
            nome=nome.split("\x00")[0].strip(),
            reparto=reparto,
            gruppo=gruppo,
            modo=modo,
            impronte=(fp & 1) + ((fp >> 1) & 1),
            amministratore=(speciale >> 6) == 3,
            raw=bytes(raw),
        )

    def a_bytes(self) -> bytes:
        """Ricostruisce i 40 byte da rimandare al terminale.

        Si parte SEMPRE dai byte originali e si sovrascrivono solo i campi che
        conosciamo: nella coda del record ci sono due byte di cui ignoriamo il
        significato, e riscriverli a caso significherebbe rovinare l'utente.
        Chi nasce adesso parte da un record vuoto (0xFF = campo assente).
        """
        if len(self.raw) == 40:
            b = bytearray(self.raw)
        else:
            b = bytearray(40)
            b[5:8] = b"\xff\xff\xff"       # password assente
            b[8:12] = b"\xff\xff\xff\xff"  # tessera assente
            b[37] = 0xFF                   # byte alto della password: assente
            b[39] = 0x40                   # permessi: utente normale

        b[0:5] = self.user_id.to_bytes(5, "big")
        if self.badge is None:
            b[8:12] = b"\xff\xff\xff\xff"
        else:
            b[8:12] = self.badge.to_bytes(4, "big")
        nome = self.nome[:10].encode("utf-16-be")
        b[12:32] = nome.ljust(20, b"\x00")[:20]
        b[32] = self.reparto & 0xFF
        b[33] = self.gruppo & 0xFF
        b[34] = self.modo & 0xFF
        # Le impronte (35-36) non si scrivono: la specifica dice che in
        # scrittura quel campo vale sempre 0, si iscrivono solo dal terminale.
        if self._cambia_password:
            if self.password is None:
                b[5:8] = b"\xff\xff\xff"     # nessuna password
                b[37] = 0x00
            else:
                cifre = len(self.password)
                valore = int(self.password)
                b[5] = ((cifre & 0x0F) << 4) | ((valore >> 16) & 0x0F)
                b[6] = (valore >> 8) & 0xFF
                b[7] = valore & 0xFF
                b[37] = (valore >> 20) & 0xFF
        # Fuori da quel caso il byte 37 NON si tocca: e' il byte alto della
        # password, e scriverci il flag amministratore cambierebbe il PIN.
        b[39] = (b[39] & 0x3F) | (0xC0 if self.amministratore else 0x40)
        return bytes(b)


# --- Connessione ------------------------------------------------------------
class Terminale:
    """Una connessione TCP a un terminale Anviz. Un comando alla volta."""

    def __init__(self, host: str, porta: int = PORTA_DEFAULT,
                 ch: int = CH_BROADCAST, timeout: float = 8.0):
        self.host, self.porta, self.ch, self.timeout = host, porta, ch, timeout
        self.sock: socket.socket | None = None
        self.cmd_utenti = CMD_DOWNLOAD_USERS

    def __enter__(self) -> "Terminale":
        self.sock = socket.create_connection((self.host, self.porta), self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, *_):
        if self.sock:
            self.sock.close()
            self.sock = None

    # -- livello frame --
    def _pacchetto(self, cmd: int, dati: bytes = b"") -> bytes:
        corpo = (bytes([STX]) + self.ch.to_bytes(4, "big") + bytes([cmd])
                 + len(dati).to_bytes(2, "big") + dati)
        return corpo + crc16(corpo).to_bytes(2, "little")

    def _leggi_esatto(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            pezzo = self.sock.recv(n - len(buf))
            if not pezzo:
                raise ErroreAnviz("il terminale ha chiuso la connessione")
            buf += pezzo
        return buf

    def leggi_risposta(self) -> tuple[int, int, bytes]:
        """Legge un frame di risposta. Ritorna (ack, ret, dati)."""
        # Risincronizza sullo STX: il terminale puo' inserire frame real-time.
        while True:
            b = self._leggi_esatto(1)
            if b[0] == STX:
                break
        testa = self._leggi_esatto(8)  # CH(4) ACK(1) RET(1) LEN(2)
        ack, ret = testa[4], testa[5]
        lung = int.from_bytes(testa[6:8], "big")
        dati = self._leggi_esatto(lung)
        crc_letto = int.from_bytes(self._leggi_esatto(2), "little")
        atteso = crc16(bytes([STX]) + testa + dati)
        if crc_letto != atteso:
            raise ErroreAnviz(f"CRC sbagliato: letto {crc_letto:#06x}, atteso {atteso:#06x}")
        return ack, ret, dati

    def comando(self, cmd: int, dati: bytes = b"") -> bytes:
        self.sock.sendall(self._pacchetto(cmd, dati))
        while True:
            ack, ret, corpo = self.leggi_risposta()
            if ack == CMD_REALTIME + 0x80 and cmd != CMD_REALTIME:
                continue  # timbratura spontanea arrivata nel mezzo: la salto
            break
        if ack != cmd + 0x80:
            raise ErroreAnviz(f"risposta al comando sbagliato: {ack:#04x} per {cmd:#04x}")
        if ret != 0x00:
            raise ErroreAnviz(f"comando {cmd:#04x} rifiutato: {RET.get(ret, hex(ret))}")
        return corpo

    # -- comandi utili --
    def modello(self) -> str:
        return self.comando(CMD_GET_MODEL).decode("ascii", "replace").strip("\x00 ")

    def device_id(self) -> int:
        return int.from_bytes(self.comando(CMD_GET_DEVICE_ID), "big")

    def orologio(self) -> dt.datetime:
        d = self.comando(CMD_GET_DATETIME)
        return dt.datetime(2000 + d[0], d[1], d[2], d[3], d[4], d[5])

    def imposta_orologio(self, quando: dt.datetime | None = None) -> None:
        q = quando or dt.datetime.now()
        self.comando(CMD_SET_DATETIME,
                     bytes([q.year - 2000, q.month, q.day, q.hour, q.minute, q.second]))

    def conteggi(self) -> dict[str, int]:
        d = self.comando(CMD_GET_RECORD_INFO)
        if len(d) != 18:
            raise ErroreAnviz(f"conteggi: {len(d)} byte invece di 18")
        campi = ["utenti", "impronte", "password", "badge", "timbrature", "nuove"]
        return {n: int.from_bytes(d[i * 3:i * 3 + 3], "big") for i, n in enumerate(campi)}

    def rete(self) -> bytes:
        return self.comando(CMD_GET_NETWORK)

    def rete_decodificata(self) -> dict:
        """Configurazione di rete (0x3A), 27 byte."""
        d = self.rete()
        if len(d) != 27:
            raise ErroreAnviz(f"configurazione di rete di {len(d)} byte invece di 27")
        return {
            "ip": _ip(d[0:4]),
            "maschera": _ip(d[4:8]),
            "mac": _mac(d[8:14]),
            "gateway": _ip(d[14:18]),
            "server_ip": _ip(d[18:22]),
            "accesso_remoto": d[22],
            "porta": int.from_bytes(d[23:25], "big"),
            "modo_rete": MODI_RETE.get(d[25], f"sconosciuto ({d[25]})"),
            "dhcp": bool(d[26]),
            "grezzo": d,
        }

    def imposta_dhcp(self, attivo: bool) -> bytes:
        """Accende o spegne il DHCP lasciando tutto il resto com'e'.

        Legge la configurazione, cambia il solo byte 27 e la riscrive: cosi'
        non si rischia di ricostruire male gli altri campi e di perdere il
        contatto col terminale.
        """
        attuale = self.rete()
        if len(attuale) != 27:
            raise ErroreAnviz(f"configurazione di {len(attuale)} byte invece di 27")
        nuova = bytearray(attuale)
        nuova[26] = 1 if attivo else 0
        if bytes(nuova) == attuale:
            return attuale  # gia' come lo vogliamo: non si scrive per niente
        self.comando(CMD_SET_NETWORK, bytes(nuova))
        return bytes(nuova)

    def azzera_timbrature(self) -> None:
        """Cancella TUTTE le timbrature dal terminale (0x4E, tipo 0)."""
        self.comando(CMD_ERASE_RECORDS, bytes([0]) + (0).to_bytes(3, "big"))

    def utenti(self) -> list[Utente]:
        """Scarica l'elenco degli utenti iscritti, a pagine di 12.

        La dimensione del record non e' fissa fra le piattaforme, quindi la si
        ricava dalla risposta invece di darla per scontata.
        """
        parametro, fuori = 1, []          # 1 = inizia, 0 = continua
        while True:
            corpo = self.comando(self.cmd_utenti, bytes([parametro, 12]))
            n = corpo[0]
            if n == 0:
                return fuori
            misura, resto = divmod(len(corpo) - 1, n)
            if resto or misura not in (27, 40):
                raise ErroreAnviz(
                    f"{n} utenti in {len(corpo)-1} byte: record da {misura} byte, "
                    "formato non riconosciuto")
            for i in range(n):
                inizio = 1 + i * misura
                fuori.append(Utente.da_bytes(corpo[inizio:inizio + misura]))
            parametro = 0

    def salva_utenti(self, utenti: list[Utente]) -> list[int]:
        """Scrive gli utenti sul terminale (0x73). Ritorna gli ID falliti.

        La risposta e' una maschera di bit: un bit per ciascuno dei record
        mandati, 1 = riuscito. Si spedisce a gruppi di 8 perche' e' il massimo
        previsto per il formato Unicode.
        """
        falliti = []
        for i in range(0, len(utenti), 8):
            lotto = utenti[i:i + 8]
            corpo = bytes([len(lotto)]) + b"".join(u.a_bytes() for u in lotto)
            risposta = self.comando(CMD_UPLOAD_USERS, corpo)
            maschera = int.from_bytes(risposta[:2], "big") if risposta else 0
            for n, u in enumerate(lotto):
                if not (maschera >> n) & 1:
                    falliti.append(u.user_id)
        return falliti

    def elimina_utente(self, user_id: int, tutto: bool = True) -> None:
        """Cancella un utente dal terminale (0x4C).

        Con tutto=True (backup 0xFF) sparisce l'utente e tutto cio' che lo
        riguarda: anagrafica, tessera, password e impronte.
        """
        self.comando(CMD_DELETE_USER,
                     user_id.to_bytes(5, "big") + bytes([0xFF if tutto else 0x0F]))

    def stati_ta(self) -> dict[int, str]:
        """Gli stati presenza definiti sul terminale (0x70).

        Sono quelli che l'operatore sceglie prima di passare il badge, e
        finiscono nel nibble basso del campo 'tipo' di ogni timbratura.
        """
        d = self.comando(CMD_GET_TA_STATUS)
        if not d:
            return {}
        quanti = d[0]
        corpo = d[1:]
        misura = 20 if len(corpo) >= quanti * 20 else 10
        fuori = {}
        for i in range(quanti):
            grezzo = corpo[i * misura:(i + 1) * misura]
            if misura == 20:
                testo = grezzo.decode("utf-16-be", "replace")
            else:
                testo = grezzo.decode("ascii", "replace")
            testo = testo.split("\x00")[0].strip()
            if testo:
                fuori[i] = testo
        return fuori

    def configurazione(self) -> dict:
        """Parametri del dispositivo (0x30).

        Il campo 18 e' la "versione dei comandi" e vale 0x02 su questo
        terminale: e' la conferma incrociata che la mappa dei byte e' giusta,
        perche' 0x02 significa "risponde a 0x24/0x25" ed e' esattamente cio'
        che fa.
        """
        d = self.comando(CMD_GET_CONFIG1)
        if len(d) < 18:
            raise ErroreAnviz(f"configurazione in {len(d)} byte invece di 18+")
        formato = d[14]
        return {
            "firmware": d[0:8].decode("ascii", "replace").strip("\x00 "),
            "sospensione_min": d[11],
            "volume": d[12],
            "lingua": d[13],
            "formato_data": (formato >> 4) & 0x0F,
            "ore_12": bool(formato & 0x0F),
            "stato_predefinito": d[15],
            "versione_comandi": d[17],
            "grezzo": d,
        }

    def imposta_configurazione(self, sospensione_min: int | None = None,
                               volume: int | None = None,
                               lingua: int | None = None,
                               ore_12: bool | None = None,
                               formato_data: int | None = None,
                               stato_predefinito: int | None = None) -> None:
        """Cambia i parametri del dispositivo (0x31).

        La specifica prevede 0xFF per "non toccare questo campo": si sfrutta,
        cosi' non serve riscrivere l'intera configurazione per cambiare il
        volume. La password di comunicazione resta fuori: il suo campo non e'
        chiaro su questo firmware e scriverci dentro alla cieca significa
        rischiare di tagliarsi fuori dal terminale.
        """
        attuale = self.configurazione()
        if ore_12 is None and formato_data is None:
            byte_formato = 0xFF
        else:
            alto = (attuale["formato_data"] if formato_data is None
                    else formato_data) & 0x0F
            basso = (1 if (attuale["ore_12"] if ore_12 is None else ore_12)
                     else 0)
            byte_formato = (alto << 4) | basso

        def o(valore):
            return 0xFF if valore is None else valore & 0xFF

        dati = bytes([0xFF, 0xFF, 0xFF,              # password: non si tocca
                      o(sospensione_min), o(volume), o(lingua), byte_formato,
                      o(stato_predefinito), 0xFF, 0x00])
        self.comando(CMD_SET_CONFIG1, dati)

    def configurazione2(self) -> dict:
        """Secondo blocco di parametri (0x32), 15 byte.

        Qui vivono tre cose che contano davvero per un ristorante: se il
        terminale spinge le timbrature in tempo reale, dopo quanto ignora una
        seconda passata di badge della stessa persona, e la correzione della
        deriva dell'orologio.
        """
        d = self.comando(CMD_GET_CONFIG2)
        if len(d) < 15:
            raise ErroreAnviz(f"configurazione2 in {len(d)} byte invece di 15")
        correzione = d[14]
        return {
            "precisione": d[0],
            "work_code": bool(d[3]),
            "tempo_reale": bool(d[4]),
            "rele": bool(d[6]),
            "ritardo_serratura_s": d[7],
            "avviso_memoria": int.from_bytes(d[8:11], "big"),
            "ignora_ripetute_min": d[11],
            "ritardo_campanella_s": d[13],
            # 0-60 = aggiunge N secondi al giorno; 0x81-0xBC = ne toglie
            "correzione_orologio_s": (-(correzione - 0x80) if correzione >= 0x81
                                      else correzione),
            "grezzo": d,
        }

    def imposta_configurazione2(self, tempo_reale: bool | None = None,
                                ignora_ripetute_min: int | None = None,
                                avviso_memoria: int | None = None,
                                correzione_orologio_s: int | None = None,
                                ritardo_campanella_s: int | None = None) -> None:
        """Cambia il secondo blocco (0x33), leggendo e riscrivendo.

        Qui non ci si affida al trucco del 0xFF: si rileggono i 15 byte e si
        toccano solo quelli voluti. Dentro ci sono impostazioni Wiegand e rele'
        che su questo modello non servono, ma riscriverle a caso sarebbe
        comunque un modo per rompere qualcosa senza accorgersene.
        """
        attuale = self.comando(CMD_GET_CONFIG2)
        if len(attuale) < 15:
            raise ErroreAnviz(f"configurazione2 in {len(attuale)} byte")
        b = bytearray(attuale)
        if tempo_reale is not None:
            b[4] = 1 if tempo_reale else 0
        if ignora_ripetute_min is not None:
            b[11] = max(0, min(250, ignora_ripetute_min))
        if avviso_memoria is not None:
            b[8:11] = max(0, min(5000, avviso_memoria)).to_bytes(3, "big")
        if ritardo_campanella_s is not None:
            b[13] = max(0, min(15, ritardo_campanella_s))
        if correzione_orologio_s is not None:
            s = max(-60, min(60, correzione_orologio_s))
            b[14] = s if s >= 0 else 0x80 + (-s)
        if bytes(b) != attuale:
            self.comando(CMD_SET_CONFIG2, bytes(b))

    def imposta_stati_ta(self, stati: dict[int, str]) -> None:
        """Riscrive i nomi degli stati presenza sul display (0x71).

        Si rileggono prima quelli attuali e si cambiano solo quelli indicati:
        gli altri quindici slot non vanno azzerati per sbaglio.
        """
        attuali = self.stati_ta()
        attuali.update(stati)
        quanti = 16
        corpo = bytearray([quanti])
        for i in range(quanti):
            testo = attuali.get(i, "")[:10]
            corpo += testo.encode("utf-16-be").ljust(20, b"\x00")[:20]
        self.comando(CMD_SET_TA_STATUS, bytes(corpo))

    def capacita(self) -> dict[str, int]:
        """Capienza del dispositivo (0x5D): impronte, utenti, timbrature."""
        d = self.comando(CMD_GET_CAPACITY)
        if len(d) < 9:
            raise ErroreAnviz(f"capacita' in {len(d)} byte invece di 9")
        return {
            "impronte": int.from_bytes(d[0:3], "big"),
            "utenti": int.from_bytes(d[3:6], "big"),
            "timbrature": int.from_bytes(d[6:9], "big"),
        }

    def numero_tessera(self) -> int:
        """L'ultima tessera passata sul lettore (0x7E), 0 se nessuna.

        La specifica dichiara questo comando "solo T5S", ma il W1C Pro
        risponde. Serve a iscrivere una tessera da remoto: invece di copiare
        a mano il numero stampato sul badge, lo si fa leggere al terminale.
        """
        d = self.comando(CMD_GET_CARD)
        return int.from_bytes(d[:4], "big") if len(d) >= 4 else 0

    def seriale(self) -> str:
        return self.comando(CMD_GET_SERIAL).decode("ascii", "replace").strip("\x00 ")

    def timbrature(self, solo_nuove: bool = False, epoca: dt.datetime = EPOCA_DEFAULT):
        """Scarica le timbrature a pagine di 25. Generatore."""
        parametro = 2 if solo_nuove else 1  # 1 = tutte, 2 = solo nuove
        while True:
            corpo = self.comando(CMD_DOWNLOAD_RECORDS, bytes([parametro, 25]))
            n = corpo[0]
            if n == 0:
                return
            for i in range(n):
                inizio = 1 + i * 14
                yield Timbratura.da_bytes(corpo[inizio:inizio + 14], epoca)
            parametro = 0  # 0 = continua a scaricare

    def marca_nuove_scaricate(self, quante: int) -> None:
        """Azzera il flag 'nuova' su esattamente `quante` timbrature.

        Da chiamare SOLO dopo aver salvato: se il collettore muore prima,
        al giro dopo le riscarica. Meglio un doppione (deduplicato dal DB)
        che una timbratura persa.
        """
        self.comando(CMD_ERASE_RECORDS, bytes([2]) + quante.to_bytes(3, "big"))

    def ascolta(self, epoca: dt.datetime = EPOCA_DEFAULT):
        """Resta in ascolto delle timbrature spinte in tempo reale (0x5F)."""
        self.sock.settimeout(None)
        while True:
            ack, ret, corpo = self.leggi_risposta()
            if ack == CMD_REALTIME + 0x80 and len(corpo) == 14:
                yield Timbratura.da_bytes(corpo, epoca)


# --- Ricerca via broadcast UDP ----------------------------------------------
def _pacchetto_udp(cmd: int, dati: bytes = b"") -> bytes:
    corpo = (bytes([STX]) + (0).to_bytes(4, "big") + bytes([cmd])
             + len(dati).to_bytes(2, "big") + dati)
    return corpo + crc16(corpo).to_bytes(2, "little")


def _testo(b: bytes) -> str:
    return b.split(b"\x00")[0].decode("ascii", "replace").strip()


def _ip(b: bytes) -> str:
    return ".".join(str(x) for x in b)


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


MODI_RETE = {0: "Server", 1: "Client", 2: "Client + Server URL"}


def leggi_risposta_udp(dati: bytes) -> dict | None:
    """Interpreta la risposta a 0x02. Ritorna None se non e' un frame valido."""
    if len(dati) < 11 or dati[0] != STX:
        return None
    lung = int.from_bytes(dati[7:9], "big")
    corpo = dati[9:9 + lung]
    if len(corpo) < 63:
        return None
    d = {
        "modello": _testo(corpo[0:10]),
        "seriale": _testo(corpo[10:26]),
        "ip": _ip(corpo[26:30]),
        "maschera": _ip(corpo[30:34]),
        "gateway": _ip(corpo[34:38]),
        "mac": _mac(corpo[38:44]),
        "server_ip": _ip(corpo[44:48]),
        "porta": int.from_bytes(corpo[48:50], "big"),
        "modo_rete": MODI_RETE.get(corpo[50], f"sconosciuto ({corpo[50]})"),
        "firmware": _testo(corpo[51:59]),
        "device_no": int.from_bytes(dati[1:5], "big"),
    }
    if len(corpo) >= 167:  # firmware con "Client + DNS"
        d["dns"] = _ip(corpo[63:67])
        d["url"] = _testo(corpo[67:167])
    return d


def sorgenti_locali() -> list[str]:
    """Gli indirizzi IPv4 di questo PC, escluse loopback e link-local."""
    fuori = []
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if not ip.startswith(("127.", "169.254.")) and ip not in fuori:
            fuori.append(ip)
    return fuori


def cerca_udp(sorgenti: list[str], attesa: float = 4.0) -> list[dict]:
    """Manda il broadcast di ricerca da ogni interfaccia e raccoglie chi risponde."""
    ascolto = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ascolto.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ascolto.bind(("0.0.0.0", UDP_PORTA_PC))
    ascolto.settimeout(0.6)
    pacchetto = _pacchetto_udp(CMD_UDP_CERCA)
    try:
        for ip in sorgenti:
            invio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            invio.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                invio.bind((ip, 0))  # forza l'interfaccia di uscita
                invio.sendto(pacchetto, ("255.255.255.255", UDP_PORTA_DISPOSITIVO))
                invio.sendto(pacchetto, ("192.168.0.255", UDP_PORTA_DISPOSITIVO))
            except OSError:
                pass
            finally:
                invio.close()

        trovati, visti = [], set()
        scadenza = time.monotonic() + attesa
        while time.monotonic() < scadenza:
            try:
                dati, mittente = ascolto.recvfrom(4096)
            except socket.timeout:
                continue
            d = leggi_risposta_udp(dati)
            if d and d["mac"] not in visti:
                visti.add(d["mac"])
                d["mittente"] = mittente[0]
                trovati.append(d)
        return trovati
    finally:
        ascolto.close()


def imposta_ip_udp(mac: str, ip: str, maschera: str, gateway: str,
                   password: str, sorgenti: list[str], porta: int = PORTA_DEFAULT,
                   modo: int = 0, utente: str = "") -> list[dict]:
    """Assegna un indirizzo statico al terminale via broadcast UDP (0x03).

    Il firmware confronta il MAC nel pacchetto col proprio: se non coincide
    ignora tutto. Quindi serve conoscere il MAC, e nessun altro dispositivo
    puo' essere toccato per sbaglio.
    """
    def ottetti(s: str) -> bytes:
        return bytes(int(x) for x in s.split("."))

    dati = (ottetti(ip) + ottetti(maschera) + ottetti(gateway)
            + bytes(int(x, 16) for x in mac.replace("-", ":").split(":"))
            + ottetti("0.0.0.0")                      # server IP
            + porta.to_bytes(2, "big")
            + bytes([modo])
            + (0).to_bytes(4, "big")                  # nuovo device no.
            + bytes(4)                                # riservato
            + utente.encode("ascii").ljust(12, b"\x00")[:12]
            + password.encode("ascii").ljust(12, b"\x00")[:12])
    assert len(dati) == 57, f"payload di {len(dati)} byte invece di 57"

    ascolto = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ascolto.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ascolto.bind(("0.0.0.0", UDP_PORTA_PC))
    ascolto.settimeout(0.6)
    pacchetto = _pacchetto_udp(CMD_UDP_IMPOSTA, dati)
    try:
        for sorg in sorgenti:
            invio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            invio.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                invio.bind((sorg, 0))
                invio.sendto(pacchetto, ("255.255.255.255", UDP_PORTA_DISPOSITIVO))
            except OSError:
                pass
            finally:
                invio.close()
        risposte = []
        scadenza = time.monotonic() + 5.0
        while time.monotonic() < scadenza:
            try:
                r, mittente = ascolto.recvfrom(4096)
            except socket.timeout:
                continue
            if len(r) >= 11 and r[0] == STX:
                risposte.append({"da": mittente[0], "ack": r[5], "ret": r[6],
                                 "esito": RET.get(r[6], hex(r[6]))})
        return risposte
    finally:
        ascolto.close()


# --- Archivio ---------------------------------------------------------------
# Tabella di atterraggio: immutabile per contratto. Si scrive solo in
# INSERT OR IGNORE, mai UPDATE. Le correzioni vivono altrove, nel cruscotto,
# come rettifiche tracciate. Campi allineati all'evento normalizzato del
# documento operativo (par. 6.3), cosi' il cruscotto non conosce il formato
# Anviz e la sorgente puo' cambiare senza toccare i calcoli.
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    source_event_id   TEXT    PRIMARY KEY,
    device_serial     TEXT    NOT NULL,
    employee_code     INTEGER NOT NULL,
    occurred_at_local TEXT    NOT NULL,
    occurred_at_utc   TEXT    NOT NULL,
    device_seconds    INTEGER NOT NULL,
    event_type_raw    INTEGER NOT NULL,
    event_type        INTEGER NOT NULL,
    metodo            TEXT    NOT NULL,
    work_code         INTEGER NOT NULL,
    raw_payload       TEXT    NOT NULL,
    imported_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventi_quando ON raw_events (occurred_at_utc);
CREATE INDEX IF NOT EXISTS idx_eventi_dipendente ON raw_events (employee_code);
"""


def apri_db(percorso: str) -> sqlite3.Connection:
    db = sqlite3.connect(percorso, timeout=15)
    # WAL: chi legge non blocca chi scrive e viceversa. Senza, lo scheduler che
    # salva e l'interfaccia che disegna una schermata si contendono lo stesso
    # lucchetto, e uno dei due prende "database is locked".
    # busy_timeout: se comunque capita, si aspetta invece di fallire subito.
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass                      # su alcuni filesystem di rete WAL non si puo'
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA synchronous=FULL")   # presenze: meglio lente che perse
    db.executescript(SCHEMA)
    return db


def salva(db: sqlite3.Connection, dispositivo: str, righe: list[Timbratura]) -> int:
    ora = dt.datetime.now(FUSO).isoformat(timespec="seconds")
    cur = db.executemany(
        "INSERT OR IGNORE INTO raw_events "
        "(source_event_id, device_serial, employee_code, occurred_at_local, "
        " occurred_at_utc, device_seconds, event_type_raw, event_type, metodo, "
        " work_code, raw_payload, imported_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(t.id_evento(dispositivo), dispositivo, t.user_id,
          t.quando.isoformat(sep=" "),
          t.quando_utc.isoformat(sep=" "),
          t.secondi, t.tipo, t.stato, t.metodo, t.work_code,
          t.raw.hex(), ora) for t in righe],
    )
    db.commit()
    return cur.rowcount


# --- Comandi da riga di comando ---------------------------------------------
def cmd_cerca(a) -> int:
    rete = ipaddress.ip_network(a.rete, strict=False)
    print(f"Cerco terminali su {rete} (porta {a.porta})...")
    trovati = 0
    for ip in rete.hosts():
        s = socket.socket()
        s.settimeout(a.attesa)
        try:
            s.connect((str(ip), a.porta))
        except OSError:
            continue
        finally:
            s.close()
        trovati += 1
        print(f"  {ip}:{a.porta} risponde", end="")
        try:
            with Terminale(str(ip), a.porta, timeout=4) as t:
                print(f"  ->  modello {t.modello()!r}")
        except Exception as e:
            print(f"  ->  ma non parla TC_B ({e})")
    print(f"Fatto: {trovati} dispositivi.")
    return 0 if trovati else 1


def cmd_cerca_udp(a) -> int:
    sorgenti = [a.da] if a.da else sorgenti_locali()
    print(f"Broadcast di ricerca (UDP {UDP_PORTA_DISPOSITIVO}) da: {', '.join(sorgenti)}")
    print("Funziona anche se il terminale non ha un indirizzo IP valido.\n")
    trovati = cerca_udp(sorgenti, a.attesa)
    if not trovati:
        print("Nessuna risposta.")
        print("Se il link e' attivo ma nessuno risponde: il terminale potrebbe")
        print("non supportare la ricerca UDP, oppure avere la rete disattivata a menu.")
        return 1
    for d in trovati:
        print(f"TROVATO  modello {d['modello']!r}  seriale {d['seriale']!r}")
        print(f"  MAC        {d['mac']}")
        print(f"  IP         {d['ip']}   maschera {d['maschera']}   gateway {d['gateway']}")
        print(f"  porta      {d['porta']}")
        print(f"  modo rete  {d['modo_rete']}   server {d['server_ip']}")
        print(f"  firmware   {d['firmware']!r}   device no. {d['device_no']}")
        if "url" in d:
            print(f"  DNS {d['dns']}   URL {d['url']!r}")
        print()
    return 0


def cmd_imposta_ip(a) -> int:
    sorgenti = [a.da] if a.da else sorgenti_locali()
    print(f"Assegno {a.ip}/{a.maschera} al terminale con MAC {a.mac}.")
    print("Il terminale ignora il pacchetto se il MAC non e' il suo.\n")
    risposte = imposta_ip_udp(a.mac, a.ip, a.maschera, a.gateway, a.password,
                              sorgenti, porta=a.porta_dispositivo, utente=a.utente)
    if not risposte:
        print("Nessuna risposta. Il terminale potrebbe avere comunque accettato:")
        print(f"prova  python anviz.py cerca-udp  e poi  python anviz.py info {a.ip}")
        return 1
    for r in risposte:
        print(f"risposta da {r['da']}: {r['esito']}")
    return 0


def cmd_info(a) -> int:
    with Terminale(a.host, a.porta, a.ch) as t:
        print(f"Terminale   {a.host}:{a.porta}")
        for etichetta, funzione in (("Modello", t.modello), ("Device ID", t.device_id)):
            try:
                print(f"{etichetta:<12}{funzione()}")
            except Exception as e:
                print(f"{etichetta:<12}non leggibile ({e})")
        try:
            suo = t.orologio()
            nostro = dt.datetime.now()
            scarto = (suo - nostro).total_seconds()
            print(f"{'Orologio':<12}{suo}  (scarto {scarto:+.0f}s rispetto a questo PC)")
            if abs(scarto) > 60:
                print("             ATTENZIONE: l'orario lo timbra il terminale. "
                      "Allinealo con  orologio --imposta")
        except Exception as e:
            print(f"{'Orologio':<12}non leggibile ({e})")
        try:
            c = t.conteggi()
            print(f"{'Utenti':<12}{c['utenti']}   badge {c['badge']}  "
                  f"password {c['password']}  impronte {c['impronte']}")
            print(f"{'Timbrature':<12}{c['timbrature']} in memoria, di cui "
                  f"{c['nuove']} mai scaricate")
        except Exception as e:
            print(f"{'Timbrature':<12}non leggibili ({e})")
    return 0


def cmd_scarica(a) -> int:
    epoca = EPOCA_SPEC if a.epoca_specifica else EPOCA_DEFAULT
    with Terminale(a.host, a.porta, a.ch) as t:
        if a.allinea_orologio:
            # Si allinea PRIMA di scaricare, mai dopo: cosi' i record appena
            # letti restano coerenti con l'orologio che li ha timbrati.
            scarto = (t.orologio() - dt.datetime.now()).total_seconds()
            if abs(scarto) >= a.tolleranza:
                t.imposta_orologio()
                print(f"Orologio riallineato (era {scarto:+.0f}s).")
            else:
                print(f"Orologio entro tolleranza ({scarto:+.0f}s): non lo tocco.")
        prima = t.conteggi()
        attese = prima["nuove"] if a.nuove else prima["timbrature"]
        print(f"Da scaricare: {attese} timbrature "
              f"({'solo nuove' if a.nuove else 'tutte quelle in memoria'})")
        righe = []
        for tb in t.timbrature(solo_nuove=a.nuove, epoca=epoca):
            righe.append(tb)
            if len(righe) % 100 == 0:
                print(f"  ...{len(righe)}", end="\r", flush=True)
        print(f"Scaricate {len(righe)} timbrature.        ")

        if not righe:
            return 0

        nuove_su_db = 0
        if a.db:
            db = apri_db(a.db)
            nuove_su_db = salva(db, a.host, righe)
            db.close()
            print(f"Salvate su {a.db}: {nuove_su_db} nuove, "
                  f"{len(righe) - nuove_su_db} gia' presenti.")
        if a.csv:
            with open(a.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["source_event_id", "device_serial", "employee_code",
                            "occurred_at_local", "occurred_at_utc",
                            "event_type_raw", "event_type", "metodo",
                            "work_code", "raw_payload"])
                for tb in righe:
                    w.writerow([tb.id_evento(a.host), a.host, tb.user_id,
                                tb.quando.isoformat(sep=" "),
                                tb.quando_utc.isoformat(sep=" "),
                                tb.tipo, tb.stato, tb.metodo, tb.work_code,
                                tb.raw.hex()])
            print(f"Esportate su {a.csv}.")

        # Il flag "nuova" si azzera solo dopo aver messo al sicuro i dati.
        if a.nuove and a.conferma:
            t.marca_nuove_scaricate(len(righe))
            print(f"Azzerato il flag 'nuova' su {len(righe)} timbrature.")
        elif a.nuove:
            print("Flag 'nuova' NON azzerato (manca --conferma): "
                  "al prossimo giro le riscarica.")

        ultima = max(righe, key=lambda r: r.secondi)
        print(f"\nUltima timbratura: {ultima.quando}  (utente {ultima.user_id})")
        if a.epoca_specifica:
            print("  Stai usando l'epoca della specifica, che sul W1C Pro e'")
            print("  sbagliata di un giorno. Togli --epoca-specifica.")
    return 0


def cmd_orologio(a) -> int:
    with Terminale(a.host, a.porta, a.ch) as t:
        print(f"Terminale: {t.orologio()}")
        print(f"Questo PC: {dt.datetime.now().replace(microsecond=0)}")
        if a.imposta:
            t.imposta_orologio()
            print(f"Reimpostato a: {t.orologio()}")
    return 0


def cmd_ascolta(a) -> int:
    epoca = EPOCA_SPEC if a.epoca_specifica else EPOCA_DEFAULT
    db = apri_db(a.db) if a.db else None
    print(f"In ascolto su {a.host}:{a.porta}. Timbra un badge. Ctrl-C per uscire.")
    print("(funziona solo se il terminale ha la modalita' real-time attiva)")
    try:
        with Terminale(a.host, a.porta, a.ch) as t:
            for tb in t.ascolta(epoca=epoca):
                print(f"{tb.quando}  utente {tb.user_id:<8} {tb.metodo:<12} "
                      f"stato {tb.stato}")
                if db:
                    salva(db, a.host, [tb])
    except KeyboardInterrupt:
        print("\nInterrotto.")
    finally:
        if db:
            db.close()
    return 0


def cmd_rete(a) -> int:
    with Terminale(a.host, a.porta, a.ch) as t:
        c = t.rete_decodificata()
        print(f"IP          {c['ip']}   maschera {c['maschera']}")
        print(f"gateway     {c['gateway']}   server {c['server_ip']}")
        print(f"MAC         {c['mac']}")
        print(f"porta       {c['porta']}   modo {c['modo_rete']}")
        print(f"DHCP        {'attivo' if c['dhcp'] else 'spento (indirizzo fisso)'}")
        if a.statico or a.dhcp:
            volere = bool(a.dhcp)
            if c["dhcp"] == volere:
                print("\nGia' cosi': non scrivo nulla.")
                return 0
            print(f"\nPasso a DHCP {'attivo' if volere else 'spento'}...")
            t.imposta_dhcp(volere)
            dopo = t.rete_decodificata()
            print(f"Ora: IP {dopo['ip']}  porta {dopo['porta']}  "
                  f"DHCP {'attivo' if dopo['dhcp'] else 'spento'}")
            if dopo["dhcp"] != volere:
                print("ATTENZIONE: il terminale non ha accettato la modifica.")
                return 1
    return 0


def cmd_azzera(a) -> int:
    with Terminale(a.host, a.porta, a.ch) as t:
        prima = t.conteggi()
        print(f"Il terminale ha {prima['timbrature']} timbrature in memoria.")
        if not a.conferma:
            print("Nessuna cancellazione: manca --conferma.")
            return 1
        t.azzera_timbrature()
        dopo = t.conteggi()
        print(f"Cancellate. Ora ne ha {dopo['timbrature']} "
              f"({dopo['nuove']} da scaricare).")
        return 0 if dopo["timbrature"] == 0 else 1


def cmd_raw(a) -> int:
    """Sonda un comando qualsiasi: serve per capire cosa supporta il ferro."""
    dati = bytes.fromhex(a.dati) if a.dati else b""
    with Terminale(a.host, a.porta, a.ch) as t:
        cmd = int(a.cmd, 16)
        pacchetto = t._pacchetto(cmd, dati)
        print(f"-> {pacchetto.hex(' ')}")
        t.sock.sendall(pacchetto)
        ack, ret, corpo = t.leggi_risposta()
        print(f"<- ack {ack:#04x}  ret {ret:#04x} ({RET.get(ret, '?')})  "
              f"{len(corpo)} byte")
        if corpo:
            print(f"   {corpo.hex(' ')}")
            print(f"   {corpo.decode('ascii', 'replace')!r}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="azione", required=True)

    def comune(sp):
        sp.add_argument("host")
        sp.add_argument("--porta", type=int, default=PORTA_DEFAULT)
        sp.add_argument("--ch", type=int, default=CH_BROADCAST,
                        help="device code; 0 = qualunque terminale risponde")

    sp = sub.add_parser("cerca", help="cerca terminali in una sottorete")
    sp.add_argument("rete", help="es. 192.168.1.0/24")
    sp.add_argument("--porta", type=int, default=PORTA_DEFAULT)
    sp.add_argument("--attesa", type=float, default=0.3)
    sp.set_defaults(f=cmd_cerca)

    sp = sub.add_parser("cerca-udp",
                        help="cerca via broadcast UDP, anche senza IP valido")
    sp.add_argument("--da", help="IP dell'interfaccia da cui trasmettere")
    sp.add_argument("--attesa", type=float, default=4.0)
    sp.set_defaults(f=cmd_cerca_udp)

    sp = sub.add_parser("imposta-ip",
                        help="assegna un IP statico via UDP conoscendo il MAC")
    sp.add_argument("mac", help="MAC del terminale, es. 00:22:ca:8c:0b:ff")
    sp.add_argument("ip")
    sp.add_argument("--maschera", default="255.255.255.0")
    sp.add_argument("--gateway", default="0.0.0.0")
    sp.add_argument("--porta-dispositivo", type=int, default=PORTA_DEFAULT)
    sp.add_argument("--password", default="12345",
                    help="password amministratore del terminale")
    sp.add_argument("--utente", default="")
    sp.add_argument("--da", help="IP dell'interfaccia da cui trasmettere")
    sp.set_defaults(f=cmd_imposta_ip)

    sp = sub.add_parser("info", help="modello, orologio, conteggi")
    comune(sp)
    sp.set_defaults(f=cmd_info)

    sp = sub.add_parser("scarica", help="scarica le timbrature")
    comune(sp)
    sp.add_argument("--nuove", action="store_true",
                    help="solo quelle mai scaricate")
    sp.add_argument("--conferma", action="store_true",
                    help="azzera il flag 'nuova' dopo il salvataggio")
    sp.add_argument("--db", default="timbrature.db")
    sp.add_argument("--csv")
    sp.add_argument("--epoca-specifica", action="store_true",
                    help="usa 2000-01-01 come da specifica (sbagliata: -1 giorno)")
    sp.add_argument("--allinea-orologio", action="store_true",
                    help="riallinea l'orologio del terminale prima di scaricare")
    sp.add_argument("--tolleranza", type=float, default=30.0,
                    help="secondi di scarto tollerati (predefinito 30)")
    sp.set_defaults(f=cmd_scarica)

    sp = sub.add_parser("orologio", help="legge/imposta l'orologio del terminale")
    comune(sp)
    sp.add_argument("--imposta", action="store_true")
    sp.set_defaults(f=cmd_orologio)

    sp = sub.add_parser("ascolta", help="timbrature in tempo reale")
    comune(sp)
    sp.add_argument("--db")
    sp.add_argument("--epoca-specifica", action="store_true")
    sp.set_defaults(f=cmd_ascolta)

    sp = sub.add_parser("rete", help="mostra/cambia la configurazione di rete")
    comune(sp)
    gruppo = sp.add_mutually_exclusive_group()
    gruppo.add_argument("--statico", action="store_true",
                        help="spegne il DHCP: l'indirizzo attuale diventa fisso")
    gruppo.add_argument("--dhcp", action="store_true", help="riaccende il DHCP")
    sp.set_defaults(f=cmd_rete)

    sp = sub.add_parser("azzera", help="cancella TUTTE le timbrature dal terminale")
    comune(sp)
    sp.add_argument("--conferma", action="store_true",
                    help="senza questo non cancella nulla")
    sp.set_defaults(f=cmd_azzera)

    sp = sub.add_parser("raw", help="manda un comando grezzo (sonda)")
    comune(sp)
    sp.add_argument("cmd", help="codice esadecimale, es. 30")
    sp.add_argument("dati", nargs="?", help="payload esadecimale")
    sp.set_defaults(f=cmd_raw)

    a = p.parse_args(argv)
    try:
        return a.f(a)
    except (ErroreAnviz, OSError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
