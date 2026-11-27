"""La conversione da Markdown md/1 a pacchetto (docs/spec/md-1.md, §1, §3 e §6)."""

import io
import json
import random
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from regodoc import declaration, importer
from tests.support import EXAMPLE, EXAMPLES, jpeg, run_cli, validate_bytes

PNG = (EXAMPLE / "images" / "coverage.png").read_bytes()
SIGNATURE = b"Firma-sintetica-di-import-77"

DOCUMENT = """# Rinnovo della rete

Una sintesi in **due** righe,
prima delle parti.

## Rete e collegamenti

### Rete locale

Le postazioni passano da un apparato di *vecchia generazione*.

- dodici postazioni
- due stampanti
  - una a colori

| Apparato | Anni |
|---|---:|
| commutatore | 9 |

![Copertura misurata](images/coverage.png)

```
ping -c 3 nas
```

## Copie di sicurezza

Ogni notte, alle 2.
"""


def bundle(text: str = DOCUMENT, images: dict[str, bytes] | None = None) -> dict[str, bytes]:
    files = {"document.md": text.encode("utf-8")}
    files.update({"images/coverage.png": PNG} if images is None else images)
    return files


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def folder(self, files: dict[str, bytes], name: str = "in") -> Path:
        root = self.root / name
        for path, data in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return root

    def archive(self, files: dict[str, bytes], name: str = "in.zip") -> Path:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, data in files.items():
                archive.writestr(zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0)), data)
        target = self.root / name
        target.write_bytes(buffer.getvalue())
        return target

    def run_import(
        self, source: Path, name: str = "out.regodoc", **options: object
    ) -> tuple[importer.canon.Outcome, Path]:
        target = self.root / name
        outcome = importer.run(
            source,
            str(target),
            language=str(options.get("language", "it")),
            document_id=options.get("document_id"),  # type: ignore[arg-type]
            strict=bool(options.get("strict", False)),
        )
        return outcome, target

    def problems(self, files: dict[str, bytes]) -> list[tuple[str, str, int]]:
        self.count = getattr(self, "count", 0) + 1
        outcome, target = self.run_import(self.folder(files, f"in-{self.count}"))
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(target.exists())
        return [(d.code, d.file, d.line) for d in outcome.validation.report.errors]

    def written(self, target: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(target) as archive:
            return {name: archive.read(name) for name in archive.namelist()}


class ConversionTest(Workspace):
    def test_the_example(self) -> None:
        outcome, target = self.run_import(self.folder(bundle()))
        self.assertEqual(outcome.exit_code, 0, outcome.validation.report.items)
        self.assertEqual(outcome.validation.report.items, [])
        files = self.written(target)
        self.assertEqual(
            list(files),
            [
                "mimetype",
                "manifest.json",
                "README.md",
                "structure.toml",
                "parts/opening.xml",
                "parts/rete-e-collegamenti.xml",
                "parts/copie-di-sicurezza.xml",
                "images/coverage.png",
            ],
        )
        structure = files["structure.toml"].decode()
        self.assertIn('title = "Rinnovo della rete"', structure)
        self.assertIn('accent = "azure"', structure)
        self.assertIn('accent = "slate"', structure)
        part = files["parts/rete-e-collegamenti.xml"].decode()
        for piece in (
            "<title>Rete locale</title>",
            "<i>vecchia generazione</i>",
            '<table columns="* *" align="left right">',
            '<figure file="images/coverage.png">',
            "<caption>Copertura misurata</caption>",
            "<listing>\nping -c 3 nas\n</listing>",
            "<item>una a colori</item>",
        ):
            self.assertIn(piece, part)
        self.assertIn("<b>due</b> righe, prima", files["parts/opening.xml"].decode())
        self.assertEqual(outcome.summary["grammar"], "rego/2")

    def test_the_output_is_a_canonical_valid_package(self) -> None:
        _, target = self.run_import(self.folder(bundle()))
        data = target.read_bytes()
        self.assertEqual([d.code for d in validate_bytes(data).report.items], [])
        again = importer.canon.run(
            target,
            str(self.root / "again.regodoc"),
            document=None,
            base_version=None,
            files_dir=None,
            strict=False,
        )
        self.assertEqual(again.exit_code, 0)
        self.assertEqual((self.root / "again.regodoc").read_bytes(), data)

    def test_same_input_same_bytes_from_folder_and_archive(self) -> None:
        _, first = self.run_import(self.folder(bundle()), "a.regodoc")
        _, second = self.run_import(self.folder(bundle(), "in2"), "b.regodoc")
        _, third = self.run_import(self.archive(bundle()), "c.regodoc")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first.read_bytes(), third.read_bytes())

    def test_language_and_document(self) -> None:
        text = "# Rowing club\n\n## Boats\n\nEight boats.\n"
        outcome, target = self.run_import(
            self.folder(bundle(text, {})), language="en", document_id="doc-7"
        )
        self.assertEqual(outcome.exit_code, 0, outcome.validation.report.items)
        files = self.written(target)
        self.assertIn('language = "en"', files["structure.toml"].decode())
        self.assertIn('"document": "doc-7"', files["manifest.json"].decode())
        self.assertNotIn("parts/opening.xml", files)

    def test_part_ids(self) -> None:
        used = {"opening"}
        cases = [
            ("Rete e collegamenti", "rete-e-collegamenti"),
            ("Rete e collegamenti", "rete-e-collegamenti-2"),
            ("Perché è così?", "perche-e-cosi"),
            ("2026: il piano", "parte-2026-il-piano"),
            ("Opening", "opening-2"),
            ("???", "parte-6"),
            ("Con", "con-2"),
            ("x" * 80, "x" * 48),
            ("Attivita'", "attivita"),
            ("Attività", "attivita-2"),
            ("ATTIVITÀ", "attivita-3"),
            ("  --Prima---e  dopo--  ", "prima-e-dopo"),
            ("Straße", "stra-e"),
        ]
        for number, (title, expected) in enumerate(cases, 1):
            with self.subTest(title):
                self.assertEqual(importer.part_id(title, used, number), expected)

    def test_accents_go_round(self) -> None:
        text = "# T\n\n" + "".join(f"## Parte {n}\n\nTesto.\n\n" for n in range(1, 10))
        _, target = self.run_import(self.folder(bundle(text, {})))
        structure = self.written(target)["structure.toml"].decode()
        accents = [
            line.split('"')[1] for line in structure.splitlines() if line.startswith("accent")
        ]
        self.assertEqual(accents[0], "azure")
        self.assertEqual(accents[8], "azure")
        self.assertEqual(len(set(accents)), 8)


