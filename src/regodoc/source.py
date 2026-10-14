"""Lettura dell'involucro di un pacchetto: archivio ZIP o cartella (specifica §1 e §6.1).

L'archivio è un ingresso non fidato. Il modulo non usa ``zipfile``: legge da sé la directory
centrale e le intestazioni locali, così può verificare ogni campo, e decomprime con ``zlib``
contando i byte consumati e quelli prodotti. Segue i passi numerati del §6.1: i passi da 1 a
4 si fermano al primo errore, il passo 5 raccoglie tutti i problemi delle voci e poi si
ferma, il passo 6 si ferma al primo limite superato. Le dimensioni dichiarate nell'archivio
non decidono mai quanto leggere: il decompressore non produce mai più di un blocco oltre il
tetto dei byte espansi.
"""

import itertools
import os
import re
import stat
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from regodoc.declaration import ENVELOPE_LIMITS, PACKAGE_MIMETYPE
from regodoc.diagnostics import Collector

MIMETYPE = PACKAGE_MIMETYPE.encode("ascii")

_CHUNK = 64 * 1024
_MIB = 1024 * 1024
_EOCD = b"PK\x05\x06"
_EOCD_SIZE = 22
_ZIP64_LOCATOR = b"PK\x06\x07"
_CENTRAL = b"PK\x01\x02"
_CENTRAL_SIZE = 46
_LOCAL = b"PK\x03\x04"
_LOCAL_SIZE = 30
_DESCRIPTOR = b"PK\x07\x08"
_ZIP64_EXTRA_ID = 0x0001
_ZIP64_MARKERS = (0xFFFF, 0xFFFFFFFF)
_STORED = 0
_DEFLATED = 8
# Il flusso «deflate» di zero byte: l'unico contenuto ammesso per una voce di cartella compressa.
_EMPTY_DEFLATE = b"\x03\x00"
_FLAG_ENCRYPTED = 0x0001
_FLAG_DESCRIPTOR = 0x0008
_FLAG_STRONG_ENCRYPTION = 0x0040

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
# File che i sistemi operativi aggiungono da soli (§1.6): ignorati in una cartella, rifiutati
# in un archivio con il consiglio di ricostruirlo.
_SYSTEM_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


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


def is_system_file(path: str) -> bool:
    """Vero per i file che i sistemi operativi aggiungono da soli (§1.6)."""
    parts = path.split("/")
    leaf = parts[-1]
    return parts[0] == "__MACOSX" or leaf in _SYSTEM_NAMES or leaf.startswith("._")


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
    if name != "README.md" and not _PATH_CHARS.fullmatch(name):
        return "caratteri fuori da [a-z0-9._/-]"
    return None


def _layout_message(name: str) -> str:
    if name.startswith("parts/"):
        return f"«{name}» non è un nome di parte valido: serve parts/<id>.xml (§1.5)"
    if name.startswith("images/"):
        return f"«{name}» non è un nome d'immagine valido: serve images/<nome>.png o .jpg (§1.5)"
    return f"la voce «{name}» non è prevista dalla disposizione del pacchetto (§1.1)"


def _system_message(name: str) -> str:
    return (
        f"la voce «{name}» è stata aggiunta dal sistema operativo: ricostruisci "
        "l'archivio con «regodoc canon»"
    )


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


@dataclass(frozen=True)
class _Entry:
    """Una voce della directory centrale, con i campi che servono ai controlli."""

    name: str
    flags: int
    method: int
    crc: int
    compressed: int
    size: int
    extra: bytes
    comment: bytes
    disk: int
    external: int
    offset: int

    @property
    def is_dir(self) -> bool:
        return self.name.endswith("/")


def _read_archive(path: Path, report: Collector) -> PackageFiles:
    where = path.name
    # Passo 1: dimensione del file.
    limit = ENVELOPE_LIMITS["compressed_bytes"]
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        report.error("regodoc.archive.too_large", f"l'archivio supera {limit // _MIB} MiB", where)
        raise _Stop
    # Passo 2: struttura. Passo 3: numero di voci.
    entries = _read_central_directory(data, where, report)
    # Passo 4: prima voce.
    _check_first_entry(data, entries, report)
    # Passo 5: controlli per voce.
    _check_entries(data, entries, report)
    # Passo 6: estrazione contata.
    return _extract(data, entries, report)


def _fail(report: Collector, code: str, message: str, where: str = "") -> None:
    report.error(code, message, where)
    raise _Stop


