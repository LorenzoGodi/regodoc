"""Il pacchetto Python di regodoc: metadati, licenza e strumenti di costruzione."""

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests.support import ENGINE

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
REQUIREMENTS = ROOT / "tools" / "requirements"
PIP_INSTALL = re.compile(r"\bpip3?\s+install\b")
# Quante impronte ha ciascun requisito fissato: una per file pubblicato su PyPI per quella
# versione. Cambiano solo con la versione, e vanno ricontate allora.
EXPECTED_HASHES = {"ruff": 18, "flit_core": 2}


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
    def test_every_pip_install_in_the_workflows_requires_hashes(self) -> None:
        installs = [
            (path.name, line.strip())
            for path in sorted(WORKFLOWS.glob("*.y*ml"))
            for line in path.read_text(encoding="utf-8").replace("\\\n", " ").splitlines()
            if PIP_INSTALL.search(line)
        ]
        self.assertGreaterEqual(len(installs), 3)
        for name, line in installs:
            with self.subTest(f"{name}: {line}"):
                self.assertRegex(line, r"(?<!\S)--require-hashes(?!\S)")
                self.assertRegex(line, r"(?<!\S)--no-deps(?!\S)")

    def test_pip_install_pattern_catches_the_variants(self) -> None:
        for line in [
            "pip install x",
            "pip3 install x",
            "pip  install x",
            "python -m pip\tinstall x",
            "uv pip install x",
        ]:
            with self.subTest(line):
                self.assertRegex(line, PIP_INSTALL)
        self.assertNotRegex("pip list --format=freeze", PIP_INSTALL)

    def test_every_locked_requirement_has_all_its_hashes(self) -> None:
        # Le impronte di tutti i file pubblicati di ciascuna versione: se ne manca una, pip
        # rifiuta il file che la impronta tolta copriva, e solo su qualche macchina.
        found = {
            name: hashes
            for path in sorted(REQUIREMENTS.glob("*.txt"))
            for name, (_, hashes) in pinned(path).items()
        }
        self.assertEqual({name: len(hashes) for name, hashes in found.items()}, EXPECTED_HASHES)
        for name, hashes in found.items():
            with self.subTest(name):
                self.assertEqual(len(set(hashes)), len(hashes))

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

    def build(self, *extra: str) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            tool = str(ROOT / "tools" / "build_release.py")
            result = subprocess.run(
                [sys.executable, tool, "--out", folder, "--check", *extra],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return (Path(folder) / "SHA256SUMS").read_text(encoding="utf-8").splitlines()

    def test_two_builds_give_the_same_bytes(self) -> None:
        sums = self.build()
        self.assertEqual(len(sums), 2)
        self.assertTrue(sums[0].endswith("-py3-none-any.whl"))
        self.assertTrue(sums[1].endswith(".tar.gz"))

    def test_untracked_files_stay_out(self) -> None:
        # La costruzione parte dai file del commit: un file non tracciato sotto tests/, che
        # l'archivio sorgente includerebbe, non cambia le impronte.
        before = self.build()
        stray = ROOT / "tests" / "zz_non_tracciato.txt"
        stray.write_text("non committato\n", encoding="utf-8")
        try:
            after = self.build()
        finally:
            stray.unlink()
        self.assertEqual(after, before)

    def test_commit_head_is_the_default(self) -> None:
        self.assertEqual(self.build("--commit", "HEAD"), self.build())

    def test_the_release_commits_give_the_announced_sums(self) -> None:
        # Le impronte annunciate in docs/release.md, ricostruite dai file del commit del
        # rilascio con lo strumento di oggi: servono la storia del repository e flit_core.
        for commit, sums in released():
            with self.subTest(commit):
                present = subprocess.run(
                    ["git", "cat-file", "-e", f"{commit}^{{commit}}"],  # noqa: S607 - git dal PATH
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                )
                if present.returncode != 0:
                    self.skipTest(f"il commit {commit} non è nel checkout")
                self.assertEqual(self.build("--commit", commit), sums)


def released() -> list[tuple[str, list[str]]]:
    """I rilasci della tabella di docs/release.md: commit e righe di ``SHA256SUMS``."""
    text = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+\.\d+\.\d+) \| `([0-9a-f]{7,40})` \|", text, re.M)
    found = []
    for version, commit in rows:
        sums = re.findall(rf"^[0-9a-f]{{64}}  regodoc-{re.escape(version)}[-.]\S+$", text, re.M)
        found.append((commit, sums))
    return found


class ReleaseTableTest(unittest.TestCase):
    def test_every_release_has_its_two_sums(self) -> None:
        releases = released()
        self.assertTrue(releases)
        for commit, sums in releases:
            with self.subTest(commit):
                self.assertEqual(len(sums), 2)
                self.assertTrue(sums[0].endswith("-py3-none-any.whl"))
                self.assertTrue(sums[1].endswith(".tar.gz"))


def engine_files(folder: Path) -> dict[str, bytes]:
    """I file del motore sotto ``folder``, senza le cache dell'interprete."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


@unittest.skipUnless(
    os.environ.get("REGODOC_TEST_INSTALLED") == "1", "le prove girano sul sorgente"
)
class InstalledEngineTest(unittest.TestCase):
    """Con REGODOC_TEST_INSTALLED=1 la CI lancia le prove contro il wheel installato: il motore
    importato deve essere quello, e portare tutti i file di src/regodoc, identici."""

    def test_the_engine_comes_from_the_installation(self) -> None:
        self.assertNotEqual(ENGINE, ROOT / "src")
        self.assertEqual(ENGINE.name, "site-packages")

    def test_the_wheel_carries_every_engine_file(self) -> None:
        installed = engine_files(ENGINE / "regodoc")
        source = engine_files(ROOT / "src" / "regodoc")
        self.assertEqual(sorted(installed), sorted(source))
        for name, data in source.items():
            with self.subTest(name):
                self.assertEqual(installed[name], data)


if __name__ == "__main__":
    unittest.main()
