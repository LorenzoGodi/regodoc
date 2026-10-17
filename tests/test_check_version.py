"""Prove di tools/check_version.py, la regola della versione dopo un rilascio."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from regodoc import __version__

_PATH = Path(__file__).resolve().parent.parent / "tools" / "check_version.py"
_SPEC = importlib.util.spec_from_file_location("check_version", _PATH)
assert _SPEC and _SPEC.loader
version = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(version)


class ProblemsTest(unittest.TestCase):
    def test_released_version_must_rise_when_the_engine_changes(self) -> None:
        self.assertEqual(version.problems("0.1.0", "0.1.0", engine_changed=False), [])
        found = version.problems("0.1.0", "0.1.0", engine_changed=True)
        self.assertEqual(len(found), 1)
        self.assertIn("0.1.1.dev0", found[0])
        self.assertEqual(version.problems("0.1.0", "0.1.1.dev0", engine_changed=True), [])
        self.assertEqual(version.problems("0.1.0", "0.2.0.dev0", engine_changed=True), [])
        self.assertEqual(version.problems("0.1.0", "0.1.1", engine_changed=True), [])

    def test_a_dev_version_may_stay(self) -> None:
        self.assertEqual(version.problems("0.1.1.dev0", "0.1.1.dev0", engine_changed=True), [])
        # Il commit del rilascio toglie .dev.
        self.assertEqual(version.problems("0.1.1.dev0", "0.1.1", engine_changed=True), [])

    def test_the_version_never_goes_down(self) -> None:
        for base, head in [("0.1.0", "0.1.0.dev0"), ("0.2.0", "0.1.9"), ("0.1.1", "0.1.1.dev3")]:
            with self.subTest(f"{base} → {head}"):
                self.assertIn("scende", version.problems(base, head, engine_changed=False)[0])

    def test_numbers_compare_as_numbers(self) -> None:
        self.assertEqual(version.problems("0.9.0", "0.10.0.dev0", engine_changed=True), [])

    def test_form(self) -> None:
        for head in ["0.1", "0.1.0rc1", "v0.1.0", "0.1.0.dev", ""]:
            with self.subTest(head):
                self.assertIn("forma", version.problems("0.1.0", head, engine_changed=True)[0])

    def test_the_engine_version_has_the_form(self) -> None:
        self.assertEqual(version.problems(__version__, __version__, engine_changed=False), [])


class EngineChangedTest(unittest.TestCase):
    """Su un repository git temporaneo, con un commit di base e uno sopra."""

    def repository(self, change: dict[str, str]) -> bool:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args: str) -> None:
                subprocess.run(
                    [  # noqa: S607 - git dal PATH, come per l'igiene
                        "git",
                        "-c",
                        "user.name=prove",
                        "-c",
                        "user.email=prove@example.invalid",
                        "-c",
                        "commit.gpgsign=false",
                        *args,
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )

            files = {
                version.INIT: '"""Motore."""\n\n__version__ = "0.1.0"\n',
                "src/regodoc/cli.py": "x = 1\n",
                "docs/a.md": "a\n",
            }
            git("init", "-q")
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text, encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            git("tag", "base")
            for name, text in change.items():
                (root / name).write_text(text, encoding="utf-8")
            git("commit", "-q", "-a", "-m", "sopra")
            return version.engine_changed("base", root=root)

    def test_only_the_version_line(self) -> None:
        init = '"""Motore."""\n\n__version__ = "0.1.1.dev0"\n'
        self.assertFalse(self.repository({version.INIT: init}))

    def test_other_files_do_not_count(self) -> None:
        self.assertFalse(self.repository({"docs/a.md": "b\n"}))

    def test_an_engine_file(self) -> None:
        self.assertTrue(self.repository({"src/regodoc/cli.py": "x = 2\n"}))

    def test_the_rest_of_init(self) -> None:
        init = '"""Motore, cambiato."""\n\n__version__ = "0.1.0"\n'
        self.assertTrue(self.repository({version.INIT: init}))


if __name__ == "__main__":
    unittest.main()