class ImagesAndTextTest(Workspace):
    def test_entities_stay_literal_in_the_package(self) -> None:
        text = "# T\n\n## P\n\nPrima &amp; dopo, &#60; e un & nudo.\n"
        outcome, target = self.run_import(self.folder(bundle(text, {})))
        self.assertEqual(outcome.exit_code, 0, outcome.validation.report.items)
        part = self.written(target)["parts/p.xml"].decode()
        self.assertIn("<p>Prima &amp;amp; dopo, &amp;#60; e un &amp; nudo.</p>", part)

    def test_images_are_checked_and_cleaned_as_in_canon(self) -> None:
        exif = b"\xff\xe1" + struct.pack(">H", 8 + len(SIGNATURE)) + b"Exif\x00\x00" + SIGNATURE
        photo = jpeg()
        dirty = photo[:20] + exif + photo[20:]
        text = "# T\n\n## P\n\n![Foto](images/foto.jpg)\n"
        outcome, target = self.run_import(self.folder(bundle(text, {"images/foto.jpg": dirty})))
        self.assertEqual(outcome.exit_code, 0, outcome.validation.report.items)
        self.assertEqual(
            [(d.code, d.file) for d in outcome.validation.report.items],
            [("regodoc.image.stripped", "images/foto.jpg")],
        )
        files = self.written(target)
        self.assertEqual(files["images/foto.jpg"], photo)
        self.assertNotIn(SIGNATURE, target.read_bytes())
        # canon sull'uscita dà gli stessi byte: import e canon scrivono lo stesso pacchetto.
        again = self.root / "again.regodoc"
        outcome = importer.canon.run(
            target, str(again), document=None, base_version=None, files_dir=None, strict=False
        )
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(again.read_bytes(), target.read_bytes())
        # Con --strict l'avviso dei metadati tolti è un rifiuto, come in canon.
        outcome, strict_target = self.run_import(
            self.folder(bundle(text, {"images/foto.jpg": dirty}), "in-strict"),
            "s.regodoc",
            strict=True,
        )
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(strict_target.exists())

    def test_a_broken_image_is_refused_as_in_canon(self) -> None:
        text = "# T\n\n## P\n\n![Foto](images/foto.png)\n"
        found = self.problems(bundle(text, {"images/foto.png": b"\x89PNG\r\n\x1a\nrotto"}))
        self.assertEqual(found, [("regodoc.image.structure", "images/foto.png", 0)])


