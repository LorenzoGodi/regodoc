"""Prove del README.md generato nel pacchetto (specifica, §1.4)."""

import tomllib
import unittest

from regodoc.declaration import CONTENT_LIMITS
from regodoc.readme import render_readme
from regodoc.tomlfiles import LANGUAGES
from tests.support import EXAMPLE, LONG_EXAMPLE


class ReadmeTest(unittest.TestCase):
    def test_examples_carry_the_generated_readme(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            with self.subTest(root.name):
                structure = tomllib.loads((root / "structure.toml").read_text(encoding="utf-8"))
                expected = render_readme(
                    structure["header"]["title"], structure.get("language", "it")
                )
                self.assertEqual((root / "README.md").read_text(encoding="utf-8"), expected)

    def test_every_language_and_the_limit(self) -> None:
        for language in LANGUAGES:
            text = render_readme("x" * 200, language)
            self.assertLess(len(text.encode()), CONTENT_LIMITS["readme_bytes"])
            self.assertTrue(text.endswith("\n"))
            self.assertNotIn("\r", text)

    def test_the_title_cannot_change_the_markdown(self) -> None:
        text = render_readme("Costi *stimati* <b> #1 [a](b) `x` | y\\", "it")
        first = text.split("\n", 1)[0]
        self.assertEqual(
            first,
            r"# Pacchetto .regodoc: Costi \*stimati\* \<b\> \#1 \[a\](b) \`x\` \| y\\",
        )

    def test_deterministic(self) -> None:
        self.assertEqual(render_readme("T", "en"), render_readme("T", "en"))


if __name__ == "__main__":
    unittest.main()
