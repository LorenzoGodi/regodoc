"""Prove di tools/check_install.py, l'avvio del motore installato come lo fa Rego.

La prova completa compila un PDF: senza pdflatex si salta, tranne quando
``REGODOC_REQUIRE_TEX`` vale 1, come nella CI.
"""

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

from regodoc import __version__
from tests.support import ENGINE, EXAMPLE, run_cli

_PATH = Path(__file__).resolve().parent.parent / "tools" / "check_install.py"
_SPEC = importlib.util.spec_from_file_location("check_install", _PATH)
assert _SPEC and _SPEC.loader
install = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(install)

REQUIRE_TEX = os.environ.get("REGODOC_REQUIRE_TEX") == "1"
PDFLATEX = shutil.which("pdflatex")
ENVIRONMENT = {"PATH": os.environ.get("PATH", os.defpath)}


def declaration() -> dict[str, object]:
    code, out, _ = run_cli("info")
    assert code == 0
    return json.loads(out)


class InfoTest(unittest.TestCase):
    def test_this_engine_passes(self) -> None:
        self.assertEqual(install.info_problems(declaration(), __version__), [])

    def test_each_mismatch_is_reported(self) -> None:
        cases = {
            "versione": {"version": "0.0.1"},
            "contracts": {"contracts": [2]},
            "più vecchio": {"expat": "2.5.0", "expat_min": "2.6.0"},
            "illeggibili": {"expat": "nuovo"},
            "grammars.read": {"grammars": {"current": "rego/2", "read": ["rego/2"]}},
        }
        for word, change in cases.items():
            with self.subTest(word):
                problems = install.info_problems({**declaration(), **change}, __version__)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])

    def test_expat_versions_compare_as_numbers(self) -> None:
        info = {**declaration(), "expat": "2.10.0", "expat_min": "2.6.0"}
        self.assertEqual(install.info_problems(info, __version__), [])


class RunTest(unittest.TestCase):
    def test_empty_folder_and_no_input(self) -> None:
        script = "import os, sys; print(os.listdir('.'), repr(sys.stdin.read()))"
        code, out = install.run([sys.executable, "-c", script], 30, ENVIRONMENT)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[] ''")

    def test_only_the_given_variables(self) -> None:
        script = "import os; print(os.environ.get('HOME'), os.environ.get('PYTHONPATH'))"
        code, out = install.run([sys.executable, "-I", "-c", script], 30, ENVIRONMENT)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "None None")

    def test_time_out_kills_the_whole_group(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            pid_file = Path(folder) / "figlio"
            script = f"sleep 60 & echo $! > {pid_file}; wait"
            started = time.monotonic()
            code, _ = install.run(["/bin/sh", "-c", script], 1, ENVIRONMENT)
            self.assertLess(time.monotonic() - started, 10)
            self.assertEqual(code, install.KILLED)
            child = int(pid_file.read_text(encoding="utf-8"))
        # Il figlio ucciso con il gruppo non esiste più, o resta solo come processo concluso
        # in attesa che il sistema lo raccolga.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _alive(child):
            time.sleep(0.05)
        self.assertFalse(_alive(child))


def _alive(pid: int) -> bool:
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        return "zombie" not in status.read_text(encoding="utf-8")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@unittest.skipUnless(PDFLATEX or REQUIRE_TEX, "pdflatex non installato")
class CheckTest(unittest.TestCase):
    def test_the_engine_passes_every_step(self) -> None:
        # Un interprete finto che, come python -I -B -m regodoc, avvia il motore da cui le
        # prove lo importano: src/ o il wheel installato.
        with tempfile.TemporaryDirectory() as folder:
            wrapper = Path(folder) / "python"
            entry = (
                "import sys; sys.path.insert(0, sys.argv[1]); from regodoc.cli import main; "
                "sys.exit(main(sys.argv[2:]))"
            )
            wrapper.write_text(
                f'#!/bin/sh\nshift 4\nexec "{sys.executable}" -I -B -c "{entry}" "{ENGINE}" "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(stat.S_IRWXU)
            out = Path(folder) / "uscita"
            out.mkdir()
            problems = install.check(str(wrapper), __version__, EXAMPLE, out)
            self.assertEqual(problems, [])
            self.assertTrue((out / "documento.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertEqual(install.check(str(wrapper), "0.0.1", EXAMPLE, out)[0][:5], "info:")


if __name__ == "__main__":
    unittest.main()
