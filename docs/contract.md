# Contratto del motore regodoc

Stato: **versione 1, approvata il 14/10/2026; emendata il 15/10/2026 prima del primo
rilascio: §2.1 e §2.3 limiti applicati dal motore, §4.4 e §5.1 avvisi oltre il tetto dei
problemi.** Lo stesso emendamento aggiunge `limits_active` con i valori applicati (§4.1),
la chiave `warnings_omitted` e i testi puri di `generator` (§4.2). `regodoc info` dichiara
`"contract": 1`. La bozza che la precedeva, dichiarata come versione 0, non è servita da
nessun motore: chi chiama passa `--contract 1`.

Questo documento dice come un programma usa il motore: come lo chiama, che cosa gli passa,
che cosa riceve, come legge ciò che il motore sa fare e quali sono i suoi limiti, come si
scrive un tema esterno e come il motore tratta le grammatiche precedenti. Il formato del
pacchetto è nella [specifica `rego/1`](spec/rego-1.md). Nel testo, «chi chiama» è il
programma che usa il motore; Rego, il gestionale per cui il motore è nato, è l'esempio
ricorrente.

Il contratto ha un numero di versione, un intero. **Finché il numero non cambia, chi chiama il
motore non cambia.** Tutto ciò che il motore può aggiungere senza cambiarlo è elencato al §9.

## 1. Tre regole

1. **Confine di processo.** Il motore si usa come un comando, mai importandolo. Chi chiama gli
   passa file e opzioni; il motore risponde con file, un rapporto JSON su stdout e un codice
   d'uscita. Archivio, XML, TOML e immagini si leggono nel processo del motore, mai nel
   processo di chi chiama.
2. **Il motore si dichiara.** Versione, contratto, grammatiche, limiti, risorse, capacità,
   passate di compilazione e contratto del tema si leggono da `regodoc info` (§5). Chi chiama
   li applica senza averli copiati nel proprio codice.
3. **Chi chiama non apre il pacchetto.** Elementi, chiavi, valori chiusi e regole del formato
   vivono nel motore. Chi chiama non apre mai l'archivio, il manifesto o i file TOML: tutto ciò
   che gli serve del pacchetto (grammatica, file e impronte, intestazione) glielo restituisce
   il motore nel rapporto (§4.2). Chi chiama conserva i pacchetti come insiemi di file con le
   loro impronte, la versione del formato e la storia delle versioni.

## 2. Invocazione

### 2.1 Comandi e opzioni

```
python -I -B -m regodoc [--contract N] [--max-seconds S] info [--json]
python -I -B -m regodoc [--contract N] [--max-seconds S] COMANDO ARGOMENTI [--json] [--strict]
python -I -B -m regodoc --version
python -I -B -m regodoc -h
```

`--version` e `-h` scrivono testo per le persone e restano fuori dalla promessa del rapporto
JSON (§4.1): chi chiama da un programma usa `info`.

| Comando | Argomenti | Uscita | Note |
|---|---|---|---|
| `info` | `[--json]` | dichiarazione JSON su stdout (§5) | `--json` è accettata e non cambia nulla: `info` scrive sempre JSON |
| `validate` | `PACCHETTO` | solo il rapporto | archivio o cartella |
| `canon` | `PACCHETTO -o ARCHIVIO [--document ID] [--base-version IMPRONTA] [--files-dir CARTELLA]` | l'archivio in forma canonica, con `README.md` e manifesto scritti dal motore | da archivio o cartella; `--document` e `--base-version` scrivono i campi del manifesto (specifica, §1.3), e senza di loro restano i valori del manifesto d'ingresso, se ci sono; `--files-dir` scrive anche i file di contenuto canonici uno per uno, nella cartella data, che deve essere vuota |
| `build` | `PACCHETTO -o FILE [--format pdf\|latex] [--header JSON] [--theme CARTELLA]` | PDF, oppure una cartella con il LaTeX | solo archivi |
| `upgrade` | `PACCHETTO -o ARCHIVIO` | l'archivio nella grammatica corrente, in forma canonica | solo archivi |

Opzioni comuni:

- `--json`: il rapporto (§4) va su stdout. Senza, i messaggi vanno su stderr in forma
  leggibile e stdout resta vuoto. Chi chiama da un programma usa sempre `--json`, anche con
  `info`.
- `--strict` (non per `info`): gli avvisi contano come errori, salvo gli avvisi informativi
  (§4.4). Rego non lo
  usa al caricamento dei pacchetti: gli avvisi li mostra a chi ha caricato il pacchetto.
- `--max-seconds S`: abbassa il tempo massimo del comando (§2.3).
- `--contract N`: chi chiama dichiara la versione del contratto che si aspetta. Se il motore
  non la supporta, esce con il codice 2 e il rapporto minimo (§4.1), nella forma stabile fra
  tutte le versioni. Rego passa sempre `--contract`.

**L'uscita `-o`.** È il percorso di un file (per `--format latex`, di una cartella) che il
motore crea in modo atomico: scrive accanto a un nome temporaneo e lo rinomina solo se il
comando è riuscito, quindi l'uscita esiste solo con il codice 0. Se il percorso esiste già
viene sostituito per intero: un file, oppure, per `--format latex`, una cartella con tutto il
suo contenuto. Se il percorso è un collegamento simbolico, il motore sostituisce il
collegamento, non ciò a cui punta. La cartella che lo contiene deve esistere: se manca, il
codice è 2; se non è scrivibile, 3. L'uscita non può coincidere con il pacchetto d'ingresso
(codice 2). `--files-dir` deve indicare una cartella che esiste ed è vuota, altrimenti il
codice è 2; il motore non la svuota e non la crea.

