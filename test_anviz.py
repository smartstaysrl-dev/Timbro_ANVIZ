# Copyright (c) 2026 Nicola Bonazzi, Andrea D'Aniello.
# Tutti i diritti riservati. Uso consentito solo a chi ha ricevuto una
# licenza scritta dai titolari: vedi LICENSE. Il fatto che il codice sia
# leggibile non e' un permesso.
"""Collaudo del client contro un finto terminale Anviz in locale."""
import datetime as dt, socket, threading, sys, importlib.util, pathlib

spec = importlib.util.spec_from_file_location(
    "anviz", pathlib.Path(__file__).with_name("anviz.py"))
A = importlib.util.module_from_spec(spec)
sys.modules["anviz"] = A
spec.loader.exec_module(A)


def frame(ch, ack, ret, data):
    body = (bytes([0xA5]) + ch.to_bytes(4, 'big') + bytes([ack, ret])
            + len(data).to_bytes(2, 'big') + data)
    return body + A.crc16(body).to_bytes(2, 'little')


def rec(uid, secs, backup, tipo, wc=0):
    return (uid.to_bytes(5, 'big') + secs.to_bytes(4, 'big')
            + bytes([backup, tipo]) + wc.to_bytes(3, 'big'))


SECS = int((dt.datetime(2026, 9, 1, 8, 32, 10) - A.EPOCA_DEFAULT).total_seconds())


def finto_terminale(sock):
    conn, _ = sock.accept()
    pagina = 0
    letture = 0
    while True:
        head = conn.recv(9)
        if not head:
            break
        cmd = head[5]
        ln = int.from_bytes(head[6:8], 'big')
        if ln:
            conn.recv(ln)
        conn.recv(2)
        if cmd == 0x48:
            conn.sendall(frame(0, 0xC8, 0, b'W1C Pro '))
        elif cmd == 0x38:
            conn.sendall(frame(0, 0xB8, 0, bytes([26, 9, 1, 8, 35, 0])))
        elif cmd == 0x3C:
            d = b''.join(x.to_bytes(3, 'big') for x in [12, 0, 2, 12, 3, 3])
            conn.sendall(frame(0, 0xBC, 0, d))
        elif cmd == 0x40:
            if pagina == 0:
                body = (bytes([3])
                        + rec(4317, SECS, 0b1000, 0x80)
                        + rec(21, SECS + 60, 0b0100, 0x81)
                        + rec(999999, SECS + 120, 0b0001, 0x00))
                pagina = 1
            else:
                body = bytes([0])
            conn.sendall(frame(0, 0xC0, 0, body))
        elif cmd == 0x4E:
            conn.sendall(frame(0, 0xCE, 0, b''))
        elif cmd == 0x7E:
            # Lettura tessera: prima nessuna, poi il badge appoggiato.
            # E' la sequenza vera, ed e' il motivo per cui il dialogo butta
            # via la prima lettura e poi insiste.
            conn.sendall(frame(0, 0xFE, 0,
                               (0 if letture == 0 else 12660233).to_bytes(4, 'big')))
            letture += 1
        else:
            conn.sendall(frame(0, cmd + 0x80, 0x01, b''))


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', 15010))
s.listen(1)
threading.Thread(target=finto_terminale, args=(s,), daemon=True).start()

with A.Terminale('127.0.0.1', 15010) as t:
    print('modello   :', repr(t.modello()))
    print('orologio  :', t.orologio())
    print('conteggi  :', t.conteggi())
    tb = list(t.timbrature())
    for x in tb:
        print(f'  utente {x.user_id:<8} {x.quando}  {x.metodo:<12} '
              f'stato={x.stato} porta={x.apre_porta}')
    t.marca_nuove_scaricate(len(tb))
    print('flag azzerato OK')
    # Lettura tessera: la prima risposta e' zero (nessuna tessera appoggiata),
    # la seconda porta il numero. Chi legge una volta sola e si accontenta
    # dello zero non iscriverebbe mai niente.
    tessera_vuota = t.numero_tessera()
    tessera_letta = t.numero_tessera()

assert tessera_vuota == 0, f'nessuna tessera doveva dare 0, ha dato {tessera_vuota}'
assert tessera_letta == 12660233, f'tessera letta {tessera_letta}'
print('lettura tessera: 0x7E interrogato finche\' non arriva il numero')

assert len(tb) == 3, 'paginazione rotta'
assert tb[0].user_id == 4317, 'user id rotto'
assert tb[0].quando == dt.datetime(2026, 9, 1, 8, 32, 10), 'data/ora rotta'
assert tb[0].metodo == 'badge' and tb[1].metodo == 'password'
assert tb[2].metodo == 'impronta 1' and tb[2].user_id == 999999
assert tb[0].apre_porta and not tb[2].apre_porta

