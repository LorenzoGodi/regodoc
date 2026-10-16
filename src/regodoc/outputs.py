"""Le uscite dei comandi (contratto, §2.1): controlli di ``-o`` e scrittura atomica."""

import hashlib
import secrets
from pathlib import Path

from regodoc.diagnostics import clip


class OutputError(Exception):
    """L'uscita di ``-o`` non va bene: codice 2 se è un errore d'uso, 3 d'ambiente."""

    def __init__(self, message: str, *, environment: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.environment = environment


def described(path: str, data: bytes) -> dict[str, object]:
    """Un file scritto, come lo descrive il rapporto: percorso, impronta e dimensione."""
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def check_output(target: Path, package: Path, *, directory: bool) -> None:
    """Le regole di ``-o`` (contratto, §2.1) che si controllano prima di lavorare."""
    parent = target.parent
    if not parent.is_dir():
        raise OutputError(f"la cartella dell'uscita «{clip(str(parent))}» non esiste")
    if target.exists() and package.exists() and target.samefile(package):
        raise OutputError("l'uscita non può essere il pacchetto d'ingresso")
    if not directory and target.is_dir() and not target.is_symlink():
        raise OutputError(f"l'uscita «{clip(str(target))}» è una cartella, non un file")


def temporary_name(target: Path) -> Path:
    return target.parent / f".{target.name}.regodoc-{secrets.token_hex(6)}"


def write_file(target: Path, data: bytes) -> None:
    """Scrive accanto a un nome temporaneo e rinomina: l'uscita esiste solo se è completa."""
    temporary = temporary_name(target)
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
        temporary.replace(target)  # sostituisce anche un collegamento, non ciò a cui punta
    except PermissionError as error:
        temporary.unlink(missing_ok=True)
        raise OutputError(
            "non posso scrivere l'uscita: permesso negato", environment=True
        ) from error
