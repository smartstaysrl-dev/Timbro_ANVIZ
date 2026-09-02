<p align="center">
  <img src="logo/timbra-logo.svg" alt="TIMBRA — Presenze" width="440">
</p>

# TIMBRA — presenze da terminale Anviz W1C Pro

Applicazione touch che parla direttamente col terminale in LAN (TCP porta 5010),
senza cloud, senza CrossChex, senza browser.

**Contesto:** un ristorante, un terminale, badge RFID/PIN. Gira su un mini PC o
sul registratore di cassa; il gestore la avvia con un doppio clic e la usa col
dito. Copre gli strati 2-5 dell'architettura del documento operativo v1.0
(1 set 2026): acquisizione, archivio grezzo, motore delle regole, cruscotto.

    python gestione.py

## I pezzi

| File | Cosa fa |
|------|---------|
| `anviz.py` | il protocollo TC_B: parla col terminale. Anche da riga di comando. |
| `presenze.py` | il motore: da timbrature grezze a ore lavorate |
| `interfaccia.py` | i mattoni touch: bottoni, liste, tastiere a schermo |
| `gestione.py` | l'applicazione: cinque schermate |
| `bootstrap_dhcp.py` | ripesca il terminale quando resta senza indirizzo |
| `copie.py` | le copie di sicurezza giornaliere, verificate |
| `posta.py` | il report mensile via email: quando spedirlo e cosa scriverci |
| `sicurezza.py` | il PIN delle sezioni pericolose, l'offuscamento, l'istanza unica |
| `guida.py` | il manuale dell'operatore, che si apre dal «?» dentro il programma |
| `logo.py` | il marchio disegnato su tela Tk, e la finestrella di avvio |
| `scatti_guida.py` | rifà le figure della guida su un archivio inventato |
| `crea_pacchetto.py` · `crea_icona.py` | preparano la cartella da copiare in sede |
| `guida_pdf.py` | stampa la stessa guida in PDF (`TIMBRA - guida.pdf`) |
| `test_anviz.py` · `test_presenze.py` · `test_copie.py` · `test_grafico.py` · `test_sicurezza.py` · `test_posta.py` | i collaudi |

Nessuna dipendenza esterna: solo la libreria standard di Python 3.10+.

## Cosa sa fare

**Raccolta automatica.** Uno scheduler interno interroga il terminale ogni N
minuti, scarica solo le timbrature nuove, riallinea l'orologio e registra
l'esito. La barra di stato dice sempre quand'è stato l'ultimo collegamento
riuscito: se il terminale smette di rispondere si vede subito, invece di
scoprirlo a fine mese.

**Anagrafica completa, scritta sul terminale.** Nome, tessera, PIN, reparto,
gruppo, modalità di identificazione e permessi di amministratore. Si creano, si
modificano e si eliminano dipendenti senza toccare il dispositivo. **La tessera
la legge il terminale**: si preme "Leggila dal terminale" e si avvicina il
badge al lettore, come nell'iscrizione in loco. Solo le impronte restano sul
dispositivo, perché richiedono il dito.

**Presenze calcolate.** Turni accoppiati entrata/uscita, turni spezzati,
notturni oltre la mezzanotte, doppioni, straordinari, pause, arrotondamenti.
Con le anomalie in evidenza invece che nascoste.

**Giorno, settimana, mese.** La schermata Presenze si filtra sui tre periodi;
le frecce si spostano di un giorno, di una settimana o di un mese, e
l'esportazione segue quello che stai guardando. A settimana e a mese la scheda
è per persona (ore totali, giorni lavorati, media, straordinario), non una riga
per giornata: quattordici dipendenti per trenta giorni farebbero quattrocento
righe da scorrere per capire chi ha fatto più ore.

**Il grafico sotto l'elenco.** A giorno, una riga per persona e la barra che va
dall'entrata all'uscita, con le ore scritte sopra: i turni spezzati diventano
due barre con il buco della pausa in mezzo. A settimana e a mese, una colonna
per giorno alta quanto le ore fatte — toccandola si apre quel giorno. Verde è
un turno chiuso, giallo uno ancora in corso, rosso un'uscita mai timbrata.
Dettagli in *Il grafico non inventa ore*, più sotto.

**Rettifiche tracciate.** Una timbratura dimenticata si aggiunge, una sbagliata
si annulla — sempre con motivo e autore. Il dato grezzo non viene mai toccato.

**Il report mensile arriva per email**, con il riepilogo per persona nel testo,
il mese giorno per giorno in figura e il foglio da aprire in Excel allegato.
Si sceglie il giorno del mese e l'ora; racconta sempre il mese appena chiuso.

**Una copia sola dell'applicazione**, e le sezioni pericolose sotto PIN.

**La guida è dentro il programma**, col «?» in alto a destra: dieci capitoli
con le figure di ogni passaggio. Le figure si rifanno con `scatti_guida.py`, e
sono fatte su un archivio inventato con nomi di fantasia — un manuale con
dentro nomi e orari veri è un documento che gira per il locale e si stampa.

**Esportazione mensile** in CSV per il consulente paghe, che avvisa se ci sono
anomalie ancora aperte.

## Le quattro strade, e perché sono meno diverse di quanto sembri

Il documento operativo ne elenca quattro. La ricognizione tecnica ha mostrato che
tre finiscono sullo stesso filo:

| Strada | Come arriva al dato | Costo di ingresso |
|--------|--------------------|-------------------|
| **A. CrossChex Standard + export TXT** | PC Windows sempre acceso con CrossChex aperto, export a file su cartella | nullo, ma va parsato un file |
| **B. Local Web API (Docker)** | container che espone REST/JWT su 5011 e **parla TC_B sulla 5010** | domanda di *Anviz Integrator Partner*, licenza da chiarire |
| **C. CrossChex Cloud API** | i dati passano dal cloud Anviz, si leggono via REST | Developer Mode da far attivare ad Anviz |
| **D. SDK / protocollo diretto** | TC_B sulla 5010, che è **quello che fa questo repo** | nessuno |

