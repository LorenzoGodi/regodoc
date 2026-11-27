# Ingresso Markdown `md/1`

Stato: **dal motore 0.4**, lotto L19 (R4). Questa specifica descrive il Markdown che `regodoc
import --from markdown` accetta e il pacchetto che ne scrive. Il pacchetto d'uscita segue la
specifica di `rego/1` e `rego/2` (`rego-1.md`), nella grammatica corrente; il contratto del
motore (`docs/contract.md`) dice come si chiama il comando.

`md/1` è un sottoinsieme chiuso di Markdown, con i nomi e le forme di CommonMark e delle
tabelle di GitHub. **Tutto ciò che non è descritto qui è un errore**, con il suo codice e la
riga del file: il motore non indovina, non scarta in silenzio e non lascia passare HTML,
collegamenti o immagini remote.

## 1. L'ingresso

Un archivio `.zip` o una cartella, con:

- `document.md`, obbligatorio, il testo;
- `images/`, facoltativa, con le immagini PNG e JPEG che il testo richiama, con i nomi, le
  estensioni e i limiti delle immagini del pacchetto (`rego-1.md`, §1.5 e §7.2).

Nessun altro file. L'archivio si legge con le stesse difese e gli stessi limiti
dell'involucro di un pacchetto (`rego-1.md`, §6.1 e §7.1).

**Le immagini come in `canon`.** Le immagini dell'ingresso passano gli stessi controlli di
quelle del pacchetto (`rego-1.md`, §6.4), con gli stessi codici, e la stessa pulizia dei
metadati della grammatica corrente (`rego-1.md`, §13): un'immagine con metadati dà l'avviso
`regodoc.image.stripped` e nel pacchetto entra pulita. L'uscita di `import` è quella che
`canon` scriverebbe per lo stesso contenuto: rifare `canon` sull'uscita dà gli stessi byte.

## 2. Codifica e righe

| Regola | Codice |
|---|---|
| UTF-8 valido, senza BOM | `regodoc.text.encoding` |
| a capo LF; CRLF vale LF; un CR da solo è un errore | `regodoc.text.encoding` |
| nessun carattere NUL | `regodoc.text.encoding` |
| nessuna tabulazione: rientri e allineamenti si scrivono con gli spazi | `regodoc.markdown.syntax` |
| il file al massimo di 2 MiB, ogni riga al massimo di 10.000 caratteri | `regodoc.limit.markdown` |

Gli spazi in fondo a una riga si ignorano. Il testo che ne esce passa poi per le regole del
testo del pacchetto (`rego-1.md`, §5: caratteri, virgolette, trattini), con i loro codici.

## 3. Blocchi

Un blocco comincia a una riga che non continua il blocco di prima; una riga vuota chiude
paragrafi, elenchi e tabelle.

| Markdown | Pacchetto |
|---|---|
| `# Titolo`, una volta sola, prima di ogni altro titolo | `header.title` di `structure.toml` |
| `## Titolo` | una parte, con quel titolo |
| `###`, `####`, `#####` | una sezione ai tre livelli del pacchetto, con il titolo in `<title>`; un livello non si salta |
| righe di testo consecutive | un `<p>`; gli a capo valgono uno spazio |
| `- ` o `* ` all'inizio della riga, seguiti da uno spazio | una voce di `<list>` puntato |
| `1. ` o `1) ` | una voce di `<list type="numbered">`; l'elenco comincia da 1, i numeri dopo non contano |
| una riga di tabella `\| a \| b \|`, poi `\|---\|---:\|`, poi le righe | `<table>`, vedi sotto |
| fra due righe di tre o più `` ` `` o `~` | `<listing>`, con il testo com'è; il resto della riga d'apertura si ignora |
| un paragrafo di una riga fatto solo di `![didascalia](images/nome.png)` | `<figure file="images/nome.png">`, con `<caption>` se la didascalia non è vuota |

**Titoli.** Il cancelletto è seguito da uno spazio; `#etichetta` è testo. I cancelletti di
chiusura (`## Titolo ##`) si tolgono. Il titolo del documento e quelli delle parti sono testo
puro: le fughe con la barra rovescia valgono, le enfasi no. I titoli delle sezioni sono testo
in linea (§4).

