"""Prove di coerenza fra il contratto (docs/contract.md) e il comando."""

import json
import re
import unittest
from pathlib import Path

from regodoc import declaration
from regodoc.cli import ExitCode
from tests.test_cli import run_cli

CONTRACT = (Path(__file__).resolve().parent.parent / "docs" / "contract.md").read_text(
    encoding="utf-8"
)


def section(number: str) -> str:
    """Il testo di un paragrafo del contratto, dal suo titolo al successivo."""
    start = CONTRACT.index(f"\n## {number}.")
    end = CONTRACT.find("\n## ", start + 1)
    return CONTRACT[start:end]


def table_keys(text: str) -> list[str]:
    """Le chiavi nella prima colonna delle tabelle di un paragrafo."""
    return re.findall(r"^\| `([a-z_]+)`", text, re.M)


class DeclarationContractTest(unittest.TestCase):
    def test_info_keys_match_section_5(self) -> None:
        self.assertEqual(sorted(declaration.describe()), sorted(table_keys(section("5"))))

    def test_exit_codes_match_section_7(self) -> None:
        documented = [int(n) for n in re.findall(r"^\| (\d+) \|", section("7"), re.M)]
        self.assertEqual(documented, [int(code) for code in ExitCode])

    def test_info_is_stable_json(self) -> None:
        code, out, _ = run_cli("info")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(
            out, json.dumps(json.loads(out), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )

    def test_tex_packages_are_sorted_and_unique(self) -> None:
        packages = list(declaration.TEX_PACKAGES)
        self.assertEqual(packages, sorted(set(packages)))

    def test_every_command_has_a_time_limit(self) -> None:
        self.assertEqual(set(declaration.RESOURCES["time_seconds"]), set(declaration.COMMANDS))


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
