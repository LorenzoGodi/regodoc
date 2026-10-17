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
# Un comando pip install: pip, pip3 o pip3.12, poi qualunque opzione, poi install, fino al
# primo separatore della shell. Si cerca sul comando normalizzato da run_commands.
PIP_INSTALL = re.compile(r"\bpip[\d.]*(?:\s+[^\s|;&]+)*?\s+install\b[^|;&\n]*")
_RUN_BLOCK = re.compile(r"^(\s*(?:-\s+)?)run:\s*([|>])[-+0-9]*\s*(?:#.*)?$")
_RUN_INLINE = re.compile(r"^(\s*(?:-\s+)?)run:\s*(\S.*)$")
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


BUILD_TESTS = "python -m unittest tests.test_packaging -v"
# Le forme di oggi di ogni comando semplice che nomina pip nei passi run: dei workflow e delle
# action composite. Una forma nuova, anche equivalente (${{ }}, virgolette, una variabile come
# $PIP, opzioni dentro $( )), fa cadere la prova: la si guarda e, se va bene, la si aggiunge qui.
CANONICAL_PIP = frozenset(
    {
        "python -m pip install --require-hashes --no-deps -r tools/requirements/lint.txt",
        "python -m pip install --require-hashes --no-deps -r tools/requirements/build.txt",
        '"$RUNNER_TEMP/venv/bin/python" -m pip install --require-hashes --no-deps'
        ' -r "$RUNNER_TEMP/pin.txt"',
        "/opt/regodoc/bin/python -m pip install --require-hashes --no-deps -r /tmp/pin.txt",
        '"$RUNNER_TEMP/venv/bin/python" -m pip list --format=freeze',
        "/opt/regodoc/bin/python -m pip list --format=freeze",
        "grep -v -E '^(pip|regodoc)=='",
    }
)
# Le shell ammesse per i passi run:; senza shell: il passo usa bash.
SHELLS = frozenset({"bash", "sh"})


def job_steps(text: str, job: str) -> list[str]:
    """I passi di un job di un workflow, uno per elemento, senza le righe di commento e senza
    i commenti in fondo alle righe."""
    found = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  \S|\Z)", text)
    assert found, job
    lines = [re.sub(r"(^|\s)#.*$", "", line).rstrip() for line in found.group(1).splitlines()]
    body = "\n".join(line for line in lines if line.strip())
    return [step for step in re.split(r"(?m)^(?=      - )", body) if step.startswith("      - ")]


def automation_files(names: list[str] | None = None) -> list[str]:
    """I file che la CI esegue: i workflow e le action composite del repository, fra quelli
    tracciati da git (o fra ``names``)."""
    if names is None:
        names = subprocess.run(
            ["git", "ls-files", "*.yml", "*.yaml"],  # noqa: S607 - git dal PATH
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    return sorted(
        name
        for name in names
        if name.startswith(".github/workflows/") or Path(name).name in {"action.yml", "action.yaml"}
    )


def run_commands(text: str) -> list[str]:
    """I comandi dei passi ``run:`` di un file YAML, come la shell li riceve: i blocchi ``>``
    piegati in una riga, i blocchi ``|`` riga per riga, il valore in linea così com'è."""
    lines = text.splitlines()
    commands = []
    for index, line in enumerate(lines):
        block = _RUN_BLOCK.match(line)
        inline = None if block else _RUN_INLINE.match(line)
        if not block and not inline:
            continue
        key = len((block or inline).group(1))  # type: ignore[union-attr]
        body = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= key:
                break
            body.append(following.strip())
        if inline:
            commands.append(" ".join([inline.group(2).strip("'\""), *filter(None, body)]))
        elif block.group(2) == ">":  # type: ignore[union-attr]
            commands.append(" ".join(filter(None, body)))
        else:
            commands.append("\n".join(body))
    return commands


def pip_installs(text: str) -> list[str]:
    """Le installazioni con pip nei passi ``run:``, con le righe continuate unite e senza i
    commenti della shell."""
    found = []
    for command in run_commands(text):
        joined = command.replace("\\\n", " ")
        bare = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in joined.splitlines())
        found.extend(match.group(0).strip() for match in PIP_INSTALL.finditer(bare))
    return found


