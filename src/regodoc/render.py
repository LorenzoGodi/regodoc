"""Dal pacchetto letto al testo LaTeX di ``document.tex``.

È una funzione pura: non legge file, orologi né ambiente. Lo stesso pacchetto, con la stessa
data, la stessa cornice e la stessa tavolozza, dà sempre lo stesso testo.

Il testo del pacchetto non passa mai al LaTeX così com'è (specifica, §5.5): ogni carattere è
trascritto qui, e i comandi ricevono solo testo trascritto o valori che il motore ha
controllato (id, percorsi d'immagine, misure). I comandi emessi sono quelli di
``regodoc.sty`` con il prefisso ``\\Rd`` (contratto, §6.4).
"""

import datetime
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from regodoc.declaration import THEME_ROLES
from regodoc.parts import Node, Text
from regodoc.texts import (
    BOX_ROLES,
    EN_DASH,
    LABEL_ROLES,
    WORDS,
    format_date,
    render_variable,
    roman,
)
from regodoc.tomlfiles import PartEntry, Structure, Variable

# Caratteri speciali del LaTeX nel testo normale, con la loro trascrizione (fontenc T1).
# «<» e «>» diventano comandi anche perché in T1 «<<» e «>>» sarebbero legature («, »);
# l'accento grave perché «?`» e «!`» lo sarebbero (¿, ¡).
_TEXT_ESCAPES: Final = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "|": r"\textbar{}",
    "`": r"\textasciigrave{}",
    "\u00a0": "~",
}
# Nel codice le virgolette e l'apostrofo restano dritti (specifica, §4.3).
_CODE_ESCAPES: Final = {**_TEXT_ESCAPES, '"': r"\textquotedbl{}", "'": r"\textquotesingle{}"}
# Dopo questi caratteri il codice, gli indirizzi e i collegamenti stampati possono andare a
# capo; in una sequenza lunga senza nessuno di loro, ogni ``_RUN`` caratteri.
_BREAK_AFTER: Final = frozenset("/.,;:-_=&?@)]}")
_RUN: Final = 16
# Lunghezza delle righe di document.tex: oltre ``_WRAP`` uno spazio diventa un a capo; una
# riga senza spazi si spezza con «%» oltre ``_HARD_WRAP``. TeX legge righe di lunghezza
# limitata, e un paragrafo del pacchetto può essere lungo centinaia di KiB.
_WRAP: Final = 78
_HARD_WRAP: Final = 200

_SPACES = re.compile(r"[ \t\n\r]+")

# Il ruolo dei riquadri «status» fuori da una parte, cioè in un'apertura, che non ha accento.
OPENING_ROLE: Final = "gray"


class _Space:
    """Uno spazio del testo: nella scrittura può diventare un a capo."""


SPACE: Final = _Space()
Piece = str | _Space


def escape(text: str, *, code: bool = False, breakable: bool = False) -> list[Piece]:
    """Trascrive un testo già convertito (tipografia, spazi) in pezzi di LaTeX.

    Ogni pezzo è un carattere trascritto oppure uno spazio: chi scrive può andare a capo fra
    due pezzi qualsiasi senza cambiare il testo. ``code`` lascia dritte le virgolette;
    ``breakable`` aggiunge punti dove il testo può andare a capo, per codice e indirizzi.
    """
    table = _CODE_ESCAPES if code else _TEXT_ESCAPES
    pieces: list[Piece] = []
    run = 0
    for index, char in enumerate(text):
        if char == " ":
            pieces.append(SPACE)
            run = 0
            continue
        piece = table.get(char, char)
        following = text[index + 1] if index + 1 < len(text) else ""
        # Legature di T1 da spezzare: «,,» darebbe „ e, nel codice, «--» il trattino breve.
        if (char == "," and following == ",") or (code and char == "-" and following == "-"):
            piece += "{}"
        pieces.append(piece)
        run += 1
        if breakable and following not in ("", " ") and (char in _BREAK_AFTER or run >= _RUN):
            pieces.append(r"\RdAB{}")
            run = 0
    return pieces


