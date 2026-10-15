"""Misura i tempi di ``validate`` sui casi peggiori ammessi dai limiti del contenuto.

Ogni caso è un pacchetto con 48 voci in ``structure.toml`` e 45 parti al limite di
384 KiB, ognuna piena di un solo tipo di elemento: elenchi di voci brevi, sezioni brevi,
tabelle. Sono i pacchetti che chiedono più lavoro per byte al lettore XML.

Il comando stampa i tempi ed esce con 1 se un caso supera il tempo che ``info`` dichiara per
``validate`` diviso ``--margin`` (predefinito 1, cioè il tempo dichiarato).

    python tools/measure_worst.py [--margin 1.5]
"""

import argparse
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests import test_limits as builders  # noqa: E402
from tests.support import build_zip, validate_bytes  # noqa: E402

from regodoc.declaration import CONTENT_LIMITS, RESOURCES  # noqa: E402

PARTS = 45
BUDGET = int(CONTENT_LIMITS["part_bytes"]) - 300


def fill(make: Callable[[int], str], budget: int = BUDGET) -> tuple[str, int]:
    """Ripete ``make`` finché il testo sta nel budget di byte; restituisce testo e numero."""
    pieces: list[str] = []
    size = 0
    while True:
        piece = make(len(pieces))
        if size + len(piece.encode()) > budget:
            return "".join(pieces), len(pieces)
        pieces.append(piece)
        size += len(piece.encode())


def cases() -> dict[str, Callable[[int], tuple[str, int]]]:
    words = random.Random(1)  # noqa: S311 - misura ripetibile

    def items(k: int) -> tuple[str, int]:
        body, count = fill(lambda n: f"<item>voce {n} {words.choice(['rete', 'disco'])}</item>")
        return f'<section id="x{k}"><title>T</title><list>{body}</list></section>', count

    def sections(k: int) -> tuple[str, int]:
        return fill(lambda n: f'<section id="s{k}-{n}"><title>T{n}</title><p>x</p></section>')

    def tables(k: int) -> tuple[str, int]:
        def row(_n: int) -> str:
            # Celle diverse fra loro: righe tutte uguali supererebbero il rapporto di
            # compressione dell'archivio e la lettura si fermerebbe prima delle parti.
            cells = "".join(f"<cell>{words.randrange(10**6)}</cell>" for _ in range(10))
            return f"<row>{cells}</row>"

        count = int(CONTENT_LIMITS["table_rows"])
        rows = "".join(row(n) for n in range(count))
        columns = " ".join(["*"] + ["1cm"] * 9)
        return (
            f'<section id="x{k}"><title>T</title><table columns="{columns}">{rows}</table>'
            "</section>",
            count,
        )

    return {"elenchi": items, "sezioni": sections, "tabelle": tables}


def measure(body_of: Callable[[int], tuple[str, int]]) -> tuple[float, int, list[str]]:
    files = builders.structure_with_parts(PARTS + 3)
    elements = 0
    for k in range(PARTS):
        body, count = body_of(k)
        elements += count
        files[f"parts/extra{k}.xml"] = builders.part(body)
    data = build_zip(files)
    best = float("inf")
    codes: list[str] = []
    for _ in range(2):
        start = time.perf_counter()
        validation = validate_bytes(data)
        best = min(best, time.perf_counter() - start)
        codes = sorted({d.code for d in validation.report.errors})
    return best, elements, codes


def main() -> int:
    parser = argparse.ArgumentParser(description="tempi di validate sui casi peggiori")
    parser.add_argument("--margin", type=float, default=1.0, help="margine sul tempo dichiarato")
    margin = parser.parse_args().margin
    allowed = RESOURCES["time_seconds"]["validate"] / margin
    worst = 0.0
    for label, body_of in cases().items():
        seconds, elements, codes = measure(body_of)
        worst = max(worst, seconds)
        print(f"{label:10s} {elements:>8} elementi  {seconds:6.2f} s  errori {codes}", flush=True)
    print(f"caso peggiore {worst:.2f} s, ammessi {allowed:.2f} s (margine {margin})")
    return 0 if worst <= allowed else 1


if __name__ == "__main__":
    sys.exit(main())