# L'epoca predefinita e' quella verificata sul dispositivo (2000-01-02), non
# quella della specifica: se qualcuno la rimette a 2000-01-01 si sbaglia di un
# giorno esatto e questo controllo lo intercetta.
assert A.EPOCA_DEFAULT == dt.datetime(2000, 1, 2), 'epoca predefinita cambiata'
sballato = A.Timbratura.da_bytes(tb[0].raw, A.EPOCA_SPEC)
assert (tb[0].quando - sballato.quando) == dt.timedelta(days=1)

# --- evento normalizzato ---------------------------------------------------
# 1 settembre = ora legale a Roma, quindi UTC+2.
assert tb[0].quando_utc.hour == 6 and tb[0].quando_utc.minute == 32, \
    'conversione UTC sbagliata'
assert tb[0].raw and len(tb[0].raw) == 14, 'payload grezzo non conservato'
assert tb[0].id_evento('X') == tb[0].id_evento('X'), 'id evento non deterministico'
assert tb[0].id_evento('X') != tb[1].id_evento('X'), 'id evento collide'
assert tb[0].id_evento('X') != tb[0].id_evento('Y'), 'id evento ignora il device'

# --- idempotenza: rileggere due volte non deve duplicare -------------------
import os, tempfile
percorso = os.path.join(tempfile.mkdtemp(), 'prova.db')
db = A.apri_db(percorso)
primo = A.salva(db, '10.0.0.1', tb)
secondo = A.salva(db, '10.0.0.1', tb)
totale = db.execute('SELECT COUNT(*) FROM raw_events').fetchone()[0]
db.close()
assert primo == 3, f'primo salvataggio: {primo} righe invece di 3'
assert secondo == 0, f'secondo salvataggio ha duplicato {secondo} righe'
assert totale == 3, f'in archivio {totale} righe invece di 3'
print(f'archivio: {primo} inserite, {secondo} duplicate scartate, {totale} totali')


# --- record utente: il campo permessi e' l'ULTIMO byte ----------------------
# Difetto trovato in revisione: il codice usava raw[37] (byte alto della
# password) come campo permessi. Con l'unico utente reale disponibile i due
# byte valevano entrambi 0x40, quindi qualunque lettura sembrava giusta. Qui
# si costruiscono apposta record in cui i due byte DIVERGONO, cosi' un ritorno
# all'offset sbagliato non puo' passare inosservato.
def utente_grezzo(pw_ms, riservato, permessi, pw=b"\xff\xff\xff"):
    b = bytearray(40)
    b[0:5] = (7).to_bytes(5, "big")
    b[5:8] = pw
    b[8:12] = (12660233).to_bytes(4, "big")
    b[12:32] = "Rossi".encode("utf-16-be").ljust(20, b"\x00")
    b[32], b[33], b[34] = 0, 1, 6
    b[35:37] = b"\x00\x00"
    b[37], b[38], b[39] = pw_ms, riservato, permessi
    return bytes(b)


# Amministratore vero: permessi 0xC0 in coda, byte alto password diverso.
admin = A.Utente.da_bytes(utente_grezzo(0x0A, 0x00, 0xC0, pw=b"\x81\x23\x45"))
assert admin.amministratore, "un amministratore non viene riconosciuto"

# Utente normale con un byte alto password che, letto come permessi, direbbe
# "amministratore": e' esattamente il caso che l'offset sbagliato sbagliava.
normale = A.Utente.da_bytes(utente_grezzo(0xFF, 0x00, 0x40))
assert not normale.amministratore, \
    "il byte alto della password viene scambiato per il campo permessi"

# Scrivere non deve toccare password, byte alto password e riservato.
originale = utente_grezzo(0x0A, 0x55, 0xC0, pw=b"\x81\x23\x45")
u = A.Utente.da_bytes(originale)
riscritto = u.a_bytes()
assert riscritto[5:8] == originale[5:8], "la password e' stata alterata"
assert riscritto[37] == originale[37], "il byte alto della password e' stato alterato"
assert riscritto[38] == originale[38], "il byte riservato e' stato alterato"
assert riscritto == originale, f"giro r/w non neutro: {riscritto.hex(' ')}"

# Cambiando solo il nome cambiano solo i byte del nome.
u2 = A.Utente.da_bytes(originale)
u2.nome = "Bianchi"
diverso = u2.a_bytes()
cambiati = {i for i in range(40) if diverso[i] != originale[i]}
assert cambiati and cambiati <= set(range(12, 32)), \
    f"cambiando il nome sono cambiati anche i byte {sorted(cambiati - set(range(12,32)))}"

# Il formato legacy a 27 byte tiene i permessi nell'ultimo byte suo.
legacy = bytearray(27)
legacy[0:5] = (7).to_bytes(5, "big")
legacy[5:8] = b"\xff\xff\xff"
legacy[8:11] = b"\xff\xff\xff"
legacy[26] = 0xC0
assert A.Utente.da_bytes(bytes(legacy)).amministratore, "formato a 27 byte rotto"
print('record utente: permessi in coda, password intatta')


