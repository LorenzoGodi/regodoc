"""Prove sui due pacchetti d'esempio: entrambi validi, e il secondo usa tutto il vocabolario."""

import re
import tomllib
import unittest
from pathlib import Path

from regodoc import parts, tomlfiles
from regodoc.diagnostics import Collector, Severity
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, codes, example_files, validate_bytes

ROOT = Path(__file__).resolve().parent.parent
PARTS_SOURCE = (ROOT / "src" / "regodoc" / "parts.py").read_text(encoding="utf-8")


def attributes_in_code() -> set[str]:
    """Gli attributi che il controllore delle parti ammette, letti dalle sue chiamate."""
    found: set[str] = set()
    for group in re.findall(r"(?:required|optional) ?= ?\(([^)]*)\)", PARTS_SOURCE):
        found |= set(re.findall(r'"([a-z]+)"', group))
    return found


class Usage:
    """Che cosa usa un pacchetto d'esempio: elementi, attributi, valori e variabili."""

    def __init__(self, root: Path) -> None:
        self.elements: set[str] = set()
        self.attributes: set[str] = set()
        self.values: dict[str, set[str]] = {}
        self.has_comment = False
        for path in sorted((root / "parts").glob("*.xml")):
            data = path.read_bytes()
            self.has_comment |= b"<!--" in data
            # Il parser del motore stesso, con le sue difese.
            root_node = parts.parse_part(data, path.name, Collector())
            assert root_node is not None, path
            pending = [root_node]
            while pending:
                node = pending.pop()
                self.elements.add(node.tag)
                for name, value in node.attrs.items():
                    self.attributes.add(name)
                    self.values.setdefault(f"{node.tag}.{name}", set()).add(value)
                pending.extend(node.elements())
        self.structure = tomllib.loads((root / "structure.toml").read_text(encoding="utf-8"))
        self.variables = tomllib.loads((root / "variables.toml").read_text(encoding="utf-8"))

    def variable_types(self) -> set[str]:
        return {key for spec in self.variables.values() for key in spec if key != "note"}


class ExamplesAreValidTest(unittest.TestCase):
    def test_both_examples_are_valid_without_warnings(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            with self.subTest(root.name):
                validation = validate_bytes(build_zip(example_files(root)))
                self.assertEqual(codes(validation), [])

    def test_long_example_is_long(self) -> None:
        structure = Usage(LONG_EXAMPLE).structure
        self.assertGreaterEqual(len(structure["part"]), 8)
        self.assertGreaterEqual(len(structure["opening"]), 2)

    def test_no_info_warnings_either(self) -> None:
        validation = validate_bytes(build_zip(example_files(LONG_EXAMPLE)))
        self.assertFalse([d for d in validation.report.items if d.severity is Severity.INFO])


class VocabularyCoverageTest(unittest.TestCase):
    usage = Usage(LONG_EXAMPLE)

    def test_every_element(self) -> None:
        self.assertEqual(sorted(parts.ELEMENTS - self.usage.elements), [])

    def test_every_attribute(self) -> None:
        self.assertIn("through", attributes_in_code())
        self.assertEqual(sorted(attributes_in_code() - self.usage.attributes), [])

    def test_every_closed_value(self) -> None:
        groups = {
            "list.type": parts.LIST_TYPES,
            "box.type": parts.BOX_TYPES,
            "label.type": parts.LABEL_TYPES,
            "tone.type": parts.TONE_TYPES,
            "var.form": parts.VAR_FORMS,
            "table.orientation": parts.ORIENTATIONS,
            "row.type": ("total",),
        }
        for key, values in groups.items():
            with self.subTest(key):
                self.assertEqual(sorted(set(values) - self.usage.values.get(key, set())), [])

    def test_every_variable_type_and_shape(self) -> None:
        self.assertEqual(sorted(set(tomlfiles.VARIABLE_TYPES) - self.usage.variable_types()), [])
        specs = list(self.usage.variables.values())
        self.assertTrue(any("note" in spec for spec in specs), "una nota")
        self.assertTrue(
            any(isinstance(v, list) for spec in specs for v in spec.values()), "un intervallo"
        )
        negative = [v for spec in specs for v in spec.values() if str(v).startswith("-")]
        self.assertTrue(negative, "un valore negativo")
        self.assertIn(1, [v for spec in specs for k, v in spec.items() if k == "days"])

    def test_every_accent_and_header_key(self) -> None:
        structure = self.usage.structure
        self.assertEqual(
            sorted(set(tomlfiles.ACCENTS) - {p["accent"] for p in structure["part"]}), []
        )
        self.assertEqual(
            set(structure["header"]), {"title", "subject", "reference", "date", "version_label"}
        )
        self.assertIn("toc", structure)

    def test_languages_across_the_examples(self) -> None:
        used = {Usage(root).structure.get("language", "it") for root in (EXAMPLE, LONG_EXAMPLE)}
        self.assertEqual(used, set(tomlfiles.LANGUAGES))

    def test_comments_and_both_image_formats(self) -> None:
        self.assertTrue(self.usage.has_comment)
        images = {path.suffix for path in (LONG_EXAMPLE / "images").iterdir()}
        self.assertEqual(images, {".png", ".jpg"})

    def test_sources_in_groups_and_flat_across_the_examples(self) -> None:
        self.assertIn("group", self.usage.elements)
        self.assertNotIn("group", Usage(EXAMPLE).elements)
        self.assertIn("source", Usage(EXAMPLE).elements)


if __name__ == "__main__":
    unittest.main()
