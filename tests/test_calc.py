"""Prove delle variabili calcolate (specifica, §3.3): grammatica, tipi, valori e grafo."""

import re
import unittest
from fractions import Fraction
from pathlib import Path

from regodoc import calc
from regodoc.canonical import variables_toml
from regodoc.diagnostics import Collector
from regodoc.texts import render_variable
from regodoc.tomlfiles import read_variables
from tests.support import example_files, validate_files
from tests.test_validate import with_file

CALC_SOURCE = (Path(__file__).resolve().parent.parent / "src" / "regodoc" / "calc.py").read_text(
    encoding="utf-8"
)


def read(text: str) -> tuple[dict[str, object], list[tuple[str, str]]]:
    """I valori delle variabili valide e gli errori (codice, messaggio) di un variables.toml."""
    report = Collector()
    variables = read_variables(text.encode("utf-8"), report)
    values = {name: v.value for name, v in variables.valid.items()}
    return values, [(d.code, d.message) for d in report.errors]


def codes(text: str) -> list[str]:
    return [code for code, _ in read(text)[1]]


class GrammarTest(unittest.TestCase):
    def test_valid_formulas(self) -> None:
        for source in (
            "a",
            "2",
            "a + b",
            "a+b",
            "(a + b) * 2",
            "a * (b - c) / 4",
            "((a))",
            "1.000 * 0,5",
            "  a  -  b  ",
        ):
            with self.subTest(source):
                calc.parse(source)

    def test_invalid_formulas(self) -> None:
        cases = {
            "": "vuota",
            "   ": "vuota",
            "a +": "finisce",
            "+ a": "«+»",
            "-a": "«-»",
            "a b": "«b»",
            "(a + b": "manca «)»",
            "a + b)": "«)»",
            "()": "«)»",
            "a ** b": "«*»",
            "a % b": "«%»",
            "a\tb": "«\t»",
            "a_b": "«_»",
            "Abc": "«Abc»",
            "1000": "«1000»",
            "1,": "«1,»",
            "007": "«007»",
            "1.0000": "«1.0000»",
            "a2b + 1x": "«1x»",
            "città": "«à»",
            "abs(a)": "«(»",
            "a.b": "«.»",
        }
        for source, needle in cases.items():
            with self.subTest(source):
                with self.assertRaises(calc.FormulaError) as caught:
                    calc.parse(source)
                self.assertEqual(caught.exception.code, "regodoc.toml.calc_syntax")
                self.assertIn(needle, caught.exception.message)

    def test_column_of_the_first_wrong_symbol(self) -> None:
        with self.assertRaises(calc.FormulaError) as caught:
            calc.parse("a + b $ c")
        self.assertIn("alla colonna 7", caught.exception.message)

    def test_limits(self) -> None:
        calc.parse(" + ".join(["a"] * 64))
        calc.parse("(" * 16 + "a" + ")" * 16)
        calc.parse("a" + " " * 499)
        for source, needle in (
            (" + ".join(["a"] * 65), "64 operandi"),
            ("(" * 17 + "a" + ")" * 17, "16 livelli"),
            ("a" + " " * 500, "501 caratteri"),
        ):
            with self.subTest(needle):
                with self.assertRaises(calc.FormulaError) as caught:
                    calc.parse(source)
                self.assertEqual(caught.exception.code, "regodoc.limit.calc")
                self.assertIn(needle, caught.exception.message)

    def test_deep_parentheses_are_not_a_crash(self) -> None:
        with self.assertRaises(calc.FormulaError):
            calc.parse("(" * 100_000 + "a" + ")" * 100_000)

    def test_names_in_order_without_repeats(self) -> None:
        self.assertEqual(calc.parse("b + a * b + 2").names, ("b", "a"))

    def test_precedence_and_left_association(self) -> None:
        values = {"a": Fraction(8), "b": Fraction(4), "c": Fraction(2)}
        for source, expected in (
            ("a - b - c", 2),
            ("a / b / c", 1),
            ("a - b * c", 0),
            ("(a - b) * c", 8),
            ("a / (b / c)", 4),
        ):
            with self.subTest(source):
                self.assertEqual(calc.evaluate(calc.parse(source).tree, values), expected)

    def test_normalized_spaces(self) -> None:
        for source, expected in (
            ("a*(b+c)", "a * (b + c)"),
            ("  ( a )  ", "(a)"),
            ("1.000*0,5", "1.000 * 0,5"),
            ("a / b - c", "a / b - c"),
        ):
            with self.subTest(source):
                self.assertEqual(calc.normalize(source), expected)
                self.assertEqual(calc.normalize(expected), expected)

    def test_no_dynamic_evaluation(self) -> None:
        for word in ("eval", "exec", "compile", "__import__", "getattr", "globals"):
            with self.subTest(word):
                # re.compile è la compilazione di un'espressione regolare, non di codice.
                self.assertIsNone(re.search(rf"(?<![.\w]){word}\s*\(", CALC_SOURCE))


