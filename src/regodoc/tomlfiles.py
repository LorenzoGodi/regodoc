"""Lettura e validazione di ``structure.toml`` e ``variables.toml`` (specifica §2, §3, §6.3)."""

import datetime
import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal

from regodoc.declaration import CONTENT_LIMITS
from regodoc.diagnostics import Collector
from regodoc.source import ID
from regodoc.text import bad_char_message, find_bad_chars, plain_text_problems, position_in

LANGUAGES = ("it", "en")
ACCENTS = ("azure", "slate", "sage", "bronze", "plum", "brick", "olive", "gray")
NUMERIC_TYPES = ("gb", "tb", "count", "number", "percent", "eur", "hours", "days", "months")
VARIABLE_TYPES = ("date", *NUMERIC_TYPES, "text")
VARIABLE_NAME = re.compile(r"[a-z][A-Za-z0-9]{0,47}")
# Primo gruppo senza zeri iniziali, salvo lo 0 da solo, che non ha gruppi dopo di sé.
ITALIAN_NUMBER = re.compile(r"-?(?:0|[1-9]\d{0,2}(?:\.\d{3})*)(?:,\d+)?")
_MAX_INTEGER = int(CONTENT_LIMITS["number_abs_max"])
# Tipi che ammettono valori negativi (§3.1).
NEGATIVE_TYPES = frozenset({"number", "percent", "eur"})
_TOML_ERROR_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")
_TOML_ERROR_END = re.compile(r"\(at end of document\)")


@dataclass(frozen=True)
class PartEntry:
    """Un'apertura o una parte dichiarata in ``structure.toml``."""

    id: str
    kind: str  # "opening" oppure "part"
    title: str = ""
    accent: str = ""
    number: int = 0  # numero d'ordine delle parti, da 1; 0 per le aperture


@dataclass
class Structure:
    """Il contenuto validato di ``structure.toml``."""

    language: str = "it"
    toc: bool = False
    header: dict[str, object] = field(default_factory=dict)
    entries: list[PartEntry] = field(default_factory=list)
    # Voci dichiarate ma escluse da ``entries`` perché il loro id non è valido, o perché
    # l'array che le contiene non è un array di tabelle. Con almeno una voce esclusa il
    # motore non sa a quale file corrisponde: una parte «orfana» potrebbe essere sua.
    invalid_entries: int = 0


@dataclass(frozen=True)
class Variable:
    """Una variabile validata: tipo, valore (o coppia di valori) e riga nel file."""

    name: str
    type: str
    value: object
    is_range: bool
    line: int


# --- Strumenti comuni ------------------------------------------------------------------------


def decode_toml(data: bytes, file: str, report: Collector, limit: int) -> str | None:
    """Decodifica un file TOML controllando dimensione, codifica e caratteri ammessi."""
    if len(data) > limit:
        report.error(
            "regodoc.limit.file_size",
            f"il file è di {len(data)} byte, il massimo è {limit}",
            file,
        )
        return None
    if data.startswith(b"\xef\xbb\xbf"):
        report.error("regodoc.text.bom", "il file comincia con un BOM: salvalo senza", file, 1, 1)
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        prefix = data[: error.start].decode("utf-8")
        line, column = position_in(prefix, len(prefix))
        report.error("regodoc.text.encoding", "il file non è UTF-8 valido", file, line, column)
        return None
    text = text.replace("\r\n", "\n")
    for index in find_bad_chars(text, newline=True, tab=True):
        line, column = position_in(text, index)
        report.error("regodoc.text.char", bad_char_message(text[index]), file, line, column)
        return None
    return text


def comment_lines(text: str) -> list[int]:
    """Righe che contengono un commento TOML, riconosciuto fuori dalle stringhe.

    tomllib scarta i commenti senza dirlo: questo piccolo analizzatore li trova per
    l'avviso del §2 e del §3. Riconosce stringhe di base, letterali e su più righe.
    """
    lines: list[int] = []
    index = 0
    line = 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
        elif char == "#":
            lines.append(line)
            end = text.find("\n", index)
            index = length if end < 0 else end
        elif text.startswith('"""', index) or text.startswith("'''", index):
            quote = text[index : index + 3]
            end = _find_closing(text, index + 3, quote, escapes=quote == '"""')
            line += text.count("\n", index, end)
            index = end
        elif char in "\"'":
            end = _find_closing(text, index + 1, char, escapes=char == '"')
            line += text.count("\n", index, end)
            index = end
        else:
            index += 1
    return lines