**Elenchi.** Una voce annidata comincia alla colonna del testo della voce di sopra: due spazi
sotto `- `, tre sotto `1. `. Al massimo tre livelli, come nel pacchetto. Una riga che non è una
voce continua il testo della voce di sopra. Le righe vuote fra due voci dello stesso elenco
non lo interrompono. Una voce di tipo diverso allo stesso livello è un errore, salvo al primo
livello, dove comincia un elenco nuovo.

**Tabelle.** Ogni riga comincia e finisce con `|`, e ha tante celle quante la riga di
separazione. La prima riga va in `<head>`, le altre in `<row>`. Le colonne sono tutte `*`;
`---` e `:---` le allineano a sinistra, `---:` a destra; `:---:` è un errore, perché il
pacchetto non centra. `\|` scrive una barra dentro una cella. Una cella vuota è `<cell/>`.

**Struttura del pacchetto.**

- I blocchi fra il titolo del documento e la prima parte formano un'apertura, con id
  `opening`.
- L'id della parte N (contando da 1) viene dal suo titolo, in quest'ordine:
  1. il titolo si scompone in NFKD e si tolgono i segni diacritici, così `à` diventa `a`;
  2. tutto passa in minuscolo;
  3. ogni carattere fuori da `a`–`z` e `0`–`9` diventa un trattino, anche le lettere che
     dopo il passo 1 non sono ASCII (`ß` dà un trattino);
  4. i trattini ripetuti si riducono a uno e si tolgono in testa e in coda;
  5. un titolo che resta vuoto dà `parte-N`; uno che comincia con una cifra prende
     `parte-` davanti;
  6. l'id si tronca a 48 caratteri, senza trattino finale;
  7. un id già usato, `opening` compreso, o uno che il pacchetto non ammette (i nomi
     riservati di Windows, come `con`) prende `-2`, poi `-3` e così via, entro i 48
     caratteri.

  «Attivita'», «Attività» e «ATTIVITÀ», in quest'ordine, danno `attivita`, `attivita-2`
  e `attivita-3`.
- L'accento delle parti segue la tavolozza a giro: `azure`, `slate`, `sage`, `bronze`, `plum`,
  `brick`, `olive`, `gray`.
- Un blocco dopo una sottosezione appartiene alla sottosezione: in Markdown non si torna al
  livello di sopra senza un titolo.

**L'intestazione.** Di `structure.toml` l'unico campo obbligatorio è `header.title`, che
viene dal titolo `#` (un titolo mancante è `regodoc.markdown.heading`). `language` viene
dall'opzione `--language`, `it` se manca; `document` del manifesto dall'opzione
`--document`, se c'è. `toc`, `subject`, `reference`, `date` e `version_label` non si
scrivono: chi vuole valorizzarli modifica il pacchetto dopo l'importazione. Nessun valore
viene dall'orologio o dall'ambiente, quindi lo stesso ingresso con le stesse opzioni dà
sempre gli stessi byte. Senza `header.date`, `build` prende la data dall'intestazione di
chi chiama o da `SOURCE_DATE_EPOCH`, come per ogni pacchetto (`rego-1.md`, §2).

## 4. Testo in linea

| Markdown | Pacchetto |
|---|---|
| `**testo**` | `<b>` |
| `*testo*` o `_testo_` | `<i>` |
| `***testo***` | `<b><i>…</i></b>` |
| `` `testo` `` | `<code>`; con più accenti, `` `` a `b` `` ``, il codice contiene l'accento; uno spazio in testa e uno in coda si tolgono |
| `\` seguito da un segno di punteggiatura ASCII | il segno, letterale |

Un segno d'enfasi apre se è seguito da un carattere che non è uno spazio, e chiude se è
preceduto da uno. Dentro una parola il trattino basso è un carattere (`nome_del_file`),
l'asterisco no. Un segno con uno spazio prima e dopo è un carattere (`5 * 3`). Le enfasi
si chiudono nell'ordine in cui si sono aperte; un'enfasi aperta e mai chiusa, o chiusa
senza essere aperta, è un errore. Al massimo otto enfasi aperte insieme. Le annidature
seguono il pacchetto: `<b>` dentro `<b>` è un errore (`rego-1.md`, §4.3).

Il testo resta testo: `x < 3`, `[nota]` e un indirizzo scritto per intero non diventano
altro. **Le entità non si decodificano**: `&amp;`, `&#60;` e un `&` da solo restano i
caratteri scritti, e il generatore li scrive nel XML come testo (`&amp;amp;`).

