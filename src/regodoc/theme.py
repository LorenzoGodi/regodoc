"""Il tema: la cartella del contratto del tema (contratto, §3.3 e §6), letta e controllata.

Un tema esterno arriva da chi chiama, non da chi ha scritto il pacchetto, ma il motore lo
tratta comunque come un ingresso non fidato: niente collegamenti né file speciali, solo i
file previsti, limiti di numero e dimensione, ``theme.toml`` controllato chiave per chiave e
un controllo statico di ``theme.sty``. Le barriere vere sono l'ambiente di pdfTeX e il
controllo del file ``.fls`` dopo la compilazione (``compiler``): il controllo statico dà
solo errori chiari, con la posizione, per i casi evidenti.

Ogni problema del tema ferma ``build`` con il codice 2 e un errore ``regodoc.theme.*``.
"""

import hashlib
import os
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from regodoc.declaration import THEME_CONTRACTS, THEME_LIMITS, THEME_ROLES
from regodoc.diagnostics import Collector, clip
from regodoc.text import bad_char_message, find_bad_chars, plain_text_problems, position_in

# Il tema neutro, dentro il pacchetto Python del motore.
TEX_DIR: Final = Path(__file__).resolve().parent / "tex"
NEUTRAL_DIR: Final = TEX_DIR / "neutral"

_NAME = re.compile(r"[a-z][a-z0-9-]{0,47}")
_ASSET = re.compile(r"assets/(?:[a-z0-9][a-z0-9._-]*/)*[a-z0-9][a-z0-9_-]*\.(?:png|jpg|jpeg|pdf)")
_FRAME_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_PACKAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
_COLOR = re.compile(r"[0-9A-Fa-f]{6}")
_TOML_POSITION = re.compile(r"\(at line (\d+), column (\d+)\)")
_KEYS: Final = ("name", "version", "theme_contract", "frame_keys", "tex_packages", "palette")
_SIGNATURES: Final = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".pdf": b"%PDF-",
}

# Comandi che theme.sty non può nominare: eseguono programmi, leggono o scrivono file per
# nome, o aggirano una ridefinizione. Comprende i nomi di expl3 per gli stessi primitivi e le
# funzioni di file e di sistema di expl3.
_FORBIDDEN = re.compile(
    r"\\(?:"
    r"write\s*18|ShellEscape|input|include|InputIfFileExists|openin|openout|pdfobj"
    r"|pdfmapfile|pdfmapline|pdffiledump|pdfmdfivesum|pdffilesize|pdffilemoddate|pdfximage"
    r"|pdfprimitive|primitive|pdfcatalog|pdfpageattr|pdfpagesattr|pdfannot|pdfnames"
    r")(?![A-Za-z@])"
    r"|\\(?:tex|pdftex|etex|sys|file|ior|iow)_[A-Za-z_]*:[A-Za-z]*"
)


@dataclass
class Theme:
    """Un tema letto: i dati di ``theme.toml``, i file e l'impronta dell'albero."""

    folder: Path
    name: str = ""
    version: str = ""
    frame_keys: tuple[str, ...] = ()
    tex_packages: tuple[str, ...] = ()
    palette: dict[str, str] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    external: bool = False

    @property
    def sha256(self) -> str:
        """L'impronta dell'albero del tema (contratto, §4.3), come ``files_sha256``."""
        lines = "".join(
            f"{hashlib.sha256(self.files[path]).hexdigest()} {len(self.files[path])} {path}\n"
            for path in sorted(self.files, key=lambda p: p.encode("utf-8"))
        )
        return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def read_theme(folder: Path | None, report: Collector) -> Theme | None:
    """Legge il tema in ``folder``, o il tema neutro se ``folder`` è None.

    Il tema neutro passa per gli stessi controlli di un tema esterno: un suo problema è un
    difetto del motore, e lo dice una prova.
    """
    theme = Theme(NEUTRAL_DIR if folder is None else folder, external=folder is not None)
    if not _read_files(theme, report):
        return None
    if not _read_toml(theme, report):
        return None
    if not _check_sty(theme, report):
        return None
    neutral = theme.palette if folder is None else _neutral_palette()
    for role in THEME_ROLES:
        if role not in theme.palette:
            theme.palette[role] = neutral[role]
            report.info(
                "regodoc.theme.role_default",
                f"il tema non definisce il ruolo «{role}»: uso il colore del tema neutro",
                "theme.toml",
            )
    return theme


