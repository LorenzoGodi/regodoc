"""La forma canonica (specifica, §9): scrittura delle parti, dei TOML, del manifesto e
dell'archivio, e il suo significato invariato."""

import datetime
import io
import json
import random
import re
import unicodedata
import unittest
import zipfile
from typing import ClassVar

from regodoc import canonical
from regodoc.render import Document, render_document
from regodoc.text import is_allowed_char
from regodoc.validate import Validation
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, validate_bytes
from tests.test_render import neutral_palette

_PART = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<part>\n  <section>\n    <title>Titolo</title>\n'
    "{body}\n  </section>\n</part>\n"
)


def valid(files: dict[str, bytes]) -> Validation:
    validation = validate_bytes(build_zip(files))
    errors = [str(d) for d in validation.report.errors]
    assert not errors, errors
    return validation


def content(files: dict[str, bytes]) -> dict[str, bytes]:
    return dict(canonical.content_files(valid(files)))


def latex(validation: Validation) -> str:
    assert validation.structure is not None
    return render_document(
        Document(
            validation.structure,
            validation.variables,
            validation.roots,
            datetime.date(2026, 10, 5),
            {},
            neutral_palette(),  # type: ignore[arg-type]
        )
    )


def with_part(body: str) -> dict[str, bytes]:
    """L'esempio breve con il corpo della prima sezione di ``network`` sostituito."""
    files = example_files()
    files["parts/network.xml"] = _PART.format(body=body).encode("utf-8")
    return files


def messy_xml(text: str, rng: random.Random) -> str:
    """Lo stesso XML con rientri a caso e ogni spazio del testo sostituito da spazi, a capo
    o tabulazioni; i listati, i commenti e gli attributi restano come sono."""
    out = []
    in_listing = False
    for number, line in enumerate(text.split("\n")):
        if number == 0 or in_listing:
            out.append(line)
            in_listing = in_listing and "</listing>" not in line
            continue
        stripped = line.lstrip(" ")
        if "<listing>" in stripped:
            out.append(line)
            in_listing = "</listing>" not in stripped
            continue
        pieces = re.split(r"(<!--.*?-->|<[^>]*>)", stripped)
        code = False
        for index, piece in enumerate(pieces):
            if piece.startswith("<"):
                # Dentro <code> e nei titoli delle fonti la tabulazione è un errore.
                if piece == "<code>" or piece.startswith("<source "):
                    code = True
                elif piece in ("</code>", "</source>"):
                    code = False
                continue
            choices = [" ", "  ", "\n" + " " * rng.randrange(9)] + ([] if code else ["\t"])
            pieces[index] = re.sub(" ", lambda _, c=choices: rng.choice(c), piece)
        indent = " " * rng.randrange(7)
        out.append(indent + "".join(pieces))
    messy = "\n".join(out)
    # Spazi in più dove il testo misto li ignora: all'inizio e alla fine dei blocchi, accanto
    # agli a capo forzati.
    messy = re.sub(r"<(p|title|caption|summary)>", lambda m: m.group() + "\n   ", messy)
    messy = re.sub(r"</(p|title|caption|summary)>", lambda m: " \n " + m.group(), messy)
    return messy.replace("<break/>", " <break/>\n ")


def messy_toml(text: str, rng: random.Random) -> str:
    """Lo stesso TOML con commenti, righe vuote e spazi in più."""
    out = ["# commento in testa", ""]
    for line in text.split("\n"):
        written = line
        if " = " in line:
            key, value = line.split(" = ", 1)
            written = f"{key}{' ' * rng.randrange(1, 4)}={' ' * rng.randrange(1, 4)}{value}"
            if rng.random() < 0.3:
                written += "   # nota"
        out.append(written)
        if rng.random() < 0.2:
            out.append("")
    return "\n".join(out)


def messy(files: dict[str, bytes], seed: int) -> dict[str, bytes]:
    rng = random.Random(seed)  # noqa: S311 - prova ripetibile
    result = dict(files)
    for path, data in files.items():
        if path.endswith(".xml"):
            result[path] = messy_xml(data.decode("utf-8"), rng).encode("utf-8")
        elif path.endswith(".toml"):
            result[path] = messy_toml(data.decode("utf-8"), rng).encode("utf-8")
    return result


