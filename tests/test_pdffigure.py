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
            # Ibridi e linearizzati, per nome (rilettura del disegno di L20, punto 1).
            "ibrido con /XRefStm": pdf(figure(), trailer=b"/XRefStm 9 "),
            "linearizzato": pdf(
                {**figure(), 5: b"<< /Linearized 1 /L 100 /H [10 20] /O 3 /E 90 /N 1 /T 80 >>"}
            ),
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

    def test_boxes_and_rotation(self) -> None:
        # Punto 5: pdfTeX include dal /CropBox, ruota e scala; il controllo lo vede.
        same = b"/CropBox [0 0 200 120] "
        self.assertIsNone(code(pdf(figure(page_extra=same))))
        self.assertIsNone(code(pdf(figure(page_extra=b"/Rotate 0 "))))
        for extra in (
            b"/CropBox [10 10 100 100] ",
            b"/CropBox [0 0 200] ",
            b"/Rotate 90 ",
            b"/UserUnit 2 ",
        ):
            with self.subTest(extra):
                self.assertEqual(code(pdf(figure(page_extra=extra))), "regodoc.image.pdf_pages")
        inherited = figure()
        inherited[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 /Rotate 180 >>"
        self.assertEqual(code(pdf(inherited)), "regodoc.image.pdf_pages")

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

    def test_escaped_names_in_values(self) -> None:
        # Punto 6: un nome con #XX conta anche come valore e come nome di una risorsa.
        for extra in (b"/S /Java#53cript ", b"/X << /#4A#53 1 >> ", b"/A [/Launc#68] "):
            with self.subTest(extra):
                self.assertEqual(code(pdf(figure(page_extra=extra))), "regodoc.image.pdf_active")

    def test_hex_strings_count_in_the_budget(self) -> None:
        # Punto 6: le stringhe esadecimali stanno nel tetto dei byte decodificati.
        objects = figure()
        half = pdffigure.MAX_STREAM_BYTES - len(DRAWING) - 10
        objects[5] = stream(zlib.compress(b" " * half, 9), b"/Filter /FlateDecode ")
        objects[6] = b"<" + b"00" * 11 + b">"
        self.assertEqual(code(pdf(objects)), "regodoc.limit.pdf")
        objects[6] = b"<" + b"00" * 10 + b">"
        self.assertIsNone(code(pdf(objects)))

    def test_fonts_reached_from_the_resources(self) -> None:
        # Un font nelle risorse va incorporato anche senza /Type; i Type0 hanno il file nel
        # discendente (punto 4).
        bare = with_font(b"<< /Subtype /TrueType /BaseFont /Arial >>")
        self.assertEqual(code(pdf(bare)), "regodoc.image.pdf_font")
        type0 = with_font(
            b"<< /Type /Font /Subtype /Type0 /BaseFont /S /DescendantFonts [6 0 R] "
            b"/FontDescriptor 7 0 R >>",
            (6, b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /S >>"),
            (7, b"<< /Type /FontDescriptor /FontName /S /FontFile2 8 0 R >>"),
            (8, stream(b"dati del font")),
        )
        self.assertEqual(code(pdf(type0)), "regodoc.image.pdf_font")

    def test_nested_resources(self) -> None:
        # Punto 2 e 4: Form XObject annidate, e un Type3 i cui glifi richiamano una forma.
        def chain(levels: int) -> dict[int, bytes]:
            objects = figure(resources=b"/XObject << /X0 10 0 R >>")
            for n in range(levels):
                inner = b"/XObject << /X%d %d 0 R >>" % (n + 1, n + 11) if n + 1 < levels else b""
                objects[10 + n] = stream(
                    b"0 0 1 1 re f",
                    b"/Type /XObject /Subtype /Form /BBox [0 0 1 1] /Resources << "
                    + inner
                    + b">> ",
                )
            return objects

        self.assertIsNone(code(pdf(chain(pdffigure.MAX_FORM_DEPTH))))
        self.assertEqual(code(pdf(chain(pdffigure.MAX_FORM_DEPTH + 1))), "regodoc.limit.pdf")
        # Un ciclo fra due forme non fa girare il controllo.
        loop = figure(resources=b"/XObject << /A 10 0 R >>")
        loop[10] = stream(b"", b"/Subtype /Form /Resources << /XObject << /B 11 0 R >> >> ")
        loop[11] = stream(b"", b"/Subtype /Form /Resources << /XObject << /A 10 0 R >> >> ")
        self.assertIsNone(code(pdf(loop)))
        # I glifi di un Type3 con un font non incorporato nelle loro risorse.
        type3 = with_font(
            b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1 1] /FontMatrix [1 0 0 1 0 0] "
            b"/CharProcs << /a 6 0 R >> /Resources << /Font << /G 7 0 R >> >> "
            b"/Encoding << /Differences [97 /a] >> /FirstChar 97 /LastChar 97 /Widths [1] >>",
            (6, stream(b"BT /G 1 Tf (a) Tj ET")),
            (7, b"<< /Subtype /Type1 /BaseFont /Helvetica >>"),
        )
        self.assertEqual(code(pdf(type3)), "regodoc.image.pdf_font")

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


class ReviewTest(unittest.TestCase):
    """I casi della rilettura di L20 (27/11): nessuno è un errore interno."""

    def test_huge_numbers(self) -> None:
        long_int = b"1" * 5_000
        cases = {
            "intero in un valore": pdf(figure(page_extra=b"/Spessore " + long_int + b" ")),
            "intero in un array": pdf({**figure(), 5: b"[0 " + long_int + b"]"}),
            "/Length": pdf(
                {**figure(), 5: b"<< /Length " + long_int + b" >>\nstream\nx\nendstream"}
            ),
            "/MediaBox": pdf(
                {
                    **figure(),
                    3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                    + b"9" * 400
                    + b" 100] /Contents 4 0 R >>",
                }
            ),
            "reale": pdf(figure(page_extra=b"/R 1." + b"5" * 40 + b" ")),
            "startxref": pdf(figure()).replace(b"startxref\n", b"startxref\n" + b"0" * 40, 1),
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.assertEqual(code(data), "regodoc.image.pdf_structure")
        # Trentadue caratteri passano.
        self.assertIsNone(code(pdf(figure(page_extra=b"/N " + b"1" * 32 + b" "))))

    def test_every_byte_is_read(self) -> None:
        html = b"<html><script>alert(1)</script></html>\n"
        hidden = b"9 0 obj\n<< /S /JavaScript /JS (app.alert(1)) >>\nendobj\n"
        cases = {
            "HTML dopo un oggetto": pdf(figure(), after={3: html}),
            "oggetto fuori dalla tabella": pdf(figure(), after={4: hidden}),
            "byte prima della tabella": pdf(figure(), after={4: b"PK\x03\x04"}),
            "commento in un oggetto": pdf(figure(page_extra=b"% /JavaScript\n")),
            "commento fra due oggetti": pdf(figure(), after={1: b"% nascosto\n"}),
            "byte fra startxref e %%EOF": pdf(figure()).replace(b"\n%%EOF", b"\nx\n%%EOF"),
            "byte fra trailer e startxref": pdf(figure()).replace(
                b">>\nstartxref", b">> x\nstartxref"
            ),
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.assertEqual(code(data), "regodoc.image.pdf_structure")
        # Solo spazi fra gli oggetti, e la seconda riga d'intestazione, passano.
        self.assertIsNone(code(pdf(figure(), after={2: b"\n \r\n\t"})))

    def test_indirect_length(self) -> None:
        objects = figure()
        objects[5] = b"<< /Length 6 0 R >>\nstream\nabc\nendstream"
        objects[6] = b"3"
        self.assertIsNone(code(pdf(objects)))
        objects[6] = b"(tre)"
        self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_structure")

    def test_flate_must_end_cleanly(self) -> None:
        packed = zlib.compress(DRAWING)
        for label, body in (("troncato", packed[:-4]), ("con una coda", packed + b"coda")):
            with self.subTest(label):
                objects = figure()
                objects[5] = stream(body, b"/Filter /FlateDecode ")
                self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_structure")
        objects = figure()
        objects[5] = stream(packed + b"\r\n", b"/Filter /FlateDecode ")
        self.assertIsNone(code(pdf(objects)))

    def test_font_of_a_graphics_state(self) -> None:
        objects = figure(resources=b"/ExtGState << /GS0 << /Font [5 0 R 12] >> >>")
        objects[5] = b"<< /Subtype /Type1 /BaseFont /Helvetica >>"
        self.assertEqual(code(pdf(objects)), "regodoc.image.pdf_font")


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
        digits = (b"9" * 400, b"1" * 5_000, b"7" * 33)
        for _ in range(3_000):
            data = bytearray(generator.choice(sources))
            for _ in range(generator.randint(1, 8)):
                position = generator.randrange(len(data))
                action = generator.randrange(3)
                if action == 0 and generator.random() < 0.1:
                    data[position:position] = generator.choice(digits)
                elif action == 0:
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
