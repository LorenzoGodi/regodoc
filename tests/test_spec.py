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


def subsection(number: str) -> str:
    """Il testo di un sottoparagrafo («5.4») della specifica, fino al titolo successivo."""
    start = SPEC.index(f"\n### {number} ")
    ends = [SPEC.find(marker, start + 1) for marker in ("\n## ", "\n### ")]
    return SPEC[start : min(end for end in ends if end > 0)]


def emitted_codes() -> set[str]:
    """Tutti i codici scritti come stringa nei sorgenti del motore."""
    found: set[str] = set()
    for path in (ROOT / "src" / "regodoc").glob("*.py"):
        text = path.read_text("utf-8")
        found |= set(re.findall(r'"(regodoc\.[a-z0-9_]+(?:\.[a-z0-9_]+)?)"', text))
    return found - {"regodoc.sty"}  # il nome di un file, non un codice


class CodeIndexTest(unittest.TestCase):
    def test_every_emitted_code_is_in_the_index(self) -> None:
        indexed = set(re.findall(r"^\| `(regodoc\.[a-z0-9_.]+)` \|", subsection("8.1"), re.M))
        self.assertGreater(len(indexed), 100)
        self.assertEqual(sorted(emitted_codes() - indexed), [], "codici senza regola nel §8.1")
        self.assertEqual(sorted(indexed - emitted_codes()), [], "codici del §8.1 mai emessi")

    def test_every_index_row_cites_a_rule(self) -> None:
        for code, rule in re.findall(r"^\| `(regodoc\.[a-z0-9_.]+)` \| (.+) \|$", SPEC, re.M):
            with self.subTest(code):
                self.assertRegex(rule, r"§\d|contratto")


class LimitKeysTest(unittest.TestCase):
    def test_section_7_names_every_info_key(self) -> None:
        documented = set(re.findall(r"`((?:envelope|content)\.[a-z_]+)`", section("7.")))
        declared = {f"envelope.{k}" for k in declaration.ENVELOPE_LIMITS} | {
            f"content.{k}" for k in declaration.CONTENT_LIMITS
        }
        self.assertEqual(documented, declared)

    def test_readme_limit(self) -> None:
        self.assertEqual(declaration.CONTENT_LIMITS["readme_bytes"], 64 * 1024)
        self.assertRegex(section("7."), r"\| `README.md` \| 64 KiB.*`regodoc.limit.file_size`")

    def test_raw_spaces_count_for_code_address_and_source(self) -> None:
        self.assertIn("con i loro spazi così come sono scritti", subsection("7.2"))

    def test_reduced_font_only_in_portrait(self) -> None:
        self.assertIn("oltre 8 colonne in carattere ridotto, solo in verticale", section("7."))


class TextRulesInSpecTest(unittest.TestCase):
    def test_address_has_its_own_row(self) -> None:
        self.assertIn(
            "| contenuto di `<address>` | errore (`regodoc.text.char`) "
            "| errore (`regodoc.text.char`) |",
            subsection("5.1"),
        )

    def test_plain_text_code_is_defined(self) -> None:
        text = subsection("5.3")
        for code in ("regodoc.text.dashes", "regodoc.text.quotes", "regodoc.text.plain"):
            self.assertIn(f"`{code}`", text)
        self.assertIn("nel **testo puro**", text)

    def test_greater_than_after_brackets(self) -> None:
        self.assertIn("`&gt;` subito dopo `]]`", subsection("5.4"))
        self.assertIn("`&gt;` subito dopo `]]`", section("9."))
        self.assertIn("un elemento per riga", section("9."))

    def test_date_from_instant(self) -> None:
        text = section("2.")
        flat = " ".join(text.split())
        self.assertIn("la data stampata è il giorno di calendario **in quel fuso**", flat)
        self.assertIn("la data stampata è il giorno di calendario **in UTC**", flat)
        self.assertIn("numero intero **non negativo**", flat)

    def test_collect_and_continue_from_step_7(self) -> None:
        text = section("6.")
        self.assertIn("**Dal passo 7 in poi**", text)
        flat = " ".join(text.split())
        self.assertIn("i suoi richiami non danno `regodoc.xml.unknown_variable`", flat)
        self.assertIn("Fermano la lettura solo questi casi, ed è l'elenco completo", flat)
        self.assertIn('`format` manca o non vale `"regodoc"`', flat)
        self.assertIn("**il pacchetto è letto per intero**", flat)


class ExampleVariablesTest(unittest.TestCase):
    def test_variables_block_matches_the_example(self) -> None:
        match = re.search(r"```toml\n(.*?)```", section("3."), re.S)
        assert match is not None
        self.assertEqual(match.group(1), (EXAMPLE / "variables.toml").read_text(encoding="utf-8"))

    def test_every_variable_name_in_the_spec_exists(self) -> None:
        names = set(re.findall(r'<var name="([A-Za-z0-9]+)"', SPEC))
        example = (EXAMPLE / "variables.toml").read_text(encoding="utf-8")
        for name in sorted(names):
            with self.subTest(name):
                self.assertRegex(example, rf"(?m)^{name} = ")


if __name__ == "__main__":
    unittest.main()
