"""Prove del controllo d'igiene, con un termine vietato inventato per l'occasione."""

import hashlib
import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "tools" / "check_hygiene.py"
_SPEC = importlib.util.spec_from_file_location("check_hygiene", _PATH)
assert _SPEC and _SPEC.loader
hygiene = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hygiene)

TERMS = frozenset(
    {
        hashlib.sha256(b"parolaproibita").hexdigest(),
        hashlib.sha256(b"frase vietata qui").hexdigest(),
    }
)


def messages(problems: list) -> list[str]:
    return [p.message for p in problems]


class TermTest(unittest.TestCase):
    def test_hash_normalizes(self) -> None:
        self.assertEqual(
            hygiene.term_hash("  Frase-VIETATA  qui\n"), hygiene.term_hash("frase vietata qui")
        )

    def test_single_word_any_case(self) -> None:
        self.assertEqual(hygiene.find_terms("ok\nUna ParolaProibita.\n", TERMS), [2])

    def test_phrase_with_punctuation(self) -> None:
        self.assertEqual(hygiene.find_terms("frase-vietata: qui", TERMS), [1])

    def test_phrase_across_lines(self) -> None:
        self.assertEqual(hygiene.find_terms("una frase\nvietata qui\n", TERMS), [1])

    def test_term_on_next_line_is_not_reported_twice(self) -> None:
        self.assertEqual(hygiene.find_terms("prima\nparolaproibita\n", TERMS), [2])

    def test_substring_is_not_a_word(self) -> None:
        self.assertEqual(hygiene.find_terms("parolaproibitamente", TERMS), [])

    def test_repository_terms_file_is_hashes_only(self) -> None:
        for line in hygiene.TERMS_FILE.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[0-9a-f]{64}$")


class TextTest(unittest.TestCase):
    def check(self, data: bytes, tabs: bool = False) -> list[str]:
        return messages(hygiene.check_text("f", data, TERMS, tabs=tabs))

    def test_clean(self) -> None:
        self.assertEqual(self.check("Perché «sì».\n".encode()), [])

    def test_not_utf8(self) -> None:
        self.assertEqual(self.check(b"caff\xe8\n"), ["non è UTF-8 valido (byte 4)"])

    def test_crlf(self) -> None:
        self.assertIn("fine riga CR", self.check(b"a\r\nb\n"))

    def test_final_newline(self) -> None:
        self.assertEqual(self.check(b"a"), ["manca l'a capo finale"])

    def test_trailing_space(self) -> None:
        self.assertEqual(self.check(b"a \n"), ["spazi in fondo alla riga"])

    def test_bidi(self) -> None:
        found = self.check("a\u202eb\n".encode())
        self.assertEqual(found, ["carattere invisibile RIGHT-TO-LEFT OVERRIDE"])

    def test_bom(self) -> None:
        self.assertIn("comincia con un BOM", self.check("\ufeffa\n".encode()))

    def test_tabs(self) -> None:
        self.assertEqual(self.check(b"\ta\n"), ["tabulazione"])
        self.assertEqual(self.check(b"\ta\n", tabs=True), [])

    def test_control(self) -> None:
        self.assertEqual(self.check(b"a\x07\n"), ["carattere di controllo U+0007"])

    def test_term(self) -> None:
        self.assertEqual(self.check(b"parolaproibita\n"), ["contiene un nome vietato"])


class MessageTest(unittest.TestCase):
    def check(self, message: str) -> list[str]:
        return messages(hygiene.check_message("c", message, TERMS))

    def test_good(self) -> None:
        self.assertEqual(self.check("L1: impalcatura del pacchetto\n\nCorpo in italiano.\n"), [])

    def test_first_line(self) -> None:
        self.assertEqual(
            self.check("impalcatura\n"), ["la prima riga deve cominciare con il lotto, «Ln: »"]
        )

    def test_trailer(self) -> None:
        found = self.check("L1: x\n\nCorpo.\n\nRevisionato-da: Qualcuno <q@example.com>\n")
        self.assertEqual(found, ["trailer non ammesso: Revisionato-da: Qualcuno <q@example.com>"])

    def test_hash_line(self) -> None:
        self.assertEqual(self.check("L1: x\n\n# titolo\n"), ["riga che comincia con #"])

    def test_closing_keyword(self) -> None:
        self.assertEqual(
            self.check("L1: x\n\nFixes #12 e altro.\n"),
            ["parola di chiusura con riferimento a issue"],
        )
        self.assertEqual(self.check("L1: x\n\nSi veda la issue 12.\n"), [])

    def test_term(self) -> None:
        self.assertEqual(self.check("L1: x\n\nparolaproibita\n"), ["contiene un nome vietato"])


if __name__ == "__main__":
    unittest.main()
