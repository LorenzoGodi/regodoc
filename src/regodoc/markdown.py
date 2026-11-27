"""Il lettore del Markdown nudo, il formato d'ingresso md/1 (docs/spec/md-1.md).

Legge un sottoinsieme chiuso di Markdown e lo porta a un albero di blocchi, con la riga e la
colonna di ognuno: titoli, paragrafi, elenchi, tabelle, codice, figure, enfasi. Tutto il resto
è un errore con il suo codice, mai testo indovinato: HTML, link, immagini remote, citazioni,
note. Il lettore va per righe, senza ricorsione sull'ingresso, e le enfasi si appaiano con una
pila: il tempo cresce in modo lineare con il testo. Nessuna espressione regolare può tornare
indietro senza limite: le uniche usate sono ancorate e senza quantificatori annidati.
"""

import bisect
import re
from dataclasses import dataclass, field

from regodoc.source import IMAGE_PATH

# I limiti del file: la dimensione e i caratteri di una riga.
MAX_BYTES = 2 * 1024 * 1024
MAX_LINE = 10_000
# Le enfasi aperte insieme: il pacchetto non ammette <b> in <b> né <i> in <i>, quindi oltre
# poche annidature c'è un errore comunque; il tetto tiene lineare l'appaiamento.
MAX_OPEN_EMPHASIS = 8

# La punteggiatura ASCII che una barra rovescia rende letterale, come in CommonMark.
_ESCAPABLE = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_HEADING = re.compile(r"(#{1,7})(?:[ ]+(.*?))?[ ]*")
_CLOSING_HASHES = re.compile(r"[ ]+#+")
_FENCE = re.compile(r"(`{3,}|~{3,})(.*)")
_BULLET = re.compile(r"([ ]*)([-*])( +)(.*)")
_NUMBER = re.compile(r"([ ]*)([0-9]{1,9})([.)])( +)(.*)")
_THEMATIC = re.compile(r"[ ]{0,3}(?:(?:\*[ ]*){3,}|(?:-[ ]*){3,}|(?:_[ ]*){3,})")
_SETEXT = re.compile(r"[ ]{0,3}(?:=+|-+)[ ]*")
_DELIMITER_CELL = re.compile(r"[ ]*(:?)-+(:?)[ ]*")
_TASK = re.compile(r"\[[ xX]\][ ]")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{0,31}:")
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{0,31});")
_FIGURE = re.compile(r"!\[([^\]]*)\]\(([^)\s]*)\)")


@dataclass(frozen=True)
class Problem:
    code: str
    message: str
    line: int
    column: int = 0


# --- In linea ---------------------------------------------------------------------------------


@dataclass
class Text:
    text: str


@dataclass
class Code:
    text: str


@dataclass
class Strong:
    children: list["Inline"] = field(default_factory=list)


@dataclass
class Emphasis:
    children: list["Inline"] = field(default_factory=list)


Inline = Text | Code | Strong | Emphasis


# --- Blocchi ----------------------------------------------------------------------------------


@dataclass
class Paragraph:
    line: int
    inlines: list[Inline]


@dataclass
class Item:
    line: int
    inlines: list[Inline]
    sublist: "ListBlock | None" = None


@dataclass
class ListBlock:
    line: int
    numbered: bool
    items: list[Item] = field(default_factory=list)


@dataclass
class Table:
    line: int
    align: list[str]
    head: list[list[Inline]]
    rows: list[list[list[Inline]]]
    row_lines: list[int] = field(default_factory=list)


@dataclass
class Listing:
    line: int
    text: str


@dataclass
class Figure:
    line: int
    path: str
    caption: list[Inline]


Block = Paragraph | ListBlock | Table | Listing | Figure


@dataclass
class Section:
    line: int
    title: list[Inline]
    blocks: list[Block] = field(default_factory=list)
    sections: list["Section"] = field(default_factory=list)


@dataclass
class Chapter:
    """Un'apertura (``title`` vuoto) o una parte, con il titolo in testo puro."""

    line: int
    title: str
    blocks: list[Block] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