class ExamplesTest(unittest.TestCase):
    def test_examples_are_canonical(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            files = example_files(root)
            with self.subTest(root.name):
                for path, data in content(files).items():
                    self.assertEqual(data, files[path], path)

    def test_messy_examples_come_back(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            files = example_files(root)
            for seed in range(6):
                with self.subTest(root.name, seed=seed):
                    mess = messy(files, seed)
                    self.assertNotEqual(mess, files)
                    for path, data in content(mess).items():
                        self.assertEqual(data, files[path], path)

    def test_meaning_is_unchanged(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            mess = messy(example_files(root), 99)
            before = valid(mess)
            after = valid({**mess, **dict(canonical.content_files(before))})
            with self.subTest(root.name):
                self.assertEqual(latex(after), latex(before))


# Frammenti di bordo per la prova di proprietà: spazi accanto agli elementi in linea, elementi
# vuoti o di soli spazi, a capo forzati, celle, voci con elenco annidato, commenti.
EDGE_FRAGMENTS = (
    "<p>a <code> x </code> b</p>",
    "<p><code>x</code><code> y</code></p>",
    "<p>il separatore è <code> </code></p>",
    "<p>il separatore è <code>\n</code></p>",
    "<p>il separatore è <code>&#32;</code></p>",
    "<p><b> <i> x </i> </b></p>",
    "<p><b> </b></p>",
    "<p><i>\n</i>x</p>",
    '<p><tone type="ok"> </tone>x</p>',
    '<p><link href="https://example.com/"> </link></p>',
    "<p> <break/> x</p>",
    "<p>x <break/> <break/> y</p>",
    "<p>x<break/></p>",
    '<p><var name="workstations"/><var name="workstations"/> <label type="observed"/></p>',
    '<p> <label type="decided"/> </p>',
    "<p>&amp;&lt;&gt;]]&gt;</p>",
    '<p>"uno" <b>"due"</b> "tre"</p>',
    "<list><item> a <list><item>b</item></list> </item></list>",
    "<list><item>a<!-- nota --></item></list>",
    "<list>\n<!-- primo -->\n<item>a</item><!-- ultimo --></list>",
    '<table columns="* *"><row><cell> </cell><cell><p> a </p></cell></row></table>',
    '<table columns="*"><head><cell>\n</cell></head><row><cell>x</cell></row></table>',
    "<listing>\n\n  rientro\n\n</listing>",
    "<listing>senza a capo</listing>",
    '<box type="note"><p> x </p><list><item> y </item></list></box>',
    "<small>\n<p>z</p>\n</small>",
)


def fragment_files(body: str) -> dict[str, bytes]:
    return with_part("    " + body)


class EdgeFragmentsTest(unittest.TestCase):
    def test_blank_code_is_empty(self) -> None:
        # <code> è vuoto senza testo non bianco, come <b>, <i>, <tone> e <link> (§4.2).
        for inner in (" ", "  ", "\n", " \n ", "\n\n", "&#32;", "&#10;", "&#32;&#10;"):
            with self.subTest(inner=inner):
                report = validate_bytes(
                    build_zip(fragment_files(f"<p>il separatore è <code>{inner}</code></p>"))
                ).report
                self.assertIn("regodoc.xml.empty", [d.code for d in report.errors])

    def test_canonical_output_of_every_valid_fragment_is_valid(self) -> None:
        checked = 0
        for body in EDGE_FRAGMENTS:
            files = fragment_files(body)
            before = validate_bytes(build_zip(files))
            if before.report.errors:
                continue
            checked += 1
            with self.subTest(body):
                after = valid({**files, **dict(canonical.content_files(before))})
                self.assertEqual(latex(after), latex(before))
                again = dict(canonical.content_files(after))
                self.assertEqual(again, dict(canonical.content_files(before)))
        self.assertGreater(checked, 15)


class MixedTextTest(unittest.TestCase):
    """Gli spazi del testo misto vanno dove li scrive il generatore LaTeX."""

    cases: ClassVar[dict[str, str]] = {
        "<p>  uno\n   due  </p>": "<p>uno due</p>",
        "<p>a<b> x</b></p>": "<p>a<b> x</b></p>",
        "<p>a <b> x</b></p>": "<p>a <b>x</b></p>",
        "<p>a<b>x </b>y</p>": "<p>a<b>x</b> y</p>",
        "<p>a<i>x</i> <b>y </b> z</p>": "<p>a<i>x</i> <b>y</b> z</p>",
        "<p>a <code> x  y </code> b</p>": "<p>a <code>x y</code> b</p>",
        "<p>a<code> x</code>b</p>": "<p>a <code>x</code>b</p>",
        "<p>uno <break/> due</p>": "<p>uno<break/>due</p>",
        "<p>Scrivi a\n<address>info@example.com</address>.</p>": (
            "<p>Scrivi a <address>info@example.com</address>.</p>"
        ),
        "<p>&gt; ]]&gt; &quot;x&quot; &#65;</p>": '<p>> ]]&gt; "x" A</p>',
        '<p><link href="https://example.com/?a=1&amp;b=&quot;">x</link></p>': (
            '<p><link href="https://example.com/?a=1&amp;b=&quot;">x</link></p>'
        ),
    }

    def test_spaces(self) -> None:
        for body, expected in self.cases.items():
            with self.subTest(body):
                files = with_part("    " + body)
                part = content(files)["parts/network.xml"].decode("utf-8")
                self.assertIn("\n    " + expected + "\n", part)
                before = valid(files)
                after = valid({**files, "parts/network.xml": part.encode("utf-8")})
                self.assertEqual(latex(after), latex(before))

    def test_attribute_order_and_empty_elements(self) -> None:
        body = (
            '    <table orientation="portrait" columns="* 2cm">\n'
            "      <row><cell>a</cell><cell></cell></row>\n"
            "      <separator></separator>\n"
            '      <row type="total"><cell>b</cell><cell> </cell></row>\n'
            "    </table>"
        )
        part = content(with_part(body))["parts/network.xml"].decode("utf-8")
        self.assertIn(
            '    <table columns="* 2cm" orientation="portrait">\n'
            "      <row>\n        <cell>a</cell>\n        <cell/>\n      </row>\n"
            "      <separator/>\n"
            '      <row type="total">\n        <cell>b</cell>\n        <cell/>\n      </row>\n'
            "    </table>\n",
            part,
        )

    def test_comments_keep_their_place(self) -> None:
        body = (
            "    <list><!-- primo -->\n<item>a</item>\n<item>b</item>\n"
            "  <!-- in fondo,\n su due righe --></list>"
        )
        part = content(with_part(body))["parts/network.xml"].decode("utf-8")
        self.assertIn(
            "    <list>\n      <!-- primo -->\n      <item>a</item>\n      <item>b</item>\n"
            "      <!-- in fondo,\n su due righe -->\n    </list>\n",
            part,
        )

    def test_listing_body_from_column_one(self) -> None:
        body = "        <listing>a &lt; b &amp;&amp; c\n  rientro\n</listing>"
        part = content(with_part(body))["parts/network.xml"].decode("utf-8")
        self.assertIn("    <listing>\na &lt; b &amp;&amp; c\n  rientro\n</listing>\n", part)


class TomlTest(unittest.TestCase):
    def test_structure_order_and_tables(self) -> None:
        files = example_files()
        files["structure.toml"] = (
            b"toc = true\n"
            b"[header]\n"
            b"version_label = 'Bozza'  # dicitura\n"
            b"date = 2026-10-05\n"
            b'title = "Titolo con \\"virgolette\\" e \\\\"\n'
            b"\n\n[[part]]\n"
            b'accent = "azure"\nid = "network"\ntitle = "Rete"\n'
            b"[[part]]\n"
            b'title = "Copie"\nid = "backup"\naccent = "sage"\n'
            b'[[opening]]\nid = "summary"\n'
        )
        self.assertEqual(
            content(files)["structure.toml"].decode("utf-8"),
            "toc = true\n\n[header]\n"
            'title = "Titolo con \\"virgolette\\" e \\\\"\n'
            "date = 2026-10-05\n"
            'version_label = "Bozza"\n'
            '\n[[opening]]\nid = "summary"\n'
            '\n[[part]]\nid = "network"\ntitle = "Rete"\naccent = "azure"\n'
            '\n[[part]]\nid = "backup"\ntitle = "Copie"\naccent = "sage"\n',
        )

    def test_variables(self) -> None:
        files = example_files()
        files["variables.toml"] = (
            b"# provenienze\n"
            b"contactOffice = {note='dal sito', text = 'Ufficio tecnico della cantina'}\n"
            b"restoreHours={hours=6}\n"
            b'backupCapacity = { tb = "4" }\n'
            b"workstations = { count = 14 }\n"
            b"installDays = { days = [ 10,14 ] }\n"
            b'wifiCoverage = { percent = "72,5" }\n'
            b'maintenanceFee = { eur = ["320", "410"] }\n'
            b"worksStart = { date = 2026-11-16 }\n"
        )
        self.assertEqual(
            content(files)["variables.toml"].decode("utf-8"),
            'contactOffice = { text = "Ufficio tecnico della cantina", note = "dal sito" }\n'
            "restoreHours = { hours = 6 }\n"
            'backupCapacity = { tb = "4" }\n'
            "workstations = { count = 14 }\n"
            "installDays = { days = [10, 14] }\n"
            'wifiCoverage = { percent = "72,5" }\n'
            'maintenanceFee = { eur = ["320", "410"] }\n'
            "worksStart = { date = 2026-11-16 }\n",
        )

    def test_empty_variables_are_omitted(self) -> None:
        files = example_files()
        files["variables.toml"] = b"# nessuna variabile\n"
        for path in ("parts/network.xml", "parts/backup.xml", "parts/summary.xml"):
            files[path] = re.sub(rb"<var [^>]*/>", b"x", files[path])
        self.assertNotIn("variables.toml", content(files))


class TextTest(unittest.TestCase):
    def test_allowed_characters_are_already_nfc(self) -> None:
        # Il testo canonico è NFC (§9): con l'insieme chiuso del §5.2 lo è già, senza
        # normalizzare nulla.
        for code in range(0x110000):
            char = chr(code)
            if is_allowed_char(char, newline=True, tab=True):
                self.assertTrue(unicodedata.is_normalized("NFC", char), hex(code))


class ArchiveTest(unittest.TestCase):
    def package(self) -> list[tuple[str, bytes]]:
        validation = valid(example_files())
        assert validation.structure is not None
        return canonical.package_files(
            canonical.content_files(validation),
            grammar="rego/1",
            title=str(validation.structure.header["title"]),
            language=validation.structure.language,
            document="doc-1",
            base_version=None,
        )

    def test_entries_follow_section_nine(self) -> None:
        files = self.package()
        data = canonical.archive(files)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            self.assertEqual([info.filename for info in infos], [path for path, _ in files])
            for info, (_, expected) in zip(infos, files, strict=True):
                self.assertEqual(archive.read(info), expected)
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.create_system, 3)
                self.assertEqual(info.create_version, 30)
                self.assertEqual(info.extract_version, 20)
                self.assertEqual(info.flag_bits, 0)
                self.assertEqual(info.extra, b"")
                self.assertEqual(info.comment, b"")
                self.assertEqual(info.external_attr, 0o100644 << 16)
                stored = info.filename == "mimetype"
                self.assertEqual(
                    info.compress_type, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
                )
            self.assertEqual(archive.comment, b"")
        report = validate_bytes(data).report
        self.assertEqual([d.code for d in report.items], [])

    def test_the_written_archive_is_read_back(self) -> None:
        problems = canonical.output_problems([], b"PK\x03\x04 non un archivio")
        self.assertTrue(problems)
        self.assertTrue(problems[0].message.startswith("nell'archivio in forma canonica: "))
        self.assertEqual(canonical.output_problems([], canonical.archive(self.package())), [])

    def test_manifest(self) -> None:
        files = dict(self.package())
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(list(manifest), ["document", "files", "format", "generator", "grammar"])
        self.assertEqual(manifest["document"], "doc-1")
        self.assertEqual(set(manifest["files"]), set(files) - {"mimetype", "manifest.json"})
        self.assertTrue(files["manifest.json"].endswith(b"}\n"))
        self.assertIn(b'\n  "format": "regodoc",\n', files["manifest.json"])


if __name__ == "__main__":
    unittest.main()