class ExampleTest(Workspace):
    def test_the_markdown_example_converts_without_warnings(self) -> None:
        outcome, target = self.run_import(EXAMPLES / "markdown")
        self.assertEqual(outcome.exit_code, 0, outcome.validation.report.items)
        self.assertEqual(outcome.validation.report.items, [])
        files = self.written(target)
        self.assertEqual(
            [path for path in files if path.startswith("parts/")],
            ["parts/opening.xml", "parts/rete-e-collegamenti.xml", "parts/copie-di-sicurezza.xml"],
        )


class RefusalTest(Workspace):
    def test_markdown_problems_point_at_the_markdown(self) -> None:
        text = "# T\n\n## P\n\nUn <b>tag</b>.\n\n![x](images/assente.png)\n"
        self.assertEqual(
            self.problems(bundle(text, {})),
            [
                ("regodoc.markdown.html", "document.md", 5),
                ("regodoc.markdown.image", "document.md", 7),
            ],
        )

    def test_package_problems_come_back_to_the_markdown_line(self) -> None:
        text = (
            "# T\n\n## P\n\nUn paragrafo giusto.\n\n"
            'Una virgoletta "aperta e mai chiusa.\n\n'
            "```\n" + "x" * 300 + "\n```\n\n## " + "y" * 210 + "\n\nTesto.\n"
        )
        found = self.problems(bundle(text, {}))
        self.assertIn(("regodoc.text.quotes", "document.md", 7), found)
        self.assertIn(("regodoc.limit.listing_line", "document.md", 10), found)
        self.assertIn(("regodoc.text.plain", "document.md", 13), found)

    def test_bundle_layout(self) -> None:
        self.assertEqual(
            self.problems({"images/coverage.png": PNG}),
            [("regodoc.package.missing", "document.md", 0)],
        )
        extra = bundle()
        extra["structure.toml"] = b"x"
        self.assertEqual([code for code, _, _ in self.problems(extra)], ["regodoc.archive.layout"])
        extra = bundle()
        extra["images/note.txt"] = b"x"
        self.assertEqual([code for code, _, _ in self.problems(extra)], ["regodoc.archive.layout"])

    def test_hostile_archive(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("document.md", "# T\n\n## P\n\nx\n")
            archive.writestr("../evil.md", "x")
        target = self.root / "evil.zip"
        target.write_bytes(buffer.getvalue())
        outcome, out = self.run_import(target)
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(out.exists())
        self.assertEqual(
            [d.code for d in outcome.validation.report.errors], ["regodoc.archive.path"]
        )

    def test_unused_image_is_a_warning_and_strict_refuses(self) -> None:
        files = bundle("# T\n\n## P\n\nTesto.\n")
        outcome, _ = self.run_import(self.folder(files))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(
            [(d.code, d.file) for d in outcome.validation.report.items],
            [("regodoc.image.unused", "images/coverage.png")],
        )
        outcome, target = self.run_import(self.folder(files, "in2"), "s.regodoc", strict=True)
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(target.exists())


class HostileImportTest(Workspace):
    def test_random_mutations_through_the_whole_import(self) -> None:
        # Ogni esito è un pacchetto valido o un rifiuto con il rapporto: mai un'eccezione, mai
        # un'uscita scritta con errori.
        source = (EXAMPLES / "markdown" / "document.md").read_bytes()
        alphabet = b"#*_`[]()!<>|-:\\ \n1.~&;^"
        generator = random.Random(20261127)  # noqa: S311 - prove ripetibili
        written = refused = 0
        for round_number in range(300):
            data = bytearray(source)
            for _ in range(generator.randint(1, 6)):
                position = generator.randrange(len(data))
                action = generator.randrange(3)
                if action == 0:
                    data[position] = generator.choice(alphabet)
                elif action == 1:
                    data.insert(position, generator.choice(alphabet))
                else:
                    del data[position]
            files = {"document.md": bytes(data), "images/coverage.png": PNG}
            target = self.root / f"out-{round_number}.regodoc"
            outcome, _ = self.run_import(self.archive(files, f"in-{round_number}.zip"), target.name)
            if outcome.exit_code == 0:
                written += 1
                self.assertEqual(validate_bytes(target.read_bytes()).report.errors, [])
            else:
                refused += 1
                self.assertEqual(outcome.exit_code, 1)
                self.assertFalse(target.exists())
                self.assertTrue(outcome.validation.report.errors)
        self.assertGreater(written, 0)
        self.assertGreater(refused, 0)

    def test_symlink_in_the_input_folder(self) -> None:
        root = self.folder(bundle())
        (root / "images" / "altro.png").symlink_to(root / "images" / "coverage.png")
        outcome, target = self.run_import(root)
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(target.exists())
        self.assertEqual(
            [d.code for d in outcome.validation.report.errors], ["regodoc.archive.special_file"]
        )

    def test_compression_bomb(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("document.md", b"# T\n\n## P\n\n" + b"a" * (8 * 1024 * 1024))
        target = self.root / "bomb.zip"
        target.write_bytes(buffer.getvalue())
        outcome, out = self.run_import(target)
        self.assertEqual(outcome.exit_code, 1)
        self.assertFalse(out.exists())
        self.assertEqual(
            [d.code for d in outcome.validation.report.errors], ["regodoc.archive.ratio"]
        )


class CommandTest(Workspace):
    def command(self, *argv: object) -> tuple[int, dict[str, object]]:
        code, out, _ = run_cli("--contract", "1", "import", *(str(a) for a in argv), "--json")
        return code, json.loads(out)

    def test_written_and_reported(self) -> None:
        target = self.root / "out.regodoc"
        code, report = self.command("--from", "markdown", self.folder(bundle()), "-o", target)
        self.assertEqual(code, 0, report["errors"])
        self.assertEqual(
            (report["command"], report["grammar"], report["input"]), ("import", "rego/2", None)
        )
        self.assertEqual(
            report["files_sha256"], validate_bytes(target.read_bytes()).summary()["files_sha256"]
        )

    def test_refused_with_the_markdown_line(self) -> None:
        target = self.root / "out.regodoc"
        source = self.folder(bundle("# T\n\n## P\n\n[x](https://example.com)\n", {}))
        code, report = self.command("--from", "markdown", source, "-o", target)
        self.assertEqual(code, 1)
        self.assertFalse(target.exists())
        error = report["errors"][0]  # type: ignore[index]
        self.assertEqual(
            (error["code"], error["file"], error["line"], error["column"]),  # type: ignore[index]
            ("regodoc.markdown.link", "document.md", 5, 1),
        )

    def test_a_deep_list_is_refused_not_an_internal_error(self) -> None:
        # Il caso della rilettura di L19: 1.200 livelli finivano in RecursionError, codice 4.
        body = "".join(" " * (2 * level) + "- x\n" for level in range(1_200))
        source = self.folder(bundle("# T\n\n## P\n\n" + body, {}))
        code, report = self.command("--from", "markdown", source, "-o", self.root / "o.regodoc")
        self.assertEqual(code, 1)
        found = [(e["code"], e["line"]) for e in report["errors"]]  # type: ignore[index, union-attr]
        self.assertEqual(found, [("regodoc.markdown.syntax", 8)])

    def test_usage(self) -> None:
        source = self.folder(bundle())
        for argv in (
            (source, "-o", self.root / "o.regodoc"),
            ("--from", "html", source, "-o", self.root / "o.regodoc"),
            ("--from", "markdown", self.root / "assente", "-o", self.root / "o.regodoc"),
            ("--from", "markdown", source, "-o", self.root / "o.regodoc", "--document", "../x"),
            ("--from", "markdown", source, "-o", self.root / "o.regodoc", "--language", "fr"),
        ):
            with self.subTest(argv):
                code, report = self.command(*argv)
                self.assertEqual(code, 2)
                self.assertEqual(report["exit_code"], 2)

    def test_declared(self) -> None:
        info = declaration.describe()
        self.assertEqual(info["commands"]["import"], "ready")  # type: ignore[index]
        self.assertEqual(info["imports"], {"markdown": ["md/1"]})
        self.assertIn("import.markdown", info["capabilities"])  # type: ignore[operator]


if __name__ == "__main__":
    unittest.main()