Il punto non ovvio: la Local Web API è un wrapper Python attorno a
`libtc-b_new_sdk.so` — la stessa libreria di CrossChex — e verso il dispositivo
parla **esattamente il protocollo TC_B sulla porta 5010** implementato qui. B e D
non sono due strade: sono la stessa strada, una con la facciata REST del
fornitore e la trafila da partner, l'altra con 400 righe di Python senza
dipendenze. Ne segue che **la compatibilità del W1C Pro col TC_B è la stessa
incognita per entrambe**, e si risolve con un solo comando.

Rispetto alla strada A, il protocollo diretto toglie di mezzo il PC Windows con
CrossChex aperto, il parsing dei file, i file troncati e la gestione dei
duplicati — cioè quasi tutti i limiti elencati ai par. 1.2 e 6.1 del documento. E
il "comportamento di conferma/avanzamento del puntatore" che il par. 6.2 chiede
ad Anviz qui esiste già nativo: è il flag "nuova" con conferma esplicita.

## Il dispositivo

**W1C Pro**: badge RFID 125 KHz + password (niente impronta né volto, nonostante
il protocollo le preveda), 3.000 utenti, **100.000 timbrature in memoria**,
Ethernet + WiFi, Linux a bordo.

**Funziona da solo.** Il riconoscimento del badge avviene sul terminale, contro
gli utenti che ha in pancia. Se la rete cade, o se il nostro server è spento, il
dipendente timbra lo stesso e il record resta in memoria: la rete serve solo a
*travasare*. È il terminale a mettere il timestamp, dal suo orologio interno —
quindi **l'orologio del terminale è il dato critico**: se sbaglia, sbagliano
tutte le timbrature, e non c'è modo di accorgersene a posteriori.

## Il protocollo

Documento ufficiale: `docs/tcb_protocol_2.5.pdf` — *ANVIZ TC_B Communication
Protocol User Manual*, v2.5, 96 pagine. Estratto in testo in `docs/`.

Richiesta:

    A5 | CH (4 byte, big-endian) | CMD (1) | LEN (2, BE) | DATA | CRC16 (2, little-endian)

Risposta:

    A5 | CH (4) | ACK = CMD+0x80 (1) | RET (1) | LEN (2, BE) | DATA | CRC16 (2)

- **CH = 0 funziona sempre**: la specifica dice *"All devices will response to
  following Commands, when CH is zero"*. Non serve conoscere il device code.
- **CRC16**: riflesso, poly `0x8408`, init `0xFFFF`, nessuno XOR finale, spedito
  little-endian (CRCL CRCH). È la tabella di RFC 1662.
- **Nessuna autenticazione, di nessun tipo.** Chi arriva alla porta 5010 legge
  tutto, scrive tutto, apre la porta. La password amministratore del terminale
  non protegge il protocollo. Vedi *Sicurezza* più sotto.

### Comandi implementati

| CMD  | Cosa fa | Note |
|------|---------|------|
| 0x30 | Configurazione 1 | non decodificato, esce grezzo |
| 0x38 | Legge data/ora | 6 byte: anno-2000, mese, giorno, ora, min, sec |
| 0x39 | Imposta data/ora | |
| 0x3A | Configurazione di rete | non decodificata |
| 0x3C | Conteggi | utenti, impronte, password, badge, timbrature totali, **nuove** |
| 0x40 | Scarica timbrature | a pagine di max 25 |
| 0x46 | Device ID | |
| 0x48 | Modello | 8 byte ASCII → `W1CPRO` |
| 0x4C | Elimina un utente | ID + maschera; 0xFF cancella tutto di lui |
| 0x4E | Azzera timbrature / flag "nuova" | |
| 0x5D | Capienza | 3.000 utenti, 100.000 timbrature |
| 0x5F | Timbrature in tempo reale | solo in uscita: è il terminale che spinge |
| 0x30 | Parametri del dispositivo | firmware, volume, sospensione, lingua, formato ora, stato predefinito |
| 0x31 | Scrive i parametri | `0xFF` = "non toccare questo campo" |
| 0x70 | Stati entrata/uscita | 16 slot; qui valgono `IN` e `OUT` |
| 0x71 | Riscrive le etichette degli stati | UTF-16, 10 caratteri per slot |
| 0x72 | Scarica utenti | **non 0x42**, vedi sotto |
| 0x73 | Scrive utenti | a gruppi di 8; risponde con una maschera di bit |
| 0x24 | Numero di serie | 16 byte ASCII |
| 0x7E | Ultima tessera passata sul lettore | la specifica lo dà "solo T5S": **risponde anche qui** |

### Gli utenti: la specifica indica i comandi sbagliati

Il manuale dice `0x42` per leggere gli utenti e `0x43` per scriverli. **Su
questo firmware vanno entrambi in timeout**, come pure il `0x22` citato come
variante. Funzionano invece `0x72` e `0x73`, la coppia "Extended".

E il record utente non è di 27 byte come da specifica, ma di **40**:

| byte | campo |
|------|-------|
| 0-4  | ID utente |
| 5-7  | PIN: nibble alto del 5 = quante cifre, i 20 bit restanti = valore (`FF FF FF` = nessuno) |
| 8-11 | tessera su **4** byte (`FF FF FF FF` = nessuna) |
| 12-31| nome in **UTF-16BE**, 10 caratteri |
| 32   | reparto |
| 33   | gruppo |
| 34   | come si identifica |
| 35-36| impronte iscritte (in scrittura vale sempre 0) |
| 37   | byte **alto** del PIN |
| 38   | riservato, significato ignoto |
| 39   | bit 7-6: 1 = utente normale, 3 = amministratore |

