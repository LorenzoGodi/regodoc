"""Rigenera i golden dell'emettitore LaTeX: il testo di document.tex per i due esempi.

    python tools/update_golden.py

Dopo un cambiamento voluto dell'emettitore, la differenza dei golden si rilegge come ogni
altra modifica e va nello stesso commit.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.support import EXAMPLE, LONG_EXAMPLE, example_files  # noqa: E402
from tests.test_render import GOLDEN, render_files  # noqa: E402


def main() -> int:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for root in (EXAMPLE, LONG_EXAMPLE):
        target = GOLDEN / f"{root.name}.tex"
        target.write_text(render_files(example_files(root)), encoding="utf-8")
        print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
