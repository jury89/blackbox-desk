# Betaflight Blackbox Desk 0.3.4

Applicazione desktop per vedere, copiare e gestire i log Blackbox delle flight controller **Betaflight** con **USB Mass Storage**. Interfaccia in italiano. Funziona interamente in locale, senza account o servizi in background.

Due pannelli affiancati: **FC a sinistra, computer a destra**. Puoi navigare nella cartella locale e trascinare uno o più log dalla FC al computer. Nel pannello Computer le cartelle restano in cima, seguite soltanto dai log Blackbox. L'elenco della FC compare prima delle date, completate in background. La versione 0.3.4 corregge il rimontaggio immediato dopo l'espulsione su Mac. Rimangono gestione locale, copia verificata, sblocco delle copie, cancellazione dalla FC e svuotamento della memoria.

## Stato di questa prima versione

- **Mac Intel:** applicazione `.app` autonoma; non richiede Python o Terminale per l'uso.
- **Windows x64:** stesso codice dell'interfaccia e della gestione file; adattatori Windows inclusi. Build `.exe` e prova fisica da eseguire su Windows. Non è una versione Windows già collaudata.
- **FC:** riconoscimento Betaflight generico, nessuna lista che limita il produttore. Richiede protocollo MSP 1.44+ (Betaflight 4.3+) e modalità disco USB funzionante. Il motore di trasferimento precedente è stato provato sulla SpeedyBee F7 V3 / 2026.6.1; l'app nuova e altre schede richiedono prove con hardware collegato.

## Uso

1. Avvia **Betaflight Blackbox Desk**. Collega una FC disarmata con un cavo USB dati e chiudi la sua connessione nel Configurator.
2. Premi **Cerca**, scegli il dispositivo e **Connetti**. La FC viene riconosciuta, poi riavviata in modalità memoria USB. Se è già un disco USB, puoi selezionarlo direttamente.
3. Il pannello sinistro mostra subito nomi e dimensioni, dal numero di log più alto. L'ultimo è selezionato. Le date inizialmente mostrate con `…` vengono lette in background: puoi già copiare o espellere. Usa clic, Maiusc e Cmd/Ctrl per selezionarne più di uno, oppure Tutti/Nessuno. La data compare soltanto se presente nell'intestazione del log; non viene dedotta dal filesystem.
4. Nel pannello **Computer** scegli la cartella di destinazione. Puoi entrare nelle sottocartelle con doppio clic, usare Indietro/Su o scrivere un percorso e premere Invio. Le cartelle sono sempre in cima, seguite solo dai file `.bbl` e `.bfl`, anche con estensione maiuscola o mista. Il contenuto si aggiorna automaticamente.
5. Trascina i log selezionati nel pannello Computer, oppure direttamente sopra una sua sottocartella. Sono disponibili anche **Copia ultimo** e **Copia selezionati**. Vengono conservati il nome originale e i dati; un conflitto diverso produce `_2`, `_3`, ecc. Copie identiche sono riutilizzate. Ogni copia è verificata con SHA-256, sbloccata e resa visibile e scrivibile.
6. **Espelli FC dopo la copia** è attivo per impostazione iniziale e vale anche per il trascinamento. Disattivalo se vuoi continuare a gestire i file; usa poi **Espelli FC**. L'espulsione riuscita viene confermata. Se fallisce, i log già copiati restano sul computer e l'app segnala il problema.
7. Per eliminare log, selezionali e premi **Elimina selezionati**. Una finestra elenca i file e richiede conferma; l'azione è definitiva.

Non vengono cancellati log automaticamente dopo la copia. Non vengono modificati PID, impostazioni di volo o firmware.

Il drag è esclusivamente **FC → computer** e rappresenta sempre una copia. Il pannello FC non accetta file; quello del computer non avvia trascinamenti. I drop da Finder/Explorer o altre app sono ignorati. Durante una copia la destinazione rimane fissa e una seconda operazione non può sovrapporsi. Rilasciare su una sottocartella la apre come nuova destinazione.