Il byte 38 è il motivo per cui **in scrittura si parte sempre dai byte letti** e
si sovrascrivono solo i campi che si vogliono cambiare: inventare un valore per
un campo ignoto significherebbe rovinare l'utente.

### Il PIN si scrive da qui, l'impronta no

Il PIN sta in tre posti (nibble alto del byte 5, i 20 bit successivi, e il byte
37 per le cifre in eccesso), e **si scrive da remoto senza toccare il
terminale** — contrariamente a quello che il progetto ha creduto per un giorno.
Verificato sul ferro: PIN `1234` sull'utente 902 → `40 04 d2`, e il contatore
`password` del dispositivo passa a 1.

Il numero di cifre viaggia separato dal valore, quindi **`0042` è un PIN diverso
da `42`** e gli zeri iniziali si conservano: provato sul terminale con l'utente
903, riletto `0042`. La codifica regge 28 bit, cioè otto cifre; oltre, si
rifiuta invece di troncare in silenzio.

Il PIN si riscrive **solo se lo si è davvero cambiato** (`imposta_password`
alza una bandierina). Senza quella guardia, cambiare il reparto a un dipendente
gli cancellerebbe la password, perché il record si riscrive tutto intero.

Le impronte restano l'unica cosa che va iscritta sul dispositivo: richiedono il
dito.

### La tessera la legge il terminale

`0x7E` restituisce l'ultima tessera passata sul lettore, `0` se non ce n'è
nessuna. La specifica lo dichiara "applicable to T5S only" — **sul W1C Pro
risponde lo stesso**. Serve a iscrivere un badge da remoto avvicinandolo al
lettore, invece di copiare a mano il numero stampato sopra (che spesso non
corrisponde a quello che il lettore vede).

Il dialogo `LetturaTessera` **butta via la prima lettura** e poi interroga ogni
400 ms per trenta secondi: il terminale conserva l'ultima tessera letta, che può
essere di ore prima, e senza quello svuotamento si iscriverebbe il badge di chi
è entrato per ultimo. Il collegamento resta aperto per tutta l'attesa, col
lucchetto in mano — aprire una connessione nuova ogni mezzo secondo
significherebbe litigare con lo scheduler.

Da verificare col badge in mano: se la tessera è già di qualcuno, il terminale
registra anche una timbratura (si annulla dalla schermata Timbrature); se non è
di nessuno, dovrebbe rifiutarla senza registrare nulla.

### Formato di una timbratura (14 byte)

| byte | campo |
|------|-------|
| 0-4  | user ID (5 byte, big-endian) |
| 5-8  | data/ora: secondi trascorsi da `2000-01-02 00:00` — vedi sotto |
| 9    | metodo — bit0 impronta1, bit1 impronta2, bit2 password, bit3 badge |
| 10   | tipo — bit7 = porta apribile; nibble basso = stato presenza (entrata/uscita/...) |
| 11-13| work code (3 byte) |

### L'epoca dell'orologio: la specifica ufficiale sbaglia

Il manuale Anviz dice due volte che i secondi si contano da `2000-01-01 00:00`.
**Non è vero.** Tarato sul dispositivo con una timbratura a un'ora nota:

    valore letto   0x32282c2e = 841.493.550 secondi
    con 2000-01-01 -> 2026-08-31 12:12:30   sbagliato di un giorno
    con 2000-01-02 -> 2026-09-01 12:12:30   corrisponde alla timbratura vera

Quindi l'epoca è il **2 gennaio 2000**, ed è quella predefinita nel codice. Chi
segue la specifica alla lettera si ritrova tutte le timbrature datate al giorno
prima — un errore particolarmente insidioso perché l'orario resta giusto e i
totali giornalieri sembrano plausibili: sbaglia solo la data. Un turno notturno
finirebbe attribuito al giorno sbagliato senza che nulla stoni.

C'è `--epoca-specifica` per tornare alla lettura del manuale, ma serve solo a
confrontare: non usarla.

### Scarico incrementale

Il terminale tiene un flag "nuova" per ogni timbratura. Il giro corretto è:

1. `0x3C` → quante nuove ci sono
2. `0x40` con parametro **2** (nuove) per la prima pagina, poi **0** (continua)
3. salvare su disco
4. **solo allora** `0x4E` tipo 2 con la quantità effettivamente salvata

Se il collettore muore fra il 3 e il 4, al giro dopo riscarica: meglio un
doppione (che il DB scarta per chiave primaria) che una timbratura persa.

## Uso

Nessuna dipendenza, solo Python 3.10+.

    python anviz.py cerca-udp                     # ricerca broadcast: modello, seriale, firmware
    python anviz.py cerca 192.168.1.0/24          # trova il terminale in LAN
    python anviz.py info 192.168.1.50             # modello, orologio, conteggi
    python anviz.py scarica 192.168.1.50 --csv timbrature.csv
    python anviz.py scarica 192.168.1.50 --nuove --conferma
    python anviz.py orologio 192.168.1.50 --imposta
    python anviz.py ascolta 192.168.1.50          # timbrature in tempo reale
    python anviz.py raw 192.168.1.50 30           # sonda un comando qualsiasi

Se il terminale è irraggiungibile perché è rimasto in DHCP su una rete che non
distribuisce indirizzi (cavo diretto, o ripristino di fabbrica), lo si ripesca
così — risponde **solo** al MAC indicato, quindi non può disturbare il router:

    python bootstrap_dhcp.py 00:22:ca:8c:0b:ff --offri 192.168.0.218 --da 192.168.0.10

