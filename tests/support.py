"""Strumenti comuni delle prove: il pacchetto d'esempio, in cartella o in archivio."""

import contextlib
import io
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path

import regodoc
from regodoc import cli
from regodoc.validate import Validation, validate_package

# La cartella da cui le prove importano il motore: src/ con PYTHONPATH=src, oppure quella
# dell'installazione quando le prove girano contro il wheel installato. Le prove che avviano il
# motore in un processo con -I, che esclude PYTHONPATH, la passano esplicitamente.
ENGINE = Path(regodoc.__file__).resolve().parent.parent
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE = EXAMPLES / "colle-rovere"
# Il secondo esempio, lungo e in inglese, usa tutto il vocabolario di rego/1.
LONG_EXAMPLE = EXAMPLES / "lakeside-rowing"


def example_files(root: Path = EXAMPLE) -> dict[str, bytes]:
    """I file di un pacchetto d'esempio, con mimetype per primo."""
    files = {"mimetype": (root / "mimetype").read_bytes()}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative != "mimetype":
            files[relative] = path.read_bytes()
    return files


def build_zip(files: dict[str, bytes], stored: tuple[str, ...] = ()) -> bytes:
    """Un archivio con ``mimetype`` non compresso e le altre voci compresse, salvo quelle di
    ``stored``, memorizzate così come sono."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            plain = name == "mimetype" or name in stored
            method = zipfile.ZIP_STORED if plain else zipfile.ZIP_DEFLATED
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = method
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def validate_bytes(data: bytes, name: str = "p.regodoc") -> Validation:
    """Valida un archivio passato come byte."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / name
        path.write_bytes(data)
        return validate_package(path)


def validate_files(files: dict[str, bytes]) -> Validation:
    """Valida un insieme di file sia come cartella sia come archivio, e controlla che i due
    esiti coincidano; restituisce quello dell'archivio."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "pkg"
        for name, data in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        as_directory = validate_package(root)
    as_archive = validate_bytes(build_zip(files))
    codes_directory = sorted(d.code for d in as_directory.report.items)
    codes_archive = sorted(d.code for d in as_archive.report.items)
    if codes_directory != codes_archive:
        raise AssertionError(f"cartella {codes_directory} e archivio {codes_archive} divergono")
    return as_archive


def codes(validation: Validation) -> list[str]:
    """I codici dei problemi, nell'ordine."""
    return [d.code for d in validation.report.items]


