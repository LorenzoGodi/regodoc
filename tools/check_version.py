"""Controlla la regola della versione dopo un rilascio (docs/release.md, «Il rilascio»).

Una versione senza ``.dev`` in ``main`` è quella rilasciata, o da rilasciare, su quel commit.
Se i commit sopra ``main`` cambiano il motore, cioè un file sotto ``src/regodoc/`` (in
``__init__.py`` conta tutto tranne la riga di ``__version__``), la versione deve salire oltre
quella di ``main``: ``0.1.1.dev0`` dopo ``0.1.0``, per esempio, così un wheel costruito da
quei commit non porta il numero della release. Una versione ``.dev`` in ``main`` può restare
com'è. Controlla anche la forma della versione.

    python tools/check_version.py --base origin/main
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = "src/regodoc/"
INIT = "src/regodoc/__init__.py"
_FORM = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?")
_LINE = re.compile(r'^__version__ = "([^"]+)"\n', re.M)


def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],  # noqa: S607 - git dal PATH, come per l'igiene
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def version_of(init: str) -> str:
    """La versione scritta in ``__init__.py``, o una stringa vuota se manca."""
    found = _LINE.search(init)
    return found.group(1) if found else ""


def _key(version: str) -> tuple[int, int, int, float]:
    """L'ordine delle versioni: una ``.dev`` viene prima della stessa versione senza."""
    found = _FORM.fullmatch(version)
    if found is None:
        raise ValueError(version)
    major, minor, patch, dev = found.groups()
    return int(major), int(minor), int(patch), float(dev) if dev is not None else float("inf")


def problems(base: str, head: str, engine_changed: bool) -> list[str]:
    """I problemi della versione ``head`` sopra ``base``, sapendo se il motore è cambiato."""
    if not _FORM.fullmatch(head):
        return [f"versione «{head}» fuori dalla forma N.N.N o N.N.N.devN"]
    if not _FORM.fullmatch(base):
        return [f"versione di base «{base}» fuori dalla forma N.N.N o N.N.N.devN"]
    if _key(head) < _key(base):
        return [f"la versione scende: da {base} a {head}"]
    if engine_changed and ".dev" not in base and head == base:
        return [
            f"il motore cambia ma la versione resta {base}, quella rilasciata: va portata a "
            "una versione .dev successiva, per esempio "
            f"{'.'.join(base.split('.')[:2])}.{int(base.split('.')[2]) + 1}.dev0"
        ]
    return []


def engine_changed(base: str, root: Path = ROOT) -> bool:
    """Se i commit da ``base`` a HEAD cambiano il motore, salvo la riga della versione."""
    names = _git("diff", "--name-only", f"{base}...HEAD", "--", ENGINE, root=root).split()
    if any(name != INIT for name in names):
        return True
    if INIT not in names:
        return False
    before = _LINE.sub("", _git("show", f"{base}:{INIT}", root=root))
    after = _LINE.sub("", _git("show", f"HEAD:{INIT}", root=root))
    return before != after


def main() -> int:
    parser = argparse.ArgumentParser(description="regola della versione dopo un rilascio")
    parser.add_argument("--base", required=True, help="il commit di main, es. origin/main")
    args = parser.parse_args()
    base = version_of(_git("show", f"{args.base}:{INIT}"))
    head = version_of(_git("show", f"HEAD:{INIT}"))
    changed = engine_changed(args.base)
    found = problems(base, head, changed)
    for problem in found:
        sys.stdout.write(f"versione: {problem}\n")
    if found:
        return 1
    state = "cambia" if changed else "non cambia"
    sys.stdout.write(f"versione: {base} in main, {head} qui; il motore {state}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
