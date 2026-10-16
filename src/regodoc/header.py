"""L'intestazione di ``build`` (contratto, §3.2) e la data del documento (specifica, §2).

L'intestazione è di chi chiama, non di chi ha scritto il pacchetto: un suo problema ferma
``build`` con il codice 2 e un errore ``regodoc.header.*``.
"""

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from regodoc.diagnostics import Collector, clip
from regodoc.text import (
    JsonProblem,
    bad_char_message,
    find_bad_chars,
    plain_text_problems,
    strict_json,
)

HEADER_BYTES = 64 * 1024
_KEYS = ("contract", "document_created", "frame")
_FRAME_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})")
_EPOCH = re.compile(r"\d{1,12}")


@dataclass
class Header:
    """L'intestazione letta."""

    document_created: datetime.datetime | None = None
    frame: dict[str, str] = field(default_factory=dict)


class HeaderError(Exception):
    """Un errore d'uso sulla data: codice e messaggio per il rapporto."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def read_header(path: Path, contract: int, report: Collector) -> Header | None:
    """Legge l'intestazione con le regole del manifesto (specifica, §1.3)."""
    try:
        with path.open("rb") as handle:
            data = handle.read(HEADER_BYTES + 1)
    except OSError:
        report.error(
            "regodoc.header.missing", f"non posso leggere l'intestazione «{clip(str(path))}»"
        )
        return None
    if len(data) > HEADER_BYTES:
        report.error("regodoc.header.syntax", "l'intestazione supera 64 KiB")
        return None

    try:
        value = strict_json(data.decode("utf-8"))
    except UnicodeDecodeError:
        report.error("regodoc.header.syntax", "l'intestazione non è UTF-8 valido")
        return None
    except json.JSONDecodeError as error:
        report.error(
            "regodoc.header.syntax",
            "l'intestazione non è JSON valido",
            "",
            error.lineno,
            error.colno,
        )
        return None
    except JsonProblem as error:
        report.error("regodoc.header.syntax", f"intestazione: {error}")
        return None
    if not isinstance(value, dict):
        report.error("regodoc.header.syntax", "l'intestazione deve essere un oggetto JSON")
        return None
    header = Header()
    for key in value:
        if key not in _KEYS:
            report.error("regodoc.header.unknown_key", f"chiave «{key}» non prevista")
    declared = value.get("contract")
    if type(declared) is not int:
        report.error("regodoc.header.contract", "«contract» manca o non è un intero")
    elif declared != contract:
        report.error(
            "regodoc.header.contract",
            f"«contract» vale {declared}, ma la chiamata usa il contratto {contract}",
        )
    created = value.get("document_created")
    if created is not None:
        if not (isinstance(created, str) and _RFC3339.fullmatch(created)):
            report.error(
                "regodoc.header.value",
                "«document_created» deve essere un istante RFC 3339 con il fuso",
            )
        else:
            try:
                header.document_created = datetime.datetime.fromisoformat(created)
            except ValueError:
                report.error("regodoc.header.value", "«document_created» non è un istante valido")
    frame = value.get("frame", {})
    if not isinstance(frame, dict):
        report.error("regodoc.header.value", "«frame» deve essere un oggetto")
    elif len(frame) > 50:
        report.error("regodoc.header.value", "«frame» ha più di 50 chiavi")
    else:
        for key, text in frame.items():
            problem = _frame_problem(key, text)
            if problem:
                report.error("regodoc.header.value", f"«frame.{clip(key)}»: {problem}")
            else:
                header.frame[key] = text
    return None if report.has_errors() else header


def _frame_problem(key: str, text: object) -> str:
    if not _FRAME_KEY.fullmatch(key):
        return "nome di chiave non valido: [a-z][a-z0-9_]{0,31}"
    if not isinstance(text, str):
        return "il valore deve essere testo"
    for index in find_bad_chars(text):
        return bad_char_message(text[index])
    problems = plain_text_problems(text, max_length=500)
    return problems[0] if problems else ""


@dataclass(frozen=True)
class DocumentDate:
    """La data stampata e l'istante del PDF, in secondi dal 1970 UTC."""

    day: datetime.date
    epoch: int


def choose_date(
    package_date: datetime.date | None, header: Header | None, source_date_epoch: str | None
) -> DocumentDate:
    """Sceglie la data del documento nell'ordine della specifica (§2).

    Solleva ``HeaderError`` se non c'è nessuna data o se ``SOURCE_DATE_EPOCH``, quando serve,
    è malformata.
    """
    chosen = _choose(package_date, header, source_date_epoch)
    if chosen.epoch < 0:
        raise HeaderError(
            "regodoc.header.date",
            "la data del documento viene prima del 1970: il PDF non la può registrare",
        )
    return chosen


def _choose(
    package_date: datetime.date | None, header: Header | None, source_date_epoch: str | None
) -> DocumentDate:
    if package_date is not None:
        midnight = datetime.datetime(
            package_date.year, package_date.month, package_date.day, tzinfo=datetime.UTC
        )
        return DocumentDate(package_date, int(midnight.timestamp()))
    if header is not None and header.document_created is not None:
        created = header.document_created
        return DocumentDate(created.date(), int(created.timestamp()))
    if source_date_epoch is not None:
        if not _EPOCH.fullmatch(source_date_epoch):
            raise HeaderError(
                "regodoc.usage",
                "SOURCE_DATE_EPOCH deve essere un intero non negativo di secondi, solo cifre",
            )
        epoch = int(source_date_epoch)
        day = datetime.datetime.fromtimestamp(epoch, datetime.UTC).date()
        return DocumentDate(day, epoch)
    raise HeaderError(
        "regodoc.header.date",
        "manca la data del documento: né header.date nel pacchetto, né document_created "
        "nell'intestazione, né SOURCE_DATE_EPOCH",
    )