## Come vengono archiviate

Le timbrature finiscono in `timbrature.db` (SQLite), tabella `raw_events`, coi
campi dell'evento normalizzato del par. 6.3 del documento: `source_event_id`,
`employee_code`, `occurred_at_local`, `occurred_at_utc`, `event_type`,
`work_code`, `device_serial`, `raw_payload`, `imported_at`.

Due proprietà che vale la pena garantire fin da qui:

- **Immutabile.** Si scrive solo in `INSERT OR IGNORE`, mai `UPDATE`. Le
  correzioni sono rettifiche tracciate, e vivono nel cruscotto, non qui.
- **Idempotente.** `source_event_id` è lo SHA-1 di dispositivo + i 14 byte
  originali: rileggere due volte lo stesso record non crea doppioni. Verificato
  dal collaudo.

`occurred_at_local` è l'ora che mostra il terminale, `occurred_at_utc` l'istante
normalizzato per ordinare. Nell'ora che si ripete al ritorno all'ora solare la
conversione è ambigua e si sceglie la prima occorrenza — ma l'ora locale grezza e
i byte originali restano archiviati, quindi la scelta è sempre rivedibile.

## Modalità di rete

Il terminale ha tre modi (`0x3A`, campo *Mode*):

- **0 Server** — il terminale ascolta sulla 5010, noi lo interroghiamo. È il modo
  che usa CrossChex Standard e quello per cui è scritto questo client.
- **1 Client** — è il terminale a chiamare *noi*. Utile se il collettore sta
  fuori dalla LAN: niente port forwarding.
- **2 Client + Server URL** — come sopra ma con URL configurabile (`0x0A`/`0x0B`).

## Il terminale in prova

Dati letti dal dispositivo, non dalla scatola (comando `cerca-udp`):

| | |
|---|---|
| Modello | `W1CPRO` |
| Seriale | `0690200024380174` |
| Firmware | `03.52.CT` |
| MAC | `00:22:ca:8c:0b:ff` |
| Device No. | 1 |

**Com'era di fabbrica:** DHCP **attivo**, orologio **non impostato** (segnava
l'anno 2251), modo rete Server sulla 5010, server IP `192.168.0.97` e URL
`www.anviz.com` residui, 1 utente con badge e 3 timbrature di collaudo di
fabbrica — timbrate con l'orologio sballato, quindi datate 2131 e da considerare
spazzatura (sono comunque archiviate, non buttate).

Il DHCP attivo su un cavo diretto è ciò che ha reso il terminale invisibile per
un'ora: chiedeva un indirizzo ogni 3 secondi e nessuno rispondeva. Da qui
`bootstrap_dhcp.py`.

## Stato del collaudo

**Verificato sul dispositivo vero** (1 set 2026):

- ✅ **Il W1C Pro parla TC_B sulla 5010.** Era l'incognita che reggeva tutto il
  progetto: risolta. Modello, device ID, orologio, conteggi, rete e timbrature
  si leggono tutti.
- ✅ Framing, CRC, paginazione e formato del record a 14 byte. La conferma più
  bella è il `backup code = 0x08` sui tre record, cioè "badge": l'unico utente
  iscritto ha una tessera e nessuna impronta. Se il parsing fosse disallineato
  di un byte, quel campo non tornerebbe.
- ✅ Orologio (`0x38`/`0x39`): 6 byte binari `anno-2000, mese, giorno, ora,
  minuto, secondo`. Verificato scrivendo e rileggendo.
- ✅ Configurazione di rete (`0x3A`), 27 byte: IP, maschera, MAC, gateway,
  server IP, permesso remoto, **porta su 2 byte big-endian** (`0x1392` = 5010),
  modo rete, flag DHCP.
- ✅ Ricerca via broadcast UDP (`0x02`), che restituisce anche seriale e
  firmware. **Ma solo se il terminale ha già un indirizzo IP**: senza IP non può
  spedire la risposta, quindi come strumento di primo ripescaggio non serve —
  per quello c'è `bootstrap_dhcp.py`.
- ✅ Percorso completo scarico → archivio → CSV, con deduplica.

- ✅ Cancellazione delle timbrature (`0x4E` tipo 0), previo scarico e archivio.

**Quello che il firmware NON lascia fare.** Il `03.52.CT` rifiuta
(`RET = 0x01`) qualunque riconfigurazione di rete da remoto:

- `0x3B` Set Network Configuration — rifiutato **anche riscrivendo byte per byte
  la configurazione identica a quella già attiva**. Quindi non è il contenuto a
  non piacergli: è il comando a essere sbarrato.
- `0x03` UDP Set Device Parameter — risposta ricevuta, ma sempre fallita, con
  tutte le combinazioni di credenziali previste dalla specifica (utente vuoto /
  `0` / `admin`, password vuota / `12345` / `0`).

È verosimilmente un irrigidimento voluto da Anviz: su un protocollo senza
autenticazione, poter cambiare l'indirizzo di un terminale da remoto era una
delle falle del 2019. **Conseguenza pratica: l'indirizzo fisso si imposta solo
dal menu del terminale**, oppure — meglio per l'installazione vera — con una
prenotazione DHCP sul router, come del resto prevede il par. 3.3 del documento.
Leggere la configurazione (`0x3A`) funziona benissimo.

**L'orologio: due difetti diversi, non uno.**

Il primo salto misurato — 79 secondi in 13 minuti — sembrava deriva, e non lo
era: fanno il 10% di errore, e nessun quarzo sbaglia così, nemmeno rotto. In
quella finestra il terminale si era **riavviato** (è quando ha perso l'indirizzo
DHCP), e al ritorno ha ripreso da un orario salvato prima. Cioè **allo
spegnimento perde il conto**: o l'RTC non è tamponato da batteria, o la batteria
è esaurita.