@dataclass
class Document:
    title: str = ""
    title_line: int = 0
    opening: Chapter | None = None
    parts: list[Chapter] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


# --- Testo e righe ----------------------------------------------------------------------------


def read(data: bytes) -> Document:
    """Legge ``document.md``. Un problema non ferma la lettura, salvo la codifica: i problemi
    stanno in ``problems``, nell'ordine del file."""
    document = Document()
    lines = _lines(data, document.problems)
    if lines is not None:
        _Reader(lines, document).run()
    return document


def _lines(data: bytes, problems: list[Problem]) -> list[str] | None:
    if len(data) > MAX_BYTES:
        problems.append(Problem("regodoc.limit.markdown", f"il file supera {MAX_BYTES} byte", 0))
        return None
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append(Problem("regodoc.text.encoding", "il file comincia con un BOM", 1, 1))
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        line = data[: error.start].count(b"\n") + 1
        problems.append(Problem("regodoc.text.encoding", "il file non è UTF-8 valido", line))
        return None
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    bad = False
    for number, line in enumerate(lines, 1):
        for char, what in (("\x00", "un carattere NUL"), ("\r", "un ritorno a capo da solo")):
            column = line.find(char)
            if column >= 0:
                problems.append(Problem("regodoc.text.encoding", what, number, column + 1))
                bad = True
        column = line.find("\t")
        if column >= 0:
            problems.append(
                Problem(
                    "regodoc.markdown.syntax",
                    "una tabulazione: rientri e allineamenti si scrivono con gli spazi",
                    number,
                    column + 1,
                )
            )
            bad = True
        if len(line) > MAX_LINE:
            problems.append(
                Problem(
                    "regodoc.limit.markdown",
                    f"la riga ha {len(line)} caratteri, il massimo è {MAX_LINE}",
                    number,
                )
            )
            bad = True
    return None if bad else [line.rstrip(" ") for line in lines]


# --- Blocchi ----------------------------------------------------------------------------------


