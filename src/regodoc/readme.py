"""Il ``README.md`` che il motore scrive in ogni pacchetto (specifica, §1.4).

È scritto nella lingua del documento, è deterministico, non porta date né versioni e resta
ben sotto il limite di 64 KiB. In lettura il motore lo ignora.
"""

import re
from typing import Final

SPECIFICATION: Final = "https://github.com/LorenzoGodi/regodoc/blob/main/docs/spec/rego-1.md"

# Caratteri che in Markdown cambierebbero il titolo: si scrivono con la barra rovescia.
_MARKDOWN = re.compile(r"([\\`*_\[\]<>|#])")

_TEXTS: Final = {
    "it": """# Pacchetto .regodoc: {title}

Questo file lo scrive il motore regodoc a ogni esportazione. Quando il pacchetto torna
indietro non conta, e ciò che vi si modifica va perso.

## Che cosa contiene

- `structure.toml`: intestazione, lingua e ordine delle parti;
- `variables.toml`: i valori nominati, come date, importi e quantità;
- `parts/`: il testo, un file XML per apertura o per parte, con il nome del suo id;
- `images/`: le figure, solo PNG o JPEG;
- `manifest.json` e `mimetype`: la busta, che scrive il motore.

## Come modificarlo

1. modifica `structure.toml`, `variables.toml` e i file in `parts/`, sempre in UTF-8;
2. metti le immagini in `images/` e richiamale nel testo con `<figure file="images/…"/>`;
3. controlla il pacchetto con `regodoc validate` e ricostruisci l'archivio con
   `regodoc canon`.

Le regole del formato sono nella specifica `rego/1` del progetto regodoc:
{specification}
""",
    "en": """# .regodoc package: {title}

The regodoc engine writes this file on every export. It is ignored when the package is
read back, and anything changed here is lost.

## What it contains

- `structure.toml`: header, language and order of the parts;
- `variables.toml`: the named values, such as dates, amounts and quantities;
- `parts/`: the text, one XML file per opening or part, named after its id;
- `images/`: the figures, PNG or JPEG only;
- `manifest.json` and `mimetype`: the envelope, written by the engine.

## How to change it

1. edit `structure.toml`, `variables.toml` and the files in `parts/`, always in UTF-8;
2. put the images in `images/` and refer to them in the text with
   `<figure file="images/…"/>`;
3. check the package with `regodoc validate` and rebuild the archive with
   `regodoc canon`.

The format is described in the `rego/1` specification of the regodoc project:
{specification}
""",
}


def render_readme(title: str, language: str) -> str:
    """Il testo di ``README.md`` per un documento con questo titolo e questa lingua."""
    escaped = _MARKDOWN.sub(r"\\\1", " ".join(title.split()))
    return _TEXTS[language].format(title=escaped, specification=SPECIFICATION)
