"""Il comando ``build``: dal pacchetto al PDF, o alla cartella con il LaTeX (contratto, §2.1).

L'ordine è quello del progetto: validazione, intestazione, tema, data, testo LaTeX, cartella
di lavoro, compilazione e controlli, uscita atomica. Ogni esito diventa un ``Outcome`` con il
codice d'uscita; il comando lo scrive nel rapporto.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from regodoc.compiler import (
    CompileError,
    check_loaded,
    check_packages,
    compile_pdf,
    find_pdflatex,
    package_closure,
)
from regodoc.diagnostics import Collector, Severity
from regodoc.header import Header, HeaderError, choose_date, read_header
from regodoc.outputs import (
    OutputError,
    check_output,
    described,
    temporary_name,
    write_file,
)
from regodoc.render import Document, render_document
from regodoc.theme import TEX_DIR, Theme, read_theme
from regodoc.validate import Validation, validate_package


@dataclass
class Outcome:
    """L'esito di ``build``, pronto per il rapporto (contratto, §4.3)."""

    exit_code: int
    validation: Validation
    outputs: list[dict[str, object]] = field(default_factory=list)
    passes: int = 0
    theme: dict[str, str] | None = None
    tex: dict[str, str] | None = None


def run(
    package: Path,
    output: str,
    *,
    output_format: str,
    header_path: Path | None,
    theme_path: Path | None,
    contract: int,
    strict: bool,
) -> Outcome:
    """Esegue ``build``. Solleva ``OutputError`` per un'uscita non valida."""
    target = Path(output)
    check_output(target, package, directory=output_format == "latex")
    validation = validate_package(package)
    report = validation.report
    outcome = Outcome(1, validation)
    if report.has_errors() or (strict and report.strict_warnings):
        return outcome
    header: Header | None = None
    if header_path is not None:
        found = Collector()
        header = read_header(header_path, contract, found)
        if header is None:
            _merge(report, found)
            outcome.exit_code = 2
            return outcome
    found = Collector()
    theme = read_theme(theme_path, found)
    _merge(report, found)
    if theme is None:
        outcome.exit_code = 2
        return outcome
    outcome.theme = {"name": theme.name, "version": theme.version, "sha256": theme.sha256}
    structure = validation.structure
    if structure is None:  # pragma: no cover - senza errori structure.toml è sempre letto
        return outcome
    try:
        date = choose_date(
            structure.header.get("date"),  # type: ignore[arg-type]
            header,
            os.environ.get("SOURCE_DATE_EPOCH"),
        )
    except HeaderError as error:
        report.error(error.code, error.message)
        outcome.exit_code = 2
        return outcome
    frame = dict(header.frame) if header is not None else {}
    for key in theme.frame_keys:
        if key not in frame:
            report.info(
                "regodoc.theme.frame_key",
                f"il tema stampa la chiave «{key}» della cornice, che l'intestazione non dà",
                "theme.toml",
            )
    text = render_document(
        Document(structure, validation.variables, validation.roots, date.day, frame, theme.palette)
    )
    with tempfile.TemporaryDirectory(prefix="regodoc-", ignore_cleanup_errors=True) as work:
        doc, home = Path(work) / "doc", Path(work) / "home"
        _prepare(doc, home, text, theme, validation)
        if output_format == "latex":
            outcome.outputs = _write_directory(doc, target, output)
            outcome.exit_code = 0
            return outcome
        return _compile(outcome, doc, home, date.epoch, theme, target, output)


def _compile(
    outcome: Outcome, doc: Path, home: Path, epoch: int, theme: Theme, target: Path, output: str
) -> Outcome:
    report = outcome.validation.report
    pdflatex = find_pdflatex()
    if pdflatex is None:
        report.error("regodoc.tex.missing", "pdflatex non c'è nel PATH: serve un'installazione TeX")
        outcome.exit_code = 3
        return outcome
    try:
        result = compile_pdf(doc, home, epoch, pdflatex)
        # L'aggancio package/before di regodoc.sty dà un messaggio chiaro per i pacchetti
        # chiesti dal tema; la barriera è il .fls, che il tema non tocca (contratto, §6.1).
        check_packages(result.packages, theme.tex_packages)
        if theme.external:
            allowed = package_closure(doc, home, epoch, pdflatex, theme.tex_packages)
            check_loaded(result.loaded, allowed)
    except CompileError as error:
        if error.environment:
            report.error(error.code, error.message)
            outcome.exit_code = 3
        elif theme.external:
            code = error.code or "regodoc.theme.compile"
            report.error(code, error.message, error.file, error.line)
            outcome.exit_code = 2
        else:
            report.error(
                "regodoc.internal",
                f"il pacchetto è valido ma non compila con il tema neutro: è un difetto del "
                f"motore ({error.message})",
                error.file,
                error.line,
            )
            outcome.exit_code = 4
        return outcome
    write_file(target, result.pdf)
    outcome.outputs = [described(output, result.pdf)]
    outcome.passes = result.passes
    outcome.tex = {"version_line": result.version_line}
    outcome.exit_code = 0
    return outcome


def _merge(report: Collector, found: Collector) -> None:
    for item in found.items:
        if item.severity is Severity.ERROR:
            report.error(item.code, item.message, item.file, item.line, item.column)
        elif item.severity is Severity.INFO:
            report.info(item.code, item.message, item.file, item.line, item.column)
        else:  # pragma: no cover - tema e intestazione non danno avvisi
            report.warning(item.code, item.message, item.file, item.line, item.column)


def _prepare(doc: Path, home: Path, text: str, theme: Theme, validation: Validation) -> None:
    """La cartella di lavoro: document.tex, regodoc.sty, il tema e le immagini."""
    doc.mkdir()
    home.mkdir()
    files: dict[str, bytes] = {"document.tex": text.encode("utf-8")}
    files["regodoc.sty"] = (TEX_DIR / "regodoc.sty").read_bytes()
    files.update(theme.files)
    package = validation.package.files if validation.package is not None else {}
    for path, data in package.items():
        if path.startswith("images/"):
            files[path] = data
    for path in sorted(files, key=lambda p: p.encode("utf-8")):
        destination = doc / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files[path])


def _write_directory(doc: Path, target: Path, output: str) -> list[dict[str, object]]:
    """Copia la cartella del LaTeX al posto di ``target``, sostituendola per intero."""
    temporary = temporary_name(target)
    try:
        shutil.copytree(doc, temporary, symlinks=False)
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            target.unlink()
        if target.is_dir():
            old = temporary_name(target)
            target.rename(old)
            temporary.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        else:
            temporary.rename(target)
    except PermissionError as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise OutputError(
            "non posso scrivere l'uscita: permesso negato", environment=True
        ) from error
    files = sorted(
        (p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()),
        key=lambda p: p.encode("utf-8"),
    )
    return [described(f"{output}/{path}", (target / path).read_bytes()) for path in files]