## 5. Che cosa è rifiutato

| Costruzione | Codice |
|---|---|
| HTML: `<` seguito da una lettera, da `/`, da `!` o da `?`, in qualunque punto del testo; per scrivere il segno si usa `\<` | `regodoc.markdown.html` |
| collegamenti: `[testo](indirizzo)`, `[testo][rif]`, `<https://…>` e le definizioni `[rif]: indirizzo` | `regodoc.markdown.link` |
| immagini con un indirizzo: `http:`, `https:`, `data:`, `//…` o un altro schema | `regodoc.markdown.remote_image` |
| un'immagine dentro un paragrafo di testo, un percorso fuori da `images/nome.png`, `.jpg` o `.jpeg`, o un file che l'ingresso non contiene | `regodoc.markdown.image` |
| un titolo mancante, ripetuto, vuoto o di livello `######`, un livello saltato, un titolo sottolineato con `===` o `---` | `regodoc.markdown.heading` |
| citazioni `>`, righe di separazione `---`, `***` o `___`, codice rientrato di quattro spazi, note `[^1]`, barrato `~~`, voci da spuntare `[ ]`, colonne centrate, un elenco numerato che non comincia da 1 | `regodoc.markdown.unsupported` |
| ogni altra forma sbagliata: un'enfasi o un codice non chiusi, un blocco di codice senza chiusura o vuoto, una tabella senza riga di separazione o con celle in numero diverso, una voce fuori colonna o senza testo | `regodoc.markdown.syntax` |

## 6. Errori e posizioni

Ogni problema dice `file: "document.md"`, la riga e, dove serve, la colonna del Markdown. La
posizione è quella dell'apertura: per un'enfasi o un codice non chiusi, il segno che li
apre; per un blocco di codice senza chiusura, la riga dei tre accenti; per una riga di
tabella sbagliata, la colonna 1 di quella riga. Il
pacchetto generato si valida per intero, come ogni uscita di `canon`. I problemi che la
validazione trova nel pacchetto (per esempio una virgoletta spaiata o un limite superato)
tengono il loro codice e tornano alla riga del Markdown da cui viene il blocco.

Lo stesso `document.md`, con le stesse immagini e le stesse opzioni, dà sempre gli stessi byte
in uscita.

**`--strict`** vale come per `canon`: gli avvisi del pacchetto generato contano come errori
e l'uscita non si scrive. Gli avvisi possibili sono quelli della validazione, per esempio
un'immagine dell'ingresso che il testo non richiama (`regodoc.image.unused`) o metadati
tolti da un'immagine (`regodoc.image.stripped`). Il Markdown in sé non dà avvisi: ciò che
non è `md/1` è sempre un errore.

## 7. Limiti

| Limite | Valore | Chiave in `info` | Codice |
|---|---|---|---|
| dimensione di `document.md` | 2 MiB | `content.markdown_bytes` | `regodoc.limit.markdown` |
| caratteri di una riga | 10.000 | `content.markdown_line_characters` | `regodoc.limit.markdown` |

Tutti gli altri limiti sono quelli del pacchetto d'uscita (`rego-1.md`, §7.2), con i loro codici.

Il lettore va per righe, senza ricorsione sull'ingresso: il tempo cresce in modo lineare con
il testo, anche con migliaia di segni d'enfasi o di parentesi di fila.

## 8. Esempio

```markdown
# Rinnovo della rete

Una sintesi in **due** righe,
prima delle parti.

## Rete e collegamenti

### Rete locale

Le postazioni passano da un apparato di *vecchia generazione*.

- dodici postazioni
- due stampanti
  - una a colori

| Apparato | Anni |
|---|---:|
| commutatore | 9 |

![Copertura misurata](images/coverage.png)
```

dà un pacchetto con l'apertura `opening`, una parte `rete-e-collegamenti` con accento
`azure` e, nella sezione «Rete locale», un paragrafo, un elenco con un elenco annidato, una
tabella con la seconda colonna a destra e una figura.
