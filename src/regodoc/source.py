"""Lettura dell'involucro di un pacchetto: archivio ZIP o cartella (specifica §1 e §6.1).

L'archivio è un ingresso non fidato. Prima di estrarre qualunque cosa il modulo verifica la
struttura dell'archivio sui byte grezzi; poi estrae ogni voce a blocchi, contando i byte
effettivamente letti, e si ferma al primo limite superato. Le dimensioni dichiarate
nell'archivio non sono mai usate per decidere quanto leggere.
"""

import io
import os
import re
import stat
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from regodoc.declaration import ENVELOPE_LIMITS
from regodoc.diagnostics import Collector

MIMETYPE = b"application/vnd.regodoc.document"

_CHUNK = 64 * 1024
_RATIO_GRACE = 64 * 1024
_EOCD = b"PK\x05\x06"
_EOCD_SIZE = 22
_ZIP64_LOCATOR = b"PK\x06\x07"
_LOCAL = b"PK\x03\x04"
_LOCAL_SIZE = 30
_ZIP64_EXTRA_ID = 0x0001
_ZIP64_MARKERS = (0xFFFF, 0xFFFFFFFF)

FIXED_FILES = frozenset(
    {"mimetype", "manifest.json", "README.md", "structure.toml", "variables.toml"}
)
FOLDERS = frozenset({"parts", "images"})
_ID = r"(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:[.]|$))[a-z](?:[a-z0-9]|-(?!-)){0,47}(?<!-)"
_IMAGE = r"(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])[.])[a-z0-9](?:[a-z0-9]|-(?!-)){0,63}(?<!-)"
PART_PATH = re.compile(rf"parts/(?P<id>{_ID})\.xml")
IMAGE_PATH = re.compile(rf"images/(?P<name>{_IMAGE})\.(?:png|jpg|jpeg)")
ID = re.compile(_ID)
_PATH_CHARS = re.compile(r"[a-z0-9._/-]+")


@dataclass
class PackageFiles:
    """I file letti dal pacchetto, nell'ordine in cui compaiono, con i byte già verificati."""

    kind: str  # "archive" oppure "directory"
    files: dict[str, bytes] = field(default_factory=dict)

    def get(self, path: str) -> bytes | None:
        """I byte di un file, o None se il pacchetto non lo contiene."""
        return self.files.get(path)


def is_allowed_path(path: str) -> bool:
    """Dice se un percorso è previsto dalla disposizione fissa del §1.1."""
    return path in FIXED_FILES or bool(PART_PATH.fullmatch(path) or IMAGE_PATH.fullmatch(path))


def _path_problem(name: str) -> str | None:
    """Spiega perché il nome di una voce non è ammesso, o None se lo è."""
    if name.startswith("/") or re.match(r"[A-Za-z]:", name):
        return "percorso assoluto"
    if "\\" in name:
        return "separatore «\\»"
    parts = name.split("/")
    if ".." in parts or "." in parts:
        return "componente «..» o «.»"
    if "" in parts:
        return "separatori doppi o componente vuoto"
    if not _PATH_CHARS.fullmatch(name):
        return "caratteri fuori da [a-z0-9._/-]"
    return None


def _layout_message(name: str) -> str:
    leaf = name.rsplit("/", 1)[-1]
    if name.startswith("__MACOSX/") or leaf == ".DS_Store" or name.startswith("._"):
        return (
            f"la voce «{name}» è stata aggiunta dal sistema operativo: ricostruisci "
            "l'archivio con «regodoc canon»"
        )
    if name.startswith("parts/"):
        return f"«{name}» non è un nome di parte valido: serve parts/<id>.xml (§1.5)"
    if name.startswith("images/"):
        return f"«{name}» non è un nome d'immagine valido: serve images/<nome>.png o .jpg (§1.5)"
    return f"la voce «{name}» non è prevista dalla disposizione del pacchetto (§1.1)"


class _Stop(Exception):
    """Interrompe la lettura dell'involucro dopo un errore che rende inutile proseguire."""


def read_package(path: Path, report: Collector) -> PackageFiles | None:
    """Legge un pacchetto da archivio o da cartella; None se l'involucro è da rifiutare."""
    try:
        if path.is_dir():
            return _read_directory(path, report)
        return _read_archive(path, report)
    except _Stop:
        return None


# --- Archivio --------------------------------------------------------------------------------


