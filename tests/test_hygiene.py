"""Prove del controllo d'igiene, con un termine vietato inventato per l'occasione."""

import hashlib
import importlib.util
import io
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "tools" / "check_hygiene.py"
_SPEC = importlib.util.spec_from_file_location("check_hygiene", _PATH)
assert _SPEC and _SPEC.loader
hygiene = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hygiene)

TERMS = hygiene.Terms(
    substrings={
        len("proibito"): frozenset({hashlib.sha256(b"proibito").digest()}),
        len("frase vietata"): frozenset({hashlib.sha256(b"frase vietata").digest()}),
    },
    words=frozenset({hashlib.sha256(b"rara").digest()}),
)


def messages(problems: list) -> list[str]:
    return [p.message for p in problems]


class TermTest(unittest.TestCase):
    def test_line_normalizes(self) -> None:
        self.assertEqual(
            hygiene.term_line("  Frase-VIETATA\n"),
            hygiene.term_line("frase vietata"),
        )
        self.assertTrue(hygiene.term_line("rara", word=True).startswith("w 4 "))

    def test_substring_inside_word(self) -> None:
        self.assertEqual(hygiene.find_terms("ok\nnon è improibitoso\n", TERMS), [2])

    def test_any_case(self) -> None:
        self.assertEqual(hygiene.find_terms("PROIBITO", TERMS), [1])

    def test_phrase_with_punctuation(self) -> None:
        self.assertEqual(hygiene.find_terms("frase-vietata: qui", TERMS), [1])

    def test_phrase_across_lines(self) -> None:
        self.assertEqual(hygiene.find_terms("una frase\nvietata qui\n", TERMS), [1])

    def test_term_on_next_line_is_not_reported_twice(self) -> None:
        self.assertEqual(hygiene.find_terms("prima\nproibito\n", TERMS), [2])

    def test_word_mode_only_whole_words(self) -> None:
        self.assertEqual(hygiene.find_terms("una rara occasione", TERMS), [1])
        self.assertEqual(hygiene.find_terms("bizzarra, rarità", TERMS), [])

    def test_word_mode_splits_letters_from_digits(self) -> None:
        self.assertEqual(hygiene.find_terms("versione rara2 e rara-3", TERMS), [1])
        self.assertEqual(hygiene.find_terms("rarità2", TERMS), [])

    def test_repository_terms_file_format(self) -> None:
        terms = hygiene.load_terms()
        self.assertTrue(terms.substrings)
        for line in hygiene.TERMS_FILE.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[sw] [1-9]\d* [0-9a-f]{64}$")


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

    def test_soft_hyphen(self) -> None:
        self.assertEqual(self.check("a\u00adb\n".encode()), ["carattere invisibile SOFT HYPHEN"])

    def test_bom(self) -> None:
        self.assertIn("comincia con un BOM", self.check("\ufeffa\n".encode()))

    def test_tabs(self) -> None:
        self.assertEqual(self.check(b"\ta\n"), ["tabulazione"])
        self.assertEqual(self.check(b"\ta\n", tabs=True), [])

    def test_control(self) -> None:
        self.assertEqual(self.check(b"a\x07\n"), ["carattere di controllo U+0007"])

    def test_term(self) -> None:
        self.assertEqual(self.check(b"parolaproibito\n"), ["contiene un nome vietato"])


class FileTest(unittest.TestCase):
    def test_symlink_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "vero.txt").write_text("ok\n")
            (root / "link.txt").symlink_to("vero.txt")
            found = messages(hygiene.check_file(root, "link.txt", TERMS))
        self.assertEqual(found, ["è un collegamento simbolico: non è ammesso"])


class IdentityTest(unittest.TestCase):
    def test_identity(self) -> None:
        good = hygiene.EXPECTED_IDENTITY
        commit = hygiene.Commit("abc", good, good, "L1: x")
        self.assertEqual(hygiene.check_identity("c", commit), [])
        other = hygiene.Commit("abc", "Qualcuno <q@example.com>", good, "L1: x")
        self.assertEqual(
            messages(hygiene.check_identity("c", other)),
            [f"autore «Qualcuno <q@example.com>» diverso da «{good}»"],
        )
        web = hygiene.Commit("abc", good, "GitHub <noreply@github.com>", "L1: x")
        self.assertEqual(len(hygiene.check_identity("c", web)), 1)