def typography(text: str, quotes: list[int]) -> str:
    """Le conversioni del §5.3 su un pezzo di testo: «--», virgolette e apostrofo.

    ``quotes`` è il contatore delle virgolette del blocco, condiviso fra i pezzi: le
    virgolette si appaiano dentro lo stesso blocco.
    """
    text = text.replace("--", EN_DASH).replace("'", "\u2019")
    if '"' not in text:
        return text
    out = []
    for char in text:
        if char == '"':
            out.append("\u201c" if quotes[0] % 2 == 0 else "\u201d")
            quotes[0] += 1
        else:
            out.append(char)
    return "".join(out)


def plain(text: str) -> list[Piece]:
    """Un valore di testo puro (TOML, attributi, titolo di una fonte), trascritto."""
    return escape(typography(_SPACES.sub(" ", text).strip(), [0]))


def join(pieces: Iterable[Piece]) -> str:
    """I pezzi su una riga sola, con gli spazi come spazi."""
    return "".join(" " if piece is SPACE else piece for piece in pieces)  # type: ignore[misc]


def wrap(pieces: Iterable[Piece]) -> str:
    """I pezzi su righe di lunghezza limitata, con a capo che TeX legge come gli originali."""
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for piece in pieces:
        if piece is SPACE:
            if length >= _WRAP:
                lines.append("".join(current))
                current, length = [], 0
            else:
                current.append(" ")
                length += 1
            continue
        text = str(piece)
        if length >= _HARD_WRAP:
            current.append("%")  # a capo senza spazio
            lines.append("".join(current))
            current, length = [], 0
        current.append(text)
        length += len(text)
    lines.append("".join(current))
    return "\n".join(lines)


def hex_url(url: str) -> str:
    """Un indirizzo in esadecimale: ``regodoc.sty`` lo decodifica con ``\\pdfunescapehex``,
    così nessun carattere dell'indirizzo è mai letto come LaTeX."""
    return url.encode("ascii").hex().upper()


# --- Documento ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """Ciò che serve all'emettitore: il pacchetto letto e i dati di chi chiama."""

    structure: Structure
    variables: Mapping[str, Variable]
    roots: Mapping[str, Node]
    date: datetime.date
    frame: Mapping[str, str] = field(default_factory=dict)
    palette: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Section:
    entry: str
    title: Node


@dataclass
class _Index:
    """Rimandi e citazioni: sezioni con id, numeri delle parti e delle fonti."""

    entries: dict[str, PartEntry] = field(default_factory=dict)
    sections: dict[str, _Section] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)
    labels: set[str] = field(default_factory=set)


def _build_index(document: Document) -> _Index:
    index = _Index(entries={entry.id: entry for entry in document.structure.entries})
    count = 0
    for entry in document.structure.entries:
        root = document.roots[entry.id]
        pending = [root]
        while pending:
            node = pending.pop(0)
            children = node.elements()
            if node.tag == "section" and "id" in node.attrs and children:
                index.sections[node.attrs["id"]] = _Section(entry.id, children[0])
            elif node.tag == "source":
                count += 1
                if "id" in node.attrs:
                    index.sources[node.attrs["id"]] = count
            elif node.tag == "label":
                index.labels.add(node.attrs["type"])
            pending[0:0] = children
    return index


def render_document(document: Document) -> str:
    """Il testo completo di ``document.tex``."""
    return _Emitter(document).run()


