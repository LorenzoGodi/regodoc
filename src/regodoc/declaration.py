"""Dichiarazione del motore: versione, grammatiche, limiti e capacità.

Rego legge questi valori dal comando ``regodoc info`` e li applica senza averli scritti
nel proprio codice (terza regola dell'autonomia). Ogni valore qui è normativo. Il §9 del
contratto dice quali cambiamenti non cambiano il contratto (per esempio limiti del contenuto
più alti, capacità e lingue in più) e quali lo cambiano (per esempio un limite
dell'involucro più basso o una chiave tolta).

Le unità dei limiti sono binarie: 1 KiB = 1024 byte, 1 MiB = 1024 KiB (specifica, §0 e §7),
per coerenza con i limiti in byte di Rego, che sono potenze di due.
"""

import xml.parsers.expat
from types import MappingProxyType
from typing import Final

from regodoc import __version__

ENGINE_NAME: Final = "regodoc"

# Tipo e estensione del pacchetto (specifica, §1.2): chi usa il motore li legge da qui.
PACKAGE_MIMETYPE: Final = "application/vnd.regodoc.document"
PACKAGE_EXTENSION: Final = ".regodoc"

# Versione del contratto fra Rego e il motore (docs/contract.md), approvata il 14/10/2026.
CONTRACT_VERSION: Final = 1
# Versioni del contratto che il motore sa servire con --contract. La bozza dichiarata come 0
# non è servita (contratto, §9).
CONTRACTS: Final = (1,)

# La versione minima di expat: dalla 2.6.0 expat limita la rianalisi dei token lunghi, che
# prima costava tempo quadratico. La CI la controlla su ogni interprete della matrice.
EXPAT_MIN: Final = (2, 6, 0)

# Grammatica scritta dal motore e grammatiche che sa leggere, dalla più vecchia.
GRAMMAR_CURRENT: Final = "rego/1"
GRAMMARS_READ: Final = ("rego/1",)

_KIB: Final = 1024
_MIB: Final = 1024 * _KIB

# Limiti dell'involucro: li applica il motore; chi riceve il pacchetto controlla all'ingresso
# solo la dimensione e la firma (contratto, §3.1).
ENVELOPE_LIMITS: Final = MappingProxyType(
    {
        "compressed_bytes": 12 * _MIB,
        "expanded_bytes": 40 * _MIB,
        "compression_ratio": 100,
        "image_compression_ratio": 20,
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
        # Coincide con il tetto dell'involucro, che lo applica: le immagini stanno nel
        # contenuto espanso (contratto, §5.1).
        "images_total_bytes": 40 * _MIB,
        "table_rows": 600,
        "table_columns": 10,
        "table_columns_normal_size": 8,
        "cell_characters": 2000,
        "variables": 1500,
        "number_abs_max": 10**15,
        "problems": 500,
        "structure_bytes": 64 * _KIB,
        "variables_bytes": 384 * _KIB,
        "manifest_bytes": 64 * _KIB,
        "readme_bytes": 64 * _KIB,
        "image_side_pixels": 6000,
        # Byte dei pixel di un PNG, larghezza × altezza × byte per pixel: un'immagine RGBA a
        # 8 bit di 6000 × 6000 pixel. Il motore li decomprime per controllarli, e così fa
        # pdfTeX: il tetto ne limita tempo e memoria.
        "image_pixel_bytes": 144_000_000,
        # Lo stesso, per tutte le immagini del pacchetto.
        "images_pixel_bytes": 600_000_000,
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
        "build": "ready",
        "upgrade": "draft",
    }
)


