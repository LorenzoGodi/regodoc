"""Le figure in PDF vettoriale nel pacchetto (specifica, §13; lotto L20): solo in rego/2, con il
controllo di pdffigure nella validazione, copiate byte per byte nella forma canonica."""

import json
import random
import tempfile
import unittest
import zipfile
from pathlib import Path

from regodoc import declaration, source
from regodoc.cli import ExitCode
from tests.support import (
    build_zip,
    codes,
    example_files,
    pdf,
    pdf_figure,
    png,
    run_cli,
    validate_files,
    vector_files,
)


def errors(files: dict[str, bytes]) -> list[tuple[str, str | None]]:
    report = validate_files(files).report
    return [(d.code, d.file) for d in report.errors]


class ValidateTest(unittest.TestCase):
    def test_a_clean_pdf_figure_is_valid_in_rego2(self) -> None:
        self.assertEqual(codes(validate_files(vector_files(example_files()))), [])

    def test_the_layout_admits_pdf(self) -> None:
        image = source.IMAGE_PATH
        self.assertTrue(image.fullmatch("images/rete.pdf"))
        self.assertEqual(image.pattern, declaration.IMAGE_PATTERN)
        self.assertFalse(source.RASTER_PATH.fullmatch("images/rete.pdf"))
        self.assertIn("figure.pdf", declaration.CAPABILITIES)

    def test_rego1_refuses_pdf_figures(self) -> None:
        files = vector_files(example_files())
        files["manifest.json"] = files["manifest.json"].replace(b'"rego/2"', b'"rego/1"')
        self.assertEqual(errors(files), [("regodoc.image.format", "images/coverage.pdf")])

    def test_each_refusal_names_the_file(self) -> None:
        objects = pdf_figure(page_extra=b"/AA << >> ")
        cases = {
            "regodoc.image.pdf_active": pdf(objects),
            "regodoc.image.pdf_pages": pdf(
                {**pdf_figure(), 2: b"<< /Type /Pages /Kids [3 0 R] /Count 2 >>"}
            ),
            "regodoc.image.pdf_structure": pdf(pdf_figure())[:-10],
            "regodoc.image.extension": png(),
        }
        for code, data in cases.items():
            with self.subTest(code):
                files = vector_files(example_files(), data)
                self.assertEqual(errors(files), [(code, "images/coverage.pdf")])

    def test_a_pdf_with_a_raster_extension_keeps_its_code(self) -> None:
        files = example_files()
        files["images/coverage.png"] = pdf(pdf_figure())
        self.assertEqual(errors(files), [("regodoc.image.format", "images/coverage.png")])

    def test_errors_are_collected_per_image(self) -> None:
        files = vector_files(example_files(), pdf(pdf_figure(page_extra=b"/JS 1 ")))
        files["images/altra.pdf"] = pdf(pdf_figure(page_extra=b"/Metadata 1 "))
        self.assertEqual(
            sorted(errors(files)),
            [
                ("regodoc.image.pdf_active", "images/coverage.pdf"),
                ("regodoc.image.pdf_metadata", "images/altra.pdf"),
            ],
        )


def at_the_limit() -> dict[str, bytes]:
    """Il pacchetto d'esempio con figure in PDF da 4 MiB fino al tetto di tutto il pacchetto.
    Il riempimento è una stringa esadecimale casuale, che l'archivio non comprime oltre il
    rapporto ammesso."""
    total = int(declaration.CONTENT_LIMITS["pdf_total_bytes"])
    each = int(declaration.CONTENT_LIMITS["pdf_bytes"])
    assert total % each == 0
    noise = random.Random(5).randbytes(each).hex().encode()  # noqa: S311 - ripetibile
    filler = each - len(pdf({**pdf_figure(), 5: b"<>"}))
    full = b""
    for _ in range(2):
        full = pdf({**pdf_figure(), 5: b"<" + noise[:filler] + b">"})
        filler -= len(full) - each
    assert len(full) == each
    files = vector_files(example_files(), full)
    for number in range(1, total // each):
        files[f"images/extra{number}.pdf"] = full
    return files


class LimitTest(unittest.TestCase):
    def test_all_pdf_figures_together(self) -> None:
        # Le figure da 4 MiB stanno al tetto; una figura in più, l'ultima in ordine di
        # percorso, lo supera ed è rifiutata da sola.
        files = at_the_limit()
        self.assertEqual(errors(files), [])
        files["images/zz.pdf"] = pdf(pdf_figure())
        self.assertEqual(errors(files), [("regodoc.limit.pdf", "images/zz.pdf")])


class Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self, *argv: object) -> tuple[int, dict[str, object]]:
        code, out, _ = run_cli("--contract", "1", *(str(a) for a in argv), "--json")
        return code, json.loads(out)


