"""Il comando ``canon``: il pacchetto in forma canonica (contratto, §2.1 e §8).

Valida, riscrive i file di contenuto nella forma del §9 della specifica, genera
``README.md`` e manifesto, e scrive l'archivio in modo atomico. Con ``--files-dir`` scrive
anche i file di contenuto canonici uno per uno.
"""

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from regodoc import __version__, canonical
from regodoc.declaration import ENGINE_NAME
from regodoc.diagnostics import clip
from regodoc.outputs import OutputError, check_output, described, temporary_name, write_file
from regodoc.validate import Validation, files_digest, validate_package

DOCUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass
class Outcome:
    """L'esito di ``canon``, pronto per il rapporto (contratto, §4.2)."""

    exit_code: int
    validation: Validation
    summary: dict[str, object] = field(default_factory=dict)


def check_options(document: str | None, base_version: str | None) -> str | None:
    """Il problema di ``--document`` o ``--base-version``, se c'è (specifica, §1.3)."""
    if document is not None and not DOCUMENT.fullmatch(document):
        return (
            f"--document: «{clip(document)}» non è un identificatore valido: da 1 a 64 "
            "caratteri fra lettere ASCII, cifre, punto, trattino e trattino basso, il primo "
            "una lettera o una cifra"
        )
    if base_version is not None and not DIGEST.fullmatch(base_version):
        return (
            f"--base-version: «{clip(base_version)}» non è un'impronta valida: «sha256:» "
            "seguito da 64 cifre esadecimali minuscole"
        )
    return None


def check_files_dir(path: Path) -> None:
    """``--files-dir`` deve essere una cartella che esiste ed è vuota (contratto, §2.1)."""
    if not path.is_dir() or path.is_symlink():
        raise OutputError(f"--files-dir: «{clip(str(path))}» non è una cartella esistente")
    if any(path.iterdir()):
        raise OutputError(f"--files-dir: la cartella «{clip(str(path))}» non è vuota")


def run(
    package: Path,
    output: str,
    *,
    document: str | None,
    base_version: str | None,
    files_dir: Path | None,
    strict: bool,
) -> Outcome:
    """Esegue ``canon``. Solleva ``OutputError`` per un'uscita non valida."""
    target = Path(output)
    check_output(target, package, directory=False)
    if files_dir is not None:
        check_files_dir(files_dir)
    validation = validate_package(package)
    report = validation.report
    outcome = Outcome(1, validation, validation.summary())
    if report.has_errors() or (strict and report.strict_warnings):
        return outcome
    structure = validation.structure
    if structure is None:  # pragma: no cover - un pacchetto valido ha structure.toml
        raise ValueError("pacchetto valido senza structure.toml")
    manifest = validation.manifest
    if document is None and isinstance(manifest.get("document"), str):
        document = str(manifest["document"])
    if base_version is None and isinstance(manifest.get("base_version"), str):
        base_version = str(manifest["base_version"])
    grammar = str(validation.grammar)
    content = canonical.content_files(validation)
    files = canonical.package_files(
        content,
        grammar=grammar,
        title=str(structure.header["title"]),
        language=structure.language,
        document=document,
        base_version=base_version,
    )
    data = canonical.archive(files)
    if files_dir is not None:
        _write_files(files_dir, content)
    write_file(target, data)
    listed = [described(path, body) for path, body in content]
    outcome.summary = {
        **outcome.summary,
        "grammar": grammar,
        "generator": {"engine": ENGINE_NAME, "version": __version__},
        "document": document,
        "base_version": base_version,
        "files": listed,
        "files_sha256": files_digest(listed),
    }
    outcome.exit_code = 0
    return outcome


def _write_files(root: Path, content: list[tuple[str, bytes]]) -> None:
    """Scrive i file di contenuto nella cartella vuota; se non ci riesce, toglie quelli già
    scritti, così la cartella torna com'era."""
    written: list[Path] = []
    try:
        for path, data in content:
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = temporary_name(destination)
            written.append(temporary)
            temporary.write_bytes(data)
            temporary.replace(destination)
            written[-1] = destination
    except OSError as error:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        for directory in sorted({p.parent for p in written}, key=lambda p: -len(p.parts)):
            if directory != root:
                with contextlib.suppress(OSError):
                    directory.rmdir()
        raise OutputError("non posso scrivere i file in --files-dir", environment=True) from error
