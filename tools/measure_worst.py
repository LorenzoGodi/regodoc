"""Misura i tempi di ``validate`` e ``canon`` sui casi peggiori ammessi dai limiti del
contenuto.

Ogni caso è un pacchetto **valido**, con 48 voci in ``structure.toml`` e 45 parti al limite
di 384 KiB, ognuna piena di un solo tipo di elemento con il minimo di testo: voci d'elenco,
sezioni, righe di tabella, elementi in linea. Sono i pacchetti che chiedono più lavoro per
byte al lettore XML restando entro tutti i limiti, compreso quello dei caratteri.

``canon`` si misura sul percorso vero, ``canon.run`` verso un file temporaneo: validazione,
forma canonica, archivio, controlli dell'uscita e, se passano, rivalidazione dell'archivio
scritto. ``upgrade`` su un pacchetto corrente fa lo stesso lavoro, con un tempo dichiarato
più largo. Scritti su una riga, i casi delle parti escono dai 384 KiB nella forma canonica e
``canon`` li rifiuta con ``regodoc.limit.file_size``; per questo ogni caso delle parti ha
anche una variante più corta, che nella forma canonica sta nei limiti e passa per intero.

Il comando stampa i tempi ed esce con 1 se un caso non è valido, se ``canon`` rifiuta un
caso con un codice diverso da ``regodoc.limit.file_size`` o rifiuta una variante canonica, o
se un tempo supera quello che ``info`` dichiara per il comando diviso ``--margin``
(predefinito 1, cioè il tempo dichiarato).

    python tools/measure_worst.py [--margin 1.5]
"""

import argparse
import random
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests import test_limits as builders  # noqa: E402
from tests.support import build_zip, example_files, png_pixels, validate_bytes  # noqa: E402

from regodoc import canon, canonical  # noqa: E402
from regodoc.declaration import CONTENT_LIMITS, RESOURCES  # noqa: E402

LABELS = ("observed", "declared", "decided", "proposed", "to-verify", "critical")
PARTS = 45
BUDGET = int(CONTENT_LIMITS["part_bytes"]) - 300


# Il budget di byte per parte in vigore: BUDGET, oppure meno per le varianti canoniche.
_BUDGET = [BUDGET]


def fill(make: Callable[[int], str], budget: int | None = None) -> tuple[str, int]:
    """Ripete ``make`` finché il testo sta nel budget di byte; restituisce testo e numero."""
    budget = _BUDGET[0] if budget is None else budget
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


def part_package(body_of: Callable[[int], tuple[str, int]]) -> tuple[bytes, int]:
    files = builders.structure_with_parts(PARTS + 3)
    elements = 0
    for k in range(PARTS):
        body, count = body_of(k)
        elements += count
        files[f"parts/extra{k}.xml"] = builders.part(body)
    return build_zip(files), elements


def time_validate(data: bytes) -> tuple[float, list[str]]:
    """Il tempo migliore di due validazioni, con gli errori trovati."""
    best = float("inf")
    codes: list[str] = []
    for _ in range(2):
        start = time.perf_counter()
        validation = validate_bytes(data)
        best = min(best, time.perf_counter() - start)
        codes = sorted({d.code for d in validation.report.errors})
    return best, codes


def time_canon(data: bytes) -> tuple[float, list[str]]:
    """Il tempo migliore di due ``canon`` verso un file, con i codici di rifiuto."""
    best = float("inf")
    codes: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        package = Path(folder) / "in.regodoc"
        package.write_bytes(data)
        for _ in range(2):
            start = time.perf_counter()
            outcome = canon.run(
                package,
                str(Path(folder) / "out.regodoc"),
                document=None,
                base_version=None,
                files_dir=None,
                strict=False,
            )
            best = min(best, time.perf_counter() - start)
            codes = sorted({d.code for d in outcome.validation.report.errors})
    return best, codes


def growth(data: bytes) -> float:
    """Quanto la forma canonica allunga la parte che cresce di più."""
    validation = validate_bytes(data)
    assert validation.package is not None  # noqa: S101 - il caso è valido
    return max(
        len(body) / len(validation.package.files[path])
        for path, body in canonical.content_files(validation)
        if path.startswith("parts/extra")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="tempi di validate e canon sui casi peggiori")
    parser.add_argument("--margin", type=float, default=1.0, help="margine sul tempo dichiarato")
    margin = parser.parse_args().margin
    allowed = RESOURCES["time_seconds"]["validate"] / margin
    allowed_canon = RESOURCES["time_seconds"]["canon"] / margin
    worst = worst_canon = 0.0
    problems = []
    runs: list[tuple[str, Callable[[], tuple[bytes, int]], bool]] = []
    for label, body_of in cases().items():
        runs.append((label, lambda body_of=body_of: part_package(body_of), True))
    for label, build in (("variabili", variables_case), ("immagini", images_case)):
        runs.append((label, lambda build=build: _zip(build()), False))
    for label, make, scalable in runs:
        _BUDGET[0] = BUDGET
        data, elements = make()
        seconds, codes = time_validate(data)
        rewrite, refused = time_canon(data)
        worst, worst_canon = max(worst, seconds), max(worst_canon, rewrite)
        if codes:
            problems.append(f"{label}: non valido {codes}")
        if set(refused) - {"regodoc.limit.file_size"}:
            problems.append(f"{label}: canon rifiuta con {refused}")
        print(
            f"{label:10s} {elements:>8} elementi  validate {seconds:6.2f} s  "
            f"canon {rewrite:6.2f} s {refused or 'scritto'}",
            flush=True,
        )
        if scalable and refused:
            _BUDGET[0] = int(BUDGET / growth(data) * 0.99)
            data, elements = make()
            rewrite, refused = time_canon(data)
            worst_canon = max(worst_canon, rewrite)
            if refused:
                problems.append(f"{label} canonico: canon rifiuta con {refused}")
            print(
                f"{'  canonico':10s} {elements:>8} elementi  {'':17s}"
                f"canon {rewrite:6.2f} s {refused or 'scritto'}",
                flush=True,
            )
    _BUDGET[0] = BUDGET
    print(f"validate: caso peggiore {worst:.2f} s, ammessi {allowed:.2f} s (margine {margin})")
    print(f"canon: caso peggiore {worst_canon:.2f} s, ammessi {allowed_canon:.2f} s")
    for problem in problems:
        print(problem)
    passed = worst <= allowed and worst_canon <= allowed_canon
    return 0 if passed and not problems else 1


def _zip(case: tuple[dict[str, bytes], tuple[str, ...], int]) -> tuple[bytes, int]:
    files, stored, elements = case
    return build_zip(files, stored), elements


if __name__ == "__main__":
    sys.exit(main())
