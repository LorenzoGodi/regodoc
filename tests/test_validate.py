"""Prove del validatore: il pacchetto d'esempio è valido, e ogni regola rifiuta ciò che deve."""

import io
import random
import struct
import unittest
import zipfile
from unittest import mock

from regodoc import source
from tests.support import (
    build_zip,
    codes,
    example_files,
    jpeg,
    png,
    validate_bytes,
    validate_files,
)


def with_file(path: str, data: bytes | str | None) -> dict[str, bytes]:
    """Il pacchetto d'esempio con un file sostituito, aggiunto o tolto (None)."""
    files = example_files()
    if data is None:
        files.pop(path, None)
    else:
        files[path] = data.encode("utf-8") if isinstance(data, str) else data
    return files


def with_part(body: str, part: str = "backup") -> dict[str, bytes]:
    """Il pacchetto d'esempio con il corpo di una parte sostituito."""
    root = "opening" if part == "summary" else "part"
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<{root}>\n{body}\n</{root}>\n'
    files = with_file(f"parts/{part}.xml", xml)
    if part == "backup":
        # Il rimando dell'apertura verso «backup» resta valido; le variabili non più usate
        # danno solo avvisi, che queste prove ignorano.
        pass
    return files


def section(body: str, identifier: str = "offsite") -> str:
    """Una sezione minima con un titolo e il corpo dato."""
    return f'<section id="{identifier}"><title>Titolo</title>{body}</section>'


def errors(files: dict[str, bytes]) -> list[str]:
    """I codici degli errori, senza gli avvisi."""
    return [d.code for d in validate_files(files).report.errors]


class ExampleTest(unittest.TestCase):
    def test_example_is_valid_without_warnings(self) -> None:
        validation = validate_files(example_files())
        self.assertEqual(codes(validation), [], [str(d) for d in validation.report.items])
        self.assertEqual(validation.grammar, "rego/1")

    def test_example_structure(self) -> None:
        validation = validate_files(example_files())
        assert validation.structure is not None
        self.assertEqual(
            [e.id for e in validation.structure.entries], ["summary", "network", "backup"]
        )
        self.assertEqual(validation.structure.entries[2].number, 2)
        self.assertIn("maintenanceFee", validation.variables)


# --- Archivio --------------------------------------------------------------------------------