class TypeTest(unittest.TestCase):
    def kind(self, source: str, **types: str) -> str:
        return calc.result_type(calc.parse(source).tree, types)

    def test_rules(self) -> None:
        cases = [
            ("a + b", {"a": "eur", "b": "eur"}, "eur"),
            ("a - b", {"a": "count", "b": "count"}, "count"),
            ("a * b", {"a": "eur", "b": "percent"}, "eur"),
            ("b * a", {"a": "gb", "b": "count"}, "gb"),
            ("a * 2", {"a": "hours"}, "hours"),
            ("a * b", {"a": "count", "b": "percent"}, "number"),
            ("a / 4", {"a": "eur"}, "eur"),
            ("a / b", {"a": "eur", "b": "eur"}, "number"),
            ("a / b", {"a": "count", "b": "count"}, "number"),
            ("2 + 3", {}, "number"),
        ]
        for source, types, expected in cases:
            with self.subTest(source=source, types=types):
                self.assertEqual(self.kind(source, **types), expected)

    def test_refused(self) -> None:
        cases = [
            ("a + b", {"a": "eur", "b": "number"}),
            ("a + 50", {"a": "eur"}),
            ("a + 2", {"a": "percent"}),
            ("a + b", {"a": "count", "b": "number"}),
            ("a + b", {"a": "gb", "b": "tb"}),
            ("a * b", {"a": "eur", "b": "eur"}),
            ("a * b", {"a": "hours", "b": "days"}),
            ("2 / a", {"a": "eur"}),
            ("a / b", {"a": "eur", "b": "gb"}),
        ]
        for source, types in cases:
            with self.subTest(source=source, types=types):
                with self.assertRaises(calc.FormulaError) as caught:
                    self.kind(source, **types)
                self.assertEqual(caught.exception.code, "regodoc.toml.calc_type")

    def test_declared_type_must_agree(self) -> None:
        self.assertTrue(calc.accepts("eur", "eur"))
        self.assertTrue(calc.accepts("percent", "number"))
        self.assertTrue(calc.accepts("count", "number"))
        self.assertTrue(calc.accepts("number", "percent"))
        self.assertFalse(calc.accepts("number", "eur"))
        self.assertFalse(calc.accepts("gb", "tb"))
        self.assertFalse(calc.accepts("eur", "number"))


