"""Verifica strutturale delle immagini PNG e JPEG (specifica §6.4), senza decodificare i pixel."""

import struct
import zlib

from regodoc.declaration import CONTENT_LIMITS
from regodoc.diagnostics import Collector

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_ALLOWED = frozenset(
    {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"pHYs"}
)
# Combinazioni ammesse di tipo di colore e profondità in bit (PNG, §11.2.2).
_PNG_DEPTHS = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}

_SOF_ALLOWED = {0xC0, 0xC1, 0xC2}
_SOF_REJECTED = {0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_STANDALONE = {0x01, *range(0xD0, 0xD8)}  # TEM e RST0-RST7: marcatori senza lunghezza


class _Bad(Exception):
    """Struttura non valida: il messaggio spiega perché."""


def check_image(path: str, data: bytes, report: Collector) -> None:
    """Verifica un'immagine del pacchetto e registra errori e avvisi."""
    limit = CONTENT_LIMITS["image_bytes"]
    if len(data) > limit:
        report.error(
            "regodoc.limit.image_size",
            f"l'immagine supera {limit // (1024 * 1024)} MiB",
            path,
        )
        return
    is_png = data.startswith(PNG_SIGNATURE)
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    expected_png = path.endswith(".png")
    if not (is_png or is_jpeg):
        report.error(
            "regodoc.image.format",
            "il file non è né PNG né JPEG: SVG, PDF e altri formati non sono ammessi",
            path,
        )
        return
    if is_png != expected_png:
        report.error(
            "regodoc.image.extension",
            "l'estensione non corrisponde al contenuto del file",
            path,
        )
        return
    try:
        notes = _check_png(data) if is_png else _check_jpeg(data)
    except _Bad as error:
        report.error("regodoc.image.structure", str(error), path)
        return
    except (struct.error, IndexError):
        report.error("regodoc.image.structure", "il file è troncato", path)
        return
    for note in notes:
        report.warning("regodoc.image.metadata", note, path)


def _check_size(width: int, height: int) -> None:
    side = CONTENT_LIMITS["image_side_pixels"]
    if not (1 <= width <= side and 1 <= height <= side):
        raise _Bad(f"dimensioni {width} × {height} pixel: ogni lato va da 1 a {side}")


def _check_png(data: bytes) -> list[str]:
    offset = len(PNG_SIGNATURE)
    first = True
    ignored: list[str] = []
    seen_idat = False
    while True:
        if offset + 8 > len(data):
            raise _Bad("il file è troncato: manca il blocco IEND")
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 8 + length + 4
        if length > 0x7FFFFFFF or end > len(data):
            raise _Bad("il file è troncato o un blocco dichiara una lunghezza impossibile")
        body = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack_from(">I", data, offset + 8 + length)
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise _Bad(f"CRC errato nel blocco {kind.decode('latin-1')!r}")
        if first:
            if kind != b"IHDR" or length != 13:
                raise _Bad("il primo blocco deve essere IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            _check_size(width, height)
            if depth not in _PNG_DEPTHS.get(color, set()) or compression or filtering:
                raise _Bad("intestazione IHDR non valida")
            if interlace not in (0, 1):
                raise _Bad("intestazione IHDR non valida")
            first = False
        elif kind == b"IHDR":
            raise _Bad("IHDR ripetuto")
        elif kind == b"IDAT":
            seen_idat = True
        elif kind == b"IEND":
            if end != len(data):
                raise _Bad("ci sono dati dopo il blocco IEND")
            if not seen_idat:
                raise _Bad("manca il blocco IDAT con i pixel")
            break
        elif kind not in _PNG_ALLOWED:
            if not kind[:1].islower():
                raise _Bad(f"blocco critico sconosciuto {kind.decode('latin-1')!r}")
            ignored.append(kind.decode("latin-1"))
        offset = end
    if ignored:
        names = ", ".join(sorted(set(ignored)))
        return [f"blocchi di metadati ignorati, non finiscono nel PDF: {names}"]
    return []


def _check_jpeg(data: bytes) -> list[str]:
    offset = 2
    frames = 0
    metadata = False
    while True:
        if offset + 2 > len(data):
            raise _Bad("il file è troncato: manca il marcatore EOI")
        if data[offset] != 0xFF:
            raise _Bad("segmento non valido")
        marker = data[offset + 1]
        if marker == 0xFF:  # riempimento fra segmenti
            offset += 1
            continue
        if marker == 0xD9:  # EOI
            if offset + 2 != len(data):
                raise _Bad("ci sono dati dopo il marcatore EOI")
            break
        if marker in _STANDALONE:
            offset += 2
            continue
        if marker in (0x00, 0xD8):
            raise _Bad("marcatore inatteso")
        (length,) = struct.unpack_from(">H", data, offset + 2)
        if length < 2 or offset + 2 + length > len(data):
            raise _Bad("il file è troncato o un segmento dichiara una lunghezza impossibile")
        segment = data[offset + 4 : offset + 2 + length]
        if marker in _SOF_ALLOWED:
            frames += 1
            precision, height, width, components = struct.unpack_from(">BHHB", segment)
            if precision != 8:
                raise _Bad("sono ammessi solo JPEG a 8 bit")
            if components not in (1, 3, 4):
                raise _Bad("numero di componenti di colore non ammesso")
            _check_size(width, height)
        elif marker in _SOF_REJECTED:
            raise _Bad("codifica JPEG non ammessa: solo baseline, estesa o progressiva")
        elif 0xE1 <= marker <= 0xEF or marker == 0xFE:
            metadata = True
        offset += 2 + length
        if marker == 0xDA:  # SOS: segue il flusso compresso fino al prossimo marcatore
            offset = _skip_scan(data, offset)
    if frames != 1:
        raise _Bad("serve esattamente un frame SOF")
    return ["segmenti di metadati ignorati"] if metadata else []


def _skip_scan(data: bytes, offset: int) -> int:
    """Salta i dati compressi dopo SOS: finiscono al primo 0xFF non seguito da 0x00 o RSTn."""
    while True:
        position = data.find(b"\xff", offset)
        if position < 0 or position + 1 >= len(data):
            raise _Bad("il file è troncato dentro i dati compressi")
        following = data[position + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            offset = position + 2
            continue
        return position
