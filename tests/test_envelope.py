"""Prove dell'involucro dopo la rilettura avversaria: rapporti, voci contigue, byte consumati,
commenti, prima voce, file di sistema, README.md e conteggio dei file."""

import io
import random
import struct
import tempfile
import unittest
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from regodoc.declaration import CONTENT_LIMITS
from regodoc.validate import validate_package
from tests.support import build_zip, codes, example_files, png, validate_bytes, validate_files

MIB = 1024 * 1024


@dataclass
class Raw:
    """Una voce da scrivere a mano: nome, contenuto, dati compressi e campi da falsare."""

    name: str
    content: bytes
    method: int = 8
    data: bytes | None = None  # i byte dopo l'intestazione locale; None = compressi da content
    flags: int = 0
    extra: bytes = b""
    comment: bytes = b""
    descriptor: bool = False
    gap: bytes = b""  # byte messi dopo la voce, prima della successiva
    crc: int | None = None  # None = il CRC vero del contenuto
    disk: int = 0  # disco d'inizio dichiarato nella directory centrale


def deflate(content: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(content) + compressor.flush()


def handmade_zip(entries: list[Raw], archive_comment: bytes = b"") -> bytes:
    """Un archivio ZIP scritto byte per byte, per i casi che zipfile non sa produrre."""
    out = bytearray()
    central = bytearray()
    for entry in entries:
        data = entry.data
        if data is None:
            data = entry.content if entry.method == 0 else deflate(entry.content)
        crc = zlib.crc32(entry.content) if entry.crc is None else entry.crc
        flags = entry.flags | (0x08 if entry.descriptor else 0)
        local_sizes = (0, 0, 0) if entry.descriptor else (crc, len(data), len(entry.content))
        name = entry.name.encode("ascii")
        offset = len(out)
        out += struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,
            flags,
            entry.method,
            0,
            0x21,
            *local_sizes,
            len(name),
            len(entry.extra),
        )
        out += name + entry.extra + data
        if entry.descriptor:
            out += b"PK\x07\x08" + struct.pack("<III", crc, len(data), len(entry.content))
        out += entry.gap
        central += struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02",
            0x031E,
            20,
            flags,
            entry.method,
            0,
            0x21,
            crc,
            len(data),
            len(entry.content),
            len(name),
            len(entry.extra),
            len(entry.comment),
            entry.disk,
            0,
            0o100644 << 16,
            offset,
        )
        central += name + entry.extra + entry.comment
    cd_offset = len(out)
    out += central
    out += struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0,
        0,
        len(entries),
        len(entries),
        len(central),
        cd_offset,
        len(archive_comment),
    )
    return bytes(out + archive_comment)


def example_raw() -> list[Raw]:
    return [
        Raw(name, data, method=0 if name == "mimetype" else 8)
        for name, data in example_files().items()
    ]


def errors_of(data: bytes) -> list[str]:
    return [d.code for d in validate_bytes(data).report.errors]


def table_part(tables: int, rows: int = 600) -> str:
    """Una parte con tabelle lunghe e ripetitive, come quelle legittime dei rapporti."""
    body = []
    for table in range(tables):
        lines = [
            f'<section id="t{table}"><title>Tabella {table + 1}</title>',
            '<table columns="1.5cm * 2.5cm">',
            "<head><cell>N.</cell><cell>Voce</cell><cell>Stato</cell></head>",
        ]
        for row in range(rows):
            lines.append(
                f"<row><cell>{row + 1}</cell><cell>Presa di rete del magazzino</cell>"
                "<cell>verificata</cell></row>"
            )
        lines.append("</table></section>")
        body.append("\n".join(lines))
    return '<?xml version="1.0" encoding="UTF-8"?>\n<part>\n' + "\n".join(body) + "\n</part>\n"


