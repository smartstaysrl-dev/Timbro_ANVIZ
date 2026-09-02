#!/usr/bin/env python3
# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""
Assegna un indirizzo al terminale rispondendo alle sue richieste DHCP.

Serve solo a ripescare un terminale lasciato in DHCP su un collegamento dove
nessuno distribuisce indirizzi (tipicamente il cavo diretto PC-terminale, o un
ripristino di fabbrica). Una volta che il terminale risponde, conviene fissargli
un indirizzo statico e smettere di usare questo script.

    python bootstrap_dhcp.py 00:22:ca:8c:0b:ff --offri 192.168.0.218 --da 192.168.0.10

SICUREZZA: risponde ESCLUSIVAMENTE al MAC indicato sulla riga di comando. Le
richieste di qualunque altro dispositivo vengono registrate e ignorate, quindi
non puo' interferire col DHCP del router di casa nemmeno se la porta e' in
ascolto su tutte le interfacce.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time

PORTA_SERVER, PORTA_CLIENT = 67, 68
COOKIE = bytes([99, 130, 83, 99])
DISCOVER, OFFER, REQUEST, ACK = 1, 2, 3, 5
TIPI = {1: "DISCOVER", 3: "REQUEST", 4: "DECLINE", 7: "RELEASE", 8: "INFORM"}


def ottetti(s: str) -> bytes:
    return bytes(int(x) for x in s.split("."))


def leggi_mac(s: str) -> bytes:
    return bytes(int(x, 16) for x in s.replace("-", ":").split(":"))


def mostra_mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def opzioni(dati: bytes) -> dict[int, bytes]:
    fuori, i = {}, 0
    corpo = dati[240:]
    while i < len(corpo) and corpo[i] != 255:
        if corpo[i] == 0:
            i += 1
            continue
        codice, lung = corpo[i], corpo[i + 1]
        fuori[codice] = corpo[i + 2:i + 2 + lung]
        i += 2 + lung
    return fuori


def costruisci_risposta(richiesta: bytes, tipo: int, offerto: str, server: str,
                        maschera: str, gateway: str | None, lease: int) -> bytes:
    xid = richiesta[4:8]
    flags = richiesta[10:12]
    chaddr = richiesta[28:44]

    pkt = bytearray()
    pkt += bytes([2, 1, 6, 0])          # op=BOOTREPLY, ethernet, 6 byte di MAC
    pkt += xid
    pkt += b"\x00\x00"                  # secs
    pkt += flags                        # si conserva il bit di broadcast
    pkt += bytes(4)                     # ciaddr
    pkt += ottetti(offerto)             # yiaddr: l'indirizzo che gli diamo
    pkt += ottetti(server)              # siaddr
    pkt += bytes(4)                     # giaddr
    pkt += chaddr
    pkt += bytes(64) + bytes(128)       # sname, file
    pkt += COOKIE

    def opz(codice: int, valore: bytes) -> bytes:
        return bytes([codice, len(valore)]) + valore

    pkt += opz(53, bytes([tipo]))
    pkt += opz(54, ottetti(server))                     # identificativo server
    pkt += opz(51, struct.pack("!I", lease))            # durata
    pkt += opz(1, ottetti(maschera))
    if gateway:
        pkt += opz(3, ottetti(gateway))
    pkt += b"\xff"
    return bytes(pkt)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mac", help="MAC del terminale: si risponde SOLO a questo")
    p.add_argument("--offri", required=True, help="indirizzo da assegnare")
    p.add_argument("--da", required=True, help="IP di questo PC sul collegamento")
    p.add_argument("--maschera", default="255.255.255.0")
    p.add_argument("--gateway", default=None,
                   help="predefinito: nessuno, cosi' il terminale non instrada")
    p.add_argument("--lease", type=int, default=7 * 86400)
    p.add_argument("--durata", type=int, default=180,
                   help="secondi di servizio prima di fermarsi")
    a = p.parse_args(argv)

    bersaglio = leggi_mac(a.mac)

    ascolto = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ascolto.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ascolto.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        ascolto.bind(("0.0.0.0", PORTA_SERVER))
    except OSError as e:
        print(f"Non riesco ad ascoltare sulla porta {PORTA_SERVER}: {e}")
        return 2
    ascolto.settimeout(1.0)

    # Si trasmette dall'indirizzo del collegamento diretto, cosi' la risposta
    # esce dalla scheda giusta e non dal Wi-Fi.
    invio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    invio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    invio.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        invio.bind((a.da, PORTA_SERVER))
    except OSError:
        invio.close()
        invio = ascolto  # ripiego: si usa la stessa presa

    print(f"Rispondo SOLO al MAC {mostra_mac(bersaglio)} con {a.offri}/{a.maschera}.")
    print(f"Trasmetto da {a.da}. Qualunque altro dispositivo viene ignorato.")
    print(f"Servizio attivo per {a.durata} secondi.\n")

    fine = time.time() + a.durata
    ignorati, assegnato = set(), False
    while time.time() < fine:
        try:
            dati, _ = ascolto.recvfrom(2048)
        except socket.timeout:
            continue
        if len(dati) < 240 or dati[0] != 1:
            continue
        mac = dati[28:34]
        opz = opzioni(dati)
        tipo = opz.get(53, b"\x00")[0]

        if mac != bersaglio:
            if mac not in ignorati:
                ignorati.add(mac)
                print(f"  (ignorato {mostra_mac(mac)}: non e' il terminale)")
            continue

        nome = TIPI.get(tipo, str(tipo))
        print(f"[{time.strftime('%H:%M:%S')}] {nome} dal terminale")
        if tipo == DISCOVER:
            risposta, etichetta = OFFER, "OFFER"
        elif tipo == REQUEST:
            risposta, etichetta = ACK, "ACK"
        else:
            continue

        pkt = costruisci_risposta(dati, risposta, a.offri, a.da,
                                  a.maschera, a.gateway, a.lease)
        invio.sendto(pkt, ("255.255.255.255", PORTA_CLIENT))
        print(f"           -> {etichetta} {a.offri}")
        if risposta == ACK:
            assegnato = True
            print(f"\nIndirizzo assegnato. Ora prova:")
            print(f"   python anviz.py info {a.offri}")
            break

    ascolto.close()
    if invio is not ascolto:
        invio.close()
    if not assegnato:
        print("\nNessun indirizzo assegnato: il terminale non ha completato lo scambio.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