def simple_commands(command: str) -> list[str]:
    """I comandi semplici di un comando della shell: divisi a ogni |, ;, &, a capo fuori dalle
    virgolette, e all'inizio e alla fine di ogni $( ), che apre un contesto di virgolette
    nuovo anche dentro le doppie."""
    pieces: list[str] = []
    current: list[str] = []
    quotes = [""]  # le virgolette aperte, una voce per ogni $( ) annidato

    def cut() -> None:
        pieces.append("".join(current).strip())
        current.clear()

    index = 0
    while index < len(command):
        char, quote = command[index], quotes[-1]
        if quote != "'" and command.startswith("$(", index):
            cut()
            quotes.append("")
            index += 2
            continue
        if char in "'\"" and quote in ("", char):
            quotes[-1] = "" if quote == char else char
        elif not quote and char == ")" and len(quotes) > 1:
            cut()
            quotes.pop()
            index += 1
            continue
        elif not quote and char in "|;&\n":
            cut()
            index += 1
            continue
        current.append(char)
        index += 1
    cut()
    return [piece for piece in pieces if piece]


def pip_uses(text: str) -> list[str]:
    """Ogni comando semplice dei passi run: che nomina pip, in qualunque forma."""
    found = []
    for command in run_commands(text):
        joined = command.replace("\\\n", " ")
        bare = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in joined.splitlines())
        found += [piece for piece in simple_commands(bare) if re.search("pip", piece, re.I)]
    return found


def shells(text: str) -> list[str]:
    """Le shell dichiarate con shell: nei passi."""
    return re.findall(r"(?m)^\s*(?:-\s+)?shell:\s*(\S+)", text)


def missing_options(command: str) -> list[str]:
    """Le opzioni obbligatorie che mancano a un'installazione con pip."""
    words = command.split()
    return [option for option in ("--require-hashes", "--no-deps") if option not in words]


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
            (name, command)
            for name in automation_files()
            for command in pip_installs((ROOT / name).read_text(encoding="utf-8"))
        ]
        self.assertGreaterEqual(len(installs), 3)
        for name, command in installs:
            with self.subTest(f"{name}: {command}"):
                self.assertEqual(missing_options(command), [])

    def test_every_pip_use_has_a_canonical_form(self) -> None:
        uses = 0
        for name in automation_files():
            text = (ROOT / name).read_text(encoding="utf-8")
            for piece in pip_uses(text):
                uses += 1
                with self.subTest(f"{name}: {piece}"):
                    self.assertIn(piece, CANONICAL_PIP)
            for shell in shells(text):
                with self.subTest(f"{name}: shell {shell}"):
                    self.assertIn(shell, SHELLS)
        self.assertGreaterEqual(uses, len(CANONICAL_PIP))

    def test_new_forms_fall_outside_the_list(self) -> None:
        cases = {
            "${{ }}": "python -m pip install --require-hashes --no-deps -r ${{ env.R }}",
            "virgolette": '"pip" install --require-hashes --no-deps -r tools/requirements/lint.txt',
            "variabile": "$PIP install --require-hashes --no-deps -r tools/requirements/lint.txt",
            "$( )": "python -m pip install $(cat opzioni) -r tools/requirements/lint.txt",
            "maiuscole": "python -m PIP install -r tools/requirements/lint.txt",
        }
        for case, command in cases.items():
            with self.subTest(case):
                uses = pip_uses(f"steps:\n  - run: |\n      {command}\n")
                self.assertTrue(uses)
                self.assertTrue([use for use in uses if use not in CANONICAL_PIP], uses)
        self.assertEqual(shells("steps:\n  - shell: python\n    run: import pip\n"), ["python"])

    def test_todays_forms_are_split_as_expected(self) -> None:
        line = (
            'test -z "$("$RUNNER_TEMP/venv/bin/python" -m pip list --format=freeze'
            " | grep -v -E '^(pip|regodoc)==')\""
        )
        self.assertEqual(
            pip_uses(f"steps:\n  - run: |\n      {line}\n"),
            [
                '"$RUNNER_TEMP/venv/bin/python" -m pip list --format=freeze',
                "grep -v -E '^(pip|regodoc)=='",
            ],
        )

    def test_the_bypasses_are_caught(self) -> None:
        cases = {
            "opzione fra pip e install": "steps:\n  - run: python -m pip -q install x\n",
            "pip3 e due spazi": "steps:\n  - run: pip3  install --no-deps x\n",
            "pip3.12": "steps:\n  - run: pip3.12 install x\n",
            "due righe di un blocco >-": "steps:\n  - run: >-\n      pip\n      install x\n",
            "riga continuata": "steps:\n  - run: |\n      pip \\\n        install x\n",
            "opzioni nel commento": (
                "steps:\n  - run: |\n      pip install x  # --require-hashes --no-deps\n"
            ),
            "dopo un altro comando": "steps:\n  - run: echo a; pip install x\n",
            "uv": "steps:\n  - run: uv pip install x\n",
        }
        for case, text in cases.items():
            with self.subTest(case):
                installs = pip_installs(text)
                self.assertEqual(len(installs), 1, installs)
                self.assertTrue(missing_options(installs[0]))

    def test_a_complete_install_passes(self) -> None:
        text = (
            "steps:\n  - run: >-\n      python -m pip -q\n      install --require-hashes\n"
            "      --no-deps -r x.txt\n  - run: pip list --format=freeze | grep install\n"
        )
        installs = pip_installs(text)
        self.assertEqual(len(installs), 1, installs)
        self.assertEqual(missing_options(installs[0]), [])

    def test_composite_actions_are_read(self) -> None:
        names = [
            ".github/workflows/ci.yml",
            ".github/actions/setup/action.yml",
            "action.yaml",
            "docs/esempio.yml",
        ]
        self.assertEqual(
            automation_files(names),
            [".github/actions/setup/action.yml", ".github/workflows/ci.yml", "action.yaml"],
        )

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

    def test_the_build_tests_run_in_the_package_job(self) -> None:
        # Sui passi del job senza i commenti: il comando è quello di un passo run:, la
        # variabile è nell'env di quel passo e la storia completa nel passo del checkout.
        steps = job_steps(CI, "package")
        runs = [step for step in steps if run_commands(step) == [BUILD_TESTS]]
        self.assertEqual(len(runs), 1, steps)
        self.assertRegex(runs[0], r'(?m)^\s+env:\n(?:\s+\w+: .*\n)*?\s+REGODOC_TEST_BUILD: "1"$')
        checkout = [step for step in steps if "uses: actions/checkout@" in step]
        self.assertEqual(len(checkout), 1)
        self.assertRegex(checkout[0], r"(?m)^\s+fetch-depth: 0$")

    def test_the_package_job_check_ignores_comments(self) -> None:
        text = (
            "jobs:\n  package:\n    steps:\n"
            "      - uses: actions/checkout@abc\n"
            "        with:\n          persist-credentials: false  # fetch-depth: 0\n"
            f"      # - run: {BUILD_TESTS}\n"
            '      - run: echo\n        env:\n          X: 1  # REGODOC_TEST_BUILD: "1"\n'
            "  tex:\n"
        )
        steps = job_steps(text, "package")
        self.assertEqual(len(steps), 2)
        self.assertFalse([step for step in steps if run_commands(step) == [BUILD_TESTS]])
        self.assertNotRegex(steps[0], r"fetch-depth")
        self.assertNotRegex(steps[1], r"REGODOC_TEST_BUILD")

    def test_ruff_matches_the_ci_version(self) -> None:
        version = re.search(r'RUFF_VERSION: "([^"]+)"', CI)
        assert version is not None
        self.assertEqual(pinned(REQUIREMENTS / "lint.txt")["ruff"][0], version.group(1))