Il pannello locale mostra le cartelle e i log Blackbox visibili; gli altri tipi di file sono esclusi dall'elenco e dal conteggio. Le cartelle precedono sempre i log anche ordinando per dimensione o data, in entrambe le direzioni. **Apri nel Finder / Apri cartella** apre la cartella con il gestore file del sistema, dove sono visibili anche gli altri tipi di file. Il divisore fra i due pannelli è regolabile.

## Espulsione e nuovo collegamento

Su macOS **Espelli FC** smonta in modo sicuro tutti i volumi del disco USB selezionato (`diskutil unmountDisk`, senza forzare), dopo averne verificato l'identità. Sulla SpeedyBee F7 V3 il precedente `diskutil eject` faceva ricomparire e rimontare il disco dopo circa due secondi. Lasciando il dispositivo USB collegato ma i volumi smontati si evita questo ciclo; la memoria scompare dal Finder e dall'elenco delle FC disponibili. La stessa procedura vale dopo la copia, alla chiusura e prima del reset FLASH.

Per usarla di nuovo, **scollega e ricollega fisicamente USB**, poi premi **Cerca** e **Connetti**. Non vengono salvati blocchi per nome o UUID né modificate le impostazioni di montaggio di macOS: la stessa FC resta utilizzabile al nuovo collegamento. Non serve tenere l'app aperta dopo l'espulsione. Il disco fisico può ancora comparire in Utility Disco come non montato; un montaggio manuale da Utility Disco resta possibile. Se lo smontaggio fallisce perché un programma usa la memoria, l'app segnala l'errore e non forza la rimozione. Windows mantiene la propria rimozione nativa, da collaudare su hardware Windows.

## Gestire file e cartelle sul computer

- Un clic seleziona l'intera riga, evidenziata in azzurro anche quando il focus passa a un altro controllo; Cmd/Ctrl e Maiusc permettono la selezione multipla. Il doppio clic su una cartella la apre.
- **Nuova cartella…** crea una sottocartella nella cartella corrente e la seleziona. Il nome deve essere un solo nome valido: percorsi e conflitti vengono rifiutati, senza sovrascrivere elementi esistenti.
- **Elimina…** riguarda soltanto la selezione nel pannello Computer. La conferma mostra percorso e nomi, con **Annulla** come scelta iniziale. Confermando **Sposta nel Cestino**, le cartelle vengono cestinate con tutto il contenuto, inclusi i file non mostrati dal filtro Blackbox. È possibile recuperarle dal Cestino del sistema finché non viene svuotato.
- Il Cestino usa l'API nativa tramite `QFile.moveToTrash`. Se fallisce, viene mostrato un errore e non viene tentata un'eliminazione definitiva. Le operazioni multiple possono essere parziali: il messaggio indica quanti elementi sono già stati spostati.
- I comandi locali sono bloccati durante copie e altre operazioni. La selezione viene verificata nuovamente dopo la conferma e non può includere la FC aperta o sue cartelle. I link vengono cestinati come link, senza cancellarne la destinazione. Non sono disponibili rinomina o spostamenti locali fra cartelle.

## Tempi di collegamento

L'apertura ha fasi diverse: identificazione seriale, riavvio in memoria USB, montaggio da parte del sistema operativo ed elenco dei file. **Informazioni** riporta i tempi misurati nell'ultimo collegamento, separando queste fasi. Il tempo mostrato quando l'elenco è pronto esclude la successiva lettura delle date.

Per SDCARD e file FLASH individuali, l'elenco iniziale legge solo nomi e metadati del filesystem, senza aprire tutti i log. Le date vengono completate usando lo stesso worker delle operazioni USB; una copia, un'espulsione o un altro comando interrompe questa lettura dopo il file già in corso. Non vengono eseguite letture parallele sulla FC. Aggiornando l'elenco si riutilizzano soltanto le date di file con percorso, dimensione, data di modifica e offset invariati. La scansione del file complessivo per FLASH oltre 100 voli resta necessaria per individuare i voli.