### 2.2 Ambiente

Chi chiama avvia il motore così:

- **Interprete isolato:** `python -I -B -m regodoc`. `-I` esclude le variabili `PYTHON*`, la
  cartella corrente e i pacchetti dell'utente; `-B` evita di scrivere file `.pyc`. La copia del
  motore che chi chiama fissa (§11) è installata da un wheel nel suo ambiente virtuale, con
  `pip install --require-hashes`; il comando usa l'interprete di quell'ambiente.
- **stdin** da `/dev/null`; **cartella corrente** una cartella temporanea vuota.
- **Variabili:** il motore legge solo `PATH`, per trovare `pdflatex`, `TMPDIR`, per la
  cartella di lavoro, e `SOURCE_DATE_EPOCH`, come ultimo ripiego della data (§3.2). Ignora
  ogni altra variabile.
- **Rete:** il motore non la usa.
- **Scritture:** il motore scrive solo nella propria cartella temporanea, che rimuove alla
  fine, e nelle uscite di `-o` e `--files-dir`.

Per pdflatex il motore costruisce un ambiente da zero, senza ereditare quello del chiamante:
`PATH` ridotto alla cartella di `pdflatex`; `HOME`, `TEXMFHOME`, `TEXMFVAR` e `TEXMFCONFIG`
nella cartella di lavoro; `openin_any=p`, `openout_any=p`, `shell_escape=f`; `MKTEXFMT=0`,
`MKTEXPK=0`, `MKTEXTFM=0`; `LC_ALL=C.UTF-8`; `SOURCE_DATE_EPOCH` dalla data del documento e
`FORCE_SOURCE_DATE=1`. pdflatex gira con `-no-shell-escape -interaction=batchmode
-halt-on-error -recorder`, **nello stesso gruppo di processi del motore**, così chi uccide il
gruppo (§2.3) uccide anche pdflatex. L'uscita di pdflatex e di ogni altro processo figlio va
in file della cartella di lavoro, mai su stdout o stderr del motore: su stdout c'è solo il
rapporto.

### 2.3 Risorse e tempo

`info` dichiara in `resources` il tempo massimo per comando e il limite di memoria, e con
`resources.enforced` se questa versione del motore li applica da sé; `memory_enforced_on`
elenca i sistemi dove il motore limita da sé la memoria, ed è vuoto quando `enforced` è
`false`.

- Con `enforced: true`, come in questa versione, il motore applica i limiti da sé:
  - **Tempo.** Allo scadere di `time_seconds` del comando il motore si ferma ed esce con il
    codice 3 e `regodoc.limit.time`. `--max-seconds S` abbassa il tempo dichiarato per
    questa chiamata; un valore più alto è ignorato, uno minore di 1 è un errore d'uso.
  - **Memoria.** Sui sistemi di `memory_enforced_on` (oggi `linux`) il motore limita lo
    spazio d'indirizzi del proprio processo (`RLIMIT_AS`) a `memory_bytes` all'avvio del
    comando; pdflatex lo eredita. Se chi chiama ha già impostato un limite più basso, resta il
    suo. Se la memoria finisce, il motore esce con il codice 3 e `regodoc.limit.memory`.
  - `limits_active` nel rapporto (§4.1) dice i valori davvero applicati.
  - Chi chiama tiene comunque una rete di sicurezza: avvia il motore in un gruppo di processi
    suo (per esempio `start_new_session`) e, scaduti `time_seconds` più un margine di 10
    secondi, uccide l'intero gruppo con `SIGKILL`, compresi i processi di pdflatex, e tratta
    il caso come codice 3 con `regodoc.limit.time`. Dove `memory_enforced_on` non comprende
    il sistema, la memoria la limita chi chiama, come sotto.
- Con `enforced: false` il motore non li applica: li applica chi chiama.
  - **Tempo.** Con il gruppo di processi e `SIGKILL` allo scadere di `time_seconds` più 10
    secondi, come sopra, trattando il caso come codice 3 con `regodoc.limit.time`.
  - **Memoria.** Chi chiama limita la memoria del processo prima di avviare il motore: su
    Linux con il limite dello spazio d'indirizzi (`RLIMIT_AS`, per esempio con `setrlimit`
    nel processo figlio prima dell'avvio, o con `prlimit`) a `memory_bytes`, oppure con il
    limite di memoria di un cgroup. Se la memoria finisce mentre il motore lavora, il motore
    esce da sé con il codice 3 e `regodoc.limit.memory`. Se invece il sistema uccide il
    processo (per esempio il cgroup con `SIGKILL`), chi chiama tratta il caso come codice 3
    con `regodoc.limit.memory`.
- Un tempo superato o la memoria esaurita non si ritentano alla cieca: con lo stesso pacchetto
  si ripetono.

## 3. Ingresso

### 3.1 Il pacchetto

Un file `.regodoc` secondo la specifica. All'ingresso chi chiama controlla soltanto:

- la dimensione, al massimo `limits.envelope.compressed_bytes`;
- la firma della prima voce che `info.package` dichiara: all'offset 0 i byte `PK\x03\x04`,
  all'offset 30 il nome `mimetype`, all'offset 38 il valore di `info.package.mimetype`.

