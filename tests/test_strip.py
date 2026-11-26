"""Prove della pulizia delle immagini (decisione 15): metadati tolti, pixel invariati."""

import struct
import unittest
import zlib

from regodoc import images
from regodoc.diagnostics import Collector
from tests.support import LONG_EXAMPLE, jpeg, png

SIGNATURE = b"Firma-sintetica-0123456789"


def segment(marker: int, body: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body


def chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def jpeg_parts(data: bytes) -> list[bytes]:
    """I segmenti di un JPEG, ognuno con il suo marcatore; il flusso compresso dopo SOS sta
    con il suo segmento; il riempimento fra i segmenti non conta. Un lettore indipendente da
    quello del motore."""
    parts = [data[:2]]
    offset = 2
    while offset < len(data):
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker == 0xD9 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            parts.append(data[offset : offset + 2])
            offset += 2
            continue
        (length,) = struct.unpack_from(">H", data, offset + 2)
        end = offset + 2 + length
        if marker == 0xDA:
            while True:
                end = data.index(b"\xff", end)
                if data[end + 1] == 0x00 or 0xD0 <= data[end + 1] <= 0xD7:
                    end += 2
                    continue
                break
        parts.append(data[offset:end])
        offset = end
    return parts


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    out = []
    offset = 8
    while offset < len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        out.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
    return out


def pixels(data: bytes) -> bytes:
    """I pixel di un PNG, decompressi."""
    return zlib.decompress(b"".join(body for kind, body in png_chunks(data) if kind == b"IDAT"))


def insert_after_soi(data: bytes, *segments: bytes) -> bytes:
    return data[:2] + b"".join(segments) + data[2:]


def valid(path: str, data: bytes) -> list[str]:
    report = Collector()
    images.check_image(path, data, report)
    return [item.code for item in report.items]


EXIF = segment(0xE1, b"Exif\x00\x00" + SIGNATURE + b"\x00" * 64)
ICC = segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + SIGNATURE)
IPTC = segment(0xED, b"Photoshop 3.0\x00" + SIGNATURE)
COMMENT = segment(0xFE, SIGNATURE)
JFXX = segment(0xE0, b"JFXX\x00\x10" + SIGNATURE)
JFIF_THUMB = segment(0xE0, b"JFIF\x00\x01\x02\x01\x00\x48\x00\x48\x02\x01" + b"\x99" * 6)
ADOBE_LONG = segment(0xEE, b"Adobe\x00\x65\x80\x00\x00\x01\x02" + SIGNATURE)


class JpegTest(unittest.TestCase):
    def test_metadata_segments_go_and_the_rest_stays(self) -> None:
        source = jpeg()
        dirty = insert_after_soi(source, EXIF, ICC, IPTC, COMMENT, JFXX)
        clean, removed = images.strip_image("images/a.jpg", dirty)
        self.assertNotIn(SIGNATURE, clean)
        self.assertEqual(clean, source)
        self.assertEqual(removed, ["APP0", "APP1", "APP13", "APP2", "COM"])
        self.assertEqual(valid("images/a.jpg", clean), [])

    def test_jfif_becomes_the_minimal_one(self) -> None:
        source = jpeg()
        # Il JFIF dell'esempio di prova è già minimo; uno con miniatura e densità si riduce.
        dirty = source[:2] + JFIF_THUMB + source[2 + 18 :]
        clean, removed = images.strip_image("images/a.jpg", dirty)
        self.assertEqual(clean, source)
        self.assertEqual(clean[2:20], images.JFIF_MINIMAL)
        self.assertEqual(removed, ["APP0 JFIF ridotto al minimo"])

    def test_no_jfif_is_added(self) -> None:
        # Un JFIF in un JPEG che non l'aveva cambierebbe la lettura dei colori.
        source = jpeg()
        without = source[:2] + source[2 + 18 :]
        self.assertEqual(images.strip_image("images/a.jpg", without), (without, []))

    def test_adobe_keeps_only_the_transform(self) -> None:
        source = jpeg()
        dirty = insert_after_soi(source, ADOBE_LONG)
        clean, removed = images.strip_image("images/a.jpg", dirty)
        self.assertNotIn(SIGNATURE, clean)
        adobe = clean.index(b"\xff\xee")
        self.assertEqual(
            clean[adobe : adobe + 16], b"\xff\xee\x00\x0eAdobe\x00\x64\x00\x00\x00\x00\x02"
        )
        self.assertEqual(removed, ["APP14 Adobe ridotto ai suoi 12 byte"])
        # Il controllo di rego/1 conta ancora l'APP14 fra i metadati: nessun errore, però.
        self.assertEqual(valid("images/a.jpg", clean), ["regodoc.image.metadata"])

    def test_fill_bytes_go(self) -> None:
        source = jpeg()
        sof = source.index(b"\xff\xc0")
        dirty = source[:sof] + b"\xff\xff\xff" + source[sof:]
        clean, removed = images.strip_image("images/a.jpg", dirty)
        self.assertEqual(clean, source)
        self.assertEqual(removed, ["riempimento fra i segmenti"])

    def test_progressive_scans_and_restart_markers_stay_byte_for_byte(self) -> None:
        source = jpeg(sof=0xC2)
        sos = source.index(b"\xff\xda")
        # Una seconda scansione con un RST nel flusso e un DRI prima, più un COM in mezzo.
        second = segment(0xDA, b"\x01\x01\x00\x01\x05\x00") + b"\x22\xff\xd0\x33\xff\x00"
        dri = segment(0xDD, b"\x00\x04")
        eoi = len(source) - 2
        dirty = source[:sos] + dri + source[sos:eoi] + COMMENT + second + EXIF + source[eoi:]
        clean, removed = images.strip_image("images/a.jpg", dirty)
        expected = source[:sos] + dri + source[sos:eoi] + second + source[eoi:]
        self.assertEqual(clean, expected)
        self.assertEqual(removed, ["APP1", "COM"])
        kept = [part for part in jpeg_parts(dirty) if part[1] not in (0xE1, 0xFE)]
        self.assertEqual(jpeg_parts(clean), kept)

    def test_twice_gives_the_same_bytes(self) -> None:
        dirty = insert_after_soi(jpeg(), EXIF, ADOBE_LONG, COMMENT)
        once, _ = images.strip_image("images/a.jpg", dirty)
        self.assertEqual(images.strip_image("images/a.jpg", once), (once, []))

    def test_hostile_metadata(self) -> None:
        big = segment(0xE1, SIGNATURE + b"\x00" * (0xFFFF - 2 - len(SIGNATURE)))
        many = [segment(0xE0 + index % 16 or 0xE1, SIGNATURE) for index in range(500)]
        for name, extra in (("64 KiB", [big]), ("500 segmenti", many)):
            with self.subTest(name):
                dirty = insert_after_soi(jpeg(), *extra)
                self.assertEqual(valid("images/a.jpg", dirty), ["regodoc.image.metadata"])
                clean, _ = images.strip_image("images/a.jpg", dirty)
                self.assertEqual(clean, jpeg())

    def test_the_example_photo(self) -> None:
        path = LONG_EXAMPLE / "images" / "landing-stage.jpg"
        source = path.read_bytes()
        clean, _ = images.strip_image("images/landing-stage.jpg", source)
        self.assertEqual(valid("images/landing-stage.jpg", clean), [])
        dropped = [
            part for part in jpeg_parts(source) if 0xE1 <= part[1] <= 0xEF or part[1] == 0xFE
        ]
        self.assertFalse(dropped, "l'esempio non ha metadati da togliere")
        kept = [part for part in jpeg_parts(source) if part[1] != 0xE0]
        self.assertEqual([part for part in jpeg_parts(clean) if part[1] != 0xE0], kept)


