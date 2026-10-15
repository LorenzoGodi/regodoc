"""Le parole che il motore stampa da sé e la resa dei valori, nelle lingue del documento.

Tutto ciò che qui produce testo restituisce testo puro, non ancora trascritto per il LaTeX:
la trascrizione la fa ``render``. La resa segue la lingua del documento (specifica, §3.1 e
§5.6); i valori in ``variables.toml`` sono sempre scritti all'italiana.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from regodoc.tomlfiles import ITALIAN_NUMBER, Variable

# Il segno meno tipografico (U+2212) e il trattino breve degli intervalli (U+2013).
MINUS: Final = "−"
EN_DASH: Final = "–"


@dataclass(frozen=True)
class Words:
    """Le parole di una lingua."""

    months: tuple[str, ...]
    part: str
    parts: str
    figure: str
    contents: str
    sources: str
    legend: str
    accessed: str
    labels: MappingProxyType[str, str]
    boxes: MappingProxyType[str, str]
    units: MappingProxyType[str, tuple[str, str]]
    decimal: str
    thousands: str


WORDS: Final = MappingProxyType(
    {
        "it": Words(
            months=(
                "gennaio",
                "febbraio",
                "marzo",
                "aprile",
                "maggio",
                "giugno",
                "luglio",
                "agosto",
                "settembre",
                "ottobre",
                "novembre",
                "dicembre",
            ),
            part="Parte",
            parts="Parti",
            figure="Figura",
            contents="Indice",
            sources="Fonti",
            legend="Legenda delle etichette",
            accessed="consultata il",
            labels=MappingProxyType(
                {
                    "observed": "osservato",
                    "declared": "dichiarato",
                    "decided": "deciso",
                    "proposed": "proposto",
                    "to-verify": "da verificare",
                    "critical": "critico",
                }
            ),
            boxes=MappingProxyType(
                {"status": "", "note": "Nota", "warning": "Attenzione", "critical": "Critico"}
            ),
            units=MappingProxyType(
                {
                    "hours": ("ora", "ore"),
                    "days": ("giorno", "giorni"),
                    "months": ("mese", "mesi"),
                }
            ),
            decimal=",",
            thousands=".",
        ),
        "en": Words(
            months=(
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            part="Part",
            parts="Parts",
            figure="Figure",
            contents="Contents",
            sources="Sources",
            legend="Label legend",
            accessed="accessed",
            labels=MappingProxyType(
                {
                    "observed": "observed",
                    "declared": "declared",
                    "decided": "decided",
                    "proposed": "proposed",
                    "to-verify": "to verify",
                    "critical": "critical",
                }
            ),
            boxes=MappingProxyType(
                {"status": "", "note": "Note", "warning": "Attention", "critical": "Critical"}
            ),
            units=MappingProxyType(
                {
                    "hours": ("hour", "hours"),
                    "days": ("day", "days"),
                    "months": ("month", "months"),
                }
            ),
            decimal=".",
            thousands=",",
        ),
    }
)

# Dal vocabolario ai ruoli della tavolozza (contratto, §6.2). Il tema riceve solo i ruoli.
LABEL_ROLES: Final = MappingProxyType(
    {
        "observed": "slate",
        "declared": "plum",
        "decided": "ok",
        "proposed": "azure",
        "to-verify": "warning",
        "critical": "critical",
    }
)
BOX_ROLES: Final = MappingProxyType({"note": "muted", "warning": "warning", "critical": "critical"})
# Un riquadro «status» prende il ruolo dell'accento della parte che lo contiene.


def roman(number: int) -> str:
    """Il numero romano di una parte, da 1."""
    if number < 1:
        raise ValueError(number)
    values = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    out = []
    for value, letters in values:
        while number >= value:
            out.append(letters)
            number -= value
    return "".join(out)


def format_date(day: datetime.date, language: str) -> str:
    """Una data per esteso: «5 ottobre 2026», «5 October 2026»."""
    return f"{day.day} {WORDS[language].months[day.month - 1]} {day.year}"


def _group(digits: str, separator: str) -> str:
    """Raggruppa per migliaia una stringa di cifre."""
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return separator.join(groups)


def format_number(value: object, language: str) -> str:
    """Un intero o un numero italiano nella forma della lingua del documento.

    Un numero italiano conserva i decimali così come sono scritti; un intero prende il
    separatore delle migliaia da 1.000 in su, come lo vuole il numero italiano (§3.1).
    """
    words = WORDS[language]
    if isinstance(value, bool):  # pragma: no cover - la validazione lo esclude
        raise TypeError(value)
    if isinstance(value, int):
        sign = MINUS if value < 0 else ""
        return sign + _group(str(abs(value)), words.thousands)
    if not isinstance(value, str) or not ITALIAN_NUMBER.fullmatch(value):
        raise ValueError(value)
    sign = MINUS if value.startswith("-") else ""
    integer, _, decimals = value.lstrip("-").partition(",")
    text = _group(integer.replace(".", ""), words.thousands)
    if decimals:
        text += words.decimal + decimals
    return sign + text


def format_eur(value: object, language: str) -> str:
    """Un importo senza unità: senza decimali se i centesimi sono zero, altrimenti con due."""
    if isinstance(value, int):
        cents = Decimal(value) * 100
    else:
        cents = Decimal(str(value).replace(".", "").replace(",", ".")) * 100
    cents = int(cents)
    sign = MINUS if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    words = WORDS[language]
    text = _group(str(units), words.thousands)
    if rest:
        text += f"{words.decimal}{rest:02d}"
    return sign + text


def _is_one(value: object) -> bool:
    """Il valore scritto 1 o "1": solo lui prende l'unità al singolare (§3.1)."""
    return (value == 1 and not isinstance(value, bool)) or value == "1"


@dataclass(frozen=True)
class Rendered:
    """Un valore reso: il testo, e se va in carattere monospaziato."""

    text: str
    mono: bool = False


def render_variable(variable: Variable, form: str, language: str) -> Rendered:
    """La resa di una variabile per un richiamo ``<var/>`` con la forma data (§3.2)."""
    kind = variable.type
    mono = kind in ("gb", "tb", "count")
    if kind == "date":
        return Rendered(format_date(variable.value, language))  # type: ignore[arg-type]
    if kind == "text":
        return Rendered(str(variable.value))
    values: tuple[object, ...]
    if variable.is_range:
        low, high = variable.value  # type: ignore[misc]
        values = {"min": (low,), "max": (high,)}.get(form, (low, high))
    else:
        values = (variable.value,)
    number = format_eur if kind == "eur" else format_number
    shown = EN_DASH.join(number(value, language) for value in values)
    if form == "number":
        return Rendered(shown, mono)
    return Rendered(_with_unit(kind, shown, values, language), mono)


def _with_unit(kind: str, shown: str, values: tuple[object, ...], language: str) -> str:
    nbsp = " "
    if kind in ("gb", "tb"):
        return f"{shown}{nbsp}{kind.upper()}"
    if kind == "percent":
        return f"{shown}%"
    if kind == "eur":
        return f"EUR{nbsp}{shown}" if language == "en" else f"{shown}{nbsp}euro"
    if kind in ("hours", "days", "months"):
        singular, plural = WORDS[language].units[kind]
        unit = singular if len(values) == 1 and _is_one(values[0]) else plural
        return f"{shown}{nbsp}{unit}"
    return shown  # count e number: nessuna unità