class CanonicalTest(Workspace):
    def test_canon_copies_the_pdf_and_is_idempotent(self) -> None:
        files = vector_files(example_files())
        source_path = self.folder / "in.regodoc"
        source_path.write_bytes(build_zip(files))
        out = self.folder / "out.regodoc"
        code, report = self.command("canon", source_path, "-o", out)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        with zipfile.ZipFile(out) as archive:
            self.assertEqual(archive.read("images/coverage.pdf"), files["images/coverage.pdf"])
            info = archive.getinfo("images/coverage.pdf")
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
        again = self.folder / "again.regodoc"
        code, _ = self.command("canon", out, "-o", again)
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(again.read_bytes(), out.read_bytes())

    def test_canon_writes_a_package_at_the_limit(self) -> None:
        # La forma canonica memorizza le figure: al tetto il pacchetto sta nell'involucro.
        source_path = self.folder / "in.regodoc"
        source_path.write_bytes(build_zip(at_the_limit()))
        out = self.folder / "out.regodoc"
        code, report = self.command("canon", source_path, "-o", out)
        self.assertEqual(code, ExitCode.OK, report["errors"])

    def test_upgrade_from_rego1_refuses_a_pdf_figure(self) -> None:
        files = vector_files(example_files())
        files["manifest.json"] = files["manifest.json"].replace(b'"rego/2"', b'"rego/1"')
        source_path = self.folder / "in.regodoc"
        source_path.write_bytes(build_zip(files))
        code, report = self.command("upgrade", source_path, "-o", self.folder / "out.regodoc")
        self.assertEqual(code, ExitCode.REFUSED)
        found = [e["code"] for e in report["errors"]]  # type: ignore[index, union-attr]
        self.assertEqual(found, ["regodoc.image.format"])


class MarkdownTest(Workspace):
    def test_md1_keeps_raster_figures_only(self) -> None:
        # L'ingresso md/1 non cambia: le sue figure restano PNG e JPEG (md-1.md, §3).
        folder = self.folder / "ingresso"
        (folder / "images").mkdir(parents=True)
        (folder / "document.md").write_text(
            "# Titolo\n\n## Parte\n\n![Rete](images/rete.pdf)\n", encoding="utf-8"
        )
        (folder / "images" / "rete.pdf").write_bytes(pdf(pdf_figure()))
        code, report = self.command(
            "import", "--from", "markdown", folder, "-o", self.folder / "out.regodoc"
        )
        self.assertEqual(code, ExitCode.REFUSED)
        found = [e["code"] for e in report["errors"]]  # type: ignore[index, union-attr]
        self.assertEqual(found, ["regodoc.archive.layout"])
        # Senza il file, il rimando del testo è rifiutato dal lettore.
        (folder / "images" / "rete.pdf").unlink()
        code, report = self.command(
            "import", "--from", "markdown", folder, "-o", self.folder / "out.regodoc"
        )
        self.assertEqual(code, ExitCode.REFUSED)
        found = [e["code"] for e in report["errors"]]  # type: ignore[index, union-attr]
        self.assertEqual(found, ["regodoc.markdown.image"])


if __name__ == "__main__":
    unittest.main()