FIRST_LINE = (
    "la prima riga deve cominciare con il lotto, «Ln: » o «An: », "
    "o con «contratto: » o «specifica: »"
)


class MessageTest(unittest.TestCase):
    def check(self, message: str) -> list[str]:
        return messages(hygiene.check_message("c", message, TERMS))

    def test_good(self) -> None:
        self.assertEqual(self.check("L1: impalcatura del pacchetto\n\nCorpo in italiano.\n"), [])

    def test_first_line(self) -> None:
        self.assertEqual(
            self.check("impalcatura\n"),
            [FIRST_LINE],
        )
        self.assertEqual(self.check("A11: revisione\n"), [])
        self.assertEqual(self.check("contratto: nota del §4.2\n"), [])
        self.assertEqual(self.check("specifica: nota del §9\n"), [])
        self.assertEqual(self.check("Contratto: nota\n"), [FIRST_LINE])
        self.assertEqual(
            self.check("B2: altro\n"),
            [FIRST_LINE],
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
        self.assertEqual(self.check("L1: x\n\nparolaproibito\n"), ["contiene un nome vietato"])


def png_with(kind: bytes, body: bytes) -> bytes:
    """Un PNG minimo con un blocco di metadati in più, prima dei pixel."""

    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + name + data + crc.to_bytes(4, "big")

    header = (1).to_bytes(4, "big") * 2 + bytes([8, 0, 0, 0, 0])
    pixels = zlib.compress(b"\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(kind, body)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


class BinaryMetadataTest(unittest.TestCase):
    def found(self, name: str, data: bytes) -> list[str]:
        return messages(hygiene.check_binary(name, Path(name).suffix, data, TERMS))

    def test_png_text_blocks(self) -> None:
        cases = {
            b"tEXt": b"Software\0proibito 1.0",
            b"zTXt": b"Comment\0\0" + zlib.compress(b"una frase vietata"),
            b"iTXt": b"XML:com.adobe.xmp\0\0\0\0\0<x>proibito</x>",
            b"eXIf": b"MM\0*proibito",
        }
        for kind, body in cases.items():
            with self.subTest(kind):
                self.assertEqual(
                    self.found("a.png", png_with(kind, body)),
                    [f"metadati ({kind.decode()}): contengono un nome vietato"],
                )
        self.assertEqual(self.found("a.png", png_with(b"tEXt", b"Software\0innocuo")), [])

    def test_jpeg_comment_and_app_segments(self) -> None:
        def segment(marker: int, body: bytes) -> bytes:
            return bytes([0xFF, marker]) + (len(body) + 2).to_bytes(2, "big") + body

        jpeg = b"\xff\xd8" + segment(0xE1, b"Exif\0\0proibito") + segment(0xFE, b"ok")
        self.assertEqual(self.found("a.jpg", jpeg), ["metadati (APP1): contengono un nome vietato"])
        jpeg = b"\xff\xd8" + segment(0xFE, b"frase vietata") + b"\xff\xda\x00\x02proibito"
        self.assertEqual(self.found("a.jpeg", jpeg), ["metadati (COM): contengono un nome vietato"])

    def test_pdf_outside_streams(self) -> None:
        info = b"1 0 obj << /Producer (proibito) >> endobj\n"
        stream = b"2 0 obj << /Length 8 >> stream\nproibito\nendstream endobj\n"
        self.assertEqual(
            self.found("a.pdf", b"%PDF-1.5\n" + info),
            ["metadati (PDF): contengono un nome vietato"],
        )
        self.assertEqual(self.found("a.pdf", b"%PDF-1.5\n" + stream), [])

    def test_archive_names_and_comments(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("parts/proibito.xml", b"x")
        self.assertEqual(
            self.found("a.regodoc", buffer.getvalue()),
            ["metadati (nome di una voce): contengono un nome vietato"],
        )

    def test_unreadable_metadata_is_reported(self) -> None:
        self.assertEqual(
            self.found("a.zip", b"non un archivio"),
            ["metadati non leggibili: BadZipFile"],
        )

    def test_repository_images_are_clean(self) -> None:
        root = Path(__file__).resolve().parent.parent
        for path in sorted((root / "examples").rglob("images/*")):
            with self.subTest(path.name):
                self.assertEqual(
                    hygiene.check_binary(path.name, path.suffix, path.read_bytes(), TERMS), []
                )


if __name__ == "__main__":
    unittest.main()
