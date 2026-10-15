"""Il compilatore: pdflatex in un ambiente costruito da zero, con i controlli dopo la
compilazione (contratto, §2.2 e §6.5).

Le barriere, nell'ordine:

1. l'ambiente di pdfTeX: niente comandi esterni, letture e scritture per nome solo nella
   cartella di lavoro e nell'albero TeX, nessuna variabile o cartella dell'utente;
2. il file ``.fls`` di ``-recorder``: ogni file letto deve stare nella cartella di lavoro o
   nell'albero TeX, ogni file scritto nella cartella di lavoro. Serve perché alcune letture
   di pdfTeX (``\\pdfobj file``, ``\\pdfmapfile``, ``\\pdfmapline``, ``\\font`` con un
   percorso assoluto) non passano dal controllo di ``openin_any``;
3. il log: comandi esterni tentati, pacchetti chiesti dal tema, comandi del contenuto
   ridefiniti.

Un problema dopo la compilazione scarta il PDF: niente esce dal motore.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from regodoc.declaration import PASSES, TEX_PACKAGES
from regodoc.diagnostics import clip

DOCUMENT: Final = "document"
# File che cambiano fra le passate finché rimandi, indice e segnalibri non sono stabili.
_STATE_FILES: Final = ("aux", "toc", "out")
_ERROR = re.compile(r"^! (.*)$", re.M)
_LINE = re.compile(r"^l\.(\d+)", re.M)
_MISSING = re.compile(r"File `([^']+)' not found")
_CANNOT_WRITE = re.compile(r"I can't write on file `([^']+)'")
_SHELL = re.compile(r"^runsystem\((.*)\)\.\.\.disabled", re.M)
_PACKAGE = re.compile(r"^regodoc-package: (\S+)$", re.M)
_REDEFINED = re.compile(r"^regodoc-redefined: (\S+)$", re.M)
_FILE_OPEN = re.compile(r"\(([^()\s]+\.(?:tex|sty|cls|cfg|def|fd|aux|toc|out|clo|ldf))")
# Estensioni dei file che mancano all'immagine TeX, non al tema: un pacchetto, una classe.
_TEX_SUPPORT = (".sty", ".cls", ".def", ".fd", ".cfg", ".clo", ".ldf", ".tfm", ".pfb", ".map")


class CompileError(Exception):
    """La compilazione è fallita o un controllo l'ha rifiutata.

    ``code`` è il codice del rapporto, vuoto per un errore di compilazione qualsiasi: con un
    tema esterno diventa ``regodoc.theme.compile`` (codice 2), con il tema neutro è un difetto
    del motore (4). ``environment`` vale per ciò che manca all'immagine TeX (3).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str = "",
        line: int = 0,
        environment: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.file = file
        self.line = line
        self.environment = environment


@dataclass
class Result:
    """Una compilazione riuscita."""

    pdf: bytes
    passes: int
    version_line: str
    packages: list[str] = field(default_factory=list)


def find_pdflatex() -> str | None:
    """Il percorso di pdflatex nel PATH di chi chiama, o None."""
    return shutil.which("pdflatex", path=os.environ.get("PATH", os.defpath))


def environment(pdflatex: str, home: Path, epoch: int) -> dict[str, str]:
    """L'ambiente di pdflatex, costruito da zero (contratto, §2.2)."""
    return {
        "PATH": str(Path(pdflatex).parent),
        "HOME": str(home),
        "TEXMFHOME": str(home / "texmf"),
        "TEXMFVAR": str(home / "texmf-var"),
        "TEXMFCONFIG": str(home / "texmf-config"),
        "TMPDIR": str(home),
        "openin_any": "p",
        "openout_any": "p",
        "shell_escape": "f",
        "MKTEXFMT": "0",
        "MKTEXPK": "0",
        "MKTEXTFM": "0",
        "LC_ALL": "C.UTF-8",
        "SOURCE_DATE_EPOCH": str(epoch),
        "FORCE_SOURCE_DATE": "1",
        # Righe del log senza a capo: il motore le legge per trovare file e posizioni.
        "max_print_line": "100000",
        "error_line": "254",
        "half_error_line": "238",
    }


