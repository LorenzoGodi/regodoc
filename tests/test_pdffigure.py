"""Il controllo delle figure in PDF vettoriale (pdffigure.py): che cosa passa e perché il resto
è rifiutato, con PDF sintetici scritti a mano."""

import random
import time
import unittest
import zlib

from regodoc import pdffigure

DRAWING = b"0.2 0.4 0.8 rg 10 10 80 40 re f 1 w 0 0 m 100 60 l S"


def pdf(
    objects: dict[int, bytes],
    *,
    trailer: bytes = b"",
    version: bytes = b"1.4",
    tail: bytes = b"",
    newline: bytes = b"\n",
) -> bytes:
    """Un PDF con questi oggetti e la tabella xref giusta: l'oggetto 1 è il catalogo. Gli a capo
    fuori dagli oggetti sono `newline`; le righe della tabella xref restano di 20 byte."""
    nl = newline
    entry_end = b" \n" if nl == b"\n" else b"\r\n"
    out = bytearray(b"%PDF-" + version + nl + b"%\xe2\xe3\xcf\xd3" + nl)
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj" % number + nl + objects[number] + nl + b"endobj" + nl
    xref = len(out)
    size = max(objects) + 1
    out += b"xref" + nl + b"0 %d" % size + nl + b"0000000000 65535 f" + entry_end
    for number in range(1, size):
        if number in offsets:
            out += b"%010d 00000 n" % offsets[number] + entry_end
        else:
            out += b"0000000000 00000 f" + entry_end
    out += b"trailer" + nl + b"<< /Size %d /Root 1 0 R " % size + trailer + b">>" + nl
    out += b"startxref" + nl + b"%d" % xref + nl + b"%%EOF" + nl + tail
    return bytes(out)


def stream(body: bytes, extra: bytes = b"") -> bytes:
    return b"<< /Length %d " % len(body) + extra + b">>\nstream\n" + body + b"\nendstream"


def figure(
    page_extra: bytes = b"", resources: bytes = b"", content: bytes = DRAWING
) -> dict[int, bytes]:
    return {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 120] /Contents 4 0 R "
        + b"/Resources << "
        + resources
        + b">> "
        + page_extra
        + b">>",
        4: stream(zlib.compress(content), b"/Filter /FlateDecode "),
    }


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
        big = pdf(figure()) + b"%" * pdffigure.MAX_BYTES
        self.assertEqual(code(big), "regodoc.limit.pdf")

    def test_objects(self) -> None:
        many = figure()
        many.update({n: b"0" for n in range(5, pdffigure.MAX_OBJECTS + 10)})
        self.assertEqual(code(pdf(many)), "regodoc.limit.pdf")

    def test_depth(self) -> None:
        deep = figure()
        deep[5] = b"[" * (pdffigure.MAX_DEPTH + 1) + b"]" * (pdffigure.MAX_DEPTH + 1)
        self.assertEqual(code(pdf(deep)), "regodoc.limit.pdf")
        fits = figure()
        fits[5] = b"[" * pdffigure.MAX_DEPTH + b"]" * pdffigure.MAX_DEPTH
        self.assertIsNone(code(pdf(fits)))

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
