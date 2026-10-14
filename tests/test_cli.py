"""Prove del comando ``regodoc``: sottocomandi, codici d'uscita e messaggi in italiano."""

import contextlib
import io
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.parsers.expat
import zlib
from pathlib import Path
from unittest import mock

from regodoc import __version__, cli, declaration
from regodoc.cli import ExitCode
from tests.support import EXAMPLE, build_zip, example_files


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
            "canon": ("canon", "p.regodoc", "-o", "q.regodoc"),
            "build": ("build", "p.regodoc", "-o", "p.pdf"),
            "upgrade": ("upgrade", "p.regodoc", "-o", "q.regodoc"),
        }
        for name, argv in cases.items():
            with self.subTest(name):
                code, out, err = run_cli(*argv)
                self.assertEqual(code, ExitCode.ENVIRONMENT)
                self.assertEqual(out, "")
                self.assertIn(f"il comando «{name}» non è ancora disponibile", err)
                self.assertNotIn("lotto", err)

    def test_strict_is_accepted(self) -> None:
        code, _, _ = run_cli("canon", "p.regodoc", "-o", "q", "--strict")
        self.assertEqual(code, ExitCode.ENVIRONMENT)

    def test_draft_json_report(self) -> None:
        code, out, err = run_cli("canon", "p.regodoc", "-o", "q", "--json")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertFalse(report["ok"])
        self.assertEqual(report["exit_code"], 3)
        self.assertEqual(report["command"], "canon")
        self.assertEqual(report["errors"][0]["code"], "regodoc.not_implemented")


