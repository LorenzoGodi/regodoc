"""Il lettore del Markdown nudo md/1 (docs/spec/md-1.md): che cosa legge, che cosa rifiuta,
con quale codice e a quale riga, e in quanto tempo."""

import random
import time
import unittest

from regodoc import markdown as md

HEAD = "# Titolo\n\n## Parte\n\n"


def read(body: str, head: str = HEAD) -> md.Document:
    return md.read((head + body).encode("utf-8"))


def problems(body: str, head: str = HEAD) -> list[tuple[str, int, int]]:
    return [(p.code, p.line, p.column) for p in read(body, head).problems]


def codes(body: str, head: str = HEAD) -> list[str]:
    return [p.code for p in read(body, head).problems]


def blocks(body: str) -> list[md.Block]:
    document = read(body)
    assert not document.problems, document.problems
    return document.parts[0].blocks


def inline(text: str) -> list[md.Inline]:
    block = blocks(text + "\n")[0]
    assert isinstance(block, md.Paragraph)
    return block.inlines


class StructureTest(unittest.TestCase):
    def test_title_opening_parts_and_sections(self) -> None:
        document = md.read(
            b"# Il documento\n\nUna sintesi.\n\n## Uno\n\nTesto.\n\n### A\n\nIn A.\n\n"
            b"#### A1\n\nIn A1.\n\n### B\n\n## Due \\#2\n\nFine.\n"
        )
        self.assertEqual(document.problems, [])
        self.assertEqual((document.title, document.title_line), ("Il documento", 1))
        assert document.opening is not None
        self.assertEqual(len(document.opening.blocks), 1)
        self.assertEqual([p.title for p in document.parts], ["Uno", "Due #2"])
        first = document.parts[0]
        self.assertEqual([s.title for s in first.sections], [[md.Text("A")], [md.Text("B")]])
        self.assertEqual(first.sections[0].sections[0].title, [md.Text("A1")])
        self.assertEqual(first.sections[0].line, 9)

    def test_closing_hashes_go(self) -> None:
        self.assertEqual(read("### Sezione ##\n").parts[0].sections[0].title, [md.Text("Sezione")])
        # Solo quelli in fondo: in mezzo al titolo un cancelletto è testo.
        self.assertEqual(read("### a ##b ##\n").parts[0].sections[0].title, [md.Text("a ##b")])

    def test_heading_problems(self) -> None:
        cases = {
            "###### Sei\n": [("regodoc.markdown.heading", 5, 1)],
            "#### Salta\n": [("regodoc.markdown.heading", 5, 1)],
            "# Secondo\n": [("regodoc.markdown.heading", 5, 1)],
            "### \n": [("regodoc.markdown.heading", 5, 1)],
            "Sottolineato\n===\n": [("regodoc.markdown.heading", 6, 1)],
            "Sottolineato\n---\n": [("regodoc.markdown.heading", 6, 1)],
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertEqual(problems(body), expected)
        self.assertEqual(
            codes("", head="Testo senza titolo.\n"),
            ["regodoc.markdown.heading", "regodoc.markdown.heading"],
        )
        self.assertEqual(codes("", head="# Solo il titolo\n"), ["regodoc.markdown.heading"])

    def test_hash_without_space_is_text(self) -> None:
        self.assertEqual(inline("#etichetta"), [md.Text("#etichetta")])


class BlockTest(unittest.TestCase):
    def test_paragraph_joins_lines(self) -> None:
        self.assertEqual(blocks("uno\n  due\n")[0], md.Paragraph(5, [md.Text("uno due")]))

    def test_lists(self) -> None:
        (block,) = blocks("- a\n- b\n  - b1\n    1. b1x\n- c\n  seguito\n")
        assert isinstance(block, md.ListBlock)
        self.assertFalse(block.numbered)
        self.assertEqual(
            [i.inlines for i in block.items], [[md.Text(t)] for t in ("a", "b", "c seguito")]
        )
        sub = block.items[1].sublist
        assert sub is not None
        self.assertEqual(sub.items[0].inlines, [md.Text("b1")])
        deepest = sub.items[0].sublist
        assert deepest is not None
        self.assertTrue(deepest.numbered)

    def test_loose_list_and_a_list_of_the_other_type(self) -> None:
        listed = blocks("1. a\n\n2. b\n\n- c\n")
        self.assertEqual(len(listed), 2)
        first, second = listed
        assert isinstance(first, md.ListBlock) and isinstance(second, md.ListBlock)
        self.assertEqual((first.numbered, len(first.items)), (True, 2))
        self.assertFalse(second.numbered)

    def test_list_problems(self) -> None:
        cases = {
            "2. b\n": ("regodoc.markdown.unsupported", 5, 1),
            "- a\n   - fuori colonna\n": ("regodoc.markdown.syntax", 6, 1),
            "- a\n  1. b\n  - c\n": ("regodoc.markdown.syntax", 7, 3),
            "- [ ] da fare\n": ("regodoc.markdown.unsupported", 5, 3),
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertIn(expected, problems(body))

    def test_table(self) -> None:
        (table,) = blocks("| A | B | C |\n|---|:--|--:|\n| 1 | `x\\|y` |  |\n| *e* | 2 | 3 |\n")
        assert isinstance(table, md.Table)
        self.assertEqual(table.align, ["left", "left", "right"])
        self.assertEqual(table.head, [[md.Text("A")], [md.Text("B")], [md.Text("C")]])
        self.assertEqual(table.rows[0], [[md.Text("1")], [md.Code("x|y")], []])
        self.assertEqual(table.rows[1][0], [md.Emphasis([md.Text("e")])])

    def test_table_problems(self) -> None:
        cases = {
            "| A | B |\n| 1 | 2 |\n": ("regodoc.markdown.syntax", 5, 1),
            "| A | B |\n|---|---|\n| 1 |\n": ("regodoc.markdown.syntax", 7, 1),
            "| A |\n|:-:|\n| 1 |\n": ("regodoc.markdown.unsupported", 6, 1),
            "| A |\n|---|\n| 1\n": ("regodoc.markdown.syntax", 7, 1),
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertIn(expected, problems(body))

    def test_fenced_code_keeps_everything(self) -> None:
        (listing,) = blocks("~~~\n<b>*non* `enfasi`</b>\n  rientro\n~~~\n")
        self.assertEqual(listing, md.Listing(5, "<b>*non* `enfasi`</b>\n  rientro"))
        (listing,) = blocks("````js\nuno\n```\ndue\n````\n")
        self.assertEqual(listing, md.Listing(5, "uno\n```\ndue"))

    def test_code_problems(self) -> None:
        self.assertEqual(problems("```\naperto\n"), [("regodoc.markdown.syntax", 5, 0)])
        self.assertEqual(problems("```\n\n```\n"), [("regodoc.markdown.syntax", 5, 0)])
        self.assertEqual(
            problems("    rientrato\n    ancora\n"), [("regodoc.markdown.unsupported", 5, 1)]
        )

    def test_figure(self) -> None:
        (figure,) = blocks("![Pianta *del* capannone](images/shed-plan.png)\n")
        self.assertEqual(
            figure,
            md.Figure(
                5,
                "images/shed-plan.png",
                [md.Text("Pianta "), md.Emphasis([md.Text("del")]), md.Text(" capannone")],
            ),
        )
        (bare,) = blocks("![](images/a.jpg)\n")
        self.assertEqual(bare, md.Figure(5, "images/a.jpg", []))

    def test_figure_problems(self) -> None:
        cases = {
            "![x](https://example.com/a.png)\n": "regodoc.markdown.remote_image",
            "![x](//example.com/a.png)\n": "regodoc.markdown.remote_image",
            "![x](data:image/png;base64,AA)\n": "regodoc.markdown.remote_image",
            "![x](../a.png)\n": "regodoc.markdown.image",
            "![x](/images/a.png)\n": "regodoc.markdown.image",
            "![x](images\\\\a.png)\n": "regodoc.markdown.image",
            "![x](images/a.gif)\n": "regodoc.markdown.image",
            "Testo ![x](images/a.png) dentro.\n": "regodoc.markdown.image",
        }
        for body, code in cases.items():
            with self.subTest(body):
                self.assertEqual(codes(body), [code])

    def test_unsupported_blocks(self) -> None:
        for body in ("> citazione\n", "---\n", "* * *\n", "___\n"):
            with self.subTest(body):
                self.assertEqual(codes(body), ["regodoc.markdown.unsupported"])


class InlineTest(unittest.TestCase):
    def test_emphasis(self) -> None:
        self.assertEqual(
            inline("a **b** *c* _d_ `e` ***f***"),
            [
                md.Text("a "),
                md.Strong([md.Text("b")]),
                md.Text(" "),
                md.Emphasis([md.Text("c")]),
                md.Text(" "),
                md.Emphasis([md.Text("d")]),
                md.Text(" "),
                md.Code("e"),
                md.Text(" "),
                md.Strong([md.Emphasis([md.Text("f")])]),
            ],
        )

    def test_intraword(self) -> None:
        self.assertEqual(inline("nome_del_file e 5 * 3"), [md.Text("nome_del_file e 5 * 3")])
        self.assertEqual(
            inline("*a**b**c*"),
            [md.Emphasis([md.Text("a"), md.Strong([md.Text("b")]), md.Text("c")])],
        )

    def test_escapes_and_code(self) -> None:
        self.assertEqual(inline(r"\*non\* \<b\> \[x\](y)"), [md.Text("*non* <b> [x](y)")])
        self.assertEqual(inline("`` a `b` ``"), [md.Code("a `b`")])
        self.assertEqual(inline("x < 3 e [nota]"), [md.Text("x < 3 e [nota]")])

    def test_inline_problems(self) -> None:
        cases = {
            "un <b>tag</b>": ("regodoc.markdown.html", 5, 4),
            "un <!-- commento -->": ("regodoc.markdown.html", 5, 4),
            "[sito](https://example.com)": ("regodoc.markdown.link", 5, 1),
            "[sito][rif]": ("regodoc.markdown.link", 5, 1),
            "[rif]: https://example.com": ("regodoc.markdown.link", 5, 1),
            "vedi <https://example.com>": ("regodoc.markdown.link", 5, 6),
            "nota[^1]": ("regodoc.markdown.unsupported", 5, 5),
            "~~barrato~~": ("regodoc.markdown.unsupported", 5, 1),
            "*aperta": ("regodoc.markdown.syntax", 5, 1),
            "chiusa*": ("regodoc.markdown.syntax", 5, 7),
            "**a*": ("regodoc.markdown.syntax", 5, 4),
            "`aperto": ("regodoc.markdown.syntax", 5, 1),
            "****a****": ("regodoc.markdown.syntax", 5, 1),
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertEqual(problems(body + "\n"), [expected])

    def test_entities_and_ampersands_stay_literal(self) -> None:
        # Nessuna decodifica delle entità di CommonMark: il testo è quello scritto.
        self.assertEqual(
            inline("a &amp; b, &#60; e & nudo"), [md.Text("a &amp; b, &#60; e & nudo")]
        )

    def test_unclosed_emphasis_points_at_the_opening(self) -> None:
        self.assertEqual(
            problems("testo *aperta su una riga\ne la seguente senza chiusura\n"),
            [("regodoc.markdown.syntax", 5, 7)],
        )

    def test_position_on_the_second_line(self) -> None:
        self.assertEqual(problems("prima riga\n  e poi <i>x\n"), [("regodoc.markdown.html", 6, 9)])


class EncodingTest(unittest.TestCase):
    def test_bytes(self) -> None:
        cases = {
            b"\xef\xbb\xbf# T\n": ("regodoc.text.encoding", 1, 1),
            b"# T\n\xff\n": ("regodoc.text.encoding", 2, 0),
            b"# T\nx\x00y\n": ("regodoc.text.encoding", 2, 2),
            b"# T\nx\ry\n": ("regodoc.text.encoding", 2, 2),
            b"# T\n\tx\n": ("regodoc.markdown.syntax", 2, 1),
        }
        for data, expected in cases.items():
            with self.subTest(data):
                found = [(p.code, p.line, p.column) for p in md.read(data).problems]
                self.assertEqual(found, [expected])

    def test_crlf_is_lf(self) -> None:
        data = (HEAD + "uno\ndue\n").encode()
        self.assertEqual(md.read(data.replace(b"\n", b"\r\n")), md.read(data))

    def test_limits(self) -> None:
        self.assertEqual(
            [p.code for p in md.read(b"x" * (md.MAX_BYTES + 1)).problems],
            ["regodoc.limit.markdown"],
        )
        long = ("# T\n\n## P\n\n" + "x" * (md.MAX_LINE + 1) + "\n").encode()
        self.assertEqual([p.code for p in md.read(long).problems], ["regodoc.limit.markdown"])
        fits = ("# T\n\n## P\n\n" + "x" * md.MAX_LINE + "\n").encode()
        self.assertEqual(md.read(fits).problems, [])
        # Un file di esattamente MAX_BYTES byte passa, uno in più no.
        head = b"# T\n\n## P\n\n"
        line = b"x" * 999 + b"\n"
        body = line * ((md.MAX_BYTES - len(head)) // len(line))
        exact = head + body + b"y" * (md.MAX_BYTES - len(head) - len(body) - 1) + b"\n"
        self.assertEqual(len(exact), md.MAX_BYTES)
        self.assertEqual(md.read(exact).problems, [])
        self.assertEqual(
            [p.code for p in md.read(exact + b"z").problems], ["regodoc.limit.markdown"]
        )


class HostileTest(unittest.TestCase):
    """Ingressi costruiti per far lavorare il lettore: devono finire presto e senza eccezioni."""

    def timed(self, data: bytes) -> md.Document:
        start = time.perf_counter()
        document = md.read(data)
        self.assertLess(time.perf_counter() - start, 2.0)
        return document

    def test_long_runs(self) -> None:
        line = 9_000
        for body in (
            "*" * line,
            "`" * line,
            "_a " * (line // 3),
            "*a " * (line // 3),
            "[" * line,
            "<" * line,
            "\\" * line,
            "![" * (line // 2),
            "a**" * (line // 3),
            "`a` " * (line // 4),
        ):
            with self.subTest(body[:6]):
                data = (HEAD + "\n".join([body] * 200) + "\n").encode()
                self.timed(data)

    def test_many_lines(self) -> None:
        for body in ("- x\n" * 50_000, "| a |\n" * 50_000, "#### x\n" * 50_000, "```\n" * 50_001):
            with self.subTest(body[:6]):
                self.timed((HEAD + body).encode())

    def test_deep_lists(self) -> None:
        body = "".join(" " * (2 * level) + "- x\n" for level in range(2_000))
        self.timed((HEAD + body).encode())

    def test_random_mutations_never_raise(self) -> None:
        source = (
            HEAD + "Testo *con* **enfasi** e `codice`.\n\n- a\n  - b\n\n| A | B |\n|---|--:|\n"
            "| 1 | 2 |\n\n```\nx\n```\n\n![F](images/a.png)\n\n### S\n\n1. uno\n"
        ).encode()
        alphabet = b"#*_`[]()!<>|-:\\ \n1.~&;^\t\r"
        generator = random.Random(20261127)  # noqa: S311 - prove ripetibili
        for _ in range(3_000):
            data = bytearray(source)
            for _ in range(generator.randint(1, 10)):
                position = generator.randrange(len(data))
                action = generator.randrange(3)
                if action == 0:
                    data[position] = generator.choice(alphabet)
                elif action == 1:
                    data.insert(position, generator.choice(alphabet))
                else:
                    del data[position]
            md.read(bytes(data))


if __name__ == "__main__":
    unittest.main()