def _neutral_palette() -> dict[str, str]:
    neutral = Collector()
    theme = Theme(NEUTRAL_DIR)
    if not (_read_files(theme, neutral) and _read_toml(theme, neutral)):  # pragma: no cover
        raise RuntimeError("il tema neutro non si legge")
    return theme.palette


def _read_files(theme: Theme, report: Collector) -> bool:
    """Legge i file della cartella senza seguire collegamenti, con i limiti del §3.3."""
    root = theme.folder
    try:
        info = root.lstat()
    except OSError:
        report.error("regodoc.theme.missing", f"la cartella del tema «{clip(str(root))}» non c'è")
        return False
    if not stat.S_ISDIR(info.st_mode):
        report.error("regodoc.theme.missing", f"«{clip(str(root))}» non è una cartella", "")
        return False
    total = 0
    pending = [("", root)]
    while pending:
        prefix, folder = pending.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as error:
            report.error(
                "regodoc.theme.layout",
                f"non posso leggere la cartella del tema: {error.strerror}",
                prefix,
            )
            return False
        for entry in entries:
            path = prefix + entry.name
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                report.error(
                    "regodoc.theme.layout", "collegamento simbolico: il tema non ne ammette", path
                )
                return False
            if stat.S_ISDIR(mode):
                pending.append((path + "/", Path(entry.path)))
                continue
            if not stat.S_ISREG(mode):
                report.error("regodoc.theme.layout", "file speciale: il tema non ne ammette", path)
                return False
            if path not in ("theme.toml", "theme.sty") and not _ASSET.fullmatch(path):
                report.error(
                    "regodoc.theme.layout",
                    "file non previsto: un tema contiene theme.toml, theme.sty e le "
                    "immagini PNG, JPEG o PDF in assets/, con nomi in minuscolo",
                    path,
                )
                return False
            if len(theme.files) >= THEME_LIMITS["files"]:
                report.error(
                    "regodoc.theme.limit",
                    f"il tema ha più di {THEME_LIMITS['files']} file",
                )
                return False
            data = _read_regular(Path(entry.path))
            total += len(data)
            if total > THEME_LIMITS["bytes"]:
                report.error(
                    "regodoc.theme.limit",
                    f"il tema supera {THEME_LIMITS['bytes']} byte in tutto",
                )
                return False
            theme.files[path] = data
    for required in ("theme.toml", "theme.sty"):
        if required not in theme.files:
            report.error("regodoc.theme.layout", f"manca {required}", required)
            return False
    for path, data in theme.files.items():
        signature = _SIGNATURES.get(path[path.rfind(".") :])
        if signature is not None and not data.startswith(signature):
            report.error("regodoc.theme.asset", "il contenuto non corrisponde all'estensione", path)
            return False
    return True