class _Reader:
    def __init__(self, lines: list[str], document: Document) -> None:
        self.lines = lines
        self.document = document
        self.index = 0
        # Dove vanno i blocchi: l'apertura, la parte o la sezione corrente.
        self.chapter: Chapter | None = None
        self.stack: list[Section] = []

    def problem(self, code: str, message: str, line: int, column: int = 0) -> None:
        self.document.problems.append(Problem(code, message, line, column))

    def run(self) -> None:
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if not line.strip():
                self.index += 1
                continue
            self.block(line)
        if not self.document.title:
            self.problem(
                "regodoc.markdown.heading",
                "manca il titolo del documento: la prima riga è «# Titolo»",
                1,
            )
        if not self.document.parts:
            self.problem(
                "regodoc.markdown.heading",
                "il documento non ha parti: ogni parte comincia con «## Titolo»",
                max(1, len(self.lines)),
            )

    # Dove finisce un blocco: la riga comincia un blocco di un altro tipo.
    def starts_block(self, line: str) -> bool:
        stripped = line.lstrip(" ")
        if not stripped or (line.startswith("#") and _is_heading(line)):
            return True
        if _FENCE.match(stripped) or _THEMATIC.fullmatch(line):
            return True
        return stripped.startswith((">", "|")) or _list_marker(line) is not None

    def block(self, line: str) -> None:
        number = self.index + 1
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if line.startswith("#") and _is_heading(line):
            self.heading(line, number)
            self.index += 1
        elif _FENCE.match(stripped) and indent <= 3:
            self.fence(stripped, number)
        elif _THEMATIC.fullmatch(line):
            self.problem(
                "regodoc.markdown.unsupported",
                "una riga di separazione: il documento si divide con i titoli",
                number,
                indent + 1,
            )
            self.index += 1
        elif stripped.startswith(">") and indent <= 3:
            self.problem(
                "regodoc.markdown.unsupported",
                "una citazione con «>»: non c'è nel formato",
                number,
                indent + 1,
            )
            self.index += 1
        elif _list_marker(line) is not None:
            self.list_block(number)
        elif stripped.startswith("|") and indent <= 3:
            self.table(number)
        elif indent >= 4:
            self.problem(
                "regodoc.markdown.unsupported",
                "codice rientrato di quattro spazi: il codice si scrive fra «```»",
                number,
                1,
            )
            self.index += 1
            while self.index < len(self.lines) and self.lines[self.index].startswith("    "):
                self.index += 1
        else:
            self.paragraph(number)

    # -- Titoli --

    def heading(self, line: str, number: int) -> None:
        match = _HEADING.fullmatch(line)
        if match is None:  # pragma: no cover - _is_heading l'ha già controllato
            return
        level = len(match.group(1))
        text = _CLOSING_HASHES.sub("", match.group(2) or "").strip()
        if level > 5:
            self.problem(
                "regodoc.markdown.heading",
                f"un titolo di livello {level}: si va da «#» a «#####»",
                number,
                1,
            )
            return
        if not text:
            self.problem("regodoc.markdown.heading", "un titolo senza testo", number, 1)
            return
        if level == 1:
            if self.document.title or self.chapter is not None:
                self.problem(
                    "regodoc.markdown.heading",
                    "un secondo titolo «#»: il documento ne ha uno solo, in testa",
                    number,
                    1,
                )
                return
            self.document.title = _plain(text)
            self.document.title_line = number
            return
        if not self.document.title:
            self.problem(
                "regodoc.markdown.heading",
                "un titolo prima del titolo del documento «#»",
                number,
                1,
            )
        if level == 2:
            self.chapter = Chapter(number, _plain(text))
            self.document.parts.append(self.chapter)
            self.stack = []
            return
        depth = level - 3  # «###» è una sezione di primo livello
        if depth > len(self.stack):
            self.problem(
                "regodoc.markdown.heading",
                f"un titolo «{'#' * level}» salta un livello",
                number,
                1,
            )
            return
        section = Section(number, self.inlines([(number, line.index(text) + 1, text)]))
        del self.stack[depth:]
        container = self.stack[-1].sections if self.stack else self.current_chapter().sections
        container.append(section)
        self.stack.append(section)

    def current_chapter(self) -> Chapter:
        if self.chapter is None:
            self.chapter = Chapter(self.index + 1, "")
            self.document.opening = self.chapter
        return self.chapter

    def add(self, block: Block) -> None:
        if self.stack:
            self.stack[-1].blocks.append(block)
            return
        chapter = self.current_chapter()
        if chapter.sections:
            # Dopo una sottosezione il Markdown non ha un modo di tornare al livello di sopra.
            chapter.sections[-1].blocks.append(block)
            return
        chapter.blocks.append(block)

    # -- Codice --

    def fence(self, stripped: str, number: int) -> None:
        match = _FENCE.match(stripped)
        if match is None:  # pragma: no cover - block l'ha già controllato
            return
        marker = match.group(1)
        if marker[0] == "`" and "`" in match.group(2):
            self.problem("regodoc.markdown.syntax", "una riga di codice in linea con «```»", number)
            self.index += 1
            return
        body: list[str] = []
        self.index += 1
        while self.index < len(self.lines):
            line = self.lines[self.index]
            closing = line.lstrip(" ")
            if (
                closing.startswith(marker[0] * len(marker))
                and not closing.strip(marker[0])
                and len(line) - len(closing) <= 3
            ):
                self.index += 1
                self.add_listing(number, body)
                return
            body.append(line)
            self.index += 1
        self.problem(
            "regodoc.markdown.syntax",
            f"il blocco di codice aperto con «{marker}» non si chiude",
            number,
        )

    def add_listing(self, number: int, body: list[str]) -> None:
        if not any(line.strip() for line in body):
            self.problem("regodoc.markdown.syntax", "un blocco di codice vuoto", number)
            return
        self.add(Listing(number, "\n".join(body)))

    # -- Paragrafi e figure --

    def paragraph(self, number: int) -> None:
        parts: list[tuple[int, str]] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if parts and _SETEXT.fullmatch(line):
                self.problem(
                    "regodoc.markdown.heading",
                    "un titolo sottolineato con «=» o «-»: i titoli si scrivono con «#»",
                    self.index + 1,
                    1,
                )
                self.index += 1
                return
            if parts and self.starts_block(line):
                break
            parts.append((self.index + 1, line.strip()))
            self.index += 1
        first = parts[0][1]
        figure = _FIGURE.fullmatch(first) if len(parts) == 1 else None
        if figure is not None:
            self.figure(figure, number, self.lines[number - 1].index("!") + 1)
            return
        self.add(Paragraph(number, self.inlines(self.pieces(parts))))

    def pieces(self, parts: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
        """Le righe di un blocco con la colonna da cui comincia il loro testo."""
        return [(number, self.lines[number - 1].index(text[0]) + 1, text) for number, text in parts]

    def figure(self, match: re.Match[str], number: int, column: int) -> None:
        caption, path = match.group(1), match.group(2)
        if _SCHEME.match(path) or path.startswith("//"):
            self.problem(
                "regodoc.markdown.remote_image",
                f"un'immagine remota, «{_clip(path)}»: le figure vengono dai file di images/",
                number,
                column,
            )
            return
        if not IMAGE_PATH.fullmatch(path):
            self.problem(
                "regodoc.markdown.image",
                f"«{_clip(path)}» non è un'immagine ammessa: images/nome.png, .jpg o .jpeg",
                number,
                column,
            )
            return
        inlines = self.inlines([(number, column + 2, caption)]) if caption.strip() else []
        self.add(Figure(number, path, inlines))

    # -- Elenchi --

    def list_block(self, number: int) -> None:
        # Per ogni livello aperto: il rientro del segno, la colonna del testo e l'elenco.
        indents: list[int] = []
        columns: list[int] = []
        lists: list[ListBlock] = []
        last: Item | None = None
        text: list[tuple[int, str]] = []

        def flush() -> None:
            if last is not None and text:
                last.inlines = self.inlines(self.pieces(text))
            text.clear()

        def continues(marker: tuple[int, bool, int, int, str] | None) -> bool:
            return marker is not None and (marker[0] in indents or marker[0] == columns[-1])

        while self.index < len(self.lines):
            line = self.lines[self.index]
            line_number = self.index + 1
            if not line.strip():
                following = self.index + 1
                while following < len(self.lines) and not self.lines[following].strip():
                    following += 1
                if following >= len(self.lines) or not continues(
                    _list_marker(self.lines[following])
                ):
                    break
                self.index = following
                continue
            marker = _list_marker(line)
            if marker is None:
                if self.starts_block(line):
                    break
                text.append((line_number, line.strip()))  # il seguito della voce
                self.index += 1
                continue
            indent, numbered, first, content_column, body = marker
            if not lists or (indent == columns[-1] and indent not in indents):
                # Un elenco nuovo: il primo, o annidato sotto l'ultima voce.
                flush()
                block = ListBlock(line_number, numbered)
                if numbered and first != 1:
                    self.problem(
                        "regodoc.markdown.unsupported",
                        "un elenco numerato comincia da 1",
                        line_number,
                        indent + 1,
                    )
                if last is not None:
                    last.sublist = block
                lists.append(block)
                indents.append(indent)
                columns.append(content_column)
            elif indent in indents:
                flush()
                level = indents.index(indent)
                if level == 0 and lists[0].numbered != numbered:
                    break  # un elenco dell'altro tipo comincia qui, come in CommonMark
                del indents[level + 1 :]
                del columns[level + 1 :]
                del lists[level + 1 :]
                columns[level] = content_column
                if lists[-1].numbered != numbered:
                    self.problem(
                        "regodoc.markdown.syntax",
                        "un elenco che cambia tipo fra puntato e numerato",
                        line_number,
                        indent + 1,
                    )
            else:
                self.problem(
                    "regodoc.markdown.syntax",
                    "una voce rientrata fuori colonna: il rientro arriva al testo della voce di "
                    "sopra",
                    line_number,
                    1,
                )
                self.index += 1
                continue
            if _TASK.match(body):
                self.problem(
                    "regodoc.markdown.unsupported",
                    "una voce da spuntare «[ ]»: non c'è nel formato",
                    line_number,
                    content_column + 1,
                )
            last = Item(line_number, [])
            lists[-1].items.append(last)
            text.append((line_number, body))
            self.index += 1
        flush()
        if lists:
            root = lists[0]
            self.add(root)
            self.check_items(root)

    def check_items(self, block: ListBlock) -> None:
        pending = [block]
        while pending:
            current = pending.pop()
            for item in current.items:
                if not item.inlines:
                    self.problem("regodoc.markdown.syntax", "una voce senza testo", item.line)
                if item.sublist is not None:
                    pending.append(item.sublist)

    # -- Tabelle --

    def table(self, number: int) -> None:
        rows: list[tuple[int, str]] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if not line.lstrip(" ").startswith("|"):
                break
            rows.append((self.index + 1, line.strip()))
            self.index += 1
        if len(rows) < 2 or not _is_delimiter_row(rows[1][1]):
            self.problem(
                "regodoc.markdown.syntax",
                "una tabella vuole la riga d'intestazione e poi la riga «|---|---|»",
                number,
            )
            return
        align: list[str] = []
        for cell in _split_row(rows[1][1]):
            match = _DELIMITER_CELL.fullmatch(cell)
            if match is None:  # pragma: no cover - _is_delimiter_row l'ha già controllato
                return
            left, right = bool(match.group(1)), bool(match.group(2))
            if left and right:
                self.problem(
                    "regodoc.markdown.unsupported",
                    "una colonna centrata «:---:»: le colonne vanno a sinistra o a destra",
                    rows[1][0],
                )
            align.append("right" if right and not left else "left")
        cells: list[list[list[Inline]]] = []
        for line_number, text in [rows[0], *rows[2:]]:
            if not (text.endswith("|") and not text.endswith("\\|")):
                self.problem(
                    "regodoc.markdown.syntax",
                    "una riga di tabella comincia e finisce con «|»",
                    line_number,
                )
                return
            row = _split_row(text)
            if len(row) != len(align):
                self.problem(
                    "regodoc.markdown.syntax",
                    f"la riga ha {len(row)} celle, la tabella {len(align)} colonne",
                    line_number,
                )
                return
            cells.append(
                [
                    self.inlines([(line_number, 1, cell.strip().replace("\\|", "|"))])
                    if cell.strip()
                    else []
                    for cell in row
                ]
            )
        self.add(Table(number, align, cells[0], cells[1:], [line for line, _ in rows[2:]]))

    # -- In linea --

    def inlines(self, pieces: list[tuple[int, int, str]]) -> list[Inline]:
        """Il testo in linea di un blocco, fatto di una o più righe: riga, colonna e testo."""
        return _Inline(self, pieces).run()


def _is_heading(line: str) -> bool:
    match = _HEADING.fullmatch(line)
    return match is not None and (match.group(2) is not None or line.rstrip("#") == "")


def _list_marker(line: str) -> tuple[int, bool, int, int, str] | None:
    """Rientro, se numerato, numero, colonna del testo e testo di una voce d'elenco."""
    if _THEMATIC.fullmatch(line):
        return None
    match = _BULLET.fullmatch(line)
    if match is not None:
        indent, spaces, body = len(match.group(1)), len(match.group(3)), match.group(4)
        if spaces != 1 or not body:
            return None
        return indent, False, 0, indent + 2, body
    match = _NUMBER.fullmatch(line)
    if match is not None:
        indent = len(match.group(1))
        spaces, body = len(match.group(4)), match.group(5)
        if spaces != 1 or not body:
            return None
        width = len(match.group(2)) + 1
        return indent, True, int(match.group(2)), indent + width + 1, body
    return None


def _is_delimiter_row(text: str) -> bool:
    if not (text.startswith("|") and text.endswith("|")):
        return False
    return all(_DELIMITER_CELL.fullmatch(cell) for cell in _split_row(text))


def _split_row(text: str) -> list[str]:
    """Le celle di una riga «| a | b |», senza le barre di testa e di coda; «\\|» resta nella
    cella."""
    inner = text[1:-1]
    cells: list[str] = []
    start = 0
    position = 0
    while position < len(inner):
        char = inner[position]
        if char == "\\" and position + 1 < len(inner):
            position += 2
            continue
        if char == "|":
            cells.append(inner[start:position])
            start = position + 1
        position += 1
    cells.append(inner[start:])
    return cells


def _plain(text: str) -> str:
    """Il testo di un titolo di parte o del documento: testo puro, con le fughe risolte."""
    out = []
    position = 0
    while position < len(text):
        char = text[position]
        if char == "\\" and position + 1 < len(text) and text[position + 1] in _ESCAPABLE:
            out.append(text[position + 1])
            position += 2
            continue
        out.append(char)
        position += 1
    return "".join(out)


def _clip(text: str, size: int = 60) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


def _merge(inlines: list[Inline]) -> list[Inline]:
    """Unisce i testi vicini."""
    out: list[Inline] = []
    for node in inlines:
        if isinstance(node, Text) and out and isinstance(out[-1], Text):
            out[-1] = Text(out[-1].text + node.text)
        else:
            out.append(node)
    return out


# --- In linea -----------------------------------------------------------------------------------


class _Inline:
    """Il testo in linea di un blocco: enfasi, codice e fughe; il resto è un errore."""

    def __init__(self, reader: _Reader, pieces: list[tuple[int, int, str]]) -> None:
        self.reader = reader
        # Le righe si uniscono con un a capo, che nel testo vale uno spazio.
        self.text = "\n".join(piece for _, _, piece in pieces)
        self.pieces = pieces
        self.starts: list[int] = []
        offset = 0
        for _, _, piece in pieces:
            self.starts.append(offset)
            offset += len(piece) + 1
        # La pila delle enfasi aperte: il segno («**», «*», «_»), il nodo e la colonna.
        self.stack: list[tuple[str, Strong | Emphasis, int]] = []
        self.root: list[Inline] = []
        self.buffer: list[str] = []
        self.failed = False
        # La prossima «]» dopo l'ultima cercata: -1 se non ce ne sono più.
        self.next_close = 0

    def problem(self, code: str, message: str, position: int) -> None:
        index = bisect.bisect_right(self.starts, position) - 1
        line, column, _ = self.pieces[index]
        self.reader.problem(code, message, line, column + position - self.starts[index])
        self.failed = True

    def target(self) -> list[Inline]:
        return self.stack[-1][1].children if self.stack else self.root

    def flush(self) -> None:
        if self.buffer:
            self.target().append(Text("".join(self.buffer)))
            self.buffer.clear()

    def run(self) -> list[Inline]:
        text = self.text
        position = 0
        while position < len(text) and not self.failed:
            char = text[position]
            if char == "\\" and position + 1 < len(text) and text[position + 1] in _ESCAPABLE:
                self.buffer.append(text[position + 1])
                position += 2
            elif char == "`":
                position = self.code(position)
            elif char in "*_":
                position = self.delimiter(position)
            elif char == "<":
                rest = text[position + 1 : position + 2]
                if _SCHEME.match(text, position + 1):
                    self.problem(
                        "regodoc.markdown.link",
                        "un collegamento «<…>»: i collegamenti non ci sono nel formato",
                        position,
                    )
                elif rest.isalpha() or rest in ("/", "!", "?"):
                    self.problem(
                        "regodoc.markdown.html",
                        "HTML nel testo: il formato non lo ammette; «\\<» scrive il segno",
                        position,
                    )
                else:
                    self.buffer.append(char)
                position += 1
            elif char == "!" and text.startswith("![", position):
                self.problem(
                    "regodoc.markdown.image",
                    "un'immagine dentro il testo: una figura sta da sola nel suo paragrafo",
                    position,
                )
            elif char == "[":
                position = self.bracket(position)
            elif char == "&" and _ENTITY.match(text, position):
                self.problem(
                    "regodoc.markdown.unsupported",
                    "un riferimento a carattere HTML «&…;»: si scrive il carattere",
                    position,
                )
            elif char == "~" and text.startswith("~~", position):
                self.problem(
                    "regodoc.markdown.unsupported", "il barrato «~~»: non c'è nel formato", position
                )
            else:
                self.buffer.append(" " if char == "\n" else char)
                position += 1
        if self.failed:
            return []
        self.flush()
        if self.stack:
            sign, _, column = self.stack[0]
            self.problem(
                "regodoc.markdown.syntax", f"l'enfasi aperta con «{sign}» non si chiude", column
            )
            return []
        return _merge(self.root)

    def code(self, position: int) -> int:
        text = self.text
        end = position
        while end < len(text) and text[end] == "`":
            end += 1
        run = text[position:end]
        close = end
        while True:
            close = text.find(run, close)
            if close < 0:
                self.problem(
                    "regodoc.markdown.syntax",
                    f"il codice aperto con «{run}» non si chiude",
                    position,
                )
                return len(text)
            after = close + len(run)
            if after < len(text) and text[after] == "`":
                close = after
                while close < len(text) and text[close] == "`":
                    close += 1
                continue
            break
        body = text[end:close].replace("\n", " ")
        if len(body) > 2 and body.startswith(" ") and body.endswith(" ") and body.strip():
            body = body[1:-1]
        if not body.strip():
            self.problem("regodoc.markdown.syntax", "un codice in linea vuoto", position)
            return len(text)
        self.flush()
        self.target().append(Code(body))
        return close + len(run)

    def bracket(self, position: int) -> int:
        text = self.text
        if text.startswith("[^", position):
            self.problem(
                "regodoc.markdown.unsupported", "una nota «[^…]»: non c'è nel formato", position
            )
            return len(text)
        if self.next_close != -1 and self.next_close <= position:
            self.next_close = text.find("]", position + 1)
        close = self.next_close
        if close >= 0 and close + 1 < len(text) and text[close + 1] in "([":
            self.problem(
                "regodoc.markdown.link",
                "un collegamento «[…](…)»: i collegamenti non ci sono nel formato",
                position,
            )
            return len(text)
        if close >= 0 and close + 1 < len(text) and text[close + 1] == ":" and position == 0:
            self.problem(
                "regodoc.markdown.link",
                "una definizione di collegamento «[…]: …»: non c'è nel formato",
                position,
            )
            return len(text)
        self.buffer.append("[")
        return position + 1

    def delimiter(self, position: int) -> int:
        text = self.text
        char = text[position]
        end = position
        while end < len(text) and text[end] == char:
            end += 1
        size = end - position
        before = text[position - 1] if position else " "
        after = text[end] if end < len(text) else " "
        can_open = not after.isspace()
        can_close = not before.isspace()
        if char == "_":
            # Dentro una parola, come in nome_del_file, il trattino basso è un carattere.
            can_open = can_open and not before.isalnum()
            can_close = can_close and not after.isalnum()
        if not (can_open or can_close):
            self.buffer.append(char * size)
            return end
        if size > 3:
            self.problem(
                "regodoc.markdown.syntax",
                f"«{char * size}»: l'enfasi usa uno, due o tre segni",
                position,
            )
            return len(text)
        # Le enfasi aperte in cima alla pila con lo stesso segno, e quanti segni chiudono.
        closable: list[int] = []
        total = 0
        for sign, _, _ in reversed(self.stack):
            if sign[0] != char:
                break
            total += len(sign)
            closable.append(total)
        if can_close and size in closable:
            self.flush()
            del self.stack[len(self.stack) - closable.index(size) - 1 :]
            return end
        if can_open:
            if len(self.stack) >= MAX_OPEN_EMPHASIS:
                self.problem(
                    "regodoc.markdown.syntax",
                    f"più di {MAX_OPEN_EMPHASIS} enfasi aperte insieme",
                    position,
                )
                return len(text)
            self.flush()
            for sign in {3: (char * 2, char), 2: (char * 2,), 1: (char,)}[size]:
                node: Strong | Emphasis = Strong() if len(sign) == 2 else Emphasis()
                self.target().append(node)
                self.stack.append((sign, node, position))
            return end
        message = (
            f"«{char * size}» non chiude l'enfasi aperta con «{self.stack[-1][0]}»"
            if closable
            else "un'enfasi chiusa che non era aperta"
        )
        self.problem("regodoc.markdown.syntax", message, position)
        return len(text)
