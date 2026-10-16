"""Verifica strutturale delle immagini PNG e JPEG (specifica §6.4).

I pixel dei JPEG non si decodificano. Quelli dei PNG si decomprimono, senza conservarli: il
flusso deve essere zlib valido e dare esattamente le righe che l'intestazione dichiara, perché
pdfTeX li decomprime a sua volta e un flusso sbagliato fermerebbe la compilazione.
"""

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
# Canali per tipo di colore.
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# I sette passaggi di Adam7: colonna e riga d'inizio, passo fra colonne e fra righe.
_ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)
_INFLATE_CHUNK = 1 << 20

_SOF_ALLOWED = {0xC0, 0xC1, 0xC2}
_SOF_REJECTED = {0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_STANDALONE = {0x01, *range(0xD0, 0xD8)}  # TEM e RST0-RST7: marcatori senza lunghezza


class _Bad(Exception):
    """Struttura non valida: il messaggio spiega perché."""


class _Limit(Exception):
    """Un limite dei pixel superato: il codice del limite e il messaggio."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def pixel_bytes(width: int, height: int, depth: int, color: int) -> int:
    """Larghezza × altezza × byte per pixel, con i byte arrotondati in su (§7.2)."""
    return width * height * -(-depth * _PNG_CHANNELS[color] // 8)


def check_image(path: str, data: bytes, report: Collector, budget: int | None = None) -> int:
    """Verifica un'immagine del pacchetto e registra errori e avvisi.

    Restituisce i byte dei pixel di un PNG valido, che contano nel totale delle immagini;
    ``budget`` è quanto ne resta. Per un JPEG o un'immagine rifiutata restituisce 0.
    """
    limit = CONTENT_LIMITS["image_bytes"]
    if len(data) > limit:
        report.error(
            "regodoc.limit.image_size",
            f"l'immagine supera {limit // (1024 * 1024)} MiB",
            path,
        )
        return 0
    is_png = data.startswith(PNG_SIGNATURE)
    is_jpeg = data.startswith(b"\xff\xd8\xff")
    expected_png = path.endswith(".png")
    if not (is_png or is_jpeg):
        report.error(
            "regodoc.image.format",
            "il file non è né PNG né JPEG: SVG, PDF e altri formati non sono ammessi",
            path,
        )
        return 0
    if is_png != expected_png:
        report.error(
            "regodoc.image.extension",
            "l'estensione non corrisponde al contenuto del file",
            path,
        )
        return 0
    used = 0
    try:
        if is_png:
            notes, used = _check_png(data, budget)
        else:
            notes = _check_jpeg(data)
    except _Limit as error:
        report.error(error.code, str(error), path)
        return 0
    except _Bad as error:
        report.error("regodoc.image.structure", str(error), path)
        return 0
    except (struct.error, IndexError):
        report.error("regodoc.image.structure", "il file è troncato", path)
        return 0
    for note in notes:
        report.warning("regodoc.image.metadata", note, path)
    return used


def _check_size(width: int, height: int) -> None:
    side = CONTENT_LIMITS["image_side_pixels"]
    if not (1 <= width <= side and 1 <= height <= side):
        raise _Bad(f"dimensioni {width} × {height} pixel: ogni lato va da 1 a {side}")


def _check_png(data: bytes, budget: int | None) -> tuple[list[str], int]:
    offset = len(PNG_SIGNATURE)
    first = True
    ignored: list[str] = []
    seen_idat = False
    seen_palette = False
    idat: list[bytes] = []
    header = (0, 0, 0, 0, 0)
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
            header = (width, height, depth, color, interlace)
            first = False
        elif kind == b"IHDR":
            raise _Bad("IHDR ripetuto")
        elif kind == b"PLTE":
            # Il PNG vieta la tavolozza nelle immagini in grigio, con o senza alfa (§11.2.3).
            if header[3] in (0, 4):
                raise _Bad("blocco PLTE in un'immagine in grigio, che non ammette tavolozza")
            seen_palette = True
        elif kind == b"IDAT":
            if header[3] == 3 and not seen_palette:
                raise _Bad("immagine a tavolozza senza il blocco PLTE prima dei pixel")
            seen_idat = True
            idat.append(body)
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
    used = _check_pixels(header, idat, budget)
    if ignored:
        names = ", ".join(sorted(set(ignored)))
        return [f"blocchi di metadati ignorati, non finiscono nel PDF: {names}"], used
    return [], used


def _check_pixels(
    header: tuple[int, int, int, int, int], idat: list[bytes], budget: int | None
) -> int:
    """Decomprime i pixel senza conservarli e controlla che diano le righe attese."""
    width, height, depth, color, interlace = header
    used = pixel_bytes(width, height, depth, color)
    limit = CONTENT_LIMITS["image_pixel_bytes"]
    if used > limit:
        raise _Limit(
            "regodoc.limit.image_size",
            f"{width} × {height} pixel di {depth * _PNG_CHANNELS[color]} bit danno {used} byte "
            f"di pixel, il massimo è {limit}",
        )
    if budget is not None and used > budget:
        raise _Limit(
            "regodoc.limit.images",
            f"con questa immagine i pixel di tutte le immagini superano "
            f"{CONTENT_LIMITS['images_pixel_bytes']} byte",
        )
    bits = depth * _PNG_CHANNELS[color]
    passes = _ADAM7 if interlace else ((0, 0, 1, 1),)
    expected = 0
    for column, row, column_step, row_step in passes:
        columns = -(-(width - column) // column_step) if width > column else 0
        rows = -(-(height - row) // row_step) if height > row else 0
        if columns and rows:
            expected += rows * (1 + -(-columns * bits // 8))
    inflater = zlib.decompressobj()
    produced = 0
    try:
        for body in idat:
            pending = body
            while pending:
                out = inflater.decompress(pending, _INFLATE_CHUNK)
                produced += len(out)
                pending = inflater.unconsumed_tail
                if produced > expected:
                    raise _Bad("i pixel compressi sono più di quanti l'intestazione ne dichiari")
        produced += len(inflater.flush())
    except zlib.error as error:
        raise _Bad("il flusso compresso dei pixel non è valido") from error
    if not inflater.eof or produced != expected:
        raise _Bad("i pixel compressi non corrispondono alle dimensioni dell'intestazione")
    return used


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
