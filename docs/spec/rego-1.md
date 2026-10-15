# Formato `.regodoc`, grammatica `rego/1`

Stato: **bozza per l'approvazione**, ottobre 2026. Diventa normativa quando è approvata in
blocco, dopo la lettura avversaria dei paragrafi 6 e 7.

Questa specifica descrive che cosa può contenere un pacchetto `.regodoc`, come si scrive e
come lo legge il motore `regodoc`. **Tutto ciò che non è descritto qui è un errore**: il
motore non indovina e non lascia passare testo che non capisce.

La specifica sostituisce la bozza del 12/10 con i nomi italiani, che non è mai stata
rilasciata. La corrispondenza fra i nomi della bozza e quelli di `rego/1` è
nell'[appendice A](#appendice-a-corrispondenza-dei-nomi); l'[appendice B](#appendice-b-decisioni-applicate)
elenca dove è applicata ciascuna decisione. «Decisione N» indica una delle decisioni sul
formato verificate una per una il 12/10/2026; «decisione AN» uno dei punti aperti chiusi lo
stesso giorno.

## 0. Convenzioni

- **Deve**, **non può** ed **è un errore** indicano regole che il motore verifica e che
  bloccano il pacchetto. **Avviso** indica un problema segnalato che non blocca, salvo con
  `--strict` (§8).
- **Lingua dei nomi.** Tutto ciò che legge la macchina è in inglese: nomi di file e cartelle
  del pacchetto, elementi e attributi XML, chiavi TOML, valori chiusi, codici d'errore. Sono
  in italiano, o nella lingua del documento, solo i contenuti scritti dall'autore e i
  messaggi d'errore del motore. Restano invariati i nomi `mimetype`, `manifest.json` e
  l'estensione `.regodoc`.
- **Unità.** 1 KiB = 1024 byte; 1 MiB = 1024 KiB. I «caratteri» sono punti di codice
  Unicode.
- **NFC.** Il testo deve essere già in forma normalizzata NFC: il motore non normalizza. Un
  carattere combinante, come un accento scritto separato dalla sua lettera, è un errore
  (§5.2).
- **Codici.** Ogni errore e avviso ha un codice (§8). Il codice è normativo, il testo del
  messaggio no: il messaggio può migliorare da una versione all'altra del motore.
- **Posizioni.** Righe e colonne contano da 1. La colonna conta i caratteri, non i byte.
- **Espressioni regolari.** Le forme come `[a-z][a-z0-9-]{0,47}` valgono sull'intero valore,
  dall'inizio alla fine, e solo con caratteri ASCII.

---

## 1. Il pacchetto

### 1.1 Disposizione

Un `.regodoc` è un archivio ZIP con questi file e nessun altro:

| Percorso | Obbligatorio | Chi lo scrive | Contenuto |
|---|---|---|---|
| `mimetype` | sì | il motore | il tipo del pacchetto (§1.2), prima voce dell'archivio |
| `manifest.json` | sì | il motore | la busta: formato, grammatica, documento, versione di partenza, impronte (§1.3) |
| `README.md` | no | il motore | istruzioni per chi modifica il pacchetto; ignorato in lettura (§1.4) |
| `structure.toml` | sì | l'autore | intestazione, lingua, ordine e attributi delle parti (§2) |
| `variables.toml` | no | l'autore | valori nominati (§3) |
| `parts/<id>.xml` | almeno uno | l'autore | il testo: un file per apertura o per parte (§4) |
| `images/<nome>.png`, `.jpg` o `.jpeg` | no | l'autore | figure (§4.5) |

Sono ammesse anche le voci di cartella `parts/` e `images/`, vuote; non contano nel limite dei
200 file (§7.1). Qualunque altra voce è un errore, comprese quelle che i sistemi operativi
aggiungono da soli (`__MACOSX/`, `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`): il messaggio
d'errore lo dice e suggerisce `regodoc canon` per ricostruire l'archivio.

Il file di una parte **si ricava dal suo id**: la parte `network` sta in `parts/network.xml`.
Un file in `parts/` che non corrisponde a nessun id di `structure.toml` è un errore, e così un
id senza file.

### 1.2 `mimetype`

La prima voce dell'archivio deve chiamarsi `mimetype`, essere memorizzata senza
compressione, cominciare all'inizio del file, non avere campo extra né descrittore di dati e
contenere esattamente i byte ASCII

```
application/vnd.regodoc.document
```

senza a capo finale. Così il valore sta sempre all'offset 38 del file, e un programma
qualunque riconosce un `.regodoc` leggendo i primi byte. Il motore legge il contenuto subito
dopo aver controllato la prima voce (§6.1, passo 4): un archivio con un'altra prima voce, o
con un contenuto diverso, è rifiutato prima di leggere il resto.

### 1.3 `manifest.json`

Un oggetto JSON in UTF-8, al massimo 64 KiB, con queste chiavi e nessun'altra:

```json
{
  "format": "regodoc",
  "grammar": "rego/1",
  "document": "doc-2026-0042",
  "base_version": "sha256:9f2c…",
  "files": {
    "structure.toml": "sha256:4a1d…",
    "parts/network.xml": "sha256:77b0…"
  },
  "generator": { "engine": "regodoc", "version": "0.1.0" }
}
```

| Chiave | Obbligatoria | Regola |
|---|---|---|
| `format` | sì | esattamente `"regodoc"` |
| `grammar` | sì | una grammatica che il motore sa leggere (§10) |
| `document` | no | identificatore del documento presso chi ha esportato il pacchetto, `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` |
| `base_version` | no | la versione da cui il pacchetto è stato esportato: `sha256:` seguito da 64 cifre esadecimali minuscole. Per il motore è un'impronta opaca, scelta da chi esporta, e verificata solo nella forma. Chi conserva le versioni ci scrive `files_sha256` della versione esportata (contratto, §4.2) |
| `files` | no | per ogni file del pacchetto tranne `mimetype` e `manifest.json`, l'impronta al momento dell'esportazione, nella stessa forma |
| `generator` | no | `engine` e `version` del motore che ha scritto il pacchetto, testo puro di al massimo 64 caratteri |

Le impronte servono a chi riceve il pacchetto modificato per capire che cosa è cambiato
rispetto all'esportazione. **Non sono un controllo d'integrità**: l'autore modifica i file e
le impronte smettono di coincidere, com'è normale. Chi importa ricalcola le impronte dai byte
letti e usa del manifesto solo `base_version`, dopo averla cercata fra le proprie versioni
(decisione 13 del 12/10: Rego ricalcola tutto e del manifesto legge solo il riferimento alla
versione di partenza).

Sono errori: chiavi ripetute, chiavi non previste, valori di tipo sbagliato, `NaN` e
`Infinity`, un percorso in `files` che non è un file ammesso dal §1.1.

### 1.4 `README.md`

Il motore lo genera a ogni esportazione, nella lingua del documento, con le istruzioni per
modificare il pacchetto e rimetterlo insieme. In lettura il suo contenuto è ignorato: conta
solo per i limiti dell'involucro (§7.1) e per il proprio limite di 64 KiB (§7.2).

### 1.5 Nomi

| Che cosa | Forma |
|---|---|
| id di aperture, parti, sezioni e fonti | `[a-z][a-z0-9-]{0,47}` |
| nome di un'immagine, senza estensione | `[a-z0-9][a-z0-9-]{0,63}` |
| estensione di un'immagine | `.png`, `.jpg` o `.jpeg`, in minuscolo |
| nome di una variabile | `[a-z][A-Za-z0-9]{0,47}` (camelCase) |

Un id o un nome d'immagine non può finire con `-`, non può contenere `--` e non può essere un
nome riservato di Windows (`con`, `prn`, `aux`, `nul`, da `com1` a `com9`, da `lpt1` a
`lpt9`): così ogni nome è un nome di file sicuro su ogni sistema (decisione 27).

### 1.6 Cartella

Chi scrive può lavorare su una cartella con la stessa disposizione, senza archiviarla: il
motore la accetta in `validate`, e `regodoc canon` la trasforma nell'archivio canonico. In una
cartella valgono le stesse regole su nomi, disposizione e limiti, tranne quelle proprie
dell'archivio ZIP. Collegamenti simbolici e file speciali sono errori. I file che i sistemi
operativi aggiungono da soli (`__MACOSX/`, `.DS_Store`, `._*`, `Thumbs.db`, `desktop.ini`)
sono ignorati con l'avviso `regodoc.package.system_file`. Chi riceve pacchetti da altri, come
Rego, accetta solo archivi.

---

## 2. `structure.toml`

Dati semplici e nient'altro: nessun testo formattato, nessun richiamo a variabili.

```toml
language = "it"
toc = true

[header]
title = "Rinnovo della rete della Cantina Colle Rovere"
subject = "Analisi dello stato attuale e proposta"
reference = "CR-2026-07"
date = 2026-10-05
version_label = "Bozza 0.3"

[[opening]]
id = "summary"

[[part]]
id = "network"
title = "Rete e collegamenti"
accent = "azure"

[[part]]
id = "backup"
title = "Copie di sicurezza"
accent = "sage"
```

| Chiave | Dove | Obbligatoria | Regola |
|---|---|---|---|
| `language` | radice | no | lingua del documento: `it` (predefinita) o `en` (§5.6) |
| `toc` | radice | no | booleano; `true` stampa l'indice; predefinito `false` |
| `header` | radice | sì | tabella con l'intestazione del documento |
| `title` | `header` | sì | testo puro, da 1 a 200 caratteri |
| `subject` | `header` | no | testo puro, da 1 a 200 caratteri |
| `reference` | `header` | no | testo puro, da 1 a 80 caratteri |
| `date` | `header` | no | data TOML senza ora, `AAAA-MM-GG` |
| `version_label` | `header` | no | dicitura libera stampata nel PDF, testo puro da 1 a 40 caratteri |
| `opening` | radice | no | zero o più aperture, nell'ordine in cui compaiono |
| `part` | radice | sì | una o più parti, nell'ordine in cui compaiono |
| `id` | `opening`, `part` | sì | id (§1.5), unico nel documento (§4.6) |
| `title` | `part` | sì | testo puro, da 1 a 200 caratteri |
| `accent` | `part` | sì | uno degli otto ruoli della tavolozza: `azure`, `slate`, `sage`, `bronze`, `plum`, `brick`, `olive`, `gray` |

Titolo, oggetto e riferimento sono la **fonte di verità** dell'intestazione: chi importa il
pacchetto li copia nei propri campi a ogni importazione, come proiezione (decisione 20). Se
`subject` o `reference` mancano, Rego scrive nei propri campi la stringa vuota.
`version_label` vive solo nel PDF.

`[header]` prevale sempre. L'intestazione in JSON che chi chiama passa a `build`
(`docs/contract.md`, §3.2) porta solo i dati della cornice del tema e la data di ripiego; non
può cambiare titolo, oggetto, riferimento né data del pacchetto.

`date` è la data del documento: dà la data stampata e l'istante usato per rendere il PDF
riproducibile. In ordine:

1. `header.date` del pacchetto; l'istante è la mezzanotte UTC di quella data;
2. altrimenti l'**istante** `document_created` dell'intestazione JSON, così com'è: l'istante
   di creazione del documento (decisione A4);
3. altrimenti `SOURCE_DATE_EPOCH` dell'ambiente, se chi chiama l'ha impostata; è ignorata
   quando uno dei due valori precedenti c'è, e allora non si controlla nemmeno la sua forma;
4. altrimenti `build` si ferma con un errore d'uso (codice 2).

Dall'istante alla data stampata:

- `document_created` è scritto in RFC 3339 con il proprio fuso; la data stampata è il giorno
  di calendario **in quel fuso**, senza conversioni: `2026-10-06T00:30:00+02:00` stampa
  6 ottobre 2026, anche se in UTC è ancora il 5;
- `SOURCE_DATE_EPOCH` è un numero intero **non negativo**, scritto con sole cifre, di
  secondi dal 1° gennaio 1970 UTC, senza fuso; la data stampata è il giorno di calendario
  **in UTC**. `1791237600` (2026-10-05T22:00:00Z) stampa 5 ottobre 2026, anche dove in quel
  momento è già il 6. Un valore negativo è malformato;
- un valore che non rispetta queste forme è un errore d'uso (codice 2), non un ripiego al
  passo successivo.

Un'apertura è un capitolo senza numero e senza titolo proprio, prima delle parti: per esempio
una sintesi. Le parti hanno un numero romano che **non si scrive**: deriva dall'ordine.

L'accento nomina un ruolo, non un colore: il valore lo decide il tema (decisione 9). Un nome
sconosciuto è un errore.

Una chiave non prevista è un errore. I commenti `#` sono ammessi ma si perdono nella forma
canonica, e il motore lo segnala con un avviso.

---

## 3. `variables.toml`

Ogni variabile è una riga: un nome e una tabella in linea con **una sola** chiave di tipo,
più `note` facoltativa.

```toml
contactOffice = { text = "Ufficio tecnico della cantina" }
restoreHours = { hours = 6 }
backupCapacity = { tb = "4" }
workstations = { count = 14 }
installDays = { days = [10, 14] }
wifiCoverage = { percent = "72,5" }
maintenanceFee = { eur = ["320", "410"], note = "stima interna da confermare con l'installatore" }
worksStart = { date = 2026-11-16 }
```

Un nome di variabile (§1.5) è unico. Le variabili sono di un solo documento: non esistono
variabili condivise fra documenti (decisione 5). Non esistono formule né variabili calcolate
(decisione 6).

### 3.1 Tipi

| Tipo | Valore | Negativi ammessi | Resa in italiano | Resa in inglese |
|---|---|---|---|---|
| `date` | data TOML senza ora | — | 30 settembre 2026 | 30 September 2026 |
| `gb`, `tb` | numero italiano (stringa) | no | `2.310,75 GB`, in carattere monospaziato | `2,310.75 GB` |
| `count` | intero | no | `96.418`, monospaziato | `96,418` |
| `number` | intero, oppure numero italiano | sì | `6`, `3,5` | `6`, `3.5` |
| `percent` | numero italiano | sì | `61,2%` | `61.2%` |
| `eur` | numero italiano, al massimo due decimali | sì | `2.140 euro`, `11,40 euro` | `EUR 2,140`, `EUR 11.40` |
| `hours`, `days`, `months` | intero, oppure numero italiano | no | `30 giorni`, `1 giorno` | `30 days`, `1 day` |
| `text` | testo puro, da 1 a 500 caratteri | — | così com'è | così com'è |

Interi e numeri italiani non possono superare 10^15 in valore assoluto.

**Numero italiano.** Una stringa che rispetta `-?(0|[1-9]\d{0,2}(\.\d{3})*)(,\d+)?`: il
punto separa sempre le migliaia, ed è obbligatorio da 1.000 in su; la virgola separa sempre i
decimali. Il primo gruppo non ha zeri iniziali, salvo lo `0` da solo, che non è mai seguito
da gruppi: `"0,5"` va bene, `"007"` e `"0.012"` sono errori. Così `"1.084"` vale
milleottantaquattro, senza ambiguità.
I numeri TOML a virgola mobile, come `87.4`, sono un errore: si perderebbe la precisione
scritta. I valori si scrivono sempre all'italiana, qualunque sia la lingua del documento; la
resa segue la lingua (§5.6).

**Intervallo.** Lo stesso tipo con un array di due valori: `{ eur = ["320", "410"] }`. Il
primo non può superare il secondo. Si rende `320–410 euro`, con l'unità una volta sola.
Ammesso per tutti i tipi tranne `date` e `text`.

**Euro.** Gli importi sono editoriali: testo validato e formattato, mai collegato alla
contabilità (decisione 7). Il motore li converte in centesimi interi solo per validarli e
formattarli: senza decimali se i centesimi sono zero, altrimenti con due.

**Singolare.** Per `hours`, `days` e `months` prende l'unità al singolare solo il valore
scritto `1` o `"1"`: `"1,0"` resta al plurale. Un intervallo è sempre al plurale.

**`note`.** Testo puro, da 1 a 500 caratteri: la provenienza del valore. Non si stampa mai.
I commenti `#` invece si perdono, con un avviso (decisione 11): la provenienza va in `note`.

### 3.2 Richiamo

Nel testo XML: `<var name="backupCapacity"/>`. L'attributo facoltativo `form` sceglie che cosa
stampare:

| `form` | Ammesso per | Stampa |
|---|---|---|
| assente | ogni tipo | il valore completo, con l'unità |
| `number` | tipi numerici | il numero senza unità |
| `min`, `max` | intervalli | un estremo, con l'unità |

Un richiamo a una variabile che non esiste è un errore. Una variabile mai richiamata produce
un avviso.

---

## 4. Le parti in XML

Il formato delle parti è XML a vocabolario chiuso (decisione 24).

### 4.1 Forma del file

```xml
<?xml version="1.0" encoding="UTF-8"?>
<part>
  <summary>…</summary>
  <section id="…">…</section>
</part>
```

- Codifica UTF-8, senza BOM. La dichiarazione XML è facoltativa e, se c'è, deve essere
  esattamente quella dell'esempio, in testa al file.
- La radice è `<part>` per le parti e `<opening>` per le aperture, secondo come l'id compare
  in `structure.toml`. `<opening>` non ha `<summary>`.
- Nessuno spazio dei nomi, nessun `DOCTYPE`, nessuna entità, nessuna istruzione di
  elaborazione, nessuna sezione `CDATA` (§6.3).
- Prima e dopo la radice sono ammessi solo spazi bianchi.

### 4.2 Blocchi

| Elemento | Dove può stare | Contenuto | Attributi |
|---|---|---|---|
| `<summary>` | primo figlio di `<part>`, facoltativo | testo misto | — |
| `<section>` | in `<part>`, `<opening>`, `<section>` | `<title>`, poi blocchi e sezioni | `id` facoltativo |
| `<title>` | primo figlio di `<section>`, obbligatorio | testo misto senza `<link>`, `<reference>`, `<cite>` e `<break>` | — |
| `<p>` | dove è ammesso un blocco | testo misto | — |
| `<list>` | dove è ammesso un blocco; in `<item>` | uno o più `<item>` | `type`: `bullet` (predefinito) o `numbered` |
| `<item>` | in `<list>` | testo misto, poi al massimo una `<list>` | — |
| `<box>` | dove è ammesso un blocco | `<p>` e `<list>` | `type`: `status`, `note`, `warning`, `critical`; obbligatorio |
| `<small>` | dove è ammesso un blocco | `<p>` e `<list>` | — |
| `<table>` | dove è ammesso un blocco | §4.4 | `columns`, obbligatorio; `orientation` facoltativo |
| `<figure>` | dove è ammesso un blocco | `<caption>` facoltativa | `file`, obbligatorio; `width` facoltativo |
| `<listing>` | dove è ammesso un blocco | solo testo, spazi conservati | — |
| `<sources>` | dove è ammesso un blocco, al massimo una volta nel documento | solo `<group>` oppure solo `<source>` | `id` facoltativo |

«Dove è ammesso un blocco» vuol dire: in `<part>`, `<opening>` e `<section>`, dopo il
`<summary>` o il `<title>`. Testo non bianco fra un blocco e l'altro è un errore.

Dentro `<part>`, `<opening>` e `<section>` i blocchi vengono prima delle sezioni figlie: dopo
la prima sezione figlia vengono solo altre sezioni. A stampa, un blocco dopo una sottosezione
sembrerebbe far parte della sottosezione.

**Blocco di testo misto.** Sono blocchi di testo misto `<p>`, `<summary>`, `<title>`,
`<caption>`, il testo di `<item>` prima dell'eventuale elenco annidato, e `<cell>` quando
contiene testo e non blocchi. Il contenuto di un blocco di testo misto è testo, con gli
elementi in linea del §4.3. Le regole del §5.3 si applicano per blocco: le virgolette si
appaiano dentro lo stesso blocco, compresi gli elementi in linea che contiene, salvo
`<code>`.

`<p>`, `<summary>`, `<title>`, `<item>`, `<caption>` e gli elementi in linea con contenuto
(`<b>`, `<i>`, `<tone>`, `<link>`, `<code>`) non possono essere vuoti. Una cella può esserlo.

Le sezioni si annidano al massimo su tre livelli: sezione, sottosezione,
sotto-sottosezione. Il livello del titolo **deriva dall'annidamento** e non si può saltare;
una quarta sezione annidata è un errore (decisione 28). Gli elenchi si annidano al massimo su
tre livelli.

`<box>` e `<small>` contengono solo paragrafi ed elenchi, non si annidano fra loro e non
contengono tabelle, figure, listati o fonti (decisione 29).

Significato dei riquadri: `status` è il riquadro informativo nel colore della parte; `note`
è un'osservazione neutra; `warning` richiama l'attenzione; `critical` segnala un rischio
grave. I colori li decide il tema.

### 4.3 Testo misto

| Elemento | Contenuto | Attributi | Resa |
|---|---|---|---|
| `<b>` | testo misto | — | grassetto |
| `<i>` | testo misto | — | corsivo |
| `<code>` | solo testo | — | monospaziato; virgolette dritte e trattini restano come sono |
| `<var/>` | vuoto | `name`; `form` facoltativo | il valore formattato (§3.2) |
| `<label/>` | vuoto | `type`: `observed`, `declared`, `decided`, `proposed`, `to-verify`, `critical` | l'etichetta colorata con la dicitura nella lingua del documento |
| `<tone>` | testo misto | `type`: `critical`, `warning`, `ok`, `muted` | testo colorato in grassetto |
| `<link>` | testo misto senza `<link>` | `href` | collegamento |
| `<address>` | solo testo | — | dominio stampato senza collegamento, oppure indirizzo email con collegamento `mailto:` |
| `<reference/>` | vuoto | `to`; `through` facoltativo | «Parte VII», «Parti IV–VII», oppure il titolo di una sezione |
| `<cite/>` | vuoto | `to` | «[12]», con collegamento alla voce nell'elenco delle fonti |
| `<break/>` | vuoto | — | a capo forzato |

Regole:

- `<b>` dentro `<b>`, `<i>` dentro `<i>` e `<tone>` dentro `<tone>` sono errori, a qualunque
  profondità.
- `href` comincia con `https://`, ha un nome di host, non contiene credenziali (`@` prima
  dell'host), spazi o caratteri fuori dall'ASCII stampabile, ed è lungo al massimo 2.000
  caratteri. Un dominio internazionale si scrive nella forma `xn--`. `http://`, `mailto:` e
  ogni altro schema sono errori (decisione 23).
- `<address>` ammette solo `[A-Za-z0-9.@_-]`. Con `@` deve essere un indirizzo email valido;
  senza `@` deve essere un nome di dominio con almeno un punto, etichette da 1 a 63
  caratteri, nessuna etichetta che comincia o finisce con `-`. A capo e tabulazione dentro
  `<address>` sono errori (§5.1).
- La legenda delle etichette si genera da sola all'inizio del documento se almeno
  un'etichetta è usata. Le diciture seguono la lingua del documento (decisione 8).

### 4.4 Tabelle

```xml
<table columns="* 2.2cm 2.6cm">
  <head>
    <cell>Archivio</cell>
    <cell>Dove</cell>
    <cell>Copia</cell>
  </head>
  <row>
    <cell>
      <p>Etichette e grafica:</p>
      <list>
        <item>file di stampa;</item>
        <item>fotografie delle annate.</item>
      </list>
    </cell>
    <cell>portatile grafico</cell>
    <cell><tone type="critical">nessuna</tone></cell>
  </row>
  <separator/>
  <row type="total">
    <cell span="2">Capacità del nuovo disco</cell>
    <cell><var name="backupCapacity"/></cell>
  </row>
</table>
```

- `columns`: una voce per colonna, separate da uno spazio. `*` è una colonna che si allarga;
  una misura come `1.8cm` è una colonna fissa, da `0.5cm` a `12cm`, con il punto decimale, al
  massimo due decimali e solo l'unità `cm`. Almeno una colonna è `*`. Al massimo 10 colonne.
- `orientation` vale `portrait`, il predefinito, oppure `landscape`, che mette la tabella su
  pagine orizzontali; `landscape` è ammesso con qualunque numero di colonne.
- **Oltre le otto colonne**, cioè con nove o dieci, la tabella si stampa in carattere ridotto
  se è verticale, in carattere normale se è orizzontale.
- `<head>`: facoltativa, al massimo una, prima di ogni riga. Contiene solo `<cell>`. Si
  ripete in cima a ogni pagina se la tabella continua.
- `<row>`: almeno una. `type="total"` la rende in grassetto. `<separator/>` traccia un filetto
  fra due righe; non può stare in testa, in coda o accanto a un altro `<separator/>`.
- **Una cella contiene testo misto oppure blocchi (`<p>`, `<list>`), mai entrambi**
  (decisione 29). Testo sciolto accanto a un `<p>` è un errore.
- `span="n"`, con n da 2 al numero di colonne: la cella occupa n colonne. Ogni riga e
  l'intestazione devono coprire esattamente il numero di colonne dichiarato.
- Al massimo 600 righe e 2.000 caratteri per cella.

### 4.5 Figure e listati

```xml
<figure file="images/rack-layout.png" width="0.8">
  <caption>Disposizione prevista dell'armadio di rete dal <var name="worksStart"/>.</caption>
</figure>
```

- `file` è il percorso completo dell'immagine nel pacchetto, in `images/`, e il file deve
  esistere. Sono ammessi solo PNG e JPEG (decisione 15).
- `width` è una frazione della larghezza del testo: un numero da `0.1` a `1`, con il punto e
  al massimo due decimali. Se manca vale `1` (decisione 32). Il punto, e non la virgola,
  perché è un parametro tecnico come le misure delle colonne, non un valore stampato.
- `<caption>`: testo misto senza `<break/>`.
- Le figure si numerano da sole («Figura 3.», «Figure 3.») nell'ordine del documento.
- Un'immagine del pacchetto mai usata produce un avviso.

`<listing>` conserva spazi e a capo così come sono. Un a capo subito dopo `<listing>` e uno
subito prima di `</listing>` si ignorano. I caratteri `<` e `&` si scrivono `&lt;` e `&amp;`.
Le tabulazioni sono un errore: la loro larghezza non è definita. Righe lunghe al massimo 200
caratteri.

### 4.6 Identificatori e rimandi

- Gli id di aperture e parti (in `structure.toml`), di sezioni, di `<sources>` e di fonti
  condividono un unico spazio: un id ripetuto nel documento è un errore.
- Una sezione ha un id solo se è scritto: il motore non lo ricava dal titolo (decisione 23).
- Le aperture non hanno numero: la prima parte è la Parte I anche quando la precedono una o
  più aperture. Nell'esempio del §11, `<reference to="network"/>` rende «Parte I»; con
  `through="backup"` rende «Parti I–II»: `through` è ammesso solo fra due parti, e la seconda
  deve venire dopo la prima.
- Verso una sezione rende il suo titolo fra virgolette, seguito dalla parte se è un'altra:
  dalla parte `backup`, `<reference to="wifi"/>` rende «Copertura senza fili» (Parte I).
- Un rimando verso un id inesistente, verso un'apertura, verso l'elenco `<sources>` o verso
  una fonte è un errore. Le fonti si citano con `<cite/>`.
- Riordinare le parti aggiorna da solo tutti i numeri.

### 4.7 Fonti

```xml
<sources id="sources">
  <group title="Documentazione dei produttori">
    <source id="ap-guide" href="https://docs.example.com/ap/installazione" publisher="Example Networks" accessed="2026-09-10">Guida all'installazione dei punti di accesso</source>
    <source href="https://docs.example.com/nas/copie" publisher="Example Storage">Copie pianificate sul NAS</source>
  </group>
</sources>
```

- `<sources>` è un blocco, al massimo uno nel documento, in qualunque parte o apertura.
  Contiene solo `<group>` oppure solo `<source>`, non mescolati, e almeno uno.
- `<group>`: attributo `title` obbligatorio, testo puro da 1 a 200 caratteri; contiene una o
  più `<source>`. Nel PDF il titolo del gruppo è un sottotitolo.
- `<source>`: il contenuto è il titolo della fonte, testo puro da 1 a 500 caratteri.
  Attributi: `href` obbligatorio, con le regole del §4.3; `publisher` obbligatorio, testo puro
  da 1 a 200 caratteri; `accessed` facoltativo, data `AAAA-MM-GG`; `id` facoltativo, ma
  obbligatorio se la fonte è citata.
- Le fonti si numerano da sole nell'ordine dell'elenco. `<cite to="ap-guide"/>` rende «[1]»
  con un collegamento alla voce. Una citazione verso un id inesistente o che non è di una
  fonte è un errore; una fonte mai citata va bene (decisione 30). Il titolo dell'elenco,
  «Fonti» o «Sources», segue la lingua del documento.
- Le citazioni numerate richiedono una passata di compilazione in più, che il motore dichiara.

### 4.8 Commenti

I commenti XML (`<!-- … -->`) sono conservati (decisione 31):

- sono ammessi dove il contenuto è fatto di elementi: fra i blocchi, fra le voci di un
  elenco, fra le righe e le celle di una tabella, fra le fonti;
- un commento dentro il testo misto, in `<code>` o in `<listing>` è un errore;
- un commento appartiene all'elemento che lo segue, oppure alla fine dell'elemento che lo
  contiene se nessun elemento lo segue, e la forma canonica lo rimette lì;
- non finiscono mai nel PDF; contano come modifica nel confronto fra versioni e restano nel
  pacchetto incluso nello ZIP di emissione;
- il loro testo segue le regole sui caratteri del §5.2, a capo compresi.

---

## 5. Regole sul testo

### 5.1 Spazi, a capo e tabulazioni

Nel testo misto ogni sequenza di spazi, tabulazioni e a capo vale un solo spazio, e gli spazi
all'inizio e alla fine di un blocco si ignorano: rientri e a capo nel file non cambiano nulla
nel PDF. Lo spazio non separabile (U+00A0) resta tale.

| Contesto | A capo | Tabulazione |
|---|---|---|
| testo misto (§4.2) | ammesso, vale uno spazio | ammessa, vale uno spazio |
| `<code>` | ammesso, vale uno spazio | errore |
| `<listing>` | ammesso e conservato | errore |
| commenti XML | ammesso | errore |
| contenuto di `<source>` | ammesso, vale uno spazio | errore |
| contenuto di `<address>` | errore (`regodoc.text.char`) | errore (`regodoc.text.char`) |
| attributi XML | l'XML li riduce a uno spazio prima di ogni controllo | come l'a capo |
| testo puro in TOML | errore | errore |

### 5.2 Caratteri

Il testo, gli attributi e i valori TOML sono in Unicode normalizzato NFC. Sono ammessi solo:

| Insieme | Punti di codice |
|---|---|
| ASCII stampabile | U+0020–U+007E |
| a capo e tabulazione, solo dove il formato li ammette | U+000A, U+0009 |
| Latin-1 | U+00A0–U+00FF, escluso U+00AD (trattino morbido) |
| Latin Extended-A | U+0100–U+017F, escluso U+0149 |
| simboli tipografici | – U+2013, — U+2014, ‘ U+2018, ’ U+2019, “ U+201C, ” U+201D, … U+2026, • U+2022, € U+20AC, ⇒ U+21D2 |
| simboli tecnici | ≤ U+2264, ≥ U+2265, → U+2192, − U+2212 (segno meno) |

Un carattere fuori elenco, per esempio un emoji, un carattere di controllo, un carattere di
controllo bidirezionale o un carattere combinante, è un errore con la sua posizione
(`regodoc.text.char`): bloccherebbe la compilazione o nasconderebbe il testo a chi rilegge.

### 5.3 Tipografia

| Conversione | Dove vale | Dove no |
|---|---|---|
| `--` diventa il trattino breve –; tre o più trattini sono un errore, la lineetta — si scrive direttamente | blocchi di testo misto; testo puro di TOML, attributi e `<source>` | `<code>`, `<listing>` |
| `"` a coppie diventano “ ”; un numero dispari è un errore (decisione 32) | per blocco di testo misto; per singolo valore di testo puro | `<code>`, `<listing>`, che non contano per le coppie |
| `'` diventa ’ | blocchi di testo misto; testo puro | `<code>`, `<listing>` |

Il codice dell'errore dipende dal testo, non dalla regola:

- nel **testo misto** i trattini danno `regodoc.text.dashes` e le virgolette dispari
  `regodoc.text.quotes`;
- nel **testo puro** (i valori di testo di `structure.toml` e di `variables.toml`, compresa
  `note`; gli attributi `title` di `<group>` e `publisher` di `<source>`; il titolo di una
  fonte) ogni problema del valore dà `regodoc.text.plain`: testo vuoto, troppo lungo,
  virgolette dispari, tre o più trattini. Il messaggio dice quale.

Un carattere fuori elenco è sempre `regodoc.text.char` (§5.2), in ogni contesto, anche
quando è scritto con una sequenza di escape TOML o con un riferimento a carattere.

### 5.4 Riferimenti a caratteri

Sono ammessi solo i cinque riferimenti predefiniti (`&lt;` `&gt;` `&amp;` `&quot;` `&apos;`) e
quelli numerici (`&#160;`, `&#xA0;`). Il carattere che ne risulta segue le regole del §5.2. La
forma canonica li riporta a caratteri normali, tranne `&lt;` e `&amp;`, che sono
indispensabili, e `&gt;` subito dopo `]]`: la sequenza `]]>` non può stare nel testo XML, e
capita davvero in un `<listing>` o in un `<code>` (per esempio `a[b[0]]>1`).
Fuori da quel caso `>` si scrive così com'è.

### 5.5 Trascrizione

Il testo del pacchetto non passa mai al LaTeX così com'è: ogni carattere è trascritto dal
generatore, e nessuna macro riceve nomi o comandi dal pacchetto.

### 5.6 Lingua del documento

`language` in `structure.toml` sceglie la lingua delle parole che il motore stampa da sé:
legenda delle etichette, «Fonti», «Figura», «Parte», nomi dei mesi e delle unità, e la
sillabazione. Sceglie anche come si stampano i numeri: in italiano `2.310,75`, in inglese
`2,310.75`. Il testo dell'autore non viene tradotto, e i valori in `variables.toml` si
scrivono sempre all'italiana.

---

## 6. Sicurezza del parser

Il pacchetto è un ingresso non fidato. Il motore lo legge con la sola libreria standard e lo
rifiuta con un errore, mai con un'eccezione grezza. Ogni regola ha il suo codice: **il codice
è normativo, il testo del messaggio no.** Ogni regola ha almeno una prova automatica.

Il motore legge il pacchetto in passi numerati. Per ogni passo è detto se si ferma al primo
errore o se raccoglie tutti gli errori del passo.

- **Passi da 1 a 6** (archivio): un passo che trova errori ferma la lettura; i passi
  successivi non partono.
- **Dal passo 7 in poi**: il motore raccoglie gli errori e prosegue con i passi successivi,
  così un solo rapporto elenca tutti i problemi del pacchetto. Fermano la lettura solo questi
  casi, ed è l'elenco completo:
  - `manifest.json` (passo 7): manca; supera 64 KiB; non è UTF-8; non è JSON valido, anche
    per una chiave ripetuta, un `NaN` o un `Infinity`; non è un oggetto; `format` manca o non
    vale `"regodoc"`; `grammar` manca, non ha la forma del §1.3, oppure nomina una grammatica
    che questo motore non legge (sconosciuta o più nuova). Una chiave non prevista o un
    valore facoltativo sbagliato non fermano la lettura;
  - `structure.toml` (passo 8): manca; supera 64 KiB; comincia con un BOM; non è UTF-8;
    contiene un carattere fuori elenco (§5.2); `tomllib` non lo legge, per sintassi o
    annidamento. Chiavi, tipi e valori sbagliati non fermano la lettura;
  - in qualunque passo, il limite dei problemi: un errore che arriva quando 500 problemi sono
    già elencati ferma la lettura con l'errore `regodoc.limit.problems` (§7.2); gli avvisi
    oltre il tetto no.

  Lo stesso vale per `variables.toml`, che però non ferma mai la lettura: se una delle
  verifiche preliminari o `tomllib` lo rifiutano, il motore prosegue senza variabili.

**Proseguire non deve produrre errori falsi.** Quando una parte dei dati manca, il motore
tace sui problemi che quella mancanza potrebbe causare:

- una variabile dichiarata ma con un valore sbagliato è segnalata una volta sola, in
  `variables.toml`: i suoi richiami non danno `regodoc.xml.unknown_variable`. Se
  `variables.toml` non si legge affatto, nessun richiamo dà `regodoc.xml.unknown_variable`,
  perché il motore non sa quali variabili esistano;
- una voce di `structure.toml` con l'id non valido è segnalata una volta sola, con
  `regodoc.toml.id`, e una voce con l'id già usato da un'altra voce con
  `regodoc.xml.duplicate_id`. Entrambe sono escluse: il file della voce ripetuta si legge una
  volta sola, e nessun file di parte dà `regodoc.package.orphan_part`, perché potrebbe essere
  di una voce esclusa;
- **il pacchetto è letto per intero** se ogni voce di `structure.toml` ha l'id valido e non
  ripetuto, ogni parte dichiarata esiste, si legge ed è percorsa per intero, e nessun file
  di parte è orfano. Una parte non è percorsa per intero quando il motore non scende in uno
  dei suoi elementi: con la radice sbagliata (`regodoc.xml.root`) non scende affatto, e non
  scende in un elemento fuori vocabolario o fuori posto, nei figli di un elemento che deve
  essere vuoto o contenere solo testo, in una sezione oltre il terzo livello
  (`regodoc.xml.section_depth`), in un elenco oltre il terzo livello
  (`regodoc.xml.list_depth`), né in un `<b>`, `<i>` o `<tone>` dentro uno uguale
  (`regodoc.xml.nested_inline`); un `<link>` dentro un `<link>` è un elemento fuori posto.
  Se non è letto per intero, gli id raccolti e gli usi sono incompleti: un rimando o una
  citazione verso un id che non si trova non dà `regodoc.xml.unknown_id` né
  `regodoc.xml.reference_through`, e non si danno gli avvisi `regodoc.toml.unused_variable`
  e `regodoc.image.unused`.

### 6.1 Archivio

Il motore legge l'archivio da sé, senza fidarsi di nessun campo, e decomprime contando i byte
consumati dal decompressore e i byte prodotti.

| Passo | Che cosa controlla | Al primo errore | Codici |
|---|---|---|---|
| 1. Dimensione | il file non supera 12 MiB | si ferma | `regodoc.archive.too_large` |
| 2. Struttura | il file comincia con un'intestazione locale; la fine della directory centrale è in coda, senza dati dopo; nessun commento d'archivio; niente ZIP64, niente dischi multipli; la directory centrale sta dove la fine dichiara | si ferma | `regodoc.archive.invalid`, `.trailing_data`, `.comment`, `.zip64`, `.multi_disk` |
| 3. Numero di voci | prima di leggere la directory centrale: le voci dichiarate dalla fine della directory non superano 202, cioè 200 file più le due voci di cartella ammesse; dopo averla letta: al massimo 200 file, senza contare le voci di cartella | si ferma | `regodoc.archive.too_many_files` |
| 4. Prima voce | si chiama `mimetype`, è all'offset 0, è «stored», non ha campo extra né descrittore di dati; il contenuto, letto subito, è quello del §1.2 e il suo CRC coincide | si ferma | `regodoc.archive.mimetype` |
| 5. Voci | per ogni voce: nome non ripetuto, anche fra file e cartella (**voci ripetute**); non è un file di sistema; percorso relativo, senza `..`, `\`, separatori doppi o componenti vuoti, con caratteri in `[a-z0-9._/-]` salvo la voce `README.md`; nessun commento di voce; **né cifrata né compressa con un metodo diverso da «stored» (0) e «deflate» (8)**; niente estensioni ZIP64; né collegamento simbolico né file speciale, dagli attributi esterni; prevista dalla disposizione del §1.1; una voce di cartella (`parts/` o `images/`, con una sola barra finale) è vuota: «stored» con 0 byte, oppure «deflate» con il solo flusso vuoto `03 00`, e in entrambi i casi CRC 0; intestazione locale uguale alla directory centrale in nome, metodo, flag, CRC e dimensioni (o nel descrittore di dati, se c'è); voci contigue: nessun byte fra la fine di una voce, o del suo descrittore, e l'intestazione locale della successiva, né fra l'ultima voce e la directory centrale | un errore per voce: al primo problema di una voce passa alla successiva; raccoglie gli errori di tutte le voci, poi si ferma. Le voci contigue (`.gap`) si controllano solo se nessuna voce ha altri errori | `regodoc.archive.duplicate`, `.system_file`, `.path`, `.comment`, `.encrypted`, `.method`, `.zip64`, `.special_file`, `.multi_disk`, `.layout`, `.header_mismatch`, `.gap`, `.corrupt` |
| 6. Estrazione contata | **il totale dei byte prodotti non supera 40 MiB, misurato durante la decompressione**, mai sulle dimensioni dichiarate: il motore non produce mai più di un blocco di 64 KiB oltre il limite; i byte compressi consumati dal decompressore coincidono con la dimensione compressa dichiarata; i byte prodotti coincidono con la dimensione e con il CRC dichiarati; ogni voce in `images/` si espande al massimo 20 volte; alla fine, l'archivio intero si espande al massimo 100 volte, come byte prodotti diviso byte consumati | si ferma | `regodoc.archive.expanded_too_large`, `.size_mismatch`, `.corrupt`, `.ratio` |

Il vero argine contro le bombe di compressione è il tetto dei 40 MiB, contato durante la
decompressione. Il rapporto 100 sull'archivio intero lascia passare i documenti legittimi
molto ripetitivi (una tabella di 600 righe si comprime più di 30 volte); il rapporto 20 resta
sulle immagini, che sono già compresse e non hanno motivo di espandersi di più.

### 6.2 Manifesto, grammatica e TOML

| Passo | Che cosa controlla | Al primo errore | Codici |
|---|---|---|---|
| 7. Manifesto e grammatica | `README.md`, se c'è, al massimo 64 KiB (il contenuto non si legge); `manifest.json` presente, al massimo 64 KiB, UTF-8, JSON senza chiavi ripetute, `NaN` o `Infinity`, un oggetto; `format`; chiavi e valori del §1.3; grammatica letta dal motore (§10) | si ferma nei casi elencati all'inizio del §6 (dimensione, codifica, sintassi, non un oggetto, `format`, grammatica); altrimenti raccoglie gli errori e prosegue | `regodoc.limit.file_size`, `regodoc.text.encoding`, `regodoc.manifest.missing`, `.syntax`, `.type`, `.unknown_key`, `.format`, `.grammar`, `.grammar_newer`, `.value` |
| 8. TOML | prima: dimensione, BOM, UTF-8, caratteri (§5.2); poi `tomllib`; poi chiavi, tipi e valori del §2 e del §3. Un commento `#` produce un avviso, trovato da un analizzatore che riconosce le stringhe | per `structure.toml`, si ferma se manca o se le verifiche preliminari o `tomllib` lo rifiutano; per il resto raccoglie tutti gli errori del file e prosegue | `regodoc.package.missing`, `regodoc.limit.file_size`, `regodoc.text.bom`, `.encoding`, `.char`, `.plain`, `regodoc.toml.syntax`, `.depth`, `.unknown_key`, `.missing`, `.type`, `.value`, `.id`, `.variable_name`, `.variable_type`, `.range`, `regodoc.xml.duplicate_id` (una voce ripetuta), `regodoc.limit.parts`, `.variables`; avviso `regodoc.toml.comment` |

### 6.3 XML

Il parser usa `xml.parsers.expat` della libreria standard. Ogni parte è letta in tre tempi.

| Passo 9 | Che cosa controlla | Al primo errore | Codici |
|---|---|---|---|
| Prima dell'analisi | dimensione del file; nessun BOM; UTF-8 valido; dichiarazione XML, se c'è, esattamente quella del §4.1 | si ferma per quella parte e passa alla successiva | `regodoc.limit.file_size`, `regodoc.text.bom`, `.encoding`, `regodoc.xml.declaration` |
| Durante l'analisi, **al primo evento** | dichiarazione `DOCTYPE`; dichiarazione di entità interna o esterna, di notazione, riferimento a un'entità che non sia uno dei cinque predefiniti (decisione 24); istruzione di elaborazione, salvo la dichiarazione XML in testa; sezione `CDATA`; spazio dei nomi (un nome con `:` o un attributo `xmlns`); commento fuori dalla radice; più di 24 elementi annidati; XML non ben formato | si ferma per quella parte e passa alla successiva | `regodoc.xml.doctype`, `.entity`, `.processing_instruction`, `.cdata`, `.namespace`, `.comment_position`, `.syntax`, `regodoc.limit.depth` |
| Dopo l'analisi | radice; elementi e attributi fuori vocabolario o fuori posto; contenuti, attributi e valori (§4); caratteri (§5.2); virgolette e trattini (§5.3); commenti (§4.8); limiti del contenuto (§7.2) | raccoglie tutti gli errori della parte | `regodoc.xml.*`, `regodoc.text.*`, `regodoc.limit.*` |

Nessuna espressione regolare con backtracking esponenziale gira su testo arbitrario.

### 6.4 Immagini, rimandi e totali

| Passo | Che cosa controlla | Al primo errore | Codici |
|---|---|---|---|
| 10. Immagini | struttura di ogni immagine, senza decodificarne i pixel (sotto); al massimo 80 immagini, ognuna al massimo 8 MiB | raccoglie, un errore per immagine | `regodoc.image.format`, `.extension`, `.structure`, `regodoc.limit.images`, `.image_size`; avviso `regodoc.image.metadata` |
| 11. Rimandi e totali | id unici; rimandi, citazioni, variabili e figure verso oggetti che esistono e del tipo giusto; totali del §7.2 | raccoglie tutti | `regodoc.xml.duplicate_id`, `.unknown_id`, `.reference_target`, `.reference_through`, `.cite_target`, `.unknown_variable`, `.var_form`, `.missing_image`, `regodoc.package.missing_part`, `.orphan_part`, `regodoc.limit.characters`, `.references`, `.sources`; avvisi `regodoc.toml.unused_variable`, `regodoc.image.unused` |

Gli avvisi sulle variabili e sulle immagini mai usate si danno solo se il pacchetto è letto per
intero (§6): con una parte non letta, «mai usata» potrebbe essere falso.

- **PNG**: firma, primo blocco `IHDR` con larghezza e altezza da 1 a 6.000 pixel e una
  combinazione valida di tipo di colore e profondità, CRC di ogni blocco, almeno un `IDAT`,
  `IEND` presente e nient'altro dopo. Sono ammessi i blocchi `IHDR`, `PLTE`, `IDAT`, `IEND`,
  `tRNS`, `gAMA`, `cHRM`, `sRGB`, `iCCP` e `pHYs`. Gli altri blocchi ancillari, per esempio
  testo, data o animazione, producono un avviso e non finiscono nel PDF; un blocco critico
  sconosciuto è un errore.
- **JPEG**: `SOI` in testa, segmenti ben formati, un solo frame `SOF0`, `SOF1` o `SOF2` con
  precisione 8 bit, 1, 3 o 4 componenti, larghezza e altezza da 1 a 6.000 pixel, `EOI` in coda
  e nient'altro dopo. I segmenti di metadati da `APP1` ad `APP15` e i commenti `COM` producono
  un avviso; `APP0` (JFIF) no. Le codifiche senza perdita, aritmetiche o a 12 bit sono errori.
- L'estensione deve corrispondere alla firma. SVG, PDF e ogni altro formato sono rifiutati.

### 6.5 Risorse ed esecuzione

- Ogni comando ha un tempo massimo e un limite di memoria, che il motore dichiara
  (`regodoc info`, `resources`) e applica da sé dove il sistema lo permette: il tempo dove ci
  sono i segnali POSIX (Linux e macOS), la memoria sui sistemi di `memory_enforced_on`
  (contratto, §2.3). Superarli è un errore d'ambiente, codice 3, con `regodoc.limit.time` o
  `regodoc.limit.memory`.
- Il motore non scrive mai fuori dalla propria cartella di lavoro temporanea e dal file
  d'uscita indicato da chi lo chiama.
- Il contenuto del pacchetto non diventa mai un comando: pdflatex gira con `shell escape`
  disattivato, in modalità batch, con la lettura e la scrittura di file limitate alla
  cartella di lavoro.

---

## 7. Limiti

I limiti sono in due famiglie (decisione 14). Il motore li dichiara con `regodoc info`, così
chi lo usa li legge senza ricopiarli.

### 7.1 Involucro

Li applica il motore. Chi riceve il pacchetto controlla all'ingresso solo la dimensione e la
firma della prima voce (contratto, §3.1), e lascia il resto al motore.

| Voce | Limite | Chiave in `info` |
|---|---|---|
| Archivio compresso | 12 MiB | `envelope.compressed_bytes` |
| Contenuto espanso, misurato sui byte prodotti dal decompressore | 40 MiB | `envelope.expanded_bytes` |
| Rapporto di compressione dell'archivio intero, sui byte consumati | 100 (§6.1, passo 6) | `envelope.compression_ratio` |
| Rapporto di compressione di ogni immagine | 20 | `envelope.image_compression_ratio` |
| File nell'archivio, senza contare le voci di cartella | 200 | `envelope.files` |

### 7.2 Contenuto

Li dichiara il motore e possono crescere con una sua versione nuova, senza cambiare
grammatica.

| Voce | Limite | Chiave in `info` |
|---|---|---|
| Aperture più parti | 48 | `content.parts` |
| Un file di parte | 384 KiB | `content.part_bytes` |
| `structure.toml` | 64 KiB | `content.structure_bytes` |
| `variables.toml` | 384 KiB | `content.variables_bytes` |
| `manifest.json` | 64 KiB | `content.manifest_bytes` |
| `README.md` | 64 KiB, oltre è `regodoc.limit.file_size` anche se il contenuto si ignora | `content.readme_bytes` |
| Testo totale del documento | 1.500.000 caratteri (sotto) | `content.characters` |
| Immagini | 80, ognuna al massimo 8 MiB e 6.000 × 6.000 pixel, tutte insieme entro i 40 MiB espansi, cioè dentro il limite dell'involucro del §7.1, che le applica | `content.images`, `content.image_bytes`, `content.image_side_pixels`, `content.images_total_bytes` |
| Tabella | 600 righe, 10 colonne, 2.000 caratteri per cella; oltre 8 colonne in carattere ridotto, solo in verticale | `content.table_rows`, `content.table_columns`, `content.cell_characters`, `content.table_columns_normal_size` |
| Annidamento | 3 livelli di sezione, 3 di elenco, 24 elementi in tutto | `content.section_depth`, `content.list_depth`, `content.element_depth` |
| Variabili | 1.500 | `content.variables` |
| Rimandi e citazioni (§4.6, §4.7) | 10.000 | `content.references` |
| Fonti | 500 | `content.sources` |
| `href` | 2.000 caratteri | `content.href_characters` |
| Riga di un listato | 200 caratteri | `content.listing_line_characters` |
| Interi e numeri delle variabili | 10^15 in valore assoluto | `content.number_abs_max` |
| Problemi elencati in un rapporto | 500; un errore in più ferma la lettura con l'errore `regodoc.limit.problems`; gli avvisi in più non si elencano, la lettura prosegue e l'avviso `regodoc.limit.warnings` li conta | `content.problems` |

**Che cosa conta nei 1.500.000 caratteri.** Il testo dei blocchi di testo misto, dopo la
riduzione degli spazi del §5.1; il contenuto di `<code>`, di `<address>` e dei titoli delle
fonti (`<source>`), **con i loro spazi così come sono scritti**, senza riduzione; il corpo
dei `<listing>`. Non contano: i titoli e gli altri valori di
`structure.toml`, gli attributi, i commenti, i valori `text` delle variabili.

---

## 8. Errori, avvisi e codici d'uscita

Ogni problema ha un codice stabile in inglese, il file, la riga, la colonna e un messaggio in
italiano. Per esempio:

```
parts/network.xml:42:17  regodoc.xml.unknown_variable  la variabile «backupCapacty» non esiste in variables.toml
```

Gli **errori** bloccano il pacchetto. Gli **avvisi** no: commenti TOML persi, variabili mai
usate, immagini mai usate, metadati delle immagini ignorati. Con `--strict` gli avvisi
contano come errori.

I codici sono raggruppati per famiglia. Le famiglie e i codici fuori famiglia sono elencati
in un solo posto, il §4.4 del contratto del motore (`docs/contract.md`), che comprende anche
quelli di `build` e degli aggiornamenti (`regodoc.grammar.*`, `regodoc.header.*`,
`regodoc.theme.*`, `regodoc.tex.*`). Un codice, una volta pubblicato, non cambia
significato.

### 8.1 Indice dei codici

Ogni codice che il motore emette, con la regola che lo definisce. «Avviso» segna i codici che
non bloccano il pacchetto.

| Codice | Regola |
|---|---|
| `regodoc.archive.too_large` | §6.1 passo 1, §7.1 |
| `regodoc.archive.invalid` | §6.1 passo 2 |
| `regodoc.archive.trailing_data` | §6.1 passo 2 |
| `regodoc.archive.comment` | §6.1 passo 2 (archivio), passo 5 (voce) |
| `regodoc.archive.zip64` | §6.1 passo 2 (archivio), passo 5 (voce) |
| `regodoc.archive.multi_disk` | §6.1 passo 2 (archivio), passo 5 (voce) |
| `regodoc.archive.too_many_files` | §6.1 passo 3, §1.6, §7.1 |
| `regodoc.archive.mimetype` | §1.2, §1.6, §6.1 passo 4 |
| `regodoc.archive.duplicate` | §6.1 passo 5 |
| `regodoc.archive.system_file` | §6.1 passo 5 |
| `regodoc.archive.path` | §1.5, §1.6, §6.1 passo 5 |
| `regodoc.archive.encrypted` | §6.1 passo 5 |
| `regodoc.archive.method` | §6.1 passo 5 |
| `regodoc.archive.special_file` | §1.6, §6.1 passo 5 |
| `regodoc.archive.layout` | §1.1, §1.6, §6.1 passo 5 |
| `regodoc.archive.header_mismatch` | §6.1 passo 5 |
| `regodoc.archive.gap` | §6.1 passo 5 |
| `regodoc.archive.corrupt` | §6.1 passi 5 e 6 |
| `regodoc.archive.expanded_too_large` | §1.6, §6.1 passo 6, §7.1 |
| `regodoc.archive.size_mismatch` | §6.1 passo 6 |
| `regodoc.archive.ratio` | §6.1 passo 6, §7.1 |
| `regodoc.package.missing` | §1.1, §6.2 passo 8 |
| `regodoc.package.missing_part` | §1.1, §6.4 passo 11 |
| `regodoc.package.orphan_part` | §1.1, §6.4 passo 11 |
| `regodoc.package.system_file` | avviso; §1.6 |
| `regodoc.manifest.missing` | §1.3, §6.2 passo 7 |
| `regodoc.manifest.syntax` | §1.3, §6.2 passo 7 |
| `regodoc.manifest.type` | §1.3, §6.2 passo 7 |
| `regodoc.manifest.unknown_key` | §1.3, §6.2 passo 7 |
| `regodoc.manifest.format` | §1.3, §6.2 passo 7 |
| `regodoc.manifest.grammar` | §1.3, §6.2 passo 7, §10 |
| `regodoc.manifest.grammar_newer` | §1.3, §6.2 passo 7, §10 |
| `regodoc.manifest.value` | §1.3, §6.2 passo 7 |
| `regodoc.toml.syntax` | §6.2 passo 8 |
| `regodoc.toml.depth` | §6.2 passo 8 |
| `regodoc.toml.unknown_key` | §2, §3, §6.2 passo 8 |
| `regodoc.toml.missing` | §2, §3, §6.2 passo 8 |
| `regodoc.toml.type` | §2, §3, §6.2 passo 8 |
| `regodoc.toml.value` | §2, §3.1, §6.2 passo 8 |
| `regodoc.toml.id` | §1.5, §2, §6.2 passo 8 |
| `regodoc.toml.variable_name` | §1.5, §3, §6.2 passo 8 |
| `regodoc.toml.variable_type` | §3, §3.1, §6.2 passo 8 |
| `regodoc.toml.range` | §3.1, §6.2 passo 8 |
| `regodoc.toml.comment` | avviso; §2, §3.1, §6.2 passo 8 |
| `regodoc.toml.unused_variable` | avviso; §3.2, §6.4 passo 11 |
| `regodoc.xml.declaration` | §4.1, §6.3 |
| `regodoc.xml.syntax` | §6.3 |
| `regodoc.xml.depth` | §6.3: annidamento oltre quanto il lettore regge, prima di ogni altro controllo |
| `regodoc.xml.doctype` | §4.1, §6.3 |
| `regodoc.xml.entity` | §4.1, §5.4, §6.3 |
| `regodoc.xml.processing_instruction` | §4.1, §6.3 |
| `regodoc.xml.cdata` | §4.1, §6.3 |
| `regodoc.xml.namespace` | §4.1, §6.3 |
| `regodoc.xml.comment_position` | §4.8, §6.3 |
| `regodoc.xml.root` | §4.1 |
| `regodoc.xml.unknown_element` | §4.2, §4.3 |
| `regodoc.xml.misplaced_element` | §4.2, §4.3 |
| `regodoc.xml.unknown_attribute` | §4.2, §4.3 |
| `regodoc.xml.missing_attribute` | §4.2, §4.3 |
| `regodoc.xml.attribute_value` | §4.2–§4.7 |
| `regodoc.xml.stray_text` | §4.2 |
| `regodoc.xml.empty` | §4.2, §4.4, §4.5, §4.7 |
| `regodoc.xml.not_empty` | §4.3 |
| `regodoc.xml.missing_title` | §4.2 |
| `regodoc.xml.block_after_section` | §4.2 |
| `regodoc.xml.section_depth` | §4.2, §7.2 |
| `regodoc.xml.list_depth` | §4.2, §7.2 |
| `regodoc.xml.item_list` | §4.2 |
| `regodoc.xml.nested_inline` | §4.3 |
| `regodoc.xml.href` | §4.3, §4.7 |
| `regodoc.xml.address` | §4.3 |
| `regodoc.xml.var_name` | §1.5, §3.2 |
| `regodoc.xml.var_form` | §3.2, §6.4 passo 11 |
| `regodoc.xml.unknown_variable` | §3.2, §6, §6.4 passo 11 |
| `regodoc.xml.columns` | §4.4 |
| `regodoc.xml.row_width` | §4.4 |
| `regodoc.xml.table_head` | §4.4 |
| `regodoc.xml.separator` | §4.4 |
| `regodoc.xml.cell_mixed` | §4.4 |
| `regodoc.xml.figure_file` | §4.5 |
| `regodoc.xml.caption` | §4.5 |
| `regodoc.xml.missing_image` | §4.5, §6.4 passo 11 |
| `regodoc.xml.id` | §1.5, §4.6 |
| `regodoc.xml.duplicate_id` | §4.6, §6.2 passo 8 (voce ripetuta di `structure.toml`), §6.4 passo 11 |
| `regodoc.xml.unknown_id` | §4.6, §6.4 passo 11 |
| `regodoc.xml.reference_target` | §4.6, §6.4 passo 11 |
| `regodoc.xml.reference_through` | §4.6, §6.4 passo 11 |
| `regodoc.xml.cite_target` | §4.7, §6.4 passo 11 |
| `regodoc.xml.sources_twice` | §4.7 |
| `regodoc.xml.sources_mixed` | §4.7 |
| `regodoc.text.bom` | §4.1, §6.2 passo 8, §6.3 |
| `regodoc.text.encoding` | §4.1, §6.2 passi 7 e 8, §6.3 |
| `regodoc.text.char` | §5.1, §5.2 |
| `regodoc.text.dashes` | §5.3, testo misto |
| `regodoc.text.quotes` | §5.3, testo misto |
| `regodoc.text.plain` | §5.3, testo puro |
| `regodoc.image.format` | §4.5, §6.4 passo 10 |
| `regodoc.image.extension` | §6.4 passo 10 |
| `regodoc.image.structure` | §6.4 passo 10 |
| `regodoc.image.metadata` | avviso; §6.4 passo 10 |
| `regodoc.image.unused` | avviso; §6.4 passo 11 |
| `regodoc.limit.file_size` | §7.2 |
| `regodoc.limit.parts` | §7.2 |
| `regodoc.limit.variables` | §7.2 |
| `regodoc.limit.characters` | §7.2 |
| `regodoc.limit.depth` | §6.3, §7.2 |
| `regodoc.limit.images` | §6.4 passo 10, §7.2 |
| `regodoc.limit.image_size` | §6.4 passo 10, §7.2 |
| `regodoc.limit.table_rows` | §4.4, §7.2 |
| `regodoc.limit.cell` | §4.4, §7.2 |
| `regodoc.limit.listing_line` | §7.2 |
| `regodoc.limit.references` | §6.4 passo 11, §7.2 |
| `regodoc.limit.sources` | §6.4 passo 11, §7.2 |
| `regodoc.limit.problems` | §7.2 |
| `regodoc.limit.warnings` | avviso; §7.2 |
| `regodoc.limit.memory` | §6.5; contratto, §2.3: codice d'uscita 3 |
| `regodoc.limit.time` | §6.5; contratto, §2.3: codice d'uscita 3 |
| `regodoc.header.missing` | contratto, §3.2: codice d'uscita 2 |
| `regodoc.header.syntax` | contratto, §3.2: codice d'uscita 2 |
| `regodoc.header.unknown_key` | contratto, §3.2: codice d'uscita 2 |
| `regodoc.header.contract` | contratto, §3.2: codice d'uscita 2 |
| `regodoc.header.value` | contratto, §3.2: codice d'uscita 2 |
| `regodoc.header.date` | §2; contratto, §3.2: codice d'uscita 2 |
| `regodoc.theme.missing` | contratto, §3.3: codice d'uscita 2 |
| `regodoc.theme.layout` | contratto, §3.3 e §6: codice d'uscita 2 |
| `regodoc.theme.limit` | contratto, §3.3: codice d'uscita 2 |
| `regodoc.theme.asset` | contratto, §6: codice d'uscita 2 |
| `regodoc.theme.encoding` | contratto, §6: codice d'uscita 2 |
| `regodoc.theme.toml` | contratto, §6.1: codice d'uscita 2 |
| `regodoc.theme.forbidden` | contratto, §6.5: codice d'uscita 2 |
| `regodoc.theme.package` | contratto, §6.1: codice d'uscita 2 |
| `regodoc.theme.redefined` | contratto, §6.4 e §6.5: codice d'uscita 2 |
| `regodoc.theme.shell` | contratto, §6.5: codice d'uscita 2 |
| `regodoc.theme.read` | contratto, §6.5: codice d'uscita 2 |
| `regodoc.theme.write` | contratto, §6.5: codice d'uscita 2 |
| `regodoc.theme.compile` | contratto, §7: codice d'uscita 2 |
| `regodoc.theme.role_default` | avviso informativo; contratto, §6.2 |
| `regodoc.theme.frame_key` | avviso informativo; contratto, §6.1 |
| `regodoc.tex.missing` | contratto, §7: codice d'uscita 3 |
| `regodoc.usage` | contratto, §7: codice d'uscita 2 |
| `regodoc.environment` | contratto, §7: codice d'uscita 3 |
| `regodoc.not_implemented` | contratto, §7: codice d'uscita 3 |
| `regodoc.internal` | contratto, §7: codice d'uscita 4 |
| `regodoc.interrupted` | contratto, §7: codice d'uscita 130 |

### 8.2 Codici d'uscita

I codici d'uscita del comando sono definiti in un solo posto, la tabella normativa del §7
del contratto del motore (`docs/contract.md`): 0 esito positivo, 1 pacchetto rifiutato, 2
errore d'uso, 3 errore d'ambiente, 4 errore interno, 130 interrotto.

Con `--json`, ogni comando scrive un rapporto JSON per **ogni** codice d'uscita, 2, 3, 4 e
130 compresi; fa eccezione solo stdout chiuso da chi legge, dove il rapporto non ha più dove
andare. Il rapporto porta sempre il codice d'uscita, errori e avvisi con la
posizione, la versione del motore, la versione del contratto, la grammatica letta e i limiti
di risorse attivi (`limits_active`, con `null` per un limite non applicato). La sua forma
esatta è nel contratto (`docs/contract.md`, §4).

---

## 9. Forma canonica

Il motore scrive sempre questa forma, e `regodoc canon` la produce. **La garanzia byte per
byte vale per i file del pacchetto**: esportare e reimportare senza modifiche non cambia i
byte di nessun file, quindi le impronte che Rego confronta restano uguali. I byte
dell'archivio possono invece cambiare fra piattaforme, perché librerie di compressione
diverse (zlib, zlib-ng) producono flussi «deflate» diversi a parità di contenuto; per questo
chi conserva le versioni confronta i file, non gli archivi. La forma canonica di una
grammatica resta la stessa in tutte le versioni del motore (contratto, §8).

- **Archivio**: `mimetype` per prima, poi `manifest.json`, `README.md`, `structure.toml`,
  `variables.toml`, le parti nell'ordine di `structure.toml`, le immagini in ordine
  alfabetico. Nessuna voce di cartella. Tutte le voci tranne `mimetype` compresse con
  «deflate» al livello 9; data di modifica fissa, 1980-01-01 00:00; versione «creata da» 3.0
  Unix e «necessaria» 2.0; flag a zero; nessun campo extra; attributi esterni
  `0100644`; nessun commento d'archivio né di voce; nessun descrittore di dati.
- **XML**: dichiarazione iniziale; rientro di due spazi per livello; un elemento per riga,
  salvo dentro un blocco di testo misto, che sta su una sola riga con i suoi elementi in
  linea, come le celle di testo; attributi nell'ordine delle tabelle del §4; virgolette
  doppie; elementi vuoti scritti `<x/>`; nei testi, riferimenti a caratteri ridotti a `&lt;`
  e `&amp;`, più `&gt;` subito dopo `]]` (§5.4); negli attributi, anche `&quot;`; `<listing>` con il
  corpo da colonna 1, fra un a capo dopo il tag d'apertura e uno prima di quello di chiusura;
  un commento su una riga sua, con lo stesso rientro dell'elemento che lo segue; nessuna
  riga vuota; a capo finale.
- **TOML**: chiavi di `structure.toml` nell'ordine della tabella del §2; `key = value` con
  uno spazio per parte attorno a `=`; una riga vuota prima di ogni tabella, nessun'altra riga
  vuota; una variabile per riga, nell'ordine scritto dall'autore, nella forma
  `name = { tipo = valore, note = "…" }`, con la chiave di tipo prima di `note`; stringhe
  fra virgolette doppie; commenti rimossi. Un `variables.toml` senza variabili è omesso
  dall'archivio canonico.
- **JSON**: chiavi in ordine alfabetico, rientro di due spazi, a capo finale.
- Testo NFC, a capo LF, UTF-8 senza BOM.

---

## 10. Grammatiche

Il manifesto dichiara la grammatica: `"grammar": "rego/1"`.

- Dentro `rego/1` si può solo aggiungere: un elemento, un attributo o un valore nuovo era
  prima un errore, quindi i file esistenti non cambiano significato.
- Un cambiamento incompatibile apre `rego/2`, con un aggiornatore automatico da `rego/1`.
- Il motore legge **tutte** le grammatiche precedenti e le porta alla forma canonica della
  grammatica corrente con una catena di aggiornatori sempre inclusa nel motore: `regodoc
  upgrade` (decisione 16bis). Chi conserva le versioni registra l'aggiornamento come
  versione nuova, tracciata, mai come riscrittura silenziosa.
- Un pacchetto con una grammatica più nuova di quella del motore è rifiutato
  (`regodoc.manifest.grammar_newer`), con un messaggio che indica la grammatica del pacchetto
  e quelle che il motore sa leggere.
- Le aggiunte dentro `rego/1` si leggono solo dai motori che le conoscono: un motore più
  vecchio rifiuta un pacchetto che usa un elemento aggiunto dopo di lui, come un errore di
  vocabolario.
- `rego/1` è la prima grammatica pubblicata. La bozza del 12/10 con i nomi italiani non è
  mai stata rilasciata e il motore non la legge.

---

## 11. Esempio completo

Il pacchetto d'esempio completo, sintetico e valido, è nel repository in
`examples/colle-rovere/`: un rapporto inventato sulla rete e sulle copie di sicurezza di una
cantina immaginaria. Le prove lo validano a ogni modifica, sia come cartella sia come archivio.
Qui sotto due dei suoi file, identici a quelli del repository: una prova lo verifica.

Un secondo pacchetto, più lungo e in inglese, è in `examples/lakeside-rowing/`: il rapporto
inventato di un circolo di canottaggio immaginario, con due aperture e otto parti. Usa tutto
il vocabolario: ogni elemento, attributo e valore chiuso, ogni tipo di variabile, intervalli,
valori negativi, tutti gli accenti, immagini PNG e JPEG e commenti. Una prova verifica che
nulla del vocabolario resti fuori.

`structure.toml`

```toml
language = "it"
toc = true

[header]
title = "Rinnovo della rete della Cantina Colle Rovere"
subject = "Analisi dello stato attuale e proposta"
reference = "CR-2026-07"
date = 2026-10-05
version_label = "Bozza 0.3"

[[opening]]
id = "summary"

[[part]]
id = "network"
title = "Rete e collegamenti"
accent = "azure"

[[part]]
id = "backup"
title = "Copie di sicurezza"
accent = "sage"
```

`parts/backup.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<part>
  <summary>Dove stanno gli archivi della cantina e come renderli più sicuri.</summary>
  <section id="current-backup">
    <title>Archivi e copie</title>
    <p><label type="observed"/> Il disco di rete in ufficio è quasi pieno; il nuovo disco di copia avrà <var name="backupCapacity"/>, e dopo un guasto il recupero completo richiederà circa <var name="restoreHours"/>.</p>
    <p>Per le copie fuori dalla cantina vedi <reference to="offsite"/>.</p>
    <box type="status">
      <p>Funziona già bene:</p>
      <list>
        <item>le versioni precedenti dei fogli di calcolo;</item>
        <item>gli accessi separati per ufficio e laboratorio.</item>
      </list>
    </box>
    <!-- Una riga per archivio, dal più consultato. -->
    <table columns="* 2.2cm 2.6cm">
      <head>
        <cell>Archivio</cell>
        <cell>Dove</cell>
        <cell>Copia</cell>
      </head>
      <row>
        <cell>Registro di cantina e analisi di laboratorio</cell>
        <cell>disco di rete</cell>
        <cell><tone type="warning">settimanale</tone></cell>
      </row>
      <row>
        <cell>
          <p>Etichette e grafica:</p>
          <list>
            <item>file di stampa;</item>
            <item>fotografie delle annate.</item>
          </list>
        </cell>
        <cell>portatile grafico</cell>
        <cell><tone type="critical">nessuna</tone> <label type="to-verify"/></cell>
      </row>
      <separator/>
      <row type="total">
        <cell span="2">Capacità del nuovo disco</cell>
        <cell><var name="backupCapacity" form="number"/> TB</cell>
      </row>
    </table>
    <section id="offsite">
      <title>Copia esterna</title>
      <p>Una copia lontana dalla cantina protegge anche da incendio e furto. La prova a secco del trasferimento:</p>
      <listing>
rclone sync --dry-run /volume1/archivi/ esterno:colle-rovere/
echo "prova conclusa"
</listing>
      <small>
        <p>Con <code>--dry-run</code> il comando elenca i file senza trasferirli.</p>
      </small>
    </section>
  </section>
</part>
```

---

## 12. Che cosa resta fuori

Il vocabolario copre i documenti tecnici che Rego produce. Restano fuori, per scelta, queste
costruzioni (decisione 4). Ognuna è un errore se compare, e può entrare solo con una versione
nuova del motore o con una grammatica nuova.

| Esclusa | Perché | Che cosa usare |
|---|---|---|
| Note a piè di pagina | rompono il flusso del testo e il confronto fra versioni | un `<box type="note">` o una fonte citata |
| Formule matematiche | richiedono un linguaggio a sé, che sarebbe un ingresso non fidato in più | un `<listing>` o testo |
| Variabili calcolate e formule sulle variabili | decisione 6 | il valore scritto, con la provenienza in `note` |
| Variabili condivise fra documenti | decisione 5 | la cornice fornita da chi chiama il motore |
| Celle unite in verticale | complicano l'impaginazione delle tabelle lunghe | celle unite in orizzontale (`span`) o una tabella diversa |
| Colori, caratteri e dimensioni scelti dall'autore | l'aspetto è del tema | `accent`, `<tone>`, `<label/>`, `<box>` |
| Allineamento a destra o al centro | previsto per una versione futura del motore (decisione 23) | — |
| Immagini dentro il testo e nelle celle | impaginazione fragile | `<figure>` |
| Immagini SVG e PDF | superficie d'attacco e resa imprevedibile (decisione 15) | PNG o JPEG |
| Collegamenti `http://`, `mailto:` e altri schemi | decisione 23 | `https://`; gli indirizzi email con `<address>` |
| Riquadri annidati, tabelle e figure nei riquadri | decisione 29 | blocchi uno dopo l'altro |
| Quarto livello di sezione | decisione 28 | una sezione in più allo stesso livello |
| Interruzioni di pagina e controllo dell'impaginazione | decide il tema | — |
| Indice analitico e glossario | non usati nei documenti di Rego | — |
| Testo in Markdown, modifiche parziali, importazione di singoli file | decisione 22 | il pacchetto completo |
| Diagrammi descritti con dati (sequenza, linea del tempo, barre, albero) | prima estensione prevista dopo la 4.0 | `<figure>` PNG o JPEG |

---

## Appendice A. Corrispondenza dei nomi

Dai nomi della bozza del 12/10 ai nomi di `rego/1`. Le colonne «Bozza» servono solo a chi
ha letto la bozza: il motore non la legge.

### A.1 File e cartelle

| Bozza | `rego/1` |
|---|---|
| `LEGGIMI.md` | `README.md` |
| `struttura.toml` | `structure.toml` |
| `variabili.toml` | `variables.toml` |
| `parti/` | `parts/` |
| `immagini/` | `images/` |
| `application/vnd.rego.documento` | `application/vnd.regodoc.document` |
| `"grammatica"` nel manifesto | `"grammar"` |

### A.2 `structure.toml`

| Bozza | `rego/1` |
|---|---|
| `indice` | `toc` |
| `versione` | `header.version_label` |
| — | `language` (decisione 8) |
| — | `header.title`, `header.subject`, `header.reference` (decisione 20) |
| — | `header.date` (decisione 17) |
| `[[apertura]]` | `[[opening]]` |
| `[[parte]]` | `[[part]]` |
| `titolo` | `title` |
| `accento` | `accent` |
| `azzurro`, `ardesia`, `salvia`, `bronzo`, `prugna`, `mattone`, `oliva`, `grigio` | `azure`, `slate`, `sage`, `bronze`, `plum`, `brick`, `olive`, `gray` |

### A.3 `variables.toml`

| Bozza | `rego/1` |
|---|---|
| `data` | `date` |
| `gb`, `tb` | `gb`, `tb` |
| `file` | `count` |
| `n` | `number` |
| `pct` | `percent` |
| `eur` | `eur` |
| `ore`, `giorni`, `mesi` | `hours`, `days`, `months` |
| `testo` | `text` |
| `nota` | `note` |
| attributo `nome` di `<var/>` | `name` |
| attributo `parte` di `<var/>`: `min`, `max`, `numero` | `form`: `min`, `max`, `number` |

### A.4 Elementi e attributi XML

| Bozza | `rego/1` |
|---|---|
| `<parte>` | `<part>` |
| `<apertura>` | `<opening>` |
| `<sommario>` | `<summary>` |
| `<sezione>` | `<section>` |
| `<titolo>` | `<title>` |
| `<p>` | `<p>` |
| `<elenco tipo="puntato\|numerato">` | `<list type="bullet\|numbered">` |
| `<voce>` | `<item>` |
| `<riquadro tipo="stato\|nota\|avviso\|critico">` | `<box type="status\|note\|warning\|critical">` |
| `<piccolo>` | `<small>` |
| `<tabella colonne>` | `<table columns>`, più `orientation` |
| `<intestazione>` | `<head>` |
| `<riga tipo="totale">` | `<row type="total">` |
| `<cella unisci>` | `<cell span>` |
| `<separatore/>` | `<separator/>` |
| `<figura file larghezza>` | `<figure file width>` |
| `<didascalia>` | `<caption>` |
| `<codice>` | `<listing>` |
| `<fonti>` | `<sources>` |
| `<gruppo titolo>` | `<group title>` |
| `<fonte href editore consultata>` | `<source href publisher accessed>` |
| `<b>`, `<i>` | `<b>`, `<i>` |
| `<cod>` | `<code>` |
| `<var/>` | `<var/>` |
| `<qual tipo="rilevato\|dichiarato\|deciso\|proposta\|da-verificare\|critico"/>` | `<label type="observed\|declared\|decided\|proposed\|to-verify\|critical"/>` |
| `<tono tipo="critico\|avviso\|ok\|tenue">` | `<tone type="critical\|warning\|ok\|muted">` |
| `<link href>` | `<link href>` |
| `<indirizzo>` | `<address>` |
| `<rimando a fino/>` | `<reference to through/>` |
| `<cita a/>` | `<cite to/>` |
| `<acapo/>` | `<break/>` |

Il blocco di codice cambia nome in `<listing>` perché `<code>` è ormai il nome breve del
testo monospaziato in linea (decisione 26).

---

## Appendice B. Decisioni applicate

| Decisione | Dove |
|---|---|
| 1 impronte sha256, non id interni | §1.3 |
| 2 primo elemento `mimetype`, disposizione fissa | §1.1, §1.2, §6.1 |
| 3 e 3bis nomi in inglese, livello 3 | §0 e appendice A |
| 4 elenco di ciò che resta fuori | §12 |
| 5 nessuna variabile condivisa | §3 |
| 6 nessuna formula | §3, §12 |
| 7 importi editoriali | §3.1 |
| 8 etichette in inglese, diciture nella lingua del documento; campo lingua | §2, §4.3, §5.6 |
| 9 otto ruoli della tavolozza | §2 |
| 10 celle con paragrafi ed elenchi | §4.4 |
| 11 `note` e commenti TOML scartati con avviso | §3.1, §6.2 |
| 13 impronte del manifesto non verificate, salvo la versione di partenza | §1.3 |
| 14 limiti in due famiglie, oltre 8 colonne | §4.4, §7 |
| 15 solo PNG e JPEG | §4.5, §6.4 |
| 16bis grammatiche precedenti sempre leggibili | §10 |
| 17 PDF riproducibili dalla data del documento | §2 |
| 20 intestazione nel pacchetto | §2 |
| 22 solo pacchetto completo | §12 |
| 23 id espliciti, solo https, doppio trattino | §4.3, §4.6, §5.3 |
| 24 XML a vocabolario chiuso, DOCTYPE rifiutato | §4, §6.3 |
| 25 chiavi di `structure.toml` | §2 |
| 26 nomi brevi `b`, `i`, `code`, `var`, `label` | §4.3, appendice A |
| 27 `parts/<id>.xml`, nomi di file sicuri | §1.1, §1.5 |
| 28 livello dei titoli dall'annidamento | §4.2 |
| 29 celle e riquadri | §4.2, §4.4 |
| 30 fonti strutturate e citazioni numerate | §4.7 |
| 31 commenti XML conservati | §4.8 |
| 32 virgolette a coppie, larghezza delle figure, `<code>` | §4.5, §5.3 |
| A1 tre regole nuove dei paragrafi 6 e 7 | §6.1, passi 5 (voci ripetute, cifratura e metodi) e 6 (40 MiB sui byte prodotti) |
| A4 data di ripiego: istante di creazione del documento | §2 |
| A9 documento di prova sintetico e inventato | §11 |
| A10 `README.md` generato dal motore e ignorato in lettura | §1.1, §1.4, §6.1 passo 5 |
| 12/10/2026, dopo la verifica: unità binarie e codici d'uscita | §0, §7, §8 |
| 12/10/2026, dopo la rilettura avversaria: rapporto 100 sull'archivio e 20 sulle immagini, sui byte consumati; voci contigue; dimensione dichiarata uguale ai byte consumati; il valore di `mimetype` all'offset 38, senza campo extra né descrittore di dati; limite di memoria (dal 14/10/2026 lo applica chi chiama: contratto, §2.3) | §1.2, §6.1, §6.5, §7.1 |
| 12/10/2026, dopo la rilettura avversaria: scelte di questa specifica ratificate (lingue, intestazione, cartella, nomi, regole di struttura, caratteri, limiti, forma canonica) | in tutta la specifica |

Le decisioni 12, 16, 18, 19 e 21 riguardano Rego e non il formato.