class RoundingTest(unittest.TestCase):
    def test_half_up_away_from_zero(self) -> None:
        cases = [
            (Fraction(5, 1000), "0,01"),
            (Fraction(-5, 1000), "-0,01"),
            (Fraction(125, 1000), "0,13"),
            (Fraction(1, 3), "0,33"),
            (Fraction(2, 3), "0,67"),
            (Fraction(4999, 1000), "5"),
            (Fraction(1234567, 100), "12.345,67"),
            (Fraction(0), "0"),
        ]
        for value, expected in cases:
            with self.subTest(value):
                self.assertEqual(calc.italian(calc.round_half_up(value, 2)), expected)

    def test_stored_forms(self) -> None:
        self.assertEqual(calc.stored("eur", Fraction(4708, 10), "f"), "470,8")
        self.assertEqual(calc.stored("eur", Fraction(50005, 1000), "f"), "50,01")
        self.assertEqual(calc.stored("eur", Fraction(2140), "f"), "2.140")
        self.assertEqual(calc.stored("count", Fraction(14), "f"), 14)
        self.assertEqual(calc.stored("days", Fraction(1), "f"), 1)
        self.assertEqual(calc.stored("number", Fraction(7, 2), "f"), "3,5")
        self.assertEqual(calc.stored("percent", Fraction(13, 14), "f"), "92,86")
        self.assertEqual(calc.stored("gb", Fraction(3), "f"), "3")

    def test_refused_values(self) -> None:
        cases = [
            ("count", Fraction(7, 2), "non dà un intero"),
            ("count", Fraction(-1), "negativa"),
            ("days", Fraction(-1), "negativa"),
            ("number", Fraction(10**15 + 1), "più di"),
        ]
        for kind, value, needle in cases:
            with self.subTest(kind=kind, value=value):
                with self.assertRaises(calc.FormulaError) as caught:
                    calc.stored(kind, value, "f")
                self.assertEqual(caught.exception.code, "regodoc.toml.calc_value")
                self.assertIn(needle, caught.exception.message)

    def test_tiny_negative_rounds_to_zero(self) -> None:
        # -0,001 giorni si arrotonda a 0, che non è negativo.
        self.assertEqual(calc.stored("days", Fraction(-1, 1000), "f"), 0)
        self.assertEqual(calc.stored("number", Fraction(-1, 1000), "f"), 0)


