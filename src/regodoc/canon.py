"""I comandi ``canon`` e ``upgrade``: il pacchetto in forma canonica (contratto, §2.1 e §8).

Validano, riscrivono i file di contenuto nella forma del §9 della specifica, generano
``README.md`` e manifesto, e scrivono l'archivio in modo atomico. ``canon`` resta nella
grammatica del pacchetto e rifiuta quelle precedenti, che il motore non sa più scrivere;
``upgrade`` porta il pacchetto alla grammatica corrente. Con ``--files-dir``, ``canon``
scrive anche i file di contenuto canonici uno per uno.
"""

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from regodoc import __version__, canonical, limits
from regodoc.declaration import ENGINE_NAME, GRAMMAR_CURRENT
from regodoc.diagnostics import clip
from regodoc.outputs import OutputError, check_output, described, temporary_name, write_file
from regodoc.validate import DIGEST, DOCUMENT, Validation, files_digest, validate_package


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
    upgrade: bool = False,
) -> Outcome:
    """Esegue ``canon``, oppure ``upgrade`` con ``upgrade``. Solleva ``OutputError`` per
    un'uscita non valida."""
    target = Path(output)
    check_output(target, package, directory=False)
    if files_dir is not None:
        check_files_dir(files_dir)
    validation = validate_package(package)
    report = validation.report
    outcome = Outcome(1, validation, validation.summary())
    if upgrade:
        outcome.summary["grammar_in"] = validation.grammar
    if report.has_errors() or (strict and report.strict_warnings):
        return outcome
    if validation.upgraded is not None and not upgrade:
        report.error(
            "regodoc.manifest.grammar_old",
            f"canon non scrive più la grammatica «{validation.grammar}»: «regodoc upgrade» "
            f"porta il pacchetto a «{GRAMMAR_CURRENT}»",
            "manifest.json",
        )
        return outcome
    structure = validation.structure
    if structure is None:  # pragma: no cover - un pacchetto valido ha structure.toml
        raise ValueError("pacchetto valido senza structure.toml")
    manifest = validation.manifest
    if document is None and isinstance(manifest.get("document"), str):
        document = str(manifest["document"])
    if base_version is None and isinstance(manifest.get("base_version"), str):
        base_version = str(manifest["base_version"])
    grammar = GRAMMAR_CURRENT if upgrade else str(validation.grammar)
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
    # Gli alberi delle parti d'ingresso non servono più, e la rivalidazione costruisce quelli
    # dell'uscita: tenerli vivi tutti e due raddoppiava il picco di memoria, oltre il limite
    # del comando sui pacchetti più grandi. Gli alberi non hanno cicli: basta il conteggio dei
    # riferimenti. Il rapporto usa il riassunto già calcolato, i problemi e input_*.
    del files
    validation.roots = {}
    validation.package = None
    validation.upgraded = None
    problems = canonical.output_problems(content, data)
    if problems:
        for problem in problems:
            report.error(problem.code, problem.message, problem.file, problem.line, problem.column)
        return outcome
    # Tutto ciò che dice il rapporto si calcola prima di scrivere: dopo la scrittura resta
    # solo da fermare il timer.
    listed = [described(path, body) for path, body in content]
    digest = files_digest(listed)
    created = _write_files(files_dir, content) if files_dir is not None else []
    try:
        write_file(target, data)
    except BaseException:
        # L'uscita esiste solo con il codice 0, anche quella di --files-dir.
        _remove(created)
        raise
    # A uscita scritta un tempo che scade non cambia più l'esito.
    limits.disarm()
    outcome.summary = {
        **outcome.summary,
        "grammar": grammar,
        "generator": {"engine": ENGINE_NAME, "version": __version__},
        "document": document,
        "base_version": base_version,
        "files": listed,
        "files_sha256": digest,
    }
    outcome.exit_code = 0
    return outcome


def _write_files(root: Path, content: list[tuple[str, bytes]]) -> list[Path]:
    """Scrive i file di contenuto nella cartella vuota e restituisce ciò che ha creato,
    cartelle comprese. Se qualcosa la interrompe, anche il tempo scaduto o un SIGINT, toglie
    ciò che ha già scritto, così la cartella torna vuota; solo un errore di sistema diventa
    ``OutputError``."""
    created: list[Path] = []
    try:
        for path, data in content:
            destination = root / path
            for parent in reversed(Path(path).parents[:-1]):
                folder = root / parent
                if not folder.exists():
                    folder.mkdir()
                    created.append(folder)
            temporary = temporary_name(destination)
            # Tutti e due, prima di scrivere: un'interruzione durante la rinomina lascia
            # l'uno o l'altro, e la pulizia li toglie entrambi.
            created += [temporary, destination]
            with temporary.open("xb") as handle:
                handle.write(data)
            temporary.replace(destination)
    except BaseException as error:
        _remove(created)
        if isinstance(error, OSError):
            raise OutputError(
                "non posso scrivere i file in --files-dir", environment=True
            ) from error
        raise
    return created


def _remove(created: list[Path]) -> None:
    """Toglie file e cartelle creati, dall'ultimo al primo."""
    for path in reversed(created):
        with contextlib.suppress(OSError):
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
