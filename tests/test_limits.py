"""Prove al bordo dei limiti del contenuto (specifica, §7.2): ogni limite passa esattamente al
suo valore e si supera di uno con il codice previsto."""

import json
import random
import unittest
from collections.abc import Callable
from unittest import mock

from regodoc import validate
from regodoc.declaration import CONTENT_LIMITS, ENVELOPE_LIMITS
from regodoc.diagnostics import Collector, TooManyProblems
from tests.support import build_zip, example_files, png, png_pixels, validate_bytes, validate_files

L = CONTENT_LIMITS
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'


def part(body: str, root: str = "part") -> bytes:
    return f"{HEAD}<{root}>\n{body}\n</{root}>\n".encode()


def section(body: str, identifier: str = "limit") -> str:
    return f'<section id="{identifier}"><title>Titolo</title>{body}</section>'


def with_backup(body: str) -> dict[str, bytes]:
    """L'esempio con la parte «backup» sostituita: i suoi id e le sue variabili spariscono,
    quindi restano solo avvisi di variabili mai usate, che queste prove ignorano."""
    files = example_files()
    files["parts/backup.xml"] = part(body)
    summary = files["parts/summary.xml"].decode()
    files["parts/summary.xml"] = summary.replace(' through="backup"', "").encode()
    return files


def padded(files: dict[str, bytes], path: str, size: int, filler: bytes) -> dict[str, bytes]:
    """Il file allungato fino a ``size`` byte con un riempimento neutro alla fine."""
    data = files[path]
    files = dict(files)
    files[path] = data + filler * (size - len(data))
    return files


def part_of_size(size: int) -> bytes:
    """Una parte valida lunga esattamente ``size`` byte."""
    start = f'{HEAD}<part>\n<section id="limit"><title>T</title><p>'.encode()
    end = b"</p></section>\n</part>\n"
    return start + b"a" * (size - len(start) - len(end)) + end


def errors_zip(files: dict[str, bytes], stored: tuple[str, ...]) -> list[str]:
    """I codici d'errore di un archivio con alcune voci memorizzate senza compressione."""
    return [d.code for d in validate_bytes(build_zip(files, stored)).report.errors]


def errors(files: dict[str, bytes]) -> list[str]:
    return [d.code for d in validate_files(files).report.errors]


def table(columns: int, rows: int, cell: str = "x") -> str:
    spec = " ".join(["*"] + ["1cm"] * (columns - 1))
    row = "<row>" + f"<cell>{cell}</cell>" * columns + "</row>"
    return f'<table columns="{spec}">{row * rows}</table>'


def nested_sections(depth: int) -> str:
    inner = "<p>x</p>"
    for level in range(depth, 0, -1):
        inner = f'<section id="s{level}"><title>T</title>{inner}</section>'
    return inner


def list_of_depth(depth: int) -> str:
    inner = "<list><item>x</item></list>"
    for _ in range(depth - 1):
        inner = f"<list><item>x{inner}</item></list>"
    return inner


def variables(count: int) -> bytes:
    """Le variabili dell'esempio più altre, fino a ``count`` in tutto."""
    base = example_files()["variables.toml"].decode()
    have = base.count("\n")
    return (base + "".join(f"v{n} = {{ number = {n} }}\n" for n in range(count - have))).encode()


def words(count: int, seed: int = 0) -> str:
    """Testo di ``count`` caratteri, fatto di parole: si comprime come un testo vero, non come
    una sequenza ripetuta, e resta sotto il rapporto di compressione dell'archivio."""
    generator = random.Random(seed)  # noqa: S311 - prova ripetibile
    out: list[str] = []
    size = 0
    while size < count:
        word = "".join(
            generator.choice("abcdefghilmnoprstuvz") for _ in range(generator.randint(2, 9))
        )
        out.append(word)
        size += len(word) + 1
    return " ".join(out)[:count].rstrip().ljust(count, "a")