def _read_central_directory(data: bytes, where: str, report: Collector) -> list[_Entry]:
    """Passi 2 e 3: firma iniziale, fine della directory centrale, ZIP64, dischi, voci."""
    if not data.startswith(_LOCAL):
        _fail(
            report,
            "regodoc.archive.invalid",
            "il file non comincia con una voce ZIP: non è un pacchetto, oppure ha dati in testa",
            where,
        )
    eocd = data.rfind(_EOCD, max(0, len(data) - _EOCD_SIZE - 0xFFFF))
    if eocd < 0 or eocd + _EOCD_SIZE > len(data):
        _fail(report, "regodoc.archive.invalid", "manca la fine della directory centrale", where)
    (_, disk, cd_disk, on_disk, total, cd_size, cd_offset, comment_len) = struct.unpack(
        "<4sHHHHIIH", data[eocd : eocd + _EOCD_SIZE]
    )
    if eocd + _EOCD_SIZE + comment_len != len(data):
        _fail(report, "regodoc.archive.trailing_data", "ci sono dati dopo la fine dell'archivio")
    if comment_len:
        _fail(report, "regodoc.archive.comment", "l'archivio ha un commento: non è ammesso")
    if (
        total in _ZIP64_MARKERS
        or cd_size in _ZIP64_MARKERS
        or cd_offset in _ZIP64_MARKERS
        or data.rfind(_ZIP64_LOCATOR, max(0, eocd - 20), eocd) >= 0
    ):
        _fail(report, "regodoc.archive.zip64", "gli archivi ZIP64 non sono ammessi")
    if disk or cd_disk or on_disk != total:
        _fail(report, "regodoc.archive.multi_disk", "archivio diviso su più dischi")
    if cd_offset + cd_size != eocd:
        _fail(
            report,
            "regodoc.archive.invalid",
            "la directory centrale non è dove l'archivio dichiara",
        )
    # Le voci di cartella non contano nel limite dei file, ma ne sono ammesse al massimo due.
    if total > ENVELOPE_LIMITS["files"] + len(FOLDERS):
        _fail(
            report,
            "regodoc.archive.too_many_files",
            f"l'archivio ha {total} voci, il massimo è {ENVELOPE_LIMITS['files']} file",
        )
    entries: list[_Entry] = []
    position = cd_offset
    for _ in range(total):
        if position + _CENTRAL_SIZE > eocd or data[position : position + 4] != _CENTRAL:
            _fail(report, "regodoc.archive.invalid", "directory centrale danneggiata")
        (
            _,
            _made_by,
            _needed,
            flags,
            method,
            _time,
            _date,
            crc,
            compressed,
            size,
            name_len,
            extra_len,
            entry_comment_len,
            disk_start,
            _internal,
            external,
            offset,
        ) = struct.unpack_from("<4sHHHHHHIIIHHHHHII", data, position)
        start = position + _CENTRAL_SIZE
        end = start + name_len + extra_len + entry_comment_len
        if end > eocd:
            _fail(report, "regodoc.archive.invalid", "directory centrale danneggiata")
        raw_name = data[start : start + name_len]
        entries.append(
            _Entry(
                name=raw_name.decode("latin-1"),
                flags=flags,
                method=method,
                crc=crc,
                compressed=compressed,
                size=size,
                extra=data[start + name_len : start + name_len + extra_len],
                comment=data[start + name_len + extra_len : end],
                disk=disk_start,
                external=external,
                offset=offset,
            )
        )
        position = end
    if position != eocd:
        _fail(report, "regodoc.archive.invalid", "directory centrale danneggiata")
    files = sum(1 for entry in entries if not entry.is_dir)
    if files > ENVELOPE_LIMITS["files"]:
        _fail(
            report,
            "regodoc.archive.too_many_files",
            f"l'archivio ha {files} file, il massimo è {ENVELOPE_LIMITS['files']}",
        )
    return entries


def _local_header(data: bytes, entry: _Entry) -> tuple[int, int, int, int, int, int, int, bytes]:
    """Campi dell'intestazione locale: flags, metodo, crc, compresso, espanso, nome, extra."""
    start = entry.offset
    if start + _LOCAL_SIZE > len(data) or data[start : start + 4] != _LOCAL:
        raise ValueError
    (_, _needed, flags, method, _time, _date, crc, compressed, size, name_len, extra_len) = (
        struct.unpack_from("<4sHHHHHIIIHH", data, start)
    )
    name = data[start + _LOCAL_SIZE : start + _LOCAL_SIZE + name_len]
    extra = data[start + _LOCAL_SIZE + name_len : start + _LOCAL_SIZE + name_len + extra_len]
    return flags, method, crc, compressed, size, name_len, extra_len, name + b"\0" + extra