def _read_archive(path: Path, report: Collector) -> PackageFiles:
    limit = ENVELOPE_LIMITS["compressed_bytes"]
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        report.error(
            "regodoc.archive.too_large",
            f"l'archivio supera {limit // (1024 * 1024)} MiB",
            path.name,
        )
        raise _Stop
    _check_structure(data, path.name, report)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        NotImplementedError,
        RuntimeError,
        ValueError,
        IndexError,
        KeyError,
        OverflowError,
        struct.error,
        OSError,
    ):
        # zipfile solleva eccezioni diverse secondo il punto in cui l'archivio è rovinato.
        report.error("regodoc.archive.invalid", "il file non è un archivio ZIP valido", path.name)
        raise _Stop from None
    with archive:
        entries = archive.infolist()
        _check_entries(data, entries, report)
        return _extract(archive, entries, report)


def _check_structure(data: bytes, where: str, report: Collector) -> None:
    """Controlli sui byte grezzi: firma iniziale, fine della directory centrale, ZIP64."""
    if not data.startswith(_LOCAL):
        report.error(
            "regodoc.archive.invalid",
            "il file non comincia con una voce ZIP: non è un pacchetto, oppure ha dati in testa",
            where,
        )
        raise _Stop
    eocd = data.rfind(_EOCD, max(0, len(data) - _EOCD_SIZE - 0xFFFF))
    if eocd < 0 or eocd + _EOCD_SIZE > len(data):
        report.error("regodoc.archive.invalid", "manca la fine della directory centrale", where)
        raise _Stop
    (_, disk, cd_disk, on_disk, total, cd_size, cd_offset, comment_len) = struct.unpack(
        "<4sHHHHIIH", data[eocd : eocd + _EOCD_SIZE]
    )
    if eocd + _EOCD_SIZE + comment_len != len(data):
        report.error(
            "regodoc.archive.trailing_data",
            "ci sono dati dopo la fine dell'archivio",
            where,
        )
        raise _Stop
    if disk or cd_disk or on_disk != total:
        report.error("regodoc.archive.multi_disk", "archivio diviso su più dischi", where)
        raise _Stop
    if (
        total in _ZIP64_MARKERS
        or cd_size in _ZIP64_MARKERS
        or cd_offset in _ZIP64_MARKERS
        or data.rfind(_ZIP64_LOCATOR, max(0, eocd - 20), eocd) >= 0
    ):
        report.error("regodoc.archive.zip64", "gli archivi ZIP64 non sono ammessi", where)
        raise _Stop
    if cd_offset + cd_size != eocd:
        report.error(
            "regodoc.archive.invalid",
            "la directory centrale non è dove l'archivio dichiara",
            where,
        )
        raise _Stop
    if total > ENVELOPE_LIMITS["files"]:
        report.error(
            "regodoc.archive.too_many_files",
            f"l'archivio ha {total} voci, il massimo è {ENVELOPE_LIMITS['files']}",
            where,
        )
        raise _Stop


