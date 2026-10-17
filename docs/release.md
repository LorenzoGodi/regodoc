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
