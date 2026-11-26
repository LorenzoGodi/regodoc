"""Prove dei diagrammi (specifica, §4.5): vocabolario, forma canonica e disposizione."""

import re
import unittest
from fractions import Fraction

from regodoc import diagrams, parts
from regodoc.canonical import part_xml
from regodoc.diagnostics import Collector
from tests.support import example_files, validate_files
from tests.test_render import diagram_example, render_files

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'


def with_figure(figure: str, variables: str = "") -> dict[str, bytes]:
    """L'esempio breve con una figura in più dopo quella della rete."""
    files = example_files()
    anchor = "        <caption>Copertura misurata prima dei lavori.</caption>\n      </figure>\n"
    part = files["parts/network.xml"].decode()
    files["parts/network.xml"] = part.replace(anchor, anchor + figure + "\n", 1).encode()
    if variables:
        files["variables.toml"] = files["variables.toml"] + variables.encode()
    return files


def errors(files: dict[str, bytes]) -> list[str]:
    return [d.code for d in validate_files(files).report.errors]


def figure(kind: str, body: str, attrs: str = "") -> str:
    return f'<figure{attrs}><diagram type="{kind}">{body}</diagram></figure>'


def steps(count: int) -> str:
    return "".join(f"<step>Passo {n}</step>" for n in range(count))


def events(count: int) -> str:
    return "".join(f'<event date="2026-11-{n + 1:02d}">Evento {n}</event>' for n in range(count))


def bars(count: int) -> str:
    return "".join(f'<bar value="{n}">Barra {n}</bar>' for n in range(count))


