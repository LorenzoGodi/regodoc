"""Regole sul testo della specifica (§5): insieme di caratteri, tipografia, posizioni."""

import re
import unicodedata
from collections.abc import Iterator

# Simboli tipografici ammessi oltre ad ASCII, Latin-1 e Latin Extended-A (§5.2).
_SYMBOLS = frozenset(
    "\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u2022\u20ac\u21d2\u2264\u2265\u2192\u2212"
)
_EXCLUDED = frozenset("\u00adŉ")
_TRIPLE_HYPHEN = re.compile(r"-{3,}")


def is_allowed_char(char: str, *, newline: bool = False, tab: bool = False) -> bool:
    """Dice se un carattere appartiene all'insieme chiuso del §5.2."""
    code = ord(char)
    if 0x20 <= code <= 0x7E:
        return True
    if char == "\n":
        return newline
    if char == "\t":
        return tab
    if 0xA0 <= code <= 0x17F:
        return char not in _EXCLUDED
    return char in _SYMBOLS


def describe_char(char: str) -> str:
    """Nome leggibile di un carattere per i messaggi d'errore: «U+202E RIGHT-TO-LEFT OVERRIDE»."""
    name = unicodedata.name(char, "")
    return f"U+{ord(char):04X} {name}".rstrip()


def bad_char_message(char: str) -> str:
    """Messaggio per un carattere fuori dall'insieme ammesso, con un consiglio quando serve."""
    if unicodedata.category(char) == "Mn":
        return (
            f"carattere combinante non ammesso ({describe_char(char)}): "
            "scrivi la lettera accentata come un solo carattere"
        )
    if char == "\t":
        return "tabulazione non ammessa qui"
    if char == "\n":
        return "a capo non ammesso qui"
    return f"carattere non ammesso ({describe_char(char)})"


def find_bad_chars(text: str, *, newline: bool = False, tab: bool = False) -> Iterator[int]:
    """Restituisce gli indici dei caratteri fuori dall'insieme ammesso."""
    for index, char in enumerate(text):
        if not is_allowed_char(char, newline=newline, tab=tab):
            yield index


def advance(line: int, column: int, text: str, index: int) -> tuple[int, int]:
    """Posizione del carattere ``text[index]`` se ``text`` comincia a ``(line, column)``."""
    before = text[:index]
    newlines = before.count("\n")
    if newlines:
        return line + newlines, index - before.rfind("\n")
    return line, column + index


def position_in(text: str, index: int) -> tuple[int, int]:
    """Riga e colonna, da 1, dell'indice ``index`` in un testo intero."""
    return advance(1, 1, text, index)


def collapse_spaces(text: str) -> str:
    """Spazi del testo misto (§5.1): spazi, tabulazioni e a capo diventano uno spazio."""
    return re.sub(r"[ \t\n\r]+", " ", text)


def triple_hyphen(text: str) -> int | None:
    """Indice della prima sequenza di tre o più trattini, se c'è (§5.3)."""
    match = _TRIPLE_HYPHEN.search(text)
    return match.start() if match else None


def plain_text_problems(value: str, *, max_length: int, min_length: int = 1) -> list[str]:
    """Problemi di un valore di testo puro: lunghezza, virgolette, trattini (§5.3).

    Restituisce messaggi in italiano, vuoto se il valore è corretto. I caratteri fuori elenco
    non sono fra questi problemi: chi chiama li segnala a parte con ``regodoc.text.char``.
    """
    problems = []
    length = len(value)
    if length < min_length or not value.strip():
        problems.append("il testo è vuoto")
    elif length > max_length:
        problems.append(f"il testo è lungo {length} caratteri, il massimo è {max_length}")
    if value.count('"') % 2:
        problems.append("virgolette dritte in numero dispari")
    if triple_hyphen(value) is not None:
        problems.append("tre o più trattini di fila: scrivi la lineetta — direttamente")
    return problems
