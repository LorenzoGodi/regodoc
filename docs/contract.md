# Contratto del motore regodoc

Stato: **bozza per il dossier DL-18**, ottobre 2026. Diventa la versione 1 del contratto
quando Lorenzo la approva. Fino ad allora `regodoc info` dichiara `"contract": 0`, cioè
«contratto in bozza, può cambiare senza preavviso».

Questo documento dice come un programma, per esempio Rego, usa il motore: come lo chiama,
che cosa gli passa, che cosa riceve, come legge ciò che il motore sa fare e quali sono i suoi
limiti, come si scrive un tema esterno e come il motore tratta le grammatiche precedenti. Il
formato del pacchetto è nella [specifica `rego/1`](spec/rego-1.md).

Il contratto ha un numero di versione, un intero. **Finché il numero non cambia, chi chiama il
motore non cambia.** Tutto ciò che il motore può aggiungere senza cambiarlo è elencato al §9.

## 1. Tre regole

1. **Confine di processo.** Il motore si usa come un comando, mai importandolo. Il chiamante
   gli passa file e opzioni; il motore risponde con file, un rapporto JSON su stdout e un
   codice d'uscita. Archivio, XML e immagini si leggono nel processo del motore, con i suoi
   limiti di tempo e di memoria, mai nel processo del chiamante.
2. **Il motore si dichiara.** Versione, contratto, grammatiche, limiti, risorse, capacità e
   passate di compilazione si leggono da `regodoc info` (§5). Il chiamante li applica senza
   averli copiati nel proprio codice.
3. **Il chiamante non conosce il vocabolario.** Elementi, chiavi, valori chiusi e regole del
   formato vivono nel motore. Il chiamante conserva i pacchetti come insiemi di file con le
   loro impronte, la versione del formato e la storia delle versioni.

## 2. Invocazione

```
regodoc [--contract N] COMANDO [ARGOMENTI] [--json] [--strict]
python -m regodoc …          # stessa cosa
```

| Comando | Argomenti | Uscita | Note |
|---|---|---|---|
| `info` | — | dichiarazione JSON su stdout (§5) | non legge pacchetti |
| `validate` | `PACCHETTO` | solo il rapporto | archivio o cartella |
| `canon` | `PACCHETTO -o ARCHIVIO` | l'archivio in forma canonica | da archivio o cartella; scrive anche `README.md` |
| `build` | `PACCHETTO -o FILE [--format pdf\|latex] [--header JSON] [--theme CARTELLA]` | PDF, oppure una cartella con il LaTeX | solo archivi |
| `upgrade` | `PACCHETTO -o ARCHIVIO` | l'archivio nella grammatica corrente, in forma canonica | solo archivi |

Opzioni comuni:

- `--json`: il rapporto (§4) va su stdout. Senza, i messaggi vanno su stderr in forma
  leggibile e stdout resta vuoto. Il chiamante automatico usa sempre `--json`.
- `--strict`: gli avvisi contano come errori.
- `--contract N`: il chiamante dichiara la versione del contratto che si aspetta. Se il
  motore non la supporta, esce subito con il codice 2 e lo dice; non produce mai un
  rapporto in una forma diversa da quella chiesta. Rego passa sempre `--contract`.
- `--max-seconds S`, solo per i comandi che leggono un pacchetto: abbassa il tempo massimo
  dichiarato dal motore (§5, `resources`); un valore più alto del dichiarato è ignorato.

Ambiente:

- Il motore legge solo `PATH`, per trovare `pdflatex`, e `TMPDIR`, per la cartella di lavoro
  temporanea. Ignora `SOURCE_DATE_EPOCH` e ogni altra variabile: la data del PDF viene dal
  pacchetto o dall'intestazione (§3.2), così due chiamanti diversi ottengono lo stesso PDF.
- Il motore non usa la rete.
- Il motore scrive solo nella propria cartella temporanea, che rimuove alla fine, e nel
  percorso dato con `-o`, che scrive in modo atomico: un file d'uscita esiste solo se il
  comando è riuscito.

## 3. Ingresso

### 3.1 Il pacchetto

Un file `.regodoc` secondo la specifica. Il chiamante applica all'ingresso i limiti
dell'involucro dichiarati in `limits.envelope` (§5) prima ancora di chiamare il motore, che li
ripete.

### 3.2 L'intestazione (`--header`)

Un file JSON in UTF-8, al massimo 64 KiB, con i dati che il pacchetto non contiene e che
servono alla cornice del tema. Chiavi ammesse e nessun'altra:

```json
{
  "contract": 1,
  "document_created": "2026-10-05T09:12:00+02:00",
  "frame": {
    "issuer": "Studio Esempio",
    "recipient": "Cantina Colle Rovere",
    "document_code": "CR-2026-07"
  }
}
```