Numero di file, espansione, rapporto di compressione e tutto il resto li controlla solo il
motore. Chi chiama non apre l'archivio. Il pacchetto passato al motore deve essere un file
regolare o una cartella: una FIFO o un dispositivo danno il codice 2.

### 3.2 L'intestazione (`--header`)

Un file JSON con i dati che il pacchetto non contiene e che servono alla cornice del tema. Si
legge con le regole del manifesto (specifica, §1.3): al massimo 64 KiB, UTF-8, nessuna chiave
ripetuta, niente `NaN` né `Infinity`, chiavi ammesse e nessun'altra:

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
| `contract` | sì | la versione del contratto con cui è scritta; deve coincidere con `--contract`, o con il contratto corrente del motore se `--contract` manca |
| `document_created` | no | istante di creazione del documento, RFC 3339 con fuso |
| `frame` | no | dati della cornice per il tema: al massimo 50 chiavi `[a-z][a-z0-9_]{0,31}`, valori di testo puro da 1 a 500 caratteri, con le regole sui caratteri della specifica (§5.2) |

**La data.** Nell'ordine (specifica, §2): `header.date` del pacchetto, e il PDF usa la
mezzanotte UTC di quella data; altrimenti l'**istante** `document_created`, così com'è;
altrimenti `SOURCE_DATE_EPOCH` dell'ambiente, ignorata quando uno dei due valori precedenti
c'è; altrimenti `build` esce con il codice 2. Rego passa sempre `document_created`, quindi due
chiamanti diversi ottengono lo stesso PDF.

Titolo, oggetto e riferimento **non** stanno nell'intestazione: la loro fonte di verità è il
pacchetto. Il motore non interpreta le chiavi di `frame`: le passa al tema, che dichiara quali
usa (§6).

Un'intestazione mancante, illeggibile o sbagliata ferma `build` con il codice 2 e un errore
`regodoc.header.*`: è un errore di chi chiama, non di chi ha scritto il pacchetto.

### 3.3 Il tema (`--theme`)

Una cartella conforme al contratto del tema (§6). Senza `--theme` il motore usa il proprio
tema neutro. Regole della cartella: niente collegamenti simbolici né file speciali; al massimo
200 file e 8 MiB in tutto (`info.theme.limits`); nomi con caratteri in `[a-z0-9._/-]`. Il motore la copia nella
propria cartella di lavoro senza seguire collegamenti. Un tema mancante, illeggibile o
sbagliato ferma `build` con il codice 2 e un errore `regodoc.theme.*`.

## 4. Il rapporto

Il rapporto è un solo oggetto JSON in UTF-8, con le chiavi in ordine alfabetico e un a capo
finale. Non contiene istanti né durate, così due esecuzioni sullo stesso ingresso danno lo
stesso rapporto.

### 4.1 Forma minima

Con `--json` **ogni** uscita di ogni comando porta almeno queste chiavi, nella stessa forma in
tutte le versioni del contratto: anche gli errori della riga di comando, il contratto non
supportato e i codici 3, 4 e 130. Vale anche quando la riga di comando non nomina un comando:
`regodoc --json` esce con il codice 2 e il rapporto con `command` a `null`. Le eccezioni sono
due, ed è l'elenco completo:

- stdout chiuso da chi legge: il rapporto non ha più dove andare, e il codice 3 basta;
- processo ucciso da un segnale, per esempio da chi chiama allo scadere del tempo (§2.3):
  non c'è né rapporto né codice d'uscita del motore, e chi chiama tratta il caso come
  codice 3 con `regodoc.limit.time`, oppure con `regodoc.limit.memory` se l'ha ucciso il
  limite di memoria.

Fuori da queste due eccezioni, un'uscita con `--json` senza un rapporto JSON valido su stdout
non dovrebbe esistere; se capita, chi chiama la tratta come codice 3 con
`regodoc.environment`, qualunque sia il codice d'uscita del processo.

| Chiave | Contenuto |
|---|---|
| `contract` | la versione del contratto del rapporto |
| `engine` | `name` e `version` del motore |
| `command` | il comando eseguito, o `null` se la riga di comando non lo nomina |
| `exit_code` | lo stesso codice con cui esce il processo (§7) |
| `ok` | `true` solo con il codice 0 |
| `errors` | gli errori (§4.4) |
| `warnings` | gli avvisi, informativi compresi (§4.4) |
| `limits_active` | i limiti di risorse davvero applicati al comando (§2.3): `time_seconds` e `memory_bytes`, ciascuno `null` quando non è applicato, per esempio la memoria fuori da `memory_enforced_on`, o entrambi quando la riga di comando è sbagliata e il comando non parte |

Per `info` la risposta riuscita è la dichiarazione (§5); il rapporto minimo compare solo
quando `info` fallisce.

### 4.2 Che cosa il motore restituisce del pacchetto

`validate`, `canon` e `upgrade` aggiungono ciò che chi chiama deve sapere del pacchetto senza
aprirlo. Una chiave vale `null` quando il motore non è arrivato a leggere la parte del
pacchetto che la contiene.

