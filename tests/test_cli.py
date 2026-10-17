"""Prove del comando ``regodoc``: sottocomandi, codici d'uscita e messaggi in italiano."""

import contextlib
import io
import json
import os
import random
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import xml.parsers.expat
import zlib
from pathlib import Path
from unittest import mock

from regodoc import __version__, cli, declaration
from regodoc.cli import ExitCode
from tests.support import ENGINE, EXAMPLE, _text, build_zip, example_files, run_cli


class InfoTest(unittest.TestCase):
    def test_info_is_the_declaration(self) -> None:
        code, out, _ = run_cli("info")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(json.loads(out), declaration.describe())

    def test_version(self) -> None:
        code, out, _ = run_cli("--version")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(out.strip(), f"regodoc {__version__}")


class NoDraftTest(unittest.TestCase):
    def test_every_command_is_ready(self) -> None:
        commands = declaration.describe()["commands"]
        self.assertEqual(set(commands.values()), {"ready"})  # type: ignore[union-attr]


class DraftCommandTest(unittest.TestCase):
    """Un comando dichiarato «draft» risponde che non è ancora disponibile (contratto, §5).
    In questa versione nessuno lo è: le prove lo dichiarano tale per la loro durata."""

    def setUp(self) -> None:
        commands = dict(declaration.COMMANDS, upgrade="draft")
        patch = mock.patch.object(declaration, "COMMANDS", commands)
        patch.start()
        self.addCleanup(patch.stop)

    def test_draft_commands_say_so(self) -> None:
        code, out, err = run_cli("upgrade", "p.regodoc", "-o", "q.regodoc")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assertEqual(out, "")
        self.assertIn("il comando «upgrade» non è ancora disponibile", err)

    def test_draft_json_report(self) -> None:
        code, out, err = run_cli("upgrade", "p.regodoc", "-o", "q", "--json", "--strict")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertFalse(report["ok"])
        self.assertEqual(report["command"], "upgrade")
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
        memory = declaration.RESOURCES["memory_bytes"] if sys.platform == "linux" else None
        applied = {"time_seconds": 30, "memory_bytes": memory}
        cases = [
            (("validate", "/nessun/percorso", "--json"), ExitCode.USAGE, "regodoc.usage", applied),
            # La riga di comando sbagliata si ferma prima dei limiti: null.
            (
                ("validate", self.EXAMPLE, "--json", "--colore"),
                ExitCode.USAGE,
                "regodoc.usage",
                {"time_seconds": None, "memory_bytes": None},
            ),
            (
                ("canon", "/nessun/percorso", "-o", "q", "--json"),
                ExitCode.USAGE,
                "regodoc.usage",
                {**applied, "time_seconds": 60},
            ),
        ]
        for argv, exit_code, code, active in cases:
            with self.subTest(argv):
                result, out, _ = run_cli(*argv)
                self.assertEqual(result, exit_code)
                report = json.loads(out)
                self.assertEqual(report["exit_code"], exit_code)
                self.assertEqual(report["errors"][0]["code"], code)
                self.assertEqual(report["limits_active"], active)
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
        # Il limite è relativo allo spazio che l'interprete occupa già dopo aver caricato il
        # motore: un numero fisso dipende dalla versione di Python (con 3.14 l'avvio ne
        # chiede di più) e non metterebbe alla prova la lettura del pacchetto.
        probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import regodoc.cli; "
                "print(next(l.split()[1] for l in open('/proc/self/status') "
                "if l.startswith('VmPeak')))",
                str(ENGINE),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )
        limit = int(probe.stdout) * 1024 + 32 * 1024 * 1024

        def limited() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "p.regodoc"
            package.write_bytes(heavy_package())
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", _ENTRY, str(ENGINE), str(package)],
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


# Avvia il motore da ENGINE anche con -I, che esclude PYTHONPATH.
_ENTRY = (
    "import sys; sys.path.insert(0, sys.argv[1]); from regodoc.cli import main; "
    "sys.exit(main(['validate', sys.argv[2], '--json']))"
)


def slow(_path: object) -> None:
    time.sleep(10)