def _check_entries(data: bytes, entries: list[zipfile.ZipInfo], report: Collector) -> None:
    """Controlli sulle voci: prima voce, nomi, doppioni, metodi, cifratura, tipi di file."""
    if len(entries) > ENVELOPE_LIMITS["files"]:
        report.error(
            "regodoc.archive.too_many_files",
            f"l'archivio ha {len(entries)} voci, il massimo è {ENVELOPE_LIMITS['files']}",
        )
        raise _Stop
    first = entries[0] if entries else None
    if (
        first is None
        or first.filename != "mimetype"
        or first.header_offset != 0
        or first.compress_type != zipfile.ZIP_STORED
    ):
        report.error(
            "regodoc.archive.mimetype",
            "la prima voce dell'archivio deve essere «mimetype», non compressa (§1.2)",
        )
        raise _Stop
    seen: set[str] = set()
    fatal = False
    for entry in entries:
        name = entry.filename
        key = name.rstrip("/")
        if key in seen:
            report.error("regodoc.archive.duplicate", f"la voce «{key}» compare più di una volta")
            fatal = True
            continue
        seen.add(key)
        problem = _path_problem(name[:-1] if name.endswith("/") else name)
        if problem:
            report.error("regodoc.archive.path", f"nome di voce non ammesso «{name}»: {problem}")
            fatal = True
            continue
        if entry.flag_bits & 0x1:
            report.error("regodoc.archive.encrypted", f"la voce «{name}» è cifrata")
            fatal = True
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            report.error(
                "regodoc.archive.method",
                f"la voce «{name}» usa il metodo di compressione {entry.compress_type}: "
                "sono ammessi solo «stored» e «deflate»",
            )
            fatal = True
        if _has_zip64_extra(entry.extra):
            report.error("regodoc.archive.zip64", f"la voce «{name}» usa estensioni ZIP64")
            fatal = True
        mode = entry.external_attr >> 16
        is_dir = name.endswith("/")
        if (
            mode
            and stat.S_IFMT(mode)
            and not (stat.S_ISREG(mode) or (is_dir and stat.S_ISDIR(mode)))
        ):
            kind = "un collegamento simbolico" if stat.S_ISLNK(mode) else "un file speciale"
            report.error("regodoc.archive.special_file", f"la voce «{name}» è {kind}")
            fatal = True
            continue
        if is_dir:
            if key not in FOLDERS or entry.file_size or entry.compress_size > 2:
                report.error("regodoc.archive.layout", _layout_message(name))
                fatal = True
            continue
        if not is_allowed_path(name):
            report.error("regodoc.archive.layout", _layout_message(name))
            fatal = True
            continue
        if _local_has_zip64(data, entry):
            report.error("regodoc.archive.zip64", f"la voce «{name}» usa estensioni ZIP64")
            fatal = True
            continue
        if not _local_header_matches(data, entry):
            report.error(
                "regodoc.archive.header_mismatch",
                f"l'intestazione locale della voce «{name}» non coincide con la directory centrale",
            )
            fatal = True
    if fatal:
        raise _Stop


def _has_zip64_extra(extra: bytes) -> bool:
    offset = 0
    while offset + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, offset)
        if header_id == _ZIP64_EXTRA_ID:
            return True
        offset += 4 + size
    return False


def _local_has_zip64(data: bytes, entry: zipfile.ZipInfo) -> bool:
    """Vero se l'intestazione locale della voce porta un campo extra ZIP64."""
    start = entry.header_offset
    if start + _LOCAL_SIZE > len(data) or data[start : start + 4] != _LOCAL:
        return False
    name_len, extra_len = struct.unpack_from("<HH", data, start + 26)
    extra_start = start + _LOCAL_SIZE + name_len
    return _has_zip64_extra(data[extra_start : extra_start + extra_len])


def _local_header_matches(data: bytes, entry: zipfile.ZipInfo) -> bool:
    """Confronta nome, metodo e cifratura dell'intestazione locale con la directory centrale."""
    start = entry.header_offset
    if start + _LOCAL_SIZE > len(data) or data[start : start + 4] != _LOCAL:
        return False
    flags, method = struct.unpack_from("<HH", data, start + 6)
    name_len, extra_len = struct.unpack_from("<HH", data, start + 26)
    name = data[start + _LOCAL_SIZE : start + _LOCAL_SIZE + name_len]
    extra = data[start + _LOCAL_SIZE + name_len : start + _LOCAL_SIZE + name_len + extra_len]
    return (
        name == entry.filename.encode("ascii", "replace")
        and method == entry.compress_type
        and (flags & 0x1) == (entry.flag_bits & 0x1)
        and not _has_zip64_extra(extra)
    )


