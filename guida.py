#!/usr/bin/env python3
"""
Il manuale, scritto per chi userà il programma, non per chi lo ha scritto.

Sta qui e non in un PDF perché un PDF finisce in una cartella e nessuno lo
apre più: la guida deve essere dentro il programma, nella schermata in cui
serve, raggiungibile con un dito.

Regole di scrittura rispettate qui dentro:
  - parole normali, niente sigle: "il numero della tessera", non "card ID";
  - si spiega cosa fare, non come è fatto dentro;
  - dove una scelta ha conseguenze sui soldi o sui dati, lo si dice chiaro;
  - quando una cosa NON si può fare, lo si scrive, con il perché e con la
    strada alternativa. È la parte che fa perdere più tempo se manca.

Ogni capitolo è (titolo, [blocchi]). Un blocco è una stringa: se comincia con
"# " è un sottotitolo, se comincia con "- " è un punto elenco, altrimenti è un
paragrafo normale.
"""

CAPITOLI = [

("Come funziona, in due parole", [
 "Il terminale appeso al muro registra chi passa la tessera o digita il "
 "codice. Le timbrature restano dentro al terminale: ne tiene decine di "
 "migliaia, cioè anni di lavoro.",

 "Questo programma, finché è aperto, ogni pochi minuti chiede al terminale "
 "se ci sono timbrature nuove e se le porta a casa. Poi le trasforma in ore "
 "lavorate seguendo le regole del locale.",

 "# Se il computer è spento non si perde niente",
 "Le timbrature restano nel terminale e arrivano tutte insieme alla prima "
 "riaccensione. Anche il report mensile, se il giorno stabilito il computer "
 "era spento, parte appena si riaccende.",

 "# I dati stanno in tre posti",
 "- dentro al terminale, che non viene mai svuotato da solo",
 "- nell'archivio del computer",
 "- in una copia di sicurezza al giorno, controllata subito dopo averla fatta",
 "Perché tre copie si perdano insieme deve succedere qualcosa di molto brutto.",

 "# Le cinque schermate",
 "- Oggi: chi è al lavoro adesso",
 "- Presenze: le ore, giorno per giorno, settimana o mese",
 "- Timbrature: l'elenco grezzo, così come arriva dal terminale",
 "- Dipendenti: chi è iscritto sul terminale",
 "- Impostazioni: collegamento, regole, report, copie",
 "Il tasto F11 mette il programma a tutto schermo e lo toglie.",
]),

("Il giro di ogni giorno", [
 "Basta guardare due cose.",

 "# La striscia in fondo allo schermo",
 "Se il pallino è verde e c'è scritto l'orario dell'ultimo scarico, il "
 "terminale risponde e sta arrivando tutto. Se diventa rosso, il terminale "
 "non si raggiunge: le timbrature non si perdono, ma finché non torna il "
 "collegamento non le vedi qui.",

 "# La schermata Oggi",
 "Chi è dentro adesso è in verde, con l'ora in cui è entrato. Chi è già "
 "uscito è in grigio, con le ore fatte.",

 "Se sotto un nome compare una scritta gialla, quella giornata ha qualcosa "
 "che non torna: quasi sempre una timbratura dimenticata. Si sistema dalla "
 "schermata Presenze, aprendo il dettaglio di quella persona.",

 "# Conviene sistemare le anomalie giorno per giorno",
 "A fine mese nessuno si ricorda più se il 12 quella persona era davvero "
 "uscita alle tre o alle cinque. Fatto lo stesso giorno, ci si ricorda.",
]),

("Presenze: giorno, settimana, mese", [
 "In alto ci sono tre bottoni: Giorno, Settimana, Mese. Cambiano cosa "
 "guardi; le frecce ai lati si spostano di un giorno, di una settimana o di "
 "un mese, e il bottone «oggi» riporta a adesso.",

 "Anche il bottone per esportare segue quello che stai guardando: se sei sul "
 "mese scrive «Esporta il mese».",

 "# A giorno",
 "Una riga per persona, con l'orario di entrata e di uscita e le ore fatte. "
 "Il bottone «dettaglio» apre tutte le timbrature di quella persona in quel "
 "giorno, ed è da lì che si correggono.",

 "# A settimana e a mese",
 "La riga diventa il riassunto della persona: ore totali, giorni lavorati, "
 "media al giorno, straordinario, e quante cose ci sono da verificare.",

 "# Il grafico in fondo",
 "A giorno la barra va dall'entrata all'uscita, con le ore scritte sopra. "
 "Un turno spezzato diventa due barre con il buco della pausa in mezzo.",
 "- verde: turno chiuso, entrata e uscita ci sono tutte e due",
 "- giallo: la persona è al lavoro adesso",
 "- rosso: manca l'entrata o manca l'uscita, e allora si vede solo un "
 "trattino, perché quanto sia durato quel turno non lo sa nessuno",

 "A settimana e a mese c'è una colonna per giorno, alta quanto le ore fatte: "
 "in un colpo d'occhio si vede chi ha lavorato tanto e chi poco. Toccando "
 "una colonna si apre quel giorno.",

 "# Attenzione a un numero che sembra sbagliato",
 "Di chi è al lavoro in questo momento, le ore totali risultano zero: il "
 "conteggio parte quando la persona esce, perché prima non si sa quanto avrà "
 "lavorato. Le ore che sta facendo si leggono in giallo, sotto il totale, "
 "scritte con il più davanti.",
]),

("Quando qualcuno dimentica di timbrare", [
 "Succede. Il programma non lo nasconde: lo segnala in giallo e ti lascia "
 "sistemare, tenendo traccia di chi ha corretto e perché.",

 "# Come si fa",
 "- Presenze, ci si mette sul giorno giusto",
 "- si preme «dettaglio» sulla persona",
 "- «Aggiungi timbratura» per una che manca, «annulla» per una sbagliata",
 "- si sceglie l'ora, se è un'entrata o un'uscita, e si scrive il motivo",

 "Il motivo è obbligatorio. Senza, fra sei mesi nessuno sa più perché quel "
 "giorno è cambiato, e davanti a una contestazione è l'unica cosa che conta.",

 "# La timbratura originale non si cancella mai",
 "Annullare vuol dire «non contarla più». Il dato di partenza resta in "
 "archivio, e nella schermata Timbrature si vede sempre com'era.",

 "# Serve il codice",
 "Le correzioni cambiano le ore che poi si pagano, quindi il programma "
 "chiede il codice di sblocco. Guardare le timbrature invece è libero: chi "
 "vuole solo controllare non ha bisogno di niente.",
]),

("I dipendenti", [
 "La schermata Dipendenti mostra chi è iscritto nel terminale. Aggiungere o "
 "modificare qui scrive davvero dentro al dispositivo: non è un elenco a "
 "parte.",

 "# Un dipendente nuovo",
 "Si preme «Nuovo», si scrive il nome, e si sceglie come farlo identificare.",

 "# La tessera si fa leggere al terminale",
 "Alla riga «Tessera» si preme «cambia» e poi «Leggila dal terminale»: "
 "compare un conto alla rovescia, si appoggia il badge al lettore e il "
 "numero arriva da solo. È la strada giusta, perché il numero stampato sul "
 "badge spesso non è quello che il lettore vede davvero.",
 "Si può anche scrivere il numero a mano, o togliere la tessera.",

 "# Il codice personale",
 "Alla riga «PIN / password» si mette il numero che la persona digiterà sul "
 "tastierino del terminale. Solo cifre, al massimo otto. Attenzione: 0042 e "
 "42 sono due codici diversi, gli zeri davanti contano.",

 "Se la persona ha solo il codice e nessuna tessera, il programma propone di "
 "metterla su «solo password», altrimenti il terminale continuerebbe a "
 "chiederle il badge.",

 "# Quello che da qui non si può fare",
 "- Le impronte digitali vanno registrate sul terminale, con il dito della "
 "persona davanti al lettore. Non c'è modo di farlo da qui.",
 "- Rendere qualcuno amministratore del terminale: il dispositivo rifiuta il "
 "comando da rete. Si fa dal menu del terminale.",

 "# Cancellare un dipendente",
 "Lo toglie dal terminale insieme a tessera e impronte. Le sue timbrature "
 "già registrate restano in archivio: la storia non si perde, e il mese si "
 "chiude lo stesso.",
]),

("Il report mensile per email", [
 "Una volta al mese arriva una mail con le ore del mese appena chiuso: il "
 "riepilogo per persona nel testo, il mese giorno per giorno in figura, e in "
 "allegato il foglio da aprire con Excel.",

 "# Come si prepara",
 "Impostazioni, sezione «Report mensile via email».",
 "- «Casella di posta»: si sceglie il fornitore e server, porta e sicurezza "
 "si riempiono da soli",
 "- «Utente» e «Password»: quelle della casella che spedisce",
 "- «Mittente»: l'indirizzo da cui parte",
 "- «Destinatario»: chi lo riceve. Può essere lo stesso indirizzo. Se ne "
 "vuoi più d'uno, si separano con una virgola",
 "- «Giorno di arrivo» e «Ora»",

 "Alla fine si accende l'interruttore in cima alla sezione. Finché mancano "
 "server, mittente o destinatario, l'interruttore si rifiuta di accendersi.",

 "# Provalo subito, non aspettare il primo del mese",
 "«Manda una prova adesso» dice in pochi secondi se le credenziali vanno. "
 "«Manda adesso il report del mese scorso» fa vedere com'è fatta davvero la "
 "mail. Questo invio a mano non consuma quello automatico: il report del "
 "mese arriverà lo stesso al giorno stabilito.",

 "# Con Gmail e con Outlook serve una password apposta",
 "Quelle caselle non accettano più la password normale da un programma. "
 "Bisogna generare una «password per le app» dalle impostazioni di sicurezza "
 "dell'account, e mettere quella qui.",

 "# Quale mese racconta",
 "Sempre quello appena chiuso: il report che arriva il 5 settembre parla di "
 "agosto. Se il giorno scelto non esiste — il 31 a febbraio — arriva "
 "l'ultimo giorno che c'è.",

 "# Se non arriva",
 "Guarda nella posta indesiderata. Poi controlla la striscia in fondo alla "
 "schermata: quando un invio fallisce, lì compare il motivo. Il programma "
 "riprova da solo al giro dopo, e non segna il mese come spedito finché la "
 "mail non è partita davvero.",
]),

("Il codice di sblocco", [
 "Di fabbrica è 12345. Serve per entrare in Dipendenti e in Impostazioni, e "
 "per correggere una timbratura.",

 "Una volta digitato resta valido un quarto d'ora, poi si richiude da solo. "
 "In Impostazioni c'è «Richiudi adesso» per chiuderlo subito, per esempio "
 "prima di lasciare il locale.",

 "# Cambiarlo",
 "Impostazioni, sezione «Sicurezza», voce «PIN delle sezioni protette». "
 "Chiede prima quello vecchio, poi il nuovo due volte. Da quattro a otto "
 "cifre.",

 "# Se lo dimentichi",
 "Nella finestra che chiede il codice, tieni premuto il lucchetto in alto "
 "per tre secondi. Compare la richiesta di un codice di recupero: sono le "
 "ultime sei cifre del numero di serie stampato sull'etichetta dietro al "
 "terminale. Il codice torna a 12345.",
 "Serve avere in mano quel terminale, cioè essere entrati nel locale: non è "
 "una chiave che vale su tutte le installazioni.",

 "# Cosa questo codice non è",
 "Non è una protezione contro chi ha accesso al computer: cinque cifre si "
 "provano tutte in poco tempo. Serve a evitare che qualcuno tocchi per "
 "sbaglio o per curiosità le parti che contano, mentre passa davanti allo "
 "schermo.",
]),

("Le regole con cui si contano le ore", [
 "Stanno in Impostazioni, sezione «Regole del locale». Vanno decise dal "
 "titolare, non lasciate come capita: cambiano le ore che si pagano.",

 "# La giornata comincia alle",
 "Una timbratura prima di quest'ora conta sul giorno precedente. È quello "
 "che tiene insieme i turni che finiscono dopo mezzanotte: chi esce all'una "
 "resta nella giornata di ieri, dove è entrato.",

 "# Entrata e uscita",
 "Il terminale saprebbe distinguerle, ma solo se il dipendente preme il "
 "tasto giusto prima di passare la tessera — e non lo fa quasi nessuno. Con "
 "«automatico» il programma usa il tasto quando c'è, altrimenti alterna: "
 "prima entrata, poi uscita, poi entrata.",

 "# Doppioni",
 "Due passate ravvicinate della stessa persona contano per una. Meglio "
 "ancora: si può dire al terminale stesso di ignorare le ripetute, così i "
 "doppioni non nascono proprio (sezione «Parametri del dispositivo»).",

 "# Arrotondamento",
 "«Su» favorisce il dipendente, «giù» il datore di lavoro, «vicino» "
 "arrotonda al più vicino. Non è un dettaglio tecnico: è una decisione, e "
 "conviene che sia scritta anche altrove, non solo qui dentro.",

 "# Pausa tolta d'ufficio",
 "Toglie un tot di minuti a chi supera un certo numero di ore. Se la persona "
 "ha già timbrato l'uscita e il rientro per la pausa, quei minuti non "
 "vengono tolti due volte.",

 "# Straordinario oltre",
 "Le ore oltre questa soglia finiscono in una colonna a parte, nel foglio "
 "esportato e nel report.",
]),

("Le copie di sicurezza", [
 "Una copia al giorno, in automatico, mentre il programma è aperto. Subito "
 "dopo averla fatta viene riaperta e controllata: se non passa il controllo "
 "viene buttata e quella buona di prima resta al suo posto.",

 "Si tengono le ultime sette, più la prima copia di ogni mese. Stanno in una "
 "cartella «copie» accanto all'archivio; il percorso esatto è scritto in "
 "Impostazioni.",

 "«Fai una copia adesso» ne fa una fuori turno, per esempio prima di una "
 "modifica grossa.",

 "# Se il computer muore",
 "Le timbrature sono ancora dentro al terminale, che non viene mai svuotato. "
 "Si reinstalla il programma su un'altra macchina, gli si dice l'indirizzo "
 "del terminale, e le riprende.",
]),

("Se qualcosa non va", [
 "# Il pallino in fondo è rosso",
 "Il terminale non risponde. Nell'ordine: controlla che sia acceso, che il "
 "cavo di rete sia attaccato da tutte e due le parti, e che l'indirizzo "
 "scritto in Impostazioni sia quello giusto. In Manutenzione c'è «Cerca il "
 "terminale in rete», che lo ripesca se ha cambiato indirizzo.",
 "Nel frattempo non si perde niente: le timbrature restano nel dispositivo.",

 "# Gli orari sono sbagliati di qualche minuto",
 "L'ora la mette il terminale col suo orologio, che va un po' indietro da "
 "solo. Il programma lo rimette a posto a ogni collegamento. Se il computer "
 "resta spento a lungo, in «Parametri del dispositivo» c'è una correzione "
 "che il terminale applica per conto suo.",
 "Se gli orari fossero sbagliati di ore, e non di minuti, guarda «Formato "
 "dell'ora» e chiama chi ha installato il programma.",

 "# Il programma non si apre",
 "Probabilmente è già aperto: era una finestra sola per scelta, e la seconda "
 "volta che lo lanci ti riporta davanti quella che c'è già. Guarda nella "
 "barra delle applicazioni.",

 "# Una persona non compare nelle presenze",
 "Controlla in Dipendenti che sia iscritta e che abbia una tessera o un "
 "codice. Poi guarda in Timbrature se le sue passate arrivano: se ci sono "
 "lì ma non nelle presenze, è una questione di regole, non di collegamento.",

 "# Il mese esportato non si apre bene in Excel",
 "Il file è già preparato per Excel italiano. Se le colonne finiscono tutte "
 "in una, aprilo da Excel con «Dati, da testo», scegliendo il punto e "
 "virgola come separatore.",
]),
]