class RatioTest(unittest.TestCase):
    def test_long_table_passes(self) -> None:
        part = table_part(1).encode()
        self.assertGreater(len(part) / len(deflate(part)), 20)  # oltre il vecchio limite
        files = example_files()
        files["parts/backup.xml"] = part
        data = build_zip(files)
        self.assertNotIn("regodoc.archive.ratio", errors_of(data))
        self.assertEqual([c for c in errors_of(data) if c.startswith("regodoc.archive")], [])

    def test_several_long_tables_within_the_part_limit_pass(self) -> None:
        files = example_files()
        part = table_part(6)
        self.assertLess(len(part.encode()), 384 * 1024)
        files["parts/backup.xml"] = part.encode()
        archive = build_zip(files)
        expanded = sum(len(data) for data in files.values())
        self.assertGreater(expanded / len(archive), 20)
        self.assertEqual(
            [c for c in errors_of(build_zip(files)) if c.startswith("regodoc.archive")], []
        )

    def test_bomb_with_padding_is_refused(self) -> None:
        # Una voce che si espande a 39 MiB, gonfiata con 2,1 MiB di riempimento dopo il flusso
        # compresso perché il rapporto sui byte dichiarati sembri basso.
        bomb = bytes(39 * MIB)
        padding = random.Random(1).randbytes(2 * MIB + MIB // 10)  # noqa: S311 - prova
        entries = example_raw()
        entries.append(Raw("parts/bomb.xml", bomb, data=deflate(bomb) + padding))
        # Il riempimento non è consumato dal decompressore: la dimensione compressa dichiarata
        # non coincide con i byte consumati, e la voce si ferma lì, prima del rapporto.
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.size_mismatch"])

    def test_bomb_without_padding_is_refused(self) -> None:
        entries = example_raw()
        entries.append(Raw("parts/bomb.xml", bytes(39 * MIB)))
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.ratio"])

    def test_bomb_beyond_the_ceiling_stops_while_decompressing(self) -> None:
        entries = example_raw()
        entries.append(Raw("parts/bomb.xml", bytes(41 * MIB)))
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.expanded_too_large"])

    def test_image_ratio(self) -> None:
        entries = example_raw()
        entries.append(Raw("images/flat.png", bytes(2 * MIB)))
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.ratio"])


class EntryLayoutTest(unittest.TestCase):
    def test_handmade_example_is_valid(self) -> None:
        self.assertEqual(errors_of(handmade_zip(example_raw())), [])

    def test_data_descriptor_is_accepted(self) -> None:
        entries = example_raw()
        for entry in entries[1:]:
            entry.descriptor = True
        self.assertEqual(errors_of(handmade_zip(entries)), [])

    def test_gap_between_entries(self) -> None:
        entries = example_raw()
        entries[2].gap = b"\x00" * 16
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.gap"])

    def test_gap_before_central_directory(self) -> None:
        entries = example_raw()
        entries[-1].gap = b"nascosto"
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.gap"])

    def test_declared_size_must_match_consumed_bytes(self) -> None:
        entries = example_raw()
        target = entries[3]
        target.data = deflate(target.content) + b"\x00\x00\x00\x00"
        found = errors_of(handmade_zip(entries))
        self.assertEqual(found, ["regodoc.archive.size_mismatch"])

    def test_entry_on_another_disk(self) -> None:
        entries = example_raw()
        entries[2].disk = 1
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.multi_disk"])

    def test_comments(self) -> None:
        self.assertEqual(
            errors_of(handmade_zip(example_raw(), archive_comment=b"ciao")),
            ["regodoc.archive.comment"],
        )
        entries = example_raw()
        entries[2].comment = b"nota"
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.comment"])

    def test_mimetype_extra_field_and_descriptor(self) -> None:
        entries = example_raw()
        entries[0].extra = b"\x99\x99\x00\x00"
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.mimetype"])
        entries = example_raw()
        entries[0].descriptor = True
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.mimetype"])

    def test_mimetype_is_checked_before_other_entries(self) -> None:
        entries = example_raw()
        entries[0].content = entries[0].data = b"application/zip-qualcosa-di-32b!"
        entries.append(Raw("../fuori.xml", b"x"))
        self.assertEqual(errors_of(handmade_zip(entries)), ["regodoc.archive.mimetype"])


class FileCountTest(unittest.TestCase):
    def test_folder_entries_do_not_count(self) -> None:
        files = example_files()
        for number in range(200 - len(files)):
            files[f"images/extra{number}.png"] = png()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in files.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else 8
                archive.writestr(info, data)
                if name == "mimetype":
                    for folder in ("parts/", "images/"):
                        archive.writestr(zipfile.ZipInfo(folder, (1980, 1, 1, 0, 0, 0)), b"")
        found = errors_of(buffer.getvalue())
        # Con 200 file e due voci di cartella l'involucro passa; le immagini oltre 80 sono un
        # limite del contenuto, non dell'involucro.
        self.assertEqual([c for c in found if c.startswith("regodoc.archive")], [])


def with_folder(entry: Raw) -> list[Raw]:
    """L'esempio scritto a mano, con una voce di cartella subito dopo ``mimetype``."""
    entries = example_raw()
    entries.insert(1, entry)
    return entries


class FolderEntryTest(unittest.TestCase):
    def test_empty_folders_pass(self) -> None:
        for entry in (
            Raw("parts/", b"", method=0),
            Raw("images/", b"", method=8, data=b"\x03\x00"),
        ):
            with self.subTest(entry.name, method=entry.method):
                self.assertEqual(errors_of(handmade_zip(with_folder(entry))), [])

    def test_only_one_trailing_slash(self) -> None:
        # Prima la barra finale si toglieva con rstrip: «parts//» e «images///» passavano.
        for name in ("parts//", "images///"):
            with self.subTest(name):
                found = errors_of(handmade_zip(with_folder(Raw(name, b"", method=0))))
                self.assertEqual(found, ["regodoc.archive.path"])

    def test_folder_crc_must_be_zero(self) -> None:
        entry = Raw("parts/", b"", method=0, crc=0xDEADBEEF)
        self.assertEqual(errors_of(handmade_zip(with_folder(entry))), ["regodoc.archive.layout"])

    def test_folder_with_data_is_refused(self) -> None:
        cases = {
            # «stored» con due byte di dati, dichiarati anche come dimensione.
            "stored, due byte": Raw("parts/", b"ab", method=0),
            # «stored» con due byte di dati e dimensione dichiarata zero.
            "stored, dimensione zero": Raw("parts/", b"", method=0, data=b"ab"),
            # «deflate» di due byte, ma non il flusso vuoto.
            "deflate, due byte": Raw("parts/", b"", method=8, data=b"\x01\x00"),
            # «deflate» di un contenuto vero.
            "deflate, contenuto": Raw("parts/", b"x" * 100, method=8),
        }
        for label, entry in cases.items():
            with self.subTest(label):
                found = errors_of(handmade_zip(with_folder(entry)))
                self.assertEqual(found, ["regodoc.archive.layout"])


class SystemFilesTest(unittest.TestCase):
    NAMES = (
        "__MACOSX/._structure.toml",
        ".DS_Store",
        "parts/._backup.xml",
        "Thumbs.db",
        "images/desktop.ini",
    )

    def test_refused_in_archive_with_canon_advice(self) -> None:
        for name in self.NAMES:
            with self.subTest(name):
                files = {**example_files(), name: b"x"}
                validation = validate_bytes(build_zip(files))
                self.assertEqual(codes(validation), ["regodoc.archive.system_file"])
                self.assertIn("regodoc canon", validation.report.errors[0].message)

    def test_ignored_in_folder_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "pkg"
            for name, data in example_files().items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(data)
            for name in self.NAMES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(b"x")
            validation = validate_package(root)
        self.assertEqual(validation.report.errors, [])
        self.assertEqual(
            sorted({d.code for d in validation.report.warnings}),
            ["regodoc.package.system_file"],
        )


class ReadmeTest(unittest.TestCase):
    def test_readme_is_valid_in_folder_and_archive(self) -> None:
        files = example_files()
        self.assertIn("README.md", files)
        validation = validate_files(files)
        self.assertEqual(codes(validation), [])
        again = validate_bytes(build_zip(files))
        self.assertEqual(codes(again), [])

    def test_readme_content_is_ignored(self) -> None:
        files = {**example_files(), "README.md": "Qualunque «cosa» \U0001f600\n".encode()}
        self.assertEqual(codes(validate_files(files)), [])

    def test_readme_size_limit(self) -> None:
        limit = int(CONTENT_LIMITS["readme_bytes"])
        self.assertEqual(limit, 64 * 1024)
        line = b"Istruzioni per chi modifica il pacchetto.\n"
        at_limit = (line * (limit // len(line) + 1))[:limit]
        self.assertEqual(codes(validate_files({**example_files(), "README.md": at_limit})), [])
        over = validate_files({**example_files(), "README.md": at_limit + b"x"})
        self.assertEqual(
            [(d.code, d.file) for d in over.report.errors],
            [("regodoc.limit.file_size", "README.md")],
        )

    def test_output_held_back_by_zlib_is_read(self) -> None:
        # A ingresso finito zlib può trattenere uscita oltre il tetto di un blocco: una voce
        # integra di 65.537 «x» non è «troncata».
        for size in (65537, 65599, 3 * 65536 + 1):
            with self.subTest(size):
                found = validate_bytes(build_zip({**example_files(), "README.md": b"x" * size}))
                self.assertEqual(
                    [(d.code, d.file) for d in found.report.items],
                    [("regodoc.limit.file_size", "README.md")],
                )

    def test_other_uppercase_names_are_refused(self) -> None:
        files = {**example_files(), "README.txt": b"x"}
        self.assertEqual(
            [d.code for d in validate_bytes(build_zip(files)).report.errors],
            ["regodoc.archive.path"],
        )


class RandomHandmadeTest(unittest.TestCase):
    def test_mutations_of_handmade_archives_never_raise(self) -> None:
        generator = random.Random(20261014)  # noqa: S311 - prova ripetibile
        original = handmade_zip(example_raw())
        for _ in range(300):
            data = bytearray(original)
            for _ in range(generator.randint(1, 6)):
                data[generator.randrange(len(data))] = generator.randrange(256)
            validate_bytes(bytes(data))


if __name__ == "__main__":
    unittest.main()