| Chiave | Obbligatoria | Regola |
|---|---|---|
| `contract` | sì | la versione del contratto con cui è scritta l'intestazione |
| `document_created` | no | istante di creazione del documento, RFC 3339 con fuso; è il ripiego della data quando il pacchetto non ha `header.date` (A4) |
| `frame` | no | dati della cornice per il tema: al massimo 50 chiavi `[a-z][a-z0-9_]{0,31}`, valori di testo puro da 1 a 500 caratteri, con le regole sui caratteri della specifica (§5.2) |

La data del documento, nell'ordine: `header.date` del pacchetto; altrimenti
`document_created` dell'intestazione, ridotta alla data nel suo fuso; altrimenti `build` esce
con il codice 2. `SOURCE_DATE_EPOCH` è la mezzanotte UTC di quella data.

Titolo, oggetto e riferimento **non** stanno nell'intestazione: la loro fonte di verità è il
pacchetto (decisione 20). Il motore non interpreta le chiavi di `frame`: le passa al tema, che
dichiara quali usa (§6).

### 3.3 Il tema (`--theme`)

Una cartella conforme al contratto del tema (§6). Senza `--theme` il motore usa il proprio
tema neutro.

## 4. Il rapporto

Ogni comando che legge un pacchetto, con `--json`, scrive su stdout un solo oggetto JSON in
UTF-8, con le chiavi in ordine alfabetico e un a capo finale. Il rapporto non contiene istanti
né durate, così due esecuzioni sullo stesso ingresso danno lo stesso rapporto.

```json
{
  "contract": 1,
  "engine": { "name": "regodoc", "version": "0.1.0" },
  "command": "build",
  "exit_code": 0,
  "ok": true,
  "grammar": "rego/1",
  "errors": [],
  "warnings": [
    {
      "severity": "warning",
      "code": "regodoc.toml.unused_variable",
      "message": "la variabile «spare» non è mai usata",
      "file": "variables.toml",
      "line": 11,
      "column": 0
    }
  ],
  "limits_active": { "time_seconds": 120, "memory_bytes": 1073741824 },
  "input": { "sha256": "…", "bytes": 48213 },
  "outputs": [ { "path": "documento.pdf", "sha256": "…", "bytes": 210844 } ],
  "passes": 3,
  "theme": { "name": "neutral", "version": "1" }
}
```

| Chiave | Sempre | Contenuto |
|---|---|---|
| `contract` | sì | la versione del contratto del rapporto |
| `engine` | sì | `name` e `version` del motore |
| `command` | sì | il comando eseguito |
| `exit_code` | sì | lo stesso codice con cui esce il processo (§7) |
| `ok` | sì | `true` solo con il codice 0 |
| `grammar` | sì | la grammatica letta dal manifesto, o `null` se non si è arrivati a leggerla |
| `errors`, `warnings` | sì | i problemi, ciascuno con `severity`, `code`, `message`, `file`, `line`, `column` (§8 della specifica); `line` e `column` valgono 0 quando non si applicano |
| `limits_active` | sì | i limiti di risorse davvero applicati: `time_seconds`, e `memory_bytes` oppure `null` dove il sistema non permette di limitare la memoria (macOS) |
| `input` | se il pacchetto è stato letto | `sha256` e `bytes` del file ricevuto |
| `outputs` | `canon`, `build`, `upgrade` riusciti | i file scritti, con `sha256` e `bytes` |
| `passes` | `build` riuscito | le passate di pdflatex eseguite |
| `theme` | `build` | il tema usato, dal suo `theme.toml` |
| `grammar_in`, `grammar_out` | `upgrade` | la grammatica letta e quella scritta |

Con il codice 2 per un file mancante il rapporto c'è, con un solo errore
`regodoc.usage`. Con il codice 4 il rapporto **può mancare**: è un difetto del motore, e
stderr dice che cosa è successo.

## 5. La dichiarazione (`regodoc info`)

`regodoc info` scrive su stdout un oggetto JSON, con le chiavi in ordine alfabetico:

| Chiave | Contenuto |
|---|---|
| `engine` | `"regodoc"` |
| `version` | versione del motore, PEP 440 |
| `contract` | versione corrente del contratto; `contracts` elenca tutte quelle supportate da `--contract` |
| `contracts` | le versioni del contratto supportate |
| `grammars` | `current`, la grammatica che il motore scrive, e `read`, quelle che sa leggere, dalla più vecchia |
| `limits` | `envelope` e `content`, in byte o in unità contate, con i nomi del §7 della specifica |
| `resources` | `time_seconds` per ciascun comando, `memory_bytes`, `memory_enforced_on` (i sistemi dove il limite di memoria è applicato) |
| `commands` | per ciascun comando, `ready` oppure `draft` (non ancora disponibile, codice 3) |
| `capabilities` | elenco di stringhe stabili: ciò che questa versione sa fare (§9) |
| `languages` | le lingue del documento supportate |
| `passes` | `min` e `max` delle passate di pdflatex che `build` può eseguire |
| `tex` | `packages`: i pacchetti LaTeX che il motore e il tema neutro caricano |
| `theme_contract` | la versione del contratto del tema (§6) |

