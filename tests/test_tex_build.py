"""Prove di ``build`` che compilano: esempi senza avvisi, PDF riproducibili, tutti i caratteri
ammessi, e un caso per ciascun divieto dei temi esterni (contratto, §6.5).

Senza pdflatex le prove si saltano, tranne quando ``REGODOC_REQUIRE_TEX`` vale 1, come nel
job TeX della CI: lì un pdflatex mancante è un errore.

I casi dei divieti aggirano di proposito il controllo statico di ``theme.sty``, con
``\\csname``: devono fermarli l'ambiente di pdfTeX, il log e il file ``.fls``.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from regodoc import build as build_module
from regodoc import compiler
from regodoc.text import is_allowed_char
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, run_cli
from tests.test_build import Workspace

REQUIRE_TEX = os.environ.get("REGODOC_REQUIRE_TEX") == "1"
PDFLATEX = compiler.find_pdflatex()
LEAK_MARK = "SEGRETO-7f3a9c"
# Messaggi del log che una compilazione degli esempi non deve contenere.
_LOG_WARNINGS = re.compile(r"Warning|Overfull|Underfull|Missing character|^! ", re.M)


def pdf_content(pdf: bytes) -> bytes:
    """I byte del PDF con i flussi compressi decompressi: i metadati stanno in flussi."""
    parts = [pdf]
    for match in re.finditer(rb"stream\r?\n", pdf):
        end = pdf.find(b"endstream", match.end())
        try:
            parts.append(zlib.decompressobj().decompress(pdf[match.end() : end]))
        except zlib.error:
            continue
    return b"\n".join(parts)


def compile_log(package: Path, root: Path) -> str:
    """Compila con il tema neutro e restituisce il log, che build non conserva."""
    code, out, _ = run_cli("build", str(package), "-o", str(root / "tex"), "--format", "latex")
    assert code == 0, out
    doc = root / "tex"
    home = root / "home"
    home.mkdir()
    assert PDFLATEX is not None
    compiler.compile_pdf(doc, home, 1791158400, PDFLATEX)
    return (doc / "document.log").read_text(encoding="utf-8", errors="replace")


@unittest.skipUnless(PDFLATEX or REQUIRE_TEX, "pdflatex non disponibile")
class ExamplesCompileTest(unittest.TestCase):
    def test_examples_compile_without_warnings(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            with self.subTest(root.name), tempfile.TemporaryDirectory() as folder:
                package = Path(folder) / "p.regodoc"
                package.write_bytes(build_zip(example_files(root)))
                log = compile_log(package, Path(folder))
                lines = log.split("\n")
                found = [
                    "\n".join(lines[i : i + 4])
                    for i, line in enumerate(lines)
                    if _LOG_WARNINGS.search(line)
                ]
                self.assertEqual(found, [])

    def test_two_builds_give_the_same_pdf(self) -> None:
        space = Workspace(self, example_files(LONG_EXAMPLE))
        pdfs = []
        for name in ("a", "b"):
            work = space.root / f"tmp-{name}"
            work.mkdir()
            with mock.patch.dict(os.environ, {"TMPDIR": str(work)}):
                tempfile.tempdir = None
                code, out, _ = run_cli(
                    "build", str(space.package), "-o", str(space.root / f"{name}.pdf"), "--json"
                )
            tempfile.tempdir = None
            self.assertEqual(code, 0, out)
            report = json.loads(out)
            self.assertGreaterEqual(report["passes"], 2)
            self.assertTrue(report["tex"]["version_line"].startswith("pdfTeX"))
            pdfs.append((space.root / f"{name}.pdf").read_bytes())
        self.assertEqual(pdfs[0], pdfs[1])
        self.assertTrue(pdfs[0].startswith(b"%PDF-"))
        content = pdf_content(pdfs[0])
        self.assertNotIn(str(space.root).encode(), content)
        self.assertNotIn(b"/ID", content)
        self.assertNotIn(b"PTEX.", content)
        # hyperref scrive le stringhe di /Info in UTF-16, con gli ottali di PDF.
        regodoc = b"\\376\\377" + b"".join(b"\\000" + bytes([c]) for c in b"regodoc")
        self.assertIn(b"/Producer(" + regodoc + b")", content)
        self.assertIn(b"/CreationDate (D:20260928000000Z)", content)

    def test_every_allowed_character_compiles(self) -> None:
        chars = [
            chr(c) for c in range(0x20, 0x2300) if is_allowed_char(chr(c)) and chr(c) not in '<&"-'
        ]
        text = " ".join("".join(chars[i : i + 8]) for i in range(0, len(chars), 8))
        files = example_files()
        part = files["parts/backup.xml"].decode()
        marker = '<section id="offsite">'
        section = (
            f"<section><title>Caratteri</title><p>{text}</p><p><code>{text}</code></p></section>"
        )
        files["parts/backup.xml"] = part.replace(marker, section + marker, 1).encode()
        space = Workspace(self, files)
        log = compile_log(space.package, space.root)
        self.assertNotIn("Missing character", log)
        self.assertIsNone(re.search(r"^! ", log, re.M))


def secret_file(test: unittest.TestCase) -> Path:
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    path = Path(folder.name) / "secret.txt"
    path.write_text(LEAK_MARK + "\n")
    return path


@unittest.skipUnless(PDFLATEX or REQUIRE_TEX, "pdflatex non disponibile")
class PdfReaderTest(unittest.TestCase):
    """Il lettore degli oggetti del PDF, su PDF scritti a mano."""

    @staticmethod
    def pdf(*objects: bytes, xref: bool = True) -> bytes:
        out = b"%PDF-1.5\n"
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        start = len(out)
        if xref:
            out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
            out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
            out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        else:
            start = offsets[-1]
        return out + f"startxref\n{start}\n%%EOF\n".encode()

    def test_clean_pdf(self) -> None:
        stream = b"BT /JS (/OpenAction) Tj ET /AA"
        pdf = self.pdf(
            b"<< /Type /Catalog /Pages 2 0 R /URI (https://x/JS/AA \\) /AA) >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        )
        compiler.check_pdf(pdf)

    def test_active_or_hidden_objects(self) -> None:
        cases = (
            self.pdf(b"<< /Type /Catalog /OpenAction 2 0 R >>"),
            self.pdf(b"<< /Type /Catalog /Names << /J#61vaScript 2 0 R >> >>"),
            self.pdf(b"<< /Type /ObjStm /N 1 /Length 3 >>\nstream\nabc\nendstream"),
            self.pdf(b"<< /Type /XRef /Length 3 >>\nstream\nabc\nendstream", xref=False),
            self.pdf(b"<< /Length 2 0 R >>\nstream\nabc\nendstream", b"3"),
            self.pdf(b"<< /Length 1 >>\nstream\nabc\nendstream /OpenAction"),
        )
        for pdf in cases:
            with self.subTest(pdf[:80]), self.assertRaises(compiler.CompileError) as caught:
                compiler.check_pdf(pdf)
            self.assertEqual(caught.exception.code, "regodoc.pdf.active")


class ExternalThemeTest(unittest.TestCase):
    """Un caso per divieto: il codice, nessuna uscita, nessuna traccia del file segreto."""

    def build_theme(
        self, extra: str, *, toml: str = ""
    ) -> tuple[int, dict[str, object], Workspace]:
        space = Workspace(self)
        theme = space.theme()
        sty = theme / "theme.sty"
        sty.write_text(sty.read_text().replace("\\endinput\n", extra + "\n\\endinput\n"))
        if toml:
            text = (theme / "theme.toml").read_text()
            (theme / "theme.toml").write_text(text.replace("tex_packages = []", toml))
        output = space.root / "out.pdf"
        code, out, _ = run_cli(
            "build", str(space.package), "-o", str(output), "--theme", str(theme), "--json"
        )
        report = json.loads(out)
        if code != 0:
            self.assertFalse(output.exists())
        self.assertNotIn(LEAK_MARK, out)
        return code, report, space

    def assert_refused(self, extra: str, code: str, exit_code: int = 2) -> dict[str, object]:
        got, report, _ = self.build_theme(extra)
        self.assertEqual(got, exit_code, report["errors"])
        self.assertEqual([e["code"] for e in report["errors"]], [code])  # type: ignore[union-attr, index]
        return report["errors"][0]  # type: ignore[index, return-value]

    def test_shell_escape_is_off(self) -> None:
        marker = secret_file(self).parent / "pwned"
        self.assert_refused(
            rf"\immediate\csname write\endcsname18{{touch {marker}}}", "regodoc.theme.shell"
        )
        self.assertFalse(marker.exists())

    def test_input_outside_is_refused(self) -> None:
        secret = secret_file(self)
        error = self.assert_refused(rf"\csname input\endcsname{{{secret}}}", "regodoc.theme.read")
        self.assertEqual(error["file"], "theme.sty")
        self.assertGreater(error["line"], 0)

    def test_input_with_dots_is_refused(self) -> None:
        self.assert_refused(r"\csname input\endcsname{../../secret.txt}", "regodoc.theme.read")

    def test_openout_outside_is_refused(self) -> None:
        target = secret_file(self).parent / "written.tex"
        self.assert_refused(
            rf"\newwrite\w \immediate\csname openout\endcsname\w={target} \immediate\write\w{{x}}",
            "regodoc.theme.write",
        )
        self.assertFalse(target.exists())

    def test_pdfobj_file_is_caught_by_the_recorder(self) -> None:
        secret = secret_file(self)
        self.assert_refused(
            rf"\immediate\csname pdfobj\endcsname file{{{secret}}}\pdfrefobj\pdflastobj",
            "regodoc.theme.read",
        )

    def test_pdfmapfile_is_caught_by_the_recorder(self) -> None:
        secret = secret_file(self)
        self.assert_refused(rf"\csname pdfmapfile\endcsname{{+{secret}}}", "regodoc.theme.read")

    def test_font_by_absolute_path_is_caught_by_the_recorder(self) -> None:
        folder = secret_file(self).parent
        assert PDFLATEX is not None
        source = Path(PDFLATEX).resolve()  # un file qualunque fuori dall'albero TeX
        shutil.copy(source, folder / "x.tfm")
        self.assert_refused(rf"\font\rdx={folder}/x.tfm", "regodoc.theme.read")

    def test_rewriting_the_recorder_is_refused(self) -> None:
        self.assert_refused(
            r"\newwrite\w \immediate\csname openout\endcsname\w=document.fls "
            r"\immediate\write\w{PWD /}\immediate\closeout\w",
            "regodoc.theme.write",
        )

    def test_content_commands_cannot_be_redefined(self) -> None:
        error = self.assert_refused(r"\renewcommand\RdB[1]{#1}", "regodoc.theme.redefined")
        self.assertIn("\\RdB", error["message"])

    def test_undeclared_package_is_refused(self) -> None:
        self.assert_refused(r"\RequirePackage{eso-pic}", "regodoc.theme.package")

    def test_declared_package_and_assets_are_fine(self) -> None:
        space_check = self.build_theme(
            r"\RequirePackage{eso-pic}\renewcommand\RegodocPageStyle{\pagestyle{regodoc}}",
            toml='tex_packages = ["eso-pic"]',
        )
        self.assertEqual(space_check[0], 0, space_check[1]["errors"])

    def test_package_missing_from_the_image_is_an_environment_error(self) -> None:
        code, report, _ = self.build_theme(
            r"\RequirePackage{regodocmissingpackage}",
            toml='tex_packages = ["regodocmissingpackage"]',
        )
        self.assertEqual(code, 3)
        self.assertEqual([e["code"] for e in report["errors"]], ["regodoc.tex.missing"])  # type: ignore[union-attr, index]

    def test_a_theme_error_points_to_theme_sty(self) -> None:
        error = self.assert_refused(r"\undefinedcommandoftheme", "regodoc.theme.compile")
        self.assertEqual(error["file"], "theme.sty")
        sty = (Path(build_module.__file__).parent / "tex" / "neutral" / "theme.sty").read_text()
        self.assertEqual(error["line"], sty.count("\n"))

    def test_switching_off_the_comparison_is_tampering(self) -> None:
        # In una .sty la @ è una lettera: un tema raggiunge i controlli di regodoc.sty. La
        # prova positiva del log lo scopre.
        for extra in (
            r"\def\rd@checkall{}\renewcommand\RdB[1]{#1}",
            r"\def\rd@guarded{}\renewcommand\RdB[1]{#1}",
        ):
            with self.subTest(extra):
                self.assert_refused(extra, "regodoc.theme.tampered")

    def test_switching_off_the_package_hook_is_caught_by_the_recorder(self) -> None:
        error = self.assert_refused(
            r"\rd@inthemefalse\RequirePackage{eso-pic}", "regodoc.theme.package"
        )
        self.assertIn("eso-pic.sty", error["message"])

    def test_active_content_in_the_pdf_is_refused(self) -> None:
        cases = (
            r"\csname pdfcatalog\endcsname{/OpenAction << /S /JavaScript /JS (app.alert(1)) >>}",
            # Un nome codificato con #XX, con # di catcode 12 perché TeX non lo raddoppi.
            r"{\catcode`\#=12 \csname pdfcatalog\endcsname{/Names << /J#61vaScript 1 0 R >>}}",
            r"\csname pdfcatalog\endcsname{/AA << >>}",
        )
        for extra in cases:
            with self.subTest(extra):
                self.assert_refused(extra, "regodoc.pdf.active")

    def test_names_inside_strings_and_streams_are_not_active(self) -> None:
        files = example_files()
        part = files["parts/backup.xml"].decode()
        link = '<p><link href="https://x.example/JS/OpenAction">qui</link> /JS /AA</p>'
        files["parts/backup.xml"] = part.replace("<small>", link + "<small>", 1).encode()
        space = Workspace(self, files)
        code, out, _ = run_cli(
            "build", str(space.package), "-o", str(space.root / "o.pdf"), "--json"
        )
        self.assertEqual(code, 0, out)

    def test_neutral_theme_failure_is_an_internal_error(self) -> None:
        space = Workspace(self)
        with mock.patch.object(
            build_module, "render_document", return_value="\\documentclass{article}\\undefined\n"
        ):
            code, out, _ = run_cli(
                "build", str(space.package), "-o", str(space.root / "o.pdf"), "--json"
            )
        self.assertEqual(code, 4)
        self.assertEqual([e["code"] for e in json.loads(out)["errors"]], ["regodoc.internal"])


if __name__ == "__main__":
    unittest.main()
