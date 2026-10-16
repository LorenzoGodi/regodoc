"""Il pacchetto Python di regodoc: metadati, licenza e strumenti di costruzione."""

import importlib.util
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
REQUIREMENTS = ROOT / "tools" / "requirements"


def pinned(path: Path) -> dict[str, tuple[str, list[str]]]:
    """I requisiti di un file con le impronte: nome, versione esatta e impronte."""
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    found = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()  # noqa: PLW2901
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+)((?:\s+--hash=sha256:[0-9a-f]{64})+)", line)
        assert match, f"{path.name}: requisito senza versione esatta o senza impronte: {line}"
        found[match.group(1)] = (match.group(2), re.findall(r"[0-9a-f]{64}", match.group(3)))
    return found


class LicenseTest(unittest.TestCase):
    def test_license_is_an_spdx_expression(self) -> None:
        # La forma nuova (PEP 639): il wheel porta License-Expression, e nessun
        # classificatore di licenza, che la forma nuova vieta.
        project = PYPROJECT["project"]
        self.assertEqual(project["license"], "Apache-2.0")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertFalse([c for c in project["classifiers"] if c.startswith("License ::")])

    def test_build_backend_supports_it(self) -> None:
        self.assertEqual(PYPROJECT["build-system"]["requires"], ["flit_core>=3.12,<4"])


class PinnedToolsTest(unittest.TestCase):
    def test_every_pip_install_in_the_ci_requires_hashes(self) -> None:
        installs = [line for line in CI.splitlines() if "pip install" in line]
        self.assertGreaterEqual(len(installs), 3)
        for line in installs:
            with self.subTest(line.strip()):
                self.assertIn("--require-hashes", line)
                self.assertIn("--no-deps", line)

    def test_build_backend_is_pinned_within_the_declared_range(self) -> None:
        version, hashes = pinned(REQUIREMENTS / "build.txt")["flit_core"]
        major, minor = (int(n) for n in version.split(".")[:2])
        self.assertEqual(major, 3)
        self.assertGreaterEqual(minor, 12)
        self.assertTrue(hashes)

    def test_ruff_matches_the_ci_version(self) -> None:
        version = re.search(r'RUFF_VERSION: "([^"]+)"', CI)
        assert version is not None
        self.assertEqual(pinned(REQUIREMENTS / "lint.txt")["ruff"][0], version.group(1))


@unittest.skipUnless(importlib.util.find_spec("flit_core"), "flit_core non installato")
class ReproducibleBuildTest(unittest.TestCase):
    """La costruzione che fa il job del pacchetto nella CI, dove flit_core c'è sempre."""

    def test_two_builds_give_the_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tool = str(ROOT / "tools" / "build_release.py")
            result = subprocess.run(
                [sys.executable, tool, "--out", folder, "--check"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            sums = (Path(folder) / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(sums), 2)
        self.assertTrue(sums[0].endswith("-py3-none-any.whl"))
        self.assertTrue(sums[1].endswith(".tar.gz"))


if __name__ == "__main__":
    unittest.main()