| Chiave | Contenuto |
|---|---|
| `input` | `sha256` e `bytes` del file ricevuto; `null` per una cartella e per un file oltre `limits.envelope.compressed_bytes`, che il motore non legge per intero |
| `grammar` | la grammatica dichiarata nel manifesto |
| `grammar_in` | solo per `upgrade`: la grammatica del pacchetto ricevuto; `grammar` è quella d'uscita |
| `generator` | `engine` e `version` del motore che ha scritto il pacchetto, dal manifesto; `null` se `generator` non ha esattamente queste due chiavi, testi puri da 1 a 64 caratteri |
| `document`, `base_version` | i valori del manifesto, verificati solo nella forma (specifica, §1.3): il motore non sa che cosa identificano |
| `files` | i file di contenuto, cioè tutti tranne `mimetype`, `manifest.json` e `README.md`, nell'ordine canonico (specifica, §9), ciascuno con `path`, `sha256` e `bytes` |
| `files_sha256` | l'impronta dell'insieme dei file, sotto |
| `warnings_omitted` | gli avvisi rimasti fuori dall'elenco oltre il tetto dei problemi (§4.4); 0 quando l'elenco è completo |
| `package_header` | `title`, `subject`, `reference`, `date` (`AAAA-MM-GG`) e `language` dal `structure.toml` del pacchetto; `null` per una chiave assente. Il nome dice che viene dal pacchetto, per non confonderlo con l'intestazione di `--header` (§3.2) |

**Che cosa descrivono i campi.** Per `validate` descrivono il pacchetto ricevuto: i file così
come sono arrivati, anche fuori dalla forma canonica. Per `canon` e `upgrade` ogni campo,
salvo `input`, descrive **l'archivio d'uscita**: `grammar` è la grammatica d'uscita,
`generator` è questo motore, `document` e `base_version` sono quelli scritti nel manifesto
d'uscita, `files` e `files_sha256` sono i file canonici, `package_header` è quello d'uscita.
`input` resta il file ricevuto.

**Il manifesto d'uscita di `canon` e `upgrade`.** `format` e `grammar` sono quelli d'uscita;
`generator` è questo motore. `document` e `base_version` sono quelli di `--document` e
`--base-version` per `canon`, altrimenti quelli del manifesto d'ingresso, così come sono, o
assenti se mancavano. La chiave `files` del manifesto è sempre riscritta: le impronte dei
file dell'archivio d'uscita, tranne `mimetype` e `manifest.json` (specifica, §1.3), cioè le
impronte al momento di questa scrittura. Le `files` del manifesto d'ingresso non passano
mai nell'uscita.

**`files_sha256`.** È lo sha256 di un testo UTF-8 con una riga per file di `files`,
nell'ordine di `files`: l'impronta esadecimale minuscola, uno spazio, la dimensione in byte
in decimale, uno spazio, il percorso, un a capo. Due pacchetti con gli stessi file di
contenuto hanno lo stesso `files_sha256`, qualunque sia il resto dell'archivio. Chi conserva
le versioni la usa come impronta della versione e la scrive in `base_version` come
`"sha256:"` seguito dall'impronta, con `canon --base-version`.

### 4.3 Che cosa aggiunge `build`

| Chiave | Contenuto |
|---|---|
| `input`, `grammar`, `package_header` | come al §4.2 |
| `outputs` | i file scritti, con `path`, `sha256` e `bytes`. `path` è il percorso di `-o` così come chi chiama l'ha scritto; per `--format latex`, un elemento per ogni file della cartella, con il percorso di `-o`, una `/` e il percorso relativo, in ordine dei byte UTF-8 del percorso |
| `passes` | le passate di pdflatex eseguite |
| `theme` | `name` e `version` dal `theme.toml` del tema usato, e `sha256`, l'impronta dell'albero del tema |
| `tex` | `version_line`, la prima riga di `pdflatex --version` (per esempio `pdfTeX 3.141592653-2.6-1.40.26 (TeX Live 2024)`), che identifica l'immagine TeX usata; `null` con `--format latex` |

**`theme.sha256`.** È calcolata come `files_sha256`, sui file della cartella del tema
ordinati per i byte UTF-8 del percorso, con i percorsi relativi alla cartella. Per chi
conserva i PDF generati, il **generatore** di un PDF è la terna versione del motore,
`theme.sha256` e `tex.version_line`: un cambiamento di uno dei tre invalida i PDF già
prodotti.

### 4.4 Errori e avvisi

Ogni problema ha `severity`, `code`, `message`, `file`, `line` e `column` (specifica, §8);
`line` e `column` valgono 0 quando non si applicano. `file` è il percorso nel pacchetto;
vale `""` per un problema che non riguarda un file del pacchetto, per esempio un errore
dell'archivio intero, che non nomina mai il file ricevuto: chi chiama lo passa spesso con un
nome temporaneo. Vale `""` anche per gli errori di una sola voce dell'archivio (per esempio
`regodoc.archive.corrupt`, `.duplicate` o `.path`), che nominano la voce nel messaggio.
`severity` vale:

- `error`: il pacchetto, l'intestazione o il tema è rifiutato;
- `warning`: un problema di chi ha scritto il pacchetto che non blocca; conta come errore con
  `--strict`;
- `info`: un fatto che non dipende da chi ha scritto il pacchetto, per esempio un ruolo che il
  tema non definisce (§6.2); `--strict` non lo conta.

**Dimensioni.** Un messaggio è lungo al massimo 500 caratteri e cita le stringhe del pacchetto
accorciate a 80 caratteri. Il rapporto elenca al massimo 500 problemi, più al massimo una
voce di chiusura:

- un **errore** che arriva quando 500 problemi sono già elencati ferma la lettura con
  l'errore `regodoc.limit.problems`, che è sempre un errore e cita nel messaggio il codice e
  la posizione dell'errore che ha fermato la lettura;
