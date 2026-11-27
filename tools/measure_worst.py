"""Misura i tempi di ``validate`` e ``canon`` sui casi peggiori ammessi dai limiti del
contenuto.

Ogni caso è un pacchetto **valido**, con 48 voci in ``structure.toml`` e 45 parti al limite
di 384 KiB, ognuna piena di un solo tipo di elemento con il minimo di testo: voci d'elenco,
sezioni, righe di tabella, elementi in linea. Sono i pacchetti che chiedono più lavoro per
byte al lettore XML restando entro tutti i limiti, compreso quello dei caratteri.

``canon`` si misura sul comando vero, ``python -m regodoc canon`` come processo figlio, con i
limiti di tempo e di memoria che il motore applica da sé, verso un file temporaneo:
validazione, forma canonica, archivio, controlli dell'uscita e, se passano, rivalidazione
dell'archivio scritto; un'uscita scritta deve poi passare ``validate``. ``upgrade`` su un
pacchetto corrente fa lo stesso lavoro, con un tempo dichiarato più largo. Scritti su una
riga, i casi delle parti escono dai 384 KiB nella forma canonica e ``canon`` li rifiuta con
``regodoc.limit.file_size``; per questo ogni caso delle parti ha anche una variante più corta,
che nella forma canonica sta nei limiti e passa per intero.

Due casi riguardano le figure in PDF vettoriale di ``rego/2``: quattro figure dense al tetto di
tutto il pacchetto, piene di token minimi scelti a caso, e ottanta figure con flussi che
decodificati arrivano al tetto per file.

Il comando stampa i tempi ed esce con 1 se un caso non è valido, se ``canon`` rifiuta un caso
con un codice diverso da ``regodoc.limit.file_size`` (memoria o tempo esauriti compresi) o
rifiuta una variante canonica, o se un tempo supera quello che ``info`` dichiara per il
comando diviso ``--margin`` (predefinito 1, cioè il tempo dichiarato).

    python tools/measure_worst.py [--margin 1.5]
"""

import argparse
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests import test_limits as builders  # noqa: E402
from tests.support import (  # noqa: E402
    DRAWING,
    build_zip,
    example_files,
    pdf,
    pdf_figure,
    png_pixels,
    stream,
    validate_bytes,
    vector_files,
)

from regodoc import canonical  # noqa: E402
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


def vector_dense_case() -> tuple[dict[str, bytes], tuple[str, ...], int]:
    """Figure in PDF di rego/2 al tetto di tutto il pacchetto, piene di token minimi scelti a
    caso fra i più lenti per il lettore: così l'archivio non le comprime oltre il rapporto
    ammesso per le immagini, e il pacchetto sta nei 12 MiB compressi."""
    each = int(CONTENT_LIMITS["pdf_bytes"])
    count = int(CONTENT_LIMITS["pdf_total_bytes"]) // each
    generator = random.Random(20)  # noqa: S311 - casi ripetibili
    body = bytearray(b"[")
    tokens = 0
    room = each - len(pdf({**pdf_figure(), 5: b"[]"}))
    while len(body) < room - 2:
        body += generator.choice((b"<>", b"()", b"[]", b"/"))
        tokens += 1
    body += b" " * (room - len(body) + 1) + b"]"
    data = b""
    for _ in range(2):
        data = pdf({**pdf_figure(), 5: bytes(body)})
        excess = len(data) - each
        if excess > 0:
            body = body[: len(body) - 1 - excess] + b"]"
        elif excess < 0:
            body = body[:-1] + b" " * -excess + b"]"
    files = vector_files(example_files(), data)
    for number in range(1, count):
        files[f"images/dense{number}.pdf"] = data
    return files, (), count * tokens


def vector_streams_case() -> tuple[dict[str, bytes], tuple[str, ...], int]:
    """Tante figure in PDF quante ne ammette il pacchetto, ognuna con flussi che decodificati
    arrivano al tetto per file."""
    rest = int(CONTENT_LIMITS["pdf_stream_bytes"]) - len(DRAWING)
    data = pdf({**pdf_figure(), 5: stream(zlib.compress(b" " * rest, 9), b"/Filter /FlateDecode ")})
    files = vector_files(example_files(), data)
    for number in range(1, int(CONTENT_LIMITS["images"])):
        files[f"images/streams{number}.pdf"] = data
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


def _command(*argv: str) -> tuple[int, list[str]]:
    """Il comando vero, come processo figlio: con i limiti di tempo e di memoria che il
    motore applica da sé, come quando lo chiama Rego."""
    result = subprocess.run(
        [sys.executable, "-B", "-m", "regodoc", *argv, "--json"],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )
    report = json.loads(result.stdout)
    return result.returncode, sorted({e["code"] for e in report["errors"]})


def time_canon(data: bytes) -> tuple[float, list[str]]:
    """Il tempo migliore di due ``canon`` con il comando vero verso un file, con i codici di
    rifiuto; se ``canon`` scrive, l'uscita deve anche passare ``validate``."""
    best = float("inf")
    codes: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        package = Path(folder) / "in.regodoc"
        output = Path(folder) / "out.regodoc"
        package.write_bytes(data)
        for _ in range(2):
            start = time.perf_counter()
            code, codes = _command("canon", str(package), "-o", str(output))
            best = min(best, time.perf_counter() - start)
            if code not in (0, 1):
                codes = codes or [f"codice d'uscita {code}"]
                break
        if not codes:
            code, problems = _command("validate", str(output))
            if code != 0:
                codes = ["uscita non valida", *problems]
    return best, codes


