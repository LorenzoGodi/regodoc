"""Il controllo delle figure in PDF vettoriale (pdffigure.py): che cosa passa e perché il resto
è rifiutato, con PDF sintetici scritti a mano."""

import random
import time
import unittest
import zlib

from regodoc import compiler, pdffigure
from tests.support import DRAWING, pdf, stream
from tests.support import pdf_figure as figure


def with_font(font: bytes, *more: tuple[int, bytes]) -> dict[int, bytes]:
    objects = figure(
        resources=b"/Font << /F1 5 0 R >>", content=b"BT /F1 12 Tf 10 10 Td (Ciao) Tj ET"
    )
    objects[5] = font
    objects.update(dict(more))
    return objects


EMBEDDED = with_font(
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Sintetico /FontDescriptor 6 0 R >>",
    (6, b"<< /Type /FontDescriptor /FontName /Sintetico /FontFile3 7 0 R >>"),
    (7, stream(b"dati del font", b"/Subtype /Type1C ")),
)


def code(data: bytes) -> str | None:
    try:
        pdffigure.check(data)
    except pdffigure.Problem as problem:
        return problem.code
    return None


class AcceptedTest(unittest.TestCase):
    def test_a_one_page_drawing(self) -> None:
        self.assertIsNone(code(pdf(figure())))

    def test_versions_and_line_endings(self) -> None:
        for version in (b"1.0", b"1.7", b"2.0"):
            with self.subTest(version):
                self.assertIsNone(code(pdf(figure(), version=version)))
        self.assertIsNone(code(pdf(figure(), newline=b"\r\n")))

    def test_embedded_fonts(self) -> None:
        self.assertIsNone(code(pdf(EMBEDDED)))
        type3 = with_font(
            b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1 1] /FontMatrix [1 0 0 1 0 0] "
            b"/CharProcs << /a 6 0 R >> /Encoding << /Differences [97 /a] >> "
            b"/FirstChar 97 /LastChar 97 /Widths [1] >>",
            (6, stream(b"0 0 1 1 re f")),
        )
        self.assertIsNone(code(pdf(type3)))
        type0 = with_font(
            b"<< /Type /Font /Subtype /Type0 /BaseFont /Sintetico /Encoding /Identity-H "
            b"/DescendantFonts [6 0 R] >>",
            (
                6,
                b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /S /FontDescriptor 7 0 R >>",
            ),
            (7, b"<< /Type /FontDescriptor /FontName /Sintetico /FontFile2 8 0 R >>"),
            (8, stream(b"dati del font")),
        )
        self.assertIsNone(code(pdf(type0)))

    def test_allowed_filters(self) -> None:
        for body, extra in (
            (DRAWING.hex().encode() + b">", b"/Filter /ASCIIHexDecode "),
            (b"<~" + __import__("base64").a85encode(DRAWING) + b"~>", b"/Filter /ASCII85Decode "),
            (bytes([len(DRAWING) - 1]) + DRAWING + b"\x80", b"/Filter /RunLengthDecode "),
            (b"\xff\xd8\xff\xd9", b"/Filter /DCTDecode "),
            (
                zlib.compress(DRAWING.hex().encode() + b">"),
                b"/Filter [/FlateDecode /ASCIIHexDecode] ",
            ),
        ):
            with self.subTest(extra):
                objects = figure()
                objects[5] = stream(body, extra)
                self.assertIsNone(code(pdf(objects)))