La deriva vera, misurata su 100 minuti di funzionamento continuo, è
**−27 secondi al giorno (312 ppm)**. Scarsa — un RTC decente sta sotto le
20 ppm — ma nell'ordine di grandezza di un oscillatore non compensato. Sono
comunque 13 minuti al mese, che su un cedolino si vedono.

Due rimedi, e conviene tenerli entrambi:

- il collettore **riallinea l'ora a ogni passaggio** (solo oltre la tolleranza, e
  sempre *prima* dello scarico, così i record letti restano coerenti con
  l'orologio che li ha timbrati);
- il terminale ha una **correzione della deriva** propria (`0x32` byte 15, ±60
  s/giorno) che lavora anche a computer spento.

Per non impostare la correzione a occhio, l'applicazione **misura la deriva da
sola**: registra lo scarto a ogni scarico e stima i secondi al giorno usando solo
gli intervalli in cui l'orologio è corso libero, saltando quelli in cui è stato
riallineato — altrimenti si scambierebbe il riallineamento per deriva.

- ✅ **Epoca dell'orologio tarata** con una timbratura a un'ora nota: è
  `2000-01-02`, non quella della specifica. Vedi sopra.
- ✅ Timbratura vera letta da capo a fondo: badge dell'utente 1 delle 12:12:30
  locali, `10:12:30Z`, payload grezzo conservato.

- ✅ **Anagrafica in scrittura**: creato, letto, rinominato, cambiato badge e
  cancellato un utente di prova sul dispositivo vero.
- ✅ Stati entrata/uscita, capienza, numero di serie.

**Entrata e uscita: risolto a metà.** Il terminale ha gli stati `IN` e `OUT`
definiti (`0x70`), quindi sa distinguerli — ma li registra solo se il dipendente
preme il tasto *prima* di passare il badge. Tutte le timbrature finora raccolte
hanno stato 0, cioè nessuno l'ha mai premuto. Quindi la scelta del par. 7.3 del
documento non è più "si può o non si può", ma:

1. si insegna al personale a premere il tasto (il terminale è già pronto);
2. si configura il cambio automatico per fasce orarie (`0x20`/`0x21`, oggi
   disattivato);
3. si deduce dall'alternanza a valle.

Il motore le supporta tutte e tre: in "automatico" usa gli stati quando ce ne
sono di diversi, altrimenti ripiega sull'alternanza, e scrive sempre a schermo
quale criterio ha applicato.

### Cosa si configura da qui, e cosa no

| | |
|---|---|
| Le nove regole del locale | tutte, e vivono solo qui: il terminale non le conosce |
| Anagrafica dipendenti | nome, tessera, reparto, gruppo, modo di identificazione, creazione ed eliminazione |
| **Permesso di amministratore** | no: il terminale rifiuta la scrittura da rete. Si legge, non si cambia |
| Orologio | lettura, scrittura, riallineamento automatico |
| Volume, sospensione, formato ora, stato predefinito | sì (`0x30`/`0x31`) |
| Etichette entrata/uscita a display | sì (`0x71`): si possono scrivere in italiano |
| Ignora badge ripetuto, correzione orologio, avviso memoria, tempo reale | sì (`0x32`/`0x33`) |
| Memoria timbrature | svuotabile, previo archivio |
| **Impronte e password** | no, e non è un limite nostro: richiedono il dito o la tastiera del dispositivo |
| **Indirizzo IP, maschera, DHCP** | no: il firmware rifiuta il comando |

### Il campo lingua non è decifrato

`0x30` restituisce **0**, che secondo la specifica sarebbe cinese semplificato,
ma il terminale è stato impostato in italiano — e l'italiano nella tabella della
specifica non esiste nemmeno. Del resto quella tabella elenca 0, 1, 3, 4, 5:
**manca il 2**, quindi era già incompleta nel 2019.

Conclusione: su questo firmware la corrispondenza numero → lingua è ignota.
L'interfaccia mostra il numero e basta, invece di scrivere a schermo un nome
sbagliato. Il comando per cambiarla c'è, ma va usato guardando lo schermo del
dispositivo e segnandosi il codice di partenza.

### Tre parametri di `0x32` che risolvono problemi reali

- **Ignora ripetute** (byte 12): a zero, com'è di fabbrica, il terminale
  registra anche il badge passato due volte di fila — ed è la ragione per cui
  vediamo doppioni. Alzandolo a uno o due minuti spariscono alla fonte, invece
  di doverli scartare a valle.
- **Correzione dell'orologio** (byte 15): compensa la deriva dell'RTC
  direttamente sul terminale, ±60 secondi al giorno. Utile se il computer non
  è sempre acceso a riallinearlo.
- **Tempo reale** (byte 5): di fabbrica è **spento**. È la risposta alla domanda
  se `0x5F` sia attivo: no, va acceso.

Restano aperti:

1. Cosa fa il terminale al cambio dell'ora legale.
2. Cosa succede quando la memoria delle 100.000 timbrature si riempie
   (sovrascrive le vecchie o smette di registrare?).
3. Se la password di comunicazione, una volta accesa, cambia qualcosa sul filo:
   il client oggi **non la gestisce**. Tenerla spenta finché non si prova.
4. Il significato dei due byte finali del record utente.
5. La corrispondenza numero → lingua.

## Come si consegna: una cartella, non un .exe

`python crea_pacchetto.py` prepara `pacchetto/TIMBRA/`: dentro c'è un Python
"incorporato" (la distribuzione ufficiale ridotta, presa da python.org) più i
sorgenti. Si copia la cartella **intera** sul computer del locale e si fa
doppio clic sul collegamento con l'icona. Non si installa niente, non si tocca
il resto della macchina. Circa 35 MB.