# Con REGODOC_TEST_BUILD=1, come nel job del pacchetto della CI, flit_core e la storia del
# repository devono esserci: le prove di costruzione falliscono invece di saltarsi.
REQUIRE_BUILD = os.environ.get("REGODOC_TEST_BUILD") == "1"


@unittest.skipUnless(
    importlib.util.find_spec("flit_core") or REQUIRE_BUILD, "flit_core non installato"
)
class ReproducibleBuildTest(unittest.TestCase):
    """La costruzione di tools/build_release.py. Gli interpreti delle prove non hanno
    flit_core, e lì queste prove si saltano: girano nel job del pacchetto della CI, con
    l'interprete in cui è installato flit_core da tools/requirements/build.txt e con
    REGODOC_TEST_BUILD=1."""

    def build(self, *extra: str, environment: dict[str, str] | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as folder:
            result = run_build_release("--out", folder, "--check", *extra, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.output = result.stdout
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

    def test_the_environment_date_is_ignored(self) -> None:
        before = self.build()
        after = self.build(environment={**os.environ, "SOURCE_DATE_EPOCH": "0"})
        self.assertEqual(after, before)
        self.assertIn("SOURCE_DATE_EPOCH dell'ambiente ignorato", self.output)

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
                if present.returncode != 0 and not REQUIRE_BUILD:
                    self.skipTest(f"il commit {commit} non è nel checkout")
                self.assertEqual(self.build("--commit", commit), sums)


def run_build_release(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    tool = str(ROOT / "tools" / "build_release.py")
    return subprocess.run(
        [sys.executable, tool, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class BuildReleaseArgumentsTest(unittest.TestCase):
    """Gli errori che lo strumento dà prima di costruire, anche senza flit_core."""

    def test_a_missing_commit_is_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            result = run_build_release("--out", folder, "--commit", "0" * 40)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("non esiste nel repository", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])


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