# I casi di import: un document.md vicino ai 2 MiB, diviso in parti che nel pacchetto stanno
# nei 384 KiB, pieno di un solo tipo di blocco: voci d'elenco, enfasi o righe di tabella.
MARKDOWN_PARTS = 40


def markdown_cases() -> dict[str, Callable[[], bytes]]:
    limit = int(CONTENT_LIMITS["markdown_bytes"])
    budget = limit // MARKDOWN_PARTS - 64
    # Parole casuali di due lettere: un testo ripetuto si comprimerebbe oltre il rapporto
    # ammesso dall'archivio del pacchetto, e il caso misurerebbe un rifiuto.
    generator = random.Random(19)  # noqa: S311 - casi ripetibili
    letters = "abcdefghijklmnopqrstuvwxyz"

    def word() -> str:
        return generator.choice(letters) + generator.choice(letters)

    def fill(piece: Callable[[], str]) -> str:
        out: list[str] = []
        size = 0
        while size < budget:
            text = piece()
            out.append(text)
            size += len(text)
        return "".join(out)[:budget].rsplit("\n", 1)[0] + "\n"

    def elenchi(index: int) -> str:
        return fill(lambda: f"- {word()}\n  - {word()}\n")

    def enfasi(index: int) -> str:
        return fill(
            lambda: " ".join(f"*{word()}* **{word()}** `{word()}`" for _ in range(30)) + "\n\n"
        )

    def tabelle(index: int) -> str:
        return fill(
            lambda: (
                "| A | B |\n|---|--:|\n"
                + "".join(f"| {word()} | {word()} |\n" for _ in range(590))
                + "\n"
            )
        )

    def titoli(index: int) -> str:
        # Il caso della rilettura di L19: lunghe serie di spazi nei titoli, prima dei
        # cancelletti di chiusura, che il lettore toglie.
        return fill(lambda: f"### {word()}" + " " * 9_000 + f"#\n\n{word()}\n\n")

    def make(body: Callable[[int], str]) -> Callable[[], bytes]:
        def build() -> bytes:
            text = "# Caso peggiore\n\n" + "".join(
                f"## Parte {index}\n\n{body(index)}\n" for index in range(MARKDOWN_PARTS)
            )
            data = text.encode("utf-8")
            if len(data) > limit:  # pragma: no cover - una regressione del caso
                raise ValueError(f"il caso supera {limit} byte: {len(data)}")
            buffer = io.BytesIO()
            # Memorizzato: un testo così ripetitivo, compresso, supererebbe il rapporto.
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr(zipfile.ZipInfo("document.md", (1980, 1, 1, 0, 0, 0)), data)
            return buffer.getvalue()

        return build

    return {
        "md elenchi": make(elenchi),
        "md enfasi": make(enfasi),
        "md tabelle": make(tabelle),
        "md titoli": make(titoli),
    }


def time_import(data: bytes) -> tuple[float, list[str]]:
    """Il tempo migliore di due ``import`` con il comando vero, con i codici di rifiuto; se
    ``import`` scrive, l'uscita deve anche passare ``validate``."""
    best = float("inf")
    codes: list[str] = []
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "in.zip"
        output = Path(folder) / "out.regodoc"
        source.write_bytes(data)
        for _ in range(2):
            start = time.perf_counter()
            code, codes = _command("import", "--from", "markdown", str(source), "-o", str(output))
            best = min(best, time.perf_counter() - start)
            if code not in (0, 1):
                codes = codes or [f"codice d'uscita {code}"]
                break
        if not codes:
            code, problems = _command("validate", str(output))
            if code != 0:
                codes = ["uscita non valida", *problems]
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
    for label, build in (
        ("variabili", variables_case),
        ("immagini", images_case),
        ("pdf token", vector_dense_case),
        ("pdf flussi", vector_streams_case),
    ):
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
    allowed_import = RESOURCES["time_seconds"]["import"] / margin
    worst_import = 0.0
    for label, build_markdown in markdown_cases().items():
        data = build_markdown()
        seconds, refused = time_import(data)
        worst_import = max(worst_import, seconds)
        if refused:
            problems.append(f"{label}: import rifiuta con {refused}")
        print(
            f"{label:10s} {len(data):>8} byte      import {seconds:6.2f} s {refused or 'scritto'}"
        )
    print(f"validate: caso peggiore {worst:.2f} s, ammessi {allowed:.2f} s (margine {margin})")
    print(f"canon: caso peggiore {worst_canon:.2f} s, ammessi {allowed_canon:.2f} s")
    print(f"import: caso peggiore {worst_import:.2f} s, ammessi {allowed_import:.2f} s")
    for problem in problems:
        print(problem)
    passed = worst <= allowed and worst_canon <= allowed_canon and worst_import <= allowed_import
    return 0 if passed and not problems else 1


def _zip(case: tuple[dict[str, bytes], tuple[str, ...], int]) -> tuple[bytes, int]:
    files, stored, elements = case
    return build_zip(files, stored), elements


if __name__ == "__main__":
    sys.exit(main())
