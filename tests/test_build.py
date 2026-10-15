"""Prove di ``build`` che non chiedono TeX: uscita LaTeX, intestazione, data, tema, uscite.

Le prove che compilano davvero, compresi i divieti per i temi esterni, sono in
``test_tex_build``.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from regodoc import declaration
from regodoc.diagnostics import Collector
from regodoc.theme import NEUTRAL_DIR, read_theme
from tests.support import EXAMPLE, build_zip, example_files, run_cli

GOLDEN = Path(__file__).resolve().parent / "data" / "golden"
SOURCE = Path(__file__).resolve().parent.parent / "src" / "regodoc" / "tex"


class Workspace:
    """Una cartella temporanea con il pacchetto d'esempio in archivio."""

    def __init__(self, test: unittest.TestCase, files: dict[str, bytes] | None = None) -> None:
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.package = self.root / "p.regodoc"
        self.package.write_bytes(build_zip(files if files is not None else example_files()))

    def theme(self, name: str = "brand") -> Path:
        """Una copia del tema neutro, da modificare nella prova."""
        target = self.root / name
        shutil.copytree(NEUTRAL_DIR, target)
        return target

    def header(self, value: object) -> Path:
        path = self.root / "header.json"
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path


def build(*argv: object) -> tuple[int, dict[str, object]]:
    code, out, _ = run_cli("build", *(str(a) for a in argv), "--format", "latex", "--json")
    return code, json.loads(out)


def error_codes(report: dict[str, object]) -> list[str]:
    return [e["code"] for e in report["errors"]]  # type: ignore[index, union-attr]


class LatexOutputTest(unittest.TestCase):
    def test_the_latex_folder(self) -> None:
        space = Workspace(self)
        output = space.root / "out"
        code, report = build(space.package, "-o", output)
        self.assertEqual(code, 0, report["errors"])
        paths = [item["path"] for item in report["outputs"]]  # type: ignore[union-attr, index]
        self.assertEqual(
            paths,
            [
                f"{output}/document.tex",
                f"{output}/images/coverage.png",
                f"{output}/regodoc.sty",
                f"{output}/theme.sty",
                f"{output}/theme.toml",
            ],
        )
        document = (output / "document.tex").read_text(encoding="utf-8")
        self.assertEqual(document, (GOLDEN / "colle-rovere.tex").read_text(encoding="utf-8"))
        self.assertEqual(
            (output / "regodoc.sty").read_bytes(), (SOURCE / "regodoc.sty").read_bytes()
        )
        self.assertEqual(report["passes"], 0)
        self.assertIsNone(report["tex"])
        self.assertEqual(report["theme"]["name"], "neutral")  # type: ignore[index]
        self.assertEqual(
            report["package_header"]["title"], "Rinnovo della rete della Cantina Colle Rovere"
        )  # type: ignore[index]

    def test_report_keys(self) -> None:
        space = Workspace(self)
        _, report = build(space.package, "-o", space.root / "out")
        for key in ("input", "grammar", "package_header", "outputs", "passes", "theme", "tex"):
            self.assertIn(key, report)
        self.assertNotIn("files", report)

    def test_an_invalid_package_writes_nothing(self) -> None:
        files = example_files()
        files["parts/backup.xml"] = b"<part><bad/></part>"
        space = Workspace(self, files)
        code, report = build(space.package, "-o", space.root / "out")
        self.assertEqual(code, 1)
        self.assertEqual(report["outputs"], [])
        self.assertFalse((space.root / "out").exists())

    def test_strict_counts_warnings(self) -> None:
        files = example_files()
        files["variables.toml"] += b"spare = { number = 1 }\n"
        space = Workspace(self, files)
        code, _ = build(space.package, "-o", space.root / "out")
        self.assertEqual(code, 0)
        code, _ = build(space.package, "-o", space.root / "out2", "--strict")
        self.assertEqual(code, 1)
        self.assertFalse((space.root / "out2").exists())

    def test_a_folder_is_not_accepted(self) -> None:
        code, report = build(EXAMPLE, "-o", tempfile.gettempdir() + "/regodoc-never")
        self.assertEqual(code, 2)
        self.assertIn("solo archivi", report["errors"][0]["message"])  # type: ignore[index]