class PngTest(unittest.TestCase):
    def test_ancillary_chunks_go_and_the_pixels_stay(self) -> None:
        extra = [
            (b"iCCP", b"profilo\x00\x00" + zlib.compress(SIGNATURE)),
            (b"sRGB", b"\x00"),
            (b"gAMA", struct.pack(">I", 45455)),
            (b"cHRM", b"\x00" * 32),
            (b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
            (b"tEXt", b"Comment\x00" + SIGNATURE),
            (b"zTXt", b"Comment\x00\x00" + zlib.compress(SIGNATURE)),
            (b"iTXt", b"Comment\x00\x00\x00\x00\x00" + SIGNATURE),
            (b"eXIf", b"MM\x00\x2a" + SIGNATURE),
            (b"prVt", SIGNATURE),
        ]
        dirty = png(extra=extra)
        clean, removed = images.strip_image("images/a.png", dirty)
        self.assertNotIn(SIGNATURE, clean)
        self.assertEqual(clean, png())
        self.assertEqual(
            removed,
            sorted(
                ["iCCP", "sRGB", "gAMA", "cHRM", "pHYs", "tEXt", "zTXt", "iTXt", "eXIf", "prVt"]
            ),
        )
        self.assertEqual(pixels(clean), pixels(dirty))
        self.assertEqual(valid("images/a.png", clean), [])

    def test_split_idat_becomes_one_without_recompressing(self) -> None:
        source = png(8, 8)
        chunks = png_chunks(source)
        stream = b"".join(body for kind, body in chunks if kind == b"IDAT")
        split = (
            source[:8]
            + chunk(b"IHDR", chunks[0][1])
            + chunk(b"IDAT", stream[:5])
            + chunk(b"IDAT", stream[5:])
            + chunk(b"IEND", b"")
        )
        clean, removed = images.strip_image("images/a.png", split)
        self.assertEqual(clean, source)
        self.assertEqual(removed, [])

    def test_palette_and_transparency_stay(self) -> None:
        header = struct.pack(">IIBBBBB", 2, 1, 8, 3, 0, 0, 0)
        stream = zlib.compress(b"\x00\x00\x01")
        source = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
            + chunk(b"tRNS", b"\x00")
            + chunk(b"IDAT", stream)
            + chunk(b"IEND", b"")
        )
        dirty = source[:33] + chunk(b"tIME", b"\x07\xea\x0b\x1a\x00\x00\x00") + source[33:]
        clean, removed = images.strip_image("images/a.png", dirty)
        self.assertEqual(clean, source)
        self.assertEqual(removed, ["tIME"])
        self.assertEqual(valid("images/a.png", clean), [])

    def test_twice_gives_the_same_bytes(self) -> None:
        dirty = png(extra=[(b"tEXt", b"k\x00" + SIGNATURE), (b"pHYs", b"\x00" * 9)])
        once, _ = images.strip_image("images/a.png", dirty)
        self.assertEqual(images.strip_image("images/a.png", once), (once, []))

    def test_the_example_plan(self) -> None:
        source = (LONG_EXAMPLE / "images" / "shed-plan.png").read_bytes()
        clean, _ = images.strip_image("images/shed-plan.png", source)
        self.assertEqual(pixels(clean), pixels(source))
        self.assertEqual(valid("images/shed-plan.png", clean), [])


class UnreadableTest(unittest.TestCase):
    def test_an_unreadable_image_comes_back_as_it_is(self) -> None:
        for path, data in (("images/a.jpg", b"\xff\xd8\xff\xe1\x00"), ("images/a.png", b"\x89PNG")):
            with self.subTest(path):
                self.assertEqual(images.strip_image(path, data), (data, []))


if __name__ == "__main__":
    unittest.main()