**Perché non un eseguibile.** Un exe di PyInstaller non firmato viene
**bloccato da Smart App Control**, acceso di serie sulle installazioni pulite
di Windows 11 — non l'avviso che si scavalca con «esegui comunque», proprio
bloccato (misurato: `VerifiedAndReputablePolicyState = 1` sulla macchina di
sviluppo). In più gli antivirus lo segnalano come falso positivo, perché la
tecnica di impacchettamento è la stessa dei malware. Il giorno che serve
davvero un file singolo la strada è il **certificato di firma** — Azure
Trusted Signing, ~10 $/mese con identità aziendale verificata — non un altro
impacchettatore.

**Il Python incorporato non ha Tkinter**: la distribuzione ridotta lascia
fuori tcl/tk, che vengono copiati dal Python installato sulla macchina che
prepara il pacchetto. Stessa versione, stessa architettura.

Il collegamento punta a `pythonw.exe`, non a `python.exe`: altrimenti a ogni
avvio resterebbe aperta anche una finestra nera di console, che prima o poi
qualcuno chiude credendo di chiudere una cosa inutile.

## Il PIN, e cosa non è

`12345` di fabbrica, cambiabile da Impostazioni. Chiude **Dipendenti**,
**Impostazioni** e le **rettifiche** — guardare le timbrature resta libero,
correggerle no, perché è lì che si toccano le ore che poi si pagano. Dato una
volta, resta aperto quindici minuti: chiederlo a ogni tocco è il modo migliore
per farlo scrivere sul monitor con un pennarello.

Sul disco finisce solo l'impronta (SHA-256 con sale per installazione), mai il
PIN. **Non è sicurezza informatica**: cinque cifre si provano tutte in un
secondo, e chi ha accesso al disco fa quello che vuole. Ferma il cameriere che
tocca il tablet mentre passa, ed è esattamente il problema che c'era.

**Il recupero è il numero di serie del terminale.** Si tiene premuto il
lucchetto per tre secondi e si digitano le ultime sei cifre stampate
sull'etichetta dietro il dispositivo; il PIN torna a quello di fabbrica. Non è
una porta di servizio universale — quella sarebbe identica su ogni
installazione e basterebbe che circolasse una volta. Qui serve avere in mano
*quel* terminale, cioè essere entrati nel locale. Se il seriale non è ancora
stato letto, il recupero si fa togliendo le due righe `pin_` da
`configurazione.json`.

## Il report mensile

`posta.py`. Il mese si racconta quando è finito: il report che arriva il giorno
*N* parla del mese precedente. Se il giorno scelto non esiste — il 31 a
febbraio — si arretra all'ultimo giorno che c'è, invece di saltare il mese come
farebbe un confronto ingenuo.

**Se il computer era spento, i mesi arretrati escono lo stesso**, uno per giro
dello scheduler, dal più vecchio. Saltarli sarebbe il guasto che nessuno nota
finché non serve. Alla prima configurazione si parte dal mese appena chiuso,
non da quando ha aperto il locale: nessuno vuole dodici mail insieme.

**Si segna «inviato» solo a spedizione avvenuta.** Se l'SMTP rifiuta, al giro
dopo ci riprova. E il controllo vive fuori dal blocco che parla col terminale:
un cavo di rete staccato non deve far smettere di arrivare le mail, che leggono
dall'archivio e del terminale non hanno bisogno.

**Il grafico dentro la mail è fatto di celle di tabella colorate, non di
un'immagine.** Un'immagine allegata i client la nascondono finché non premi
«mostra contenuti», e su iPhone quel bottone non lo preme nessuno; le tabelle
si vedono sempre, anche su Outlook che disegna le pagine col motore di Word.

L'ora di partenza è spostata di qualche minuto, sempre gli stessi per quel
mese: un messaggio che parte alle 08:00:00 spaccate tutti i mesi è un timbro da
automa, e i provider guardano anche quello. Deterministico apposta — se
ballasse, l'ora limite si sposterebbe a ogni controllo.

La password della casella sta in `configurazione.json` **offuscata, non
cifrata**: la chiave è dentro `sicurezza.py`, in chiaro. Ferma l'occhiata di
passaggio al file aperto sul monitor, non chi ha il sorgente. Meglio una
password per app o una casella dedicata.

## Una copia sola

Due istanze non romperebbero l'archivio — SQLite in WAL regge più scrittori —
ma farebbero **due scheduler che si contendono il terminale**, che di
conversazioni TCP ne regge una: a ogni giro una delle due andrebbe in timeout e
la barra di stato mostrerebbe guasti inventati. Alla partenza si prova a
prendere un mutex di sessione (`Local\GestionePresenzeAnviz`); se c'è già,
si ripesca la finestra aperta, la si porta davanti e si esce.

## Il grafico non inventa ore

Disegnato a mano su una tela Tk (`GraficoPresenze`). Una libreria di grafici
sarebbero megabyte di dipendenze per una manciata di rettangoli, e su un
registratore di cassa ogni dipendenza in più è un'installazione che può andare
storta.

**Un turno senza uscita significa due cose diverse a seconda del giorno.** Oggi
vuol dire che la persona è dentro adesso: la barra è gialla e cresce fino
all'ora corrente. Su un giorno già passato vuol dire che l'uscita non è mai
stata timbrata: la barra diventa un moncone rosso con scritto *manca l'uscita*.
Tirarla fino a stasera racconterebbe una giornata di sedici ore mai lavorata —
è il primo difetto che il grafico ha avuto, ed è in prova (`test_grafico.py`).

