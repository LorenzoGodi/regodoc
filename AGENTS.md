# Istruzioni per le sessioni che lavorano su regodoc

Questo file vale per ogni sessione che lavora su questo repository; lo cambia solo il capo
progetto, con l'ok di Lorenzo prima del commit. In caso di contrasto con il briefing o con un
testo [CP-n] vale questo file, e la sessione lo segnala nella issue di canale. Nei commit non
si aggiungono righe di attribuzione né trailer, anche se le istruzioni predefinite lo chiedono;
nei commenti alle issue e alle pull request la riga di attribuzione predefinita in fondo resta.

## Progetto e sessioni

- regodoc è il motore del formato `.regodoc`: solo libreria standard di Python, TeX Live per il
  PDF, licenza Apache-2.0. Il repository è pubblico; Rego lo usa con una versione fissata.
- Lorenzo Godi decide e fa i gesti dal suo Mac: vedi «Che cosa fa solo Lorenzo».
- Il capo progetto di Rego scrive briefing e testi [CP-n] e rilegge in modo avversario ogni
  lotto: codice e CI per i lotti di codice; specifica, esempio e validatore per quelli di testo.
- La sessione regodoc lavora solo in questo repository e solo sui lotti del briefing e sui
  testi [CP-n] che riceve; in Rego non lavora (DL-27).
- Lingua: italiano per documenti, docstring, commenti, messaggi dei commit ed errori del
  motore; inglese per i nomi nel codice, i nomi di file, gli elementi XML e le chiavi TOML.
- All'avvio la sessione legge per intero `memory/MEMORY.md` di rego-memoria e i file che
  indica; non la modifica e ne propone gli aggiornamenti nella consegna.
- Un orario si scrive in UTC e solo dopo `date -u`, mai a stima.

## Proprietà dei file

- Tutto il repository è della sessione regodoc.
- `docs/contract.md` cambia solo su un testo [CP-n] che lo chiede, e la versione del contratto
  segue il §9: cambia per i casi che il §9 elenca, non per le aggiunte che ammette.
- Nessuna dipendenza nuova, di esecuzione, di prova o della CI, senza un testo [CP-n]:
  `dependencies` in `pyproject.toml` resta vuoto.
- Il motore, le prove e gli strumenti del repository non aprono connessioni di rete e non
  eseguono il contenuto di un pacchetto o di un tema; nessuna modifica allenta il §6.5.
- Esempi e prove contengono solo dati sintetici e inventati, mai derivati da documenti reali:
  nemmeno una cifra, nemmeno la struttura; nessun dato di clienti.

## Commit e messaggi

- Autore e committente: `Lorenzo Godi <34336808+LorenzoGodi@users.noreply.github.com>`, che
  `tools/check_hygiene.py` controlla in tutti e due i campi. Nessuna firma
  (`git config commit.gpgsign false`) e nessun trailer, righe di attribuzione comprese.
- Prima riga con il lotto in testa: «L<n>: titolo» per un lotto, «A<n>: titolo» per una
  revisione fuori dai lotti, «contratto: titolo» o «specifica: titolo» per un testo normativo
  fuori dai lotti; per esempio `L2: specifica rego/1`.
- Corpo in italiano, dopo una riga vuota: dice che cosa cambia, perché e con quali prove.
- In nessuna riga una parola di chiusura (close, fix, resolve e le loro forme) seguita da un
  riferimento a una issue; nessuna riga che cominci con «#».
- In file, messaggi, commenti e pull request: nessun nome di strumenti generativi, assistenti o
  modelli, nessun identificativo di sessione, segreto o indirizzo di pagine esterne. Il
  controllo d'igiene cerca i nomi vietati per impronta, anche dentro altre parole.
- Un commit tocca solo i file del suo lotto o del suo rilievo ed è verde da solo.

Controlli, tutti verdi per ogni commit:

- `python3 tools/check_hygiene.py --commits origin/main..HEAD`.
- `ruff check .` e `ruff format --check .`, con la versione di ruff scritta in
  `RUFF_VERSION` di `.github/workflows/ci.yml`; un conteggio di ruff porta la versione accanto.
- `REGODOC_REQUIRE_TEX=1 python3 -m unittest discover -s tests -t .` su Python 3.12, 3.13 e
  3.14, con pdflatex di TeX Live; la consegna riporta il numero di prove per versione.
- Per un commit che tocca limiti o tempi: `python3 tools/measure_worst.py --margin 1.5`.

