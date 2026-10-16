"""Il comando ``canon`` (contratto, §2.1, §4.2 e §8)."""

import contextlib
import json
import resource
import shutil
import tempfile
import unittest
import zipfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from regodoc import __version__, limits
from regodoc.cli import ExitCode
from regodoc.declaration import CONTENT_LIMITS
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, png_pixels, run_cli
from tests.test_limits import section, with_backup

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

    def test_canonical_form_over_the_limits_is_refused(self) -> None:
        # Una parte tutta su una riga, valida perché sta nei 384 KiB, che con un elemento per
        # riga e i rientri della forma canonica ne esce.
        items = "<item>a</item>" * (CONTENT_LIMITS["part_bytes"] // 15)
        files = with_backup(section(f"<list>{items}</list>"))
        code, report, output = self.canon(self.package(files))
        self.assertEqual(code, ExitCode.REFUSED)
        error = report["errors"][0]  # type: ignore[index]
        self.assertEqual(
            (error["code"], error["file"]), ("regodoc.limit.file_size", "parts/backup.xml")
        )
        self.assertIn("nella forma canonica", error["message"])
        self.assertFalse(output.exists())

    def test_flat_image_stored_in_the_input(self) -> None:
        # Un PNG bianco di 1200 × 800 pixel arriva memorizzato: compresso con deflate si
        # espanderebbe più di 20 volte, e il lettore lo rifiuterebbe (specifica, §7.1).
        files = example_files()
        files["images/coverage.png"] = png_pixels(1200, 800, raw=(b"\x00" + b"\xff" * 1200) * 800)
        package = self.folder / "flat.regodoc"
        package.write_bytes(build_zip(files, stored=("images/coverage.png",)))
        code, report, output = self.canon(package)
        self.assertEqual(code, ExitCode.OK, report["errors"])
        code, out, _ = run_cli("validate", str(output), "--json")
        self.assertEqual(code, ExitCode.OK, out)

    def test_output_cannot_be_the_input(self) -> None:
        package = self.package()
        code, out, _ = run_cli("canon", str(package), "-o", str(package), "--json")
        self.assertEqual(code, ExitCode.USAGE)
        self.assertEqual(json.loads(out)["errors"][0]["code"], "regodoc.usage")


class NothingLeftBehindTest(unittest.TestCase):
    """Dopo un fallimento non resta nulla, né accanto a -o né in --files-dir (contratto, §2.1
    e §2.2): un file troppo grande per il sistema, il tempo scaduto, un SIGINT."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.package = self.folder / "in.regodoc"
        self.package.write_bytes(build_zip(example_files()))
        self.files = self.folder / "files"
        self.files.mkdir()
        self.output = self.folder / "out.regodoc"

    def run_canon(self) -> int:
        code, _, _ = run_cli(
            "canon", str(self.package), "-o", str(self.output), "--files-dir", str(self.files)
        )
        return code

    def assert_nothing_left(self) -> None:
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["files", "in.regodoc"])
        self.assertEqual(list(self.files.iterdir()), [])

    @contextlib.contextmanager
    def file_size_limit(self, size: int) -> Iterator[None]:
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        resource.setrlimit(resource.RLIMIT_FSIZE, (size, hard))
        try:
            yield
        finally:
            resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))

    def test_file_too_large_for_the_output(self) -> None:
        # 3.000 byte bastano a ogni file di contenuto, non all'archivio: EFBIG su -o.
        with self.file_size_limit(3000):
            code = self.run_canon()
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assert_nothing_left()

    def test_file_too_large_for_files_dir(self) -> None:
        # 1.000 byte: i TOML passano, la prima parte no.
        with self.file_size_limit(1000):
            code = self.run_canon()
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assert_nothing_left()

    def interrupted(self, error: BaseException, name: str) -> int:
        original = Path.replace

        def replace(path: Path, target: Path) -> Path:
            if Path(target).name == name:
                raise error
            return original(path, target)

        with mock.patch.object(Path, "replace", replace):
            return self.run_canon()

    def test_time_out_while_renaming_the_output(self) -> None:
        code = self.interrupted(limits.TimeLimitExceeded(1), "out.regodoc")
        self.assertEqual(code, ExitCode.ENVIRONMENT)
        self.assert_nothing_left()

    def test_sigint_while_renaming_a_file_of_files_dir(self) -> None:
        code = self.interrupted(KeyboardInterrupt(), "network.xml")
        self.assertEqual(code, ExitCode.INTERRUPTED)
        self.assert_nothing_left()

    def test_sigint_while_renaming_the_output(self) -> None:
        code = self.interrupted(KeyboardInterrupt(), "out.regodoc")
        self.assertEqual(code, ExitCode.INTERRUPTED)
        self.assert_nothing_left()


if __name__ == "__main__":
    unittest.main()
