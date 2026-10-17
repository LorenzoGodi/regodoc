"""Prova un motore installato avviandolo come lo avvia Rego (contratto, §2.2 e §2.3).

Ogni comando parte con l'interprete dato, ``-I -B -m regodoc --contract 1``, stdin da
``/dev/null``, una cartella corrente temporanea vuota e un ambiente con solo ``PATH`` e
``TMPDIR``, in un gruppo di processi suo. Allo scadere del tempo che ``info`` dichiara per il
comando, più 10 secondi di margine, lo strumento uccide l'intero gruppo con ``SIGKILL`` e lo
conta come codice 3.

I passi: ``info``, con il controllo di versione, contratto, expat e grammatiche; ``validate``
e ``canon`` del pacchetto d'esempio; ``build`` in PDF dell'archivio canonico. Esce con 1 al
primo passo che non torna, con 0 se tornano tutti, e scrive per ogni passo codice e durata.

    python3 tools/check_install.py --python VENV/bin/python --version 0.1.0
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = 1
GRAMMAR = "rego/1"
# Il margine del §2.3 oltre il tempo dichiarato, prima di uccidere il gruppo.
MARGIN = 10
# Il tempo di info prima di averlo letto: quello che info dichiara per sé.
INFO_SECONDS = 5
KILLED = 3


def run(command: Sequence[str], seconds: float, environment: Mapping[str, str]) -> tuple[int, str]:
    """Esegue ``command`` in una cartella vuota e in un gruppo di processi suo; restituisce il
    codice e lo stdout. Oltre ``seconds`` uccide il gruppo e restituisce il codice 3."""
    with tempfile.TemporaryDirectory() as folder:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=folder,
            env=dict(environment),
            start_new_session=True,
        )
        try:
            out, _ = process.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return KILLED, ""
        return process.returncode, out.decode("utf-8", "replace")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def info_problems(info: Mapping[str, object], version: str) -> list[str]:
    """Ciò che nella dichiarazione di ``info`` non va per chi usa il contratto 1."""
    problems = []
    if info.get("version") != version:
        problems.append(f"versione {info.get('version')!r}, attesa {version!r}")
    contracts = info.get("contracts")
    if not isinstance(contracts, list) or CONTRACT not in contracts:
        problems.append(f"il contratto {CONTRACT} manca in contracts: {contracts!r}")
    try:
        if _version(str(info["expat"])) < _version(str(info["expat_min"])):
            problems.append(f"expat {info['expat']} più vecchio di {info['expat_min']}")
    except (KeyError, ValueError):
        problems.append("expat o expat_min mancanti o illeggibili")
    grammars = info.get("grammars")
    if not isinstance(grammars, dict) or GRAMMAR not in grammars.get("read", []):
        problems.append(f"la grammatica {GRAMMAR} manca in grammars.read: {grammars!r}")
    return problems


def check(python: str, version: str, package: Path, out: Path) -> list[str]:
    """Esegue i passi e restituisce i problemi; scrive su stdout una riga per passo."""
    environment = {"PATH": os.environ.get("PATH", os.defpath), "TMPDIR": str(out)}
    engine = [python, "-I", "-B", "-m", "regodoc", "--contract", str(CONTRACT)]

    def step(name: str, args: list[str], seconds: float) -> tuple[int, str]:
        started = time.monotonic()
        code, stdout = run([*engine, name, *args, "--json"], seconds, environment)
        sys.stdout.write(f"{name}: codice {code}, {time.monotonic() - started:.1f} s\n")
        return code, stdout

    code, stdout = step("info", [], INFO_SECONDS + MARGIN)
    if code != 0:
        return [f"info: codice {code}"]
    info = json.loads(stdout)
    problems = info_problems(info, version)
    if problems:
        return [f"info: {problem}" for problem in problems]
    seconds = info["resources"]["time_seconds"]

    archive = out / "documento.regodoc"
    pdf = out / "documento.pdf"
    steps = [
        ("validate", [str(package)]),
        ("canon", [str(package), "-o", str(archive)]),
        ("build", [str(archive), "-o", str(pdf), "--format", "pdf"]),
    ]
    for name, args in steps:
        code, stdout = step(name, args, seconds[name] + MARGIN)
        if code != 0:
            return [f"{name}: codice {code}: {stdout.strip()[:2000]}"]
        report = json.loads(stdout)
        if report.get("errors"):
            return [f"{name}: errori nel rapporto con codice 0"]
    if not pdf.read_bytes().startswith(b"%PDF-"):
        return ["build: l'uscita non è un PDF"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="prova del motore installato")
    parser.add_argument("--python", required=True, help="l'interprete del venv del motore")
    parser.add_argument("--version", required=True, help="la versione attesa da info")
    parser.add_argument(
        "--package",
        type=Path,
        default=ROOT / "examples" / "colle-rovere",
        help="il pacchetto d'esempio, in cartella",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        problems = check(args.python, args.version, args.package.resolve(), Path(folder))
    for problem in problems:
        sys.stdout.write(problem + "\n")
    if problems:
        return 1
    sys.stdout.write("motore installato in ordine\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