def _check_first_entry(data: bytes, entries: list[_Entry], report: Collector) -> None:
    """Passo 4: la prima voce è mimetype, stored, all'offset 0, senza extra né descrittore,
    con il contenuto atteso, letto subito (§1.2)."""
    message = (
        "la prima voce dell'archivio deve essere «mimetype», non compressa, senza campo extra "
        "né descrittore di dati, con il contenuto «application/vnd.regodoc.document» (§1.2)"
    )
    first = entries[0] if entries else None
    if (
        first is None
        or first.name != "mimetype"
        or first.offset != 0
        or first.method != _STORED
        or first.flags & (_FLAG_DESCRIPTOR | _FLAG_ENCRYPTED)
        or first.extra
        or first.compressed != len(MIMETYPE)
        or first.size != len(MIMETYPE)
    ):
        _fail(report, "regodoc.archive.mimetype", message)
    flags, method, crc, compressed, size, name_len, extra_len, _ = _local_header(data, first)
    content_start = _LOCAL_SIZE + name_len + extra_len
    content = data[content_start : content_start + len(MIMETYPE)]
    if (
        flags & (_FLAG_DESCRIPTOR | _FLAG_ENCRYPTED)
        or method != _STORED
        or extra_len
        or (compressed, size) != (len(MIMETYPE), len(MIMETYPE))
        or content != MIMETYPE
        or zlib.crc32(content) != crc
        or crc != first.crc
    ):
        _fail(report, "regodoc.archive.mimetype", message, "mimetype")


def _has_zip64_extra(extra: bytes) -> bool:
    offset = 0
    while offset + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, offset)
        if header_id == _ZIP64_EXTRA_ID:
            return True
        offset += 4 + size
    return False


def _check_entries(data: bytes, entries: list[_Entry], report: Collector) -> None:
    """Passo 5: controlli su ogni voce; raccoglie tutti i problemi, poi si ferma se ce n'è."""
    before = len(report.errors)
    seen: set[str] = set()
    ends: list[tuple[int, int, str]] = []
    for entry in entries:
        name = entry.name
        # Una sola barra finale distingue una cartella: «parts//» resta un nome con un
        # componente vuoto, e il controllo del percorso lo rifiuta.
        key = name[:-1] if name.endswith("/") else name
        if key in seen:
            report.error("regodoc.archive.duplicate", f"la voce «{key}» compare più di una volta")
            continue
        seen.add(key)
        if is_system_file(key):
            report.error("regodoc.archive.system_file", _system_message(name))
            continue
        problem = _path_problem(key)
        if problem:
            report.error("regodoc.archive.path", f"nome di voce non ammesso «{name}»: {problem}")
            continue
        if entry.comment:
            report.error("regodoc.archive.comment", f"la voce «{name}» ha un commento")
            continue
        if entry.flags & (_FLAG_ENCRYPTED | _FLAG_STRONG_ENCRYPTION):
            report.error("regodoc.archive.encrypted", f"la voce «{name}» è cifrata")
            continue
        if entry.method not in (_STORED, _DEFLATED):
            report.error(
                "regodoc.archive.method",
                f"la voce «{name}» usa il metodo di compressione {entry.method}: "
                "sono ammessi solo «stored» e «deflate»",
            )
            continue
        if entry.disk:
            report.error("regodoc.archive.multi_disk", f"la voce «{name}» sta su un altro disco")
            continue
        if _has_zip64_extra(entry.extra):
            report.error("regodoc.archive.zip64", f"la voce «{name}» usa estensioni ZIP64")
            continue
        mode = entry.external >> 16
        if (
            mode
            and stat.S_IFMT(mode)
            and not (stat.S_ISREG(mode) or (entry.is_dir and stat.S_ISDIR(mode)))
        ):
            kind = "un collegamento simbolico" if stat.S_ISLNK(mode) else "un file speciale"
            report.error("regodoc.archive.special_file", f"la voce «{name}» è {kind}")
            continue
        if entry.is_dir:
            empty = (entry.method == _STORED and entry.compressed == 0) or (
                entry.method == _DEFLATED and entry.compressed == len(_EMPTY_DEFLATE)
            )
            if key not in FOLDERS or entry.size or entry.crc or not empty:
                report.error(
                    "regodoc.archive.layout",
                    f"la voce di cartella «{name}» deve essere «parts/» o «images/», vuota: "
                    "«stored» senza dati, oppure «deflate» con il solo flusso vuoto, e CRC 0",
                )
                continue
        elif not is_allowed_path(name):
            report.error("regodoc.archive.layout", _layout_message(name))
            continue
        end = _local_end(data, entry, report)
        if end is None:
            continue
        if entry.is_dir and entry.method == _DEFLATED:
            name_len, extra_len = struct.unpack_from("<HH", data, entry.offset + 26)
            start = entry.offset + _LOCAL_SIZE + name_len + extra_len
            if data[start : start + entry.compressed] != _EMPTY_DEFLATE:
                report.error(
                    "regodoc.archive.layout",
                    f"la voce di cartella «{name}» contiene dati: deve essere vuota",
                )
                continue
        ends.append((entry.offset, end, name))
    if len(report.errors) == before:
        _check_contiguity(data, entries, ends, report)
    if len(report.errors) > before:
        raise _Stop