class RefusedTest(unittest.TestCase):
    def test_the_output_names_are_refused_too(self) -> None:
        # I nomi che il motore non lascia uscire nel suo PDF non entrano neppure da una figura;
        # /ObjStm è un errore di struttura.
        self.assertLessEqual(compiler.ACTIVE_NAMES - {"ObjStm"}, pdffigure.ACTIVE)

    def test_structure(self) -> None:
        good = pdf(figure())
        xref = good.rindex(b"\nxref") + 1
        cases = {
            "senza intestazione": good[good.index(b"\n") + 1 :],
            "versione 3.0": good.replace(b"%PDF-1.4", b"%PDF-3.0", 1),
            "senza %%EOF": good.replace(b"%%EOF", b""),
            "dati dopo %%EOF": good + b"altro",
            "startxref sbagliato": good.replace(
                b"startxref\n%d" % xref, b"startxref\n%d" % (xref - 3)
            ),
            "xref spostata": good[:xref] + b" " + good[xref:],
            "cifrato": pdf(figure(), trailer=b"/Encrypt 9 0 R "),
            "più revisioni": pdf(figure(), trailer=b"/Prev 9 "),
            "flusso xref": pdf(figure(), trailer=b"/XRefStm 9 "),
            "flusso di oggetti": pdf(
                {**figure(), 5: stream(b"1 0", b"/Type /ObjStm /N 1 /First 4 ")}
            ),
            "lunghezza sbagliata": pdf(
                {**figure(), 5: b"<< /Length 99 >>\nstream\nabc\nendstream"}
            ),
            "stringa aperta": pdf({**figure(), 5: b"(non chiusa"}),
            "oggetto all'offset sbagliato": pdf(figure()).replace(b"3 0 obj", b"7 0 obj", 1),
            "MediaBox assente": pdf(
                {**figure(), 3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R /Resources << >> >>"}
            ),
            "pagina enorme": pdf(
                {
                    **figure(),
                    3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 9000 10] /Contents 4 0 R >>",
                }
            ),
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.assertEqual(code(data), "regodoc.image.pdf_structure")

    def test_one_page_only(self) -> None:
        two = figure()
        two[2] = b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>"
        two[5] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] >>"
        self.assertEqual(code(pdf(two)), "regodoc.image.pdf_pages")
        lying = figure()
        lying[2] = b"<< /Type /Pages /Kids [3 0 R 3 0 R] /Count 1 >>"
        self.assertEqual(code(pdf(lying)), "regodoc.image.pdf_pages")

    def test_active_and_hidden_content(self) -> None:
        for name in sorted(pdffigure.ACTIVE):
            with self.subTest(name):
                written = name.encode()
                self.assertEqual(
                    code(pdf(figure(page_extra=b"/" + written + b" 1 "))),
                    "regodoc.image.pdf_active",
                )
        # Anche con un carattere scritto come #XX.
        self.assertEqual(code(pdf(figure(page_extra=b"/J#53 1 "))), "regodoc.image.pdf_active")
        self.assertEqual(
            code(
                pdf(
                    {
                        **figure(),
                        1: b"<< /Type /Catalog /Pages 2 0 R /OpenAction 5 0 R >>",
                        5: b"<< /S /JavaScript /JS (app.alert(1)) >>",
                    }
                )
            ),
            "regodoc.image.pdf_active",
        )

    def test_fonts_must_be_embedded(self) -> None:
        cases = [
            with_font(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
            with_font(
                b"<< /Type /Font /Subtype /TrueType /BaseFont /Arial /FontDescriptor 6 0 R >>",
                (6, b"<< /Type /FontDescriptor /FontName /Arial >>"),
            ),
            with_font(b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1 1] >>"),
            with_font(b"<< /Type /Font /Subtype /Type0 /BaseFont /X /DescendantFonts [] >>"),
        ]
        for objects in cases:
            with self.subTest(objects[5][:40]):
                self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_font")

    def test_filters(self) -> None:
        for name in ("JBIG2Decode", "JPXDecode", "LZWDecode", "CCITTFaxDecode", "Crypt", "Altro"):
            with self.subTest(name):
                objects = figure()
                objects[5] = stream(b"x", b"/Filter /" + name.encode() + b" ")
                self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_filter")
        objects = figure()
        objects[5] = stream(b"non zlib", b"/Filter /FlateDecode ")
        self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_structure")

    def test_metadata(self) -> None:
        self.assertEqual(
            code(pdf({**figure(), 5: stream(b"<x:xmpmeta/>", b"/Type /Metadata /Subtype /XML ")})),
            "regodoc.image.pdf_metadata",
        )
        self.assertEqual(
            code(pdf(figure(page_extra=b"/PieceInfo << >> "))), "regodoc.image.pdf_metadata"
        )
        self.assertEqual(
            code(
                pdf(
                    {**figure(), 5: b"<< /Producer (Strumento 1.0) /Author (Qualcuno) >>"},
                    trailer=b"/Info 5 0 R ",
                )
            ),
            "regodoc.image.pdf_metadata",
        )
        self.assertIsNone(code(pdf({**figure(), 5: b"<< >>"}, trailer=b"/Info 5 0 R ")))


class LimitsTest(unittest.TestCase):
    def test_size(self) -> None:
        # Al limite passa, un byte oltre no: il riempimento è una stringa dentro un oggetto.
        def sized(total: int) -> bytes:
            # Il numero dopo startxref si allunga con il file: si corregge una seconda volta.
            data = b""
            filler = total - len(pdf({**figure(), 5: b"()"}))
            for _ in range(2):
                data = pdf({**figure(), 5: b"(" + b"x" * filler + b")"})
                filler -= len(data) - total
            return data

        self.assertEqual(len(sized(pdffigure.MAX_BYTES)), pdffigure.MAX_BYTES)
        self.assertIsNone(code(sized(pdffigure.MAX_BYTES)))
        self.assertEqual(code(sized(pdffigure.MAX_BYTES + 1)), "regodoc.limit.pdf")

    def test_objects(self) -> None:
        # Gli oggetti da 1 a MAX_OBJECTS; la riga 0 della tabella xref non è un oggetto.
        def objects(last: int) -> dict[int, bytes]:
            return {**figure(), **{n: b"0" for n in range(5, last + 1)}}

        self.assertIsNone(code(pdf(objects(pdffigure.MAX_OBJECTS))))
        self.assertEqual(code(pdf(objects(pdffigure.MAX_OBJECTS + 1))), "regodoc.limit.pdf")

    def test_stream_bytes(self) -> None:
        # Contano tutti i flussi decodificati: il disegno della pagina e il riempimento.
        def decoded(total: int) -> bytes:
            filler = zlib.compress(b" " * (total - len(DRAWING)), 9)
            return pdf({**figure(), 5: stream(filler, b"/Filter /FlateDecode ")})

        self.assertIsNone(code(decoded(pdffigure.MAX_STREAM_BYTES)))
        self.assertEqual(code(decoded(pdffigure.MAX_STREAM_BYTES + 1)), "regodoc.limit.pdf")

    def test_depth(self) -> None:
        deep = figure()
        deep[5] = b"[" * (pdffigure.MAX_DEPTH + 1) + b"]" * (pdffigure.MAX_DEPTH + 1)
        self.assertEqual(code(pdf(deep)), "regodoc.limit.pdf")
        fits = figure()
        fits[5] = b"[" * pdffigure.MAX_DEPTH + b"]" * pdffigure.MAX_DEPTH
        self.assertIsNone(code(pdf(fits)))

    def test_the_budget_counts_every_filter(self) -> None:
        # Un flusso ASCIIHex non supera il tetto da solo, ma dopo la bomba sì.
        half = zlib.compress(b"\x00" * (pdffigure.MAX_STREAM_BYTES - 100), 9)
        objects = figure()
        objects[5] = stream(half, b"/Filter /FlateDecode ")
        objects[6] = stream(b"00" * 200 + b">", b"/Filter /ASCIIHexDecode ")
        self.assertEqual(code(pdf(objects)), "regodoc.limit.pdf")

    def test_decompression_bombs(self) -> None:
        bomb = zlib.compress(b"\x00" * (pdffigure.MAX_STREAM_BYTES + 1), 9)
        objects = figure()
        objects[5] = stream(bomb, b"/Filter /FlateDecode ")
        start = time.perf_counter()
        self.assertEqual(code(pdf(objects)), "regodoc.limit.pdf")
        self.assertLess(time.perf_counter() - start, 5)
        # Tanti flussi piccoli che insieme superano il tetto.
        piece = zlib.compress(b"\x00" * (8 * 1024 * 1024), 9)
        objects = figure()
        objects.update({n: stream(piece, b"/Filter /FlateDecode ") for n in range(5, 15)})
        self.assertEqual(code(pdf(objects)), "regodoc.limit.pdf")
        run_length = bytes([129, 0]) * (pdffigure.MAX_STREAM_BYTES // 128 + 10) + b"\x80"
        objects = figure()
        objects[5] = stream(run_length, b"/Filter /RunLengthDecode ")
        self.assertEqual(code(pdf(objects)), "regodoc.limit.pdf")


class HostileTest(unittest.TestCase):
    def test_random_mutations_never_raise_anything_else(self) -> None:
        sources = [pdf(figure()), pdf(EMBEDDED)]
        generator = random.Random(20261127)  # noqa: S311 - prove ripetibili
        alphabet = b"<>[]()/%0123456789 \nRobjstreamendxref#\\"
        for _ in range(3_000):
            data = bytearray(generator.choice(sources))
            for _ in range(generator.randint(1, 8)):
                position = generator.randrange(len(data))
                action = generator.randrange(3)
                if action == 0:
                    data[position] = generator.choice(alphabet)
                elif action == 1:
                    data.insert(position, generator.choice(alphabet))
                else:
                    del data[position]
            code(bytes(data))

    def test_long_runs_are_linear(self) -> None:
        for body in (
            b"[" * 200_000,
            b"(" * 200_000,
            b"<<" * 100_000,
            b"/a" * 200_000,
            b"%" * 200_000,
        ):
            with self.subTest(body[:4]):
                objects = figure()
                objects[5] = body
                start = time.perf_counter()
                code(pdf(objects))
                self.assertLess(time.perf_counter() - start, 3)


if __name__ == "__main__":
    unittest.main()
