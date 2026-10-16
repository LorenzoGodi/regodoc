"""Costruisce il wheel e l'archivio sorgente di regodoc in modo riproducibile.

La data dei file viene dall'ultimo commit (``SOURCE_DATE_EPOCH``), così due costruzioni dello
stesso commit danno gli stessi byte, su qualunque macchina e con qualunque umask. Scrive i due
file e ``SHA256SUMS`` nella cartella d'uscita. Con ``--check`` costruisce due volte, in due
cartelle con umask diverse, ed esce con 1 se i byte non coincidono o se il wheel non porta la
versione del motore e ``License-Expression: Apache-2.0``.

Serve flit_core nell'interprete che lo esegue, alla versione fissata con le impronte in
``tools/requirements/build.txt``.

    python tools/build_release.py --out dist [--check]
"""

import argparse
import contextlib
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_date_epoch() -> str:
    """La data dell'ultimo commit, in secondi: quella che i file del pacchetto portano."""
    if "SOURCE_DATE_EPOCH" in os.environ:
        return os.environ["SOURCE_DATE_EPOCH"]
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct"],  # noqa: S607 - git dal PATH, come per l'igiene
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@contextlib.contextmanager
def _umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def build(out: Path, epoch: str) -> list[Path]:
    """Costruisce wheel e archivio sorgente in ``out``; restituisce i due file."""
    from flit_core import buildapi  # noqa: PLC0415 - serve solo qui, e solo con flit_core

    out.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = epoch
    cwd = Path.cwd()
    try:
        os.chdir(ROOT)
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


def metadata_problems(wheel: Path) -> list[str]:
    """Ciò che manca ai metadati del wheel: la versione del motore e la licenza SPDX."""
    sys.path.insert(0, str(ROOT / "src"))
    from regodoc import __version__  # noqa: PLC0415 - la versione del sorgente costruito

    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        lines = archive.read(name).decode("utf-8").split("\n\n", 1)[0].splitlines()
    expected = [f"Version: {__version__}", "License-Expression: Apache-2.0"]
    return [f"manca «{line}» nei metadati" for line in expected if line not in lines]


def main() -> int:
    parser = argparse.ArgumentParser(description="costruzione riproducibile di regodoc")
    parser.add_argument("--out", type=Path, required=True, help="cartella d'uscita")
    parser.add_argument("--check", action="store_true", help="costruisce due volte e confronta")
    args = parser.parse_args()
    epoch = source_date_epoch()
    with _umask(0o022):
        files = build(args.out, epoch)
    sums = write_sums(files, args.out)
    sys.stdout.write(sums)
    if args.check:
        with tempfile.TemporaryDirectory() as folder, _umask(0o077):
            again = build(Path(folder), epoch)
            different = [
                first.name
                for first, second in zip(files, again, strict=True)
                if first.read_bytes() != second.read_bytes()
            ]
        problems = metadata_problems(files[0])
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
