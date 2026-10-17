"""Costruisce il wheel e l'archivio sorgente di regodoc in modo riproducibile.

Costruisce dai file di un commit, l'ultimo o quello di ``--commit``, estratti con
``git archive`` in una cartella temporanea: le modifiche non committate e i file non tracciati
restano fuori, e lo strumento lo dice. La data dei file viene dallo stesso commit
(``SOURCE_DATE_EPOCH``), così due costruzioni dello stesso commit danno gli stessi byte, su
qualunque macchina e con qualunque umask. Con ``--commit`` si ricostruisce un commit del
passato, per esempio quello di una release, con lo strumento di oggi. Scrive i due
file e ``SHA256SUMS`` nella cartella d'uscita. Con ``--check`` costruisce due volte, in due
cartelle con umask diverse, ed esce con 1 se i byte non coincidono o se il wheel non porta la
versione del motore e ``License-Expression: Apache-2.0``.

Serve flit_core nell'interprete che lo esegue, alla versione fissata con le impronte in
``tools/requirements/build.txt``.

    python tools/build_release.py --out dist [--check] [--commit COMMIT]
"""

import argparse
import contextlib
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_date_epoch(commit: str = "HEAD") -> str:
    """La data del commit, in secondi: quella che i file del pacchetto portano."""
    if "SOURCE_DATE_EPOCH" in os.environ:
        return os.environ["SOURCE_DATE_EPOCH"]
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", commit],  # noqa: S607 - git dal PATH, come per l'igiene
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def committed_tree(destination: Path, commit: str = "HEAD") -> None:
    """Estrae in ``destination`` i file del commit, e solo quelli."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],  # noqa: S607 - git dal PATH
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")


def uncommitted() -> list[str]:
    """I file modificati o non tracciati dell'albero di lavoro, che la costruzione ignora."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607 - git dal PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line[3:] for line in status.splitlines()]


@contextlib.contextmanager
def _umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def build(out: Path, epoch: str, commit: str = "HEAD") -> list[Path]:
    """Costruisce wheel e archivio sorgente del commit in ``out``; restituisce i due file."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder)
        committed_tree(source, commit)
        return _build(source, out.resolve(), epoch)


def _build(source: Path, out: Path, epoch: str) -> list[Path]:
    from flit_core import buildapi  # noqa: PLC0415 - serve solo qui, e solo con flit_core

    out.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = epoch
    cwd = Path.cwd()
    try:
        os.chdir(source)
        names = [buildapi.build_wheel(str(out)), buildapi.build_sdist(str(out))]
    finally:
        os.chdir(cwd)
        if previous is None:
            del os.environ["SOURCE_DATE_EPOCH"]
        else:
            os.environ["SOURCE_DATE_EPOCH"] = previous
    return [out / name for name in names]


def write_sums(files: list[Path], out: Path) -> str:
    """Scrive ``SHA256SUMS`` nella forma di ``sha256sum`` e ne restituisce il testo."""
    text = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in sorted(files)
    )
    (out / "SHA256SUMS").write_text(text, encoding="utf-8")
    return text


def metadata_problems(wheel: Path, commit: str = "HEAD") -> list[str]:
    """Ciò che manca ai metadati del wheel: la versione del motore nel commit e la licenza
    SPDX."""
    text = subprocess.run(
        ["git", "show", f"{commit}:src/regodoc/__init__.py"],  # noqa: S607 - git dal PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    version = found.group(1) if found else "?"

    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        lines = archive.read(name).decode("utf-8").split("\n\n", 1)[0].splitlines()
    expected = [f"Version: {version}", "License-Expression: Apache-2.0"]
    return [f"manca «{line}» nei metadati" for line in expected if line not in lines]


def main() -> int:
    parser = argparse.ArgumentParser(description="costruzione riproducibile di regodoc")
    parser.add_argument("--out", type=Path, required=True, help="cartella d'uscita")
    parser.add_argument("--check", action="store_true", help="costruisce due volte e confronta")
    parser.add_argument("--commit", default="HEAD", help="il commit da costruire (HEAD)")
    args = parser.parse_args()
    epoch = source_date_epoch(args.commit)
    left_out = uncommitted()
    if args.commit != "HEAD":
        sys.stdout.write(f"costruzione dal commit {args.commit}\n")
    elif left_out:
        sys.stdout.write(
            f"costruzione dall'ultimo commit: {len(left_out)} file non committati restano fuori\n"
        )
    with _umask(0o022):
        files = build(args.out, epoch, args.commit)
    sums = write_sums(files, args.out)
    sys.stdout.write(sums)
    if args.check:
        with tempfile.TemporaryDirectory() as folder, _umask(0o077):
            again = build(Path(folder), epoch, args.commit)
            different = [
                first.name
                for first, second in zip(files, again, strict=True)
                if first.read_bytes() != second.read_bytes()
            ]
        problems = metadata_problems(files[0], args.commit)
        if different:
            problems.append(f"costruzioni diverse: {', '.join(different)}")
        for problem in problems:
            sys.stdout.write(problem + "\n")
        if problems:
            return 1
        sys.stdout.write("due costruzioni, stessi byte; metadati in ordine\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