class ValidateCommandTest(unittest.TestCase):
    EXAMPLE = str(Path(__file__).resolve().parent.parent / "examples" / "colle-rovere")

    def test_example_is_valid(self) -> None:
        code, out, err = run_cli("validate", self.EXAMPLE)
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(out, "")
        self.assertIn("pacchetto valido (0 errori, 0 avvisi)", err)

    def test_json_report(self) -> None:
        code, out, _ = run_cli("validate", self.EXAMPLE, "--json")
        self.assertEqual(code, ExitCode.OK)
        report = json.loads(out)
        self.assertTrue(report["ok"])
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["grammar"], "rego/1")
        self.assertEqual(report["engine"]["version"], __version__)

    def test_refused_and_strict(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "pkg"
            shutil.copytree(self.EXAMPLE, target)
            variables = target / "variables.toml"
            variables.write_text(variables.read_text() + "spare = { number = 1 }\n")
            code, _, err = run_cli("validate", str(target))
            self.assertEqual(code, ExitCode.OK)
            self.assertIn("avviso: variables.toml:9  regodoc.toml.unused_variable", err)
            code, out, _ = run_cli("validate", str(target), "--strict", "--json")
            self.assertEqual(code, ExitCode.REFUSED)
            self.assertFalse(json.loads(out)["ok"])
            (target / "structure.toml").write_text("[[part]\n")
            code, _, err = run_cli("validate", str(target))
            self.assertEqual(code, ExitCode.REFUSED)
            self.assertIn("errore: structure.toml:1", err)

    def test_json_report_for_every_exit_code(self) -> None:
        cases = [
            (("validate", "/nessun/percorso", "--json"), ExitCode.USAGE, "regodoc.usage"),
            (("validate", self.EXAMPLE, "--json", "--colore"), ExitCode.USAGE, "regodoc.usage"),
            (("canon", "p", "-o", "q", "--json"), ExitCode.ENVIRONMENT, "regodoc.not_implemented"),
        ]
        for argv, exit_code, code in cases:
            with self.subTest(argv):
                result, out, _ = run_cli(*argv)
                self.assertEqual(result, exit_code)
                report = json.loads(out)
                self.assertEqual(report["exit_code"], exit_code)
                self.assertEqual(report["errors"][0]["code"], code)
                self.assertEqual(
                    report["limits_active"], {"time_seconds": None, "memory_bytes": None}
                )
        for error, exit_code, code in (
            (KeyboardInterrupt, ExitCode.INTERRUPTED, "regodoc.interrupted"),
            (RuntimeError("guasto"), ExitCode.INTERNAL, "regodoc.internal"),
            (OSError(28, "No space left on device"), ExitCode.ENVIRONMENT, "regodoc.environment"),
        ):
            with self.subTest(error), mock.patch("regodoc.cli.validate_package", side_effect=error):
                result, out, err = run_cli("validate", self.EXAMPLE, "--json")
                self.assertEqual(result, exit_code)
                report = json.loads(out)
                self.assertEqual(report["exit_code"], exit_code)
                self.assertEqual(report["errors"][0]["code"], code)
                self.assertNotIn("Traceback", err)

    def test_missing_package_is_a_usage_error(self) -> None:
        code, _, err = run_cli("validate", "/nessun/percorso.regodoc")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("non esiste", err)


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

    def test_abbreviations_are_refused(self) -> None:
        for argv in (("validate", str(EXAMPLE), "--stri"), ("validate", str(EXAMPLE), "--js")):
            with self.subTest(argv):
                code, out, _ = run_cli(*argv)
                self.assertEqual(code, ExitCode.USAGE)
                self.assertEqual(out, "")

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


class EnvironmentTest(unittest.TestCase):
    def test_closed_pipe_is_an_environment_error(self) -> None:
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "regodoc", "info"],
                stdout=write_end,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
        finally:
            os.close(write_end)
        self.assertEqual(result.returncode, ExitCode.ENVIRONMENT)
        stderr = result.stderr.decode("utf-8")
        self.assertIn("errore d'ambiente", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("errore interno", stderr)

    def test_interrupt(self) -> None:
        with mock.patch.object(declaration, "describe", side_effect=KeyboardInterrupt):
            code, out, err = run_cli("info")
        self.assertEqual(code, ExitCode.INTERRUPTED)
        self.assertEqual(out, "")
        self.assertIn("regodoc: interrotto", err)


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


def heavy_package() -> bytes:
    """Un pacchetto lecito nell'involucro ma che chiede molta memoria per essere letto."""
    files = example_files()
    structure = files["structure.toml"].decode()
    generator = random.Random(1)  # noqa: S311 - prova ripetibile
    words = "abcdefghilmnoprstuv"

    def paragraph() -> str:
        return " ".join("".join(generator.choice(words) for _ in range(7)) for _ in range(12))

    body = "".join(f"<p>{paragraph()}</p>\n" for _ in range(3800))
    for number in range(40):
        structure += f'\n[[part]]\nid = "p{number}"\ntitle = "P{number}"\naccent = "gray"\n'
        files[f"parts/p{number}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<part>\n'
            f'<section id="s{number}"><title>T</title>\n{body}</section>\n</part>\n'
        ).encode()
    files["structure.toml"] = structure.encode()
    return build_zip(files)


class MemoryTest(unittest.TestCase):
    def test_memory_error_is_an_environment_error(self) -> None:
        with mock.patch("regodoc.cli.validate_package", side_effect=MemoryError):
            code, out, err = run_cli("validate", str(EXAMPLE), "--json")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        report = json.loads(out)
        self.assertEqual(report["errors"][0]["code"], "regodoc.limit.memory")
        self.assertIn("non ritentare", report["errors"][0]["message"])
        self.assertNotIn("Traceback", err)

    @unittest.skipUnless(sys.platform == "linux", "RLIMIT_AS vale come limite solo su Linux")
    def test_address_space_limit(self) -> None:
        limit = 40 * 1024 * 1024

        def limited() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "p.regodoc"
            package.write_bytes(heavy_package())
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", _ENTRY, str(root / "src"), str(package)],
                capture_output=True,
                check=False,
                timeout=120,
                preexec_fn=limited,
                cwd=folder,
            )
        self.assertEqual(result.returncode, ExitCode.ENVIRONMENT, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([e["code"] for e in report["errors"]], ["regodoc.limit.memory"])

    def test_memory_errors_inside_expat_and_zlib(self) -> None:
        # Expat e zlib segnalano la memoria finita con un errore proprio: non deve diventare
        # un errore del pacchetto.
        no_memory = xml.parsers.expat.ExpatError("out of memory")
        no_memory.code = xml.parsers.expat.errors.codes[
            xml.parsers.expat.errors.XML_ERROR_NO_MEMORY
        ]
        no_memory.lineno, no_memory.offset = 1, 0
        broken = mock.Mock()
        broken.return_value.decompress.side_effect = zlib.error("Error -4 while decompressing data")
        broken.return_value.eof = False
        broken.return_value.unconsumed_tail = b""
        cases = (
            ("regodoc.parts._TreeBuilder.parse", {"side_effect": no_memory}, str(EXAMPLE)),
            ("regodoc.source.zlib.decompressobj", {"new": broken}, None),
        )
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "p.regodoc"
            archive.write_bytes(build_zip(example_files()))
            for target, options, package in cases:
                with self.subTest(target):
                    with mock.patch(target, **options):
                        code, out, _ = run_cli("validate", package or str(archive), "--json")
                    self.assertEqual(code, ExitCode.ENVIRONMENT)
                    report = json.loads(out)
                    self.assertEqual(report["errors"][0]["code"], "regodoc.limit.memory")

    def test_other_zlib_errors_stay_corrupt(self) -> None:
        broken = mock.Mock()
        broken.return_value.decompress.side_effect = zlib.error("Error -3 while decompressing")
        broken.return_value.eof = False
        broken.return_value.unconsumed_tail = b""
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "p.regodoc"
            archive.write_bytes(build_zip(example_files()))
            with mock.patch("regodoc.source.zlib.decompressobj", broken):
                code, out, _ = run_cli("validate", str(archive), "--json")
        self.assertEqual(code, ExitCode.REFUSED)
        self.assertEqual(json.loads(out)["errors"][0]["code"], "regodoc.archive.corrupt")


# Avvia il motore da src/ anche con -I, che esclude PYTHONPATH.
_ENTRY = (
    "import sys; sys.path.insert(0, sys.argv[1]); from regodoc.cli import main; "
    "sys.exit(main(['validate', sys.argv[2], '--json']))"
)


class NoCommandTest(unittest.TestCase):
    def test_json_without_command(self) -> None:
        code, out, _ = run_cli("--json")
        self.assertEqual(code, ExitCode.USAGE)
        report = json.loads(out)
        self.assertIsNone(report["command"])
        self.assertEqual(report["exit_code"], ExitCode.USAGE)
        self.assertEqual(report["errors"][0]["code"], "regodoc.usage")


if __name__ == "__main__":
    unittest.main()
