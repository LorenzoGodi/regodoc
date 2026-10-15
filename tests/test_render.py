"""Prove dell'emettitore LaTeX: trascrizione, spazi, tipografia, comandi e golden.

I golden sono il testo di ``document.tex`` per i due esempi, con il tema neutro. Si
rigenerano con ``python tools/update_golden.py`` dopo un cambiamento voluto, e la differenza
si rilegge come ogni altra modifica.
"""

import datetime
import re
import tomllib
import unittest
from pathlib import Path

from regodoc.render import (
    SPACE,
    Document,
    escape,
    hex_url,
    join,
    plain,
    render_document,
    typography,
    wrap,
)
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, validate_bytes

GOLDEN = Path(__file__).resolve().parent / "data" / "golden"


def neutral_palette() -> dict[str, str]:
    """La tavolozza del tema neutro, letta dal suo theme.toml."""
    path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "regodoc"
        / "tex"
        / "neutral"
        / "theme.toml"
    )
    return dict(tomllib.loads(path.read_text(encoding="utf-8"))["palette"])


def render_files(files: dict[str, bytes], date: datetime.date | None = None) -> str:
    validation = validate_bytes(build_zip(files))
    errors = [str(d) for d in validation.report.errors]
    assert not errors, errors
    structure = validation.structure
    assert structure is not None
    day = date or structure.header.get("date") or datetime.date(2026, 1, 1)
    document = Document(
        structure,
        validation.variables,
        validation.roots,
        day,
        {},
        neutral_palette(),  # type: ignore[arg-type]
    )
    return render_document(document)


def with_paragraph(xml: str, root: Path = EXAMPLE) -> str:
    """L'esempio con un paragrafo in più all'inizio della parte «backup»."""
    files = example_files(root)
    part = files["parts/backup.xml"].decode()
    marker = '<section id="current-backup">'
    files["parts/backup.xml"] = part.replace(marker, f"{xml}{marker}", 1).encode()
    return render_files(files)


class EscapeTest(unittest.TestCase):
    def test_tex_specials_become_commands(self) -> None:
        text = join(escape("\\{}$&#%_^~<>|`"))
        self.assertEqual(
            text,
            r"\textbackslash{}\{\}\$\&\#\%\_\textasciicircum{}\textasciitilde{}"
            r"\textless{}\textgreater{}\textbar{}\textasciigrave{}",
        )

    def test_t1_ligatures_are_broken(self) -> None:
        self.assertEqual(join(escape(",,")), ",{},")
        self.assertEqual(join(escape("?`")), r"?\textasciigrave{}")
        self.assertEqual(
            join(escape("<<>>")), r"\textless{}\textless{}\textgreater{}\textgreater{}"
        )
        self.assertEqual(join(escape("--", code=True)), "-{}-")

    def test_code_keeps_straight_quotes(self) -> None:
        self.assertEqual(join(escape("\"'", code=True)), r"\textquotedbl{}\textquotesingle{}")

    def test_non_breaking_space_and_other_letters(self) -> None:
        self.assertEqual(join(escape("a\u00a0b")), "a~b")
        self.assertEqual(join(escape("àĦ€")), "àĦ€")

    def test_breakable_text_breaks_after_punctuation_and_long_runs(self) -> None:
        self.assertEqual(join(escape("a/b", breakable=True)), r"a/\RdAB{}b")
        long = join(escape("x" * 40, breakable=True))
        self.assertEqual(long.count(r"\RdAB{}"), 2)

    def test_typography_pairs_quotes_per_block(self) -> None:
        quotes = [0]
        self.assertEqual(typography('a "b', quotes), "a \u201cb")
        self.assertEqual(typography("c\" d--e l'f", quotes), "c\u201d d\u2013e l\u2019f")

    def test_plain_text_collapses_spaces(self) -> None:
        self.assertEqual(
            join(plain('  un  "titolo" -- 50%  ')), "un \u201ctitolo\u201d \u2013 50\\%"
        )

    def test_hex_url(self) -> None:
        self.assertEqual(hex_url("https://a.b/%7B"), "68747470733A2F2F612E622F253742")


