"""Prove della resa dei valori e delle parole del motore (specifica, §3.1, §4.6 e §5.6)."""

import datetime
import unittest

from regodoc.declaration import THEME_ROLES
from regodoc.parts import BOX_TYPES, LABEL_TYPES
from regodoc.texts import (
    BOX_ROLES,
    LABEL_ROLES,
    WORDS,
    format_date,
    format_eur,
    format_number,
    render_variable,
    roman,
)
from regodoc.tomlfiles import Variable

NBSP = " "


def variable(kind: str, value: object) -> Variable:
    return Variable("v", kind, value, isinstance(value, tuple), 1)


class NumbersTest(unittest.TestCase):
    def test_integers_take_the_thousands_separator(self) -> None:
        self.assertEqual(format_number(96418, "it"), "96.418")
        self.assertEqual(format_number(96418, "en"), "96,418")
        self.assertEqual(format_number(999, "it"), "999")
        self.assertEqual(format_number(10**15, "en"), "1,000,000,000,000,000")

    def test_italian_numbers_keep_their_decimals(self) -> None:
        self.assertEqual(format_number("2.310,75", "it"), "2.310,75")
        self.assertEqual(format_number("2.310,75", "en"), "2,310.75")
        self.assertEqual(format_number("1,0", "en"), "1.0")
        self.assertEqual(format_number("0,5", "it"), "0,5")

    def test_negative_numbers_use_the_minus_sign(self) -> None:
        self.assertEqual(format_number("-3,5", "it"), "−3,5")
        self.assertEqual(format_number(-1200, "en"), "−1,200")

    def test_euro_amounts(self) -> None:
        self.assertEqual(format_eur("2.140", "it"), "2.140")
        self.assertEqual(format_eur("11,4", "it"), "11,40")
        self.assertEqual(format_eur("11,40", "en"), "11.40")
        self.assertEqual(format_eur("320,00", "it"), "320")
        self.assertEqual(format_eur("-40", "en"), "−40")

    def test_roman_numbers(self) -> None:
        self.assertEqual(
            [roman(n) for n in (1, 4, 9, 14, 40, 48)], ["I", "IV", "IX", "XIV", "XL", "XLVIII"]
        )
        with self.assertRaises(ValueError):
            roman(0)

    def test_dates(self) -> None:
        day = datetime.date(2026, 9, 30)
        self.assertEqual(format_date(day, "it"), "30 settembre 2026")
        self.assertEqual(format_date(datetime.date(2026, 10, 5), "en"), "5 October 2026")


class VariablesTest(unittest.TestCase):
    def test_the_table_of_section_3_1(self) -> None:
        cases = [
            ("date", datetime.date(2026, 9, 30), "it", "30 settembre 2026"),
            ("gb", "2.310,75", "it", f"2.310,75{NBSP}GB"),
            ("gb", "2.310,75", "en", f"2,310.75{NBSP}GB"),
            ("count", 96418, "it", "96.418"),
            ("count", 96418, "en", "96,418"),
            ("number", 6, "it", "6"),
            ("number", "3,5", "en", "3.5"),
            ("percent", "61,2", "it", "61,2%"),
            ("percent", "61,2", "en", "61.2%"),
            ("eur", "2.140", "it", f"2.140{NBSP}euro"),
            ("eur", "11,40", "it", f"11,40{NBSP}euro"),
            ("eur", "2.140", "en", f"EUR{NBSP}2,140"),
            ("eur", "11,40", "en", f"EUR{NBSP}11.40"),
            ("days", 30, "it", f"30{NBSP}giorni"),
            ("days", 1, "it", f"1{NBSP}giorno"),
            ("days", 30, "en", f"30{NBSP}days"),
            ("days", 1, "en", f"1{NBSP}day"),
            ("hours", "1", "it", f"1{NBSP}ora"),
            ("months", "1,0", "it", f"1,0{NBSP}mesi"),
            ("text", "Ufficio tecnico", "it", "Ufficio tecnico"),
        ]
        for kind, value, language, expected in cases:
            with self.subTest(kind=kind, value=value, language=language):
                rendered = render_variable(variable(kind, value), "", language)
                self.assertEqual(rendered.text, expected)
                self.assertEqual(rendered.mono, kind in ("gb", "tb", "count"))

    def test_ranges_have_the_unit_once_and_are_plural(self) -> None:
        eur = variable("eur", ("320", "410"))
        self.assertEqual(render_variable(eur, "", "it").text, f"320–410{NBSP}euro")
        self.assertEqual(render_variable(eur, "", "en").text, f"EUR{NBSP}320–410")
        days = variable("days", (1, 2))
        self.assertEqual(render_variable(days, "", "it").text, f"1–2{NBSP}giorni")

    def test_forms(self) -> None:
        eur = variable("eur", ("320", "410"))
        self.assertEqual(render_variable(eur, "number", "it").text, "320–410")
        self.assertEqual(render_variable(eur, "min", "it").text, f"320{NBSP}euro")
        self.assertEqual(render_variable(eur, "max", "en").text, f"EUR{NBSP}410")
        days = variable("days", (1, 3))
        self.assertEqual(render_variable(days, "min", "it").text, f"1{NBSP}giorno")
        size = variable("tb", "4")
        rendered = render_variable(size, "number", "it")
        self.assertEqual(rendered.text, "4")
        self.assertTrue(rendered.mono)


class RolesTest(unittest.TestCase):
    def test_every_label_and_box_has_a_role_and_words(self) -> None:
        self.assertEqual(set(LABEL_ROLES), set(LABEL_TYPES))
        self.assertTrue(set(LABEL_ROLES.values()) <= set(THEME_ROLES))
        self.assertTrue(set(BOX_ROLES.values()) <= set(THEME_ROLES))
        for words in WORDS.values():
            self.assertEqual(set(words.labels), set(LABEL_TYPES))
            self.assertEqual(set(words.boxes), set(BOX_TYPES))
            self.assertEqual(words.boxes["status"], "")
            self.assertEqual(len(words.months), 12)


if __name__ == "__main__":
    unittest.main()
