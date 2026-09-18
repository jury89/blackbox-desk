# Verifica della versione 0.3.4

L'app si presenta come **Betaflight Blackbox Desk**, per indicare subito che gestisce i log Blackbox delle FC Betaflight. La chiusura distrugge la finestra Qt e i relativi osservatori locali, così una successiva apertura riparte senza modelli del filesystem residui.

Data: 18 settembre 2026. Host: Mac Intel x86_64, Python 3.14.6, PySide6 6.11.2.

- **123 test superati:** protocollo MSP simulato, FC di produttori diversi, transizione a volume USB, rifiuto di dischi ambigui o estranei, filesystem Blackbox, estrazione oltre 100 voli flash, integrità delle copie, collisioni dei nomi, visibilità nel Finder, sblocco, annullamento, cancellazione confermata, svuotamento completo, cambio di volume, espulsione, navigazione e selezione locale, creazione cartelle e Cestino, elenco rapido e date differite, filtro e ordinamento dei log locali, drag in una sola direzione e interfaccia Qt.
- I test usano risposte simulate e file temporanei. Nessun log reale è stato eliminato.
- Build PyInstaller completata per Mac Intel; avvio del pacchetto verificato in modalità offscreen e con finestra macOS nativa.
- `codesign --verify --deep --strict` completato senza errori. Si tratta di firma locale ad hoc, non di un certificato Apple per distribuzione o notarizzazione.
- Anteprima dell'interfaccia con dati dimostrativi verificata visivamente.
- Pacchetto circa 30 MB compresso, circa 80 MB estratto. Richiede macOS 14+ per l'interprete incorporato.

## Da collaudare con hardware

1. Nuovo ciclo completo a freddo con la SpeedyBee F7 V3: confronto del montaggio, copia dell'ultimo log, controllo dell'apertura in Blackbox Explorer, espulsione. Il 18 settembre sono stati verificati collegamento ed elenco reale dei 17 log, come descritto sotto.
2. Ripetizione con una FC FLASH e una SDCARD di un altro produttore.
3. Eliminazione soltanto di un log che l'utente abbia scelto esplicitamente e già salvato; verificare l'elenco dopo un nuovo collegamento.
4. Build e prova su Windows. I test degli adattatori Windows eseguiti sul Mac verificano i contratti delle risposte e non il comportamento reale di Windows.

Il download del precedente script sulla SpeedyBee F7 V3 è evidenza utile sul dispositivo, ma non viene presentato come collaudo hardware di questa nuova applicazione.

## Correzione 0.1.1: file invisibile nel Finder

Riscontro reale: `Documents/Blackbox/btfl_001.bbl` era presente (8.388.608 byte), con il flag macOS `UF_HIDDEN`. Il file è stato reso visibile senza modificarne i dati. SHA-256: `4e566d53820b86e9429c9c465ae6c1e065c16a582c9271d55ddc5c184e722a0d`.

Due test aggiunti riproducono il problema prima della correzione: riutilizzo di un log locale nascosto e flag nascosto sull'inode condiviso col temporaneo durante la pubblicazione. Il controllo finale avviene dopo la rimozione del temporaneo. Il confronto attuale con il log sulla FC non è stato possibile, perché il volume non era disponibile durante la verifica.

## Svuotamento completo 0.2.0

- 20 test aggiunti: conferma obbligatoria, default Annulla e chiusura della finestra di conferma, UID diverso, memoria diversa, FC armata, capacità cambiata, cancellazione prima dell'invio, attesa di pronto+0 byte, timeout, perdita di collegamento senza retry dell'erase, monitoraggio non annullabile dopo l'invio, dati MSP invalidi.
- SDCARD: svuotamento di log validi, vuoti e incompleti in cartelle temporanee, conservazione di file estranei, rifiuto di elenco/volume cambiati, report di cancellazione parziale, aggiornamento dell'interfaccia.
- FLASH vuota dopo erase: elenco vuoto valido quando il file complessivo ha dimensione zero.
- Nessun erase è stato inviato a una FC reale. Il collaudo hardware resta da eseguire volontariamente dall'utente, con log già copiati.
- Fonti: [comandi e formato MSP](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/msp/msp.c), [blackboxEraseAll](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/blackbox/blackbox_io.c), [flashfsEraseCompletely](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/io/flashfs.c).

## Due pannelli e trascinamento 0.3.0

13 prove aggiunte: elenco locale con cartelle e tipi di file diversi; navigazione con doppio clic, Indietro, Su e percorso scritto; cartella inesistente; copia multipla con drop; drop su sottocartella; blocco della direzione inversa e dei file esterni; solo CopyAction e nessun URL esterno nel drag; rifiuto di sessioni obsolete e payload invalidi; blocco delle destinazioni nella FC anche tramite symlink; rifiuto di un drag che consente solo MoveAction; destinazione bloccata durante il trasferimento; creazione della destinazione iniziale mancante; espulsione automatica dopo un drop.

I test eseguono i gestori di drag/drop dei widget e la copia reale di file temporanei tramite il backend. Il trasferimento tramite mouse con una FC reale resta da collaudare. L'anteprima grafica usa esclusivamente FC e cartella del computer dimostrative.

## Cartelle prima dei log 0.3.1

