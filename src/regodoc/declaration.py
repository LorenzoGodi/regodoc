"""Dichiarazione del motore: versione, grammatiche, limiti e capacità.

Rego legge questi valori dal comando ``regodoc info`` e li applica senza averli scritti
nel proprio codice (terza regola dell'autonomia). Ogni valore qui è normativo: cambiarlo
cambia il contratto e va registrato nella specifica.

Le unità dei limiti sono binarie: 1 KiB = 1024 byte, 1 MiB = 1024 KiB (CP-72), per coerenza
con i limiti in byte di Rego, che sono potenze di due.
"""

from types import MappingProxyType
from typing import Final

from regodoc import __version__

ENGINE_NAME: Final = "regodoc"

# Versione del contratto fra Rego e il motore. Resta 0 finché il lotto L3 non lo fissa:
# con la versione 0 il contratto può ancora cambiare senza preavviso.
CONTRACT_VERSION: Final = 0

# Grammatica scritta dal motore e grammatiche che sa leggere, dalla più vecchia.
GRAMMAR_CURRENT: Final = "rego/1"
GRAMMARS_READ: Final = ("rego/1",)

_KIB: Final = 1024
_MIB: Final = 1024 * _KIB

# Limiti dell'involucro: li applica Rego all'ingresso e li ripete il motore.
ENVELOPE_LIMITS: Final = MappingProxyType(
    {
        "compressed_bytes": 12 * _MIB,
        "expanded_bytes": 40 * _MIB,
        "compression_ratio": 20,
        "files": 200,
    }
)

# Limiti del contenuto: li dichiara il motore.
CONTENT_LIMITS: Final = MappingProxyType(
    {
        "parts": 48,
        "characters": 1_500_000,
        "part_bytes": 384 * _KIB,
        "images": 80,
        "image_bytes": 8 * _MIB,
        "images_total_bytes": 40 * _MIB,
        "table_rows": 600,
        "table_columns": 10,
        "table_columns_normal_size": 8,
        "cell_characters": 2000,
        "variables": 1500,
        "structure_bytes": 64 * _KIB,
        "variables_bytes": 384 * _KIB,
        "manifest_bytes": 64 * _KIB,
        "image_side_pixels": 6000,
        "section_depth": 3,
        "list_depth": 3,
        "element_depth": 24,
        "references": 10_000,
        "sources": 500,
        "href_characters": 2000,
        "listing_line_characters": 200,
    }
)

# Stato dei comandi: "draft" vuol dire che il comando esiste ma non fa ancora il suo lavoro
# ed esce con il codice d'ambiente 3; sparisce entro la versione 0.1.0.
COMMANDS: Final = MappingProxyType(
    {
        "info": "ready",
        "validate": "ready",
        "canon": "draft",
        "build": "draft",
        "upgrade": "draft",
    }
)


def describe() -> dict[str, object]:
    """Restituisce la dichiarazione completa del motore, pronta per JSON."""
    return {
        "engine": ENGINE_NAME,
        "version": __version__,
        "contract": CONTRACT_VERSION,
        "grammars": {"current": GRAMMAR_CURRENT, "read": list(GRAMMARS_READ)},
        "limits": {
            "envelope": dict(ENVELOPE_LIMITS),
            "content": dict(CONTENT_LIMITS),
        },
        "commands": dict(COMMANDS),
    }