**Il totale a destra è quello del motore delle presenze, che i turni aperti non
li conta.** Chi è dentro adesso vedrebbe quindi `0:00` accanto a una barra
lunga cinque ore: per non farlo sembrare un errore, le ore in corso si scrivono
sotto in giallo come `+5:00`. Due numeri diversi perché misurano due cose
diverse, non perché uno sbagli.

**La finestra oraria è adattiva.** Un ristorante lavora dalle 11 a mezzanotte:
disegnare le ventiquattro ore vorrebbe dire sprecare metà figura per mostrare
che di notte non c'era nessuno. Il righello parte dalla prima entrata e arriva
all'ultima uscita, con un passo di 1-6 ore scelto in modo che le etichette non
si accavallino.

**Il giorno senza ore resta visibile come tacca**, nel calendario di settimana e
mese: un buco vuoto si confonderebbe con "il dipendente non c'era ancora".

## Giornata, settimana, anno: i numeri veri

Non stime: un anno di esercizio simulato e misurato. Ristorante da **14
dipendenti**, turno spezzato pranzo e cena, chiuso il lunedì.

| | |
|---|---|
| Al giorno | ~47 timbrature · 288 giri dello scheduler · **7 minuti di rete in tutto** |
| Alla settimana | ~283 timbrature |
| All'anno | 312 giorni aperti · **14.724 timbrature** · **4,7 MB** di archivio |

Tempi di calcolo su un archivio da un anno intero: le presenze di un giorno
**4 ms**, l'export mensile per le paghe **6 ms**, un anno intero ricalcolato da
zero **55 ms**. Non c'è nessun problema di scala all'orizzonte: dopo dieci anni
l'archivio starebbe sotto i 50 MB e il ricalcolo sotto il secondo.

La memoria del terminale — 100.000 timbrature — a questo ritmo si riempirebbe in
**quasi sette anni**, e comunque non ci arriva mai perché il collettore la svuota.

Una cosa che la misura ha fatto emergere: il registro tecnico degli scarichi
cresceva di **105.000 righe l'anno** e veniva riletto per intero ogni volta che
si apriva la schermata Impostazioni. Ora si tiene 120 giorni e la stima della
deriva guarda solo le ultime due settimane: da 131 ms a 13 ms.

## A prova di bomba: tre copie, non una

**1. Il terminale.** Le timbrature scaricate **non vengono cancellate** dal
dispositivo: il collettore azzera solo il contrassegno "nuova". Il W1C Pro tiene
quindi anni di storico per conto suo. Se il computer prendesse fuoco stanotte,
domani si ricollega un altro PC e si riscarica tutto.

**2. L'archivio vivo**, in WAL con `synchronous=FULL`: chi legge non blocca chi
scrive, e un commit è su disco prima di dirsi fatto.

**3. Le copie giornaliere**, in `copie/`, fatte in automatico dallo scheduler una
volta al giorno — nessun servizio da installare, se il programma gira la copia
si fa. Si tengono le ultime sette più la prima di ogni mese, che non si cancella
mai: è l'unica difesa contro un guasto che nessuno nota per settimane.

Tre dettagli che fanno la differenza fra una copia e una copia che serve:

- si usa l'**API di copia online di SQLite**, non `shutil.copy`: copiare un
  database mentre qualcuno ci scrive produce un file incoerente, e lo si scopre
  il giorno che serve;
- ogni copia viene **riaperta e verificata** subito con `integrity_check` e un
  conteggio delle timbrature;
- la copia nasce con un nome provvisorio e **prende il nome buono solo dopo aver
  passato la verifica**: se qualcosa va storto resta quella di ieri, invece di
  essere sostituita da un file rotto.

Sei prove automatiche coprono proprio questi casi, compresa una copia eseguita
mentre un altro thread sta scrivendo, e una copia sabotata di proposito per
controllare che non sovrascriva la buona.

## Dove gira

Requisiti reali, verificati e non dedotti:

| | |
|---|---|
| Python | **3.8+** (la sintassi passa anche a 3.7; nessun modulo fuori dalla libreria standard) |
| SQLite | **3.24+**, per l'UPSERT dell'anagrafica — è del 2018, ce l'ha qualunque Python recente |
| Tkinter | incluso in Python su Windows; su Linux e Raspberry è un pacchetto a parte (`python3-tk`) |
| Schermo | da **1024×600** in su: verificato a quella risoluzione, e sotto i 1024 px parte a pieno schermo |
| Architettura | x86, x86-64 e ARM: il codice è puro Python, l'architettura la vede solo l'interprete |

**Il fuso orario era una trappola.** Windows non porta con sé il database dei
fusi: `zoneinfo.ZoneInfo("Europe/Rome")` fallisce a meno che qualcuno non abbia
installato il pacchetto `tzdata`. Su una cassa con Python appena installato
l'applicazione non sarebbe partita affatto — e questo README dichiarava "nessuna
dipendenza esterna". C'è ora un ripiego calcolato a mano (regola europea: ultima
domenica di marzo, ultima domenica di ottobre, CET/CEST) che entra in funzione
solo se il database manca. Le due strade sono state confrontate **ora per ora su
sedici anni, 140.256 confronti, zero divergenze**, e la prova è permanente.

**Sull'eseguibile: PyInstaller non compila per un'altra architettura.** Il
pacchetto va costruito sulla macchina di destinazione, o su una identica. Un exe
fatto qui su x86-64 non gira su un ARM, e viceversa. Per un ristorante solo
conviene comunque installare Python e mettere un `.bat` nell'avvio automatico:
niente pacchetto, niente firma, niente SmartScreen.