class OutputRulesTest(unittest.TestCase):
    def test_missing_parent(self) -> None:
        space = Workspace(self)
        code, report = build(space.package, "-o", space.root / "no" / "out")
        self.assertEqual(code, 2)
        self.assertEqual(error_codes(report), ["regodoc.usage"])

    def test_output_cannot_be_the_input(self) -> None:
        space = Workspace(self)
        code, _, _ = run_cli("build", str(space.package), "-o", str(space.package))
        self.assertEqual(code, 2)
        self.assertTrue(space.package.is_file())

    def test_an_existing_folder_is_replaced_whole(self) -> None:
        space = Workspace(self)
        output = space.root / "out"
        (output / "old").mkdir(parents=True)
        (output / "old" / "stale.txt").write_text("x")
        code, _ = build(space.package, "-o", output)
        self.assertEqual(code, 0)
        self.assertFalse((output / "old").exists())
        self.assertTrue((output / "document.tex").is_file())
        self.assertEqual([p.name for p in space.root.iterdir() if p.name.startswith(".")], [])

    def test_a_symlink_is_replaced_not_followed(self) -> None:
        space = Workspace(self)
        elsewhere = space.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("x")
        link = space.root / "out"
        link.symlink_to(elsewhere)
        code, _ = build(space.package, "-o", link)
        self.assertEqual(code, 0)
        self.assertFalse(link.is_symlink())
        self.assertEqual(sorted(p.name for p in elsewhere.iterdir()), ["keep.txt"])

    def test_pdf_output_cannot_be_a_folder(self) -> None:
        space = Workspace(self)
        folder = space.root / "folder"
        folder.mkdir()
        code, _, err = run_cli("build", str(space.package), "-o", str(folder))
        self.assertEqual(code, 2)
        self.assertIn("è una cartella", err)


class HeaderTest(unittest.TestCase):
    def test_frame_reaches_the_document(self) -> None:
        space = Workspace(self)
        header = space.header({"contract": 1, "frame": {"issuer": "Studio Esempio & C."}})
        code, report = build(space.package, "-o", space.root / "out", "--header", header)
        self.assertEqual(code, 0, report["errors"])
        document = (space.root / "out" / "document.tex").read_text(encoding="utf-8")
        self.assertIn(r"\RdFrame{issuer}{Studio Esempio \& C.}", document)

    def test_header_errors_stop_with_2(self) -> None:
        cases = {
            "regodoc.header.contract": {"contract": 2},
            "regodoc.header.unknown_key": {"contract": 1, "title": "x"},
            "regodoc.header.value": {"contract": 1, "document_created": "2026-10-05"},
        }
        for expected, value in cases.items():
            with self.subTest(expected):
                space = Workspace(self)
                code, report = build(
                    space.package, "-o", space.root / "out", "--header", space.header(value)
                )
                self.assertEqual(code, 2)
                self.assertIn(expected, error_codes(report))
                self.assertFalse((space.root / "out").exists())

    def test_header_syntax(self) -> None:
        for text in ('{"contract": 1, "contract": 1}', "{", '{"contract": NaN}', "[]"):
            with self.subTest(text):
                space = Workspace(self)
                code, report = build(
                    space.package, "-o", space.root / "o", "--header", space.header(text)
                )
                self.assertEqual(code, 2)
                self.assertEqual(error_codes(report), ["regodoc.header.syntax"])

    def test_frame_values(self) -> None:
        for frame in ({"Bad": "x"}, {"issuer": ""}, {"issuer": 3}, {"issuer": "a\u202eb"}):
            with self.subTest(frame):
                space = Workspace(self)
                header = space.header({"contract": 1, "frame": frame})
                code, report = build(space.package, "-o", space.root / "o", "--header", header)
                self.assertEqual(code, 2)
                self.assertEqual(error_codes(report), ["regodoc.header.value"])

    def test_missing_header_file(self) -> None:
        space = Workspace(self)
        code, report = build(
            space.package, "-o", space.root / "o", "--header", space.root / "none.json"
        )
        self.assertEqual(code, 2)
        self.assertEqual(error_codes(report), ["regodoc.header.missing"])