def version_line(pdflatex: str, env: Mapping[str, str]) -> str:
    """La prima riga di ``pdflatex --version``, che identifica l'immagine TeX."""
    done = subprocess.run(
        [pdflatex, "--version"],
        env=dict(env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    return done.stdout.decode("utf-8", "replace").split("\n", 1)[0].strip()


def tex_roots(env: Mapping[str, str]) -> list[Path]:
    """Le cartelle dell'albero TeX installato, chieste a kpsewhich nello stesso ambiente."""
    kpsewhich = shutil.which("kpsewhich", path=env["PATH"])
    if kpsewhich is None:
        return []
    roots: list[Path] = []
    for variable in ("$TEXMF", "$TEXMFCNF", "$TEXMFSYSVAR", "$TEXMFSYSCONFIG"):
        done = subprocess.run(
            [kpsewhich, f"--expand-braces={variable}"],
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
        for entry in done.stdout.decode("utf-8", "replace").strip().split(os.pathsep):
            folder = entry.strip().removeprefix("!!")
            if folder.startswith("/"):
                roots.append(Path(os.path.realpath(folder)))
    return roots


def compile_pdf(doc: Path, home: Path, epoch: int, pdflatex: str) -> Result:
    """Compila ``document.tex`` in ``doc`` e fa i controlli; solleva ``CompileError``."""
    env = environment(pdflatex, home, epoch)
    previous: dict[str, bytes] | None = None
    passes = 0
    while True:
        passes += 1
        done = subprocess.run(
            [
                pdflatex,
                "-no-shell-escape",
                "-interaction=batchmode",
                "-halt-on-error",
                "-recorder",
                f"{DOCUMENT}.tex",
            ],
            cwd=doc,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        log = _read_log(doc)
        allowed = [doc.resolve(), home.resolve(), *tex_roots(env)]
        _check_recorder(doc, allowed)
        _check_log(log)
        if done.returncode != 0:
            raise _failure(log)
        state = {ext: _read(doc / f"{DOCUMENT}.{ext}") for ext in _STATE_FILES}
        if passes >= PASSES["min"] and state == previous:
            break
        if passes >= PASSES["max"]:
            raise CompileError(
                "", f"rimandi e indice non sono stabili dopo {passes} passate di pdflatex"
            )
        previous = state
    return Result(
        pdf=(doc / f"{DOCUMENT}.pdf").read_bytes(),
        passes=passes,
        version_line=version_line(pdflatex, env),
        packages=_PACKAGE.findall(log),
    )


def check_packages(requested: Iterable[str], declared: Iterable[str]) -> None:
    """I pacchetti chiesti direttamente dal tema stanno in ``tex_packages`` o
    in ``info.tex.packages`` (contratto, §6.1)."""
    allowed = set(declared) | set(TEX_PACKAGES)
    for file in requested:
        name = file.removesuffix(".sty")
        if name not in allowed:
            raise CompileError(
                "regodoc.theme.package",
                f"il tema carica il pacchetto «{clip(name)}», che non sta né in tex_packages "
                "di theme.toml né fra i pacchetti del motore",
                file="theme.sty",
            )


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _read_log(doc: Path) -> str:
    return _read(doc / f"{DOCUMENT}.log").decode("utf-8", "replace")


def _check_log(log: str) -> None:
    """Comandi esterni tentati e comandi del contenuto ridefiniti."""
    shell = _SHELL.search(log)
    if shell:
        raise CompileError(
            "regodoc.theme.shell",
            f"il tema prova a eseguire un comando esterno («{clip(shell.group(1))}»): "
            "l'esecuzione è spenta",
            file="theme.sty",
        )
    redefined = _REDEFINED.search(log)
    if redefined:
        raise CompileError(
            "regodoc.theme.redefined",
            f"il tema ridefinisce \\{redefined.group(1)}, un comando del contenuto: un tema "
            "ridefinisce solo gli agganci \\Regodoc…",
            file="theme.sty",
        )


def _check_recorder(doc: Path, allowed: list[Path]) -> None:
    """Ogni file letto sta nella cartella di lavoro o nell'albero TeX; ogni file scritto
    sta nella cartella di lavoro. Un .fls malformato è un errore: lo ha riscritto il tema."""
    data = _read(doc / f"{DOCUMENT}.fls")
    text = data.decode("utf-8", "replace")
    if "\x00" in text or not text.startswith("PWD /"):
        raise _tampered()
    lines = text.split("\n")
    pwd = Path(lines[0].removeprefix("PWD "))
    work = doc.resolve()
    for line in lines[1:]:
        if not line:
            continue
        kind, _, name = line.partition(" ")
        if kind not in ("INPUT", "OUTPUT") or not name:
            raise _tampered()
        path = Path(os.path.realpath(pwd / name))
        if kind == "OUTPUT":
            if not path.is_relative_to(work) or path.name == f"{DOCUMENT}.fls":
                raise CompileError(
                    "regodoc.theme.write",
                    f"il tema scrive «{clip(name)}», fuori dalla cartella di lavoro "
                    "o sul registro dei file letti",
                    file="theme.sty",
                )
        elif not any(path.is_relative_to(root) for root in allowed):
            raise CompileError(
                "regodoc.theme.read",
                f"il tema legge «{clip(name)}», fuori dal pacchetto, dal tema e dall'albero TeX",
                file="theme.sty",
            )


def _tampered() -> CompileError:
    return CompileError(
        "regodoc.theme.write",
        "il registro dei file letti di pdflatex è stato riscritto durante la compilazione",
        file="theme.sty",
    )


def _failure(log: str) -> CompileError:
    """L'errore di una compilazione fallita, con il file e la riga quando il log li dà."""
    match = _ERROR.search(log)
    if match is None:
        return CompileError("", "pdflatex è uscito con un errore senza messaggio")
    message = match.group(1).strip()
    before = log[: match.start()]
    file = _current_file(before)
    line_match = _LINE.search(log, match.end())
    line = int(line_match.group(1)) if line_match else 0
    missing = _MISSING.search(message)
    if missing:
        name = missing.group(1)
        if name.endswith(_TEX_SUPPORT) and "/" not in name:
            return CompileError(
                "regodoc.tex.missing",
                f"manca «{clip(name)}» nell'immagine TeX",
                environment=True,
            )
        return CompileError(
            "regodoc.theme.read",
            f"il tema chiede «{clip(name)}», che non c'è o sta fuori dal pacchetto e dal tema",
            file=file,
            line=line,
        )
    cannot_write = _CANNOT_WRITE.search(message)
    if cannot_write:
        return CompileError(
            "regodoc.theme.write",
            f"il tema prova a scrivere «{clip(cannot_write.group(1))}», fuori dalla cartella "
            "di lavoro",
            file=file,
            line=line,
        )
    return CompileError("", f"pdflatex: {clip(message, 300)}", file=file, line=line)


def _current_file(log: str) -> str:
    """Il file che TeX stava leggendo, dalla pila delle parentesi del log."""
    stack: list[str] = []
    index = 0
    while index < len(log):
        char = log[index]
        if char == "(":
            match = _FILE_OPEN.match(log, index)
            if match:
                stack.append(match.group(1))
                index = match.end()
                continue
            stack.append("")
        elif char == ")" and stack:
            stack.pop()
        index += 1
    for name in reversed(stack):
        if name:
            return name.removeprefix("./") if name.startswith("./") else Path(name).name
    return ""