def measure(files: dict[str, bytes], attribute: str) -> int:
    """Il valore di un totale del motore (caratteri, rimandi, fonti) per un pacchetto."""
    counted: list[int] = []
    original = validate._check_totals

    def spy(context: object) -> None:
        counted.append(getattr(context, attribute))
        original(context)  # type: ignore[arg-type]

    with mock.patch.object(validate, "_check_totals", spy):
        validate_files(files)
    return counted[0]


def structure_with_parts(count: int) -> dict[str, bytes]:
    files = example_files()
    text = files["structure.toml"].decode()
    for n in range(count - 3):
        text += f'\n[[part]]\nid = "extra{n}"\ntitle = "P{n}"\naccent = "gray"\n'
        files[f"parts/extra{n}.xml"] = part(section("<p>x</p>", f"extra-section-{n}"))
    files["structure.toml"] = text.encode()
    return files


def references(count: int) -> str:
    return "<p>" + '<reference to="network"/>' * count + "</p>"


def sources(count: int) -> str:
    items = "".join(
        f'<source href="https://a.example/{n}" publisher="P">Fonte {n}</source>'
        for n in range(count)
    )
    return f'<sources id="many">{items}</sources>'


def without_sources(files: dict[str, bytes]) -> dict[str, bytes]:
    """L'esempio senza il suo elenco di fonti: <sources> è uno solo per documento."""
    network = files["parts/network.xml"].decode()
    start = network.index('  <section id="sources-network">')
    end = network.index("  </section>\n", start) + len("  </section>\n")
    network = network[:start] + network[end:]
    network = network.replace('<cite to="ap-guide"/>', "")
    files["parts/network.xml"] = network.encode()
    return files


class Boundary:
    """Un limite: come si costruisce un pacchetto con un valore dato, e il codice atteso."""

    def __init__(
        self, key: str, code: str, build: Callable[[int], dict[str, bytes]], limit: int
    ) -> None:
        self.key, self.code, self.build, self.limit = key, code, build, limit


BOUNDARIES = [
    Boundary("parts", "regodoc.limit.parts", structure_with_parts, L["parts"]),
    Boundary(
        "part_bytes",
        "regodoc.limit.file_size",
        lambda n: {**with_backup(section("<p>x</p>")), "parts/backup.xml": part_of_size(n)},
        L["part_bytes"],
    ),
    Boundary(
        "structure_bytes",
        "regodoc.limit.file_size",
        lambda n: padded(example_files(), "structure.toml", n, b"\n"),
        L["structure_bytes"],
    ),
    Boundary(
        "variables_bytes",
        "regodoc.limit.file_size",
        lambda n: padded(example_files(), "variables.toml", n, b"\n"),
        L["variables_bytes"],
    ),
    Boundary(
        "manifest_bytes",
        "regodoc.limit.file_size",
        lambda n: padded(example_files(), "manifest.json", n, b" "),
        L["manifest_bytes"],
    ),
    Boundary(
        "table_rows",
        "regodoc.limit.table_rows",
        lambda n: with_backup(section(table(1, n))),
        L["table_rows"],
    ),
    Boundary(
        "table_columns",
        "regodoc.xml.columns",
        lambda n: with_backup(section(table(n, 1))),
        L["table_columns"],
    ),
    Boundary(
        "cell_characters",
        "regodoc.limit.cell",
        lambda n: with_backup(section(table(1, 1, "a" * n))),
        L["cell_characters"],
    ),
    Boundary(
        "section_depth",
        "regodoc.xml.section_depth",
        lambda n: with_backup(nested_sections(n)),
        L["section_depth"],
    ),
    Boundary(
        "list_depth",
        "regodoc.xml.list_depth",
        lambda n: with_backup(section(list_of_depth(n))),
        L["list_depth"],
    ),
    Boundary(
        "variables",
        "regodoc.limit.variables",
        lambda n: {**example_files(), "variables.toml": variables(n)},
        L["variables"],
    ),
    Boundary(
        "references",
        "regodoc.limit.references",
        # Più i rimandi e le citazioni che l'esempio ha già.
        lambda n: with_backup(
            section(references(n - measure(with_backup(section("<p>x</p>")), "references")))
        ),
        L["references"],
    ),
    Boundary(
        "sources",
        "regodoc.limit.sources",
        lambda n: without_sources(with_backup(section(sources(n)))),
        L["sources"],
    ),
    Boundary(
        "href_characters",
        "regodoc.xml.href",
        lambda n: with_backup(
            section(f'<p><link href="https://a.example/{"a" * (n - 18)}">x</link></p>')
        ),
        L["href_characters"],
    ),
    Boundary(
        "listing_line_characters",
        "regodoc.limit.listing_line",
        lambda n: with_backup(section(f"<listing>\n{'a' * n}\n</listing>")),
        L["listing_line_characters"],
    ),
    Boundary(
        "images",
        "regodoc.limit.images",
        lambda n: {**example_files(), **{f"images/extra{k}.png": png() for k in range(n - 1)}},
        L["images"],
    ),
    Boundary(
        "image_side_pixels",
        "regodoc.image.structure",
        lambda n: {**example_files(), "images/coverage.png": png(width=n, height=1)},
        L["image_side_pixels"],
    ),
]