class WrapTest(unittest.TestCase):
    def test_spaces_become_newlines_after_the_limit(self) -> None:
        pieces = escape(" ".join(["parola"] * 40))
        lines = wrap(pieces).split("\n")
        self.assertGreater(len(lines), 2)
        self.assertTrue(all(len(line) < 100 for line in lines))
        self.assertEqual(" ".join(lines), join(pieces))

    def test_a_line_without_spaces_breaks_with_a_comment(self) -> None:
        text = wrap(escape("x" * 1000))
        lines = text.split("\n")
        self.assertTrue(all(len(line) <= 202 for line in lines))
        self.assertTrue(all(line.endswith("%") for line in lines[:-1]))
        self.assertEqual(text.replace("%\n", ""), "x" * 1000)

    def test_breaks_never_split_a_command(self) -> None:
        text = wrap(escape("\\" * 300))
        for line in text.split("\n"):
            self.assertTrue(line.startswith(r"\textbackslash{}"))

    def test_space_piece(self) -> None:
        self.assertIs(escape(" ")[0], SPACE)


class MixedTextTest(unittest.TestCase):
    def test_spaces_collapse_across_inline_elements(self) -> None:
        tex = with_paragraph("<p>  uno <b> due </b>  tre\n\t<i>quattro</i>  </p>")
        self.assertIn(r"uno \RdB{due} tre \RdI{quattro}" + "\n\\par", tex)

    def test_quotes_pair_across_inline_elements_but_not_in_code(self) -> None:
        tex = with_paragraph('<p>"a <b>b"</b> <code>"x"</code></p>')
        self.assertIn("\u201ca \\RdB{b\u201d} \\RdCode{\\textquotedbl{}x\\textquotedbl{}}", tex)

    def test_break_drops_the_spaces_around_it(self) -> None:
        tex = with_paragraph("<p>riga uno <break/> riga due</p>")
        self.assertIn(r"riga uno\RdBreak{}riga due", tex)

    def test_text_starting_with_a_bracket_after_an_item(self) -> None:
        tex = with_paragraph("<list><item>[nota] testo</item></list>")
        self.assertIn(r"\RdItem [nota] testo", tex)
        self.assertIn(r"\newcommand\RdItem{\item\relax}", _sty())

    def test_references_and_citations(self) -> None:
        tex = with_paragraph(
            '<p><reference to="network" through="backup"/>, <reference to="wifi"/>, '
            '<reference to="offsite"/>, <cite to="ap-guide"/></p>'
        )
        self.assertIn(r"\RdRef{rd-network}{Parti~I–II}", tex)
        self.assertIn(r"\RdRef{rd-wifi}{“Copertura senza fili” (Parte~I)}", tex)
        self.assertIn(r"\RdRef{rd-offsite}{“Copia esterna”}", tex)
        self.assertIn(r"\RdCite{rd-ap-guide}{1}", tex)

    def test_links_and_addresses_pass_as_hexadecimal(self) -> None:
        tex = with_paragraph(
            '<p><link href="https://x.example/a%7D?b=1#c">qui</link> '
            "<address>info@x.example</address> <address>x.example</address></p>"
        )
        self.assertIn(rf"\RdLink{{{hex_url('https://x.example/a%7D?b=1#c')}}}{{qui}}", tex)
        self.assertIn(rf"\RdMail{{{hex_url('mailto:info@x.example')}}}", tex)
        self.assertIn(r"\RdDomain{x.\RdAB{}example}", tex)
        self.assertNotIn("%7D", tex)

    def test_labels_tones_and_variables(self) -> None:
        tex = with_paragraph(
            '<p><label type="to-verify"/> <tone type="ok">bene</tone> '
            '<var name="backupCapacity"/> <var name="maintenanceFee" form="max"/></p>'
        )
        self.assertIn(r"\RdLabel{warning}{da verificare}", tex)
        self.assertIn(r"\RdTone{ok}{bene}", tex)
        self.assertIn(r"\RdMono{4~TB}", tex)
        self.assertIn(r"410~euro", tex)


