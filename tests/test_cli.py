"""Prove del comando ``regodoc``: sottocomandi, codici d'uscita e messaggi in italiano."""

import contextlib
import io
import json
import subprocess
import sys
import unittest

from regodoc import __version__, cli, declaration
from regodoc.cli import ExitCode


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Esegue il comando nel processo e restituisce codice, stdout e stderr."""
    out, err = io.TextIOWrapper(io.BytesIO(), "utf-8"), io.TextIOWrapper(io.BytesIO(), "utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, _text(out), _text(err)


def _text(stream: io.TextIOWrapper) -> str:
    stream.flush()
    return stream.buffer.getvalue().decode("utf-8")  # type: ignore[attr-defined]


class InfoTest(unittest.TestCase):
    def test_info_is_the_declaration(self) -> None:
        code, out, _ = run_cli("info")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(json.loads(out), declaration.describe())

    def test_version(self) -> None:
        code, out, _ = run_cli("--version")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(out.strip(), f"regodoc {__version__}")


class DraftCommandTest(unittest.TestCase):
    def test_draft_commands_say_so(self) -> None:
        cases = {
            "validate": ("validate", "p.regodoc"),
            "canon": ("canon", "p.regodoc", "-o", "q.regodoc"),
            "build": ("build", "p.regodoc", "-o", "p.pdf"),
            "upgrade": ("upgrade", "p.regodoc", "-o", "q.regodoc"),
        }
        for name, argv in cases.items():
            with self.subTest(name):
                code, out, err = run_cli(*argv)
                self.assertEqual(code, ExitCode.ENVIRONMENT)
                self.assertEqual(out, "")
                self.assertIn(f"il comando «{name}» non è ancora implementato", err)

    def test_strict_is_accepted(self) -> None:
        code, _, _ = run_cli("validate", "p.regodoc", "--strict")
        self.assertEqual(code, ExitCode.ENVIRONMENT)

    def test_draft_json_report(self) -> None:
        code, out, err = run_cli("validate", "p.regodoc", "--json")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertFalse(report["ok"])
        self.assertEqual(report["command"], "validate")
        self.assertEqual(report["errors"][0]["code"], "regodoc.not_implemented")


class UsageErrorTest(unittest.TestCase):
    def test_missing_command(self) -> None:
        code, _, err = run_cli()
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("uso: regodoc", err)
        self.assertIn("errore: mancano gli argomenti COMANDO", err)

    def test_unknown_command(self) -> None:
        code, _, err = run_cli("stampa")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("valore 'stampa' non ammesso", err)

    def test_missing_output(self) -> None:
        code, _, err = run_cli("canon", "p.regodoc")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("mancano gli argomenti -o/--output", err)

    def test_bad_format(self) -> None:
        code, _, err = run_cli("build", "p.regodoc", "-o", "x", "--format", "docx")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("valore 'docx' non ammesso per --format", err)

    def test_unrecognized_argument(self) -> None:
        code, _, err = run_cli("info", "--colore")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("argomenti non riconosciuti: --colore", err)

    def test_no_english_in_errors(self) -> None:
        for argv in [(), ("stampa",), ("canon", "p"), ("info", "--x"), ("build", "p", "-o")]:
            with self.subTest(argv):
                _, _, err = run_cli(*argv)
                for word in ("usage", "error:", "required", "invalid", "argument"):
                    self.assertNotIn(word, err)

    def test_help_is_italian(self) -> None:
        code, out, _ = run_cli("--help")
        self.assertEqual(code, ExitCode.OK)
        self.assertIn("uso: regodoc", out)
        self.assertIn("opzioni", out)
        self.assertIn("mostra questo aiuto", out)

    def test_unknown_argparse_message_is_wrapped(self) -> None:
        self.assertEqual(
            cli.translate_argparse_message("something new"),
            "riga di comando non valida («something new»)",
        )


class InternalErrorTest(unittest.TestCase):
    def test_no_raw_exception(self) -> None:
        original = declaration.describe

        def broken() -> dict[str, object]:
            raise RuntimeError("guasto simulato")

        declaration.describe = broken
        try:
            code, out, err = run_cli("info")
        finally:
            declaration.describe = original
        self.assertEqual(code, ExitCode.INTERNAL)
        self.assertEqual(out, "")
        self.assertIn("errore interno del motore (RuntimeError)", err)
        self.assertNotIn("Traceback", err)


class ModuleEntryPointTest(unittest.TestCase):
    def test_python_dash_m(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "regodoc", "info"],
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["engine"], "regodoc")


if __name__ == "__main__":
    unittest.main()