class _Emitter:
    def __init__(self, document: Document) -> None:
        self.document = document
        self.structure = document.structure
        self.language = document.structure.language
        self.words = WORDS[self.language]
        self.index = _build_index(document)
        self.lines: list[str] = []
        self.entry: PartEntry | None = None

    def out(self, line: str) -> None:
        self.lines.append(line)

    def run(self) -> str:
        self.preamble()
        self.out(r"\begin{document}")
        self.out(r"\RdTitlePage")
        if self.structure.toc:
            self.out(r"\RdTableOfContents")
        if self.index.labels:
            self.out(rf"\begin{{RdLegend}}{{{join(plain(self.words.legend))}}}")
            for kind in LABEL_ROLES:
                if kind in self.index.labels:
                    label = join(plain(self.words.labels[kind]))
                    self.out(rf"\RdLegendItem{{{LABEL_ROLES[kind]}}}{{{label}}}")
            self.out(r"\end{RdLegend}")
        for entry in self.structure.entries:
            self.entry = entry
            root = self.document.roots[entry.id]
            self.out("")
            if entry.kind == "opening":
                self.out(rf"\RdOpening{{rd-{entry.id}}}")
            else:
                title = wrap(plain(entry.title))
                self.out(rf"\RdPart{{{roman(entry.number)}}}{{{entry.accent}}}{{rd-{entry.id}}}")
                self.out(f"{{{title}}}")
            self.container(root, level=0)
        self.out("")
        self.out(r"\RdCheckContent")
        self.out(r"\end{document}")
        return "\n".join(self.lines) + "\n"

    # Preambolo

    def preamble(self) -> None:
        header = self.structure.header
        self.out(r"\documentclass[a4paper,11pt]{article}")
        self.out(rf"\usepackage[{self.language}]{{regodoc}}")
        for role in THEME_ROLES:
            self.out(rf"\RdColor{{{role}}}{{{self.document.palette[role]}}}")
        words = self.words
        self.out(rf"\RdNames{{{words.part}}}{{{words.figure}}}{{{words.contents}}}")
        self.out(rf"\RdTitle{{{wrap(plain(str(header['title'])))}}}")
        for key, command in (
            ("subject", "RdSubject"),
            ("reference", "RdReference"),
            ("version_label", "RdVersionLabel"),
        ):
            if key in header:
                self.out(rf"\{command}{{{wrap(plain(str(header[key])))}}}")
        self.out(rf"\RdDate{{{join(plain(format_date(self.document.date, self.language)))}}}")
        for key in sorted(self.document.frame):
            value = wrap(plain(self.document.frame[key]))
            self.out(rf"\RdFrame{{{key}}}{{{value}}}")

    # Contenitori e blocchi

    def container(self, node: Node, level: int) -> None:
        elements = node.elements()
        start = 0
        if node.tag == "part" and elements and elements[0].tag == "summary":
            self.out(rf"\RdSummary{{{wrap(self.mixed(elements[0]))}}}")
            start = 1
        for child in elements[start:]:
            if child.tag == "section":
                self.section(child, level + 1)
            else:
                self.block(child)

    def section(self, node: Node, level: int) -> None:
        elements = node.elements()
        title = elements[0]
        anchor = f"rd-{node.attrs['id']}" if "id" in node.attrs else ""
        self.out("")
        self.out(rf"\RdSection{{{level}}}{{{anchor}}}")
        self.out(f"{{{wrap(self.mixed(title))}}}")
        self.out(f"{{{wrap(self.mixed(title, bookmark=True))}}}")
        for child in elements[1:]:
            if child.tag == "section":
                self.section(child, level + 1)
            else:
                self.block(child)

    def block(self, node: Node) -> None:
        tag = node.tag
        if tag == "p":
            self.out("")
            self.out(wrap(self.mixed(node)))
            self.out(r"\par")
        elif tag == "list":
            self.list_block(node)
        elif tag == "box":
            kind = node.attrs["type"]
            role = BOX_ROLES.get(kind) or self.accent()
            title = join(plain(self.words.boxes[kind])) if self.words.boxes[kind] else ""
            self.out(rf"\begin{{RdBox}}{{{role}}}{{{title}}}")
            self.small_blocks(node)
            self.out(r"\end{RdBox}")
        elif tag == "small":
            self.out(r"\begin{RdSmall}")
            self.small_blocks(node)
            self.out(r"\end{RdSmall}")
        elif tag == "table":
            self.table(node)
        elif tag == "figure":
            self.figure(node)
        elif tag == "listing":
            self.listing(node)
        elif tag == "sources":
            self.sources(node)
        else:  # pragma: no cover - il validatore lo esclude
            raise ValueError(tag)

    def accent(self) -> str:
        return self.entry.accent if self.entry and self.entry.kind == "part" else OPENING_ROLE

    def small_blocks(self, node: Node) -> None:
        for child in node.elements():
            self.block(child)

    def list_block(self, node: Node) -> None:
        kind = node.attrs.get("type", "bullet")
        self.out(rf"\begin{{RdList}}{{{kind}}}")
        for item in node.elements():
            nested = [child for child in item.elements() if child.tag == "list"]
            if nested:
                position = item.children.index(nested[-1])
                text = Node(item.tag, {}, item.line, item.column, item.children[:position])
                self.out(rf"\RdItem {wrap(self.mixed(text))}")
                self.list_block(nested[-1])
            else:
                self.out(rf"\RdItem {wrap(self.mixed(item))}")
        self.out(r"\end{RdList}")

    def figure(self, node: Node) -> None:
        captions = node.elements()
        caption = wrap(self.mixed(captions[0])) if captions else ""
        width = node.attrs.get("width", "1")
        self.out(rf"\RdFigure{{{node.attrs['file']}}}{{{width}}}")
        self.out(f"{{{caption}}}")

    def listing(self, node: Node) -> None:
        body = "".join(child.value for child in node.children if isinstance(child, Text))
        body = body.removeprefix("\n").removesuffix("\n")
        self.out(r"\begin{RdListing}")
        for line in body.split("\n"):
            pieces = escape(line, code=True, breakable=True)
            self.out(rf"\RdListingLine{{{join(r'~' if p is SPACE else p for p in pieces)}}}")
        self.out(r"\end{RdListing}")

    def sources(self, node: Node) -> None:
        self.out(rf"\begin{{RdSources}}{{{join(plain(self.words.sources))}}}")
        number = 0  # le fonti si numerano nell'ordine dell'elenco
        for child in node.elements():
            if child.tag == "group":
                self.out(rf"\RdSourceGroup{{{wrap(plain(child.attrs['title']))}}}")
                sources = child.elements()
            else:
                sources = [child]
            for source in sources:
                number += 1
                self.source(source, number)
        self.out(r"\end{RdSources}")

    def source(self, node: Node, number: int) -> None:
        identifier = node.attrs.get("id")
        anchor = f"rd-{identifier}" if identifier else ""
        title = "".join(child.value for child in node.children if isinstance(child, Text))
        href = node.attrs["href"]
        accessed = ""
        if "accessed" in node.attrs:
            day = datetime.date.fromisoformat(node.attrs["accessed"])
            accessed = join(plain(f"{self.words.accessed} {format_date(day, self.language)}"))
        self.out(rf"\RdSource{{{number}}}{{{anchor}}}{{{hex_url(href)}}}")
        self.out(f"{{{join(escape(href, code=True, breakable=True))}}}")
        self.out(f"{{{wrap(plain(title))}}}")
        self.out(f"{{{wrap(plain(node.attrs['publisher']))}}}")
        self.out(f"{{{accessed}}}")

    # Tabelle

    def table(self, node: Node) -> None:
        columns = node.attrs["columns"].split(" ")
        landscape = node.attrs.get("orientation") == "landscape"
        small = len(columns) > 8 and not landscape
        stars = columns.count("*")
        fixed = sum(float(c.removesuffix("cm")) for c in columns if c != "*")
        widths = [r"\RdStar" if c == "*" else c for c in columns]
        spec = "".join(f">{{\\RdCellStart}}p{{{w}}}" for w in widths)
        if landscape:
            self.out(r"\begin{RdLandscape}")
        size = "small" if small else "normal"
        self.out(rf"\begin{{RdTable}}{{{size}}}{{{len(columns)}}}{{{stars}}}{{{fixed:g}cm}}")
        self.out(f"{{{spec}}}")
        rows = node.elements()
        for row in rows:
            if row.tag == "separator":
                self.out(r"\RdSeparator")
                continue
            kind = "head" if row.tag == "head" else row.attrs.get("type", "row")
            column = 0
            cells = []
            for cell in row.elements():
                span = int(cell.attrs.get("span", "1"))
                taken = widths[column : column + span]
                column += span
                width = taken[0] if span == 1 else self.span_width(taken)
                cells.append(rf"\RdCell{{{kind}}}{{{span}}}{{{width}}}{{{self.cell(cell)}}}")
            self.out("\n&".join(cells))
            self.out(r"\RdHeadEnd" if kind == "head" else r"\RdRowEnd")
        self.out(r"\end{RdTable}")
        if landscape:
            self.out(r"\end{RdLandscape}")

    @staticmethod
    def span_width(widths: list[str]) -> str:
        """La larghezza di una cella su più colonne: le colonne e gli spazi fra di loro."""
        gaps = 2 * (len(widths) - 1)
        return rf"\dimexpr{'+'.join(widths)}+{gaps}\tabcolsep\relax"

    def cell(self, cell: Node) -> str:
        elements = cell.elements()
        if any(child.tag in ("p", "list") for child in elements):
            parts = []
            for child in elements:
                if child.tag == "p":
                    parts.append(wrap(self.mixed(child)) + r"\par")
                else:
                    saved, self.lines = self.lines, []
                    self.list_block(child)
                    parts.append("\n".join(self.lines))
                    self.lines = saved
            return "\n".join(parts)
        return wrap(self.mixed(cell))

    # Testo misto

    def mixed(self, node: Node, *, bookmark: bool = False) -> list[Piece]:
        """Un blocco di testo misto: spazi ridotti, tipografia e trascrizione (§5)."""
        writer = _Mixed(self, bookmark=bookmark)
        writer.children(node)
        return writer.pieces

    def reference(self, node: Node) -> list[Piece]:
        target = node.attrs["to"]
        through = node.attrs.get("through")
        index = self.index
        if target in index.entries:
            number = roman(index.entries[target].number)
            if through:
                last = roman(index.entries[through].number)
                text = f"{self.words.parts}\u00a0{number}{EN_DASH}{last}"
            else:
                text = f"{self.words.part}\u00a0{number}"
            return [rf"\RdRef{{rd-{target}}}{{{join(escape(text))}}}"]
        section = index.sections[target]
        title = _Mixed(self, bookmark=False)
        title.children(section.title)
        text = f"\u201c{join(title.pieces)}\u201d"
        if self.entry is None or section.entry != self.entry.id:
            number = roman(index.entries[section.entry].number)
            text += join(escape(f" ({self.words.part}\u00a0{number})"))
        return [rf"\RdRef{{rd-{target}}}{{{text}}}"]


