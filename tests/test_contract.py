"""Prove di coerenza fra il contratto (docs/contract.md) e il comando."""

import hashlib
import json
import os
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from regodoc import declaration
from regodoc.cli import ExitCode
from regodoc.diagnostics import Collector, Diagnostic, Severity
from regodoc.validate import files_digest
from tests.support import EXAMPLE, build_zip, example_files
from tests.test_cli import run_cli

CONTRACT = (Path(__file__).resolve().parent.parent / "docs" / "contract.md").read_text(
    encoding="utf-8"
)


def section(number: str) -> str:
    """Il testo di un paragrafo («7») o sottoparagrafo («4.1») del contratto, fino al titolo
    successivo dello stesso livello o di un livello più alto."""
    if "." in number:
        start = CONTRACT.index(f"\n### {number} ")
        ends = [CONTRACT.find(marker, start + 1) for marker in ("\n## ", "\n### ")]
    else:
        start = CONTRACT.index(f"\n## {number}. ")
        ends = [CONTRACT.find("\n## ", start + 1)]
    ends = [end for end in ends if end > 0]
    return CONTRACT[start : min(ends) if ends else len(CONTRACT)]


def flat(text: str) -> str:
    """Il testo con gli a capo e i rientri ridotti a uno spazio."""
    return " ".join(text.split())


def table_keys(text: str) -> list[str]:
    """Le chiavi nella prima colonna delle tabelle di un testo."""
    return re.findall(r"^\| `([a-z_]+)`", text, re.M)


def table_names(text: str) -> list[str]:
    """Tutti i nomi fra apici inversi nella prima colonna delle tabelle di un testo."""
    names = []
    for cell in re.findall(r"^\| ([^|]+) \|", text, re.M):
        names += re.findall(r"`([a-z_]+)`", cell)
    return names


def json_run(*argv: str) -> tuple[int, dict[str, object]]:
    code, out, _ = run_cli(*argv)
    return code, json.loads(out)