def without_date() -> dict[str, bytes]:
    files = example_files()
    files["structure.toml"] = re.sub(rb"date = .*\n", b"", files["structure.toml"])
    return files


class DateTest(unittest.TestCase):
    def date_in(self, output: Path) -> str:
        document = (output / "document.tex").read_text(encoding="utf-8")
        match = re.search(r"\\RdDate\{(.*)\}", document)
        assert match is not None
        return match.group(1)

    def test_package_date_wins(self) -> None:
        space = Workspace(self)
        header = space.header({"contract": 1, "document_created": "2027-01-01T10:00:00+01:00"})
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
            build(space.package, "-o", space.root / "o", "--header", header)
        self.assertEqual(self.date_in(space.root / "o"), "5 ottobre 2026")

    def test_document_created_keeps_its_own_time_zone(self) -> None:
        space = Workspace(self, without_date())
        header = space.header({"contract": 1, "document_created": "2026-10-06T00:30:00+02:00"})
        code, report = build(space.package, "-o", space.root / "o", "--header", header)
        self.assertEqual(code, 0, report["errors"])
        self.assertEqual(self.date_in(space.root / "o"), "6 ottobre 2026")

    def test_source_date_epoch_is_utc(self) -> None:
        space = Workspace(self, without_date())
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1791237600"}):
            code, _ = build(space.package, "-o", space.root / "o")
        self.assertEqual(code, 0)
        self.assertEqual(self.date_in(space.root / "o"), "5 ottobre 2026")

    def test_malformed_or_missing_date(self) -> None:
        for value, expected in (
            ("-1", "regodoc.usage"),
            ("12a", "regodoc.usage"),
            (None, "regodoc.header.date"),
        ):
            with self.subTest(value):
                space = Workspace(self, without_date())
                environment = {k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}
                if value is not None:
                    environment["SOURCE_DATE_EPOCH"] = value
                with mock.patch.dict(os.environ, environment, clear=True):
                    code, report = build(space.package, "-o", space.root / "o")
                self.assertEqual(code, 2)
                self.assertEqual(error_codes(report), [expected])

    def test_source_date_epoch_is_ignored_when_not_needed(self) -> None:
        space = Workspace(self)
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "nonsense"}):
            code, _ = build(space.package, "-o", space.root / "o")
        self.assertEqual(code, 0)


