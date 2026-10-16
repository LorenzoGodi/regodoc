"""Misura i tempi di ``validate`` sui casi peggiori ammessi dai limiti del contenuto.

Ogni caso è un pacchetto **valido**, con 48 voci in ``structure.toml`` e 45 parti al limite
di 384 KiB, ognuna piena di un solo tipo di elemento con il minimo di testo: voci d'elenco,
sezioni, righe di tabella, elementi in linea. Sono i pacchetti che chiedono più lavoro per
byte al lettore XML restando entro tutti i limiti, compreso quello dei caratteri.

Il comando stampa i tempi ed esce con 1 se un caso non è valido, o se supera il tempo che
``info`` dichiara per ``validate`` diviso ``--margin`` (predefinito 1, cioè il tempo
dichiarato).

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
from tests.support import build_zip, example_files, png_pixels, validate_bytes  # noqa: E402

from regodoc.declaration import CONTENT_LIMITS, RESOURCES  # noqa: E402

LABELS = ("observed", "declared", "decided", "proposed", "to-verify", "critical")
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
        body, count = fill(lambda _n: f"<item>{words.choice('abcdefgh')}</item>")
        return f'<section id="x{k}"><title>T</title><list>{body}</list></section>', count

    def sections(k: int) -> tuple[str, int]:
        return fill(lambda n: f'<section id="s{k}-{n}"><title>T</title><p>x</p></section>')

    def inline(k: int) -> tuple[str, int]:
        # Elementi in linea senza testo o con un solo carattere: il lettore lavora per
        # elemento, mentre il conteggio dei caratteri resta basso.
        # In ordine casuale, con lettere diverse: una sequenza regolare supererebbe il
        # rapporto di compressione dell'archivio.
        def piece(_n: int) -> str:
            letter = words.choice("abcdefghilmnoprstuvz")
            return words.choice(
                (
                    "<break/>",
                    f"<b>{letter}</b>",
                    f'<label type="{words.choice(LABELS)}"/>',
                    f"<i>{letter}</i>",
                )
            )

        body, count = fill(piece)
        return f'<section id="x{k}"><title>T</title><p>x{body}</p></section>', count

    def tables(k: int) -> tuple[str, int]:
        def row(_n: int) -> str:
            # Celle diverse fra loro: righe tutte uguali supererebbero il rapporto di
            # compressione dell'archivio e la lettura si fermerebbe prima delle parti.
            # Una cifra per cella: il testo resta entro il limite dei caratteri.
            cells = "".join(f"<cell>{words.randrange(10)}</cell>" for _ in range(10))
            return f"<row>{cells}</row>"

        count = int(CONTENT_LIMITS["table_rows"])
        rows = "".join(row(n) for n in range(count))
        columns = " ".join(["*"] + ["1cm"] * 9)
        return (
            f'<section id="x{k}"><title>T</title><table columns="{columns}">{rows}</table>'
            "</section>",
            count,
        )

    def mixed(k: int) -> tuple[str, int]:
        # Metà delle parti di elenchi, metà di elementi in linea: un caso combinato.
        return items(k) if k % 2 else inline(k)

    return {
        "elenchi": items,
        "sezioni": sections,
        "tabelle": tables,
        "in linea": inline,
        "misto": mixed,
    }


def variables_case() -> tuple[dict[str, bytes], tuple[str, ...], int]:
    """1.500 variabili di testo che riempiono variables.toml fino al suo limite."""
    files = example_files()
    count = int(CONTENT_LIMITS["variables"])
    size = int(CONTENT_LIMITS["variables_bytes"]) - len(files["variables.toml"]) - 64
    each = size // count - len('v0000 = { text = "" }\n')
    lines = [f'v{n:04d} = {{ text = "{"a" * each}" }}\n' for n in range(count - 8)]
    files["variables.toml"] += "".join(lines).encode()
    return files, (), count


def images_case() -> tuple[dict[str, bytes], tuple[str, ...], int]:
    """Immagini PNG con i pixel al tetto di tutto il pacchetto, da decomprimere."""
    files = example_files()
    big = png_pixels(6000, 6000, color=6)
    for number in range(4):
        files[f"images/big{number}.png"] = big
    files["images/coverage.png"] = png_pixels(6000, 1000, color=6)
    stored = tuple(path for path in files if path.startswith("images/"))
    return files, stored, len(stored)


def measure(body_of: Callable[[int], tuple[str, int]]) -> tuple[float, int, list[str]]:
    files = builders.structure_with_parts(PARTS + 3)
    elements = 0
    for k in range(PARTS):
        body, count = body_of(k)
        elements += count
        files[f"parts/extra{k}.xml"] = builders.part(body)
    return timed(build_zip(files), elements)


def timed(data: bytes, elements: int) -> tuple[float, int, list[str]]:
    """Il tempo migliore di due validazioni, con gli errori trovati."""
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
    invalid = []
    measures = {
        label: lambda body_of=body_of: measure(body_of) for label, body_of in cases().items()
    }
    for label, build in (("variabili", variables_case), ("immagini", images_case)):
        measures[label] = lambda build=build: timed(build_zip(*build()[:2]), build()[2])
    for label, run in measures.items():
        seconds, elements, codes = run()
        worst = max(worst, seconds)
        if codes:
            invalid.append(label)
        print(f"{label:10s} {elements:>8} elementi  {seconds:6.2f} s  errori {codes}", flush=True)
    print(f"caso peggiore {worst:.2f} s, ammessi {allowed:.2f} s (margine {margin})")
    if invalid:
        print(f"casi non validi, quindi non ammessi dai limiti: {', '.join(invalid)}")
    return 0 if worst <= allowed and not invalid else 1


if __name__ == "__main__":
    sys.exit(main())