def _local_end(data: bytes, entry: _Entry, report: Collector) -> int | None:
    """Verifica l'intestazione locale contro la directory centrale e restituisce l'offset
    subito dopo i dati della voce, descrittore compreso; None se non coincide."""
    name = entry.name
    mismatch = (
        "regodoc.archive.header_mismatch",
        f"l'intestazione locale della voce «{name}» non coincide con la directory centrale: "
        "nome, metodo, flag, CRC e dimensioni devono essere uguali",
    )
    try:
        flags, method, crc, compressed, size, name_len, extra_len, name_extra = _local_header(
            data, entry
        )
    except (ValueError, struct.error):
        report.error(*mismatch)
        return None
    local_name, _, local_extra = name_extra.partition(b"\0")
    if _has_zip64_extra(local_extra):
        report.error("regodoc.archive.zip64", f"la voce «{name}» usa estensioni ZIP64")
        return None
    same = local_name == name.encode("latin-1") and method == entry.method and flags == entry.flags
    descriptor = bool(entry.flags & _FLAG_DESCRIPTOR)
    if not descriptor:
        same = same and (crc, compressed, size) == (entry.crc, entry.compressed, entry.size)
    if not same:
        report.error(*mismatch)
        return None
    end = entry.offset + _LOCAL_SIZE + name_len + extra_len + entry.compressed
    if end > len(data):
        report.error("regodoc.archive.corrupt", f"la voce «{name}» è troncata")
        return None
    if descriptor:
        expected = struct.pack("<III", entry.crc, entry.compressed, entry.size)
        if data[end : end + 4] == _DESCRIPTOR and data[end + 4 : end + 16] == expected:
            end += 16
        elif data[end : end + 12] == expected:
            end += 12
        else:
            report.error(*mismatch)
            return None
    return end


def _check_contiguity(
    data: bytes, entries: list[_Entry], ends: list[tuple[int, int, str]], report: Collector
) -> None:
    """Nessun byte fra la fine di una voce e l'intestazione locale della successiva, né fra
    l'ultima voce e la directory centrale (§6.1, passo 5)."""
    spans = sorted(ends)
    cd_offset = (
        len(data)
        - _EOCD_SIZE
        - sum(
            _CENTRAL_SIZE + len(e.name.encode("latin-1")) + len(e.extra) + len(e.comment)
            for e in entries
        )
    )
    if not spans or spans[0][0] != 0:
        report.error("regodoc.archive.gap", "l'archivio non comincia con la prima voce")
        return
    for (_, end, name), (next_start, _, _) in itertools.pairwise(spans):
        if next_start != end:
            report.error(
                "regodoc.archive.gap",
                f"ci sono byte fuori posto dopo la voce «{name}»: le voci devono essere contigue",
            )
            return
    if spans and spans[-1][1] != cd_offset:
        report.error(
            "regodoc.archive.gap",
            "ci sono byte fuori posto fra l'ultima voce e la directory centrale",
        )


