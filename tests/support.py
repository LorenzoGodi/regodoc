"""Strumenti comuni delle prove: il pacchetto d'esempio, in cartella o in archivio."""

import contextlib
import io
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path

from regodoc import cli
from regodoc.validate import Validation, validate_package

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