**Quando NON gira:** se il registratore di cassa è un Android (molti POS di nuova
generazione lo sono), Python con Tkinter non è una strada. Lì servirebbe un
mini PC accanto, che costa cento euro ed è comunque la scelta migliore: legare
le presenze alla cassa significa che quando la cassa si pianta si fermano anche
quelle.

## L'audit del 1 settembre

Cinque revisori indipendenti sul codice, ciascuno su una dimensione diversa, e
ogni reperto passato a un verificatore col compito di **smontarlo**: senza un
input concreto che produce l'errore, il reperto cade. Venti reperti grezzi, otto
verificati, **cinque confermati e corretti**, tre smontati.

**1. Il byte dei permessi era quello sbagliato** (`anviz.py`). Nel record utente
esteso il campo "special info" è l'**ultimo** byte (39); il 37 è il byte alto
della password. Il codice usava il 37 per entrambe le cose. Conseguenze: il flag
amministratore letto da un byte che non lo contiene, e — peggio — **ogni
salvataggio riscriveva il byte alto della password del dipendente**.
L'errore era sopravvissuto perché l'unico utente disponibile aveva `0x40` in
entrambe le posizioni: un campione che non poteva distinguere le due ipotesi.
Corretto, e ora c'è una prova con record in cui i due byte divergono.

Scoperta collaterale: **il terminale rifiuta qualunque scrittura del permesso di
amministratore** — provate tre codifiche, rilegge sempre "utente normale".
L'interruttore nell'interfaccia è diventato una voce in sola lettura, perché un
comando che finge di funzionare è peggio di un comando che non c'è.

**2. L'ora legale spostava i turni notturni di un'ora** (`presenze.py`). Le
durate si calcolavano sottraendo ore locali ingenue. Nella notte di ottobre un
turno 22:00 → 04:00 dura sette ore e ne risultavano sei; a marzo ne dura cinque
e ne risultavano sei. Il campo `occurred_at_utc` esisteva già, con tanto di
docstring che diceva "serve per l'ora legale", e il motore non lo leggeva.
Corretto: il giorno operativo si decide sull'ora locale, le durate sull'istante.

**3. La pausa d'ufficio veniva scalata due volte** (`presenze.py`). A chi timbrava
l'uscita per il pranzo veniva tolta anche la pausa automatica, quindi **chi
timbrava con diligenza risultava pagato meno di chi non timbrava**. Ora si
garantisce il minimo: si toglie solo quanto manca alla pausa già presa.

**4. Un'eccezione nell'aggiornare una schermata rendeva l'applicazione sorda**
(`gestione.py`). Se `_svuota_coda` sollevava, il riarmo non avveniva più:
finestra aperta, barra di stato ferma, nessun errore visibile. Ora il riarmo sta
in un `finally` e ogni messaggio si lavora per conto suo.

**5. Un archivio occupato poteva uccidere lo scheduler per sempre**
(`gestione.py`). Il gestore d'errore di `_scarica` scriveva sul database; se
quella scrittura falliva, l'eccezione usciva da `run()` e il thread moriva. Da
quel momento la raccolta automatica non sarebbe più ripartita, in silenzio.

Il filo comune dei primi tre: **confondere "coerente con quello che vedo" con
"verificato"**. Due dati che tornano non provano un'ipotesi se tornerebbero
anche con l'ipotesi opposta.

## Tre trappole che ci sono costate tempo

Scritte qui perché non si ripetano.

**Il terminale regge una conversazione alla volta.** Se lo scheduler sta
scaricando e l'interfaccia gli chiede il seriale, una delle due va in timeout.
Tutti gli accessi passano da un unico lucchetto.

**`after()` chiamata da un thread di lavoro non esegue mai.** Tkinter non è
thread-safe: il callback viene registrato e resta lì. Non si vede nessun errore,
si vede solo un dato che non arriva — ed è il tipo di guasto che manda a caccia
di fantasmi. Tutto ciò che nasce in un thread torna al thread principale
passando dalla coda.

**Non inghiottire le eccezioni in silenzio.** Il seriale che restava a `?` era
un `except Exception: pass`. Ora il motivo del fallimento finisce a schermo.

## Le nove decisioni che mancano

Il software è pronto; queste no, e sono del titolare, non nostre. Si impostano
tutte dalla schermata Impostazioni:

giorno operativo · entrata/uscita o alternanza · tolleranza doppioni · pausa ·
arrotondamento **e la sua direzione** · soglia straordinario · chi può
correggere · turno spezzato · chiusura del mese

Una nota sull'arrotondamento: la direzione non è un dettaglio tecnico. "Su"
favorisce il dipendente, "giù" il datore di lavoro. Va decisa consapevolmente e
messa per iscritto.

## Sicurezza

Il protocollo non ha autenticazione né cifratura, ed è documentato pubblicamente
(CVE-2019-12388 e seguenti). Chiunque raggiunga la porta 5010 può scaricare
l'anagrafica, alterare l'orologio e aprire la porta.

Quindi: **il terminale non va mai esposto su internet**, nemmeno con port
forwarding (che è invece quello che suggerisce la documentazione Anviz per
collegare più sedi). Sta su una VLAN, e solo il collettore ci parla.

## Fonti

- [Scheda W1C Pro](https://www.anviz.com/product/w1cpro-time-attendance.html)
- [TC_B Communication Protocol v2.5](https://github.com/WhiteaglePT/node-anviz/blob/master/dev/tcb_communications_protocol2.5.pdf) (via node-anviz)
- [node-anviz](https://github.com/WhiteaglePT/node-anviz) — implementazione JS testata
- [coyotevz/anviz](https://github.com/coyotevz/anviz) — implementazione Python parziale
- [Anviz Pwn! (0x90.zone)](https://www.0x90.zone/multiple/reverse/2019/11/28/Anviz-pwn.html) — analisi di sicurezza