def raw_zip(entries: list[tuple[str, bytes, int]], **options: object) -> bytes:
    """Un archivio costruito voce per voce: (nome, dati, metodo)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data, method in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = method
            info.external_attr = int(options.get("mode", 0o100644)) << 16  # type: ignore[call-overload]
            archive.writestr(info, data)
    return buffer.getvalue()


def example_entries() -> list[tuple[str, bytes, int]]:
    return [
        (name, data, zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
        for name, data in example_files().items()
    ]


class ArchiveTest(unittest.TestCase):
    def archive_codes(self, data: bytes) -> list[str]:
        return [d.code for d in validate_bytes(data).report.errors]

    def test_not_a_zip(self) -> None:
        self.assertEqual(
            self.archive_codes(b"ciao, non sono un archivio"), ["regodoc.archive.invalid"]
        )

    def test_prepended_data(self) -> None:
        data = b"MZ" + build_zip(example_files())
        self.assertEqual(self.archive_codes(data), ["regodoc.archive.invalid"])

    def test_trailing_data(self) -> None:
        data = build_zip(example_files()) + b"coda"
        self.assertEqual(self.archive_codes(data), ["regodoc.archive.trailing_data"])

    def test_mimetype_not_first(self) -> None:
        entries = example_entries()
        entries.append(entries.pop(0))
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.mimetype"])

    def test_mimetype_compressed(self) -> None:
        entries = example_entries()
        entries[0] = ("mimetype", entries[0][1], zipfile.ZIP_DEFLATED)
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.mimetype"])

    def test_mimetype_wrong_content(self) -> None:
        entries = example_entries()
        entries[0] = ("mimetype", b"application/zip", zipfile.ZIP_STORED)
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.mimetype"])

    def test_duplicate_entry(self) -> None:
        entries = example_entries()
        entries.append(("structure.toml", b"x", zipfile.ZIP_DEFLATED))
        with self.assertWarns(UserWarning):  # zipfile avverte del nome ripetuto
            data = raw_zip(entries)
        self.assertEqual(self.archive_codes(data), ["regodoc.archive.duplicate"])

    def test_duplicate_file_and_folder(self) -> None:
        entries = example_entries()
        entries.append(("images/coverage.png/", b"", zipfile.ZIP_STORED))
        self.assertIn("regodoc.archive.duplicate", self.archive_codes(raw_zip(entries)))

    def test_method_not_allowed(self) -> None:
        entries = example_entries()
        entries[1] = (entries[1][0], entries[1][1], zipfile.ZIP_BZIP2)
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.method"])

    def test_encrypted_flag(self) -> None:
        data = bytearray(build_zip(example_files()))
        # Accende il bit di cifratura della seconda voce, sia in locale sia nella directory.
        for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            position = data.find(signature, data.find(signature) + 1)
            (flags,) = struct.unpack_from("<H", data, position + flag_offset)
            struct.pack_into("<H", data, position + flag_offset, flags | 1)
        self.assertEqual(self.archive_codes(bytes(data)), ["regodoc.archive.encrypted"])

    def test_paths(self) -> None:
        for name in (
            "../evil.xml",
            "/etc/passwd",
            "parts\\a.xml",
            "parts//a.xml",
            "Parts/A.xml",
            "parts/./a.xml",
        ):
            with self.subTest(name):
                entries = [*example_entries(), (name, b"x", zipfile.ZIP_DEFLATED)]
                self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.path"])

    def test_layout(self) -> None:
        for name in (
            "notes.txt",
            "parts/Network.xml",
            "images/a.gif",
            "__MACOSX/._x",
            "parts/con.xml",
            "parts/a--b.xml",
            "images/x-.png",
            "extra/",
        ):
            with self.subTest(name):
                entries = [*example_entries(), (name, b"", zipfile.ZIP_DEFLATED)]
                self.assertIn("regodoc.archive.", self.archive_codes(raw_zip(entries))[0])

    def test_symlink(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data, method in example_entries():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = method
                mode = 0o120777 if name == "variables.toml" else 0o100644
                info.external_attr = mode << 16
                archive.writestr(info, data)
        self.assertEqual(self.archive_codes(buffer.getvalue()), ["regodoc.archive.special_file"])

    def test_too_many_entries(self) -> None:
        entries = example_entries()
        entries += [(f"images/i{n}.png", png(), zipfile.ZIP_DEFLATED) for n in range(200)]
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.too_many_files"])

    def test_compression_ratio(self) -> None:
        entries = example_entries()
        entries.append(("images/zeros.png", bytes(1024 * 1024), zipfile.ZIP_DEFLATED))
        self.assertEqual(self.archive_codes(raw_zip(entries)), ["regodoc.archive.ratio"])

    def test_expanded_limit_counts_bytes_read(self) -> None:
        limits = dict(source.ENVELOPE_LIMITS, expanded_bytes=2_000)
        with mock.patch.object(source, "ENVELOPE_LIMITS", limits):
            result = self.archive_codes(build_zip(example_files()))
        self.assertEqual(result, ["regodoc.archive.expanded_too_large"])

    def test_archive_too_large(self) -> None:
        limits = dict(source.ENVELOPE_LIMITS, compressed_bytes=1000)
        with mock.patch.object(source, "ENVELOPE_LIMITS", limits):
            result = self.archive_codes(build_zip(example_files()))
        self.assertEqual(result, ["regodoc.archive.too_large"])

    def test_crc_mismatch(self) -> None:
        entries = [
            (name, data, zipfile.ZIP_STORED if name == "structure.toml" else method)
            for name, data, method in example_entries()
        ]
        data = bytearray(raw_zip(entries))
        position = data.find(b"language")
        self.assertGreater(position, 0)
        data[position] = ord("L")
        self.assertEqual(self.archive_codes(bytes(data)), ["regodoc.archive.corrupt"])

    def test_zip64(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data, method in example_entries():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = method
                with archive.open(info, "w", force_zip64=name == "structure.toml") as stream:
                    stream.write(data)
        self.assertIn("regodoc.archive.zip64", self.archive_codes(buffer.getvalue()))

    def test_local_header_name_mismatch(self) -> None:
        data = bytearray(build_zip(example_files()))
        position = data.find(b"structure.toml")  # primo nome: intestazione locale
        data[position : position + 9] = b"structurx"
        self.assertEqual(self.archive_codes(bytes(data)), ["regodoc.archive.header_mismatch"])


# --- Manifesto -------------------------------------------------------------------------------


class ManifestTest(unittest.TestCase):
    def manifest(self, text: str) -> list[str]:
        return errors(with_file("manifest.json", text))

    def test_missing(self) -> None:
        self.assertEqual(errors(with_file("manifest.json", None)), ["regodoc.manifest.missing"])

    def test_syntax(self) -> None:
        self.assertEqual(self.manifest("{"), ["regodoc.manifest.syntax"])

    def test_duplicate_key(self) -> None:
        text = '{"format": "regodoc", "grammar": "rego/1", "grammar": "rego/1"}'
        self.assertEqual(self.manifest(text), ["regodoc.manifest.syntax"])

    def test_nan(self) -> None:
        text = '{"format": "regodoc", "grammar": "rego/1", "generator": NaN}'
        self.assertEqual(self.manifest(text), ["regodoc.manifest.syntax"])

    def test_unknown_key(self) -> None:
        text = '{"format": "regodoc", "grammar": "rego/1", "author": "x"}'
        self.assertEqual(self.manifest(text), ["regodoc.manifest.unknown_key"])

    def test_format(self) -> None:
        self.assertEqual(
            self.manifest('{"format": "odt", "grammar": "rego/1"}'), ["regodoc.manifest.format"]
        )

    def test_newer_grammar(self) -> None:
        text = '{"format": "regodoc", "grammar": "rego/2"}'
        self.assertEqual(self.manifest(text), ["regodoc.manifest.grammar_newer"])
        message = validate_files(with_file("manifest.json", text)).report.errors[0].message
        self.assertIn("«rego/2»", message)
        self.assertIn("rego/1", message)

    def test_bad_grammar(self) -> None:
        self.assertEqual(
            self.manifest('{"format": "regodoc", "grammar": "rego/01"}'),
            ["regodoc.manifest.grammar"],
        )

    def test_optional_values(self) -> None:
        good = (
            '{"format": "regodoc", "grammar": "rego/1", "document": "doc-1", '
            '"base_version": "sha256:' + "a" * 64 + '", '
            '"files": {"structure.toml": "sha256:' + "b" * 64 + '"}, '
            '"generator": {"engine": "regodoc", "version": "0.1.0"}}'
        )
        self.assertEqual(self.manifest(good), [])
        for text in (
            '{"format": "regodoc", "grammar": "rego/1", "base_version": "sha1:00"}',
            '{"format": "regodoc", "grammar": "rego/1", "document": "../x"}',
            '{"format": "regodoc", "grammar": "rego/1", "files": {"../x": "sha256:00"}}',
            '{"format": "regodoc", "grammar": "rego/1", "generator": {"name": "x"}}',
        ):
            with self.subTest(text):
                self.assertEqual(self.manifest(text), ["regodoc.manifest.value"])


# --- TOML ------------------------------------------------------------------------------------

STRUCTURE = """language = "it"