class TimeLimitTest(unittest.TestCase):
    def test_time_limit_stops_the_command(self) -> None:
        started = time.monotonic()
        with mock.patch("regodoc.cli.validate_package", side_effect=slow):
            code, out, err = run_cli("--max-seconds", "1", "validate", str(EXAMPLE), "--json")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        report = json.loads(out)
        self.assertEqual(report["errors"][0]["code"], "regodoc.limit.time")
        self.assertIn("non ritentare", report["errors"][0]["message"])
        self.assertEqual(report["limits_active"]["time_seconds"], 1)
        self.assertNotIn("Traceback", err)

    def test_max_seconds_only_lowers(self) -> None:
        declared = declaration.RESOURCES["time_seconds"]["validate"]
        for value, expected in (("5", 5), (str(declared + 100), declared)):
            with self.subTest(value):
                code, out, _ = run_cli("--max-seconds", value, "validate", str(EXAMPLE), "--json")
                self.assertEqual(code, ExitCode.OK)
                self.assertEqual(json.loads(out)["limits_active"]["time_seconds"], expected)

    def test_max_seconds_must_be_positive(self) -> None:
        for value in ("0", "-3"):
            with self.subTest(value):
                code, out, _ = run_cli("--max-seconds", value, "validate", str(EXAMPLE), "--json")
                self.assertEqual(code, ExitCode.USAGE)
                self.assertEqual(json.loads(out)["errors"][0]["code"], "regodoc.usage")

    def test_limits_are_restored_after_the_command(self) -> None:
        before = signal.getsignal(signal.SIGALRM)
        memory = resource.getrlimit(resource.RLIMIT_AS)
        run_cli("validate", str(EXAMPLE), "--json")
        self.assertIs(signal.getsignal(signal.SIGALRM), before)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
        self.assertEqual(resource.getrlimit(resource.RLIMIT_AS), memory)

    def test_report_is_written_with_the_timer_stopped(self) -> None:
        # Una scrittura lenta, più lunga del tempo concesso: se il timer fosse ancora armato,
        # scadrebbe a metà e stdout avrebbe un rapporto tronco seguito da un altro.
        class SlowBuffer(io.BytesIO):
            def write(self, data: bytes) -> int:  # type: ignore[override]
                time.sleep(1.3)
                return super().write(data)

        out = io.TextIOWrapper(SlowBuffer(), "utf-8")
        err = io.TextIOWrapper(io.BytesIO(), "utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--max-seconds", "1", "validate", str(EXAMPLE), "--json"])
        self.assertEqual(code, ExitCode.OK)
        report = json.loads(_text(out))
        self.assertEqual(report["exit_code"], 0)

    def test_without_posix_timers_the_time_is_null(self) -> None:
        with mock.patch("regodoc.limits.time_enforced", return_value=False):
            for argv in (("info", "--json"), ("validate", str(EXAMPLE), "--json")):
                with self.subTest(argv):
                    code, _out, _ = run_cli(*argv)
                    self.assertEqual(code, ExitCode.OK)
            report = json.loads(run_cli("validate", str(EXAMPLE), "--json")[1])
        self.assertIsNone(report["limits_active"]["time_seconds"])

    def test_a_timer_of_the_caller_survives(self) -> None:
        fired: list[int] = []
        previous = signal.signal(signal.SIGALRM, lambda *_: fired.append(1))
        try:
            signal.setitimer(signal.ITIMER_REAL, 100)
            run_cli("validate", str(EXAMPLE), "--json")
            remaining, _ = signal.getitimer(signal.ITIMER_REAL)
            self.assertGreater(remaining, 90)
            self.assertLessEqual(remaining, 100)
            self.assertEqual(fired, [])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    @unittest.skipUnless(sys.platform == "linux", "il limite di memoria vale solo su Linux")
    def test_memory_limit_is_reported_and_kept_lower(self) -> None:
        code, out, _ = run_cli("validate", str(EXAMPLE), "--json")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(
            json.loads(out)["limits_active"]["memory_bytes"], declaration.RESOURCES["memory_bytes"]
        )

    @unittest.skipUnless(sys.platform == "linux", "il limite di memoria vale solo su Linux")
    def test_engine_limit_stops_a_heavy_package(self) -> None:
        # Senza limiti imposti da chi chiama: il motore applica il proprio, abbassato qui a 40
        # MiB solo per la prova, e il pacchetto pesante lo supera.
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "p.regodoc"
            package.write_bytes(heavy_package())
            entry = (
                "import sys; sys.path.insert(0, sys.argv[1]); from types import MappingProxyType; "
                "from regodoc import declaration as d; "
                "d.RESOURCES = MappingProxyType({**d.RESOURCES, 'memory_bytes': 40 * 2**20}); "
                "import regodoc.limits as l; l.RESOURCES = d.RESOURCES; "
                "from regodoc.cli import main; sys.exit(main(['validate', sys.argv[2], '--json']))"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", entry, str(ENGINE), str(package)],
                capture_output=True,
                check=False,
                timeout=120,
                cwd=folder,
            )
        self.assertEqual(result.returncode, ExitCode.ENVIRONMENT, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([e["code"] for e in report["errors"]], ["regodoc.limit.memory"])
        self.assertEqual(report["limits_active"]["memory_bytes"], 40 * 2**20)


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