class _Mixed:
    """Scrive un blocco di testo misto, con gli spazi del §5.1 su tutto il blocco."""

    def __init__(self, emitter: _Emitter, *, bookmark: bool) -> None:
        self.emitter = emitter
        self.bookmark = bookmark
        self.pieces: list[Piece] = []
        self.quotes = [0]
        self.started = False  # c'è già testo visibile nel blocco
        self.pending = False  # uno spazio da scrivere prima del testo che segue
        self.spaced = False  # l'ultimo spazio scritto non ha ancora testo dopo di sé

    def space(self) -> None:
        """Scrive lo spazio in attesa, se serve: mai all'inizio del blocco, mai due di fila."""
        if self.pending and self.started and not self.spaced:
            self.pieces.append(SPACE)
            self.spaced = True
        self.pending = False

    def content(self, pieces: list[Piece]) -> None:
        self.space()
        self.started = True
        self.spaced = False
        self.pieces.extend(pieces)

    def text(self, value: str, *, code: bool = False) -> None:
        if not code:
            value = typography(value, self.quotes)
        words = _SPACES.split(value)
        for position, word in enumerate(words):
            if position:
                self.pending = True
            if word:
                self.content(escape(word, code=code, breakable=code and not self.bookmark))

    def children(self, node: Node) -> None:
        for child in node.children:
            if isinstance(child, Text):
                self.text(child.value)
            elif isinstance(child, Node):
                self.element(child)

    def group(self, command: str, node: Node, *arguments: str) -> None:
        """Un elemento con contenuto: il comando, poi il contenuto fra graffe."""
        if self.bookmark:
            self.children(node)
            return
        self.space()
        self.pieces.append(command + "".join(f"{{{a}}}" for a in arguments) + "{")
        self.children(node)
        self.pieces.append("}")

    def element(self, node: Node) -> None:
        tag = node.tag
        emitter = self.emitter
        if tag == "b":
            self.group(r"\RdB", node)
        elif tag == "i":
            self.group(r"\RdI", node)
        elif tag == "tone":
            self.group(r"\RdTone", node, node.attrs["type"])
        elif tag == "link":
            self.group(r"\RdLink", node, hex_url(node.attrs["href"]))
        elif tag == "code":
            value = _SPACES.sub(" ", "".join(c.value for c in node.children if isinstance(c, Text)))
            if self.bookmark:
                self.text(value, code=True)
                return
            inner = _Mixed(emitter, bookmark=False)
            inner.text(value, code=True)
            if value.startswith(" "):
                self.pending = True
            self.content([r"\RdCode{", *inner.pieces, "}"])
            if value.endswith(" "):
                self.pending = True
        elif tag == "address":
            value = "".join(c.value for c in node.children if isinstance(c, Text)).strip()
            shown = join(escape(value, breakable=not self.bookmark))
            if self.bookmark:
                self.content([shown])
            elif "@" in value:
                self.content([rf"\RdMail{{{hex_url('mailto:' + value)}}}{{{shown}}}"])
            else:
                self.content([rf"\RdDomain{{{shown}}}"])
        elif tag == "var":
            variable = emitter.document.variables[node.attrs["name"]]
            value = render_variable(variable, node.attrs.get("form", ""), emitter.language)
            text = escape(typography(value.text, [0]) if variable.type == "text" else value.text)
            if value.mono and not self.bookmark:
                self.content([r"\RdMono{", *text, "}"])
            else:
                self.content(text)
        elif tag == "label":
            kind = node.attrs["type"]
            words = join(plain(emitter.words.labels[kind]))
            if self.bookmark:
                self.content([words])
            else:
                self.content([rf"\RdLabel{{{LABEL_ROLES[kind]}}}{{{words}}}"])
        elif tag == "reference":
            pieces = emitter.reference(node)
            self.content(pieces if not self.bookmark else [_strip_ref(pieces[0])])
        elif tag == "cite":
            number = emitter.index.sources[node.attrs["to"]]
            if self.bookmark:
                self.content([f"[{number}]"])
            else:
                self.content([rf"\RdCite{{rd-{node.attrs['to']}}}{{{number}}}"])
        elif tag == "break":
            if not self.bookmark:
                self.pieces.append(r"\RdBreak{}")
            self.pending = False
            self.started = False
        else:  # pragma: no cover - il validatore lo esclude
            raise ValueError(tag)


def _strip_ref(piece: Piece) -> str:
    """Il testo di un rimando senza il collegamento, per i segnalibri."""
    match = re.fullmatch(r"\\RdRef\{[^}]*\}\{(.*)\}", str(piece), re.S)
    return match.group(1) if match else piece