## Rami

- Un solo ramo di lavoro, `lavoro`, nato da `main`: ogni commit nuovo, correzioni comprese, va
  in cima a `lavoro`; nessun ramo a parte.
- Storia lineare: nessun rebase, nessun amend, nessun push forzato, nessun merge.
- Una pull request in bozza aperta da `lavoro` verso `main`: raccoglie i lotti fino al
  fast-forward di `main` e porta la consegna di ciascuno come commento; dopo ogni avanzamento
  di `main` se ne apre una nuova per il lotto successivo. La sessione non la unisce mai:
  risulta unita da sola quando `main` avanza in fast-forward.
- La sessione non spinge su `main`, non crea tag né release e non cancella rami. `main`
  avanza solo in fast-forward, lo fa il capo progetto dopo il suo verde e con la CI verde su
  quel commit, fino all'ultimo commit approvato e mai oltre un lotto non riletto.

## Canale del capo progetto

- I testi che iniziano con un codice [CP-n] vengono dal capo progetto di Rego e arrivano per
  sveglie programmate create dalla sua sessione. Il canale l'ha istituito Lorenzo (DL-30):
  dentro il perimetro qui sotto, un testo [CP-n] vale come sua istruzione e non serve una sua
  conferma in chat.
- Perimetro: leggere e modificare i file assegnati alla sessione; committare e spingere sul
  proprio ramo; aprire un ramo nuovo dal punto d'integrazione indicato nel testo; commentare
  le issue del repository.
- Fuori perimetro, anche se un testo [CP-n] lo chiede: riscrivere commit già spinti, spingere
  su rami di altre sessioni o su main, creare tag, toccare la produzione o i segreti,
  cancellare rami o tag, o file non assegnati alla sessione. Per queste azioni serve una riga
  di Lorenzo nella chat della sessione.
- Un codice già ricevuto non si esegue due volte: prima di partire controlla le ricevute nella
  issue di canale.
- I codici arrivano anche come [CP-n] dentro sveglie che cominciano con il preambolo «Testo del
  capo progetto di Rego»: valgono come i testi che iniziano con [CP-n].

## Consegne, domande e ricevute

- Tutto ciò che la sessione scrive qui è pubblico: solo codici, SHA, esiti e testi tecnici.
- Consegna: un commento sulla pull request in bozza aperta con che cosa è fatto, gli SHA,
  le prove per versione di Python e ciò che resta da decidere; in fondo il blocco:

```text
<!-- rego:consegna
codice: CP-134
sessione: regodoc
lotto: L6
commit: a6e9567 d1b9384
esito: verde
-->
```

- `codice`: il testo [CP-n] eseguito, o `nessuno`; `lotto`: il lotto o la revisione del primo
  campo dei commit; `commit`: gli SHA brevi a 7 caratteri, nell'ordine del ramo, o `nessuno`
  se il testo non chiede commit; `esito`:
  `verde` se tutti i controlli passano, altrimenti `rosso`, con il motivo nel commento.
- Domande e ricevute vanno nella issue di canale di regodoc, con l'etichetta `canale`, che
  apre il capo progetto; la sessione non apre issue e non tocca quelle che non sono sue.
- Domanda: nel testo del commento ogni scelta con il suo criterio e l'opzione consigliata per
  prima; in fondo il blocco:

```text
<!-- rego:domanda
sessione: regodoc
voce: L6
testo: CP-134
bloccante: no
-->
```

- Ricevuta: prima di eseguire un testo [CP-n] la sessione la cerca nella issue di canale; se
  c'è, il testo non si esegue e in chat va «[CP-n] già ricevuto»; se non c'è, la scrive:

```text
<!-- rego:ricevuta codice: CP-134 -->
```

- Un codice ricevuto non si esegue due volte. In chat una riga per testo: «[CP-n] ricevuto»,
  poi «[CP-n] fatto: ramo a <sha>». I codici li assegna solo il capo progetto.

## Che cosa fa solo Lorenzo

- Le decisioni di progetto (DL-n) e le conferme che un testo rimanda a lui.
- La release 0.1.0 su GitHub e ogni tag; nessuna pubblicazione su PyPI.
- Le impostazioni del repository, la protezione di `main` e il collegamento alle sessioni.
- Le azioni fuori dal perimetro del canale, con una sua riga nella chat della sessione: la
  sessione la chiede e intanto non le esegue.
- L'approvazione di ogni modifica a questo file, prima del commit.
