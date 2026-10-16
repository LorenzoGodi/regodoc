"""Prove dei pacchetti e delle chiamate ostili di una revisione di sicurezza del lettore.

Ogni prova riproduce un caso trovato eseguendo il motore come processo separato: con il
codice di prima falliva, e il motore ne usciva con un errore interno, con un rapporto
sbagliato o con troppa memoria.
"""

import errno
import gc
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
import weakref
import xml.parsers.expat
import zlib
from pathlib import Path
from unittest import mock

from regodoc import declaration, parts
from regodoc.diagnostics import Collector, Diagnostic, Severity
from regodoc.tomlfiles import MAX_KEY_SEGMENTS, long_dotted_key
from tests.support import (
    build_zip,
    example_files,
    png_pixels,
    run_cli,
    validate_bytes,
    validate_files,
)
from tests.test_limits import part, structure_with_parts

ROOT = Path(__file__).resolve().parent.parent
_ENTRY = (
    "import sys; sys.path.insert(0, sys.argv[1]); from regodoc.cli import main; "
    "sys.exit(main(sys.argv[2:]))"
)


def codes(files: dict[str, bytes]) -> list[str]:
    return [d.code for d in validate_bytes(build_zip(files)).report.errors]


def with_file(name: str, data: bytes) -> dict[str, bytes]:
    return {**example_files(), name: data}


class TomlTest(unittest.TestCase):
    def test_huge_decimal_integer_in_the_structure(self) -> None:
        files = example_files()
        files["structure.toml"] = files["structure.toml"].replace(
            b"toc = true", b"toc = " + b"9" * 5000
        )
        validation = validate_bytes(build_zip(files))
        errors = validation.report.errors
        self.assertEqual([d.code for d in errors], ["regodoc.toml.syntax"])
        self.assertEqual((errors[0].file, errors[0].line), ("structure.toml", 2))

    def test_huge_hexadecimal_integer_in_the_variables(self) -> None:
        files = example_files()
        files["variables.toml"] += b"huge = { eur = 0x" + b"f" * 20000 + b" }\n"
        errors = validate_bytes(build_zip(files)).report.errors
        self.assertEqual([d.code for d in errors], ["regodoc.toml.value"])
        self.assertLess(len(errors[0].message), 200)

    def test_long_dotted_key_is_refused_quickly(self) -> None:
        files = example_files()
        # 40 KB: con Python 3.12 tomllib ci metteva 12 s e 1,5 GiB; con 3.13 si ferma per
        # ricorsione. Il motore ora rifiuta la chiave prima di tomllib, con ogni versione.
        files["variables.toml"] += b"x" + b".a" * 20_000 + b" = 1\n"
        start = time.perf_counter()
        errors = validate_bytes(build_zip(files)).report.errors
        self.assertLess(time.perf_counter() - start, 2)
        self.assertEqual([d.code for d in errors], ["regodoc.toml.depth"])

    def test_dotted_keys_up_to_the_limit_and_in_strings_are_fine(self) -> None:
        self.assertIsNone(long_dotted_key(".".join("a" * MAX_KEY_SEGMENTS) + " = 1\n"))
        self.assertEqual(long_dotted_key(".".join("a" * (MAX_KEY_SEGMENTS + 1)) + " = 1\n"), 0)
        self.assertIsNone(long_dotted_key('x = "a.b.c.d.e.f.g.h.i.j"\n# a.b.c.d.e.f.g.h.i.j\n'))
        self.assertEqual(long_dotted_key('"a"."b"."c"."d"."e"."f"."g"."h"."i" = 1\n'), 0)


class ManifestTest(unittest.TestCase):
    def test_surrogate_in_a_manifest_key(self) -> None:
        manifest = b'{"format": "regodoc", "grammar": "rego/1", "\\ud800": 1}'
        files = with_file("manifest.json", manifest)
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "p.regodoc"
            package.write_bytes(build_zip(files))
            code, out, err = run_cli("validate", str(package), "--json")
        self.assertEqual(code, 1, err)
        report = json.loads(out)
        self.assertEqual([e["code"] for e in report["errors"]], ["regodoc.manifest.unknown_key"])
        self.assertIn("U+D800", report["errors"][0]["message"])