Il chiamante legge la dichiarazione all'avvio, o quando cambia la versione fissata del motore,
e la conserva. Per esempio Rego:

- applica `limits.envelope` all'ingresso dei pacchetti;
- concede a ogni chiamata `resources.time_seconds` più un margine;
- abilita le funzioni della propria interfaccia secondo `commands` e `capabilities`;
- confronta `tex.packages` con la propria immagine TeX e segnala un pacchetto mancante prima
  di aggiornare il motore.

## 6. Il contratto del tema

Un tema è una cartella:

```
mio-tema/
  theme.toml        # obbligatorio
  theme.sty         # obbligatorio
  assets/           # facoltativo: immagini PNG, JPEG o PDF usate dal tema
```

### 6.1 `theme.toml`

```toml
name = "colle-rovere-demo"
version = "3"
theme_contract = 1
frame_keys = ["issuer", "recipient", "document_code"]

[palette]
azure = "1F6F9F"
slate = "4A5560"
sage = "5E7F5A"
bronze = "8C6A2F"
plum = "6B4A6E"
brick = "9C4A3A"
olive = "6E7330"
gray = "6B6B6B"
warning = "A86B00"
critical = "A23030"
ok = "2F6B3A"
muted = "7A7A7A"
```

| Chiave | Regola |
|---|---|
| `name` | `[a-z][a-z0-9-]{0,47}` |
| `version` | testo, da 1 a 32 caratteri; entra nella versione del generatore (decisione 16) |
| `theme_contract` | la versione del contratto del tema: oggi 1 |
| `frame_keys` | le chiavi di `frame` (§3.2) che il tema stampa; una chiave usata e assente dall'intestazione stampa una stringa vuota e produce un avviso |
| `palette` | i colori, in esadecimale `RRGGBB`: gli otto ruoli degli accenti e i quattro toni; un ruolo mancante è un errore |

### 6.2 `theme.sty`

Un pacchetto LaTeX caricato dopo `regodoc.sty`. Può caricare solo pacchetti dell'insieme
dichiarato in `tex.packages` e può ridefinire solo questi agganci, che `regodoc.sty` definisce
con un comportamento neutro:

| Aggancio | Quando | Argomenti |
|---|---|---|
| `\RegodocThemeSetup` | fine del preambolo | — |
| `\RegodocTitlePage` | inizio del documento | — |
| `\RegodocPageStyle` | dopo il frontespizio | — |
| `\RegodocPartOpening` | inizio di ogni parte | numero romano, titolo, ruolo dell'accento |
| `\RegodocOpeningStart` | inizio di ogni apertura | — |
| `\RegodocBox` | ambiente dei riquadri | tipo |
| `\RegodocLabel` | etichetta in linea | tipo, dicitura nella lingua del documento |

I dati arrivano al tema solo attraverso macro di sola lettura, con testo già trascritto dal
generatore:

- `\RegodocTitle`, `\RegodocSubject`, `\RegodocReference`, `\RegodocVersionLabel`,
  `\RegodocDate`;
- `\RegodocFrame{chiave}`;
- `\RegodocLanguage`;
- il colore `regodoc-<ruolo>` per ogni voce di `palette`.

Il tema non riceve mai testo del pacchetto non trascritto e non definisce comandi che il
generatore usa per il contenuto.

### 6.3 Regole

- Il motore copia il tema nella propria cartella di lavoro e compila da lì: il tema non vede
  altri file.
- pdflatex gira senza `shell escape`, con lettura e scrittura limitate alla cartella di
  lavoro.
- Il tema neutro del motore è un tema come gli altri, nella stessa forma, e fa da esempio.
- Un tema che non rispetta il contratto ferma `build` con il codice 1 e un errore
  `regodoc.theme.*`.

## 7. Codici d'uscita

