"""Errori e avvisi del motore, con codice stabile, posizione e messaggio in italiano."""

import enum
import re
from dataclasses import dataclass, field
from typing import NoReturn

from regodoc.declaration import CONTENT_LIMITS

# Lunghezza massima di un messaggio e di una stringa del pacchetto citata in un messaggio: il
# rapporto resta piccolo anche con un pacchetto ostile (contratto, §4).
MESSAGE_MAX = 500
QUOTE_MAX = 80
_QUOTED = (
    re.compile(rf"(«)([^»]{{{QUOTE_MAX + 1},}})(»)"),
    re.compile(rf"(<)([^<>]{{{QUOTE_MAX + 1},}})(>)"),
)


def clip(text: str, limit: int = QUOTE_MAX) -> str:
    """Accorcia una stringa del pacchetto prima di citarla in un messaggio."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Severity(enum.StrEnum):
    """Gravità di un problema.

    Un errore blocca il pacchetto. Un avviso no, ma conta come errore con ``--strict``. Un
    avviso informativo («info») segnala un fatto che non dipende da chi ha scritto il
    pacchetto, per esempio un ruolo che il tema non definisce: ``--strict`` non lo conta.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Un problema trovato nel pacchetto.

    ``code`` è stabile e in inglese (per esempio ``regodoc.xml.unknown_element``);
    ``message`` è in italiano. ``line`` e ``column`` contano da 1; 0 vuol dire «non
    applicabile», per esempio per un problema che riguarda il file intero.
    """

    severity: Severity
    code: str
    message: str
    file: str = ""
    line: int = 0
    column: int = 0

    def __post_init__(self) -> None:
        """Accorcia le stringhe citate fra «» o fra <> e tiene il messaggio entro
        ``MESSAGE_MAX`` caratteri: un pacchetto ostile non può gonfiare il rapporto."""
        message = self.message
        for pattern in _QUOTED:
            message = pattern.sub(lambda m: m.group(1) + clip(m.group(2)) + m.group(3), message)
        message = clip(message, MESSAGE_MAX)
        if message != self.message:
            object.__setattr__(self, "message", message)

    def __str__(self) -> str:
        """Forma «file:riga:colonna  codice  messaggio», come nella specifica (§8)."""
        where = self.file
        if self.line:
            where += f":{self.line}"
            if self.column:
                where += f":{self.column}"
        return f"{where}  {self.code}  {self.message}" if where else f"{self.code}  {self.message}"

    def to_json(self) -> dict[str, object]:
        """Il problema come oggetto JSON del rapporto."""
        return {
            "severity": str(self.severity),
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "column": self.column,
        }


class TooManyProblems(Exception):
    """Interrompe la lettura quando i problemi superano il massimo che vale la pena elencare."""


@dataclass
class Collector:
    """Raccoglie errori e avvisi, con un tetto per non produrre rapporti smisurati.

    Il rapporto elenca al massimo ``limit`` problemi (specifica, §7.2):

    - un errore che arriva oltre il tetto ferma la lettura con l'errore
      ``regodoc.limit.problems``, che ne cita il codice e la posizione;
    - un avviso oltre il tetto non cambia l'esito: non si elenca, si conta in
      ``warnings_omitted``, e ``finish`` aggiunge un solo avviso ``regodoc.limit.warnings``.

    Così un pacchetto entro i limiti con molti avvisi resta valido.
    """

    limit: int = field(default_factory=lambda: int(CONTENT_LIMITS["problems"]))
    items: list[Diagnostic] = field(default_factory=list)
    warnings_omitted: int = 0
    stopped: bool = False

    def error(
        self, code: str, message: str, file: str = "", line: int = 0, column: int = 0
    ) -> None:
        """Registra un errore."""
        self._add(Diagnostic(Severity.ERROR, code, message, file, line, column))

    def warning(
        self, code: str, message: str, file: str = "", line: int = 0, column: int = 0
    ) -> None:
        """Registra un avviso."""
        self._add(Diagnostic(Severity.WARNING, code, message, file, line, column))

    def info(self, code: str, message: str, file: str = "", line: int = 0, column: int = 0) -> None:
        """Registra un avviso informativo, che ``--strict`` non conta."""
        self._add(Diagnostic(Severity.INFO, code, message, file, line, column))

    def _add(self, diagnostic: Diagnostic) -> None:
        if len(self.items) < self.limit:
            self.items.append(diagnostic)
        elif diagnostic.severity is not Severity.ERROR:
            self.warnings_omitted += 1
        else:
            self._stop(diagnostic)

    def _stop(self, cause: Diagnostic) -> NoReturn:
        """Un errore oltre il tetto: la lettura si ferma, e l'errore si cita nel messaggio."""
        where = ":".join(str(x) for x in (cause.file, cause.line, cause.column) if x)
        self.stopped = True
        self.items.append(
            Diagnostic(
                Severity.ERROR,
                "regodoc.limit.problems",
                f"troppi problemi: la lettura si ferma al primo errore oltre i {self.limit}, "
                f"{cause.code}" + (f" in {where}" if where else ""),
                cause.file,
                cause.line,
                cause.column,
            )
        )
        raise TooManyProblems

    def finish(self) -> None:
        """Chiude la raccolta: conta in un avviso quelli rimasti fuori dal tetto."""
        if self.warnings_omitted and not self.stopped:
            count = self.warnings_omitted
            text = "1 avviso non è elencato" if count == 1 else f"{count} avvisi non sono elencati"
            self.items.append(
                Diagnostic(
                    Severity.WARNING,
                    "regodoc.limit.warnings",
                    f"{text}: il rapporto elenca al massimo {self.limit} problemi",
                )
            )

    @property
    def errors(self) -> list[Diagnostic]:
        """Solo gli errori."""
        return [d for d in self.items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Gli avvisi, informativi compresi: nel rapporto stanno tutti nella stessa lista."""
        return [d for d in self.items if d.severity is not Severity.ERROR]

    @property
    def strict_warnings(self) -> list[Diagnostic]:
        """Gli avvisi che ``--strict`` conta come errori: non gli informativi."""
        return [d for d in self.items if d.severity is Severity.WARNING]

    def has_errors(self) -> bool:
        """Vero se c'è almeno un errore."""
        return any(d.severity is Severity.ERROR for d in self.items)
