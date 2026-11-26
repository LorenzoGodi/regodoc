"""La grammatica rego/2 (specifica, §13): immagini senza metadati nella forma canonica,
l'aggiornatore da rego/1 e la forma canonica di rego/1 fissa (contratto, §8)."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from regodoc import declaration, grammars, images
from regodoc.cli import ExitCode
from tests.support import (
    LONG_EXAMPLE,
    METADATA_SIGNATURE,
    build_zip,
    example_files,
    run_cli,
    validate_bytes,
    with_metadata,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "data" / "golden" / "rego1-canon-0.2.0.json"


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def archive(self, files: dict[str, bytes], name: str = "in.regodoc") -> Path:
        path = self.folder / name
        path.write_bytes(build_zip(files))
        return path

    def command(self, *argv: object) -> tuple[int, dict[str, object]]:
        code, out, _ = run_cli("--contract", "1", *(str(a) for a in argv), "--json")
        return code, json.loads(out)

    def written(self, path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}


def codes(report: dict[str, object]) -> list[str]:
    return sorted(w["code"] for w in report["warnings"])  # type: ignore[index, union-attr]


class GrammarTest(unittest.TestCase):
    def test_declared_grammars(self) -> None:
        self.assertEqual(declaration.GRAMMAR_CURRENT, "rego/2")
        self.assertEqual(declaration.GRAMMARS_READ, ("rego/1", "rego/2"))
        self.assertEqual(grammars.readable(), declaration.GRAMMARS_READ)
        self.assertEqual([step.target for step in grammars.chain("rego/1")], ["rego/2"])

    def test_the_step_touches_only_images(self) -> None:
        old = with_metadata(example_files(LONG_EXAMPLE), "rego/1")
        new = grammars.upgrade(old, "rego/1")
        for path, data in old.items():
            with self.subTest(path):
                if path.startswith("images/"):
                    self.assertNotIn(METADATA_SIGNATURE, new[path])
                    self.assertEqual(new[path], images.strip_image(path, data)[0])
                else:
                    self.assertEqual(new[path], data)

    def test_an_image_over_the_size_limit_is_left_to_the_validation(self) -> None:
        big = b"\xff\xd8" + b"\x00" * int(declaration.CONTENT_LIMITS["image_bytes"])
        self.assertEqual(grammars.rego1_to_rego2({"images/a.jpg": big}), {"images/a.jpg": big})


class ValidateTest(unittest.TestCase):
    def test_rego2_metadata_give_the_stripped_warning(self) -> None:
        validation = validate_bytes(build_zip(with_metadata(example_files(LONG_EXAMPLE), "rego/2")))
        warnings = [(d.code, d.file) for d in validation.report.items]
        self.assertEqual(
            warnings,
            [
                ("regodoc.image.stripped", "images/landing-stage.jpg"),
                ("regodoc.image.stripped", "images/shed-plan.png"),
            ],
        )
        messages = [d.message for d in validation.report.items]
        self.assertIn("APP1", messages[0])
        self.assertIn("COM", messages[0])
        self.assertIn("tEXt", messages[1])

    def test_rego1_keeps_its_warnings(self) -> None:
        validation = validate_bytes(build_zip(with_metadata(example_files(LONG_EXAMPLE), "rego/1")))
        self.assertEqual(
            sorted(d.code for d in validation.report.items),
            ["regodoc.grammar.upgraded", "regodoc.image.metadata", "regodoc.image.metadata"],
        )

    def test_clean_examples_have_no_warning(self) -> None:
        validation = validate_bytes(build_zip(example_files(LONG_EXAMPLE)))
        self.assertEqual(validation.report.items, [])


class CanonTest(Workspace):
    def test_rego2_canon_strips_and_is_idempotent(self) -> None:
        dirty = with_metadata(example_files(LONG_EXAMPLE), "rego/2")
        out = self.folder / "out.regodoc"
        code, report = self.command("canon", self.archive(dirty), "-o", out)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        self.assertEqual(report["grammar"], "rego/2")
        files = self.written(out)
        clean = example_files(LONG_EXAMPLE)
        for path in clean:
            if path != "manifest.json":
                with self.subTest(path):
                    self.assertEqual(files[path], clean[path])
        self.assertNotIn(METADATA_SIGNATURE, out.read_bytes())
        again = self.folder / "again.regodoc"
        code, report = self.command("canon", out, "-o", again)
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(codes(report), [])
        self.assertEqual(again.read_bytes(), out.read_bytes())
        # upgrade di un pacchetto già corrente dà gli stessi byte di canon.
        upgraded = self.folder / "upgraded.regodoc"
        code, _ = self.command("upgrade", out, "-o", upgraded)
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(upgraded.read_bytes(), out.read_bytes())

    def test_rego1_canon_writes_what_engine_0_2_0_wrote(self) -> None:
        # Il §8 del contratto: la forma canonica di rego/1 resta quella della 0.2.0, metadati
        # delle immagini compresi. Il golden viene da canon del motore 0.2.0 (794a2a1) sullo
        # stesso pacchetto; cambia solo «generator» del manifesto.
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        dirty = with_metadata(example_files(LONG_EXAMPLE), "rego/1")
        out = self.folder / "out.regodoc"
        code, report = self.command("canon", self.archive(dirty), "-o", out)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        self.assertEqual(report["grammar"], "rego/1")
        files = self.written(out)
        self.assertEqual(list(files), golden["ordine"])
        sums = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
        del sums["manifest.json"]
        self.assertEqual(sums, golden["sha256"])
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest.pop("generator")["version"], "0.3.0.dev0")
        self.assertEqual(manifest, golden["manifesto_senza_generator"])
        self.assertIn(METADATA_SIGNATURE, files["images/landing-stage.jpg"])
        self.assertIn(b"`rego/1`", files["README.md"])

    def test_rego1_upgrade_strips_and_changes_nothing_else(self) -> None:
        dirty = with_metadata(example_files(LONG_EXAMPLE), "rego/1")
        out = self.folder / "out.regodoc"
        code, report = self.command("upgrade", self.archive(dirty), "-o", out)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        self.assertEqual((report["grammar_in"], report["grammar"]), ("rego/1", "rego/2"))
        files = self.written(out)
        self.assertEqual(json.loads(files["manifest.json"])["grammar"], "rego/2")
        clean = example_files(LONG_EXAMPLE)
        for path in clean:
            if path != "manifest.json":
                with self.subTest(path):
                    self.assertEqual(files[path], clean[path])
        self.assertNotIn(METADATA_SIGNATURE, out.read_bytes())

    def test_two_runs_give_the_same_bytes(self) -> None:
        dirty = self.archive(with_metadata(example_files(LONG_EXAMPLE), "rego/1"))
        outputs = []
        for name in ("a.regodoc", "b.regodoc"):
            out = self.folder / name
            code, _ = self.command("upgrade", dirty, "-o", out)
            self.assertEqual(code, ExitCode.OK)
            outputs.append(out.read_bytes())
        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