- un **avviso** che arriva oltre il tetto non si elenca: la lettura prosegue, il rapporto
  conta gli avvisi omessi in `warnings_omitted` (§4.2) e chiude l'elenco con un solo avviso
  `regodoc.limit.warnings`. Un pacchetto entro i limiti resta valido per quanti avvisi abbia.

Con i campi del §4.2 per 200 file, un rapporto resta sotto 1 MiB.

**Codici.** Il codice è normativo, il testo del messaggio no. Famiglie: `regodoc.archive.*`,
`regodoc.package.*`, `regodoc.manifest.*`, `regodoc.grammar.*`, `regodoc.toml.*`,
`regodoc.xml.*`, `regodoc.text.*`, `regodoc.image.*`, `regodoc.limit.*`,
`regodoc.header.*`, `regodoc.theme.*`, `regodoc.tex.*`; fuori dalle famiglie: `regodoc.usage`,
`regodoc.environment`, `regodoc.not_implemented`, `regodoc.interrupted`,
`regodoc.internal`.

Chi chiama sceglie l'azione **prima dal codice d'uscita** (§7). I codici d'errore e d'avviso
servono a mostrare il problema; questi, e solo questi, precisano l'azione dentro lo stesso
codice d'uscita:

| Codice | Uscita | Azione |
|---|---|---|
| `regodoc.manifest.grammar_newer` | 1 | il pacchetto viene da un motore più recente: serve aggiornare la copia fissata del motore |
| `regodoc.manifest.grammar_old` | 1 | `canon` non scrive più quella grammatica: passare il pacchetto per `upgrade` (§8) |
| `regodoc.grammar.upgraded` | 0 | avviso informativo: il pacchetto è in una grammatica precedente e il motore l'ha aggiornato in memoria; per chi conserva le versioni è il segnale del «primo bisogno» (§8) |
| `regodoc.limit.time`, `regodoc.limit.memory` | 3 | non ritentare con lo stesso pacchetto |
| `regodoc.not_implemented` | 3 | la funzione non c'è in questa versione: nasconderla nell'interfaccia |

## 5. La dichiarazione (`regodoc info`)

`regodoc info` scrive su stdout un oggetto JSON, con le chiavi in ordine alfabetico:

| Chiave | Contenuto |
|---|---|
| `engine` | `"regodoc"` |
| `version` | versione del motore, PEP 440 |
| `contract` | versione corrente del contratto |
| `contracts` | le versioni del contratto supportate da `--contract` |
| `package` | `mimetype` ed `extension` del pacchetto (`application/vnd.regodoc.document`, `.regodoc`), per la firma del §3.1 |
| `grammars` | `current`, la grammatica che il motore scrive, e `read`, quelle che sa leggere, dalla più vecchia |
| `limits` | `envelope` e `content`, tabella del §5.1 |
| `resources` | `time_seconds` per comando, `memory_bytes`, `memory_enforced_on` (i sistemi dove il motore applica da sé il limite di memoria: vuoto quando `enforced` è `false`) ed `enforced` (§2.3) |
| `commands` | per ciascun comando, `ready` oppure `draft` (non ancora disponibile, codice 3) |
| `capabilities` | le capacità di questa versione (§5.2) |
| `languages` | le lingue del documento supportate |
| `passes` | `min` e `max` delle passate di pdflatex che `build` può eseguire |
| `tex` | `packages`: i pacchetti LaTeX che il motore e il tema neutro caricano |
| `theme` | `contracts`, le versioni del contratto del tema supportate; `roles`, i ruoli della tavolozza; `hooks`, gli agganci (§6); `limits`, `files` e `bytes` della cartella del tema (§3.3) |

Chi chiama legge la dichiarazione quando cambia la versione fissata del motore e la conserva.
Per esempio Rego applica `limits.envelope.compressed_bytes` all'ingresso, concede a ogni
chiamata il tempo di `resources`, abilita le funzioni dell'interfaccia secondo `commands` e
`capabilities`, e confronta `tex.packages` con la propria immagine TeX prima di aggiornare il
motore.

### 5.1 Limiti

| Chiave | Unità | Che cosa conta |
|---|---|---|
| `envelope.compressed_bytes` | byte | dimensione del file `.regodoc` |
| `envelope.expanded_bytes` | byte | byte prodotti dal decompressore, contati durante l'estrazione |
| `envelope.compression_ratio` | rapporto | byte prodotti diviso byte compressi consumati, sull'archivio intero |
| `envelope.image_compression_ratio` | rapporto | lo stesso, per ogni voce in `images/` |
| `envelope.files` | file | file nell'archivio; le voci di cartella non contano |
| `content.parts` | aperture e parti | voci di `structure.toml` |
| `content.characters` | caratteri | testo del documento, come dice il §7.2 della specifica |
| `content.part_bytes`, `structure_bytes`, `variables_bytes`, `manifest_bytes`, `readme_bytes` | byte | dimensione di ciascun file |
| `content.images`, `image_bytes`, `images_total_bytes` | immagini, byte | numero e dimensioni delle immagini |
| `content.image_side_pixels` | pixel | lato più lungo di un'immagine |
| `content.table_rows`, `table_columns`, `table_columns_normal_size` | righe, colonne | per tabella; oltre `table_columns_normal_size` il carattere si riduce in verticale |
| `content.cell_characters` | caratteri | per cella |
| `content.variables` | variabili | voci di `variables.toml` |
| `content.number_abs_max` | valore | valore assoluto massimo di un intero o di un numero delle variabili |
| `content.section_depth`, `list_depth`, `element_depth` | livelli | annidamento |
| `content.references` | rimandi e citazioni | elementi `<reference/>` e `<cite/>` |
| `content.sources` | fonti | elementi `<source>` |
| `content.href_characters` | caratteri | per `href` |
| `content.listing_line_characters` | caratteri | per riga di un `<listing>` |
| `content.problems` | problemi | elencati in un rapporto; oltre, un errore ferma la lettura con `regodoc.limit.problems` e gli avvisi si contano in `warnings_omitted` (§4.4) |