# Risorse per comando: tempo massimo in secondi e memoria (contratto, §2.3 e §5).
RESOURCES: Final = MappingProxyType(
    {
        "time_seconds": MappingProxyType(
            {"info": 5, "validate": 30, "canon": 30, "build": 300, "upgrade": 60}
        ),
        "memory_bytes": 1024 * _MIB,
        # I sistemi dove il motore limita da sé la memoria, con RLIMIT_AS: altrove il
        # limite dello spazio d'indirizzi non è applicato dal sistema (contratto, §2.3).
        "memory_enforced_on": ("linux",),
        # Il motore applica da sé il tempo e, dove può, la memoria (regodoc/limits.py).
        "enforced": True,
    }
)

# Contratto del tema (contratto, §6): versioni supportate, ruoli della tavolozza, agganci.
THEME_CONTRACTS: Final = (1,)
THEME_ROLES: Final = (
    "azure",
    "slate",
    "sage",
    "bronze",
    "plum",
    "brick",
    "olive",
    "gray",
    "ok",
    "warning",
    "critical",
    "muted",
)
THEME_HOOKS: Final = (
    "RegodocThemeSetup",
    "RegodocTitlePage",
    "RegodocPageStyle",
    "RegodocPartOpening",
    "RegodocOpeningStart",
    "RegodocBox",
    "RegodocLabel",
)
# Limiti della cartella di un tema esterno (contratto, §3.3).
THEME_LIMITS: Final = MappingProxyType({"files": 200, "bytes": 8 * _MIB})

# Capacità stabili di questa versione (docs/contract.md, §5 e §9).
CAPABILITIES: Final = (
    "validate",
    "validate.directory",
    "build.pdf",
    "build.latex",
    "build.theme",
)

LANGUAGES: Final = ("it", "en")

# Passate di pdflatex che build può eseguire: due per indice e rimandi, una in più per le
# citazioni, una di riserva per i riferimenti che si spostano.
PASSES: Final = MappingProxyType({"min": 2, "max": 4})

# Pacchetti LaTeX che regodoc.sty e il tema neutro caricano direttamente, cioè quelli che
# chiedono all'immagine TeX (contratto, §6.1). Una prova li confronta con regodoc.sty.
TEX_PACKAGES: Final = (
    "array",
    "babel",
    "booktabs",
    "enumitem",
    "fancyhdr",
    "fontenc",
    "geometry",
    "graphicx",
    "hyperref",
    "lmodern",
    "longtable",
    "microtype",
    "pdflscape",
    "tcolorbox",
    "textcomp",
    "xcolor",
)


def describe() -> dict[str, object]:
    """Restituisce la dichiarazione completa del motore, pronta per JSON."""
    return {
        "engine": ENGINE_NAME,
        "version": __version__,
        # La versione di expat con cui questo interprete legge le parti: le difese del
        # lettore XML dipendono anche da lei (specifica, §6.3).
        "expat": ".".join(str(n) for n in xml.parsers.expat.version_info),
        "expat_min": ".".join(str(n) for n in EXPAT_MIN),
        "contract": CONTRACT_VERSION,
        "contracts": list(CONTRACTS),
        "package": {"mimetype": PACKAGE_MIMETYPE, "extension": PACKAGE_EXTENSION},
        "grammars": {"current": GRAMMAR_CURRENT, "read": list(GRAMMARS_READ)},
        "limits": {
            "envelope": dict(ENVELOPE_LIMITS),
            "content": dict(CONTENT_LIMITS),
        },
        "resources": {
            "time_seconds": dict(RESOURCES["time_seconds"]),
            "memory_bytes": RESOURCES["memory_bytes"],
            "memory_enforced_on": list(RESOURCES["memory_enforced_on"]),
            "enforced": RESOURCES["enforced"],
        },
        "commands": dict(COMMANDS),
        "capabilities": list(CAPABILITIES),
        "languages": list(LANGUAGES),
        "passes": dict(PASSES),
        "tex": {"packages": list(TEX_PACKAGES)},
        "theme": {
            "contracts": list(THEME_CONTRACTS),
            "roles": list(THEME_ROLES),
            "hooks": list(THEME_HOOKS),
            "limits": dict(THEME_LIMITS),
        },
    }
