# regodoc

Motore del formato di pacchetto `.regodoc` per documenti tecnici. Un pacchetto è un archivio
ZIP con XML a vocabolario chiuso e TOML. Il motore lo valida, lo porta in forma canonica e ne
produce LaTeX e PDF riproducibili byte per byte. Usa solo la libreria standard di Python;
per il PDF serve TeX Live.

Rego lo usa come dipendenza con versione fissata. Chiunque può usarlo da solo, con Python
e TeX Live.

> **Stato:** in costruzione, verso la versione 0.1.0. Funzionano tutti i comandi: `info`,
> `validate`, `canon`, `build` e `upgrade`. La specifica del formato è in
> [`docs/spec/rego-1.md`](docs/spec/rego-1.md). Due pacchetti d'esempio, sintetici, sono in
> `examples/`: `colle-rovere/`, breve e in italiano, e `lakeside-rowing/`, lungo, in inglese,
> con tutto il vocabolario.

## Requisiti

- Python 3.12 o successivo, senza altre dipendenze.
- Per produrre PDF: pdflatex di TeX Live con i pacchetti Debian `lmodern`,
  `texlive-latex-base`, `texlive-latex-recommended`, `texlive-latex-extra`,
  `texlive-fonts-recommended`, `texlive-fonts-extra`, `texlive-lang-italian` e
  `texlive-science`. Il motore non usa pacchetti LaTeX fuori da questo insieme.
- La riproducibilità dei PDF byte per byte è provata con TeX Live 2023 di Ubuntu e nella CI su
  Debian trixie con TeX Live 2024, le cui versioni apt però non sono fissate: chi usa il
  motore la verifica sulla propria immagine TeX, con due compilazioni dello stesso pacchetto
  ([contratto](docs/contract.md), §10).

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
| `regodoc canon PACCHETTO -o USCITA` | Riscrive il pacchetto in forma canonica, con `README.md` e manifesto; `--document` e `--base-version` scrivono i campi del manifesto, `--files-dir` scrive anche i file uno per uno | pronto |
| `regodoc build PACCHETTO -o USCITA` | Produce PDF o LaTeX (`--format`), con un tema esterno (`--theme`) e un'intestazione (`--header`) | pronto |
| `regodoc upgrade PACCHETTO -o USCITA` | Porta il pacchetto alla grammatica corrente, in forma canonica; oggi `rego/1` è l'unica grammatica | pronto |

Ogni comando che legge un pacchetto accetta `--json`, che scrive il rapporto in JSON su stdout,
e `--strict`, che tratta gli avvisi come errori. Lo stesso comando si può chiamare con
`python -m regodoc`.

Chi usa il motore da un altro programma segue il [contratto](docs/contract.md): invocazione,
intestazione JSON, rapporto, dichiarazione di `info`, contratto del tema, grammatiche e
codici d'uscita. L'opzione `--contract N` dichiara la versione del contratto attesa.

### Codici d'uscita

0 esito positivo, 1 pacchetto rifiutato, 2 errore d'uso, 3 errore d'ambiente, 4 errore interno,
130 interrotto. La tabella normativa, con che cosa deve fare chi chiama, è nel §7 del
[contratto](docs/contract.md).

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
con Python 3.12, 3.13 e 3.14. Verifica anche l'installazione in un venv pulito. Un job TeX compila
due volte lo stesso sorgente sulla stessa base dell'immagine di produzione di Rego
(`python:3.12-slim` su Debian trixie, fissata per digest) con i pacchetti TeX Live elencati
sopra, e confronta i PDF byte per byte.

## Licenza

Apache-2.0, vedi `LICENSE`.