def _read_regular(path: Path) -> bytes:
    """Legge un file regolare senza seguire un collegamento creato nel frattempo."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):  # pragma: no cover - corsa
            raise OSError("il file del tema non è più un file regolare")
        return handle.read(THEME_LIMITS["bytes"] + 1)


def _decode(data: bytes, file: str, report: Collector) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        line, column = position_in(data[: error.start].decode("utf-8"), error.start)
        report.error("regodoc.theme.encoding", "il file non è UTF-8 valido", file, line, column)
        return None
    if text.startswith("\ufeff"):
        report.error("regodoc.theme.encoding", "il file comincia con un BOM", file, 1, 1)
        return None
    text = text.replace("\r\n", "\n")
    for index in find_bad_chars(text, newline=True, tab=True):
        if ord(text[index]) >= 0x80 and text[index].isprintable():
            continue  # nel codice del tema sono ammessi i caratteri stampabili
        line, column = position_in(text, index)
        report.error("regodoc.theme.encoding", bad_char_message(text[index]), file, line, column)
        return None
    return text


def _read_toml(theme: Theme, report: Collector) -> bool:
    file = "theme.toml"
    text = _decode(theme.files[file], file, report)
    if text is None:
        return False
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        match = _TOML_POSITION.search(str(error))
        line, column = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        report.error("regodoc.theme.toml", "TOML non valido", file, line, column)
        return False
    problems: list[str] = []
    for key in data:
        if key not in _KEYS:
            problems.append(f"chiave «{key}» non prevista")
    name = data.get("name")
    if not (isinstance(name, str) and _NAME.fullmatch(name)):
        problems.append("«name» deve rispettare [a-z][a-z0-9-]{0,47}")
    version = data.get("version")
    if not isinstance(version, str) or plain_text_problems(version, max_length=32):
        problems.append("«version» deve essere testo da 1 a 32 caratteri")
    contract = data.get("theme_contract")
    if type(contract) is not int or contract not in THEME_CONTRACTS:
        supported = ", ".join(str(v) for v in THEME_CONTRACTS)
        problems.append(f"«theme_contract» deve essere uno di {supported}")
    frame_keys = _string_list(data, "frame_keys", _FRAME_KEY, 50, problems)
    packages = _string_list(data, "tex_packages", _PACKAGE, 200, problems)
    palette = data.get("palette", {})
    if not isinstance(palette, dict):
        problems.append("«palette» deve essere una tabella")
        palette = {}
    for role, value in palette.items():
        if role not in THEME_ROLES:
            problems.append(f"«palette.{role}»: ruolo sconosciuto")
        elif not (isinstance(value, str) and _COLOR.fullmatch(value)):
            problems.append(f"«palette.{role}» deve essere un colore RRGGBB in esadecimale")
    if problems:
        for problem in problems:
            report.error("regodoc.theme.toml", problem, file)
        return False
    theme.name, theme.version = str(name), str(version)
    theme.frame_keys, theme.tex_packages = frame_keys, packages
    theme.palette = {role: str(value).upper() for role, value in palette.items()}
    return True


def _string_list(
    data: Mapping[str, object], key: str, pattern: re.Pattern[str], limit: int, problems: list[str]
) -> tuple[str, ...]:
    value = data.get(key, [])
    if (
        not isinstance(value, list)
        or len(value) > limit
        or not all(isinstance(item, str) and pattern.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        problems.append(
            f"«{key}» deve essere un elenco di al massimo {limit} nomi validi, senza ripetizioni"
        )
        return ()
    return tuple(value)


def _check_sty(theme: Theme, report: Collector) -> bool:
    """Controllo statico di theme.sty: i comandi vietati, fuori dai commenti."""
    file = "theme.sty"
    text = _decode(theme.files[file], file, report)
    if text is None:
        return False
    found = False
    for number, line in enumerate(text.split("\n"), start=1):
        code = _without_comment(line)
        for match in _FORBIDDEN.finditer(code):
            command = re.sub(r"\s+", "", match.group(0))
            report.error(
                "regodoc.theme.forbidden",
                f"{clip(command)} non è ammesso in un tema: legge o scrive file, esegue "
                "programmi o aggira i controlli del motore",
                file,
                number,
                match.start() + 1,
            )
            found = True
    return not found


def _without_comment(line: str) -> str:
    """La riga senza il commento: dal primo «%» non preceduto da un numero dispari di «\\»."""
    index = 0
    while (index := line.find("%", index)) >= 0:
        slashes = len(line[:index]) - len(line[:index].rstrip("\\"))
        if slashes % 2 == 0:
            return line[:index]
        index += 1
    return line