### 5.2 Capacità

Stringhe stabili; una capacità nuova è un'aggiunta compatibile.

| Capacità | Significato |
|---|---|
| `validate` | `validate` su un archivio |
| `validate.directory` | `validate` su una cartella |
| `canon` | `canon`, con `--document`, `--base-version` e `--files-dir` |
| `build.pdf`, `build.latex` | `build` nei due formati |
| `build.theme` | `build` con `--theme` |
| `upgrade` | `upgrade` |

Se il motore applica da sé i limiti di risorse non è una capacità: lo dice solo
`resources.enforced` (§2.3).

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
name = "demo"
version = "3"
theme_contract = 1
frame_keys = ["issuer", "recipient", "document_code"]
tex_packages = ["tikz", "eso-pic", "siunitx"]

[palette]
azure = "2B6CB0"
slate = "4A5560"
sage = "5E7F5A"
bronze = "8C6A2F"
plum = "6B4A6E"
brick = "9C4A3A"
olive = "6E7330"
gray = "6B6B6B"
ok = "2F6B3A"
warning = "A86B00"
critical = "A23030"
muted = "7A7A7A"
```

I colori dell'esempio sono inventati per questo documento e non sono quelli di nessun marchio.

| Chiave | Regola |
|---|---|
| `name` | `[a-z][a-z0-9-]{0,47}` |
| `version` | testo, da 1 a 32 caratteri |
| `theme_contract` | una delle versioni di `info.theme.contracts`: oggi 1 |
| `frame_keys` | le chiavi di `frame` (§3.2) che il tema stampa; una chiave usata e assente dall'intestazione stampa una stringa vuota e produce un avviso informativo |
| `tex_packages` | i pacchetti LaTeX che `theme.sty` carica oltre a quelli di `info.tex.packages` |
| `palette` | i colori, in esadecimale `RRGGBB`, per i ruoli di `info.theme.roles` |

**Pacchetti LaTeX.** L'elenco del tema è suo: non allarga quello del motore. Il motore controlla
solo i pacchetti che `theme.sty` **chiede direttamente**, con `\usepackage`,
`\RequirePackage` o `\RequirePackageWithOptions`: `regodoc.sty` li registra con l'aggancio
`package/before` di LaTeX mentre si carica `theme.sty`. Ognuno deve stare in `tex_packages`
o in `info.tex.packages`, altrimenti `build` si ferma con il codice 2 e
`regodoc.theme.package`. Le dipendenze che quei pacchetti caricano a loro volta (per esempio
`pgf` sotto `tikz`, `kvoptions` sotto `hyperref`) non contano: arrivano con il pacchetto
nell'immagine TeX. Conta solo l'estensione `.sty`; `theme.sty` non può caricare classi
(`.cls`), e i file `.tex`, `.def`, `.cfg`, `.fd` e i caratteri non si controllano per nome:
la lettura dei file resta limitata dall'ambiente del §2.2. Il file `.fls` di `-recorder`
resta per chi gestisce l'immagine TeX, che confronta lo stesso elenco con i pacchetti
installati.

### 6.2 Ruoli, non vocabolario

Il tema riceve **ruoli della tavolozza e testo già nella lingua del documento**, mai i tipi del
vocabolario del formato. È il motore a tradurre il vocabolario in ruoli: per esempio un
riquadro `warning` diventa il ruolo `warning`, un riquadro `status` il ruolo dell'accento
della parte, un'etichetta `to-verify` il ruolo `warning` con la dicitura «da verificare». Un
valore aggiunto alla grammatica viene tradotto in un ruolo esistente, quindi un'aggiunta
compatibile alla grammatica non rompe un tema.

Gli otto accenti delle parti in `structure.toml` (`azure`, `slate`, `sage`, `bronze`, `plum`,
`brick`, `olive`, `gray`) sono ruoli con lo stesso nome; `ok`, `warning`, `critical` e
`muted` servono a riquadri, etichette e toni.

Un ruolo che il tema non definisce prende il valore del tema neutro, con l'avviso informativo
`regodoc.theme.role_default`.

### 6.3 `theme.sty` e agganci

Un pacchetto LaTeX caricato dopo `regodoc.sty`. Può ridefinire solo gli agganci elencati in
`info.theme.hooks`, che `regodoc.sty` definisce con un comportamento neutro:

| Aggancio | Quando | Argomenti |
|---|---|---|
| `\RegodocThemeSetup` | fine del preambolo | — |
| `\RegodocTitlePage` | inizio del documento | — |
| `\RegodocPageStyle` | dopo il frontespizio | — |
| `\RegodocPartOpening` | inizio di ogni parte | numero romano, titolo, ruolo |
| `\RegodocOpeningStart` | inizio di ogni apertura | — |
| `\RegodocBox` | ambiente dei riquadri | ruolo, titolo nella lingua del documento (anche vuoto) |
| `\RegodocLabel` | etichetta in linea | ruolo, dicitura nella lingua del documento |

I dati arrivano al tema solo attraverso macro di sola lettura, con testo già trascritto dal
generatore:

- `\RegodocTitle`, `\RegodocSubject`, `\RegodocReference`, `\RegodocVersionLabel`,
  `\RegodocDate`;
- `\RegodocFrame{chiave}`;
- `\RegodocLanguage`;
- il colore `regodoc-<ruolo>` per ogni ruolo.

Il tema non riceve mai testo del pacchetto non trascritto e non definisce comandi che il
generatore usa per il contenuto. Il tema neutro del motore è un tema come gli altri, nella
stessa forma, e fa da esempio.

## 7. Codici d'uscita

Questa è l'unica tabella normativa dei codici d'uscita: il README e la specifica rimandano qui.

| Codice | Significato | Chi chiama… |
|---|---|---|
| 0 | esito positivo, anche con avvisi (senza `--strict`) | usa l'uscita |
| 1 | pacchetto rifiutato per errori, o per avvisi con `--strict`; l'elenco è nel rapporto | mostra gli errori a chi ha caricato il pacchetto |
| 2 | errore d'uso: argomenti, file mancante o non regolare, opzione sconosciuta, contratto non supportato, intestazione o tema sbagliati, data mancante, uscita non valida; anche un pacchetto valido che non compila con un tema esterno (`regodoc.theme.compile`), perché il difetto è del tema | corregge la chiamata o il tema: è un difetto di chi chiama |
| 3 | errore d'ambiente: TeX assente (`regodoc.tex.missing`), memoria esaurita (`regodoc.limit.memory`), cartella non scrivibile, tempo massimo superato, stdout chiuso da chi legge, comando non ancora disponibile | segnala l'ambiente; non ritenta alla cieca |
| 4 | errore interno: un'eccezione non prevista; anche un pacchetto valido che non compila con il tema neutro (`regodoc.internal`), perché il difetto è del motore | segnala un difetto del motore; non ritenta |
| 130 | interrotto | — |

## 8. Grammatiche e aggiornamento

- Il manifesto di ogni pacchetto dichiara la grammatica. Il motore legge tutte quelle in
  `grammars.read` e le porta alla corrente con una catena di aggiornatori, uno per passo
  (`rego/1` → `rego/2` → …), sempre inclusa nel motore.
- **La forma canonica di una grammatica è fissa fra le versioni del motore**: due versioni del
  motore scrivono gli stessi byte per gli stessi file di quella grammatica. Altrimenti chi
  confronta le impronte vedrebbe modifiche che nessuno ha fatto.
- `upgrade` è una funzione pura e idempotente: lo stesso ingresso dà sempre la stessa uscita,
  e aggiornare un pacchetto già nella grammatica corrente dà gli stessi byte di `canon` senza
  opzioni. `upgrade` conserva `document` e `base_version` del manifesto d'ingresso così come
  sono; chi vuole valori diversi li riscrive con `canon`. Il rapporto dice la grammatica
  ricevuta in `grammar_in` e quella d'uscita in `grammar` (§4.2). Chi conserva le versioni
  registra l'uscita come **versione nuova**, tracciata, mai come riscrittura della
  precedente.
- `canon` non aggiorna mai la grammatica: su una grammatica precedente scrive la forma
  canonica di quella grammatica, se il motore la sa ancora scrivere, altrimenti rifiuta con il
  codice 1 e l'errore `regodoc.manifest.grammar_old`, che rimanda a `upgrade`.
- `validate` e `build` accettano anche le grammatiche precedenti: aggiornano in memoria e lo
  segnalano con l'avviso informativo `regodoc.grammar.upgraded`.
- Una grammatica più nuova di `grammars.current` è rifiutata con il codice 1 e l'errore
  `regodoc.manifest.grammar_newer`. Il messaggio nomina la grammatica del pacchetto, quelle
  che il motore legge, la versione del motore e, se il manifesto ha un `generator` valido
  (§4.2), il motore che ha scritto il pacchetto.
- Le aggiunte dentro una grammatica si leggono solo dai motori che le conoscono: un motore più
  vecchio rifiuta un pacchetto che usa un elemento nato dopo di lui, come un errore di
  vocabolario.

Quando aggiornare lo decide chi conserva le versioni. In Rego è deciso (14/10/2026):

- l'aggiornamento è **automatico al primo bisogno**. Il bisogno si riconosce da ciò che il
  motore restituisce, non dal pacchetto: è la prima esportazione o la prima compilazione di
  una versione il cui `grammar`, nel rapporto (§4.2), è diverso da `info.grammars.current`.
  `build` legge anche le grammatiche precedenti, quindi senza questa regola un PDF si
  compilerebbe senza aggiornare; l'avviso `regodoc.grammar.upgraded` dice la stessa cosa a
  chi guarda solo il rapporto di `validate` o di `build`. Non c'è un comando né una rotta
  apposita per chiedere l'aggiornamento;
- Rego registra l'uscita di `upgrade` come versione nuova con origine «aggiornamento» e come
  autore chi ha chiesto l'operazione che l'ha resa necessaria;
- la versione di partenza resta com'era: l'aggiornamento non la riscrive mai.

## 9. Che cosa cambia senza cambiare il contratto

Il motore può, con una versione nuova e **senza** cambiare il numero del contratto:

- aggiungere elementi, attributi e valori alla grammatica corrente (specifica, §10);
- aprire una grammatica nuova con il suo aggiornatore;
- alzare i limiti del contenuto e le risorse dichiarate;
- aggiungere capacità, lingue, ruoli e agganci del tema, codici d'errore e d'avviso, chiavi
  nuove nel rapporto e nella dichiarazione (chi chiama ignora le chiavi che non conosce);
- cambiare l'aspetto del tema neutro;
- cambiare il numero di passate entro `passes`.

Cambiano il contratto, e richiedono una versione nuova di chi chiama:

- togliere o rinominare comandi, opzioni o chiavi;
- cambiare il significato di un codice d'uscita o di un codice d'errore;
- abbassare un limite dell'involucro;
- cambiare la forma canonica di una grammatica esistente;
- cambiare il contratto del tema in modo incompatibile (ha un proprio numero, in
  `info.theme.contracts`).

Il motore supporta la versione corrente del contratto e, per almeno una versione minore del
motore dopo un cambiamento, anche la precedente, scelta con `--contract`. La regola vale
dalla versione 1: la bozza dichiarata come versione 0 non era una versione supportata, e
`--contract 0` esce con il codice 2.

## 10. Riproducibilità

Due compilazioni dello stesso pacchetto danno lo stesso PDF, byte per byte, quando sono uguali:

- la versione del motore;
- `theme.sha256`;
- l'immagine TeX, cioè le versioni dei pacchetti TeX installati, che il rapporto di `build`
  identifica con `tex.version_line` (§4.3);
- la data del documento (§3.2) e l'intestazione;
- le opzioni di `build`.

Il motore non usa l'ora di sistema, ordina tutto ciò che scrive e azzera l'identificatore del
PDF (`\pdftrailerid{}`). La CI del motore lo prova a ogni modifica: compila due volte lo stesso
sorgente, in due cartelle diverse, sull'immagine TeX di riferimento, e confronta i byte.

## 11. Studio di autonomia

Quanto chi chiama può sostenere funzioni nuove del motore senza toccare il proprio codice, o
almeno senza toccare il proprio database.

| Cambiamento nel motore | Codice di chi chiama | Database di chi chiama |
|---|---|---|
| Elemento, attributo o valore nuovo nella grammatica | nessuno | nessuno |
| Grammatica nuova con aggiornatore | nessuno: le versioni aggiornate sono versioni nuove | nessuno: la versione del formato è un testo |
| Limiti di contenuto più alti | nessuno: non li applica | nessuno |
| Limite dell'involucro più alto | nessuno se legge `compressed_bytes` da `info` | nessuno |
| Lingua nuova del documento | nessuno | nessuno |
| Capacità nuova (per esempio un formato d'uscita) | l'interfaccia la mostra se la conosce; altrimenti la ignora | nessuno |
| Passate di compilazione in più | nessuno: il tempo concesso viene da `resources` | nessuno |
| Pacchetto LaTeX nuovo nel motore | nessuno; l'immagine TeX sì, e `tex.packages` lo rivela prima dell'aggiornamento | nessuno |
| Ruolo o aggancio nuovo nel tema | nessuno: il tema di chi chiama prende il valore neutro, con un avviso informativo | nessuno |
| Contratto nuovo | sì, il modulo che chiama il motore | nessuno |
| Contratto del tema nuovo | sì, il tema | nessuno |

Il database di chi chiama conserva i pacchetti in forma generica: file con impronte, versione
del formato, storia delle versioni. Nessun suo vincolo conosce il vocabolario, quindi nessuna
tabella cambia schema per un'evoluzione del formato.

**Ciclo di vita, per chi chiama.**

- **Copia fissata del motore.** Chi chiama installa una versione precisa da un wheel con le
  impronte (`pip install --require-hashes`) e legge `info` a ogni cambio di versione.
  Tornare alla versione precedente (rollback) è possibile finché i pacchetti già salvati non
  usano una grammatica o un'aggiunta che la versione precedente non legge: prima di tornare
  indietro, chi chiama verifica con `validate` della versione precedente le versioni
  correnti dei propri documenti.
- **Aggiornamento di grammatica.** Lo avvia chi chiama, quando decide (§8). L'uscita è una
  versione nuova; la versione di partenza resta nella storia.
- **Conflitti dopo un aggiornamento.** Un pacchetto esportato prima dell'aggiornamento torna
  con una `base_version` più vecchia della corrente. Chi chiama lo aggiorna con `upgrade` e
  poi confronta i file con quelli della versione aggiornata, come per ogni altra modifica
  concorrente: l'aggiornamento non conta come modifica dell'autore, perché la forma canonica
  di una grammatica è fissa. Per confrontare i file chi chiama usa le impronte che restituisce
  `canon` (o `upgrade`), cioè dei file in forma canonica, **non quelle di `validate`**, che
  descrivono i file così come sono arrivati: un autore che ha solo cambiato i rientri
  avrebbe impronte diverse senza aver cambiato niente.
- **PDF già prodotti.** Cambiano generatore quando cambia la versione del motore,
  `theme.sha256` o `tex.version_line` (§4.3): chi li conserva li segna come da rigenerare.
- **Spazio.** Ogni versione aggiunge solo i file cambiati, se chi chiama li conserva per
  impronta; il tetto di un pacchetto è quello dell'involucro (§5.1).

Restano comunque di chi chiama, qualunque cosa faccia il motore: i documenti e le colonne di
titolo, oggetto e riferimento come proiezione; quali tipi di documento ammettono un pacchetto;
permessi, rotte e interfaccia; la logica dei conflitti sulle impronte; i PDF generati e il loro
archivio; il tema di marchio; l'immagine TeX e i controlli all'ingresso del §3.1.