def _extract(
    archive: zipfile.ZipFile, entries: list[zipfile.ZipInfo], report: Collector
) -> PackageFiles:
    """Estrae le voci a blocchi, contando i byte letti e il rapporto di compressione."""
    expanded_limit = ENVELOPE_LIMITS["expanded_bytes"]
    ratio = ENVELOPE_LIMITS["compression_ratio"]
    result = PackageFiles("archive")
    total_read = 0
    total_compressed = 0
    for entry in entries:
        if entry.filename.endswith("/"):
            continue
        total_compressed += entry.compress_size
        chunks: list[bytes] = []
        entry_read = 0
        try:
            with archive.open(entry) as stream:
                while chunk := stream.read(_CHUNK):
                    entry_read += len(chunk)
                    total_read += len(chunk)
                    if total_read > expanded_limit:
                        report.error(
                            "regodoc.archive.expanded_too_large",
                            f"il contenuto espanso supera {expanded_limit // (1024 * 1024)} MiB "
                            f"(misurato durante l'estrazione di «{entry.filename}»)",
                        )
                        raise _Stop
                    if entry_read > _RATIO_GRACE and entry_read > ratio * max(
                        entry.compress_size, 1
                    ):
                        report.error(
                            "regodoc.archive.ratio",
                            f"la voce «{entry.filename}» si espande più di {ratio} volte",
                        )
                        raise _Stop
                    if total_read > _RATIO_GRACE and total_read > ratio * max(total_compressed, 1):
                        report.error(
                            "regodoc.archive.ratio",
                            f"l'archivio si espande più di {ratio} volte",
                        )
                        raise _Stop
                    chunks.append(chunk)
        except _Stop:
            raise
        except NotImplementedError:
            report.error(
                "regodoc.archive.method",
                f"la voce «{entry.filename}» richiede una funzione ZIP non ammessa",
            )
            raise _Stop from None
        except (
            zipfile.BadZipFile,
            zlib.error,
            EOFError,
            OSError,
            ValueError,
            RuntimeError,
            struct.error,
        ):
            report.error(
                "regodoc.archive.corrupt",
                f"la voce «{entry.filename}» è danneggiata: CRC o dimensione non coincidono",
            )
            raise _Stop from None
        if entry_read != entry.file_size:
            report.error(
                "regodoc.archive.corrupt",
                f"la voce «{entry.filename}» non ha la dimensione dichiarata",
            )
            raise _Stop
        result.files[entry.filename] = b"".join(chunks)
    if result.files.get("mimetype") != MIMETYPE:
        report.error(
            "regodoc.archive.mimetype",
            "il contenuto di «mimetype» non è «application/vnd.regodoc.document» (§1.2)",
            "mimetype",
        )
        raise _Stop
    return result


# --- Cartella --------------------------------------------------------------------------------


def _read_directory(root: Path, report: Collector) -> PackageFiles:
    """Legge un pacchetto aperto in una cartella, con le stesse regole di disposizione."""
    result = PackageFiles("directory")
    total = 0
    count = 0
    expanded_limit = ENVELOPE_LIMITS["expanded_bytes"]
    fatal = False
    for current, dirs, files in os.walk(root, followlinks=False):
        here = Path(current)
        relative_dir = here.relative_to(root).as_posix()
        dirs.sort()
        for name in list(dirs):
            relative = f"{relative_dir}/{name}" if relative_dir != "." else name
            entry = here / name
            if entry.is_symlink():
                report.error(
                    "regodoc.archive.special_file", f"«{relative}» è un collegamento simbolico"
                )
                fatal = True
                dirs.remove(name)
            elif relative not in FOLDERS:
                report.error("regodoc.archive.layout", _layout_message(relative + "/"))
                fatal = True
                dirs.remove(name)
        for name in sorted(files):
            relative = f"{relative_dir}/{name}" if relative_dir != "." else name
            entry = here / name
            count += 1
            if count > ENVELOPE_LIMITS["files"]:
                report.error(
                    "regodoc.archive.too_many_files",
                    f"la cartella ha più di {ENVELOPE_LIMITS['files']} file",
                )
                raise _Stop
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode):
                kind = "un collegamento simbolico" if stat.S_ISLNK(info.st_mode) else "speciale"
                report.error("regodoc.archive.special_file", f"«{relative}» è {kind}")
                fatal = True
                continue
            problem = _path_problem(relative)
            if problem:
                report.error("regodoc.archive.path", f"nome non ammesso «{relative}»: {problem}")
                fatal = True
                continue
            if not is_allowed_path(relative):
                report.error("regodoc.archive.layout", _layout_message(relative))
                fatal = True
                continue
            remaining = expanded_limit - total
            with entry.open("rb") as handle:
                data = handle.read(remaining + 1)
            total += len(data)
            if total > expanded_limit:
                report.error(
                    "regodoc.archive.expanded_too_large",
                    f"il contenuto supera {expanded_limit // (1024 * 1024)} MiB",
                )
                raise _Stop
            result.files[relative] = data
    if fatal:
        raise _Stop
    if result.files.get("mimetype") != MIMETYPE:
        report.error(
            "regodoc.archive.mimetype",
            "manca «mimetype» o il suo contenuto non è «application/vnd.regodoc.document»",
            "mimetype",
        )
        raise _Stop
    return result
