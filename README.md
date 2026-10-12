# regodoc

Motore del formato di pacchetto `.regodoc` per documenti tecnici. Un pacchetto è un archivio
ZIP con XML a vocabolario chiuso e TOML. Il motore lo valida, lo porta in forma canonica e ne
produce LaTeX e PDF riproducibili byte per byte. Usa solo la libreria standard di Python;
per il PDF serve TeX Live.

Rego lo usa come dipendenza con versione fissata. Chiunque può usarlo da solo, con Python
e TeX Live.

> **Stato:** in costruzione. Funzionano `regodoc info` e `regodoc validate`. Gli altri
> comandi esistono, rispondono «non ancora implementato» ed escono con il codice 3, quello
> degli errori d'ambiente. La specifica del formato è in
> [`docs/spec/rego-1.md`](docs/spec/rego-1.md); un pacchetto d'esempio completo, sintetico,
> è in `examples/colle-rovere/`.

## Requisiti

- Python 3.12 o successivo, senza altre dipendenze.
- Per produrre PDF: pdflatex di TeX Live con i pacchetti Debian `lmodern`,
  `texlive-latex-base`, `texlive-latex-recommended`, `texlive-latex-extra`,
  `texlive-fonts-recommended`, `texlive-fonts-extra`, `texlive-lang-italian` e
  `texlive-science`. Il motore non usa pacchetti LaTeX fuori da questo insieme.

## Installazione

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/regodoc --version
```

## Comandi

| Comando | Che cosa fa | Stato |
|---|---|---|
| `regodoc info` | Stampa in JSON la versione del motore, la versione del contratto, le grammatiche lette e i limiti | pronto |
| `regodoc validate PACCHETTO` | Controlla un pacchetto, archivio o cartella, e ne elenca errori e avvisi | pronto |
| `regodoc canon PACCHETTO -o USCITA` | Riscrive il pacchetto in forma canonica | in arrivo |
| `regodoc build PACCHETTO -o USCITA` | Produce PDF o LaTeX (`--format`), con un tema esterno (`--theme`) e un'intestazione (`--header`) | in arrivo |
| `regodoc upgrade PACCHETTO -o USCITA` | Porta il pacchetto alla grammatica corrente | in arrivo |

Ogni comando che legge un pacchetto accetta `--json`, che scrive il rapporto in JSON su stdout,
e `--strict`, che tratta gli avvisi come errori. Lo stesso comando si può chiamare con
`python -m regodoc`.

### Codici d'uscita

| Codice | Significato |
|---|---|
| 0 | esito positivo, anche con avvisi |
| 1 | pacchetto rifiutato per errori di validazione, o per avvisi con `--strict`; il rapporto li elenca |
| 2 | errore d'uso: argomenti sbagliati, file mancante, opzione sconosciuta |
| 3 | errore d'ambiente: TeX assente, cartella non scrivibile, tempo massimo superato |
| 4 | errore interno del motore: non deve mai accadere, è un difetto da segnalare |
| 130 | interrotto |

## Sviluppo

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -t .
ruff check . && ruff format --check .
python3 tools/check_hygiene.py --commits origin/main..HEAD
```

La prova di compilazione TeX si salta se manca pdflatex. Con `REGODOC_REQUIRE_TEX=1`, come
nella CI, un pdflatex mancante diventa un errore.

### Regole del repository

- Il repository è pubblico. Esempi e documenti di prova sono sintetici e inventati: mai dati
  di clienti.
- Documenti, commenti, messaggi di commit e messaggi d'errore del motore sono in italiano.
  Nomi di file, elementi XML, chiavi TOML e valori chiusi del formato sono in inglese.
  Nel codice, i nomi sono in inglese e le docstring in italiano.
- La prima riga di ogni commit comincia con il lotto, per esempio `L2: specifica rego/1`.
  Non sono ammessi trailer.
- `tools/check_hygiene.py` controlla tutto questo, più codifica, fine riga, caratteri
  invisibili e un elenco di nomi vietati, conservato come impronte sha256.

### CI

La CI usa GitHub Actions ed esegue ruff, il controllo d'igiene e le prove su Linux e macOS
con Python 3.12 e 3.13. Verifica anche l'installazione in un venv pulito. Un job TeX compila
due volte lo stesso sorgente sulla stessa base dell'immagine di produzione di Rego
(`python:3.12-slim` su Debian trixie, fissata per digest) con i pacchetti TeX Live elencati
sopra, e confronta i PDF byte per byte.

## Licenza

Apache-2.0, vedi `LICENSE`.