| Codice | Significato | Il chiamante… |
|---|---|---|
| 0 | esito positivo, anche con avvisi (senza `--strict`) | usa l'uscita |
| 1 | pacchetto o tema rifiutato per errori, o per avvisi con `--strict`; l'elenco è nel rapporto | mostra gli errori a chi ha caricato il pacchetto |
| 2 | errore d'uso: argomenti, file mancante, opzione sconosciuta, contratto non supportato, data mancante | corregge la chiamata: è un difetto del chiamante |
| 3 | errore d'ambiente: TeX assente, cartella non scrivibile, tempo massimo superato, uscita chiusa da chi legge, comando non ancora disponibile | riprova più tardi o segnala l'ambiente |
| 4 | errore interno: un'eccezione non prevista | segnala un difetto del motore; non riprova |
| 130 | interrotto | — |

## 8. Grammatiche e aggiornamento

- Il manifesto di ogni pacchetto dichiara la grammatica. Il motore legge tutte quelle in
  `grammars.read` e le porta alla corrente con una catena di aggiornatori, uno per passo
  (`rego/1` → `rego/2` → …), sempre inclusa nel motore.
- `upgrade` scrive il pacchetto nella grammatica corrente, in forma canonica, e il rapporto
  dice `grammar_in` e `grammar_out`. Il chiamante lo conserva come **versione nuova**,
  tracciata, mai come riscrittura della precedente.
- `validate` e `build` accettano anche le grammatiche precedenti: aggiornano in memoria e lo
  segnalano con l'avviso `regodoc.grammar.upgraded`.
- Una grammatica più nuova di `grammars.current` è rifiutata con il codice 1 e l'errore
  `regodoc.manifest.grammar_newer`, che indica la versione del motore necessaria.

## 9. Che cosa cambia senza cambiare il contratto

Il motore può, con una versione nuova e **senza** cambiare il numero del contratto:

- aggiungere elementi, attributi e valori alla grammatica corrente (§10 della specifica);
- aprire una grammatica nuova con il suo aggiornatore;
- alzare i limiti del contenuto e le risorse dichiarate;
- aggiungere capacità, lingue, codici d'errore e d'avviso, chiavi nuove nel rapporto e nella
  dichiarazione (il chiamante ignora le chiavi che non conosce);
- cambiare l'aspetto del tema neutro;
- cambiare il numero di passate entro `passes`.

Cambiano il contratto, e richiedono una versione nuova di chi chiama:

- togliere o rinominare comandi, opzioni o chiavi;
- cambiare il significato di un codice d'uscita o di un codice d'errore;
- abbassare un limite dell'involucro;
- cambiare il contratto del tema in modo incompatibile (che ha un proprio numero,
  `theme_contract`).

Il motore supporta la versione corrente del contratto e, per almeno una versione minore del
motore dopo un cambiamento, anche la precedente, scelta con `--contract`.

## 10. Studio di autonomia

Domanda di Lorenzo (decisione 4ter): quanto Rego può sostenere funzioni nuove del motore
senza toccare il proprio codice, o almeno senza toccare il database.

| Cambiamento nel motore | Codice di Rego | Database di Rego |
|---|---|---|
| Elemento, attributo o valore nuovo nella grammatica | nessuno | nessuno |
| Grammatica nuova con aggiornatore | nessuno: le versioni aggiornate sono versioni nuove | nessuno: la versione del formato è un testo |
| Limiti di contenuto più alti | nessuno: li legge da `info` | nessuno |
| Limiti dell'involucro più alti | nessuno se Rego li legge da `info`; la configurazione del proxy, se ne ha uno, a parte | nessuno |
| Lingua nuova del documento | nessuno | nessuno |
| Capacità nuova (per esempio un formato d'uscita) | l'interfaccia la mostra se la conosce; altrimenti la ignora | nessuno |
| Passate di compilazione in più | nessuno: il tempo concesso viene da `resources` | nessuno |
| Pacchetto LaTeX nuovo | nessuno; l'immagine TeX sì, e `tex.packages` lo rivela prima dell'aggiornamento | nessuno |
| Contratto nuovo | sì, il modulo che chiama il motore | nessuno |
| Contratto del tema nuovo | sì, il tema di marchio | nessuno |

Il database di Rego conserva i pacchetti in forma generica: file con impronte, versione del
formato, storia delle versioni. Nessun suo vincolo conosce il vocabolario, quindi nessuna
riga della tabella cambia schema per un'evoluzione del formato. La proposta delle tabelle
segue questo principio ed è consegnata a parte, al capo progetto.

Restano comunque di Rego, qualunque cosa faccia il motore:

- la tabella dei documenti e le colonne di titolo, oggetto e riferimento come proiezione;
- la capacità «ammette pacchetto» del catalogo dei tipi;
- i permessi e le rotte di esportazione, importazione, ripristino, elenco e differenze;
- la logica dei conflitti sulle impronte;
- i candidati d'emissione e lo ZIP d'emissione;
- il tema di marchio;
- l'immagine TeX e i limiti all'ingresso.