# --- PIN --------------------------------------------------------------------
# Il PIN vive in tre posti: il nibble alto del byte 5 dice quante cifre sono,
# i 20 bit rimanenti piu' il byte 37 dicono il valore. Verificato sul ferro il
# 1 set 2026: PIN 1234 scritto sull'utente 902 come 40 04 d2, riletto uguale.
letto = A.Utente.da_bytes(utente_grezzo(0x00, 0x00, 0x40, pw=b"\x40\x04\xd2"))
assert letto.password == "1234", f"PIN riletto {letto.password!r} invece di '1234'"
assert letto.ha_password

# Nessuna password: 0xFF sui tre byte.
assert A.Utente.da_bytes(utente_grezzo(0xFF, 0, 0x40)).password is None

# Gli zeri iniziali NON si perdono: "0042" e' un PIN diverso da "42", e la
# differenza sta solo nel numero di cifre dichiarato.
zeri = A.Utente.da_bytes(utente_grezzo(0x00, 0x00, 0x40, pw=b"\x40\x00\x2a"))
assert zeri.password == "0042", f"zeri iniziali persi: {zeri.password!r}"

# Andata e ritorno per ogni lunghezza, zeri iniziali compresi.
for pin in ("1", "42", "0042", "123456", "000001", "99999999"):
    u3 = A.Utente.da_bytes(utente_grezzo(0xFF, 0x00, 0x40))
    u3.imposta_password(pin)
    ritorno = A.Utente.da_bytes(u3.a_bytes())
    assert ritorno.password == pin, f"PIN {pin} torna come {ritorno.password!r}"
    assert ritorno.ha_password

# Togliere il PIN lo cancella davvero, e chi lo aveva risulta senza.
u4 = A.Utente.da_bytes(utente_grezzo(0x00, 0x00, 0x40, pw=b"\x40\x04\xd2"))
u4.imposta_password(None)
tolto = A.Utente.da_bytes(u4.a_bytes())
assert tolto.password is None and not tolto.ha_password, "il PIN non e' stato tolto"

# Chi NON tocca il PIN non deve riscriverlo: e' la guardia che impedisce di
# cancellare la password a un dipendente mentre gli si cambia il reparto.
prima = utente_grezzo(0x0A, 0x00, 0x40, pw=b"\x81\x23\x45")
u5 = A.Utente.da_bytes(prima)
u5.reparto = 3
dopo = u5.a_bytes()
assert dopo[5:8] == prima[5:8] and dopo[37] == prima[37], \
    "cambiando il reparto e' stata riscritta la password"

# Cifre non valide: si rifiuta invece di scrivere spazzatura sul terminale.
for cattivo in ("12a4", "12 34", "123456789"):
    try:
        A.Utente.da_bytes(utente_grezzo(0xFF, 0, 0x40)).imposta_password(cattivo)
        assert False, f"PIN {cattivo!r} accettato"
    except ValueError:
        pass
print('PIN: scritto, riletto, zeri iniziali salvi, non riscritto per sbaglio')


# --- fuso di riserva --------------------------------------------------------
# Windows non ha il database dei fusi: senza il pacchetto tzdata l'intero
# programma non partirebbe. Esiste quindi un ripiego calcolato a mano, e qui si
# controlla che dia gli stessi identici risultati di zoneinfo, ora per ora.
try:
    from zoneinfo import ZoneInfo
    riferimento = ZoneInfo("Europe/Rome")
except Exception:
    riferimento = None

if riferimento is not None:
    riserva = A.FusoItalia()
    divergenze, provate = [], 0
    momento = dt.datetime(2020, 1, 1)
    while momento.year < 2036:
        a = momento.replace(tzinfo=riferimento).utcoffset()
        b = momento.replace(tzinfo=riserva).utcoffset()
        provate += 1
        if a != b:
            divergenze.append((momento, a, b))
        momento += dt.timedelta(hours=1)
    assert not divergenze, \
        f"{len(divergenze)} divergenze, la prima: {divergenze[0]}"
    print(f'fuso di riserva: {provate} ore confrontate su 16 anni, nessuna divergenza')
else:
    print('fuso di riserva: zoneinfo non disponibile, confronto saltato')

# I confini devono cadere sull'ultima domenica, non su una data fissa.
assert A._ultima_domenica(2026, 3) == dt.date(2026, 3, 29), A._ultima_domenica(2026, 3)
assert A._ultima_domenica(2026, 10) == dt.date(2026, 10, 25)
assert A._ultima_domenica(2027, 3) == dt.date(2027, 3, 28)

print('\nTUTTI I CONTROLLI PASSATI')
