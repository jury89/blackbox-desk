# Direzione dell'interfaccia

Un gestore a due pannelli per recuperare i voli. La FC occupa la metà sinistra; il computer la metà destra. Il divisore è regolabile e le due liste restano affiancate. Collegamento e comandi della FC rimangono nel suo pannello, navigazione locale nel pannello Computer. Nessun terzo pannello che sottragga spazio ai file.

```text
Betaflight Blackbox Desk          Trascina i log dalla FC al computer
Flight controller                 │ Computer
Dispositivo · Cerca · Connetti     │ Indietro · Su · Percorso · Scegli
Modello e memoria                 │ Cartella corrente
Log · Registrato · Dimensione     │ Nome · Dimensione · Modificato
... selezione multipla ...        │ ... cartelle, poi log ...
Copia ultimo · Copia selezionati  │ Aggiornamento automatico
Elimina · Svuota · Espelli         │ Espelli dopo la copia
Stato dell'operazione e avanzamento comune
```

Palette: carta #FFFFFF, fondo FC #F1F5FA, testo #172B46, secondario #62738B, blu azione #245AD1, errore #B63D49. Carattere di sistema (Helvetica Neue / Segoe UI); titolo 22, sezioni 17, comandi e testo 13. Allineamento a sinistra; dimensioni dei file a destra. I nomi dei file mantengono maiuscole e minuscole originali.

Nel pannello Computer tutte le cartelle visibili precedono sempre i file, anche in ordine decrescente e ordinando per dimensione o data. Tra i file sono mostrati solo i log `.bbl` e `.bfl` (senza distinzione fra maiuscole e minuscole). Il conteggio indica separatamente cartelle e log visibili; gli altri file rimangono accessibili dal Finder/Explorer.

La selezione locale usa tutta la riga, con azzurro esplicito anche senza focus. Accanto al conteggio compaiono **Nuova cartella…** ed **Elimina…**. Il primo chiede un nome per una sottocartella; il secondo si abilita con la selezione e apre una conferma per il Cestino. La conferma di cartelle include esplicitamente tutto il contenuto, anche escluso dal filtro. Nessuna eliminazione permanente locale. Il numero di elementi selezionati appare sotto la lista; entrando in una cartella la selezione si azzera.

L'elenco FC compare appena pronti nomi e dimensioni. Le date partono da `…` e si aggiornano in background senza cambiare selezione, ordine o stato della copia. I pulsanti sono già utilizzabili; le operazioni dell'utente hanno precedenza sulle date. Lo stato distingue attesa del disco USB ed elenco dei log; Informazioni espone i tempi dell'ultimo collegamento.

Una linea di volo blu compatta identifica l'app. Il resto segue il modello familiare dei gestori di file: selezione con clic, Maiusc e Cmd/Ctrl; doppio clic sulle cartelle; percorso modificabile, Indietro e Su. Il drag rende blu solo il pannello Computer quando la destinazione è valida. Il trascinamento è sempre una copia: nessun trasferimento inverso e nessuna cancellazione automatica dalla FC. Nessuna data del filesystem presentata come data certa del volo.

Revisione del brief prima della realizzazione: rimosso il vecchio sidebar, che avrebbe creato tre colonne invece delle due richieste. Due superfici continue, niente schede statistiche o decorazioni ripetitive. La distinzione visiva principale è fra sorgente FC e destinazione Computer. Le funzioni già presenti rimangono raggiungibili anche senza trascinamento. La modalità demo è chiaramente etichettata.