def _extract(data: bytes, entries: list[_Entry], report: Collector) -> PackageFiles:
    """Passo 6: estrae le voci contando i byte consumati e quelli prodotti."""
    expanded_limit = ENVELOPE_LIMITS["expanded_bytes"]
    result = PackageFiles("archive")
    total_out = 0
    total_in = 0
    for entry in entries:
        if entry.is_dir:
            continue
        start = entry.offset + _LOCAL_SIZE
        name_len, extra_len = struct.unpack_from("<HH", data, entry.offset + 26)
        start += name_len + extra_len
        raw = data[start : start + entry.compressed]
        content, consumed = _decompress(entry, raw, expanded_limit - total_out, report)
        total_out += len(content)
        total_in += consumed
        if consumed != entry.compressed:
            _fail(
                report,
                "regodoc.archive.size_mismatch",
                f"la voce «{entry.name}» dichiara {entry.compressed} byte compressi, il "
                f"decompressore ne consuma {consumed}",
            )
        if len(content) != entry.size or zlib.crc32(content) != entry.crc:
            _fail(
                report,
                "regodoc.archive.corrupt",
                f"la voce «{entry.name}» è danneggiata: CRC o dimensione non coincidono",
            )
        image_ratio = ENVELOPE_LIMITS["image_compression_ratio"]
        if entry.name.startswith("images/") and len(content) > image_ratio * max(consumed, 1):
            _fail(
                report,
                "regodoc.archive.ratio",
                f"l'immagine «{entry.name}» si espande più di {image_ratio} volte",
            )
        result.files[entry.name] = content
    ratio = ENVELOPE_LIMITS["compression_ratio"]
    if total_out > ratio * max(total_in, 1):
        _fail(
            report,
            "regodoc.archive.ratio",
            f"l'archivio si espande più di {ratio} volte: {total_out} byte da {total_in}",
        )
    return result


def _decompress(entry: _Entry, raw: bytes, budget: int, report: Collector) -> tuple[bytes, int]:
    """Decomprime una voce senza mai produrre più di un blocco oltre ``budget``.

    Restituisce il contenuto e i byte compressi effettivamente consumati.
    """
    too_large = (
        "regodoc.archive.expanded_too_large",
        f"il contenuto espanso supera {ENVELOPE_LIMITS['expanded_bytes'] // _MIB} MiB "
        f"(misurato durante l'estrazione di «{entry.name}»)",
    )
    if entry.method == _STORED:
        if len(raw) > budget:
            _fail(report, *too_large)
        return raw, len(raw)
    decompressor = zlib.decompressobj(-15)
    chunks: list[bytes] = []
    produced = 0
    position = 0
    try:
        while not decompressor.eof:
            pending = decompressor.unconsumed_tail
            drained = False
            if not pending and position < len(raw):
                pending = raw[position : position + _CHUNK]
                position += len(pending)
            elif not pending:
                # Ingresso finito, ma zlib può avere ancora uscita in sospeso, trattenuta dal
                # tetto di _CHUNK byte: si chiede finché ne arriva.
                drained = True
            chunk = decompressor.decompress(pending, _CHUNK)
            if drained and not chunk:
                break
            produced += len(chunk)
            if produced > budget:
                _fail(report, *too_large)
            chunks.append(chunk)
    except zlib.error:
        _fail(report, "regodoc.archive.corrupt", f"la voce «{entry.name}» è danneggiata")
    if not decompressor.eof:
        _fail(report, "regodoc.archive.corrupt", f"la voce «{entry.name}» è troncata")
    consumed = position - len(decompressor.unused_data) - len(decompressor.unconsumed_tail)
    return b"".join(chunks), consumed


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
            elif is_system_file(relative):
                report.warning(
                    "regodoc.package.system_file",
                    f"«{relative}/» è stata aggiunta dal sistema operativo: è ignorata",
                )
                dirs.remove(name)
            elif relative not in FOLDERS:
                report.error("regodoc.archive.layout", _layout_message(relative + "/"))
                fatal = True
                dirs.remove(name)
        for name in sorted(files):
            relative = f"{relative_dir}/{name}" if relative_dir != "." else name
            entry = here / name
            if is_system_file(relative) and not entry.is_symlink():
                report.warning(
                    "regodoc.package.system_file",
                    f"«{relative}» è stato aggiunto dal sistema operativo: è ignorato",
                )
                continue
            count += 1
            if count > ENVELOPE_LIMITS["files"]:
                _fail(
                    report,
                    "regodoc.archive.too_many_files",
                    f"la cartella ha più di {ENVELOPE_LIMITS['files']} file",
                )
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
                _fail(
                    report,
                    "regodoc.archive.expanded_too_large",
                    f"il contenuto supera {expanded_limit // _MIB} MiB",
                )
            result.files[relative] = data
    if fatal:
        raise _Stop
    if result.files.get("mimetype") != MIMETYPE:
        _fail(
            report,
            "regodoc.archive.mimetype",
            "manca «mimetype» o il suo contenuto non è «application/vnd.regodoc.document»",
            "mimetype",
        )
    return result
