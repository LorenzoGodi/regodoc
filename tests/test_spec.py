"""Prove di coerenza fra la specifica rego/1 e il codice del validatore.

La specifica e il validatore nascono dalle stesse tabelle: queste prove falliscono se uno
dei due nomina un elemento, un attributo, un valore chiuso o un limite che l'altro non ha.
"""

import re
import unittest
from pathlib import Path

from regodoc import declaration, parts, source, tomlfiles

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "docs" / "spec" / "rego-1.md").read_text(encoding="utf-8")
EXAMPLE = ROOT / "examples" / "colle-rovere"


def section(title_start: str) -> str:
    """Il testo di un paragrafo della specifica, dal suo titolo al titolo successivo."""
    start = SPEC.index(f"\n## {title_start}")
    end = SPEC.find("\n## ", start + 1)
    return SPEC[start : end if end > 0 else len(SPEC)]


class ExampleInSpecTest(unittest.TestCase):
    def test_example_blocks_match_files(self) -> None:
        text = section("11.")
        for name in ("structure.toml", "parts/backup.xml"):
            with self.subTest(name):
                match = re.search(rf"`{re.escape(name)}`\n\n```\w+\n(.*?)```", text, re.S)
                assert match is not None, name
                self.assertEqual(match.group(1), (EXAMPLE / name).read_text(encoding="utf-8"))

    def test_mimetype(self) -> None:
        self.assertIn(source.MIMETYPE.decode(), section("1."))
        self.assertEqual((EXAMPLE / "mimetype").read_bytes(), source.MIMETYPE)


class VocabularyInSpecTest(unittest.TestCase):
    def test_every_element_is_specified(self) -> None:
        text = section("4.")
        for element in sorted(parts.ELEMENTS):
            with self.subTest(element):
                self.assertRegex(text, rf"<{element}[ />]")

    def test_every_element_is_in_the_name_table(self) -> None:
        text = section("Appendice A.")
        for element in sorted(parts.ELEMENTS):
            with self.subTest(element):
                self.assertRegex(text, rf"[|,] `<{element}[ />`]")

    def test_closed_values(self) -> None:
        text = SPEC
        groups = {
            "accent": tomlfiles.ACCENTS,
            "language": tomlfiles.LANGUAGES,
            "list": parts.LIST_TYPES,
            "box": parts.BOX_TYPES,
            "label": parts.LABEL_TYPES,
            "tone": parts.TONE_TYPES,
            "form": parts.VAR_FORMS,
            "orientation": parts.ORIENTATIONS,
            "types": tomlfiles.VARIABLE_TYPES,
        }
        for name, values in groups.items():
            for value in values:
                with self.subTest(f"{name}={value}"):
                    self.assertIn(f"`{value}`", text)

    def test_limits_are_in_the_spec(self) -> None:
        text = section("7.")
        expected = {
            "compressed_bytes": "12 MiB",
            "expanded_bytes": "40 MiB",
            "files": "| 200 |",
            "parts": "| 48 |",
            "part_bytes": "384 KiB",
            "characters": "1.500.000",
            "variables": "1.500",
            "table_rows": "600 righe",
            "image_side_pixels": "6.000 × 6.000",
        }
        for key, needle in expected.items():
            with self.subTest(key):
                self.assertIn(key, {**declaration.ENVELOPE_LIMITS, **declaration.CONTENT_LIMITS})
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
