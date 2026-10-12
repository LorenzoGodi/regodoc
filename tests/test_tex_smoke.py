"""Prova di fumo dell'immagine TeX: compilazione riproducibile byte per byte.

Senza pdflatex la prova si salta, tranne quando la variabile ``REGODOC_REQUIRE_TEX`` vale 1,
come nel job TeX della CI: lì un pdflatex mancante è un errore.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parent / "data" / "tex" / "smoke.tex"
REQUIRE_TEX = os.environ.get("REGODOC_REQUIRE_TEX") == "1"
PDFLATEX = shutil.which("pdflatex")


def compile_once(workdir: Path) -> bytes:
    """Compila il sorgente di prova in una cartella pulita e restituisce i byte del PDF."""
    shutil.copy(SOURCE, workdir / "smoke.tex")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(workdir),
        "SOURCE_DATE_EPOCH": "1790812800",
        "FORCE_SOURCE_DATE": "1",
        "openout_any": "p",
        "openin_any": "p",
        "shell_escape": "f",
    }
    for _ in range(2):
        subprocess.run(
            [
                PDFLATEX or "pdflatex",
                "-no-shell-escape",
                "-interaction=batchmode",
                "-halt-on-error",
                "smoke.tex",
            ],
            cwd=workdir,
            env=env,
            capture_output=True,
            check=True,
            timeout=120,
        )
    return (workdir / "smoke.pdf").read_bytes()


@unittest.skipUnless(PDFLATEX or REQUIRE_TEX, "pdflatex non disponibile")
class TexSmokeTest(unittest.TestCase):
    """Due compilazioni in cartelle diverse danno lo stesso PDF."""

    def test_reproducible_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            pdf_a = compile_once(Path(first))
            pdf_b = compile_once(Path(second))
        self.assertTrue(pdf_a.startswith(b"%PDF-"))
        self.assertEqual(pdf_a, pdf_b)


if __name__ == "__main__":
    unittest.main()
