"""La catena delle grammatiche e il comando ``upgrade`` (specifica, §10; contratto, §8).

Le prove usano una grammatica fittizia, «rego/0-test», che esiste solo qui: il registro del
motore non la contiene e le prove ve la aggiungono per la loro durata. Differisce da rego/1
in tre punti, uno per tipo di cambiamento, e il suo aggiornatore conserva le righe:

- XML, un elemento: ``<para>`` al posto di ``<p>``;
- XML, un valore chiuso: ``<list type="dots">`` al posto di ``type="bullet"``;
- TOML, una chiave: ``lang`` al posto di ``language`` in ``structure.toml``.
"""

import contextlib
import json
import re
import shutil
import tempfile
import unittest
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from unittest import mock

from regodoc import declaration, grammars
from regodoc.cli import ExitCode
from tests.support import LONG_EXAMPLE, build_zip, example_files, run_cli

TEST_GRAMMAR = "rego/0-test"


def upgrade_test_grammar(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Il passo da «rego/0-test» a rego/1."""
    result = {}
    for path, data in files.items():
        if path.endswith(".xml"):
            data = re.sub(rb"<(/?)para\b", rb"<\1p", data)  # noqa: PLW2901
            data = data.replace(b'<list type="dots"', b'<list type="bullet"')  # noqa: PLW2901
        elif path == "structure.toml":
            data = re.sub(rb"(?m)^lang(\s*=)", rb"language\1", data)  # noqa: PLW2901
        result[path] = data
    return result


def test_step() -> grammars.Step:
    return grammars.Step(TEST_GRAMMAR, declaration.GRAMMAR_CURRENT, upgrade_test_grammar)


@contextlib.contextmanager
def test_grammar() -> Iterator[None]:
    with mock.patch.dict(grammars.STEPS, {TEST_GRAMMAR: test_step()}):
        yield


def current_files() -> dict[str, bytes]:
    return example_files(LONG_EXAMPLE)


def old_files() -> dict[str, bytes]:
    """Lo stesso documento nella grammatica di prova, scritto fuori dalla forma canonica:
    rientri di quattro spazi e una chiave TOML con gli spazi allargati."""
    files = {}
    for path, data in current_files().items():
        if path.endswith(".xml"):
            data = re.sub(rb"<(/?)p>", rb"<\1para>", data)  # noqa: PLW2901
            data = data.replace(b'<list type="bullet"', b'<list type="dots"')  # noqa: PLW2901
            data = re.sub(rb"(?m)^( +)", lambda m: m.group(1) * 2, data)  # noqa: PLW2901
        elif path == "structure.toml":
            data = re.sub(rb"(?m)^language =", b"lang   =", data)  # noqa: PLW2901
        elif path == "manifest.json":
            data = json.dumps(  # noqa: PLW2901
                {"format": "regodoc", "grammar": TEST_GRAMMAR, "document": "doc-9"}
            ).encode("utf-8")
        files[path] = data
    return files


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def archive(self, files: dict[str, bytes], name: str = "in.regodoc") -> Path:
        path = self.folder / name
        path.write_bytes(build_zip(files))
        return path

    def command(self, *argv: object) -> tuple[int, dict[str, object]]:
        code, out, _ = run_cli(*(str(a) for a in argv), "--json")
        return code, json.loads(out)


class RegistryTest(unittest.TestCase):
    def test_test_grammar_never_reaches_the_engine(self) -> None:
        self.assertEqual(grammars.STEPS, {})
        self.assertEqual(grammars.readable(), declaration.GRAMMARS_READ)
        read = declaration.describe()["grammars"]["read"]  # type: ignore[index]
        self.assertNotIn(TEST_GRAMMAR, read)

    def test_every_step_reaches_the_current_grammar(self) -> None:
        for steps in ({}, {TEST_GRAMMAR: test_step()}):
            with mock.patch.dict(grammars.STEPS, steps, clear=True):
                for grammar in grammars.readable():
                    with self.subTest(grammar):
                        chain = grammars.chain(grammar)
                        self.assertLessEqual(len(chain), len(grammars.STEPS))
                        self.assertEqual(
                            chain[-1].target if chain else grammar, declaration.GRAMMAR_CURRENT
                        )

    def test_a_broken_chain_is_caught(self) -> None:
        loop = {
            "rego/0-a": grammars.Step("rego/0-a", "rego/0-b", upgrade_test_grammar),
            "rego/0-b": grammars.Step("rego/0-b", "rego/0-a", upgrade_test_grammar),
            "rego/0-c": grammars.Step("rego/0-c", "rego/0-x", upgrade_test_grammar),
        }
        with mock.patch.dict(grammars.STEPS, loop):
            for grammar in ("rego/0-a", "rego/0-c"):
                with self.subTest(grammar), self.assertRaises(ValueError):
                    grammars.chain(grammar)

    def test_the_fixture_differs_where_it_should(self) -> None:
        old, new = old_files(), current_files()
        self.assertIn(b"<para>", old["parts/brief.xml"])
        self.assertIn(b'<list type="dots">', old["parts/members.xml"])
        self.assertTrue(old["structure.toml"].startswith(b"lang   ="))
        with test_grammar():
            upgraded = grammars.upgrade(old, TEST_GRAMMAR)
        for path in new:
            if path.endswith(".xml"):
                # Le righe restano dove sono: cambiano solo i rientri del pacchetto vecchio.
                self.assertEqual(upgraded[path].count(b"\n"), new[path].count(b"\n"), path)
        self.assertEqual(upgraded["manifest.json"], old["manifest.json"])


class UpgradeTest(Workspace):
    def test_old_package_comes_out_current_and_canonical(self) -> None:
        output = self.folder / "out.regodoc"
        with test_grammar():
            code, report = self.command("upgrade", self.archive(old_files()), "-o", output)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        self.assertEqual((report["grammar_in"], report["grammar"]), (TEST_GRAMMAR, "rego/1"))
        self.assertEqual(
            [w["code"] for w in report["warnings"]],  # type: ignore[union-attr, index]
            ["regodoc.grammar.upgraded"],
        )
        expected = current_files()
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            for item in report["files"]:  # type: ignore[union-attr]
                path = item["path"]  # type: ignore[index]
                self.assertEqual(archive.read(path), expected[path], path)
        self.assertEqual(manifest["grammar"], "rego/1")
        self.assertEqual(manifest["document"], "doc-9")
        # L'uscita è già corrente: aggiornarla di nuovo dà gli stessi byte.
        again = self.folder / "again.regodoc"
        code, report = self.command("upgrade", output, "-o", again)
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(report["grammar_in"], "rego/1")
        self.assertEqual(again.read_bytes(), output.read_bytes())

    def test_current_package_gives_the_bytes_of_canon(self) -> None:
        files = current_files()
        files["structure.toml"] = b"# commento\n" + files["structure.toml"]
        package = self.archive(files)
        upgraded, canonical = self.folder / "u.regodoc", self.folder / "c.regodoc"
        self.assertEqual(self.command("upgrade", package, "-o", upgraded)[0], ExitCode.OK)
        self.assertEqual(self.command("canon", package, "-o", canonical)[0], ExitCode.OK)
        self.assertEqual(upgraded.read_bytes(), canonical.read_bytes())

    def test_upgrade_takes_only_archives(self) -> None:
        code, report = self.command("upgrade", LONG_EXAMPLE, "-o", self.folder / "o")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("solo archivi", report["errors"][0]["message"])  # type: ignore[index]

    def test_refused_package_writes_nothing(self) -> None:
        files = old_files()
        files["structure.toml"] = b"[[part]\n"
        output = self.folder / "out.regodoc"
        with test_grammar():
            code, report = self.command("upgrade", self.archive(files), "-o", output)
        self.assertEqual(code, ExitCode.REFUSED)
        self.assertEqual(report["grammar_in"], TEST_GRAMMAR)
        self.assertFalse(output.exists())


class ReadingOldGrammarsTest(Workspace):
    def test_validate_upgrades_in_memory(self) -> None:
        package = self.archive(old_files())
        with test_grammar():
            code, report = self.command("validate", package, "--strict")
        self.assertEqual(code, ExitCode.OK, report["errors"])
        self.assertEqual(report["grammar"], TEST_GRAMMAR)
        warning = report["warnings"][0]  # type: ignore[index]
        self.assertEqual(warning["code"], "regodoc.grammar.upgraded")
        self.assertEqual(warning["severity"], "info")
        self.assertIn("regodoc upgrade", warning["message"])
        # I file del rapporto di validate sono quelli ricevuti.
        received = old_files()["parts/brief.xml"]
        brief = next(f for f in report["files"] if f["path"] == "parts/brief.xml")  # type: ignore[union-attr, index]
        self.assertEqual(brief["bytes"], len(received))

    def test_errors_keep_the_line_and_say_so(self) -> None:
        files = old_files()
        lines = files["parts/brief.xml"].split(b"\n")
        number = next(i for i, line in enumerate(lines) if b"<para>" in line)
        lines[number] = lines[number].replace(b"<para>", b"<para>\x7f", 1)
        files["parts/brief.xml"] = b"\n".join(lines)
        with test_grammar():
            code, report = self.command("validate", self.archive(files))
        self.assertEqual(code, ExitCode.REFUSED)
        error = report["errors"][0]  # type: ignore[index]
        self.assertEqual((error["file"], error["line"]), ("parts/brief.xml", number + 1))
        self.assertTrue(error["message"].endswith(f"(dopo l'aggiornamento da «{TEST_GRAMMAR}»)"))

    def test_canon_refuses_an_old_grammar(self) -> None:
        output = self.folder / "out.regodoc"
        with test_grammar():
            code, report = self.command("canon", self.archive(old_files()), "-o", output)
        self.assertEqual(code, ExitCode.REFUSED)
        self.assertEqual(
            [e["code"] for e in report["errors"]],  # type: ignore[union-attr, index]
            ["regodoc.manifest.grammar_old"],
        )
        self.assertIn("regodoc upgrade", report["errors"][0]["message"])  # type: ignore[index]
        self.assertFalse(output.exists())

    def test_build_reads_old_grammars(self) -> None:
        old, new = self.folder / "old", self.folder / "new"
        with test_grammar():
            code, report = self.command(
                "build", self.archive(old_files()), "-o", old, "--format", "latex"
            )
        self.assertEqual(code, ExitCode.OK, report["errors"])
        code, _ = self.command(
            "build", self.archive(current_files(), "new.regodoc"), "-o", new, "--format", "latex"
        )
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual((old / "document.tex").read_bytes(), (new / "document.tex").read_bytes())

    def test_newer_grammar(self) -> None:
        files = current_files()
        files["manifest.json"] = json.dumps(
            {
                "format": "regodoc",
                "grammar": "rego/2",
                "generator": {"engine": "regodoc", "version": "9.0.0"},
            }
        ).encode("utf-8")
        with test_grammar():
            code, report = self.command("validate", self.archive(files))
        self.assertEqual(code, ExitCode.REFUSED)
        error = report["errors"][0]  # type: ignore[index]
        self.assertEqual(error["code"], "regodoc.manifest.grammar_newer")
        for words in ("rego/2", "regodoc 9.0.0", f"{TEST_GRAMMAR}, rego/1"):
            self.assertIn(words, error["message"])


if __name__ == "__main__":
    unittest.main()