def png(width: int = 4, height: int = 4, extra: list[tuple[bytes, bytes]] | None = None) -> bytes:
    """Un PNG minimo valido, in scala di grigi, con blocchi aggiuntivi facoltativi."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    chunks = [chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))]
    chunks += [chunk(kind, body) for kind, body in extra or []]
    chunks += [chunk(b"IDAT", zlib.compress(raw)), chunk(b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def jpeg(width: int = 4, height: int = 4, sof: int = 0xC0, precision: int = 8) -> bytes:
    """Un JPEG strutturalmente valido: SOI, SOF, SOS con dati finti, EOI."""

    def segment(marker: int, body: bytes) -> bytes:
        return bytes([0xFF, marker]) + struct.pack(">H", len(body) + 2) + body

    sof_body = struct.pack(">BHHB", precision, height, width, 1) + b"\x01\x11\x00"
    sos_body = b"\x01\x01\x00\x00\x3f\x00"
    return (
        b"\xff\xd8"
        + segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
        + segment(sof, sof_body)
        + segment(0xDA, sos_body)
        + b"\x12\x34\xff\x00\x56"
        + b"\xff\xd9"
    )


# Una firma sintetica nei metadati delle immagini: le prove la cercano dove non deve stare.
METADATA_SIGNATURE = b"Firma-sintetica-dei-metadati-4242"


# --- Figure in PDF vettoriale sintetiche (specifica, §13), scritte a mano ------------------

DRAWING = b"0.2 0.4 0.8 rg 10 10 80 40 re f 1 w 0 0 m 100 60 l S"


def pdf(
    objects: dict[int, bytes],
    *,
    trailer: bytes = b"",
    version: bytes = b"1.4",
    tail: bytes = b"",
    newline: bytes = b"\n",
) -> bytes:
    """Un PDF sintetico con questi oggetti e la tabella xref giusta: l'oggetto 1 è il
    catalogo. Gli a capo fuori dagli oggetti sono ``newline``; le righe della tabella xref
    restano di 20 byte."""
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
    """Un flusso del PDF con la sua /Length."""
    return b"<< /Length %d " % len(body) + extra + b">>\nstream\n" + body + b"\nendstream"


def pdf_figure(
    page_extra: bytes = b"", resources: bytes = b"", content: bytes = DRAWING
) -> dict[int, bytes]:
    """Gli oggetti di una figura in PDF di una pagina, con un tracciato."""
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


def vector_files(files: dict[str, bytes], data: bytes | None = None) -> dict[str, bytes]:
    """Il pacchetto con la figura della rete in PDF vettoriale al posto del PNG."""
    out = dict(files)
    del out["images/coverage.png"]
    out["images/coverage.pdf"] = pdf(pdf_figure()) if data is None else data
    part = out["parts/network.xml"]
    assert part.count(b"images/coverage.png") == 1
    out["parts/network.xml"] = part.replace(b"images/coverage.png", b"images/coverage.pdf")
    return out


def with_metadata(files: dict[str, bytes], grammar: str) -> dict[str, bytes]:
    """Il pacchetto con i metadati nelle immagini, nella grammatica ``grammar``: Exif e un
    commento in ogni JPEG, dopo il JFIF; un blocco di testo in ogni PNG, dopo IHDR."""
    out = dict(files)
    out["manifest.json"] = files["manifest.json"].replace(b'"rego/2"', f'"{grammar}"'.encode())
    for path, data in files.items():
        if path.endswith(".jpg"):
            exif = b"\xff\xe1" + struct.pack(">H", len(METADATA_SIGNATURE) + 8)
            exif += b"Exif\x00\x00" + METADATA_SIGNATURE
            comment = b"\xff\xfe" + struct.pack(">H", len(METADATA_SIGNATURE) + 2)
            comment += METADATA_SIGNATURE
            jfif_end = 4 + struct.unpack_from(">H", data, 4)[0]
            out[path] = data[:jfif_end] + exif + comment + data[jfif_end:]
        elif path.endswith(".png"):
            body = b"Comment\x00" + METADATA_SIGNATURE
            crc = zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF
            text = struct.pack(">I", len(body)) + b"tEXt" + body + struct.pack(">I", crc)
            out[path] = data[:33] + text + data[33:]
    return out


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Esegue il comando nel processo e restituisce codice, stdout e stderr."""
    out, err = io.TextIOWrapper(io.BytesIO(), "utf-8"), io.TextIOWrapper(io.BytesIO(), "utf-8")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, _text(out), _text(err)


def _text(stream: io.TextIOWrapper) -> str:
    stream.flush()
    return stream.buffer.getvalue().decode("utf-8")  # type: ignore[attr-defined]


def png_pixels(
    width: int,
    height: int,
    *,
    depth: int = 8,
    color: int = 0,
    interlace: int = 0,
    raw: bytes | None = None,
    stream: bytes | None = None,
    palette: bool = True,
) -> bytes:
    """Un PNG con pixel tutti a zero, compressi davvero: le righe hanno la lunghezza che
    l'intestazione dichiara, salvo ``raw``, i byte da comprimere al loro posto."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    if stream is not None:
        pass
    elif raw is None:
        # Le righe di ogni passaggio di Adam7, o un solo passaggio senza interlacciamento.
        passes = (
            (
                (0, 0, 8, 8),
                (4, 0, 8, 8),
                (0, 4, 4, 8),
                (2, 0, 4, 4),
                (0, 2, 2, 4),
                (1, 0, 2, 2),
                (0, 1, 1, 2),
            )
            if interlace
            else ((0, 0, 1, 1),)
        )
        compressor = zlib.compressobj(9)
        pieces = []
        for column, row_start, column_step, row_step in passes:
            columns = len(range(column, width, column_step))
            rows = len(range(row_start, height, row_step))
            if columns:
                row = bytes(1 + -(-columns * depth * channels // 8))
                pieces += [compressor.compress(row) for _ in range(rows)]
        stream = b"".join(pieces) + compressor.flush()
    else:
        stream = zlib.compress(raw)
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace)
    chunks = [chunk(b"IHDR", header)]
    if color == 3 and palette:
        chunks.append(chunk(b"PLTE", bytes(3)))
    chunks += [chunk(b"IDAT", stream), chunk(b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)
