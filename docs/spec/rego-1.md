# Formato `.regodoc`, grammatica `rego/1`

Stato: **bozza per l'approvazione**, ottobre 2026. Diventa normativa quando Lorenzo la
approva in blocco, dopo la lettura avversaria dei paragrafi 6 e 7.

Questa specifica descrive che cosa può contenere un pacchetto `.regodoc`, come si scrive e
come lo legge il motore `regodoc`. **Tutto ciò che non è descritto qui è un errore**: il
motore non indovina e non lascia passare testo che non capisce.

La specifica sostituisce la bozza del 12/10 con i nomi italiani, che non è mai stata
rilasciata. La corrispondenza fra i nomi della bozza e quelli di `rego/1` è
nell'[appendice A](#appendice-a-corrispondenza-dei-nomi); l'[appendice B](#appendice-b-decisioni-applicate)
elenca dove è applicata ciascuna decisione verificata il 12/10.

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
  Unicode dopo la normalizzazione NFC.
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

Sono ammesse anche le voci di cartella `parts/` e `images/`, vuote. Qualunque altra voce è un
errore, comprese quelle che i sistemi operativi aggiungono da soli, come `__MACOSX/` o
`.DS_Store`. Il messaggio d'errore lo dice e suggerisce `regodoc canon` per ricostruire
l'archivio.

Il file di una parte **si ricava dal suo id**: la parte `network` sta in `parts/network.xml`.
Un file in `parts/` che non corrisponde a nessun id di `structure.toml` è un errore, e così un
id senza file.

### 1.6 Cartella

Chi scrive può lavorare su una cartella con la stessa disposizione, senza archiviarla: il
motore la accetta in `validate`, e `regodoc canon` la trasforma nell'archivio canonico. In una
cartella valgono le stesse regole su nomi, disposizione e limiti, tranne quelle proprie
dell'archivio ZIP. Collegamenti simbolici e file speciali sono errori. Chi riceve pacchetti da
altri, come Rego, accetta solo archivi.

### 1.2 `mimetype`

La prima voce dell'archivio deve chiamarsi `mimetype`, essere memorizzata senza
compressione, cominciare all'inizio del file e contenere esattamente i byte ASCII

```
application/vnd.regodoc.document
```

senza a capo finale. Così un programma qualunque riconosce un `.regodoc` leggendo i primi
byte. Un archivio con un'altra prima voce, o con un contenuto diverso, è rifiutato prima di
leggere il resto.

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
| `base_version` | no | la versione da cui il pacchetto è stato esportato: `sha256:` seguito da 64 cifre esadecimali minuscole |
| `files` | no | per ogni file del pacchetto tranne `mimetype` e `manifest.json`, l'impronta al momento dell'esportazione, nella stessa forma |
| `generator` | no | `engine` e `version` del motore che ha scritto il pacchetto, testo puro di al massimo 64 caratteri |

Le impronte servono a chi riceve il pacchetto modificato per capire che cosa è cambiato
rispetto all'esportazione. **Non sono un controllo d'integrità**: l'autore modifica i file e
le impronte smettono di coincidere, com'è normale. Chi importa ricalcola le impronte dai byte
letti e usa del manifesto solo `base_version`, dopo averla verificata (decisione 13).

Sono errori: chiavi ripetute, chiavi non previste, valori di tipo sbagliato, `NaN` e
`Infinity`, un percorso in `files` che non è un file ammesso dal §1.1.

### 1.4 `README.md`

Il motore lo genera a ogni esportazione, nella lingua del documento, con le istruzioni per
modificare il pacchetto e rimetterlo insieme. In lettura il suo contenuto è ignorato: conta
solo per i limiti dell'involucro (§7.1).

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
pacchetto li copia nei propri campi a ogni importazione, come proiezione (decisione 20).
`version_label` vive solo nel PDF.

`date` è la data del documento. Dà la data stampata e l'istante usato per rendere il PDF
riproducibile (`SOURCE_DATE_EPOCH`, mezzanotte UTC di quella data). Se manca, il motore usa la
data fornita da chi lo chiama con l'intestazione in JSON; se manca anche quella, `build` si
ferma con un errore d'uso.

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
surveyDate    = { date = 2026-09-14 }
nasUsed       = { gb = "2.310,75" }
fileCount     = { count = 96418 }
diskFill      = { percent = "61,2" }
accessPoints  = { number = 9 }
upgradeMonths = { months = [3, 5] }
switchCost    = { eur = ["2.140", "2.680"], note = "due preventivi di installatori, settembre 2026" }
cloudFee      = { eur = "11,40" }
versions      = { days = 45 }
siteName      = { text = "Cantina Colle Rovere" }
```

Un nome di variabile (§1.5) è unico. Le variabili sono di un solo documento: non esistono
variabili condivise fra documenti (decisione 5). Non esistono formule né variabili calcolate
(decisione 6).

### 3.1 Tipi

| Tipo | Valore | Resa in italiano | Resa in inglese |
|---|---|---|---|
| `date` | data TOML senza ora | 14 settembre 2026 | 14 September 2026 |
| `gb`, `tb` | numero italiano (stringa) | `2.310,75 GB`, in carattere monospaziato | `2,310.75 GB` |
| `count` | intero non negativo | `96.418`, monospaziato | `96,418` |
| `number` | intero, oppure numero italiano | `6`, `3,5` | `6`, `3.5` |
| `percent` | numero italiano | `61,2%` | `61.2%` |
| `eur` | numero italiano, al massimo due decimali | `2.140 euro`, `11,40 euro` | `EUR 2,140`, `EUR 11.40` |
| `hours`, `days`, `months` | intero non negativo, oppure numero italiano | `30 giorni`, `1 giorno` | `30 days`, `1 day` |
| `text` | testo puro, da 1 a 500 caratteri | così com'è | così com'è |

**Numero italiano.** Una stringa che rispetta `-?\d{1,3}(\.\d{3})*(,\d+)?` oppure
`-?\d{1,3}(,\d+)?`: il punto separa sempre le migliaia, ed è obbligatorio da 1.000 in su; la
virgola separa sempre i decimali. Così `"1.084"` vale milleottantaquattro, senza ambiguità.
I numeri TOML a virgola mobile, come `87.4`, sono un errore: si perderebbe la precisione
scritta. I valori si scrivono sempre all'italiana, qualunque sia la lingua del documento; la
resa segue la lingua (§5.6).

**Intervallo.** Lo stesso tipo con un array di due valori: `{ eur = ["2.140", "2.680"] }`. Il
primo non può superare il secondo. Si rende `2.140–2.680 euro`, con l'unità una volta sola.
Ammesso per tutti i tipi tranne `date` e `text`.

**Euro.** Gli importi sono editoriali: testo validato e formattato, mai collegato alla
contabilità (decisione 7). Il motore li converte in centesimi interi solo per validarli e
formattarli: senza decimali se i centesimi sono zero, altrimenti con due.

**Singolare.** Per `hours`, `days` e `months` il valore 1 prende l'unità al singolare.

**`note`.** Testo puro, da 1 a 500 caratteri: la provenienza del valore. Non si stampa mai.
I commenti `#` invece si perdono, con un avviso (decisione 11): la provenienza va in `note`.

### 3.2 Richiamo

Nel testo XML: `<var name="nasUsed"/>`. L'attributo facoltativo `form` sceglie che cosa
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
  elaborazione, nessuna sezione `CDATA` (§6.2).
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
  caratteri, nessuna etichetta che comincia o finisce con `-`.
- La legenda delle etichette si genera da sola all'inizio del documento se almeno
  un'etichetta è usata. Le diciture seguono la lingua del documento (decisione 8).

### 4.4 Tabelle

```xml
<table columns="* 2.2cm 2.6cm">
  <head>
    <cell>Archivio</cell><cell>Dove</cell><cell>Copia</cell>
  </head>
  <row>
    <cell>
      <p>Etichette e grafica:</p>
      <list><item>file di stampa;</item><item>fotografie delle annate.</item></list>
    </cell>
    <cell>portatile grafico</cell>
    <cell><tone type="critical">nessuna</tone></cell>
  </row>
  <separator/>
  <row type="total">
    <cell span="2">Spazio occupato</cell>
    <cell><var name="nasUsed"/></cell>
  </row>
</table>
```

- `columns`: una voce per colonna, separate da uno spazio. `*` è una colonna che si allarga;
  una misura come `1.8cm` è una colonna fissa, da `0.5cm` a `12cm`, con il punto decimale, al
  massimo due decimali e solo l'unità `cm`. Almeno una colonna è `*`. Al massimo 10 colonne.
- **Oltre le otto colonne**, cioè con nove o dieci, la tabella si stampa in carattere ridotto.
  `orientation` vale `portrait`, il predefinito, oppure `landscape`, che mette la tabella su
  pagine orizzontali; `landscape` è ammesso con qualunque numero di colonne.
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
  <caption>Disposizione dell'armadio di rete al <var name="surveyDate"/>.</caption>
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
- `<reference to="network"/>` verso una parte rende «Parte II». Con
  `through="backup"` rende «Parti II–III»: `through` è ammesso solo fra due parti, e la
  seconda deve venire dopo la prima.
- Verso una sezione rende il suo titolo fra virgolette, seguito dalla parte se è un'altra:
  «Copie fuori sede» (Parte III).
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

### 5.1 Spazi

Nel testo misto ogni sequenza di spazi, tabulazioni e a capo vale un solo spazio, e gli spazi
all'inizio e alla fine di un blocco si ignorano: rientri e a capo nel file non cambiano nulla
nel PDF. Lo spazio non separabile (U+00A0) resta tale. Le eccezioni sono `<listing>` (§4.5) e
il testo di `<code>`, dove gli spazi interni si conservano.

### 5.2 Caratteri

Il testo, gli attributi e i valori TOML sono in Unicode normalizzato NFC. Sono ammessi solo:

| Insieme | Punti di codice |
|---|---|
| ASCII stampabile | U+0020–U+007E |
| a capo e tabulazione, solo dove il formato li ammette | U+000A, U+0009 |
| Latin-1 | U+00A0–U+00FF, escluso U+00AD (trattino morbido) |
| Latin Extended-A | U+0100–U+017F, escluso U+0149 |
| simboli tipografici | – U+2013, — U+2014, ‘ U+2018, ’ U+2019, “ U+201C, ” U+201D, … U+2026, • U+2022, € U+20AC, ⇒ U+21D2 |

Un carattere fuori elenco, per esempio un emoji, un carattere di controllo o un carattere di
controllo bidirezionale, è un errore con la sua posizione: bloccherebbe la compilazione o
nasconderebbe il testo a chi rilegge.

### 5.3 Tipografia

- `--` diventa il trattino breve –. Tre o più trattini di fila sono un errore: la lineetta —
  si scrive direttamente.
- Le virgolette dritte `"` si chiudono a coppie dentro lo stesso blocco e diventano “ ”; un
  numero dispari nello stesso blocco è un errore (decisione 32). Vale anche per i valori di
  testo puro di `structure.toml`, di `variables.toml` e degli attributi.
- L'apostrofo dritto `'` diventa ’.
- Dentro `<code>` e `<listing>` virgolette, apostrofi e trattini restano come sono e non
  contano per le coppie.

### 5.4 Riferimenti a caratteri

Sono ammessi solo i cinque riferimenti predefiniti (`&lt;` `&gt;` `&amp;` `&quot;` `&apos;`) e
quelli numerici (`&#160;`, `&#xA0;`). Il carattere che ne risulta segue le regole del §5.2. La
forma canonica li riporta a caratteri normali, tranne `&lt;` e `&amp;`, che sono
indispensabili.

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
rifiuta, con un errore e senza eccezioni grezze, nei casi seguenti. Ogni caso ha una prova
automatica.

### 6.1 Archivio

Il motore legge l'archivio dalla directory centrale e verifica ogni voce contro la sua
intestazione locale. È un errore:

1. una prima voce diversa da `mimetype`, compressa, che non comincia all'offset 0 o con un
   contenuto diverso da quello del §1.2;
2. **una voce ripetuta**, cioè due voci con lo stesso nome, anche se una è una cartella;
3. **una voce cifrata, o compressa con un metodo diverso da «stored» (0) e «deflate» (8)**;
4. un archivio diviso su più dischi, un archivio ZIP64, dati prima della prima voce o dopo la
   fine della directory centrale;
5. un nome diverso fra directory centrale e intestazione locale;
6. un percorso assoluto, con `..`, con `\`, con separatori doppi, con componenti vuoti, con
   caratteri fuori da `[a-z0-9._/-]`, o fuori dalla disposizione del §1.1;
7. un collegamento simbolico o un file speciale, riconosciuto dagli attributi esterni;
8. più di 200 voci;
9. un archivio di più di 12 MiB;
10. **più di 40 MiB espansi, misurati sui byte effettivamente letti durante l'estrazione**,
    mai sulle dimensioni dichiarate nell'archivio, che possono mentire;
11. un rapporto di compressione oltre 20: sull'archivio intero, come byte letti diviso byte
    compressi; e su ogni voce appena i suoi byte letti superano 64 KiB, così i file piccoli
    e ripetitivi non danno falsi allarmi;
12. una voce i cui byte letti non coincidono con la dimensione o con il CRC dichiarati.

La lettura si ferma al primo superamento di un limite: il motore non espande mai più dei
limiti, nemmeno per scrivere il messaggio d'errore.

### 6.2 XML

Il parser usa `xml.parsers.expat` della libreria standard e rifiuta, **al primo evento**:

- una dichiarazione `DOCTYPE`, una dichiarazione di entità interna o esterna, un riferimento
  a un'entità che non sia uno dei cinque predefiniti (decisione 24);
- un'istruzione di elaborazione, salvo la dichiarazione XML in testa;
- una sezione `CDATA`;
- uno spazio dei nomi: un nome con `:` o un attributo `xmlns`;
- un elemento o un attributo fuori vocabolario, o fuori posto;
- più di 24 elementi annidati.

Prima ancora di analizzare: dimensione del file entro il limite, UTF-8 valido, nessun BOM, la
dichiarazione XML, se c'è, esattamente quella del §4.1. Dopo l'analisi: caratteri (§5.2),
virgolette (§5.3), commenti (§4.8) e riferimenti (§4.6). Nessuna espressione regolare con
backtracking esponenziale gira su testo arbitrario.

### 6.3 TOML

Il motore legge i file TOML con `tomllib` della libreria standard, dopo aver controllato
dimensione e codifica. È un errore: una chiave fuori vocabolario, un tipo sbagliato, un valore
oltre i limiti, una data con ora o fuso, un array annidato o una tabella oltre la profondità
prevista, un id che non è un nome di file sicuro (§1.5). Un commento `#` produce un avviso.

### 6.4 Immagini

Il motore verifica la struttura di ogni immagine senza decodificarne i pixel:

- **PNG**: firma, primo blocco `IHDR` con larghezza e altezza da 1 a 6.000 pixel, CRC di ogni
  blocco, `IEND` presente e nient'altro dopo. Sono ammessi i blocchi `IHDR`, `PLTE`, `IDAT`,
  `IEND`, `tRNS`, `gAMA`, `cHRM`, `sRGB`, `iCCP` e `pHYs`. Gli altri blocchi ancillari, per
  esempio testo, data o animazione, producono un avviso e non finiscono nel PDF.
- **JPEG**: `SOI` in testa, segmenti ben formati, un solo frame `SOF0`, `SOF1` o `SOF2` con
  precisione 8 bit, 1, 3 o 4 componenti, larghezza e altezza da 1 a 6.000 pixel, `EOI` in
  coda e nient'altro dopo. I segmenti `APPn` di metadati producono un avviso.
- L'estensione deve corrispondere alla firma. SVG, PDF e ogni altro formato sono rifiutati.

### 6.5 Risorse ed esecuzione

- Ogni fase ha un tempo massimo e, dove il sistema lo permette, un limite di memoria; i
  valori li dichiara il motore. Superarli è un errore d'ambiente (§8).
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

Li applica chi riceve il pacchetto, per esempio Rego all'ingresso, e li ripete il motore.

| Voce | Limite |
|---|---|
| Archivio compresso | 12 MiB |
| Contenuto espanso, misurato sui byte letti | 40 MiB |
| Rapporto di compressione | 20 (§6.1, punto 11) |
| Voci nell'archivio | 200 |

### 7.2 Contenuto

Li dichiara il motore e possono crescere con una sua versione nuova, senza cambiare
grammatica.

| Voce | Limite |
|---|---|
| Aperture più parti | 48 |
| Un file di parte | 384 KiB |
| `structure.toml` | 64 KiB |
| `variables.toml` | 384 KiB |
| Testo totale del documento | 1.500.000 caratteri |
| Immagini | 80, ognuna al massimo 8 MiB e 6.000 × 6.000 pixel, tutte insieme entro i 40 MiB espansi |
| Tabella | 600 righe, 10 colonne, 2.000 caratteri per cella; oltre 8 colonne in carattere ridotto |
| Annidamento | 3 livelli di sezione, 3 di elenco, 24 elementi in tutto |
| Variabili | 1.500 |
| Rimandi e citazioni | 10.000 |
| Fonti | 500 |
| `href` | 2.000 caratteri |
| Riga di un listato | 200 caratteri |

---

## 8. Errori, avvisi e codici d'uscita

Ogni problema ha un codice stabile in inglese, il file, la riga, la colonna e un messaggio in
italiano. Per esempio:

```
parts/network.xml:42:17  regodoc.xml.unknown_variable  la variabile «nasUsd» non esiste in variables.toml
```

Gli **errori** bloccano il pacchetto. Gli **avvisi** no: commenti TOML persi, variabili mai
usate, immagini mai usate, metadati delle immagini ignorati. Con `--strict` gli avvisi
contano come errori.

I codici sono raggruppati per famiglia: `regodoc.archive.*`, `regodoc.manifest.*`,
`regodoc.toml.*`, `regodoc.xml.*`, `regodoc.text.*`, `regodoc.image.*`, `regodoc.limit.*`. Un
codice, una volta pubblicato, non cambia significato.

Il comando esce con questi codici, che fanno parte del contratto (CP-72):

| Codice | Significato |
|---|---|
| 0 | esito positivo, anche con avvisi |
| 1 | pacchetto rifiutato per errori di validazione, o per avvisi con `--strict`; l'elenco è nel rapporto |
| 2 | errore d'uso: argomenti, file mancante, opzione sconosciuta |
| 3 | errore d'ambiente: TeX assente, cartella non scrivibile, tempo massimo superato |
| 4 | errore interno: un'eccezione non prevista; non deve mai accadere, e le prove avversarie lo dimostrano |

Il rapporto JSON riporta sempre il codice d'uscita, errori e avvisi con la posizione, la
versione del motore, la versione del contratto e la grammatica letta. La sua forma esatta è
nel contratto (`docs/contract.md`).

---

## 9. Forma canonica

Il motore scrive sempre questa forma, e `regodoc canon` la produce: esportare e reimportare
senza modifiche non cambia un byte.

- **Archivio**: `mimetype` per prima, poi `manifest.json`, `README.md`, `structure.toml`,
  `variables.toml`, le parti nell'ordine di `structure.toml`, le immagini in ordine
  alfabetico. Nessuna voce di cartella. Tutte le voci tranne `mimetype` compresse con
  «deflate»; data di modifica fissa, 1980-01-01 00:00; nessun attributo esterno oltre ai
  permessi `0644`; nessun commento d'archivio.
- **XML**: dichiarazione iniziale; rientro di due spazi per i blocchi; un blocco di testo
  misto su una sola riga; attributi nell'ordine delle tabelle del §4; virgolette doppie;
  elementi vuoti scritti `<x/>`; riferimenti a caratteri ridotti a `&lt;` e `&amp;`; a capo
  finale.
- **TOML**: chiavi di `structure.toml` nell'ordine della tabella del §2; una variabile per
  riga, nell'ordine scritto dall'autore, con la chiave di tipo prima di `note`; commenti
  rimossi.
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
- Un pacchetto con una grammatica più nuova di quella del motore è rifiutato, con un
  messaggio che indica la versione del motore necessaria.
- `rego/1` è la prima grammatica pubblicata. La bozza del 12/10 con i nomi italiani non è
  mai stata rilasciata e il motore non la legge.

---

## 11. Esempio completo

Il pacchetto d'esempio completo, sintetico e valido, è nel repository in
`examples/colle-rovere/`: un rapporto inventato sulla rete e sulle copie di sicurezza di una
cantina immaginaria. Le prove lo validano a ogni modifica, sia come cartella sia come archivio.
Qui sotto due dei suoi file, identici a quelli del repository: una prova lo verifica.

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
  <summary>Dove stanno gli archivi della cantina al <var name="surveyDate"/> e come renderli più sicuri.</summary>
  <section id="current-backup">
    <title>Archivi e copie</title>
    <p><label type="observed"/> Il disco di rete in ufficio contiene <var name="nasUsed"/> in <var name="fileCount"/> file e ha i dischi pieni al <var name="diskFill"/>.</p>
    <p>Ogni file modificato resta recuperabile per <var name="versions"/>; per le copie fuori dalla cantina vedi <reference to="offsite"/>.</p>
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
        <cell span="2">Spazio occupato</cell>
        <cell><var name="nasUsed" form="number"/> GB</cell>
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

> **Da verificare.** L'elenco del «7% escluso» calcolato dalla Compilazione intermedia non era
> nel materiale ricevuto dalla sessione regodoc: la tabella qui sopra è ricostruita dalle
> decisioni e dalla bozza. Il capo progetto la confronta con l'elenco originale prima
> dell'approvazione.

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
| 11 `note` e commenti TOML scartati con avviso | §3.1, §6.3 |
| 13 impronte del manifesto non verificate, salvo la versione di partenza | §1.3 |
| 14 limiti in due famiglie, oltre 8 colonne | §4.4, §7 |
| 15 solo PNG e JPEG | §4.5, §6.4 |
| 16bis grammatiche precedenti sempre leggibili | §10 |
| 17 PDF riproducibili dalla data del documento | §2 |
| 20 intestazione nel pacchetto | §2 |
| 22 solo pacchetto completo | §12 |
| 23 id espliciti, solo https, doppio trattino | §4.3, §4.6, §5.3 |
| 24 XML a vocabolario chiuso, DOCTYPE rifiutato | §4, §6.2 |
| 25 chiavi di `structure.toml` | §2 |
| 26 nomi brevi `b`, `i`, `code`, `var`, `label` | §4.3, appendice A |
| 27 `parts/<id>.xml`, nomi di file sicuri | §1.1, §1.5 |
| 28 livello dei titoli dall'annidamento | §4.2 |
| 29 celle e riquadri | §4.2, §4.4 |
| 30 fonti strutturate e citazioni numerate | §4.7 |
| 31 commenti XML conservati | §4.8 |
| 32 virgolette a coppie, larghezza delle figure, `<code>` | §4.5, §5.3 |
| A1 tre regole nuove dei paragrafi 6 e 7 | §6.1 punti 2, 3 e 10 |
| CP-72 unità binarie e codici d'uscita | §0, §7, §8 |

Le decisioni 12, 16, 18, 19 e 21 riguardano Rego e non il formato.