class ValidationTest(unittest.TestCase):
    def test_the_example_is_valid(self) -> None:
        self.assertEqual(errors(diagram_example()), [])

    def test_counts(self) -> None:
        valid = [
            figure("sequence", steps(2)),
            figure("sequence", steps(8)),
            figure("timeline", events(2)),
            figure("timeline", events(12)),
            figure("bars", bars(1)),
            figure("bars", bars(12)),
            figure("tree", "<node>Radice</node>"),
        ]
        for case in valid:
            with self.subTest(case):
                self.assertEqual(errors(with_figure(case)), [])
        invalid = [
            figure("sequence", steps(1)),
            figure("sequence", steps(9)),
            figure("timeline", events(1)),
            figure("timeline", events(13)),
            figure("bars", ""),
            figure("bars", bars(13)),
            figure("tree", "<node>A</node><node>B</node>"),
            figure("tree", ""),
        ]
        for case in invalid:
            with self.subTest(case):
                self.assertIn("regodoc.xml.diagram", errors(with_figure(case)))

    def test_figure_with_file_and_diagram(self) -> None:
        case = figure("sequence", steps(2), ' file="images/coverage.png"')
        self.assertEqual(errors(with_figure(case)), ["regodoc.xml.diagram"])
        two = '<figure><diagram type="sequence">' + steps(2) + "</diagram>"
        two += '<diagram type="sequence">' + steps(2) + "</diagram></figure>"
        self.assertIn("regodoc.xml.diagram", errors(with_figure(two)))
        self.assertEqual(
            errors(with_figure("<figure><caption>x</caption></figure>")),
            ["regodoc.xml.missing_attribute"],
        )

    def test_width_of_a_diagram(self) -> None:
        self.assertEqual(errors(with_figure(figure("sequence", steps(2), ' width="0.5"'))), [])
        self.assertEqual(
            errors(with_figure(figure("sequence", steps(2), ' width="0.4"'))),
            ["regodoc.xml.diagram"],
        )

    def test_type_and_children(self) -> None:
        self.assertIn("regodoc.xml.attribute_value", errors(with_figure(figure("pie", steps(2)))))
        self.assertIn(
            "regodoc.xml.missing_attribute",
            errors(with_figure("<figure><diagram>" + steps(2) + "</diagram></figure>")),
        )
        self.assertIn(
            "regodoc.xml.misplaced_element",
            errors(with_figure(figure("sequence", "<step>a</step><event>b</event>"))),
        )
        self.assertIn(
            "regodoc.xml.misplaced_element",
            errors(with_figure("<figure><step>a</step></figure>")),
        )

    def test_labels(self) -> None:
        good = "<step><b>a</b> <i>b</i> <code>c</code> <var name='workstations'/></step>"
        self.assertEqual(errors(with_figure(figure("sequence", good + "<step>x</step>"))), [])
        for inline in (
            '<link href="https://example.org">x</link>',
            "<break/>",
            '<label type="observed"/>',
            '<tone type="ok">x</tone>',
        ):
            with self.subTest(inline):
                body = f"<step>a {inline}</step><step>b</step>"
                self.assertIn(
                    "regodoc.xml.misplaced_element", errors(with_figure(figure("sequence", body)))
                )
        empty = figure("sequence", "<step> </step><step>b</step>")
        self.assertIn("regodoc.xml.empty", errors(with_figure(empty)))

    def test_label_length(self) -> None:
        # Ottanta caratteri di testo; un richiamo <var/> non conta.
        text = "x" * 80
        ok = f"<step>{text}<var name='workstations'/></step><step>b</step>"
        self.assertEqual(errors(with_figure(figure("sequence", ok))), [])
        long = f"<step>{text}y</step><step>b</step>"
        self.assertEqual(errors(with_figure(figure("sequence", long))), ["regodoc.limit.diagram"])

    def test_events(self) -> None:
        same_day = '<event date="2026-11-01">a</event><event date="2026-11-01">b</event>'
        self.assertEqual(errors(with_figure(figure("timeline", same_day))), [])
        backwards = '<event date="2026-11-02">a</event><event date="2026-11-01">b</event>'
        self.assertEqual(
            errors(with_figure(figure("timeline", backwards))), ["regodoc.xml.diagram"]
        )
        for date in ("2026-02-30", "2026-1-01", "oggi"):
            with self.subTest(date):
                body = f'<event date="{date}">a</event><event date="2026-11-01">b</event>'
                self.assertIn(
                    "regodoc.xml.attribute_value", errors(with_figure(figure("timeline", body)))
                )
        missing = "<event>a</event><event date='2026-11-01'>b</event>"
        self.assertIn(
            "regodoc.xml.missing_attribute", errors(with_figure(figure("timeline", missing)))
        )

    def test_bars(self) -> None:
        variables = (
            'altre = { count = 3 }\nmeno = { number = -2 }\nquota = { percent = "50" }\n'
            'intervallo = { count = [1, 2] }\ntesto = { text = "x" }\n'
        )
        cases = {
            '<bar var="workstations">a</bar><bar var="altre">b</bar>': [],
            '<bar value="2">a</bar><bar value="1.000,5">b</bar>': [],
            '<bar value="2" var="altre">a</bar>': ["regodoc.xml.diagram"],
            "<bar>a</bar>": ["regodoc.xml.diagram"],
            '<bar value="-2">a</bar>': ["regodoc.xml.attribute_value"],
            '<bar value="2.5">a</bar>': ["regodoc.xml.attribute_value"],
            # Il limite dei numeri del §3.1, 10^15, vale anche per «value».
            '<bar value="1.000.000.000.000.000">a</bar>': [],
            '<bar value="1.000.000.000.000.000,01">a</bar>': ["regodoc.xml.attribute_value"],
            '<bar value="1.000.000.000.000.001">a</bar>': ["regodoc.xml.attribute_value"],
            '<bar value="1.000.000.000.000.000.000">a</bar>': ["regodoc.xml.attribute_value"],
            '<bar value="2">a</bar><bar var="workstations">b</bar>': ["regodoc.xml.diagram"],
            '<bar var="altre">a</bar><bar var="quota">b</bar>': ["regodoc.xml.diagram"],
            '<bar var="meno">a</bar>': ["regodoc.xml.diagram"],
            '<bar var="intervallo">a</bar>': ["regodoc.xml.diagram"],
            '<bar var="testo">a</bar>': ["regodoc.xml.diagram"],
            '<bar var="nessuna">a</bar>': ["regodoc.xml.unknown_variable"],
        }
        for body, expected in cases.items():
            with self.subTest(body):
                self.assertEqual(errors(with_figure(figure("bars", body), variables)), expected)

    def test_a_bar_variable_counts_as_used(self) -> None:
        files = with_figure(figure("bars", '<bar var="altre">a</bar>'), "altre = { count = 3 }\n")
        warned = [d.message for d in validate_files(files).report.warnings]
        self.assertFalse([m for m in warned if "altre" in m])

    def test_tree(self) -> None:
        deep = "<node>1<node>2<node>3<node>4</node></node></node></node>"
        self.assertEqual(errors(with_figure(figure("tree", deep))), [])
        deeper = "<node>1<node>2<node>3<node>4<node>5</node></node></node></node></node>"
        self.assertEqual(errors(with_figure(figure("tree", deeper))), ["regodoc.xml.diagram"])
        wide = "<node>r" + "".join(f"<node>{n}</node>" for n in range(8)) + "</node>"
        self.assertEqual(errors(with_figure(figure("tree", wide))), [])
        wider = "<node>r" + "".join(f"<node>{n}</node>" for n in range(9)) + "</node>"
        self.assertEqual(errors(with_figure(figure("tree", wider))), ["regodoc.xml.diagram"])
        after = "<node>r<node>a</node> testo</node>"
        self.assertEqual(errors(with_figure(figure("tree", after))), ["regodoc.xml.diagram"])
        no_text = "<node><node>a</node></node>"
        self.assertEqual(errors(with_figure(figure("tree", no_text))), ["regodoc.xml.empty"])

    def test_items_limit(self) -> None:
        # Trenta nodi passano, trentuno no: 1 radice, 6 figli, 4 nipoti per figlio, 1 in più.
        children = "".join(
            "<node>f" + "".join("<node>n</node>" for _ in range(4)) + "</node>" for _ in range(5)
        )
        twenty_six = "<node>r" + children + "</node>"
        self.assertEqual(errors(with_figure(figure("tree", twenty_six))), [])
        children += "<node>f" + "".join("<node>n</node>" for _ in range(5)) + "</node>"
        thirty_two = "<node>r" + children + "</node>"
        self.assertEqual(errors(with_figure(figure("tree", thirty_two))), ["regodoc.limit.diagram"])

    def test_diagrams_per_document(self) -> None:
        one = figure("sequence", steps(2))
        self.assertEqual(errors(with_figure(one * parts.MAX_DIAGRAMS)), [])
        self.assertEqual(
            errors(with_figure(one * (parts.MAX_DIAGRAMS + 1))), ["regodoc.limit.diagram"]
        )


