"""Errori e avvisi del motore, con codice stabile, posizione e messaggio in italiano."""

import enum
from dataclasses import dataclass, field


class Severity(enum.StrEnum):
    """Gravità di un problema: un errore blocca il pacchetto, un avviso no."""

    ERROR = "error"
    WARNING = "warning"


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
    """Raccoglie errori e avvisi, con un tetto per non produrre rapporti smisurati."""

    limit: int = 500
    items: list[Diagnostic] = field(default_factory=list)

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

    def _add(self, diagnostic: Diagnostic) -> None:
        self.items.append(diagnostic)
        if len(self.items) >= self.limit:
            self.items.append(
                Diagnostic(
                    Severity.ERROR,
                    "regodoc.limit.problems",
                    f"troppi problemi: la lettura si ferma dopo {self.limit}",
                )
            )
            raise TooManyProblems

    @property
    def errors(self) -> list[Diagnostic]:
        """Solo gli errori."""
        return [d for d in self.items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Solo gli avvisi."""
        return [d for d in self.items if d.severity is Severity.WARNING]

    def has_errors(self) -> bool:
        """Vero se c'è almeno un errore."""
        return any(d.severity is Severity.ERROR for d in self.items)
