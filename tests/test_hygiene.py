"""Prove del controllo d'igiene, con un termine vietato inventato per l'occasione."""

import hashlib
import importlib.util
import io
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

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
            [
                "metadati (PDF fuori dai flussi): contengono un nome vietato",
                "metadati (stringhe del PDF): contengono un nome vietato",
            ],
        )
        self.assertEqual(self.found("a.pdf", b"%PDF-1.5\n" + stream), [])

    def test_pdf_strings_in_utf16_and_hex(self) -> None:
        utf16 = "\ufeffproibito".encode("utf-16-be")
        octal = "".join(f"\\{byte:03o}" for byte in utf16).encode("ascii")
        for body in (
            b"1 0 obj << /Title <" + utf16.hex().encode() + b"> >> endobj",
            b"1 0 obj << /Title (" + octal + b") >> endobj",
        ):
            with self.subTest(body[:30]):
                self.assertEqual(
                    self.found("a.pdf", b"%PDF-1.5\n" + body),
                    ["metadati (stringhe del PDF): contengono un nome vietato"],
                )

    def test_pdf_xmp_stream_even_compressed(self) -> None:
        xmp = zlib.compress(b"<x:xmpmeta><pdf:Producer>proibito</pdf:Producer></x:xmpmeta>")
        body = (
            b"5 0 obj << /Type /Metadata /Subtype /XML /Filter /FlateDecode /Length "
            + str(len(xmp)).encode()
            + b" >> stream\n"
            + xmp
            + b"\nendstream endobj\n"
        )
        self.assertEqual(
            self.found("a.pdf", b"%PDF-1.5\n" + body),
            ["metadati (metadati XMP): contengono un nome vietato"],
        )
        # Un flusso che non è di metadati non si legge: è un limite dichiarato.
        page = body.replace(b"/Type /Metadata /Subtype /XML ", b"")
        self.assertEqual(self.found("a.pdf", b"%PDF-1.5\n" + page), [])

    def test_exif_in_utf16_and_bytes_after_the_end(self) -> None:
        def segment(marker: int, body: bytes) -> bytes:
            return bytes([0xFF, marker]) + (len(body) + 2).to_bytes(2, "big") + body

        jpeg = b"\xff\xd8" + segment(0xE1, b"Exif\0\0" + "proibito".encode("utf-16-le"))
        self.assertEqual(self.found("a.jpg", jpeg), ["metadati (APP1): contengono un nome vietato"])
        tail = b"\xff\xd8\xff\xda\x00\x02\x00\xff\xd9una frase vietata"
        self.assertEqual(
            self.found("a.jpg", tail),
            ["metadati (dopo la fine dell'immagine): contengono un nome vietato"],
        )
        png = png_with(b"tEXt", b"Software\0ok") + b"proibito"
        self.assertEqual(
            self.found("a.png", png),
            ["metadati (dopo la fine dell'immagine): contengono un nome vietato"],
        )

    def test_archive_entries_are_read(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("parts/a.xml", b"<p>una frase vietata</p>")
            archive.writestr("images/b.png", png_with(b"tEXt", b"Software\0proibito"))
        self.assertEqual(
            self.found("a.regodoc", buffer.getvalue()),
            [
                "metadati (voce parts/a.xml, testo): contengono un nome vietato",
                "metadati (voce images/b.png, tEXt): contengono un nome vietato",
            ],
        )

    def test_archive_names_and_comments(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("parts/proibito.xml", b"x")
        self.assertEqual(
            self.found("a.regodoc", buffer.getvalue()),
            ["metadati (nome di una voce): contengono un nome vietato"],
        )

    def test_pdf_compressed_object_streams(self) -> None:
        title = "\ufeffuna frase vietata".encode("utf-16-be").hex().encode()
        for inner, blocks in (
            (b"1 0 obj << /Producer (proibito) >> endobj", ["oggetti compressi", "stringhe"]),
            (b"7 0 obj << /Title <" + title + b"> /Parent 6 0 R >>", ["stringhe"]),
        ):
            packed = zlib.compress(inner)
            body = (
                b"9 0 obj << /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /Length "
                + str(len(packed)).encode()
                + b" >> stream\n"
                + packed
                + b"\nendstream endobj\n"
            )
            names = {
                "oggetti compressi": "metadati (oggetti compressi del PDF)",
                "stringhe": "metadati (stringhe degli oggetti compressi)",
            }
            with self.subTest(inner[:20]):
                self.assertEqual(
                    self.found("a.pdf", b"%PDF-1.5\n" + body),
                    [f"{names[b]}: contengono un nome vietato" for b in blocks],
                )

    def test_pdf_hex_string_before_the_end_of_a_dictionary(self) -> None:
        title = "\ufeffproibito".encode("utf-16-be").hex().encode()
        for body in (
            b"1 0 obj << /Title <" + title + b">>> endobj",
            b"1 0 obj <<<" + title + b"> /A 1 >> endobj",
        ):
            with self.subTest(body[:16]):
                self.assertEqual(
                    self.found("a.pdf", b"%PDF-1.5\n" + body),
                    ["metadati (stringhe del PDF): contengono un nome vietato"],
                )

    def test_pdf_hex_string_after_an_isolated_less_than(self) -> None:
        # Un < che non apre una stringa esadecimale non deve far perdere quella che segue.
        title = "\ufeffproibito".encode("utf-16-be").hex().encode()
        for body in (
            b"1 0 obj << /Subject (a<b) /Title <" + title + b"> >> endobj",
            b"% x<y\n1 0 obj << /Title <" + title + b"> >> endobj",
        ):
            with self.subTest(body[:20]):
                self.assertEqual(
                    self.found("a.pdf", b"%PDF-1.5\n" + body),
                    ["metadati (stringhe del PDF): contengono un nome vietato"],
                )

    def test_pdf_literal_continued_on_the_next_line(self) -> None:
        for newline in (b"\n", b"\r\n", b"\r"):
            with self.subTest(newline):
                body = b"1 0 obj << /Author (proi\\" + newline + b"bito) >> endobj"
                self.assertEqual(
                    self.found("a.pdf", b"%PDF-1.5\n" + body),
                    ["metadati (stringhe del PDF): contengono un nome vietato"],
                )

    def test_encrypted_or_unsupported_entries_are_reported(self) -> None:
        # Le voci si scrivono normali e poi si cambiano i campi nell'intestazione locale e in
        # quella centrale: zipfile non scrive né voci cifrate né metodi che non conosce.
        def patched(name: str, local: int, central: int, value: int) -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(name, b"x")
            data = bytearray(buffer.getvalue())
            for header, offset in ((b"PK\x03\x04", local), (b"PK\x01\x02", central)):
                start = data.find(header) + offset
                data[start : start + 2] = value.to_bytes(2, "little")
            return bytes(data)

        self.assertEqual(
            self.found("a.regodoc", patched("parts/a.xml", 6, 8, 0x1)),
            ["metadati non leggibili: voce parts/a.xml cifrata"],
        )
        self.assertEqual(
            self.found("a.zip", patched("parts/b.xml", 8, 10, 99)),
            [
                "metadati non leggibili: voce parts/b.xml con un metodo di compressione "
                "non supportato"
            ],
        )

    def test_broken_bzip2_entry_is_reported(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_BZIP2) as archive:
            archive.writestr("parts/c.xml", b"<p>testo di prova</p>" * 50)
        data = bytearray(buffer.getvalue())
        start = data.find(b"BZh") + 10
        data[start : start + 8] = b"\x00" * 8
        self.assertEqual(
            self.found("a.regodoc", bytes(data)),
            ["metadati non leggibili: voce parts/c.xml con dati rotti (OSError)"],
        )

    def test_large_entry_is_read_up_to_the_limit(self) -> None:
        # Con il limite abbassato a 16 byte: della voce si leggono i primi 16, non la si
        # salta; un nome dopo il limite resta fuori.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("parts/d.xml", b"<p>proibito</p>" + b" " * 100)
            archive.writestr("parts/e.xml", b" " * 100 + b"<p>proibito</p>")
        with mock.patch.object(hygiene, "_MAX_ENTRY", 16):
            self.assertEqual(
                self.found("a.regodoc", buffer.getvalue()),
                ["metadati (voce parts/d.xml, testo): contengono un nome vietato"],
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
