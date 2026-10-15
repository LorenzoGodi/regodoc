"""Strumenti comuni delle prove: il pacchetto d'esempio, in cartella o in archivio."""

import io
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path

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


def build_zip(files: dict[str, bytes]) -> bytes:
    """Un archivio con ``mimetype`` non compresso e le altre voci compresse."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            method = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
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