class ThemeFolderTest(unittest.TestCase):
    def build_with(self, space: Workspace, theme: Path) -> tuple[int, dict[str, object]]:
        return build(space.package, "-o", space.root / "o", "--theme", theme)

    def test_a_copy_of_the_neutral_theme_works(self) -> None:
        space = Workspace(self)
        code, report = self.build_with(space, space.theme())
        self.assertEqual(code, 0, report["errors"])
        self.assertEqual(report["theme"]["name"], "neutral")  # type: ignore[index]

    def test_missing_theme(self) -> None:
        space = Workspace(self)
        code, report = self.build_with(space, space.root / "none")
        self.assertEqual(code, 2)
        self.assertEqual(error_codes(report), ["regodoc.theme.missing"])

    def test_layout_errors(self) -> None:
        def symlink(theme: Path) -> None:
            (theme / "assets").mkdir()
            (theme / "assets" / "logo.png").symlink_to("/etc/hostname")

        def extra(theme: Path) -> None:
            (theme / "notes.txt").write_text("x")

        def uppercase(theme: Path) -> None:
            (theme / "assets").mkdir()
            (theme / "assets" / "Logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        def missing(theme: Path) -> None:
            (theme / "theme.sty").unlink()

        def fifo(theme: Path) -> None:
            os.mkfifo(theme / "theme.cfg")

        for change in (symlink, extra, uppercase, missing, fifo):
            with self.subTest(change.__name__):
                space = Workspace(self)
                theme = space.theme()
                change(theme)
                code, report = self.build_with(space, theme)
                self.assertEqual(code, 2)
                self.assertEqual(error_codes(report), ["regodoc.theme.layout"])

    def test_asset_signature(self) -> None:
        space = Workspace(self)
        theme = space.theme()
        (theme / "assets").mkdir()
        (theme / "assets" / "logo.pdf").write_bytes(b"not a pdf")
        code, report = self.build_with(space, theme)
        self.assertEqual(code, 2)
        self.assertEqual(error_codes(report), ["regodoc.theme.asset"])

    def test_limits(self) -> None:
        space = Workspace(self)
        theme = space.theme()
        (theme / "assets").mkdir()
        for index in range(declaration.THEME_LIMITS["files"]):
            (theme / "assets" / f"a{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        code, report = self.build_with(space, theme)
        self.assertEqual(code, 2)
        self.assertEqual(error_codes(report), ["regodoc.theme.limit"])
        for path in (theme / "assets").iterdir():
            path.unlink()
        (theme / "assets" / "big.pdf").write_bytes(
            b"%PDF-" + b"0" * declaration.THEME_LIMITS["bytes"]
        )
        code, report = self.build_with(space, theme)
        self.assertEqual(error_codes(report), ["regodoc.theme.limit"])

    def test_theme_toml(self) -> None:
        cases = {
            'name = "x"\nname = "y"\n': 2,
            'name = "Brand"\nversion = "1"\ntheme_contract = 1\n': 0,
            'name = "b"\nversion = "1"\ntheme_contract = 2\n': 0,
            'name = "b"\nversion = "1"\ntheme_contract = 1\ncolour = 1\n': 0,
            'name = "b"\nversion = "1"\ntheme_contract = 1\n[palette]\nazure = "blue"\n': 0,
            'name = "b"\nversion = "1"\ntheme_contract = 1\n[palette]\nteal = "000000"\n': 0,
            'name = "b"\nversion = "1"\ntheme_contract = 1\ntex_packages = ["a", "a"]\n': 0,
        }
        for text, line in cases.items():
            with self.subTest(text):
                space = Workspace(self)
                theme = space.theme()
                (theme / "theme.toml").write_text(text)
                code, report = self.build_with(space, theme)
                self.assertEqual(code, 2)
                self.assertEqual(set(error_codes(report)), {"regodoc.theme.toml"})
                self.assertEqual(report["errors"][0]["line"], line)  # type: ignore[index]

    def test_missing_roles_take_the_neutral_colour(self) -> None:
        space = Workspace(self)
        theme = space.theme()
        text = (theme / "theme.toml").read_text()
        (theme / "theme.toml").write_text(
            re.sub(r'azure = "\w+"\n', 'azure = "123abc"\n', re.sub(r"plum = .*\n", "", text))
        )
        code, report = self.build_with(space, theme)
        self.assertEqual(code, 0, report["errors"])
        infos = [w for w in report["warnings"] if w["severity"] == "info"]  # type: ignore[union-attr]
        self.assertEqual([w["code"] for w in infos], ["regodoc.theme.role_default"])
        self.assertIn("«plum»", infos[0]["message"])
        document = (space.root / "o" / "document.tex").read_text()
        self.assertIn(r"\RdColor{azure}{123ABC}", document)
        self.assertIn(r"\RdColor{plum}{674766}", document)
        code, _, _ = run_cli(
            "build",
            str(space.package),
            "-o",
            str(space.root / "s"),
            "--format",
            "latex",
            "--theme",
            str(theme),
            "--strict",
        )
        self.assertEqual(code, 0)

    def test_frame_keys_missing_from_the_header(self) -> None:
        space = Workspace(self)
        theme = space.theme()
        text = (
            (theme / "theme.toml")
            .read_text()
            .replace("frame_keys = []", 'frame_keys = ["issuer", "recipient"]')
        )
        (theme / "theme.toml").write_text(text)
        header = space.header({"contract": 1, "frame": {"issuer": "Studio"}})
        code, report = build(
            space.package, "-o", space.root / "o", "--theme", theme, "--header", header
        )
        self.assertEqual(code, 0)
        messages = [
            w["message"] for w in report["warnings"] if w["code"] == "regodoc.theme.frame_key"
        ]  # type: ignore[union-attr]
        self.assertEqual(len(messages), 1)
        self.assertIn("«recipient»", messages[0])

    def test_theme_sha256(self) -> None:
        first, second = read_theme(None, Collector()), read_theme(None, Collector())
        assert first is not None and second is not None
        self.assertEqual(first.sha256, second.sha256)
        self.assertRegex(first.sha256, "^[0-9a-f]{64}$")
        space = Workspace(self)
        theme = space.theme()
        _, before = self.build_with(space, theme)
        (theme / "theme.sty").write_text((theme / "theme.sty").read_text() + "% x\n")
        _, after = self.build_with(space, theme)
        self.assertNotEqual(before["theme"], after["theme"])  # type: ignore[index]


class StaticCheckTest(unittest.TestCase):
    def test_forbidden_commands_with_position(self) -> None:
        cases = {
            r"\input{/etc/passwd}": (r"\input", 1),
            r"  \immediate\write18{ls}": (r"\write18", 13),
            r"\pdfobj file{/etc/passwd}": (r"\pdfobj", 1),
            r"x\pdfmapfile{+/x.map}": (r"\pdfmapfile", 2),
            r"\openin3=/etc/passwd": (r"\openin", 1),
            r"\ExplSyntaxOn \tex_input:D /etc/passwd": (r"\tex_input:D", 15),
            r"\pdfprimitive\pdfobj": (r"\pdfprimitive", 1),
            r"\% \input{x}": (r"\input", 4),
        }
        for line, (command, column) in cases.items():
            with self.subTest(line):
                space = Workspace(self)
                theme = space.theme()
                sty = theme / "theme.sty"
                sty.write_text(sty.read_text() + line + "\n")
                lines = sty.read_text().count("\n")
                code, report = build(space.package, "-o", space.root / "o", "--theme", theme)
                self.assertEqual(code, 2)
                error = report["errors"][0]  # type: ignore[index]
                self.assertEqual(error["code"], "regodoc.theme.forbidden")
                self.assertEqual(
                    (error["file"], error["line"], error["column"]), ("theme.sty", lines, column)
                )
                self.assertTrue(error["message"].startswith(command))

    def test_comments_and_longer_names_are_not_forbidden(self) -> None:
        space = Workspace(self)
        theme = space.theme()
        sty = theme / "theme.sty"
        sty.write_text(
            sty.read_text() + "% \\input{x} \\write18\n\\newcommand\\inputx{}\\includegraphics\n"
        )
        code, report = build(space.package, "-o", space.root / "o", "--theme", theme)
        self.assertEqual(code, 0, report["errors"])

    def test_encoding(self) -> None:
        for data in (b"\xff", "a\u202eb".encode(), b"\xef\xbb\xbfx"):
            with self.subTest(data):
                space = Workspace(self)
                theme = space.theme()
                (theme / "theme.sty").write_bytes(data)
                code, report = build(space.package, "-o", space.root / "o", "--theme", theme)
                self.assertEqual(code, 2)
                self.assertEqual(error_codes(report), ["regodoc.theme.encoding"])


class DeclarationTest(unittest.TestCase):
    def test_build_is_ready(self) -> None:
        described = declaration.describe()
        self.assertEqual(described["commands"]["build"], "ready")  # type: ignore[index]
        for capability in ("build.pdf", "build.latex", "build.theme"):
            self.assertIn(capability, described["capabilities"])  # type: ignore[operator]

    def test_tex_packages_are_those_of_regodoc_sty(self) -> None:
        sty = (SOURCE / "regodoc.sty").read_text()
        loaded = set(re.findall(r"\\RequirePackage(?:\[[^\]]*\])?\{([a-z]+)\}", sty)) - {"theme"}
        self.assertEqual(sorted(loaded), sorted(declaration.TEX_PACKAGES))
        neutral = (NEUTRAL_DIR / "theme.sty").read_text()
        self.assertNotIn("\\RequirePackage", neutral)
        self.assertNotIn("\\usepackage", neutral)


if __name__ == "__main__":
    unittest.main()