class ContentBoundaryTest(unittest.TestCase):
    def test_each_limit_at_and_beyond(self) -> None:
        for boundary in BOUNDARIES:
            with self.subTest(boundary.key):
                at = errors(boundary.build(boundary.limit))
                self.assertNotIn(boundary.code, at, f"{boundary.key} al limite")
                self.assertEqual(at, [], f"{boundary.key} al limite: {at}")
                beyond = errors(boundary.build(boundary.limit + 1))
                self.assertIn(boundary.code, beyond, f"{boundary.key} oltre il limite")

    def test_every_content_limit_has_a_boundary_test(self) -> None:
        covered = {b.key for b in BOUNDARIES} | {
            "characters",  # sotto, con il conteggio del motore
            "number_abs_max",  # sotto
            "image_bytes",  # sotto
            "element_depth",  # sotto
            "problems",  # sotto
            "readme_bytes",  # test_envelope
            "images_total_bytes",  # coincide con il tetto dell'involucro
            "table_columns_normal_size",  # tocca la resa, non la validazione
            "image_pixel_bytes",  # sotto, al passo intero di byte per pixel
            "images_pixel_bytes",  # sotto
        }
        self.assertEqual(sorted(set(L) - covered), [])

    def test_characters(self) -> None:
        base = with_backup(section("<p>a</p>"))
        missing = L["characters"] - measure(base, "characters")
        chunk = 300_000

        def build(extra: int) -> dict[str, bytes]:
            files = dict(base)
            text = files["structure.toml"].decode()
            parts_needed = -(-extra // chunk)
            # Ogni parte nuova aggiunge anche il titolo «T» della sezione: un carattere.
            remaining = extra - parts_needed
            for n in range(parts_needed):
                size = min(chunk - 1, remaining)
                remaining -= size
                body = section(f"<p>{words(size, n)}</p>", f"m{n}")
                files[f"parts/more{n}.xml"] = part(
                    body.replace("<title>Titolo</title>", "<title>T</title>")
                )
                text += f'\n[[part]]\nid = "more{n}"\ntitle = "Altro"\naccent = "gray"\n'
            files["structure.toml"] = text.encode()
            return files

        at = build(missing)
        self.assertEqual(measure(at, "characters"), L["characters"])
        self.assertEqual(errors(at), [])
        self.assertIn("regodoc.limit.characters", errors(build(missing + 1)))

    def test_number_abs_max(self) -> None:
        top = L["number_abs_max"]
        for value, ok in (
            (top, True),
            (-top, True),
            (top + 1, False),
            (f'"{top:,}"'.replace(",", "."), True),
            (f'"{top + 1:,}"'.replace(",", "."), False),
        ):
            with self.subTest(value):
                extra = f"v = {{ number = {value} }}\n".encode()
                files = example_files()
                files["variables.toml"] += extra
                found = errors(files)
                if ok:
                    self.assertEqual(found, [])
                else:
                    self.assertIn("regodoc.toml.value", found)

    def test_image_bytes(self) -> None:
        limit = L["image_bytes"]
        base = png()
        # Un blocco ancillare privato porta l'immagine alla dimensione voluta: dà un avviso
        # sui metadati, non un errore.
        for size, code in ((limit, None), (limit + 1, "regodoc.limit.image_size")):
            with self.subTest(size):
                filler = size - len(base) - 12
                noise = random.Random(size).randbytes(filler)  # noqa: S311 - prova ripetibile
                image = png(extra=[(b"ruNk", noise)])
                self.assertEqual(len(image), size)
                found = errors({**example_files(), "images/coverage.png": image})
                if code is None:
                    self.assertEqual(found, [])  # solo l'avviso sui metadati
                else:
                    self.assertEqual(found, [code])

    def test_image_pixel_bytes(self) -> None:
        # 6000 × 6000 RGBA a 8 bit è esattamente il tetto. Il passo successivo possibile, con
        # gli stessi lati, è RGB a 16 bit: i byte per pixel sono interi, il tetto non si può
        # superare di un byte solo.
        self.assertEqual(L["image_pixel_bytes"], 6000 * 6000 * 4)
        cases = (
            (png_pixels(6000, 6000, color=6), []),
            (png_pixels(6000, 6000, color=2, depth=16, raw=b""), ["regodoc.limit.image_size"]),
        )
        for image, expected in cases:
            files = {**example_files(), "images/coverage.png": image}
            found = errors_zip(files, stored=("images/coverage.png",))
            self.assertEqual(found, expected)

    def test_images_pixel_bytes(self) -> None:
        # Quattro immagini al tetto, una da 24.000.000 byte: 600.000.000 in tutto. Un'immagine
        # in più di un solo pixel grigio supera il tetto di un byte.
        self.assertEqual(L["images_pixel_bytes"], 4 * L["image_pixel_bytes"] + 24_000_000)
        files = example_files()
        big = png_pixels(6000, 6000, color=6)
        for number in range(4):
            files[f"images/big{number}.png"] = big
        # L'immagine dell'esempio, usata da una figura, prende i 24.000.000 byte che restano.
        files["images/coverage.png"] = png_pixels(6000, 1000, color=6)
        stored = tuple(path for path in files if path.startswith("images/"))
        self.assertEqual(errors_zip(files, stored=stored), [])
        files["images/zz-one.png"] = png_pixels(1, 1)
        stored = (*stored, "images/zz-one.png")
        self.assertEqual(errors_zip(files, stored=stored), ["regodoc.limit.images"])

    def test_element_depth(self) -> None:
        def nested(depth: int) -> bytes:
            # part > section > p > b > i > b > i …: «depth» elementi annidati in tutto.
            inline = "x"
            for level in range(depth - 3):
                tag = "b" if level % 2 == 0 else "i"
                inline = f"<{tag}>{inline}</{tag}>"
            return part(section(f"<p>{inline}</p>"))

        files = with_backup(section("<p>x</p>"))
        at = errors({**files, "parts/backup.xml": nested(L["element_depth"])})
        self.assertNotIn("regodoc.limit.depth", at)
        beyond = errors({**files, "parts/backup.xml": nested(L["element_depth"] + 1)})
        self.assertIn("regodoc.limit.depth", beyond)

    def test_errors_at_and_beyond_the_problem_cap(self) -> None:
        limit = L["problems"]

        def package(errors_count: int) -> list[object]:
            body = section("<p>" + '<var name="nope"/>' * errors_count + "</p>")
            return validate_files(with_backup(body)).report.items

        at = package(limit)
        self.assertEqual(
            [d.code for d in at if d.severity == "error"].count("regodoc.xml.unknown_variable"),
            limit,
        )
        self.assertNotIn("regodoc.limit.problems", [d.code for d in at])
        beyond = package(limit + 1)
        self.assertEqual(len(beyond), limit + 1)
        last = beyond[-1]
        self.assertEqual((last.code, str(last.severity)), ("regodoc.limit.problems", "error"))
        self.assertIn("regodoc.xml.unknown_variable in parts/backup.xml:", last.message)
        report = json.dumps([d.to_json() for d in beyond], ensure_ascii=False)
        self.assertLess(len(report.encode()), 1024 * 1024)


class WarningsBeyondTheCapTest(unittest.TestCase):
    """Emendamento del 15/10/2026: gli avvisi oltre il tetto non rifiutano il pacchetto."""

    def validate(self, unused: int) -> object:
        # Le variabili dell'esempio sono tutte usate: ogni variabile in più è un avviso.
        have = example_files()["variables.toml"].decode().count("\n")
        return validate_files({**example_files(), "variables.toml": variables(have + unused)})

    def test_warnings_at_the_cap(self) -> None:
        validation = self.validate(L["problems"])
        report = validation.report
        self.assertFalse(report.has_errors())
        self.assertEqual(len(report.items), L["problems"])
        self.assertEqual(report.warnings_omitted, 0)
        self.assertNotIn("regodoc.limit.warnings", [d.code for d in report.items])

    def test_one_and_two_warnings_beyond_the_cap(self) -> None:
        for extra, text in ((1, "1 avviso non è elencato"), (2, "2 avvisi non sono elencati")):
            with self.subTest(extra):
                report = self.validate(L["problems"] + extra).report
                self.assertFalse(report.has_errors())
                self.assertEqual(report.warnings_omitted, extra)
                self.assertEqual(len(report.items), L["problems"] + 1)
                last = report.items[-1]
                self.assertEqual(
                    (last.code, str(last.severity)), ("regodoc.limit.warnings", "warning")
                )
                self.assertIn(text, last.message)

    def test_an_error_after_many_warnings_stops_and_is_named(self) -> None:
        collector = Collector(limit=3)
        for _ in range(5):
            collector.warning("regodoc.toml.unused_variable", "x")
        with self.assertRaises(TooManyProblems):
            collector.error("regodoc.xml.unknown_id", "x", "parts/a.xml", 7, 3)
        collector.finish()
        self.assertEqual(len(collector.items), 4)
        last = collector.items[-1]
        self.assertEqual((last.code, str(last.severity)), ("regodoc.limit.problems", "error"))
        self.assertIn("regodoc.xml.unknown_id in parts/a.xml:7:3", last.message)
        self.assertEqual(collector.warnings_omitted, 2)

    def test_errors_exactly_at_the_cap_do_not_stop(self) -> None:
        collector = Collector(limit=3)
        for _ in range(3):
            collector.error("regodoc.xml.unknown_id", "x")
        collector.finish()
        self.assertEqual([d.code for d in collector.items], ["regodoc.xml.unknown_id"] * 3)

    def test_the_cli_reports_the_omitted_warnings(self) -> None:
        validation = self.validate(L["problems"] + 7)
        self.assertEqual(validation.report.warnings_omitted, 7)


class EnvelopeBoundaryTest(unittest.TestCase):
    def test_file_count(self) -> None:
        limit = ENVELOPE_LIMITS["files"]
        base = example_files()
        for count, ok in ((limit, True), (limit + 1, False)):
            with self.subTest(count):
                files = dict(base)
                for n in range(count - len(base)):
                    files[f"images/f{n}.png"] = png()
                found = [c for c in errors(files) if c.startswith("regodoc.archive")]
                self.assertEqual(found == [], ok, found)


if __name__ == "__main__":
    unittest.main()