class DeclarationContractTest(unittest.TestCase):
    def test_info_keys_match_section_5(self) -> None:
        text = section("5").split("\n### 5.1 ")[0]
        self.assertEqual(sorted(declaration.describe()), sorted(table_keys(text)))

    def test_limit_keys_match_section_5_1(self) -> None:
        text = section("5.1")
        documented = set()
        for cell in re.findall(r"^\| (`[^|]+) \|", text, re.M):
            family = re.match(r"`(envelope|content)\.", cell)
            assert family is not None, cell
            for name in re.findall(r"`(?:envelope\.|content\.)?([a-z_]+)`", cell):
                documented.add(f"{family.group(1)}.{name}")
        declared = {f"envelope.{k}" for k in declaration.ENVELOPE_LIMITS} | {
            f"content.{k}" for k in declaration.CONTENT_LIMITS
        }
        self.assertEqual(documented, declared)

    def test_capabilities_match_section_5_2(self) -> None:
        # Uguaglianza, non inclusione: una capacità documentata e non dichiarata farebbe
        # nascondere a Rego una funzione che il motore ha.
        documented = set()
        for cell in re.findall(r"^\| (`[^|]+) \|", section("5.2"), re.M):
            documented |= set(re.findall(r"`([a-z.]+)`", cell))
        self.assertEqual(documented, set(declaration.CAPABILITIES))

    def test_every_ready_command_has_its_capability(self) -> None:
        for command, state in declaration.COMMANDS.items():
            if command != "info" and state == "ready":
                with self.subTest(command):
                    self.assertTrue(
                        any(
                            c == command or c.startswith(f"{command}.")
                            for c in declaration.CAPABILITIES
                        )
                    )

    def test_exit_codes_match_section_7(self) -> None:
        documented = [int(n) for n in re.findall(r"^\| (\d+) \|", section("7"), re.M)]
        self.assertEqual(documented, [int(code) for code in ExitCode])

    def test_only_one_exit_code_table(self) -> None:
        root = Path(__file__).resolve().parent.parent
        for path in (root / "README.md", root / "docs" / "spec" / "rego-1.md"):
            with self.subTest(path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?m)^\| 130 \|")

    def test_theme_roles_and_hooks(self) -> None:
        example = re.search(r"```toml\n(name = \"demo\".*?)```", section("6.1"), re.S)
        assert example is not None
        theme = tomllib.loads(example.group(1))
        self.assertEqual(sorted(theme["palette"]), sorted(declaration.THEME_ROLES))
        for hook in declaration.THEME_HOOKS:
            self.assertIn(f"\\{hook}", section("6.3"))

    def test_resources_say_whether_they_are_enforced(self) -> None:
        self.assertIs(declaration.RESOURCES["enforced"], True)
        self.assertNotIn("limits.enforced", declaration.CAPABILITIES)

    def test_info_is_stable_json(self) -> None:
        code, out, _ = run_cli("info")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(
            out, json.dumps(json.loads(out), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

    def test_info_accepts_json(self) -> None:
        self.assertEqual(run_cli("info", "--json")[:2], run_cli("info")[:2])

    def test_tex_packages_are_sorted_and_unique(self) -> None:
        packages = list(declaration.TEX_PACKAGES)
        self.assertEqual(packages, sorted(set(packages)))

    def test_every_command_has_a_time_limit(self) -> None:
        self.assertEqual(set(declaration.RESOURCES["time_seconds"]), set(declaration.COMMANDS))

    def test_upgrade_decision_is_closed(self) -> None:
        text = flat(section("8"))
        self.assertNotIn("da confermare", CONTRACT)
        self.assertIn("**automatico al primo bisogno**", text)
        self.assertIn("origine «aggiornamento»", text)
        # Il bisogno si riconosce da ciò che il motore restituisce.
        self.assertIn("il cui `grammar`, nel rapporto (§4.2), è diverso da", text)
        self.assertIn("`info.grammars.current`", text)
        self.assertIn("dà gli stessi byte di `canon` senza opzioni", text)
        self.assertIn("conserva `document` e `base_version`", text)

    def test_action_table(self) -> None:
        text = section("4.4")
        actions = re.findall(
            r"^\| `(regodoc\.[a-z0-9_.]+)`(?:, `(regodoc\.[a-z0-9_.]+)`)? \|", text, re.M
        )
        codes = {code for pair in actions for code in pair if code}
        self.assertEqual(
            codes,
            {
                "regodoc.manifest.grammar_newer",
                "regodoc.manifest.grammar_old",
                "regodoc.grammar.upgraded",
                "regodoc.limit.time",
                "regodoc.limit.memory",
                "regodoc.not_implemented",
            },
        )
        self.assertNotIn("decide solo in base al codice d'uscita", CONTRACT)
        for family in ("grammar", "header", "theme", "tex"):
            self.assertIn(f"`regodoc.{family}.*`", text)

    def test_limits_are_enforced_by_the_engine(self) -> None:
        resources = declaration.describe()["resources"]
        self.assertIs(resources["enforced"], True)
        self.assertEqual(resources["memory_enforced_on"], ["linux"])
        text = flat(section("2"))
        self.assertIn("Con `enforced: true`, come in questa versione", text)
        self.assertIn("`RLIMIT_AS`", text)
        self.assertIn("`--max-seconds S` abbassa il tempo dichiarato", text)
        self.assertIn("codice 3 con `regodoc.limit.memory`", text)

    def test_theme_limits_are_declared(self) -> None:
        self.assertEqual(
            declaration.describe()["theme"]["limits"], {"files": 200, "bytes": 8 * 1024 * 1024}
        )
        self.assertIn("`info.theme.limits`", section("3"))

    def test_theme_package_check(self) -> None:
        text = flat(section("6.1"))
        # Il controllo vero è sul .fls, fuori da TeX; l'aggancio di LaTeX è solo un aiuto.
        self.assertIn("file `.fls` di `-recorder`", text)
        self.assertIn("ogni file `.sty` o `.cls`", text)
        self.assertIn("non una barriera", text)

    def test_build_identifies_the_tex_image(self) -> None:
        self.assertIn("`version_line`", section("4.3"))
        self.assertIn("`tex.version_line`", section("10"))

    def test_exit_codes_for_failed_compilation_and_missing_tex(self) -> None:
        text = section("7")
        for code in ("regodoc.theme.compile", "regodoc.tex.missing", "regodoc.limit.memory"):
            self.assertIn(f"`{code}`", text)

    def test_callers_compare_canonical_files(self) -> None:
        self.assertIn("**non quelle di `validate`**", flat(section("11")))
        self.assertIn("descrive **l'archivio d'uscita**", flat(section("4.2")))

    def test_generator_of_stored_pdfs(self) -> None:
        text = flat(section("11"))
        self.assertIn("`theme.sha256` o `tex.version_line` (§4.3)", text)

    def test_canon_keeps_the_manifest_values(self) -> None:
        self.assertIn("senza di loro restano i valori del manifesto d'ingresso", section("2"))
        text = flat(section("4.2"))
        self.assertIn("La chiave `files` del manifesto è sempre riscritta", text)
        self.assertIn("altrimenti quelli del manifesto d'ingresso", text)

    def test_report_edges(self) -> None:
        self.assertIn('vale `""` per un problema che non riguarda un file', flat(section("4.4")))
        for code in ("regodoc.limit.time", "regodoc.limit.memory"):
            self.assertIn(f"codice 3 e `{code}`", flat(section("2")))
        self.assertIn("senza un rapporto JSON valido", flat(section("4.1")))

    def test_residual_notes_of_the_amendment(self) -> None:
        self.assertIn("un `<link>` dentro un `<link>` è un elemento fuori posto", flat(CONTRACT))
        self.assertIn("**Timer di chi chiama.**", section("2"))
        self.assertIn("scatta quindi subito dopo la fine, non durante", flat(section("2")))
        self.assertIn("Il caso peggiore valido", flat(section("2")))
        self.assertIn("Se poi un errore ferma la lettura, il valore resta", flat(section("4.2")))

    def test_enforcement_is_not_a_capability(self) -> None:
        self.assertNotIn("limits.enforced", CONTRACT)

    def test_no_internal_codes_in_the_contract(self) -> None:
        self.assertNotRegex(CONTRACT, r"\b(?:DL|CP|CMP|MAC)-\d+|\bA\d{1,2}\b|\blotto\b|4ter")


MINIMAL = set(table_keys(section("4.1")))
PACKAGE = set(table_names(section("4.2"))) - {"grammar_in"}  # grammar_in: solo upgrade


class ReportContractTest(unittest.TestCase):
    def test_minimal_form_on_every_exit(self) -> None:
        cases = [
            ("validate", str(EXAMPLE), "--json"),
            ("validate", "/nessun/percorso", "--json"),
            ("validate", str(EXAMPLE), "--json", "--colore"),
            ("--contract", "99", "validate", str(EXAMPLE), "--json"),
            ("--contract", "99", "info", "--json"),
            ("info", "--json", "--colore"),
            ("canon", "p", "-o", "q", "--json"),
        ]
        for argv in cases:
            with self.subTest(argv):
                code, report = json_run(*argv)
                self.assertLessEqual(MINIMAL, set(report))
                self.assertEqual(report["exit_code"], code)
                self.assertEqual(report["ok"], code == 0)

    def test_validate_returns_the_package(self) -> None:
        code, report = json_run("validate", str(EXAMPLE), "--json")
        self.assertEqual(code, ExitCode.OK)
        self.assertLessEqual(MINIMAL | PACKAGE, set(report))
        self.assertIsNone(report["input"])  # una cartella
        self.assertEqual(report["grammar"], "rego/1")
        paths = [f["path"] for f in report["files"]]
        self.assertEqual(
            paths,
            [
                "structure.toml",
                "variables.toml",
                "parts/summary.xml",
                "parts/network.xml",
                "parts/backup.xml",
                "images/coverage.png",
            ],
        )
        for item in report["files"]:
            data = (EXAMPLE / item["path"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(item["bytes"], len(data))
        header = report["package_header"]
        self.assertEqual(header["title"], "Rinnovo della rete della Cantina Colle Rovere")
        self.assertEqual(header["date"], "2026-10-05")
        self.assertEqual(header["language"], "it")
        self.assertNotIn("header", report)

    def test_files_sha256_definition(self) -> None:
        _, report = json_run("validate", str(EXAMPLE), "--json")
        text = "".join(f"{f['sha256']} {f['bytes']} {f['path']}\n" for f in report["files"])
        self.assertEqual(report["files_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(report["files_sha256"], files_digest(report["files"]))

    def test_archive_and_folder_have_the_same_files_sha256(self) -> None:
        _, folder = json_run("validate", str(EXAMPLE), "--json")
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "p.regodoc"
            data = build_zip(example_files())
            archive.write_bytes(data)
            _, packed = json_run("validate", str(archive), "--json")
        self.assertEqual(packed["files_sha256"], folder["files_sha256"])
        self.assertEqual(packed["input"]["sha256"], hashlib.sha256(data).hexdigest())

    def test_manifest_fields_are_returned_only_when_well_formed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for manifest, document in (
                ('{"format": "regodoc", "grammar": "rego/1", "document": "doc-7"}', "doc-7"),
                ('{"format": "regodoc", "grammar": "rego/1", "document": "../x"}', None),
            ):
                files = {**example_files(), "manifest.json": manifest.encode()}
                archive = Path(tmp) / "p.regodoc"
                archive.write_bytes(build_zip(files))
                _, report = json_run("validate", str(archive), "--json")
                self.assertEqual(report["document"], document)

    def test_generator_is_returned_only_when_well_formed(self) -> None:
        good = {"engine": "regodoc", "version": "0.1.0"}
        cases = (
            (good, good),
            ({"engine": "regodoc"}, None),
            ({**good, "extra": "x"}, None),
            ({"engine": ["a"], "version": "1"}, None),
            ({"engine": "x" * 60000, "version": "1"}, None),
            ({"engine": "rego\ndoc", "version": "1"}, None),
            ({"engine": "rego\u202edoc", "version": "1"}, None),
            ("regodoc 0.1.0", None),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for generator, expected in cases:
                with self.subTest(generator=str(generator)[:40]):
                    manifest = {"format": "regodoc", "grammar": "rego/1", "generator": generator}
                    files = {**example_files(), "manifest.json": json.dumps(manifest).encode()}
                    archive = Path(tmp) / "p.regodoc"
                    archive.write_bytes(build_zip(files))
                    _, report = json_run("validate", str(archive), "--json")
                    self.assertEqual(report["generator"], expected)

    def test_archive_errors_do_not_name_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "tmp-8f3a1c.regodoc"
            archive.write_bytes(b"non un archivio")
            _, report = json_run("validate", str(archive), "--json")
        self.assertEqual(report["errors"][0]["code"], "regodoc.archive.invalid")
        self.assertEqual(report["errors"][0]["file"], "")

    def test_fifo_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "p.regodoc"
            os.mkfifo(fifo)
            code, report = json_run("validate", str(fifo), "--json")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertEqual(report["errors"][0]["code"], "regodoc.usage")


class MessageContractTest(unittest.TestCase):
    def test_package_strings_are_clipped(self) -> None:
        long = "x" * 1000
        diagnostic = Diagnostic(
            Severity.ERROR, "c", f"l'attributo «{long}» non è ammesso in <{long}>"
        )
        self.assertLessEqual(len(diagnostic.message), 500)
        self.assertNotIn("x" * 81, diagnostic.message)

    def test_info_severity_is_not_counted_by_strict(self) -> None:
        collector = Collector()
        collector.info("regodoc.theme.role_default", "ruolo dal tema neutro")
        self.assertEqual(collector.strict_warnings, [])
        self.assertEqual(len(collector.warnings), 1)
        self.assertFalse(collector.has_errors())


class VersionOneTest(unittest.TestCase):
    def test_contract_is_version_one(self) -> None:
        self.assertEqual(declaration.CONTRACT_VERSION, 1)
        self.assertEqual(declaration.CONTRACTS, (1,))
        self.assertIn(
            "Stato: **versione 1, approvata il 14/10/2026; emendata il 15/10/2026 prima del "
            "primo rilascio: §2.1 e §2.3 limiti applicati dal motore, §4.4 e §5.1 avvisi oltre "
            "il tetto dei problemi.**",
            " ".join(CONTRACT.split()),
        )
        self.assertNotIn("in approvazione", CONTRACT)
        self.assertIn("`--contract 0` esce con il codice 2", flat(section("9")))

    def test_draft_contract_is_not_served(self) -> None:
        code, _, err = run_cli("--contract", "0", "info")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("non supporta il contratto 0", err)

    def test_header_example_is_valid_for_version_one(self) -> None:
        example = re.search(r"```json\n(\{.*?\})\n```", section("3.2"), re.S)
        assert example is not None
        self.assertEqual(json.loads(example.group(1))["contract"], declaration.CONTRACT_VERSION)

    def test_grammar_in_is_in_the_table(self) -> None:
        self.assertIn("| `grammar_in` |", section("4.2"))
        self.assertNotIn("grammar_out", CONTRACT)

    def test_entry_errors_have_no_file(self) -> None:
        self.assertIn("anche per gli errori di una sola voce", flat(section("4.4")))


class ContractOptionTest(unittest.TestCase):
    def test_supported_contract(self) -> None:
        code, out, _ = run_cli("--contract", str(declaration.CONTRACT_VERSION), "info")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(json.loads(out)["contract"], declaration.CONTRACT_VERSION)

    def test_unsupported_contract(self) -> None:
        code, out, err = run_cli("--contract", "99", "info")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertEqual(out, "")
        self.assertIn("non supporta il contratto 99", err)

    def test_contract_must_be_an_integer(self) -> None:
        code, _, err = run_cli("--contract", "uno", "info")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertIn("--contract vuole un numero intero", err)


if __name__ == "__main__":
    unittest.main()