[header]
title = "Titolo"

[[opening]]
id = "summary"

[[part]]
id = "network"
title = "Rete"
accent = "azure"

[[part]]
id = "backup"
title = "Copie"
accent = "sage"
"""


class StructureTest(unittest.TestCase):
    def structure(self, text: str) -> list[str]:
        return errors(with_file("structure.toml", text))

    def test_minimal(self) -> None:
        self.assertEqual(self.structure(STRUCTURE), [])

    def test_comment_is_a_warning(self) -> None:
        validation = validate_files(with_file("structure.toml", "# nota\n" + STRUCTURE))
        self.assertEqual(
            [(d.code, d.line) for d in validation.report.warnings],
            [("regodoc.toml.comment", 1)],
        )

    def test_hash_in_string_is_not_a_comment(self) -> None:
        text = STRUCTURE.replace('title = "Titolo"', 'title = "Rapporto #3"')
        self.assertEqual(codes(validate_files(with_file("structure.toml", text))), [])

    def test_errors(self) -> None:
        cases = {
            "unknown_key": STRUCTURE + "\ncolor = 1\n",
            "missing": STRUCTURE.replace('title = "Titolo"', 'subject = "S"'),
            "value": STRUCTURE.replace('accent = "azure"', 'accent = "azzurro"'),
            "id": STRUCTURE.replace('id = "network"', 'id = "Network"'),
            "type": STRUCTURE.replace('language = "it"', 'toc = "sì"'),
            "syntax": STRUCTURE + "\n[[part]\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertIn(f"regodoc.toml.{name}", self.structure(text))

    def test_reserved_and_bad_ids(self) -> None:
        for identifier in ("con", "a--b", "a-", "lpt1", "1a", "a" * 49):
            with self.subTest(identifier):
                text = STRUCTURE.replace('id = "summary"', f'id = "{identifier}"')
                self.assertIn("regodoc.toml.id", self.structure(text))

    def test_date_with_time(self) -> None:
        text = STRUCTURE.replace('title = "Titolo"', 'title = "T"\ndate = 2026-10-05T10:00:00')
        self.assertIn("regodoc.toml.type", self.structure(text))

    def test_duplicate_id(self) -> None:
        text = STRUCTURE.replace('id = "summary"', 'id = "network"')
        self.assertIn("regodoc.xml.duplicate_id", self.structure(text))

    def test_plain_text_rules(self) -> None:
        for title in ("'a \"b'", '"a---b"', '"' + "x" * 201 + '"', '"   "'):
            with self.subTest(title):
                text = STRUCTURE.replace('title = "Titolo"', f"title = {title}")
                self.assertIn("regodoc.text.plain", self.structure(text))
        # Un carattere fuori elenco scritto con una sequenza di escape resta un problema di
        # carattere, come se fosse scritto direttamente.
        text = STRUCTURE.replace('title = "Titolo"', 'title = "a\\u202eb"')
        self.assertEqual(
            [c for c in self.structure(text) if c.startswith("regodoc.text")], ["regodoc.text.char"]
        )

    def test_no_parts(self) -> None:
        text = STRUCTURE.split("[[part]]", maxsplit=1)[0]
        self.assertIn("regodoc.toml.missing", self.structure(text))

    def test_deep_nesting_is_an_error_not_a_crash(self) -> None:
        text = STRUCTURE + "x = " + "[" * 5000 + "]" * 5000 + "\n"
        self.assertTrue(self.structure(text))


class VariablesTest(unittest.TestCase):
    def variables(self, line: str) -> list[str]:
        files = with_file("variables.toml", line + "\n")
        return [d.code for d in validate_files(files).report.errors]

    def test_valid_values(self) -> None:
        for line in (
            'a = { gb = "1.084" }',
            'a = { gb = "999,5" }',
            "a = { number = 3 }",
            'a = { number = "-2,5" }',
            'a = { eur = ["0", "1.000,50"] }',
            "a = { days = 1 }",
            'a = { text = "Studio Esempio" }',
            'a = { date = 2026-01-31, note = "fonte" }',
        ):
            with self.subTest(line):
                self.assertNotIn("regodoc.toml", " ".join(self.variables(line)))

    def test_invalid_values(self) -> None:
        cases = {
            "a = { percent = 99.8 }": "value",
            'a = { gb = "1084" }': "value",
            'a = { gb = "1,084.5" }': "value",
            'a = { eur = "1,005" }': "value",
            "a = { count = -1 }": "value",
            "a = { count = true }": "value",
            'a = { days = "-1" }': "value",
            'a = { eur = ["900", "450"] }': "range",
            'a = { eur = ["1"] }': "range",
            'a = { text = ["a", "b"] }': "range",
            'a = { gb = "1", tb = "2" }': "variable_type",
            "a = { kg = 3 }": "unknown_key",
            "A = { n = 3 }": "variable_name",
            "a = 3": "type",
            "a = { date = 2026-01-31T10:00:00 }": "value",
        }
        for line, code in cases.items():
            with self.subTest(line):
                self.assertIn(f"regodoc.toml.{code}", self.variables(line))

    def toml_codes(self, line: str) -> list[str]:
        return [c for c in self.variables(line) if c.startswith("regodoc.toml")]

    def test_italian_number_grammar(self) -> None:
        for good in ('"0"', '"0,5"', '"1.084"', '"999"', '"12.345,6"', '"-0,25"'):
            with self.subTest(good):
                self.assertEqual(self.toml_codes(f"a = {{ number = {good} }}"), [])
        for bad in ('"007"', '"0.012"', '"01"', '"1000"', '"1.08"', '"1,"', '",5"'):
            with self.subTest(bad):
                self.assertIn("regodoc.toml.value", self.toml_codes(f"a = {{ number = {bad} }}"))

    def test_negative_values(self) -> None:
        self.assertEqual(self.toml_codes('a = { eur = "-12,50" }'), [])
        self.assertEqual(self.toml_codes('a = { percent = "-3,5" }'), [])
        self.assertEqual(self.toml_codes("a = { number = -4 }"), [])
        for line in (
            'a = { gb = "-1" }',
            'a = { tb = "-0,5" }',
            "a = { days = -1 }",
            'a = { hours = "-2" }',
            "a = { count = -3 }",
        ):
            with self.subTest(line):
                self.assertIn("regodoc.toml.value", self.toml_codes(line))

    def test_integer_ceiling(self) -> None:
        self.assertEqual(self.toml_codes("a = { number = 1000000000000000 }"), [])
        self.assertIn("regodoc.toml.value", self.toml_codes("a = { number = 1000000000000001 }"))
        self.assertIn(
            "regodoc.toml.value",
            self.toml_codes('a = { eur = "1.000.000.000.000.001" }'),
        )

    def test_unused_variable_is_a_warning(self) -> None:
        text = (example_files()["variables.toml"] + b"spare = { n = 1 }\n").decode()
        text = text.replace("{ n = 1 }", "{ number = 1 }")
        validation = validate_files(with_file("variables.toml", text))
        self.assertEqual(codes(validation), ["regodoc.toml.unused_variable"])
        self.assertEqual(validation.report.warnings[0].line, 9)


class CollectAndContinueTest(unittest.TestCase):
    """Dal passo 7 in poi il motore raccoglie e prosegue, senza errori falsi (§6)."""

    def test_invalid_variable_is_not_also_unknown(self) -> None:
        text = example_files()["variables.toml"].decode()
        text = text.replace('backupCapacity = { tb = "4" }', 'backupCapacity = { tb = "4.0" }')
        found = errors(with_file("variables.toml", text))
        self.assertEqual(found, ["regodoc.toml.value"])

    def test_unreadable_variables_give_no_unknown_variable(self) -> None:
        for data in (b"a = {", b"\xef\xbb\xbfa = 1\n", b"x" * (384 * 1024 + 1)):
            with self.subTest(data[:8]):
                found = errors(with_file("variables.toml", data))
                self.assertEqual(len(found), 1, found)
                self.assertNotIn("regodoc.xml.unknown_variable", found)

    def test_undeclared_variable_is_still_unknown(self) -> None:
        found = errors(with_part(section('<p><var name="nowhere"/></p>')))
        self.assertIn("regodoc.xml.unknown_variable", found)

    def test_manifest_errors_do_not_stop_the_reading(self) -> None:
        manifest = '{"format": "regodoc", "grammar": "rego/1", "extra": 1}'
        files = with_part(section('<p><var name="nowhere"/></p>'))
        files["manifest.json"] = manifest.encode()
        found = errors(files)
        self.assertIn("regodoc.manifest.unknown_key", found)
        self.assertIn("regodoc.xml.unknown_variable", found)

    def test_missing_structure_stops_the_reading(self) -> None:
        files = with_part(section('<p><var name="nowhere"/></p>'))
        del files["structure.toml"]
        self.assertEqual(errors(files), ["regodoc.package.missing"])

    def test_format_stops_the_reading(self) -> None:
        for manifest in ('{"format": "altro", "grammar": "rego/1"}', '{"grammar": "rego/1"}'):
            with self.subTest(manifest):
                files = with_part(section('<p><var name="nowhere"/></p>'))
                files["manifest.json"] = manifest.encode()
                self.assertEqual(errors(files), ["regodoc.manifest.format"])

    def test_invalid_part_id_is_reported_once(self) -> None:
        for old, new in (('id = "backup"', 'id = "Backup"'), ('id = "network"', 'id = "a--b"')):
            with self.subTest(new):
                files = example_files()
                files["structure.toml"] = files["structure.toml"].replace(
                    old.encode(), new.encode()
                )
                self.assertEqual(codes(validate_files(files)), ["regodoc.toml.id"])

    def test_unreadable_part_gives_no_unknown_id(self) -> None:
        summary = example_files()["parts/summary.xml"].decode()
        summary = summary.replace(
            '<reference to="network" through="backup"/>', '<reference to="wifi"/>'
        )
        files = with_file("parts/summary.xml", summary)
        self.assertEqual(codes(validate_files(files)), [])
        files["parts/network.xml"] = b"<part"
        self.assertEqual(codes(validate_files(files)), ["regodoc.xml.syntax"])

    def test_orphan_part_makes_the_reading_incomplete(self) -> None:
        text = example_files()["variables.toml"].decode() + "spare = { number = 1 }\n"
        files = with_file("variables.toml", text)
        files["parts/extra.xml"] = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n<part>\n'
            b'  <section id="extra">\n    <title>Extra</title>\n'
            b'    <p><var name="spare"/> <reference to="altrove"/></p>\n  </section>\n</part>\n'
        )
        self.assertEqual(codes(validate_files(files)), ["regodoc.package.orphan_part"])

    def test_no_parts_declared(self) -> None:
        text = example_files()["structure.toml"].decode()
        files = with_file("structure.toml", text[: text.index("[[part]]")])
        self.assertEqual(
            codes(validate_files(files)),
            ["regodoc.toml.missing", "regodoc.package.orphan_part", "regodoc.package.orphan_part"],
        )


# --- XML -------------------------------------------------------------------------------------


class XmlParsingTest(unittest.TestCase):
    def part(self, data: str | bytes) -> list[str]:
        return errors(with_file("parts/network.xml", data))

    def test_forbidden_constructs(self) -> None:
        cases = {
            '<!DOCTYPE part [<!ENTITY x "y">]><part/>': "regodoc.xml.doctype",
            "<part>&nbsp;</part>": "regodoc.xml.syntax",
            '<?xml-stylesheet href="x"?><part/>': "regodoc.xml.processing_instruction",
            "<part><p><![CDATA[x]]></p></part>": "regodoc.xml.cdata",
            '<part xmlns="urn:x"/>': "regodoc.xml.namespace",
            "<x:part/>": "regodoc.xml.namespace",
            "<!-- prima --><part/>": "regodoc.xml.comment_position",
            "<part></par>": "regodoc.xml.syntax",
        }
        for text, code in cases.items():
            with self.subTest(text):
                self.assertEqual(self.part(text), [code])

    def test_declaration(self) -> None:
        self.assertEqual(self.part("<?xml version='1.0'?><part/>"), ["regodoc.xml.declaration"])
        self.assertEqual(
            self.part('<?xml version="1.0" encoding="ISO-8859-1"?><part/>'),
            ["regodoc.xml.declaration"],
        )

    def test_bom_and_encoding(self) -> None:
        self.assertEqual(self.part(b"\xef\xbb\xbf<part/>"), ["regodoc.text.bom"])
        self.assertEqual(self.part(b"<part>caff\xe8</part>"), ["regodoc.text.encoding"])

    def test_depth(self) -> None:
        body = "<list><item>" * 13 + "x" + "</item></list>" * 13
        self.assertEqual(self.part(f"<part><p>{body}</p></part>"), ["regodoc.limit.depth"])

    def test_part_size(self) -> None:
        generator = random.Random(  # noqa: S311 - prove ripetibili
            1
        )
        body = "<p>" + "".join(generator.choice("abcdefghij ") for _ in range(384 * 1024)) + "</p>"
        self.assertEqual(self.part(f"<part>{body}</part>"), ["regodoc.limit.file_size"])


NOTE_TABLE = '<box type="note"><table columns="*"><row><cell>x</cell></row></table></box>'
NOTE_BOX = '<box type="note"><box type="note"><p>x</p></box></box>'


class XmlVocabularyTest(unittest.TestCase):
    def body(self, xml: str) -> list[str]:
        return errors(with_part(section(xml)))

    def assert_error(self, xml: str, code: str) -> None:
        self.assertIn(code, self.body(xml), xml)

    def test_minimal_part_is_valid(self) -> None:
        self.assertEqual(self.body("<p>Testo.</p>"), [])

    def test_vocabulary(self) -> None:
        cases = {
            "<para>x</para>": "regodoc.xml.unknown_element",
            "<item>x</item>": "regodoc.xml.misplaced_element",
            '<p class="x">x</p>': "regodoc.xml.unknown_attribute",
            "<box><p>x</p></box>": "regodoc.xml.missing_attribute",
            '<box type="info"><p>x</p></box>': "regodoc.xml.attribute_value",
            "testo sciolto": "regodoc.xml.stray_text",
            "<p></p>": "regodoc.xml.empty",
            "<p><b><b>x</b></b></p>": "regodoc.xml.nested_inline",
            "<p><b><i><b>x</b></i></b></p>": "regodoc.xml.nested_inline",
            '<p><tone type="ok"><tone type="ok">x</tone></tone></p>': "regodoc.xml.nested_inline",
            '<p><link href="https://a.example"><b><link href="https://b.example">x</link></b>'
            "</link></p>": "regodoc.xml.misplaced_element",
            "<p>a <!-- no --> b</p>": "regodoc.xml.comment_position",
            "<p><var/></p>": "regodoc.xml.missing_attribute",
            '<p><var name="x">y</var></p>': "regodoc.xml.not_empty",
            '<p><label type="new"/></p>': "regodoc.xml.attribute_value",
            "<p><code><b>x</b></code></p>": "regodoc.xml.misplaced_element",
            NOTE_TABLE: "regodoc.xml.misplaced_element",
            NOTE_BOX: "regodoc.xml.misplaced_element",
            "<small></small>": "regodoc.xml.empty",
            "<list></list>": "regodoc.xml.empty",
            '<list type="dash"><item>x</item></list>': "regodoc.xml.attribute_value",
            "<list><item><list><item>a</item></list>dopo</item></list>": "regodoc.xml.item_list",
        }
        for xml, code in cases.items():
            with self.subTest(xml):
                self.assert_error(xml, code)

    def test_sections(self) -> None:
        self.assert_error("<section><p>x</p></section>", "regodoc.xml.missing_title")
        deep = section(section(section("<p>x</p>", "c"), "b"), "a")
        self.assert_error(deep, "regodoc.xml.section_depth")
        self.assert_error(
            section("<p>x</p>", "inner") + "<p>dopo</p>", "regodoc.xml.block_after_section"
        )
        self.assert_error('<section id="Bad"><title>T</title></section>', "regodoc.xml.id")
        self.assert_error(section("<p>x</p>", "network"), "regodoc.xml.duplicate_id")
        self.assert_error(
            '<section><title><link href="https://a.example">x</link></title></section>',
            "regodoc.xml.misplaced_element",
        )

    def test_list_depth(self) -> None:
        nested = "<list><item>a" * 4 + "</item></list>" * 4
        self.assert_error(nested, "regodoc.xml.list_depth")
        self.assertEqual(self.body("<list><item>a" * 3 + "</item></list>" * 3), [])

    def test_text_rules(self) -> None:
        self.assert_error('<p>"aperte e mai chiuse</p>', "regodoc.text.quotes")
        self.assertEqual(self.body('<p>"a" e <code>"</code></p>'), [])
        self.assert_error("<p>a --- b</p>", "regodoc.text.dashes")
        self.assertEqual(self.body("<p>a -- b <code>---</code></p>"), [])
        self.assert_error("<p>a &#x202E; b</p>", "regodoc.text.char")
        self.assert_error("<p>emoji \U0001f600</p>", "regodoc.text.char")
        self.assert_error("<p>e\u0301</p>", "regodoc.text.char")
        self.assertEqual(self.body("<p>Città, «così» — 37,65 € e ⇒ ok&#160;sì.</p>"), [])
        self.assertEqual(
            self.body("<p>Tempo \u2264 5 s, carico \u2265 2, A \u2192 B, \u22123 °C.</p>"), []
        )

    def test_links_and_addresses(self) -> None:
        for href in (
            "http://a.example",
            "https://user@a.example",
            "https://a example",
            "mailto:a@b.example",
            "https://",
            "https://a.example:99999",
            "https://" + "a" * 2000 + ".example",
            "https://-a.example/",
        ):
            with self.subTest(href):
                self.assert_error(f'<p><link href="{href}">x</link></p>', "regodoc.xml.href")
        self.assertEqual(
            self.body('<p><link href="https://a.example:8443/x?q=1#f">x</link></p>'), []
        )
        for value in (
            "localhost",
            "a@b",
            "a@@b.example",
            ".a@b.example",
            "a..b@c.example",
            "dominio con spazi.example",
            "-a.example",
        ):
            with self.subTest(value):
                self.assert_error(f"<p><address>{value}</address></p>", "regodoc.xml.address")
        self.assertEqual(self.body("<p><address>a.b_c@x-y.example</address></p>"), [])

    def test_address_has_no_newline_or_tab(self) -> None:
        for value in ("a@b.\nexample", "a@b.\texample", "\na@b.example", "a@b&#13;.example"):
            with self.subTest(repr(value)):
                self.assertEqual(
                    self.body(f"<p><address>{value}</address></p>"), ["regodoc.text.char"]
                )
        # Nello stesso contesto <code> e <source> ammettono l'a capo.
        self.assertEqual(self.body("<p><code>a\nb</code></p>"), [])

    def test_plain_text_has_its_own_code(self) -> None:
        source = '<sources><source href="https://a.example" publisher="{}">{}</source></sources>'
        for publisher, title in (('a "b', "T"), ("a --- b", "T"), ("P", 'T "x'), ("P", "a---b")):
            with self.subTest(publisher=publisher, title=title):
                xml = source.format(publisher.replace('"', "&quot;"), title)
                found = [c for c in self.body(xml) if c.startswith("regodoc.text")]
                self.assertEqual(found, ["regodoc.text.plain"])
        mixed = (('<p>"a</p>', "regodoc.text.quotes"), ("<p>a---b</p>", "regodoc.text.dashes"))
        for xml, code in mixed:
            with self.subTest(xml):
                self.assertEqual(self.body(xml), [code])

    def test_greater_than_after_brackets(self) -> None:
        self.assertEqual(self.body("<listing>\na[b[0]]&gt;1\n</listing>"), [])
        self.assertEqual(self.body("<p><code>a[b[0]]&gt;1</code></p>"), [])
        self.assertEqual(self.body("<listing>\na[b[0]]>1\n</listing>"), ["regodoc.xml.syntax"])
        self.assertEqual(self.body("<p>a > b</p>"), [])


class XmlTableFigureTest(unittest.TestCase):
    def body(self, xml: str) -> list[str]:
        return errors(with_part(section(xml)))

    def test_tables(self) -> None:
        def table(columns: str, inner: str, extra: str = "") -> str:
            return f'<table columns="{columns}"{extra}>{inner}</table>'

        row = "<row><cell>x</cell></row>"
        two = "<row><cell>x</cell><cell>y</cell></row>"
        cases = [
            (table("1cm", row), "regodoc.xml.columns"),
            (table("* 13cm", two), "regodoc.xml.columns"),
            (table("* 1,5cm", two), "regodoc.xml.columns"),
            (table(" ".join(["*"] * 11), row), "regodoc.xml.columns"),
            (table("* *", row), "regodoc.xml.row_width"),
            (table("* *", '<row><cell span="3">x</cell></row>'), "regodoc.xml.attribute_value"),
            (
                table("* *", '<row><cell span="1">x</cell><cell/></row>'),
                "regodoc.xml.attribute_value",
            ),
            (table("*", "<separator/>" + row), "regodoc.xml.separator"),
            (table("*", row + "<separator/>"), "regodoc.xml.separator"),
            (table("*", "<head><cell>h</cell></head>"), "regodoc.xml.empty"),
            (table("*", row + "<head><cell>h</cell></head>"), "regodoc.xml.table_head"),
            (table("*", "<row><cell>x<p>y</p></cell></row>"), "regodoc.xml.cell_mixed"),
            (table("*", "<row><cell><p>y</p><b>z</b></cell></row>"), "regodoc.xml.cell_mixed"),
            (table("*", row, ' orientation="sideways"'), "regodoc.xml.attribute_value"),
            (table("*", "<row><cell>" + "a" * 2001 + "</cell></row>"), "regodoc.limit.cell"),
        ]
        for xml, code in cases:
            with self.subTest(xml[:60]):
                self.assertIn(code, self.body(xml))

    def test_valid_tables(self) -> None:
        wide = '<table columns="' + " ".join(["*"] * 10) + '" orientation="landscape">'
        wide += "<row>" + "<cell/>" * 10 + "</row></table>"
        self.assertEqual(self.body(wide), [])

    def test_table_rows_limit(self) -> None:
        rows = "<row><cell>x</cell></row>" * 601
        self.assertIn("regodoc.limit.table_rows", self.body(f'<table columns="*">{rows}</table>'))

    def test_figures(self) -> None:
        self.assertIn("regodoc.xml.missing_image", self.body('<figure file="images/none.png"/>'))
        self.assertIn("regodoc.xml.figure_file", self.body('<figure file="coverage.png"/>'))
        for width in ("1.5", "0.05", "0,5", "0.123"):
            with self.subTest(width):
                self.assertIn(
                    "regodoc.xml.attribute_value",
                    self.body(f'<figure file="images/coverage.png" width="{width}"/>'),
                )

    def test_listing(self) -> None:
        self.assertIn("regodoc.text.char", self.body("<listing>\ta</listing>"))
        self.assertIn("regodoc.limit.listing_line", self.body(f"<listing>{'a' * 201}</listing>"))
        self.assertIn("regodoc.xml.comment_position", self.body("<listing><!-- x --></listing>"))
        self.assertEqual(self.body("<listing>\n  a &lt; b\n</listing>"), [])


class CrossReferenceTest(unittest.TestCase):
    def body(self, xml: str) -> list[str]:
        return errors(with_part(section(xml)))

    def test_references(self) -> None:
        cases = {
            '<p><reference to="nowhere"/></p>': "regodoc.xml.unknown_id",
            '<p><reference to="summary"/></p>': "regodoc.xml.reference_target",
            '<p><reference to="ap-guide"/></p>': "regodoc.xml.reference_target",
            '<p><reference to="backup" through="network"/></p>': "regodoc.xml.reference_through",
            '<p><reference to="lan" through="backup"/></p>': "regodoc.xml.reference_through",
            '<p><cite to="lan"/></p>': "regodoc.xml.cite_target",
            '<p><cite to="nowhere"/></p>': "regodoc.xml.unknown_id",
            '<p><var name="nowhere"/></p>': "regodoc.xml.unknown_variable",
            '<p><var name="contactOffice" form="number"/></p>': "regodoc.xml.var_form",
            '<p><var name="restoreHours" form="max"/></p>': "regodoc.xml.var_form",
        }
        for xml, code in cases.items():
            with self.subTest(xml):
                self.assertIn(code, self.body(xml))

    def test_valid_references(self) -> None:
        xml = (
            '<p><reference to="network" through="backup"/> <reference to="wifi"/> '
            '<cite to="ap-guide"/> <var name="maintenanceFee" form="min"/> '
            '<var name="backupCapacity" form="number"/></p>'
        )
        self.assertEqual(self.body(xml), [])

    def test_second_sources_block(self) -> None:
        xml = '<sources><source href="https://a.example" publisher="P">T</source></sources>'
        self.assertIn("regodoc.xml.sources_twice", self.body(xml))

    def test_sources_rules(self) -> None:
        files = with_part(
            "<summary>s</summary>",
            part="backup",
        )
        sources = (
            '<sources><group title="G"><source href="https://a.example" publisher="P">T'
            '</source></group><source href="https://b.example" publisher="P">U</source></sources>'
        )
        network = example_files()["parts/network.xml"].decode()
        start = network.index("<sources")
        end = network.index("</sources>") + len("</sources>")
        files["parts/network.xml"] = (network[:start] + sources + network[end:]).encode()
        found = [d.code for d in validate_files(files).report.errors]
        self.assertIn("regodoc.xml.sources_mixed", found)

    def test_no_unused_warning_when_a_part_is_unreadable(self) -> None:
        files = with_file("parts/backup.xml", "<part><p>non chiuso</part>")
        validation = validate_files(files)
        self.assertEqual(validation.report.warnings, [])
        self.assertIn("regodoc.xml.syntax", [d.code for d in validation.report.errors])

    def test_root_and_files(self) -> None:
        files = with_file("parts/backup.xml", "<opening/>")
        self.assertIn("regodoc.xml.root", errors(files))
        files = with_file("parts/extra.xml", "<part/>")
        self.assertIn("regodoc.package.orphan_part", errors(files))
        files = with_file("parts/backup.xml", None)
        self.assertIn("regodoc.package.missing_part", errors(files))


# --- Immagini --------------------------------------------------------------------------------


class ImageTest(unittest.TestCase):
    def image(self, name: str, data: bytes) -> list[str]:
        files = with_file(name, data)
        return [d.code for d in validate_files(files).report.items]

    def test_valid(self) -> None:
        self.assertEqual(self.image("images/coverage.png", png()), [])
        files = with_file("images/coverage.png", None)
        files["images/coverage.jpg"] = jpeg()
        files["parts/network.xml"] = files["parts/network.xml"].replace(
            b"images/coverage.png", b"images/coverage.jpg"
        )
        self.assertEqual(codes(validate_files(files)), [])

    def test_invalid(self) -> None:
        good = png()
        cases = {
            b"<svg xmlns='http://www.w3.org/2000/svg'/>": "regodoc.image.format",
            b"%PDF-1.7": "regodoc.image.format",
            jpeg(): "regodoc.image.extension",
            good[:-5]: "regodoc.image.structure",
            good + b"coda": "regodoc.image.structure",
            good[:30] + b"\x00" + good[31:]: "regodoc.image.structure",
            png(6001, 1): "regodoc.image.structure",
            png(extra=[(b"zZzZ", b"")]).replace(b"zZzZ", b"ZZZZ"): "regodoc.image.structure",
        }
        for data, code in cases.items():
            with self.subTest(data[:12]):
                self.assertIn(code, self.image("images/coverage.png", data))

    def test_jpeg_rules(self) -> None:
        def jpeg_codes(data: bytes) -> list[str]:
            files = with_file("images/coverage.png", None)
            files["images/coverage.jpg"] = data
            files["parts/network.xml"] = files["parts/network.xml"].replace(
                b"images/coverage.png", b"images/coverage.jpg"
            )
            return [d.code for d in validate_files(files).report.errors]

        self.assertIn("regodoc.image.structure", jpeg_codes(jpeg(sof=0xC3)))
        self.assertIn("regodoc.image.structure", jpeg_codes(jpeg(precision=12)))
        self.assertIn("regodoc.image.structure", jpeg_codes(jpeg(width=7000)))
        self.assertIn("regodoc.image.structure", jpeg_codes(jpeg()[:-2]))
        self.assertIn("regodoc.image.structure", jpeg_codes(jpeg() + b"x"))

    def test_metadata_and_unused_are_warnings(self) -> None:
        self.assertEqual(
            self.image("images/coverage.png", png(extra=[(b"tEXt", b"Autore\x00X")])),
            ["regodoc.image.metadata"],
        )
        self.assertEqual(self.image("images/spare.png", png()), ["regodoc.image.unused"])


# --- Robustezza ------------------------------------------------------------------------------


class RobustnessTest(unittest.TestCase):
    """Nessun pacchetto, per quanto rovinato, produce un'eccezione grezza."""

    def test_random_byte_mutations(self) -> None:
        original = build_zip(example_files())
        generator = random.Random(  # noqa: S311 - prove ripetibili
            20261012
        )
        for _ in range(400):
            data = bytearray(original)
            for _ in range(generator.randint(1, 8)):
                data[generator.randrange(len(data))] = generator.randrange(256)
            validate_bytes(bytes(data))

    def test_random_truncations(self) -> None:
        original = build_zip(example_files())
        for size in range(0, len(original), max(1, len(original) // 150)):
            validate_bytes(original[:size])

    def test_random_xml_mutations(self) -> None:
        text = example_files()["parts/backup.xml"]
        generator = random.Random(  # noqa: S311 - prove ripetibili
            7
        )
        alphabet = b'<>/"=&;!?-[] \n#xabc'
        for _ in range(300):
            data = bytearray(text)
            for _ in range(generator.randint(1, 5)):
                data[generator.randrange(len(data))] = generator.choice(alphabet)
            validate_files(with_file("parts/backup.xml", bytes(data)))


if __name__ == "__main__":
    unittest.main()
