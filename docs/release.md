# Rilascio e versione fissata

Come si costruisce e si pubblica una versione di regodoc, e come chi lo usa, Rego per primo,
installa proprio quella versione verificandone le impronte (contratto, §11: «Copia fissata del
motore»).

## Che cosa costruisce la CI

A ogni commit il job «pacchetto riproducibile e installazione con le impronte» della CI:

1. installa flit_core con `pip install --require-hashes` da `tools/requirements/build.txt`;
2. costruisce con `tools/build_release.py --check` il wheel `regodoc-<versione>-py3-none-any.whl`
   e l'archivio sorgente `regodoc-<versione>.tar.gz`, con la data dell'ultimo commit come
   `SOURCE_DATE_EPOCH`; li costruisce una seconda volta con un'altra umask e ne confronta i
   byte; controlla nei metadati del wheel la versione e `License-Expression: Apache-2.0`;
3. scrive `SHA256SUMS`, nella forma di `sha256sum`;
4. installa il wheel con la sua impronta in un ambiente pulito, prova `regodoc info` e lancia
   tutte le prove con il motore importato dal wheel invece che da `src/`
   (`REGODOC_TEST_INSTALLED=1`): un file che manca nel wheel, o diverso da quello del
   sorgente, le fa fallire;
5. carica i tre file come artefatto `regodoc-<commit>`, con lo SHA completo del commit.

Nella stessa corsa il job «TeX sull'immagine di riferimento», sulla base dell'immagine di Rego e
con i suoi pacchetti TeX, scarica quell'artefatto e installa il wheel in un venv suo con
`--require-hashes` sull'impronta calcolata dal job del pacchetto, e la scrive nel log. Poi
lancia tutte le prove contro il wheel installato, con TeX obbligatorio, e
`tools/check_install.py`, che avvia il motore come lo avvia Rego: `info` con i controlli
della sezione «La versione fissata in Rego», poi `validate`, `canon` e `build` in PDF del
pacchetto d'esempio, ciascuno con `-I -B`, stdin da `/dev/null`, una cartella corrente vuota,
solo `PATH` e `TMPDIR` nell'ambiente e il gruppo di processi ucciso allo scadere del tempo
dichiarato più 10 secondi (contratto, §2.2 e §2.3).

Chiunque può rifare la costruzione dallo stesso commit e ottenere gli stessi byte. Lo
strumento costruisce dai file del commit estratti con `git archive`, non dall'albero di
lavoro: modifiche non committate e file non tracciati restano fuori, e lo strumento lo dice.
Basta un checkout del commit, anche non pulito:

```sh
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --require-hashes --no-deps -r tools/requirements/build.txt
.venv-build/bin/python tools/build_release.py --out dist --check
```

## Il rilascio

Lo fa Lorenzo, a mano; la versione non va su PyPI.

1. `main` è sul commit approvato, con la CI verde, e `__version__` in
   `src/regodoc/__init__.py` è la versione da rilasciare, senza suffissi `.dev`.
2. Scarica l'artefatto `regodoc-<commit>` della CI di quel commit e verifica i file con
   `sha256sum -c SHA256SUMS`. Se vuole una seconda prova, rifà la costruzione come sopra e
   confronta le impronte.
3. Crea il tag `v<versione>` su quel commit e la release su GitHub con i tre file
   dell'artefatto; nelle note della release copia il contenuto di `SHA256SUMS`.

**La versione dopo il rilascio.** Dopo il tag, `main` resta alla versione rilasciata finché
non entra il primo commit che cambia il motore, cioè un file sotto `src/regodoc/` (in
`__init__.py` conta tutto tranne la riga di `__version__`). Quel commit, o uno dello stesso
lotto, porta `__version__` a una versione `.dev` successiva: `0.1.1.dev0` dopo `0.1.0`, o
`0.2.0.dev0` se il lotto aggiunge funzioni. Così un wheel costruito da `main` dopo il rilascio
non porta il numero della release. I commit che non toccano il motore, come documenti, prove
e strumenti, lasciano la versione com'è. Il commit del rilascio successivo toglie `.dev`.
`tools/check_version.py --base origin/main`, nel job d'igiene della CI, rifiuta un lotto che
cambia il motore sopra una versione rilasciata senza alzarla, e ogni versione che scende o
non ha la forma `N.N.N` o `N.N.N.devN`.

## La versione fissata in Rego

Rego installa il wheel della release nel proprio ambiente virtuale, con un file di requisiti
che porta l'indirizzo del file e la sua impronta, presa da `SHA256SUMS` della release:

```text
regodoc @ https://github.com/LorenzoGodi/regodoc/releases/download/v0.1.0/regodoc-0.1.0-py3-none-any.whl \
    --hash=sha256:<impronta del wheel>
```