Prova del 18 settembre 2026: la SpeedyBee F7 V3 con 17 log ha impiegato 31,13 s per le sole letture delle intestazioni nella versione precedente. Il nuovo elenco sullo stesso volume già montato ha richiesto 0,148 s, di cui 0,012 s per l'elenco. Quest'ultimo dato non include riavvio e montaggio iniziale, né garantisce lo stesso tempo al primo accesso a freddo. La prova precedente aveva incontrato anche una lunga attesa del sistema operativo aprendo la cartella: non tutti i ritardi dipendono dall'app.

## Cancellazione: limite reale della memoria

| Memoria esposta da Betaflight | Elenco e copia | Eliminazione individuale | Svuotamento |
| --- | --- | --- | --- |
| SDCARD su volume scrivibile, incluse memorie integrate come quella della SpeedyBee F7 V3 | Sì | Sì, dopo conferma | Tutti i file di log, dopo conferma |
| FLASH esposta come filesystem virtuale | Sì | No | Erase completo tramite connessione USB normale |
| SDCARD di sola lettura | Sì | No | Non disponibile |

L'eliminazione singola richiede file di log validi. **Svuota memoria…** su SDCARD include anche log vuoti o incompleti; elimina soltanto `LOG*.BFL` numerati, nella radice o nella cartella `LOGS`, senza usare il cestino. Eventuali altri file, inclusi file già nel cestino del sistema, rimangono sulla memoria: non è una formattazione del volume.

## Svuotare la memoria Blackbox

**SDCARD scrivibile:** con la memoria aperta premi **Svuota memoria…** sotto l'elenco della FC. La conferma mostra volume, percorso, numero e dimensione totale di tutti i log. La selezione delle righe non limita questa operazione. Dopo la conferma l'app elimina tutti quei log e aggiorna l'elenco. Se l'elenco o il volume cambiano dopo la conferma, l'operazione viene bloccata.

**FLASH:** il disco virtuale USB non accetta cancellazioni. Se è aperto, **Svuota memoria…** guida prima all'espulsione. Scollega tutte le alimentazioni della FC e ricollega solo USB. Premi **Cerca**, scegli la FC e premi **Svuota memoria… prima di Connetti**. L'app legge modello, UID e capacità della FLASH; la conferma finale identifica questa FC e avverte che tutti i suoi log verranno persi. Una FC con UID o capacità diversi al momento dell'operazione viene rifiutata.

Solo dopo la conferma viene inviato `MSP_DATAFLASH_ERASE` (72). La FC deve usare Betaflight, avere Blackbox su FLASH ed essere disarmata. L'app attende tramite `MSP_DATAFLASH_SUMMARY` (70) memoria pronta e 0 byte usati, fino a 10 minuti. L'erase hardware non può essere annullato dopo l'invio: chiusura e annullamento sono disabilitati durante il monitoraggio. Un errore di comunicazione non viene presentato come successo e non provoca un secondo erase automatico.

La cancellazione riguarda la memoria Blackbox, non il ripristino delle impostazioni della FC. Le copie sul computer rimangono disponibili. I comandi di erase sono stati verificati su risposte simulate; non è stato eseguito uno svuotamento reale durante lo sviluppo.

Per le flash che espongono al massimo 100 file, l'app legge l'indice del file complessivo e mostra anche i voli successivi. I voli estratti ricevono un nome `VOLO_00101.BBL`, perché non esiste un file individuale originale oltre il limite del firmware.

## Compatibilità e limiti

