"""Il controllo delle figure in PDF vettoriale (specifica, §4.5 e §6.4; lotto L20, R6).

Il motore non esegue né ripulisce un PDF: lo legge come dati e lo rifiuta se non ha la forma
che lo strumento di pulizia di chi chiama scrive. Le regole:

- una sola tabella xref classica, una sola revisione, nessun flusso di oggetti né flusso
  xref, nessuna cifratura; ogni oggetto letto all'offset che la tabella dichiara;
- una pagina sola, con una ``/MediaBox`` sensata;
- nessun nome di contenuto attivo o nascosto, anche scritto con ``#XX``;
- ogni font incorporato;
- solo i filtri che i lettori PDF trattano senza storia di difetti; i flussi si decodificano
  contati, senza conservarli, entro un tetto;
- nessun metadato: niente ``/Metadata``, niente ``/PieceInfo``, ``/Info`` assente o vuoto.

Il lettore degli oggetti usa una pila, non la ricorsione, e ogni ciclo avanza nei byte o
finisce: il tempo cresce in modo lineare con il file, salvo la decodifica dei flussi, che ha
il suo tetto.
"""

import base64
import binascii
import re
import zlib
from dataclasses import dataclass

from regodoc.declaration import CONTENT_LIMITS

# I limiti di un PDF (specifica, §7.2).
MAX_BYTES = int(CONTENT_LIMITS["pdf_bytes"])
MAX_OBJECTS = int(CONTENT_LIMITS["pdf_objects"])
MAX_STREAM_BYTES = int(CONTENT_LIMITS["pdf_stream_bytes"])
MAX_DEPTH = 32
MAX_SIDE = 5000  # punti tipografici, poco meno di 1,8 m

