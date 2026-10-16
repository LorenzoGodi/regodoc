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

from regodoc.declaration import GRAMMAR_CURRENT

# I file della busta: non sono contenuto e nessun passo li riceve.
ENVELOPE = frozenset({"mimetype", "manifest.json", "README.md"})


@dataclass(frozen=True)
class Step:
    """Un passo della catena: da ``source`` a ``target``."""

    source: str
    target: str
    upgrade: Callable[[Mapping[str, bytes]], dict[str, bytes]]


# Un passo per grammatica precedente. rego/1 è la prima grammatica pubblicata: la catena è
# vuota finché non nasce rego/2. Le prove vi aggiungono una grammatica fittizia per la loro
# durata.
STEPS: dict[str, Step] = {}


def readable() -> tuple[str, ...]:
    """Le grammatiche lette, dalla più vecchia alla corrente."""
    return (*STEPS, GRAMMAR_CURRENT)


def chain(grammar: str) -> list[Step]:
    """I passi da ``grammar`` alla grammatica corrente, in ordine."""
    steps: list[Step] = []
    while grammar != GRAMMAR_CURRENT:
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