- Solo Mac e Windows. La build Mac di questa consegna è per **Intel x86_64, macOS 14+**; Apple Silicon richiede una build dedicata oppure Rosetta.
- Una FC selezionata per volta. Dopo il riavvio l'app cerca un nuovo volume USB esterno e si ferma se ne compaiono più di uno. Evitare di collegare altri dischi durante il passaggio.
- Selezionando un disco già montato non è possibile verificare di nuovo via MSP modello e firmware; l'interfaccia lo segnala come memoria già collegata.
- Le FC senza MSC non sono supportate in questa fase. Nessuno scaricamento seriale alternativo della flash.
- Destinazione su disco locale Mac (APFS/HFS+) o Windows (NTFS): la pubblicazione senza sovrascrittura utilizza hard link. Filesystem che non li supportano, come exFAT, non sono destinazioni supportate nella prima versione.
- Le copie locali restano disponibili dopo un errore successivo. Un errore durante una cancellazione multipla può lasciare un'operazione parziale, indicata nel messaggio: aggiornare l'elenco.
- L'espulsione da macOS/Windows non riavvia Betaflight. Scollegare e ricollegare l'alimentazione USB per uscire dalla modalità memoria.
- Le build locali non sono firmate con un certificato Apple/Microsoft di distribuzione e non sono notarizzate. Per distribuire l'app ad altre persone serviranno firma e test sui sistemi destinatari.

## Sviluppo e test

Python 3.10–3.14. Si consiglia 3.13 per nuove build Windows. Le dipendenze sono fissate in `requirements.txt`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_app.py
```

Su Windows sostituire `.venv/bin/python` con `.venv\Scripts\python.exe`.

La suite usa cartelle temporanee e risposte dei dispositivi simulate: non cancella file su FC reali. Include prove dell'interfaccia Qt, della copia, dei conflitti, della cancellazione selettiva e degli adattatori. I test dei comandi Windows eseguiti sul Mac verificano i contratti, **non sostituiscono un collaudo Windows**.

`run_app.py --demo` apre una dimostrazione con file finti temporanei; il banner giallo lo indica. Non vengono toccati dispositivi reali. I file demo non contengono un volo utilizzabile per l'analisi.

## Creare gli eseguibili

```sh
.venv/bin/python tools/build.py
```

La build include interprete, Qt e dipendenze; il destinatario non deve installare Python. Su Mac produce `dist/Blackbox Desk.app`, su Windows `dist/Blackbox Desk/Blackbox Desk.exe` con la sua cartella di dipendenze. I pacchetti vanno compilati sul sistema operativo di destinazione. Non copiare soltanto l'exe fuori dalla sua cartella.

La prima build scarica i testi delle licenze ufficiali in `resources/licenses`; vengono conservati e inclusi nei pacchetti successivi. Il comando produce anche uno ZIP distribuibile e verifica l'avvio dell'eseguibile.

La procedura `.github/workflows/build.yml`, se il progetto viene in futuro caricato su GitHub, esegue test e build su Windows e Mac; non è stata pubblicata o eseguita durante questa consegna.

## Fonti tecniche

- [Betaflight: USB Mass Storage](https://betaflight.com/docs/wiki/guides/current/Mass-Storage-Device-Support)
- [Configurazione SpeedyBee F7 V3: SDCARD integrata](https://support.betaflight.com/targets/SPEEDYBEEF7V3)
- [Filesystem virtuale flash Betaflight](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/msc/emfat_file.c)
- [Protocollo MSP Betaflight](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/msp/msp.c)
- [Qt for Python: distribuzione desktop](https://doc.qt.io/qtforpython-6/faq/distribution.html)
- [Qt: cestino nativo per file, cartelle e link](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QFile.html#PySide6.QtCore.QFile.moveToTrash)

## Prossime fasi

1. Collaudo dell'app sulla FC dell'utente: elenco, copia, espulsione; prova di cancellazione soltanto su un log scelto esplicitamente dall'utente e già salvato.
2. Build e collaudo su Windows con almeno una FC FLASH e una SDCARD.
3. Collaudo hardware dello svuotamento completo, soltanto su iniziativa dell'utente dalla finestra di conferma; eventuale scaricamento seriale per FC senza MSC.