class CanonicalTest(unittest.TestCase):
    def test_canonical_form(self) -> None:
        source = (
            '<part><figure width="0.9"><diagram   type="tree"><node> Radice\n  <b>forte</b>'
            "<node>Figlio  <node>Nipote</node></node> <node>Altro</node></node></diagram>"
            '<caption>c</caption></figure><figure><diagram type="bars">'
            '<bar var="x"> a </bar><bar value="2">b</bar></diagram></figure></part>'
        )
        root = parts.parse_part((HEAD + source).encode(), "p.xml", Collector())
        assert root is not None
        expected = (
            HEAD
            + "<part>\n"
            + '  <figure width="0.9">\n'
            + '    <diagram type="tree">\n'
            + "      <node>Radice <b>forte</b>\n"
            + "        <node>Figlio\n"
            + "          <node>Nipote</node>\n"
            + "        </node>\n"
            + "        <node>Altro</node>\n"
            + "      </node>\n"
            + "    </diagram>\n"
            + "    <caption>c</caption>\n"
            + "  </figure>\n"
            + "  <figure>\n"
            + '    <diagram type="bars">\n'
            + '      <bar var="x">a</bar>\n'
            + '      <bar value="2">b</bar>\n'
            + "    </diagram>\n"
            + "  </figure>\n"
            + "</part>\n"
        )
        self.assertEqual(part_xml(root).decode(), expected)

    def test_the_example_is_canonical_after_one_pass(self) -> None:
        files = diagram_example()
        root = parts.parse_part(files["parts/network.xml"], "network.xml", Collector())
        assert root is not None
        once = part_xml(root)
        again = parts.parse_part(once, "network.xml", Collector())
        assert again is not None
        self.assertEqual(part_xml(again), once)