Il test dell'elenco locale ora verifica cartelle prima dei log `.bbl` e `.bfl`, estensioni maiuscole e miste, esclusione di documenti e archivi e conteggio dei soli elementi visibili. Due prove aggiunte verificano ordinamento per nome, dimensione e data in entrambe le direzioni, corrispondenza fra cartella mostrata e destinazione del drop, e aggiornamento automatico quando un file viene rinominato da documento a log e viceversa. Navigazione e copie tramite trascinamento restano coperte dall'intera suite.

## Selezione e gestione locale 0.3.2

16 prove aggiunte: clic singolo e multiplo con evidenziazione grafica anche senza focus; creazione e selezione della nuova cartella; nomi invalidi, conflitti, percorsi inesistenti e FC protetta; conferma con default Annulla e avviso per tutto il contenuto delle cartelle; cestino di file e cartelle non vuote; rifiuto di selezioni esterne, cambiate e della cartella padre sostituita; nessuna eliminazione definitiva se il Cestino fallisce; conteggio delle operazioni parziali e annullamento; link passati senza risoluzione; aggiornamento della lista e blocco dei comandi durante trasferimenti.

Prova aggiuntiva su macOS nativo: clic su una cartella e screenshot con selezione evidenziata, più Cestino reale per un file, una cartella non vuota e un link, tutti creati temporaneamente per il test e subito ripristinati. Il contenuto e la destinazione del link sono rimasti intatti. Nessun file dell'utente è stato cestinato. Il Cestino Windows rimane da collaudare fisicamente.

## Caricamento progressivo 0.3.3

8 test aggiunti: 17 log elencati senza aprire i file; annullamento delle date prima del secondo log; cache solo per file invariati; errore di una data senza perdere altri log; lettura MSP limitata ai byte disponibili; righe e copia disponibili mentre le date sono ancora in attesa; copia prioritaria ed espulsione dopo annullamento dei metadati; selezione preservata e risultati di una sessione obsoleta ignorati.

Misura hardware del 18 settembre, SpeedyBee F7 V3, firmware 26.6.1, volume CHIMERA7 da 503.316.480 byte, 17 log SDCARD:

- Versione 0.3.2: identificazione terminata a 1,16 s; sole letture delle date pari a **31,134 s**, con molti file a circa 2,05 s ciascuno. Il totale è stato 173,56 s perché si è verificata anche un'attesa anomala nell'apertura della cartella: lo stack del processo era in `opendir`/`open`, prima delle intestazioni. Non si attribuiscono tutti questi secondi alla lettura delle date.
- Nuovo codice sul volume già montato: **0,148 s** fino all'elenco dei 17 log, inclusi 0,136 s di verifica del disco e 0,012 s di elenco; tutte le date differite. La misura è a caldo e non costituisce un confronto del tempo totale dal collegamento USB a freddo.
- Nessun log della FC è stato copiato, cancellato o modificato durante la misura. È stato usato il normale riavvio Betaflight in modalità disco USB; non sono state modificate impostazioni di volo.

## Espulsione senza rimontaggio 0.3.4

Prova reale del 18 settembre 2026 sulla SpeedyBee F7 V3 / Betaflight 26.6.1, volume CHIMERA7:

- Problema riprodotto con il vecchio comando: `diskutil eject` terminato con successo dopo circa 8 s; dispositivo riapparso a 9,09 s e volume nuovamente montato a 10,17 s, senza scollegare USB.
- `diskutil unmountDisk` sullo stesso disco, dopo verifica dell'identità, ha lasciato il volume smontato per tutti i 45 controlli successivi (circa 51 s dopo il completamento). Nessun blocco di automount o processo residente.
- Dopo lo scollegamento e ricollegamento fisico confermato dall'utente, la FC è tornata disponibile sulla porta seriale. Il backend 0.3.4 ha riconosciuto la stessa scheda, riaperto MSC e ritrovato 17 log; questo ciclo fino all'elenco ha richiesto 5,79 s.
- Espulsione dal backend aggiornato completata in 8,24 s. Quindici ricerche successive, ciascuna con una nuova istanza di backend, non hanno trovato la memoria montata (osservazione per circa 31 s dopo il completamento). Non si tratta soltanto di nascondere la FC nell'interfaccia.
- Quattro test aggiunti verificano rifiuto di identità cambiata, annullamento durante la validazione, esclusione del volume smontato e riconoscimento della stessa FC dopo il nuovo montaggio. Il test del comando verifica `unmountDisk` sul disco padre validato, senza `force` né `eject`; rimangono i controlli di errori e memoria ancora montata.
- Nessun log reale copiato, eliminato o modificato durante queste prove. Lo stesso adattatore è usato dall'espulsione manuale, automatica e prima del reset FLASH. Il reset FLASH e Windows restano coperti da test simulati, senza nuova prova hardware.

La memoria può restare visibile in Utility Disco come dispositivo fisico non montato. L'app non impedisce un montaggio manuale e non installa regole persistenti. Il comportamento del nuovo smontaggio su altre FC richiede prove con quelle schede. Il comando e il suo comportamento sono documentati nel manuale macOS locale `man diskutil`, sezioni `unmountDisk` ed `eject`.