def _find_closing(text: str, start: int, quote: str, *, escapes: bool) -> int:
    """Indice subito dopo la chiusura di una stringa, o la fine del testo."""
    index = start
    while index < len(text):
        if escapes and text[index] == "\\":
            index += 2
            continue
        if text.startswith(quote, index):
            end = index + len(quote)
            # Le stringhe su più righe possono finire con una o due virgolette in più.
            while len(quote) == 3 and end < len(text) and text[end] == quote[0]:
                end += 1
            return end
        if len(quote) == 1 and text[index] == "\n":
            return index
        index += 1
    return len(text)


def parse_toml(text: str, file: str, report: Collector) -> dict[str, object] | None:
    """Analizza il TOML; in caso d'errore lo registra con la posizione, in italiano."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        match = _TOML_ERROR_POSITION.search(str(error))
        line, column = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        where = "alla fine del file" if _TOML_ERROR_END.search(str(error)) else "qui"
        report.error(
            "regodoc.toml.syntax",
            f"TOML non valido {where}: controlla virgolette, parentesi e uguali",
            file,
            line,
            column,
        )
    except RecursionError:
        report.error("regodoc.toml.depth", "annidamento eccessivo di array o tabelle", file)
    return None


def _line_of_key(text: str, key: str) -> int:
    match = re.search(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=", text)
    return text.count("\n", 0, match.start()) + 1 if match else 0


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_plain_date(value: object) -> bool:
    return type(value) is datetime.date


def _type_name(value: object) -> str:
    names = {
        bool: "booleano",
        int: "intero",
        float: "numero a virgola mobile",
        str: "stringa",
        list: "array",
        dict: "tabella",
        datetime.date: "data",
        datetime.datetime: "data con ora",
        datetime.time: "ora",
    }
    return names.get(type(value), type(value).__name__)


def _check_plain(
    value: object, where: str, file: str, report: Collector, *, max_length: int, line: int = 0
) -> bool:
    if not isinstance(value, str):
        report.error(
            "regodoc.toml.type",
            f"{where} deve essere testo, non {_type_name(value)}",
            file,
            line,
        )
        return False
    # Un carattere scritto con una sequenza di escape sfugge al controllo sul testo del file.
    for index in find_bad_chars(value):
        message = f"{where}: {bad_char_message(value[index])} alla posizione {index + 1}"
        report.error("regodoc.text.char", message, file, line)
        return False
    for problem in plain_text_problems(value, max_length=max_length):
        report.error("regodoc.text.plain", f"{where}: {problem}", file, line)
        return False
    return True


# --- structure.toml --------------------------------------------------------------------------

_ROOT_KEYS = ("language", "toc", "header", "opening", "part")
_HEADER_KEYS = ("title", "subject", "reference", "date", "version_label")
_HEADER_LENGTHS = {"title": 200, "subject": 200, "reference": 80, "version_label": 40}


def read_structure(data: bytes, report: Collector) -> Structure | None:
    """Legge e valida ``structure.toml``; None se il file è inutilizzabile."""
    file = "structure.toml"
    text = decode_toml(data, file, report, CONTENT_LIMITS["structure_bytes"])
    if text is None:
        return None
    for line in comment_lines(text):
        report.warning(
            "regodoc.toml.comment", "il commento si perde nella forma canonica", file, line
        )
    document = parse_toml(text, file, report)
    if document is None:
        return None
    structure = Structure()
    for key in document:
        if key not in _ROOT_KEYS:
            report.error(
                "regodoc.toml.unknown_key",
                f"chiave «{key}» non prevista",
                file,
                _line_of_key(text, key),
            )
    if "language" in document:
        language = document["language"]
        if language not in LANGUAGES:
            report.error(
                "regodoc.toml.value",
                f"«language» deve essere uno fra {', '.join(LANGUAGES)}",
                file,
                _line_of_key(text, "language"),
            )
        else:
            structure.language = str(language)
    if "toc" in document:
        if not isinstance(document["toc"], bool):
            report.error(
                "regodoc.toml.type",
                "«toc» deve essere true o false",
                file,
                _line_of_key(text, "toc"),
            )
        else:
            structure.toc = document["toc"]
    _read_header(document.get("header"), structure, file, report)
    _read_entries(document, structure, file, report)
    return structure


def _read_header(header: object, structure: Structure, file: str, report: Collector) -> None:
    if header is None:
        report.error("regodoc.toml.missing", "manca la tabella [header]", file)
        return
    if not isinstance(header, dict):
        report.error("regodoc.toml.type", "«header» deve essere una tabella", file)
        return
    for key in header:
        if key not in _HEADER_KEYS:
            report.error("regodoc.toml.unknown_key", f"chiave «header.{key}» non prevista", file)
    if "title" not in header:
        report.error("regodoc.toml.missing", "manca «header.title»", file)
    for key, max_length in _HEADER_LENGTHS.items():
        if key in header and _check_plain(
            header[key], f"«header.{key}»", file, report, max_length=max_length
        ):
            structure.header[key] = header[key]
    if "date" in header:
        if _is_plain_date(header["date"]):
            structure.header["date"] = header["date"]
        else:
            report.error(
                "regodoc.toml.type",
                "«header.date» deve essere una data AAAA-MM-GG, senza ora",
                file,
            )


def _read_entries(
    document: dict[str, object], structure: Structure, file: str, report: Collector
) -> None:
    number = 0
    for kind in ("opening", "part"):
        items = document.get(kind, [])
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            report.error("regodoc.toml.type", f"«{kind}» deve essere un array di tabelle", file)
            structure.invalid_entries += 1
            continue
        allowed = ("id",) if kind == "opening" else ("id", "title", "accent")
        for position, item in enumerate(items, start=1):
            where = f"{kind}[{position}]"
            for key in item:
                if key not in allowed:
                    report.error(
                        "regodoc.toml.unknown_key", f"chiave «{where}.{key}» non prevista", file
                    )
            identifier = item.get("id")
            if not isinstance(identifier, str) or not ID.fullmatch(identifier):
                report.error(
                    "regodoc.toml.id",
                    f"«{where}.id» non è un id valido: [a-z][a-z0-9-]{{0,47}}, "
                    "senza «--», senza «-» finale, non un nome riservato (§1.5)",
                    file,
                )
                structure.invalid_entries += 1
                continue
            title = ""
            accent = ""
            if kind == "part":
                number += 1
                if "title" not in item:
                    report.error("regodoc.toml.missing", f"manca «{where}.title»", file)
                elif _check_plain(item["title"], f"«{where}.title»", file, report, max_length=200):
                    title = str(item["title"])
                accent_value = item.get("accent")
                if accent_value not in ACCENTS:
                    report.error(
                        "regodoc.toml.value",
                        f"«{where}.accent» deve essere uno fra {', '.join(ACCENTS)}",
                        file,
                    )
                else:
                    accent = str(accent_value)
            structure.entries.append(
                PartEntry(identifier, kind, title, accent, number if kind == "part" else 0)
            )
    if not any(e.kind == "part" for e in structure.entries):
        report.error("regodoc.toml.missing", "serve almeno una [[part]]", file)
    if len(structure.entries) > CONTENT_LIMITS["parts"]:
        report.error(
            "regodoc.limit.parts",
            f"{len(structure.entries)} aperture e parti, il massimo è {CONTENT_LIMITS['parts']}",
            file,
        )


# --- variables.toml --------------------------------------------------------------------------


def parse_italian_number(text: str) -> Decimal | None:
    """Valore di un numero italiano (§3.1), o None se la stringa non lo è."""
    if not ITALIAN_NUMBER.fullmatch(text):
        return None
    return Decimal(text.replace(".", "").replace(",", "."))


@dataclass
class Variables:
    """Le variabili lette: quelle valide, e i nomi di tutte quelle dichiarate, valide o no.

    ``declared`` vale None quando il file non si è potuto leggere: allora nessun richiamo a
    una variabile si può dire «inesistente».
    """

    valid: dict[str, Variable] = field(default_factory=dict)
    declared: set[str] | None = field(default_factory=set)


def read_variables(data: bytes, report: Collector) -> Variables:
    """Legge e valida ``variables.toml``; le variabili sbagliate sono escluse da ``valid``."""
    file = "variables.toml"
    result = Variables()
    text = decode_toml(data, file, report, CONTENT_LIMITS["variables_bytes"])
    if text is None:
        result.declared = None
        return result
    for line in comment_lines(text):
        report.warning(
            "regodoc.toml.comment",
            "il commento si perde nella forma canonica: la provenienza va in «note»",
            file,
            line,
        )
    document = parse_toml(text, file, report)
    if document is None:
        result.declared = None
        return result
    if len(document) > CONTENT_LIMITS["variables"]:
        report.error(
            "regodoc.limit.variables",
            f"{len(document)} variabili, il massimo è {CONTENT_LIMITS['variables']}",
            file,
        )
        result.declared = None
        return result
    result.declared = set(document)
    for name, spec in document.items():
        line = _line_of_key(text, name)
        variable = _read_variable(name, spec, file, line, report)
        if variable is not None:
            result.valid[name] = variable
    return result


def _read_variable(
    name: str, spec: object, file: str, line: int, report: Collector
) -> Variable | None:
    if not VARIABLE_NAME.fullmatch(name):
        report.error(
            "regodoc.toml.variable_name",
            f"«{name}» non è un nome di variabile valido: [a-z][A-Za-z0-9]{{0,47}}",
            file,
            line,
        )
        return None
    if not isinstance(spec, dict):
        report.error(
            "regodoc.toml.type",
            f"«{name}» deve essere una tabella come {{ date = 2026-01-31 }}",
            file,
            line,
        )
        return None
    types = [key for key in spec if key in VARIABLE_TYPES]
    unknown = [key for key in spec if key not in VARIABLE_TYPES and key != "note"]
    if unknown:
        report.error(
            "regodoc.toml.unknown_key",
            f"«{name}»: chiave «{unknown[0]}» non prevista; tipi ammessi: "
            f"{', '.join(VARIABLE_TYPES)}",
            file,
            line,
        )
        return None
    if len(types) != 1:
        report.error(
            "regodoc.toml.variable_type",
            f"«{name}» deve avere una sola chiave di tipo, ne ha {len(types)}",
            file,
            line,
        )
        return None
    if "note" in spec and not _check_plain(
        spec["note"], f"«{name}.note»", file, report, max_length=500, line=line
    ):
        return None
    kind = types[0]
    value = spec[kind]
    if isinstance(value, list):
        if kind in ("date", "text"):
            report.error(
                "regodoc.toml.range",
                f"«{name}»: il tipo «{kind}» non ammette intervalli",
                file,
                line,
            )
            return None
        if len(value) != 2:
            report.error(
                "regodoc.toml.range",
                f"«{name}»: un intervallo ha esattamente due valori",
                file,
                line,
            )
            return None
        low = _scalar(name, kind, value[0], file, line, report)
        high = _scalar(name, kind, value[1], file, line, report)
        if low is None or high is None:
            return None
        if low > high:  # type: ignore[operator]
            report.error(
                "regodoc.toml.range",
                f"«{name}»: il primo valore dell'intervallo supera il secondo",
                file,
                line,
            )
            return None
        return Variable(name, kind, (value[0], value[1]), True, line)
    if _scalar(name, kind, value, file, line, report) is None:
        return None
    return Variable(name, kind, value, False, line)


def _scalar(
    name: str, kind: str, value: object, file: str, line: int, report: Collector
) -> object | None:
    """Valida un singolo valore; restituisce un valore confrontabile o None se è sbagliato."""

    def fail(expected: str) -> None:
        report.error(
            "regodoc.toml.value",
            f"«{name}»: il tipo «{kind}» vuole {expected}, non {_type_name(value)} {value!r}",
            file,
            line,
        )

    if kind == "date":
        if _is_plain_date(value):
            return value
        fail("una data AAAA-MM-GG senza ora")
        return None
    if kind == "text":
        return (
            value
            if _check_plain(value, f"«{name}»", file, report, max_length=500, line=line)
            else None
        )
    if isinstance(value, float):
        fail('un numero italiano fra virgolette, come "61,2"')
        return None
    integer_ok = kind in ("count", "number", "hours", "days", "months")
    string_ok = kind != "count"
    if _is_int(value) and integer_ok:
        if abs(value) > _MAX_INTEGER or (kind not in NEGATIVE_TYPES and value < 0):  # type: ignore[operator]
            fail(
                f"un intero di valore assoluto non oltre {_MAX_INTEGER}, non negativo per «{kind}»"
            )
            return None
        return Decimal(value)  # type: ignore[arg-type]
    if isinstance(value, str) and string_ok:
        number = parse_italian_number(value)
        if number is None:
            fail("un numero italiano, con il punto per le migliaia e la virgola per i decimali")
            return None
        if kind == "eur" and "," in value and len(value.split(",")[1]) > 2:
            fail("un importo con al massimo due decimali")
            return None
        if kind not in NEGATIVE_TYPES and number < 0:
            fail("un numero non negativo")
            return None
        if abs(number) > _MAX_INTEGER:
            fail(f"un numero di valore assoluto non oltre {_MAX_INTEGER}")
            return None
        return number
    if kind == "count":
        fail("un intero non negativo")
    elif integer_ok:
        fail("un intero o un numero italiano fra virgolette")
    else:
        fail('un numero italiano fra virgolette, come "2.310,75"')
    return None