class VariablesFileTest(unittest.TestCase):
    """Le formule dentro variables.toml, con il grafo delle dipendenze."""

    def test_examples_of_the_spec(self) -> None:
        values, problems = read(
            'imponibile = { eur = "2.140" }\n'
            'aliquota = { percent = "22" }\n'
            'iva = { eur = { calc = "imponibile * aliquota" } }\n'
            'canone = { eur = "100,01" }\n'
            'meta = { eur = { calc = "canone / 2" } }\n'
            "uffici = { count = 3 }\n"
            'postazioni = { count = { calc = "uffici * 4 + 2" } }\n'
            "coperte = { count = 13 }\n"
            'copertura = { percent = { calc = "coperte / postazioni" } }\n'
        )
        self.assertEqual(problems, [])
        self.assertEqual(values["iva"], "470,8")
        self.assertEqual(values["meta"], "50,01")
        self.assertEqual(values["postazioni"], 14)
        self.assertEqual(values["copertura"], "92,86")

    def test_a_calculated_variable_enters_with_its_rounded_value(self) -> None:
        # terzo vale 33,33 euro, quello stampato; tre terzi danno 99,99, non 100.
        values, problems = read(
            'totale = { eur = "100" }\n'
            'terzo = { eur = { calc = "totale / 3" } }\n'
            'treTerzi = { eur = { calc = "terzo * 3" } }\n'
        )
        self.assertEqual(problems, [])
        self.assertEqual((values["terzo"], values["treTerzi"]), ("33,33", "99,99"))

    def test_order_of_the_file_does_not_matter(self) -> None:
        values, problems = read(
            'b = { eur = { calc = "a * 2" } }\n'
            'a = { eur = { calc = "c + c" } }\n'
            'c = { eur = "1,5" }\n'
        )
        self.assertEqual(problems, [])
        self.assertEqual(list(values), ["b", "a", "c"])
        self.assertEqual(values["b"], "6")

    def test_constant_with_a_unit_goes_through_a_variable(self) -> None:
        self.assertIn(
            "regodoc.toml.calc_type",
            codes('canone = { eur = "900" }\nt = { eur = { calc = "canone + 50" } }\n'),
        )
        self.assertEqual(
            codes(
                'canone = { eur = "900" }\nspese = { eur = "50" }\n'
                't = { eur = { calc = "canone + spese" } }\n'
            ),
            [],
        )

    def test_cycles(self) -> None:
        for text, path in (
            ('a = { number = { calc = "a + 1" } }\n', "a → a"),
            ('a = { number = { calc = "b" } }\nb = { number = { calc = "a" } }\n', "a → b → a"),
            (
                'a = { number = { calc = "b" } }\nb = { number = { calc = "c * 2" } }\n'
                'c = { number = { calc = "b + 1" } }\n',
                "b → c → b",
            ),
        ):
            with self.subTest(path):
                values, problems = read(text)
                self.assertEqual(values, {})
                self.assertEqual([code for code, _ in problems], ["regodoc.toml.calc_cycle"])
                self.assertIn(path, problems[0][1])

    def test_a_long_chain_is_not_a_crash(self) -> None:
        # 1.500 variabili, il massimo, ognuna sulla precedente: più della ricorsione di Python.
        lines = ["v0 = { number = 0 }"]
        lines += [f'v{i} = {{ number = {{ calc = "v{i - 1} + 1" }} }}' for i in range(1, 1500)]
        lines.reverse()
        values, problems = read("\n".join(lines) + "\n")
        self.assertEqual(problems, [])
        self.assertEqual(values["v1499"], 1499)
        cycle = [f'v{i} = {{ count = {{ calc = "v{(i + 1) % 1500}" }} }}' for i in range(1500)]
        values, problems = read("\n".join(cycle) + "\n")
        self.assertEqual(values, {})
        self.assertEqual([code for code, _ in problems], ["regodoc.toml.calc_cycle"])

    def test_names(self) -> None:
        cases = {
            'a = { number = { calc = "missing + 1" } }': "non esiste",
            'd = { date = 2026-01-31 }\na = { number = { calc = "d" } }': "«date»",
            't = { text = "x" }\na = { number = { calc = "t" } }': "«text»",
            'r = { eur = ["1", "2"] }\na = { eur = { calc = "r * 2" } }': "intervallo",
        }
        for text, needle in cases.items():
            with self.subTest(text):
                values, problems = read(text + "\n")
                self.assertNotIn("a", values)
                self.assertEqual([code for code, _ in problems], ["regodoc.toml.calc_name"])
                self.assertIn(needle, problems[0][1])

    def test_an_invalid_dependency_gives_no_second_error(self) -> None:
        values, problems = read(
            'bad = { eur = "1,005" }\n'
            'a = { eur = { calc = "bad * 2" } }\n'
            'b = { eur = { calc = "a + a" } }\n'
            'c = { eur = { calc = "missing" } }\n'
            'd = { eur = { calc = "c" } }\n'
        )
        self.assertEqual(values, {})
        self.assertEqual(
            [code for code, _ in problems], ["regodoc.toml.value", "regodoc.toml.calc_name"]
        )

    def test_division_by_zero(self) -> None:
        for formula, needle in (
            ("a / zero", "«zero»"),
            ("a / (b - b)", "«b - b»"),
            ("a / 0", "«0»"),
        ):
            with self.subTest(formula):
                text = 'a = { eur = "10" }\nb = { number = 3 }\nzero = { number = 0 }\n'
                text += f'x = {{ eur = {{ calc = "{formula}" }} }}\n'
                values, problems = read(text)
                self.assertNotIn("x", values)
                self.assertEqual([code for code, _ in problems], ["regodoc.toml.calc_division"])
                self.assertIn(needle, problems[0][1])

    def test_values(self) -> None:
        cases = {
            'p = { count = 14 }\nx = { count = { calc = "p / 4" } }': "non dà un intero",
            'a = { eur = "5" }\nx = { days = { calc = "(a - a) / a" } }': "«days»",
            'a = { days = 3 }\nb = { days = 5 }\nx = { days = { calc = "a - b" } }': "negativa",
            (
                'a = { number = 1000000000000000 }\nx = { number = { calc = "a * a / a" } }'
            ): "più di",
        }
        for text, needle in cases.items():
            with self.subTest(text):
                values, problems = read(text + "\n")
                self.assertNotIn("x", values)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(needle, problems[0][1])

    def test_negative_euro_and_percent(self) -> None:
        values, problems = read(
            'a = { eur = "10" }\nb = { eur = "12,5" }\n'
            'saldo = { eur = { calc = "a - b" } }\n'
            'scarto = { percent = { calc = "(a - b) / b" } }\n'
        )
        self.assertEqual(problems, [])
        self.assertEqual((values["saldo"], values["scarto"]), ("-2,5", "-20"))

    def test_shape_of_the_table(self) -> None:
        for text in (
            'a = { eur = { calc = "1", note = "x" } }',
            'a = { eur = { formula = "1" } }',
            "a = { eur = {} }",
            'a = { date = { calc = "1" } }',
            'a = { text = { calc = "1" } }',
            "a = { eur = { calc = 1 } }",
        ):
            with self.subTest(text):
                self.assertEqual(codes(text + "\n"), ["regodoc.toml.value"])

    def test_syntax_and_limit_errors_name_the_variable(self) -> None:
        _, problems = read('a = { number = { calc = "1 +" } }\n')
        self.assertEqual(problems[0][0], "regodoc.toml.calc_syntax")
        self.assertTrue(problems[0][1].startswith("«a»: "))
        long = " + ".join(["1"] * 65)
        self.assertEqual(
            codes(f'a = {{ number = {{ calc = "{long}" }} }}\n'), ["regodoc.limit.calc"]
        )

    def test_rendering(self) -> None:
        report = Collector()
        variables = read_variables(
            b'a = { number = 2 }\nt = { days = 2 }\nd = { days = { calc = "t / a" } }\n'
            b'base = { eur = "1.070,5" }\ne = { eur = { calc = "a * base" } }\n',
            report,
        )
        self.assertEqual(report.errors, [])
        self.assertEqual(render_variable(variables.valid["d"], "", "it").text, "1\xa0giorno")
        self.assertEqual(render_variable(variables.valid["e"], "", "it").text, "2.141\xa0euro")
        self.assertEqual(render_variable(variables.valid["e"], "", "en").text, "EUR\xa02,141")
        self.assertEqual(render_variable(variables.valid["e"], "number", "it").text, "2.141")

    def test_canonical_form(self) -> None:
        text = 'a = { number = 2 }\nb = { number = { calc = "a*(a+1.000)/0,5" }, note = "prova" }\n'
        self.assertEqual(
            variables_toml(text.encode()).decode(),
            "a = { number = 2 }\n"
            'b = { number = { calc = "a * (a + 1.000) / 0,5" }, note = "prova" }\n',
        )


class PackageTest(unittest.TestCase):
    """Le formule nel pacchetto: richiami, avvisi e il valore stampato."""

    def files(self, extra: str) -> dict[str, bytes]:
        text = example_files()["variables.toml"].decode() + extra
        return with_file("variables.toml", text)

    def test_a_variable_used_only_in_a_formula_is_used(self) -> None:
        validation = validate_files(
            self.files('base = { eur = "10" }\ndoppio = { eur = { calc = "base * 2" } }\n')
        )
        warned = [d.message for d in validation.report.warnings]
        self.assertEqual(warned, ["la variabile «doppio» non è mai usata"])

    def test_form_min_is_still_for_ranges_only(self) -> None:
        files = self.files('doppio = { eur = { calc = "2 * 3" } }\n'.replace("eur", "number"))
        part = (
            files["parts/backup.xml"]
            .decode()
            .replace("</summary>", ' <var name="doppio" form="min"/></summary>', 1)
        )
        files["parts/backup.xml"] = part.encode()
        codes_found = [d.code for d in validate_files(files).report.errors]
        self.assertEqual(codes_found, ["regodoc.xml.var_form"])


if __name__ == "__main__":
    unittest.main()