```sh
python -m pip install --require-hashes --no-deps -r requirements-regodoc.txt
python -I -B -m regodoc --contract 1 info
```

`--no-deps` è sicuro: il motore non ha dipendenze. Dopo ogni installazione Rego legge `info`
e controlla almeno `version`, che `contracts` contenga il contratto che usa, `expat` non
più vecchio di `expat_min` e `grammars`; poi chiama sempre il motore con `--contract`
(contratto, §2.1 e §5).

Per cambiare versione Rego cambia indirizzo e impronta nello stesso file e rilegge `info`;
per tornare indietro segue le condizioni del contratto, §11.

## Immagine di Rego

Questa sezione è solo documentazione: il Dockerfile di Rego lo cambia la sessione CI di Rego,
su una voce sua, non questo repository. Qui c'è quello che l'immagine deve dare al motore
perché funzioni come lo prova la CI (job «TeX sull'immagine di riferimento») e come lo
promette il contratto.

**Base e pacchetti.** La stessa base della CI, `python:3.12-slim` su Debian trixie fissata per
digest, con i pacchetti apt, senza i raccomandati:

```text
lmodern texlive-latex-base texlive-latex-recommended texlive-latex-extra
texlive-fonts-recommended texlive-fonts-extra texlive-lang-italian texlive-science
```

Le versioni apt non sono fissate: la riproducibilità dei PDF si verifica sull'immagine con due
compilazioni dello stesso pacchetto (contratto, §10).

**Installazione.** Un venv dedicato al motore, per esempio `/opt/regodoc`, creato con
l'interprete dell'immagine; il wheel della release si installa con il file di requisiti della
sezione precedente, `--require-hashes --no-deps`, durante la costruzione dell'immagine. Il
venv appartiene a root e il servizio non può scriverci.

**Esecuzione.** Il servizio che chiama il motore gira con un utente non root. Per ogni
chiamata:

- l'interprete del venv con `-I -B -m regodoc --contract 1` e `--json`;
- stdin da `/dev/null` e come cartella corrente una cartella temporanea vuota;
- nell'ambiente solo `PATH`, che deve contenere `pdflatex`, `TMPDIR`, una cartella
  scrivibile e pulita del servizio, e, se serve, `SOURCE_DATE_EPOCH`: il motore ignora ogni
  altra variabile (contratto, §2.2);
- un gruppo di processi suo (`start_new_session`), ucciso per intero con `SIGKILL` allo
  scadere di `resources.time_seconds` del comando più 10 secondi, trattando il caso come
  codice 3 con `regodoc.limit.time` (contratto, §2.3).

`tools/check_install.py` fa esattamente questo, ed è il riferimento da cui copiare:

```sh
python3 tools/check_install.py --python /opt/regodoc/bin/python --version 0.1.0
```

**Controllo di `info`.** All'avvio del servizio, o alla costruzione dell'immagine, Rego legge
`info` e confronta almeno questi campi; per la 0.1.0 i valori attesi sono:

```json
{
  "version": "0.1.0",
  "contract": 1,
  "contracts": [1],
  "expat_min": "2.6.0",
  "grammars": {"current": "rego/1", "read": ["rego/1"]},
  "commands": {
    "build": "ready",
    "canon": "ready",
    "info": "ready",
    "upgrade": "ready",
    "validate": "ready"
  },
  "resources": {
    "enforced": true,
    "memory_bytes": 1073741824,
    "memory_enforced_on": ["linux"],
    "time_seconds": {"build": 300, "canon": 60, "info": 5, "upgrade": 60, "validate": 30}
  }
}
```

`expat` dipende dalla libreria dell'interprete e non ha un valore atteso: deve essere almeno
`expat_min`, confrontando le versioni come numeri (`2.10.0` è più recente di `2.6.0`). Un
esempio sintetico del controllo, lo stesso di `info_problems` in `tools/check_install.py`:

```python
def info_problems(info: dict, version: str) -> list[str]:
    def number(text: str) -> tuple[int, ...]:
        return tuple(int(part) for part in text.split("."))

    problems = []
    if info["version"] != version:
        problems.append("versione diversa da quella fissata")
    if 1 not in info["contracts"]:
        problems.append("il motore non supporta il contratto 1")
    if number(info["expat"]) < number(info["expat_min"]):
        problems.append("expat troppo vecchio")
    if "rego/1" not in info["grammars"]["read"]:
        problems.append("il motore non legge la grammatica rego/1")
    return problems
```

Con un problema il servizio non usa il motore e lo segnala; non prova a chiamarlo comunque.