class LayoutTest(unittest.TestCase):
    def test_numbers(self) -> None:
        cases = {
            Fraction(0): "0",
            Fraction(12): "12",
            Fraction(25, 2): "12.5",
            Fraction(100, 3): "33.33",
            Fraction(200, 3): "66.67",
            Fraction(1, 200): "0.01",
            Fraction(-3, 2): "-1.5",
        }
        for value, expected in cases.items():
            with self.subTest(value):
                self.assertEqual(diagrams.number(value), expected)

    def test_sequence(self) -> None:
        self.assertEqual(
            diagrams.sequence(["a", "b"]),
            [
                r"\RdDiagramBox{rd0}{0}{43}{a}",
                r"\RdDiagramBox{rd1}{53}{43}{b}",
                r"\RdDiagramArrow{rd0}{rd1}",
            ],
        )

    def test_timeline(self) -> None:
        self.assertEqual(
            diagrams.timeline([("1 maggio", "a"), ("2 maggio", "b")]),
            [
                r"\RdDiagramAxis{0}{98}",
                r"\RdDiagramEvent{25}{46}{1 maggio}{a}",
                r"\RdDiagramEvent{75}{46}{2 maggio}{b}",
            ],
        )

    def test_bars(self) -> None:
        items = [
            diagrams.Bar("a", Fraction(4), "4"),
            diagrams.Bar("b", Fraction(1), "1"),
            diagrams.Bar("c", Fraction(0), "0"),
        ]
        self.assertEqual(
            diagrams.bars(items),
            [
                r"\RdDiagramBar{rd0}{}{30}{50}{a}{4}",
                r"\RdDiagramBar{rd1}{rd0}{30}{12.5}{b}{1}",
                r"\RdDiagramBar{rd2}{rd1}{30}{0}{c}{0}",
            ],
        )
        zero = [diagrams.Bar("z", Fraction(0), "0")]
        self.assertEqual(diagrams.bars(zero), [r"\RdDiagramBar{rd0}{}{30}{0}{z}{0}"])

    def test_tree(self) -> None:
        leaf = diagrams.TreeNode
        root = leaf("r", (leaf("a", (leaf("a1", ()),)), leaf("b", ())))
        self.assertEqual(
            diagrams.tree(root),
            [
                r"\RdDiagramNode{rd0}{}{0}{96}{r}",
                r"\RdDiagramNode{rd1}{rd0}{6}{90}{a}",
                r"\RdDiagramNode{rd2}{rd1}{12}{84}{a1}",
                r"\RdDiagramNode{rd3}{rd2}{6}{90}{b}",
                r"\RdDiagramEdge{rd0}{rd1}",
                r"\RdDiagramEdge{rd1}{rd2}",
                r"\RdDiagramEdge{rd0}{rd3}",
            ],
        )

    def test_a_wide_tree_does_not_overlap(self) -> None:
        # Ogni nodo ha una riga sua, sotto la precedente: trenta nodi, trenta righe, e nessun
        # nodo esce dalla larghezza.
        leaf = diagrams.TreeNode
        root = leaf(
            "r", tuple(leaf(f"f{n}", tuple(leaf("n", ()) for _ in range(3))) for n in range(7))
        )
        lines = [line for line in diagrams.tree(root) if line.startswith(r"\RdDiagramNode")]
        self.assertEqual(len(lines), 29)
        fields = [line.removeprefix("\\RdDiagramNode{").split("}{") for line in lines]
        self.assertEqual([f[1] for f in fields][1:], [f[0] for f in fields][:-1])
        for field in fields:
            self.assertLessEqual(Fraction(field[2]) + Fraction(field[3]), 96)

    def test_layout_is_deterministic(self) -> None:
        first = render_files(diagram_example())
        self.assertEqual(render_files(diagram_example()), first)
        self.assertIn(r"\RdDiagramBox{rd2}{53}{16.5}", first)


class RenderTest(unittest.TestCase):
    def test_special_characters_are_text(self) -> None:
        tex = render_files(diagram_example())
        self.assertIn(
            r"{Stampanti \textbackslash{} \{ \} \% \$ \& \# \_ \textasciicircum{} "
            r"\textasciitilde{}}",
            tex,
        )

    def test_tikz_only_with_a_diagram(self) -> None:
        self.assertIn(r"\usepackage[it,diagrams]{regodoc}", render_files(diagram_example()))
        self.assertIn(r"\usepackage[it]{regodoc}", render_files(example_files()))

    def test_the_accent_of_the_part(self) -> None:
        tex = render_files(diagram_example())
        self.assertEqual(set(re.findall(r"\\begin\{RdDiagram\}\{(\w+)\}", tex)), {"azure"})


if __name__ == "__main__":
    unittest.main()