VERSIONS = frozenset({"1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "2.0"})
ACTIVE = frozenset(
    {
        "JavaScript",
        "JS",
        "OpenAction",
        "AA",
        "Launch",
        "SubmitForm",
        "ImportData",
        "RichMedia",
        "EmbeddedFile",
        "EmbeddedFiles",
        "XFA",
        "Annots",
        "AcroForm",
        "URI",
        "GoToR",
        "GoToE",
        "FileAttachment",
        "Sound",
        "Movie",
        "Rendition",
        "3D",
        "Names",
        "OCProperties",
    }
)
FILTERS = frozenset(
    {"FlateDecode", "DCTDecode", "ASCIIHexDecode", "ASCII85Decode", "RunLengthDecode"}
)
FONT_FILES = ("FontFile", "FontFile2", "FontFile3")

_WHITESPACE = b"\x00\t\n\x0c\r "
_DELIMITERS = b"()<>[]{}/%"
_NUMBER = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_OBJECT = re.compile(rb"([0-9]{1,10})[ \t\r\n\x0c\x00]+([0-9]{1,5})[ \t\r\n\x0c\x00]+obj\b")
_XREF_ENTRY = re.compile(rb"([0-9]{10}) ([0-9]{5}) ([nf])(?: \r| \n|\r\n)")
_SUBSECTION = re.compile(rb"([0-9]{1,10}) ([0-9]{1,10})[ \t]*(?:\r\n|\r|\n)")


class Problem(Exception):
    """Il PDF è da rifiutare: il codice e il messaggio."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _bad(message: str) -> Problem:
    return Problem("regodoc.image.pdf_structure", message)


@dataclass(frozen=True)
class Name:
    value: str


@dataclass(frozen=True)
class Ref:
    number: int
    generation: int


@dataclass
class Stream:
    dictionary: dict[str, object]
    raw: bytes


_KEYWORDS: dict[bytes, object] = {b"true": True, b"false": False, b"null": None}


class _Lexer:
    """Legge oggetti PDF da ``data`` a partire da una posizione, senza ricorsione."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.names: set[str] = set()

    def skip(self, index: int) -> int:
        data = self.data
        while index < len(data):
            char = data[index]
            if char in _WHITESPACE:
                index += 1
            elif char == 0x25:  # % commento fino a fine riga
                while index < len(data) and data[index] not in b"\r\n":
                    index += 1
            else:
                break
        return index

    def token(self, index: int) -> tuple[object, int]:
        """Un token: un valore semplice, o uno dei segni «<<», «>>», «[», «]»."""
        data = self.data
        index = self.skip(index)
        if index >= len(data):
            raise _bad("il file finisce dentro un oggetto")
        char = data[index]
        if data.startswith(b"<<", index):
            return "<<", index + 2
        if data.startswith(b">>", index):
            return ">>", index + 2
        if char == 0x5B:
            return "[", index + 1
        if char == 0x5D:
            return "]", index + 1
        if char == 0x2F:
            end = index + 1
            while end < len(data) and data[end] not in _WHITESPACE and data[end] not in _DELIMITERS:
                end += 1
            raw = data[index + 1 : end]
            try:
                name = re.sub(
                    rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw
                ).decode("latin-1")
            except ValueError as error:  # pragma: no cover - re.sub su byte non fallisce
                raise _bad("un nome illeggibile") from error
            self.names.add(name)
            return Name(name), end
        if char == 0x28:
            return self.literal(index)
        if char == 0x3C:
            end = data.find(b">", index)
            if end < 0:
                raise _bad("una stringa esadecimale non si chiude")
            digits = bytes(b for b in data[index + 1 : end] if b not in _WHITESPACE)
            if not re.fullmatch(rb"[0-9A-Fa-f]*", digits):
                raise _bad("una stringa esadecimale con caratteri non esadecimali")
            return binascii.unhexlify(digits + b"0" * (len(digits) % 2)), end + 1
        match = _NUMBER.match(data, index)
        if match is not None and (
            match.end() >= len(data)
            or data[match.end()] in _WHITESPACE
            or data[match.end()] in _DELIMITERS
        ):
            text = match.group()
            value: object = float(text) if b"." in text else int(text)
            return value, match.end()
        end = index
        while end < len(data) and data[end] not in _WHITESPACE and data[end] not in _DELIMITERS:
            end += 1
        word = data[index:end]
        if word in _KEYWORDS:
            return _KEYWORDS[word], end
        if word in (b"R", b"obj", b"endobj", b"stream", b"endstream"):
            return word.decode("ascii"), end
        raise _bad(f"un elemento sconosciuto all'offset {index}")

    def literal(self, index: int) -> tuple[bytes, int]:
        data = self.data
        depth = 0
        position = index
        while position < len(data):
            char = data[position]
            if char == 0x5C:
                position += 2
                continue
            if char == 0x28:
                depth += 1
            elif char == 0x29:
                depth -= 1
                if depth == 0:
                    return data[index + 1 : position], position + 1
            position += 1
        raise _bad("una stringa non si chiude")

    def value(self, index: int) -> tuple[object, int]:
        """Un valore completo: dizionari e array con una pila, riferimenti «n g R»."""
        stack: list[list[object] | dict[str, object]] = []
        keys: list[str | None] = []
        while True:
            item, index = self.token(index)
            if item in ("<<", "["):
                if len(stack) >= MAX_DEPTH:
                    raise Problem(
                        "regodoc.limit.pdf", f"dizionari e array annidati oltre {MAX_DEPTH} livelli"
                    )
                stack.append({} if item == "<<" else [])
                keys.append(None)
                continue
            if item in (">>", "]"):
                if not stack or isinstance(stack[-1], dict) != (item == ">>"):
                    raise _bad("una chiusura senza apertura")
                if item == ">>" and keys[-1] is not None:
                    raise _bad("una chiave di dizionario senza valore")
                item = stack.pop()
                keys.pop()
            elif isinstance(item, str):
                raise _bad(f"«{item}» fuori posto")
            elif isinstance(item, int) and item >= 0:
                # Un riferimento «n g R», se seguono un intero e «R».
                after = self.skip(index)
                match = _NUMBER.match(self.data, after)
                if match is not None and b"." not in match.group():
                    following = self.skip(match.end())
                    if self.data.startswith(b"R", following) and (
                        following + 1 >= len(self.data)
                        or self.data[following + 1] in _WHITESPACE
                        or self.data[following + 1] in _DELIMITERS
                    ):
                        item = Ref(item, int(match.group()))
                        index = following + 1
            if not stack:
                return item, index
            container = stack[-1]
            if isinstance(container, list):
                container.append(item)
            elif keys[-1] is None:
                if not isinstance(item, Name):
                    raise _bad("una chiave di dizionario che non è un nome")
                keys[-1] = item.value
            else:
                container[keys[-1]] = item  # type: ignore[index]
                keys[-1] = None


@dataclass
class _Document:
    objects: dict[int, object]
    trailer: dict[str, object]

    def resolve(self, value: object) -> object:
        # Un riferimento a un riferimento si segue una volta sola: oltre è un errore.
        if isinstance(value, Ref):
            value = self.objects.get(value.number)
            if isinstance(value, Ref):
                raise _bad("un riferimento che punta a un altro riferimento")
        return value

    def dictionary(self, value: object) -> dict[str, object]:
        value = self.resolve(value)
        if isinstance(value, Stream):
            return value.dictionary
        return value if isinstance(value, dict) else {}


def check(data: bytes) -> None:
    """Solleva ``Problem`` se il PDF non è una figura ammessa."""
    if len(data) > MAX_BYTES:
        raise Problem("regodoc.limit.pdf", f"il PDF supera {MAX_BYTES // (1024 * 1024)} MiB")
    match = re.match(rb"%PDF-([0-9]\.[0-9])[\r\n]", data)
    if match is None or match.group(1).decode() not in VERSIONS:
        raise _bad("manca l'intestazione %PDF-1.x o %PDF-2.0")
    document, lexer = _read(data)
    found = sorted(lexer.names & ACTIVE)
    if found:
        raise Problem(
            "regodoc.image.pdf_active",
            f"il PDF contiene /{found[0]}: contenuto attivo, interattivo o nascosto",
        )
    for name in ("Metadata", "PieceInfo"):
        if name in lexer.names:
            raise Problem("regodoc.image.pdf_metadata", f"il PDF contiene /{name}: metadati")
    if document.dictionary(document.trailer.get("Info")):
        raise Problem("regodoc.image.pdf_metadata", "il dizionario /Info del PDF non è vuoto")
    _check_pages(document)
    _check_streams(document)
    _check_fonts(document)


def _read(data: bytes) -> tuple[_Document, _Lexer]:
    tail = data.rstrip(_WHITESPACE)
    if not tail.endswith(b"%%EOF"):
        raise _bad("il file non finisce con %%EOF")
    start = tail.rfind(b"startxref")
    if start < 0:
        raise _bad("manca startxref")
    lexer = _Lexer(data)
    offset, _ = lexer.token(start + len(b"startxref"))
    if not isinstance(offset, int) or not 0 < offset < start:
        raise _bad("startxref non indica una tabella xref")
    if not data.startswith(b"xref", offset):
        raise _bad("la tabella xref è compressa o non è dove dice startxref")
    position = lexer.skip(offset + 4)
    entries: dict[int, int] = {}
    while True:
        section = _SUBSECTION.match(data, position)
        if section is None:
            break
        first, count = int(section.group(1)), int(section.group(2))
        position = section.end()
        if len(entries) + count > MAX_OBJECTS + 1:
            raise Problem("regodoc.limit.pdf", f"il PDF ha più di {MAX_OBJECTS} oggetti")
        for number in range(first, first + count):
            entry = _XREF_ENTRY.match(data, position)
            if entry is None:
                raise _bad("una riga della tabella xref è illeggibile")
            if entry.group(3) == b"n":
                entries[number] = int(entry.group(1))
            position = entry.end()
    if not data.startswith(b"trailer", lexer.skip(position)):
        raise _bad("manca il trailer dopo la tabella xref")
    trailer, after = lexer.value(lexer.skip(position) + len(b"trailer"))
    if not isinstance(trailer, dict):
        raise _bad("il trailer non è un dizionario")
    if not data.startswith(b"startxref", lexer.skip(after)):
        raise _bad("dopo il trailer non c'è startxref: il PDF ha più revisioni")
    for key, problem in (
        ("Prev", "il PDF ha più revisioni (/Prev)"),
        ("XRefStm", "il PDF usa un flusso xref"),
        ("Encrypt", "il PDF è cifrato"),
    ):
        if key in trailer:
            raise _bad(problem)
    objects: dict[int, object] = {}
    lengths: list[tuple[int, int, dict[str, object]]] = []
    for number, where in sorted(entries.items()):
        header = _OBJECT.match(data, where)
        if header is None or int(header.group(1)) != number:
            raise _bad(f"l'oggetto {number} non è all'offset che la tabella xref dichiara")
        value, index = lexer.value(header.end())
        keyword, after_keyword = lexer.token(index)
        if keyword == "stream":
            if not isinstance(value, dict):
                raise _bad(f"il flusso dell'oggetto {number} non ha un dizionario")
            if value.get("Type") == Name("ObjStm") or value.get("Type") == Name("XRef"):
                raise _bad("il PDF usa flussi di oggetti o flussi xref")
            body = after_keyword
            if data.startswith(b"\r\n", body):
                body += 2
            elif data.startswith(b"\n", body):
                body += 1
            else:
                raise _bad(f"il flusso dell'oggetto {number} non comincia con un a capo")
            lengths.append((number, body, value))
            objects[number] = Stream(value, b"")
            continue
        if keyword != "endobj":
            raise _bad(f"l'oggetto {number} non finisce con endobj")
        objects[number] = value
    document = _Document(objects, trailer)
    for number, body, dictionary in lengths:
        length = document.resolve(dictionary.get("Length"))
        if not isinstance(length, int) or length < 0 or body + length > len(data):
            raise _bad(f"il flusso dell'oggetto {number} ha una /Length impossibile")
        end = lexer.skip(body + length)
        if not data.startswith(b"endstream", end):
            raise _bad(f"il flusso dell'oggetto {number} non finisce dove dice /Length")
        objects[number] = Stream(dictionary, data[body : body + length])
    return document, lexer


def _check_pages(document: _Document) -> None:
    root = document.dictionary(document.trailer.get("Root"))
    if root.get("Type") != Name("Catalog"):
        raise _bad("manca il catalogo /Root")
    pages = document.dictionary(root.get("Pages"))
    kids = document.resolve(pages.get("Kids"))
    if pages.get("Type") != Name("Pages") or pages.get("Count") != 1:
        raise Problem("regodoc.image.pdf_pages", "una figura in PDF ha una pagina sola")
    if not isinstance(kids, list) or len(kids) != 1:
        raise Problem("regodoc.image.pdf_pages", "una figura in PDF ha una pagina sola")
    page = document.dictionary(kids[0])
    if page.get("Type") != Name("Page"):
        raise Problem("regodoc.image.pdf_pages", "una figura in PDF ha una pagina sola")
    box = document.resolve(page.get("MediaBox", pages.get("MediaBox")))
    numbers = [document.resolve(item) for item in box] if isinstance(box, list) else []
    if len(numbers) != 4 or not all(
        isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers
    ):
        raise _bad("la pagina non ha una /MediaBox di quattro numeri")
    width = abs(float(numbers[2]) - float(numbers[0]))  # type: ignore[arg-type]
    height = abs(float(numbers[3]) - float(numbers[1]))  # type: ignore[arg-type]
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise _bad(f"la pagina misura {width:g} × {height:g} punti: ogni lato va da 1 a {MAX_SIDE}")


def _filters(document: _Document, dictionary: dict[str, object]) -> list[str]:
    value = document.resolve(dictionary.get("Filter"))
    items = value if isinstance(value, list) else [] if value is None else [value]
    names: list[str] = []
    for item in items:
        resolved = document.resolve(item)
        if not isinstance(resolved, Name):
            raise _bad("un /Filter che non è un nome")
        names.append(resolved.value)
    return names


def _check_streams(document: _Document) -> None:
    budget = MAX_STREAM_BYTES
    for value in document.objects.values():
        if not isinstance(value, Stream):
            continue
        filters = _filters(document, value.dictionary)
        for name in filters:
            if name not in FILTERS:
                raise Problem(
                    "regodoc.image.pdf_filter", f"il filtro /{name} non è ammesso in una figura"
                )
        data = value.raw
        for name in filters:
            if name == "DCTDecode":
                break  # i dati JPEG restano compressi: pdfTeX li copia così
            data = _decode(name, data, budget)
        if len(data) > budget:
            raise _over()
        budget -= len(data)


def _over() -> Problem:
    return Problem(
        "regodoc.limit.pdf",
        f"i flussi del PDF decompressi superano {MAX_STREAM_BYTES // (1024 * 1024)} MiB",
    )


def _decode(name: str, data: bytes, budget: int) -> bytes:
    """Un filtro applicato a ``data``; Flate e RunLength si fermano oltre ``budget`` byte."""
    try:
        if name == "FlateDecode":
            inflater = zlib.decompressobj()
            out = inflater.decompress(data, budget + 1)
            if len(out) > budget or inflater.unconsumed_tail:
                raise _over()
            return out
        if name == "ASCIIHexDecode":
            digits = bytes(b for b in data.split(b">", 1)[0] if b not in _WHITESPACE)
            return binascii.unhexlify(digits + b"0" * (len(digits) % 2))
        if name == "ASCII85Decode":
            body = data.strip(_WHITESPACE)
            body = body.removeprefix(b"<~")
            return base64.a85decode(body.split(b"~>", 1)[0], ignorechars=_WHITESPACE)
        # RunLengthDecode: la lunghezza d'uscita si conta prima di produrla.
        out = bytearray()
        position = 0
        while position < len(data):
            length = data[position]
            if length == 128:
                break
            if length < 128:
                chunk = data[position + 1 : position + 2 + length]
                position += 2 + length
            else:
                chunk = data[position + 1 : position + 2] * (257 - length)
                position += 2
            if len(out) + len(chunk) > budget:
                raise _over()
            out += chunk
        return bytes(out)
    except (zlib.error, binascii.Error, ValueError) as error:
        raise _bad(f"un flusso /{name} non si decodifica") from error


def _check_fonts(document: _Document) -> None:
    for value in document.objects.values():
        dictionary = value.dictionary if isinstance(value, Stream) else value
        if not isinstance(dictionary, dict) or dictionary.get("Type") != Name("Font"):
            continue
        subtype = document.resolve(dictionary.get("Subtype"))
        if subtype == Name("Type3"):
            if not document.dictionary(dictionary.get("CharProcs")):
                raise Problem("regodoc.image.pdf_font", "un font Type3 senza /CharProcs")
            continue
        if subtype == Name("Type0"):
            descendants = document.resolve(dictionary.get("DescendantFonts"))
            fonts = descendants if isinstance(descendants, list) else []
            if len(fonts) != 1:
                raise Problem("regodoc.image.pdf_font", "un font Type0 senza un /DescendantFonts")
            dictionary = document.dictionary(fonts[0])
        descriptor = document.dictionary(dictionary.get("FontDescriptor"))
        if not any(isinstance(document.resolve(descriptor.get(k)), Stream) for k in FONT_FILES):
            base = document.resolve(dictionary.get("BaseFont"))
            shown = base.value if isinstance(base, Name) else "senza nome"
            raise Problem(
                "regodoc.image.pdf_font",
                f"il font {shown} non è incorporato: il PDF dipenderebbe dai font della macchina",
            )
