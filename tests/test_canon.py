"""Il comando ``canon`` (contratto, §2.1, §4.2 e §8)."""

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from regodoc import __version__
from regodoc.cli import ExitCode
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, run_cli

DIGEST = "sha256:" + "ab" * 32


class CanonCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def package(self, files: dict[str, bytes] | None = None) -> Path:
        path = self.folder / "in.regodoc"
        path.write_bytes(build_zip(files if files is not None else example_files()))
        return path

    def canon(self, package: Path, *options: str) -> tuple[int, dict[str, object], Path]:
        output = self.folder / "out.regodoc"
        code, out, _ = run_cli("canon", str(package), "-o", str(output), "--json", *options)
        return code, json.loads(out), output

    def test_folder_and_archive_give_the_same_files(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            with self.subTest(root.name):
                code, from_folder, output = self.canon(root)
                self.assertEqual(code, ExitCode.OK)
                first = output.read_bytes()
                code, from_archive, _ = self.canon(self.package(example_files(root)))
                self.assertEqual(code, ExitCode.OK)
                self.assertEqual(from_folder["files_sha256"], from_archive["files_sha256"])
                self.assertEqual(output.read_bytes(), first)

    def test_output_is_valid_and_described_by_the_report(self) -> None:
        code, report, output = self.canon(self.package())
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(report["generator"], {"engine": "regodoc", "version": __version__})
        code, out, _ = run_cli("validate", str(output), "--json")
        self.assertEqual(code, ExitCode.OK)
        checked = json.loads(out)
        self.assertEqual(checked["warnings"], [])
        for key in ("grammar", "generator", "files", "files_sha256", "package_header"):
            self.assertEqual(report[key], checked[key], key)
        self.assertNotEqual(report["input"], checked["input"])

    def test_canon_is_idempotent(self) -> None:
        files = example_files(LONG_EXAMPLE)
        files["structure.toml"] = b"# commento\n" + files["structure.toml"]
        code, report, output = self.canon(self.package(files))
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual([w["code"] for w in report["warnings"]], ["regodoc.toml.comment"])
        first = output.read_bytes()
        again = self.folder / "again.regodoc"
        code, _, _ = run_cli("canon", str(output), "-o", str(again), "--json")
        self.assertEqual(code, ExitCode.OK)
        self.assertEqual(again.read_bytes(), first)

    def test_manifest_fields(self) -> None:
        files = example_files()
        files["manifest.json"] = json.dumps(
            {
                "format": "regodoc",
                "grammar": "rego/1",
                "document": "doc-7",
                "base_version": DIGEST,
                "files": {"structure.toml": "sha256:" + "00" * 32},
            }
        ).encode("utf-8")
        package = self.package(files)
        code, report, output = self.canon(package)
        self.assertEqual(code, ExitCode.OK)
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertNotEqual(manifest["files"]["structure.toml"], "sha256:" + "00" * 32)
        self.assertEqual((manifest["document"], manifest["base_version"]), ("doc-7", DIGEST))
        self.assertEqual((report["document"], report["base_version"]), ("doc-7", DIGEST))
        other = "sha256:" + "cd" * 32
        code, report, output = self.canon(package, "--document", "altro", "--base-version", other)
        self.assertEqual(code, ExitCode.OK)
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual((manifest["document"], manifest["base_version"]), ("altro", other))
        self.assertEqual((report["document"], report["base_version"]), ("altro", other))

    def test_bad_options_are_usage_errors(self) -> None:
        package = self.package()
        for option, value in (
            ("--document", "-iniziacontrattino"),
            ("--document", "x" * 65),
            ("--base-version", "sha256:" + "AB" * 32),
            ("--base-version", "ab" * 32),
        ):
            with self.subTest(option, value=value):
                code, report, output = self.canon(package, option, value)
                self.assertEqual(code, ExitCode.USAGE)
                self.assertIn(option, report["errors"][0]["message"])
                self.assertFalse(output.exists())

    def test_refused_package_writes_nothing(self) -> None:
        files = example_files()
        files["structure.toml"] = b"[[part]\n"
        code, report, output = self.canon(self.package(files))
        self.assertEqual(code, ExitCode.REFUSED)
        self.assertEqual(report["errors"][0]["code"], "regodoc.toml.syntax")
        self.assertFalse(output.exists())
        files = example_files()
        files["structure.toml"] = b"# commento\n" + files["structure.toml"]
        code, _, output = self.canon(self.package(files), "--strict")
        self.assertEqual(code, ExitCode.REFUSED)
        self.assertFalse(output.exists())

    def test_files_dir(self) -> None:
        target = self.folder / "files"
        target.mkdir()
        code, report, _ = self.canon(self.package(), "--files-dir", str(target))
        self.assertEqual(code, ExitCode.OK)
        written = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
        self.assertEqual(written, sorted(f["path"] for f in report["files"]))  # type: ignore[index]
        files = example_files()
        for path in written:
            self.assertEqual((target / path).read_bytes(), files[path], path)

    def test_files_dir_must_exist_and_be_empty(self) -> None:
        full = self.folder / "full"
        full.mkdir()
        (full / "x").write_bytes(b"")
        for path in (self.folder / "missing", full):
            with self.subTest(path.name):
                code, report, output = self.canon(self.package(), "--files-dir", str(path))
                self.assertEqual(code, ExitCode.USAGE)
                self.assertIn("--files-dir", report["errors"][0]["message"])
                self.assertFalse(output.exists())

    def test_output_cannot_be_the_input(self) -> None:
        package = self.package()
        code, out, _ = run_cli("canon", str(package), "-o", str(package), "--json")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertEqual(json.loads(out)["errors"][0]["code"], "regodoc.usage")


if __name__ == "__main__":
    unittest.main()
