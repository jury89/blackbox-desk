# Blackbox Desk

- Applicazione desktop Python / PySide6, Mac e Windows; nessun server o account.
- Eseguire l'intera suite prima di commit/build di consegna: `.venv/bin/python -m unittest discover -s tests -v` (su Windows `.venv\Scripts\python.exe`). Un solo build/test pesante alla volta.
- Aggiornare README e documentazione delle capacità insieme al codice.
- Nessun comando di configurazione, armamento o formattazione del disco. Sono consentiti il riavvio in MSC e, su richiesta esplicita dell'utente tramite conferma nell'app, MSP_DATAFLASH_ERASE per la sola memoria Blackbox FLASH. Verificare Betaflight, UID, capacità e stato disarmato subito prima dell'erase; attendere memoria pronta e usata=0 prima di dichiarare successo.
- Svuotamento SDCARD: eliminare solo file di log Blackbox nel volume selezionato dopo conferma dell'intero elenco, inclusi log vuoti/incompleti. Non toccare altri file o il cestino del sistema. Mai eseguire erase o cancellazioni reali durante i test.
- Cancellazione individuale solo per file SDCARD validati, su volume USB scrivibile, dopo conferma esplicita nell'interfaccia. Mai cancellare file reali durante i test: usare cartelle temporanee.
- Copia con controllo di integrità, conservazione del nome originale, conflitti numerati, copie locali sbloccate. Non copiare i flag di blocco dalla FC.
- UX a due pannelli: FC a sinistra, cartella locale navigabile a destra. Drag solo FC → computer, sempre CopyAction. Nessun drag dal computer né drop sulla FC; rifiutare MIME esterni, sessioni obsolete e destinazioni nella FC anche attraverso symlink. Riutilizzare il backend di copia verificata.
- Gestione locale: creare soltanto sottocartelle con nomi validi, senza sovrascritture. Eliminazione locale solo tramite Cestino nativo e conferma dell'elenco, esplicitando tutto il contenuto delle cartelle; mai ripiegare sulla cancellazione definitiva. Verificare selezione e cartella dopo la conferma, escludere la FC aperta e bloccare le azioni durante i trasferimenti. Per i test usare soltanto file temporanei.
- Collegamento: mostrare l'elenco dei file individuali senza leggere prima tutte le date. I metadati differiti usano lo stesso worker USB, si interrompono per le operazioni dell'utente e non possono aggiornare una sessione successiva. Conservare validazione delle copie e dei dispositivi; distinguere misure a caldo da prove complete di montaggio a freddo.
- Espulsione Mac: usare `diskutil unmountDisk` sul solo disco padre validato, senza force. `diskutil eject` provoca un rimontaggio immediato sulla SpeedyBee F7 V3. Nessuna blacklist persistente, regola globale di automount o processo di sorveglianza: il nuovo collegamento fisico USB deve restare possibile.
- Non dichiarare Windows o hardware non disponibile come testati. Le build vanno prodotte sul sistema operativo di destinazione.
- `--demo` usa soltanto dati temporanei locali per provare l'interfaccia; renderlo chiarissimo nell'app.
