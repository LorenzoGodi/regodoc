"""Le grammatiche che il motore legge e la catena degli aggiornatori (specifica, §10;
contratto, §8).

Un passo porta i file di contenuto da una grammatica alla successiva. È una funzione pura e
totale: non legge altro che i file che riceve, dà sempre la stessa uscita e non solleva
eccezioni. Ciò che non sa aggiornare lo lascia com'è, e lo segnala la validazione nella
grammatica corrente, che segue sempre l'ultimo passo. Dove può, un passo conserva le righe,
così gli errori trovati dopo l'aggiornamento indicano la riga del file ricevuto.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from regodoc.declaration import CONTENT_LIMITS, GRAMMAR_CURRENT
from regodoc.images import strip_image

# I file della busta: non sono contenuto e nessun passo li riceve.
ENVELOPE = frozenset({"mimetype", "manifest.json", "README.md"})


@dataclass(frozen=True)
class Step:
    """Un passo della catena: da ``source`` a ``target``."""

    source: str
    target: str
    upgrade: Callable[[Mapping[str, bytes]], dict[str, bytes]]


# Le grammatiche la cui forma canonica scrive le immagini così come sono: in rego/2 le
# immagini sono senza metadati (specifica, §13).
VERBATIM_IMAGES = frozenset({"rego/1"})
# Le grammatiche con le sole immagini a pixel: le figure in PDF vettoriale nascono con rego/2
# (specifica, §13).
RASTER_ONLY = frozenset({"rego/1"})


def rego1_to_rego2(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Il passo da rego/1 a rego/2: le immagini senza metadati, a pixel invariati; il resto
    com'è. Un'immagine oltre il limite di dimensione resta com'è, e la rifiuta la validazione."""
    result = {}
    for path, data in files.items():
        if path.startswith("images/") and len(data) <= CONTENT_LIMITS["image_bytes"]:
            data = strip_image(path, data)[0]  # noqa: PLW2901
        result[path] = data
    return result


# Un passo per grammatica precedente, da rego/1, la prima pubblicata. Le prove vi aggiungono
# una grammatica fittizia per la loro durata.
STEPS: dict[str, Step] = {"rego/1": Step("rego/1", "rego/2", rego1_to_rego2)}


def readable() -> tuple[str, ...]:
    """Le grammatiche lette, dalla più vecchia alla corrente."""
    return (*STEPS, GRAMMAR_CURRENT)


def chain(grammar: str) -> list[Step]:
    """I passi da ``grammar`` alla grammatica corrente, in ordine."""
    steps: list[Step] = []
    while grammar != GRAMMAR_CURRENT:
        # Un passo per grammatica: più passi di quante grammatiche ci sono vuol dire un ciclo.
        if grammar not in STEPS or len(steps) == len(STEPS):
            raise ValueError(f"catena delle grammatiche interrotta a «{grammar}»")
        step = STEPS[grammar]
        steps.append(step)
        grammar = step.target
    return steps


def upgrade(files: Mapping[str, bytes], grammar: str) -> dict[str, bytes]:
    """I file del pacchetto portati alla grammatica corrente; la busta resta com'è."""
    envelope = {path: data for path, data in files.items() if path in ENVELOPE}
    content: Mapping[str, bytes] = {
        path: data for path, data in files.items() if path not in ENVELOPE
    }
    for step in chain(grammar):
        content = step.upgrade(content)
    return {**envelope, **content}