class XmlTest(unittest.TestCase):
    def test_utf16_part_is_refused(self) -> None:
        text = '<part><section id="s"><title>T</title><p>x</p></section></part>'
        for encoding in ("utf-16-le", "utf-16-be"):
            with self.subTest(encoding):
                found = codes(with_file("parts/backup.xml", text.encode(encoding)))
                self.assertIn("regodoc.text.encoding", found)

    def test_undefined_entity_is_an_entity_error(self) -> None:
        found = validate_files(with_file("parts/backup.xml", b"<part>&nbsp;</part>"))
        self.assertEqual([d.code for d in found.report.errors], ["regodoc.xml.entity"])

    def test_parts_do_not_accumulate_in_memory(self) -> None:
        # Un pezzo di testo per ogni a capo, tenuto in vita dal ciclo fra parser e gestori,
        # portava un pacchetto valido oltre 1 GiB. Ora i pezzi contigui sono uno solo.
        line_count = 20_000
        data = (
            "<part><section><title>T</title><p>x" + "a\n" * line_count + "</p></section></part>"
        ).encode()
        root = parts.parse_part(data, "parts/x.xml", Collector())
        assert root is not None
        paragraph = root.elements()[0].elements()[1]
        self.assertEqual(len(paragraph.children), 1)
        self.assertEqual(len(paragraph.children[0].chunks), 1)  # type: ignore[union-attr]
        # Senza il raccoglitore ciclico l'albero si libera appena non serve più.
        gc.disable()
        try:
            root = parts.parse_part(data, "parts/x.xml", Collector())
            reference = weakref.ref(root)  # type: ignore[arg-type]
            del root
            self.assertIsNone(reference())
        finally:
            gc.enable()

    def test_many_parts_of_newlines_stay_small(self) -> None:
        files = structure_with_parts(8)
        budget = int(declaration.CONTENT_LIMITS["part_bytes"]) - 200
        # Un carattere a caso ogni 32 a capo: abbastanza per stare sotto il rapporto di
        # compressione dell'involucro, poco per il limite dei caratteri.
        generator = random.Random(5)  # noqa: S311 - prova ripetibile
        body = (
            "<p>x"
            + "".join(
                "\n" * 31 + generator.choice("abcdefghilmnopqrstuv") for _ in range(budget // 32)
            )
            + "</p>"
        )
        for number in range(5):
            files[f"parts/extra{number}.xml"] = part(
                f'<section id="x{number}"><title>T</title>{body}</section>'
            )
        tracemalloc.start()
        try:
            validation = validate_bytes(build_zip(files))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual([d.code for d in validation.report.errors], [])
        self.assertLess(peak, 64 * 1024 * 1024)

    def test_positions_survive_the_merged_text(self) -> None:
        # Il carattere vietato viene dopo due a capo e un riferimento a carattere: i pezzi di
        # testo uniti devono ancora dare la sua posizione esatta.
        data = (
            "<part><section><title>T</title><p>a\nb &amp; c\n x\u202e</p></section></part>".encode()
        )
        found = validate_files(with_file("parts/backup.xml", data)).report.errors
        self.assertEqual([(d.code, d.line, d.column) for d in found], [("regodoc.text.char", 3, 3)])


class ImageTest(unittest.TestCase):
    def check(self, image: bytes) -> list[str]:
        files = with_file("images/coverage.png", image)
        return [
            d.code for d in validate_bytes(build_zip(files, ("images/coverage.png",))).report.errors
        ]

    def test_valid_images_pass(self) -> None:
        for kwargs in (
            {},
            {"color": 6, "depth": 16},
            {"color": 3, "depth": 4},
            {"interlace": 1},
            {"color": 2, "interlace": 1},
        ):
            with self.subTest(kwargs):
                self.assertEqual(self.check(png_pixels(37, 23, **kwargs)), [])  # type: ignore[arg-type]

    def test_pixels_beyond_the_header_are_refused(self) -> None:
        # Un PNG piccolo che si espande molto più di quanto l'intestazione dichiari.
        image = png_pixels(10, 10, raw=bytes(50_000_000))
        self.assertLess(len(image), 100_000)
        self.assertEqual(self.check(image), ["regodoc.image.structure"])

    def test_too_few_pixels_and_broken_streams(self) -> None:
        self.assertEqual(self.check(png_pixels(10, 10, raw=bytes(10))), ["regodoc.image.structure"])
        complete = zlib.compress(bytes(110))
        for stream in (b"not zlib at all", complete[:-6], zlib.compress(bytes(109))):
            with self.subTest(stream):
                image = png_pixels(10, 10, stream=stream)
                self.assertEqual(self.check(image), ["regodoc.image.structure"])

    def test_palette_without_plte(self) -> None:
        self.assertEqual(
            self.check(png_pixels(4, 4, color=3, palette=False)), ["regodoc.image.structure"]
        )


class CommandTest(unittest.TestCase):
    def run_engine(
        self, *args: str, close: int | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        command = [sys.executable, "-I", "-B", "-c", _ENTRY, str(ROOT / "src"), *args]
        if close is not None:
            # Chiude il descrittore nel processo figlio prima di avviare l'interprete.
            command = ["/bin/sh", "-c", f'exec "$@" {close}>&-', "sh", *command]
        return subprocess.run(
            command, capture_output=True, check=False, timeout=60, stdin=subprocess.DEVNULL
        )

    def test_closed_stderr(self) -> None:
        result = self.run_engine("validate", "/nonexistent/p.regodoc", "--json", close=2)
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)  # un solo oggetto JSON
        self.assertEqual(report["exit_code"], 2)

    def test_closed_stdout(self) -> None:
        result = self.run_engine("info", close=1)
        self.assertEqual(result.returncode, 3)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_paths_of_the_caller_stay_out_of_the_report(self) -> None:
        code, out, _ = run_cli("validate", "/very/secret/folder/p.regodoc", "--json")
        self.assertEqual(code, 2)
        self.assertNotIn("secret", out)
        self.assertIn("«p.regodoc»", out)

    def test_non_utf8_names(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = os.fsdecode(Path(folder).as_posix().encode() + b"/none\xff.regodoc")
            result = self.run_engine("validate", missing, "--json")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["exit_code"], 2)
            directory = Path(os.fsdecode(Path(folder).as_posix().encode() + b"/pkg\xff"))
            try:
                directory.mkdir()
            except OSError:
                # APFS di macOS rifiuta i nomi non UTF-8: lì il caso non può presentarsi.
                return
            for name, data in example_files().items():
                target = directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            result = self.run_engine("validate", str(directory), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_messages_cannot_carry_control_characters(self) -> None:
        diagnostic = Diagnostic(Severity.ERROR, "regodoc.x", "a\u202eb\x1b[31m\ud800", "f\u2066")
        self.assertEqual(diagnostic.message, "aU+202EbU+001B[31mU+D800")
        self.assertEqual(diagnostic.file, "fU+2066")

    def test_the_file_is_read_once(self) -> None:
        opened: list[str] = []
        original = Path.open

        def counting(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            if self.name == "p.regodoc":
                opened.append(str(self))
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "p.regodoc"
            package.write_bytes(build_zip(example_files()))
            with mock.patch.object(Path, "open", counting):
                code, _, _ = run_cli("validate", str(package))
        self.assertEqual(code, 0)
        self.assertEqual(len(opened), 1)

    def test_info_declares_expat(self) -> None:
        self.assertEqual(
            declaration.describe()["expat"],
            ".".join(str(n) for n in xml.parsers.expat.version_info),
        )


class ResidualTest(unittest.TestCase):
    """I punti rimasti scoperti dopo la prima correzione."""

    def test_python_messages_never_reach_the_report(self) -> None:
        cases = {
            b'{"format": "regodoc", "grammar": "rego/1", "x": '
            + b"9" * 5000
            + b"}": "troppe cifre",
            b'{"format": "regodoc", "x": ' + b"[" * 30_000 + b"]" * 30_000 + b"}": "annidamento",
        }
        for manifest, words in cases.items():
            with self.subTest(words):
                errors = validate_bytes(
                    build_zip(with_file("manifest.json", manifest))
                ).report.errors
                self.assertEqual([d.code for d in errors], ["regodoc.manifest.syntax"])
                self.assertIn(words, errors[0].message)
                for english in ("Exceeds", "recursion", "limit", "digits"):
                    self.assertNotIn(english, errors[0].message)

    def test_system_errors_are_in_italian(self) -> None:
        failure = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch("regodoc.cli.validate_package", side_effect=failure):
            code, out, _ = run_cli("validate", str(ROOT / "examples" / "colle-rovere"), "--json")
        self.assertEqual(code, 3)
        message = json.loads(out)["errors"][0]["message"]
        self.assertIn("spazio su disco esaurito", message)
        self.assertNotIn("No space", message)

    def test_grey_images_cannot_carry_a_palette(self) -> None:
        def with_palette(image: bytes) -> bytes:
            body = bytes(3)
            crc = zlib.crc32(b"PLTE" + body) & 0xFFFFFFFF
            chunk = len(body).to_bytes(4, "big") + b"PLTE" + body + crc.to_bytes(4, "big")
            return image[:33] + chunk + image[33:]  # subito dopo IHDR

        for color in (0, 4):
            with self.subTest(color):
                image = with_palette(png_pixels(4, 4, color=color))
                files = with_file("images/coverage.png", image)
                errors = [d.code for d in validate_bytes(build_zip(files)).report.errors]
                self.assertEqual(errors, ["regodoc.image.structure"])
        # Nelle immagini a colori la tavolozza è un suggerimento ammesso.
        image = with_palette(png_pixels(4, 4, color=2))
        self.assertEqual(codes(with_file("images/coverage.png", image)), [])

    def test_many_variables_are_read_in_linear_time(self) -> None:
        files = example_files()
        lines = "".join(f'v{n:04d} = {{ text = "{"a" * 200}" }}\n' for n in range(1490))
        files["variables.toml"] += lines.encode()
        start = time.perf_counter()
        validation = validate_bytes(build_zip(files))
        self.assertLess(time.perf_counter() - start, 3)
        unused = [d for d in validation.report.warnings if d.code == "regodoc.toml.unused_variable"]
        first = (
            files["variables.toml"].split(b"\n").index(b'v0000 = { text = "' + b"a" * 200 + b'" }')
        )
        self.assertEqual(unused[0].line, first + 1)

    def test_memory_error_at_the_entry_point(self) -> None:
        with mock.patch("regodoc.cli.build_parser", side_effect=MemoryError):
            code, out, err = run_cli("validate", "x", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["errors"][0]["code"], "regodoc.limit.memory")
        self.assertNotIn("Traceback", err)
        # Nemmeno la memoria per il rapporto: una riga fissa su stderr e il codice 3.
        with (
            mock.patch("regodoc.cli.build_parser", side_effect=MemoryError),
            mock.patch("regodoc.cli._write_json", side_effect=MemoryError),
            mock.patch("regodoc.cli._note", side_effect=MemoryError),
            mock.patch("os.write") as raw,
        ):
            code, _, _ = run_cli("validate", "x", "--json")
        self.assertEqual(code, 3)
        raw.assert_called_once_with(2, b"regodoc: memoria esaurita\n")

    def test_expat_is_at_least_the_declared_minimum(self) -> None:
        self.assertGreaterEqual(xml.parsers.expat.version_info, declaration.EXPAT_MIN)
        self.assertEqual(declaration.describe()["expat_min"], "2.6.0")


if __name__ == "__main__":
    unittest.main()