class StructureTest(unittest.TestCase):
    def test_preamble_has_every_role_and_the_data(self) -> None:
        tex = render_files(example_files())
        self.assertTrue(
            tex.startswith("\\documentclass[a4paper,11pt]{article}\n\\usepackage[it]{regodoc}\n")
        )
        self.assertEqual(len(re.findall(r"^\\RdColor\{", tex, re.M)), 12)
        self.assertIn(r"\RdDate{5 ottobre 2026}", tex)
        self.assertIn(r"\RdTableOfContents", tex)

    def test_parts_openings_and_sections(self) -> None:
        tex = render_files(example_files())
        self.assertIn("\\RdOpening{rd-summary}", tex)
        self.assertIn("\\RdPart{II}{sage}{rd-backup}\n{Copie di sicurezza}", tex)
        self.assertIn("\\RdSection{2}{rd-offsite}\n{Copia esterna}\n{Copia esterna}", tex)

    def test_status_box_takes_the_accent_of_the_part(self) -> None:
        tex = render_files(example_files())
        self.assertIn(r"\begin{RdBox}{sage}{}", tex)

    def test_tables(self) -> None:
        tex = render_files(example_files())
        self.assertIn(r"\begin{RdTable}{normal}{3}{1}{4.8cm}", tex)
        self.assertIn(r"\RdCell{total}{2}{\dimexpr\RdStar+2.2cm+2\tabcolsep\relax}", tex)
        self.assertIn(r"\RdHeadEnd", tex)

    def test_wide_tables_are_small_in_portrait_only(self) -> None:
        tex = render_files(example_files(LONG_EXAMPLE))
        self.assertIn(r"\begin{RdLandscape}", tex)
        sizes = re.findall(r"\\begin\{RdTable\}\{(\w+)\}\{(\d+)\}", tex)
        self.assertIn(("small", "9"), sizes)
        self.assertIn(("normal", "10"), sizes)

    def test_english_words(self) -> None:
        tex = render_files(example_files(LONG_EXAMPLE))
        self.assertIn(r"\usepackage[en]{regodoc}", tex)
        self.assertIn(r"\RdNames{Part}{Figure}{Contents}", tex)
        self.assertIn(r"\begin{RdSources}{Sources}", tex)

    def test_the_same_package_gives_the_same_text(self) -> None:
        files = example_files(LONG_EXAMPLE)
        self.assertEqual(render_files(files), render_files(files))

    def test_no_raw_package_text_reaches_a_command_name(self) -> None:
        # Ogni comando del testo emesso è uno di regodoc.sty o un comando di testo del LaTeX.
        for root in (EXAMPLE, LONG_EXAMPLE):
            tex = render_files(example_files(root))
            commands = set(re.findall(r"\\([A-Za-z]+)", tex))
            allowed = set(re.findall(r"\\newcommand\\?\{?\\?(Rd[A-Za-z]+)", _sty()))
            allowed |= set(re.findall(r"\\newenvironment\{(Rd[A-Za-z]+)\}", _sty()))
            allowed |= set(re.findall(r"\\newlength\\(Rd[A-Za-z]+)", _sty()))
            allowed |= {
                "documentclass",
                "usepackage",
                "begin",
                "end",
                "par",
                "tabcolsep",
                "dimexpr",
                "relax",
                "textbackslash",
                "textasciicircum",
                "textasciitilde",
                "textless",
                "textgreater",
                "textbar",
                "textasciigrave",
                "textquotedbl",
                "textquotesingle",
            }
            self.assertEqual(sorted(commands - allowed), [], root.name)


def _sty() -> str:
    return (
        Path(__file__).resolve().parent.parent / "src" / "regodoc" / "tex" / "regodoc.sty"
    ).read_text()


class GoldenTest(unittest.TestCase):
    def test_examples_match_the_golden_files(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            with self.subTest(root.name):
                expected = (GOLDEN / f"{root.name}.tex").read_text(encoding="utf-8")
                self.assertEqual(render_files(example_files(root)), expected)


if __name__ == "__main__":
    unittest.main()
