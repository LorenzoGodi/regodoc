"""Lettura e validazione delle parti XML (specifica §4, §5 e §6.2).

La lettura ha due tempi. Prima ``parse_part`` costruisce un albero leggero con expat,
rifiutando al primo evento DOCTYPE, entità, istruzioni di elaborazione, CDATA, spazi dei nomi
e annidamenti eccessivi. Poi ``PartChecker`` percorre l'albero e verifica vocabolario,
contenuti, attributi, testo e tipografia. I riferimenti fra file (id, rimandi, citazioni,
variabili, immagini) si raccolgono in un ``Context`` e si verificano alla fine, in
``validate``.
"""

import datetime
import re
import urllib.parse
import xml.parsers.expat
from dataclasses import dataclass, field

from regodoc.declaration import CONTENT_LIMITS
from regodoc.diagnostics import Collector
from regodoc.source import ID, IMAGE_PATH
from regodoc.text import (
    advance,
    bad_char_message,
    collapse_spaces,
    find_bad_chars,
    plain_text_problems,
    position_in,
    triple_hyphen,
)
from regodoc.tomlfiles import VARIABLE_NAME, PartEntry, Variable

XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>'

BLOCKS = frozenset({"p", "list", "box", "small", "table", "figure", "listing", "sources"})
INLINE = frozenset(
    {"b", "i", "code", "var", "label", "tone", "link", "address", "reference", "cite", "break"}
)
TITLE_INLINE = INLINE - {"link", "reference", "cite", "break"}
CAPTION_INLINE = INLINE - {"break"}
EMPTY = frozenset({"var", "label", "reference", "cite", "break", "separator"})
ELEMENTS = (
    BLOCKS
    | INLINE
    | {"part", "opening", "summary", "section", "title", "item", "head", "row", "cell"}
    | {"separator", "caption", "group", "source"}
)

LIST_TYPES = ("bullet", "numbered")
BOX_TYPES = ("status", "note", "warning", "critical")
LABEL_TYPES = ("observed", "declared", "decided", "proposed", "to-verify", "critical")
TONE_TYPES = ("critical", "warning", "ok", "muted")
VAR_FORMS = ("min", "max", "number")
ORIENTATIONS = ("portrait", "landscape")

_COLUMN = re.compile(r"\*|(?P<n>\d{1,2}(?:\.\d{1,2})?)cm")
_WIDTH = re.compile(r"(?:0(?:\.\d{1,2})?|1(?:\.0{1,2})?)")
_SPAN = re.compile(r"[1-9]\d?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_HOST_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
_EMAIL_LOCAL = re.compile(r"(?!\.)(?!.*\.\.)[A-Za-z0-9._-]{1,64}(?<!\.)")
_ADDRESS_CHARS = re.compile(r"[A-Za-z0-9.@_-]+")
_PORT = re.compile(r"\d{1,5}")

_EXPAT_MESSAGES = {
    xml.parsers.expat.errors.XML_ERROR_UNDEFINED_ENTITY: (
        "entità non definita: sono ammessi solo &lt; &gt; &amp; &quot; &apos; "
        "e i riferimenti numerici"
    ),
    xml.parsers.expat.errors.XML_ERROR_TAG_MISMATCH: "il tag di chiusura non corrisponde",
    xml.parsers.expat.errors.XML_ERROR_INVALID_TOKEN: "XML non ben formato",
    xml.parsers.expat.errors.XML_ERROR_UNCLOSED_TOKEN: "il file finisce in mezzo a un tag",
    xml.parsers.expat.errors.XML_ERROR_NO_ELEMENTS: "il file non contiene elementi",
    xml.parsers.expat.errors.XML_ERROR_JUNK_AFTER_DOC_ELEMENT: "contenuto dopo la radice",
    xml.parsers.expat.errors.XML_ERROR_DUPLICATE_ATTRIBUTE: "attributo ripetuto",
    xml.parsers.expat.errors.XML_ERROR_BAD_CHAR_REF: "riferimento a un carattere non valido",
    xml.parsers.expat.errors.XML_ERROR_SYNTAX: "errore di sintassi XML",
    xml.parsers.expat.errors.XML_ERROR_MISPLACED_XML_PI: (
        "la dichiarazione XML è ammessa solo in testa al file"
    ),
}


# --- Albero ----------------------------------------------------------------------------------


@dataclass
class Text:
    """Testo fra due eventi XML, conservato a pezzi con la posizione di ciascuno."""

    chunks: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def value(self) -> str:
        """Il testo completo."""
        return "".join(chunk for chunk, _, _ in self.chunks)

    @property
    def line(self) -> int:
        """Riga d'inizio."""
        return self.chunks[0][1]

    @property
    def column(self) -> int:
        """Colonna d'inizio."""
        return self.chunks[0][2]

    def is_blank(self) -> bool:
        """Vero se il testo è fatto solo di spazi bianchi XML."""
        return not self.value.strip(" \t\n\r")


@dataclass
class Comment:
    """Un commento XML."""

    value: str
    line: int
    column: int


@dataclass
class Node:
    """Un elemento XML con attributi, figli e posizione."""

    tag: str
    attrs: dict[str, str]
    line: int
    column: int
    children: list["Node | Text | Comment"] = field(default_factory=list)

    def elements(self) -> list["Node"]:
        """Solo i figli che sono elementi."""
        return [child for child in self.children if isinstance(child, Node)]


class _Abort(Exception):
    """Errore che ferma subito la lettura del file (§6.2: «al primo evento»)."""

    def __init__(self, code: str, message: str, line: int, column: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line
        self.column = column


def parse_part(data: bytes, file: str, report: Collector) -> Node | None:
    """Analizza un file di parte; None se il file non è utilizzabile."""
    if len(data) > CONTENT_LIMITS["part_bytes"]:
        report.error(
            "regodoc.limit.file_size",
            f"il file è di {len(data)} byte, il massimo è {CONTENT_LIMITS['part_bytes']}",
            file,
        )
        return None
    if data.startswith(b"\xef\xbb\xbf"):
        report.error("regodoc.text.bom", "il file comincia con un BOM: salvalo senza", file, 1, 1)
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        prefix = data[: error.start].decode("utf-8")
        line, column = position_in(prefix, len(prefix))
        report.error("regodoc.text.encoding", "il file non è UTF-8 valido", file, line, column)
        return None
    if re.match(rb"<\?xml[ \t\r\n]", data) and not (
        data.startswith(XML_DECLARATION)
        and (len(data) == len(XML_DECLARATION) or data[len(XML_DECLARATION)] in b" \t\r\n<")
    ):
        report.error(
            "regodoc.xml.declaration",
            'la dichiarazione XML deve essere esattamente <?xml version="1.0" encoding="UTF-8"?>',
            file,
            1,
            1,
        )
        return None
    builder = _TreeBuilder()
    try:
        builder.parse(text)
    except _Abort as abort:
        report.error(abort.code, abort.message, file, abort.line, abort.column)
        return None
    except xml.parsers.expat.ExpatError as error:
        message = _EXPAT_MESSAGES.get(error.code, "XML non ben formato")
        report.error("regodoc.xml.syntax", message, file, error.lineno, error.offset + 1)
        return None
    except RecursionError:
        report.error("regodoc.xml.depth", "annidamento eccessivo", file)
        return None
    return builder.root


class _TreeBuilder:
    """Costruisce l'albero con expat e rifiuta subito le costruzioni vietate."""

    def __init__(self) -> None:
        self.root: Node | None = None
        self.stack: list[Node] = []
        self.parser = xml.parsers.expat.ParserCreate(encoding="UTF-8")
        parser = self.parser
        parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
        parser.ordered_attributes = True
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.characters
        parser.CommentHandler = self.comment
        parser.StartDoctypeDeclHandler = self.forbid(
            "regodoc.xml.doctype", "le dichiarazioni DOCTYPE non sono ammesse"
        )
        parser.EntityDeclHandler = self.forbid(
            "regodoc.xml.entity", "le dichiarazioni di entità non sono ammesse"
        )
        parser.UnparsedEntityDeclHandler = self.forbid(
            "regodoc.xml.entity", "le dichiarazioni di entità non sono ammesse"
        )
        parser.NotationDeclHandler = self.forbid(
            "regodoc.xml.entity", "le dichiarazioni di notazione non sono ammesse"
        )
        parser.ExternalEntityRefHandler = self.forbid(
            "regodoc.xml.entity", "le entità esterne non sono ammesse"
        )
        parser.SkippedEntityHandler = self.forbid(
            "regodoc.xml.entity", "le entità non sono ammesse"
        )
        parser.ProcessingInstructionHandler = self.forbid(
            "regodoc.xml.processing_instruction", "le istruzioni di elaborazione non sono ammesse"
        )
        parser.StartCdataSectionHandler = self.forbid(
            "regodoc.xml.cdata", "le sezioni CDATA non sono ammesse: usa &lt; e &amp;"
        )

    def position(self) -> tuple[int, int]:
        return self.parser.CurrentLineNumber, self.parser.CurrentColumnNumber + 1

    def forbid(self, code: str, message: str):  # type: ignore[no-untyped-def]
        def handler(*_args: object) -> None:
            raise _Abort(code, message, *self.position())

        return handler

    def parse(self, text: str) -> None:
        self.parser.Parse(text.encode("utf-8"), True)

    def start(self, tag: str, attributes: list[str]) -> None:
        line, column = self.position()
        names = attributes[0::2]
        if ":" in tag or any(":" in name or name == "xmlns" for name in names):
            raise _Abort(
                "regodoc.xml.namespace", "gli spazi dei nomi non sono ammessi", line, column
            )
        if len(self.stack) >= CONTENT_LIMITS["element_depth"]:
            raise _Abort(
                "regodoc.limit.depth",
                f"più di {CONTENT_LIMITS['element_depth']} elementi annidati",
                line,
                column,
            )
        node = Node(tag, dict(zip(names, attributes[1::2], strict=True)), line, column)
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.root = node
        self.stack.append(node)

    def end(self, _tag: str) -> None:
        self.stack.pop()

    def characters(self, data: str) -> None:
        line, column = self.position()
        if not self.stack:
            return  # solo spazi bianchi fuori dalla radice: expat rifiuta il resto
        children = self.stack[-1].children
        if children and isinstance(children[-1], Text):
            children[-1].chunks.append((data, line, column))
        else:
            children.append(Text([(data, line, column)]))

    def comment(self, data: str) -> None:
        line, column = self.position()
        if not self.stack:
            raise _Abort(
                "regodoc.xml.comment_position",
                "i commenti sono ammessi solo dentro la radice, fra i blocchi",
                line,
                column,
            )
        self.stack[-1].children.append(Comment(data, line, column))


# --- Contesto del documento ------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """Un id del documento: di che tipo è e dove è definito."""

    kind: str  # "opening", "part", "section", "source"
    file: str
    line: int
    column: int
    part: str  # id della parte o apertura che lo contiene


@dataclass(frozen=True)
class Use:
    """Un uso da verificare alla fine: rimando, citazione, variabile o figura."""

    kind: str
    name: str
    extra: str
    file: str
    line: int
    column: int


@dataclass
class Context:
    """Ciò che serve per i controlli fra file, raccolto durante la lettura delle parti."""

    report: Collector
    variables: dict[str, Variable]
    entries: dict[str, PartEntry]
    targets: dict[str, Target] = field(default_factory=dict)
    uses: list[Use] = field(default_factory=list)
    declared_variables: set[str] | None = field(default_factory=set)
    # Falso se qualche parte non è stata letta: gli id raccolti sono incompleti.
    complete: bool = True
    sources_blocks: int = 0
    sources: int = 0
    characters: int = 0
    references: int = 0

    def define(self, identifier: str, target: Target) -> None:
        """Registra un id, segnalando i doppioni."""
        previous = self.targets.get(identifier)
        if previous is not None:
            where = f"{previous.file}:{previous.line}" if previous.line else previous.file
            self.report.error(
                "regodoc.xml.duplicate_id",
                f"l'id «{identifier}» è già usato ({where})",
                target.file,
                target.line,
                target.column,
            )
            return
        self.targets[identifier] = target


# --- Validatori di attributi -----------------------------------------------------------------


def check_href(value: str) -> str | None:
    """Spiega perché un ``href`` non è ammesso (§4.3), o None se lo è."""
    if len(value) > CONTENT_LIMITS["href_characters"]:
        return f"l'indirizzo supera {CONTENT_LIMITS['href_characters']} caratteri"
    if any(not 0x21 <= ord(char) <= 0x7E for char in value):
        return "l'indirizzo contiene spazi o caratteri fuori dall'ASCII stampabile"
    if not value.startswith("https://"):
        return "sono ammessi solo indirizzi https://"
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        return "indirizzo non valido"
    if "@" in parts.netloc:
        return "l'indirizzo non può contenere credenziali («@» prima dell'host)"
    host = parts.hostname or ""
    if not _is_domain(host, require_dot=False):
        return "nome di host non valido"
    if port is not None and not _PORT.fullmatch(str(port)):
        return "porta non valida"
    return None


def _is_domain(value: str, *, require_dot: bool) -> bool:
    if not value or len(value) > 253:
        return False
    labels = value.split(".")
    if require_dot and len(labels) < 2:
        return False
    return all(_HOST_LABEL.fullmatch(label) for label in labels)


def check_address(value: str) -> str | None:
    """Spiega perché il contenuto di ``<address>`` non è ammesso (§4.3), o None."""
    if not _ADDRESS_CHARS.fullmatch(value):
        return "sono ammessi solo lettere ASCII, cifre e . @ _ -"
    if "@" in value:
        local, _, domain = value.partition("@")
        if (
            "@" in domain
            or not _EMAIL_LOCAL.fullmatch(local)
            or not _is_domain(domain, require_dot=True)
        ):
            return "indirizzo email non valido"
        return None
    if not _is_domain(value, require_dot=True):
        return "nome di dominio non valido"
    return None


def _check_date(value: str) -> str | None:
    if not _DATE.fullmatch(value):
        return "serve una data AAAA-MM-GG"
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return "data inesistente"
    return None


# --- Verifica dell'albero --------------------------------------------------------------------


class PartChecker:
    """Verifica l'albero di una parte o apertura e raccoglie i dati per i controlli finali."""

    def __init__(self, context: Context, file: str, entry: PartEntry) -> None:
        self.context = context
        self.report = context.report
        self.file = file
        self.entry = entry

    # Strumenti

    def error(self, code: str, message: str, line: int = 0, column: int = 0) -> None:
        self.report.error(code, message, self.file, line, column)

    def at(self, node: Node | Text | Comment, code: str, message: str) -> None:
        self.error(code, message, node.line, node.column)

    def check_attributes(
        self, node: Node, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()
    ) -> bool:
        ok = True
        for name, value in node.attrs.items():
            if name not in required and name not in optional:
                self.at(
                    node,
                    "regodoc.xml.unknown_attribute",
                    f"l'attributo «{name}» non è ammesso in <{node.tag}>",
                )
                ok = False
                continue
            for index in find_bad_chars(value):
                self.at(
                    node,
                    "regodoc.text.char",
                    f"attributo «{name}»: {bad_char_message(value[index])}",
                )
                ok = False
                break
        for name in required:
            if name not in node.attrs:
                self.at(
                    node,
                    "regodoc.xml.missing_attribute",
                    f"<{node.tag}> richiede l'attributo «{name}»",
                )
                ok = False
        return ok

    def check_choice(self, node: Node, name: str, choices: tuple[str, ...]) -> None:
        value = node.attrs.get(name)
        if value is not None and value not in choices:
            self.at(
                node,
                "regodoc.xml.attribute_value",
                f"«{name}» di <{node.tag}> deve essere uno fra {', '.join(choices)}, non «{value}»",
            )

    def check_id_attribute(self, node: Node, name: str = "id") -> str | None:
        value = node.attrs.get(name)
        if value is None:
            return None
        if not ID.fullmatch(value):
            self.at(
                node,
                "regodoc.xml.id",
                f"«{value}» non è un id valido: [a-z][a-z0-9-]{{0,47}}, senza «--», "
                "senza «-» finale, non un nome riservato (§1.5)",
            )
            return None
        return value

    def check_plain_attribute(self, node: Node, name: str, max_length: int) -> None:
        value = node.attrs.get(name)
        if value is None:
            return
        for problem in plain_text_problems(value, max_length=max_length):
            self.at(node, "regodoc.text.plain", f"attributo «{name}»: {problem}")

    def unexpected(self, node: Node, parent: Node) -> None:
        if node.tag not in ELEMENTS:
            self.at(node, "regodoc.xml.unknown_element", f"<{node.tag}> non è nel vocabolario")
        else:
            self.at(
                node,
                "regodoc.xml.misplaced_element",
                f"<{node.tag}> non è ammesso dentro <{parent.tag}>",
            )

    def stray_text(self, text: Text, parent: Node) -> None:
        self.at(
            text,
            "regodoc.xml.stray_text",
            f"testo fuori posto dentro <{parent.tag}>: va in un <p> o in un altro blocco",
        )

    def check_comment(self, comment: Comment) -> None:
        for index in find_bad_chars(comment.value, newline=True):
            line, column = advance(comment.line, comment.column + 4, comment.value, index)
            self.error(
                "regodoc.text.char",
                f"nel commento: {bad_char_message(comment.value[index])}",
                line,
                column,
            )
            break

    # Radice e contenitori

    def check_root(self, root: Node) -> None:
        expected = self.entry.kind
        if root.tag != expected:
            self.at(
                root,
                "regodoc.xml.root",
                f"la radice deve essere <{expected}>, come dichiarato in structure.toml, "
                f"non <{root.tag}>",
            )
            return
        self.check_attributes(root)
        self.check_container(root, depth=0)

    def check_container(self, node: Node, depth: int) -> None:
        """Contenuto di <part>, <opening> e <section> (§4.2)."""
        index = 0
        children = [c for c in node.children if not (isinstance(c, Text) and c.is_blank())]
        for child in children:
            if isinstance(child, Comment):
                self.check_comment(child)
            elif isinstance(child, Text):
                self.stray_text(child, node)
        elements = node.elements()
        if node.tag == "section":
            if not elements or elements[0].tag != "title":
                self.at(node, "regodoc.xml.missing_title", "<section> deve cominciare con <title>")
            else:
                self.check_mixed_block(elements[0], TITLE_INLINE)
                index = 1
        elif node.tag == "part" and elements and elements[0].tag == "summary":
            self.check_mixed_block(elements[0], INLINE)
            index = 1
        seen_section = False
        for child in elements[index:]:
            if child.tag == "section":
                seen_section = True
                self.check_section(child, depth + 1)
            elif child.tag in BLOCKS:
                if seen_section:
                    self.at(
                        child,
                        "regodoc.xml.block_after_section",
                        f"<{child.tag}> viene dopo una sezione: dopo la prima sezione figlia "
                        "vengono solo altre sezioni",
                    )
                self.check_block(child, list_depth=0)
            else:
                self.unexpected(child, node)

    def check_section(self, node: Node, depth: int) -> None:
        if depth > CONTENT_LIMITS["section_depth"]:
            self.at(
                node,
                "regodoc.xml.section_depth",
                f"più di {CONTENT_LIMITS['section_depth']} livelli di sezione",
            )
            return
        self.check_attributes(node, optional=("id",))
        identifier = self.check_id_attribute(node)
        if identifier:
            self.context.define(
                identifier, Target("section", self.file, node.line, node.column, self.entry.id)
            )
        self.check_container(node, depth)

    # Blocchi

    def check_block(self, node: Node, list_depth: int) -> None:
        handler = {
            "p": lambda: self.check_paragraph(node),
            "list": lambda: self.check_list(node, list_depth + 1),
            "box": lambda: self.check_box(node),
            "small": lambda: self.check_box(node),
            "table": lambda: self.check_table(node),
            "figure": lambda: self.check_figure(node),
            "listing": lambda: self.check_listing(node),
            "sources": lambda: self.check_sources(node),
        }[node.tag]
        handler()

    def check_paragraph(self, node: Node) -> None:
        self.check_attributes(node)
        self.check_mixed_block(node, INLINE)

    def check_list(self, node: Node, depth: int) -> None:
        self.check_attributes(node, optional=("type",))
        self.check_choice(node, "type", LIST_TYPES)
        if depth > CONTENT_LIMITS["list_depth"]:
            self.at(
                node,
                "regodoc.xml.list_depth",
                f"più di {CONTENT_LIMITS['list_depth']} livelli di elenco",
            )
            return
        self.check_element_only(node, ("item",))
        items = node.elements()
        if not items:
            self.at(node, "regodoc.xml.empty", "<list> deve contenere almeno un <item>")
        for item in items:
            if item.tag == "item":
                self.check_item(item, depth)

    def check_item(self, node: Node, depth: int) -> None:
        self.check_attributes(node)
        nested = [child for child in node.elements() if child.tag == "list"]
        if nested:
            last = nested[-1]
            position = node.children.index(last)
            after = node.children[position + 1 :]
            if len(nested) > 1 or any(not (isinstance(c, Text) and c.is_blank()) for c in after):
                self.at(
                    node,
                    "regodoc.xml.item_list",
                    "<item> ammette al massimo un <list>, e solo alla fine",
                )
            mixed = Node(node.tag, {}, node.line, node.column, node.children[:position])
            self.check_mixed_block(mixed, INLINE, allow_empty=False)
            self.check_list(last, depth + 1)
        else:
            self.check_mixed_block(node, INLINE)

    def check_box(self, node: Node) -> None:
        if node.tag == "box":
            self.check_attributes(node, required=("type",))
            self.check_choice(node, "type", BOX_TYPES)
        else:
            self.check_attributes(node)
        self.check_element_only(node, ("p", "list"))
        children = node.elements()
        if not children:
            self.at(node, "regodoc.xml.empty", f"<{node.tag}> deve contenere un <p> o un <list>")
        for child in children:
            if child.tag == "p":
                self.check_paragraph(child)
            elif child.tag == "list":
                self.check_list(child, 1)

    def check_element_only(self, node: Node, allowed: tuple[str, ...]) -> None:
        """Contenuto fatto solo di elementi ammessi, commenti e spazi bianchi."""
        for child in node.children:
            if isinstance(child, Comment):
                self.check_comment(child)
            elif isinstance(child, Text):
                if not child.is_blank():
                    self.stray_text(child, node)
            elif child.tag not in allowed:
                self.unexpected(child, node)

    def check_listing(self, node: Node) -> None:
        self.check_attributes(node)
        for child in node.children:
            if isinstance(child, Comment):
                self.at(child, "regodoc.xml.comment_position", "commento dentro <listing>")
            elif isinstance(child, Node):
                self.unexpected(child, node)
        text = Text([c for t in node.children if isinstance(t, Text) for c in t.chunks])
        if not text.chunks:
            self.at(node, "regodoc.xml.empty", "<listing> è vuoto")
            return
        self.check_chars(text, newline=True, tab=False)
        body = text.value
        body = body.removeprefix("\n")
        body = body.removesuffix("\n")
        self.context.characters += len(body)
        limit = CONTENT_LIMITS["listing_line_characters"]
        for offset, line_text in enumerate(body.split("\n")):
            if len(line_text) > limit:
                self.error(
                    "regodoc.limit.listing_line",
                    f"riga del listato lunga {len(line_text)} caratteri, il massimo è {limit}",
                    text.line + offset + (1 if text.value.startswith("\n") else 0),
                )

    def check_figure(self, node: Node) -> None:
        self.check_attributes(node, required=("file",), optional=("width",))
        path = node.attrs.get("file")
        if path is not None:
            if not IMAGE_PATH.fullmatch(path):
                self.at(
                    node,
                    "regodoc.xml.figure_file",
                    f"«{path}» non è un percorso d'immagine valido: images/<nome>.png o .jpg",
                )
            else:
                self.context.uses.append(Use("figure", path, "", self.file, node.line, node.column))
        width = node.attrs.get("width")
        if width is not None and not (_WIDTH.fullmatch(width) and 0.1 <= float(width) <= 1):
            self.at(
                node,
                "regodoc.xml.attribute_value",
                f"«width» deve essere un numero da 0.1 a 1 con il punto, non «{width}»",
            )
        self.check_element_only(node, ("caption",))
        captions = node.elements()
        if len(captions) > 1:
            self.at(node, "regodoc.xml.caption", "<figure> ammette una sola <caption>")
        for caption in captions:
            if caption.tag == "caption":
                self.check_attributes(caption)
                self.check_mixed_block(caption, CAPTION_INLINE)

    # Tabelle

    def check_table(self, node: Node) -> None:
        self.check_attributes(node, required=("columns",), optional=("orientation",))
        self.check_choice(node, "orientation", ORIENTATIONS)
        columns = self.parse_columns(node)
        self.check_element_only(node, ("head", "row", "separator"))
        children = node.elements()
        rows = 0
        previous = ""
        for position, child in enumerate(children):
            if child.tag == "head":
                if position != 0:
                    self.at(
                        child,
                        "regodoc.xml.table_head",
                        "<head> deve essere la prima e unica intestazione della tabella",
                    )
                self.check_attributes(child)
                self.check_row_cells(child, columns)
            elif child.tag == "row":
                rows += 1
                self.check_attributes(child, optional=("type",))
                self.check_choice(child, "type", ("total",))
                self.check_row_cells(child, columns)
            elif child.tag == "separator":
                self.check_empty(child)
                if previous != "row" or position == len(children) - 1:
                    self.at(
                        child,
                        "regodoc.xml.separator",
                        "<separator/> va fra due righe, non in testa, in coda o ripetuto",
                    )
            previous = child.tag
        if rows == 0:
            self.at(node, "regodoc.xml.empty", "<table> deve avere almeno un <row>")
        if rows > CONTENT_LIMITS["table_rows"]:
            self.at(
                node,
                "regodoc.limit.table_rows",
                f"{rows} righe, il massimo è {CONTENT_LIMITS['table_rows']}",
            )

    def parse_columns(self, node: Node) -> int:
        value = node.attrs.get("columns")
        if value is None:
            return 0
        items = value.split(" ")
        problem = ""
        for item in items:
            match = _COLUMN.fullmatch(item)
            if not match:
                problem = f"«{item}» non è «*» né una misura come 1.8cm"
                break
            if match.group("n") is not None and not 0.5 <= float(match.group("n")) <= 12:
                problem = f"«{item}» è fuori dall'intervallo da 0.5cm a 12cm"
                break
        else:
            if "*" not in items:
                problem = "serve almeno una colonna «*»"
            elif len(items) > CONTENT_LIMITS["table_columns"]:
                problem = f"{len(items)} colonne, il massimo è {CONTENT_LIMITS['table_columns']}"
        if problem:
            self.at(node, "regodoc.xml.columns", f"«columns»: {problem}")
            return 0
        return len(items)

    def check_row_cells(self, row: Node, columns: int) -> None:
        self.check_element_only(row, ("cell",))
        covered = 0
        cells = [c for c in row.elements() if c.tag == "cell"]
        if not cells:
            self.at(row, "regodoc.xml.empty", f"<{row.tag}> deve contenere almeno una <cell>")
            return
        for cell in cells:
            self.check_attributes(cell, optional=("span",))
            span = cell.attrs.get("span")
            width = 1
            if span is not None:
                if not _SPAN.fullmatch(span) or not 2 <= int(span) <= max(columns, 2):
                    self.at(
                        cell,
                        "regodoc.xml.attribute_value",
                        f"«span» deve essere un intero da 2 al numero di colonne, non «{span}»",
                    )
                else:
                    width = int(span)
            covered += width
            self.check_cell(cell)
        if columns and covered != columns:
            self.at(
                row,
                "regodoc.xml.row_width",
                f"la riga copre {covered} colonne, la tabella ne dichiara {columns}",
            )

    def check_cell(self, cell: Node) -> None:
        elements = cell.elements()
        before = self.context.characters
        if any(child.tag in ("p", "list") for child in elements):
            for child in cell.children:
                if isinstance(child, Text) and not child.is_blank():
                    self.at(
                        child,
                        "regodoc.xml.cell_mixed",
                        "una cella contiene testo oppure blocchi, mai entrambi",
                    )
                elif isinstance(child, Comment):
                    self.check_comment(child)
            for child in elements:
                if child.tag == "p":
                    self.check_paragraph(child)
                elif child.tag == "list":
                    self.check_list(child, 1)
                else:
                    self.at(
                        child,
                        "regodoc.xml.cell_mixed",
                        f"<{child.tag}> accanto a un blocco: una cella contiene testo "
                        "oppure blocchi, mai entrambi",
                    )
        else:
            self.check_mixed_block(cell, INLINE, allow_empty=True)
        used = self.context.characters - before
        if used > CONTENT_LIMITS["cell_characters"]:
            self.at(
                cell,
                "regodoc.limit.cell",
                f"cella di {used} caratteri, il massimo è {CONTENT_LIMITS['cell_characters']}",
            )

    # Fonti

    def check_sources(self, node: Node) -> None:
        self.check_attributes(node, optional=("id",))
        identifier = self.check_id_attribute(node)
        if identifier:
            self.context.define(
                identifier, Target("sources", self.file, node.line, node.column, self.entry.id)
            )
        self.context.sources_blocks += 1
        if self.context.sources_blocks > 1:
            self.at(node, "regodoc.xml.sources_twice", "<sources> compare più di una volta")
        self.check_element_only(node, ("group", "source"))
        children = node.elements()
        kinds = {child.tag for child in children if child.tag in ("group", "source")}
        if not children:
            self.at(node, "regodoc.xml.empty", "<sources> deve contenere fonti")
        if len(kinds) > 1:
            self.at(
                node,
                "regodoc.xml.sources_mixed",
                "<sources> contiene solo <group> oppure solo <source>, non mescolati",
            )
        for child in children:
            if child.tag == "group":
                self.check_attributes(child, required=("title",))
                self.check_plain_attribute(child, "title", 200)
                self.check_element_only(child, ("source",))
                sources = [s for s in child.elements() if s.tag == "source"]
                if not sources:
                    self.at(child, "regodoc.xml.empty", "<group> deve contenere fonti")
                for source in sources:
                    self.check_source(source)
            elif child.tag == "source":
                self.check_source(child)

    def check_source(self, node: Node) -> None:
        self.context.sources += 1
        self.check_attributes(node, required=("href", "publisher"), optional=("id", "accessed"))
        href = node.attrs.get("href")
        if href is not None and (problem := check_href(href)):
            self.at(node, "regodoc.xml.href", problem)
        self.check_plain_attribute(node, "publisher", 200)
        accessed = node.attrs.get("accessed")
        if accessed is not None and (problem := _check_date(accessed)):
            self.at(node, "regodoc.xml.attribute_value", f"«accessed»: {problem}")
        identifier = self.check_id_attribute(node)
        if identifier:
            self.context.define(
                identifier, Target("source", self.file, node.line, node.column, self.entry.id)
            )
        self.check_text_only(node)
        title = collapse_spaces(self.text_of(node)).strip()
        for problem in plain_text_problems(title, max_length=500):
            self.at(node, "regodoc.text.plain", f"titolo della fonte: {problem}")

    # Testo misto

    def check_mixed_block(
        self, node: Node, allowed: frozenset[str], *, allow_empty: bool = False
    ) -> None:
        """Verifica un blocco di testo misto: elementi, caratteri, virgolette, vuoto."""
        if node.tag in ("summary", "title", "caption") and node.attrs:
            self.check_attributes(node)
        state = _BlockState()
        self.check_mixed(node, allowed, state, ancestors=frozenset())
        if state.quotes % 2:
            self.at(
                node,
                "regodoc.text.quotes",
                f"virgolette dritte in numero dispari dentro <{node.tag}>",
            )
        if not allow_empty and not state.has_content:
            self.at(node, "regodoc.xml.empty", f"<{node.tag}> è vuoto")

    def check_mixed(
        self, node: Node, allowed: frozenset[str], state: "_BlockState", ancestors: frozenset[str]
    ) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                self.at(
                    child,
                    "regodoc.xml.comment_position",
                    "i commenti non sono ammessi dentro il testo",
                )
            elif isinstance(child, Text):
                self.check_chars(child, newline=True, tab=True)
                value = child.value
                self.context.characters += len(collapse_spaces(value))
                if value.strip(" \t\n\r"):
                    state.has_content = True
                state.quotes += value.count('"')
                if (index := triple_hyphen(value)) is not None:
                    line, column = advance(child.line, child.column, value, index)
                    self.error(
                        "regodoc.text.dashes",
                        "tre o più trattini di fila: scrivi la lineetta — direttamente",
                        line,
                        column,
                    )
            elif child.tag not in allowed:
                self.unexpected(child, node)
            elif child.tag in ancestors and child.tag in ("b", "i", "tone", "link"):
                self.at(
                    child,
                    "regodoc.xml.nested_inline",
                    f"<{child.tag}> dentro un altro <{child.tag}>",
                )
            else:
                state.has_content = True
                self.check_inline(child, allowed, state, ancestors | {child.tag})

    def check_inline(
        self, node: Node, allowed: frozenset[str], state: "_BlockState", ancestors: frozenset[str]
    ) -> None:
        tag = node.tag
        if tag in ("b", "i"):
            self.check_attributes(node)
            self.check_inline_mixed(node, allowed, state, ancestors)
        elif tag == "tone":
            self.check_attributes(node, required=("type",))
            self.check_choice(node, "type", TONE_TYPES)
            self.check_inline_mixed(node, allowed, state, ancestors)
        elif tag == "link":
            self.check_attributes(node, required=("href",))
            href = node.attrs.get("href")
            if href is not None and (problem := check_href(href)):
                self.at(node, "regodoc.xml.href", problem)
            self.check_inline_mixed(node, allowed - {"link"}, state, ancestors)
        elif tag == "code":
            self.check_attributes(node)
            self.check_text_only(node)
            if not self.text_of(node):
                self.at(node, "regodoc.xml.empty", "<code> è vuoto")
        elif tag == "address":
            self.check_attributes(node)
            self.check_text_only(node)
            value = self.text_of(node)
            # Un carattere vietato, tabulazione compresa, l'ha già segnalato check_text_only;
            # l'a capo, ammesso negli altri testi senza elementi, qui è un errore (§5.1). Con
            # uno dei due l'indirizzo non si controlla: sarebbe un secondo errore per lo
            # stesso carattere.
            if "\n" in value:
                self.at(node, "regodoc.text.char", "a capo dentro <address>")
            elif next(find_bad_chars(value), None) is None and (problem := check_address(value)):
                self.at(node, "regodoc.xml.address", f"<address>: {problem}")
        elif tag == "var":
            self.check_empty(node)
            if self.check_attributes(node, required=("name",), optional=("form",)):
                name = node.attrs["name"]
                self.check_choice(node, "form", VAR_FORMS)
                if not VARIABLE_NAME.fullmatch(name):
                    self.at(node, "regodoc.xml.var_name", f"«{name}» non è un nome di variabile")
                else:
                    self.context.uses.append(
                        Use(
                            "var",
                            name,
                            node.attrs.get("form", ""),
                            self.file,
                            node.line,
                            node.column,
                        )
                    )
        elif tag == "label":
            self.check_empty(node)
            self.check_attributes(node, required=("type",))
            self.check_choice(node, "type", LABEL_TYPES)
        elif tag in ("reference", "cite"):
            self.check_empty(node)
            optional = ("through",) if tag == "reference" else ()
            if self.check_attributes(node, required=("to",), optional=optional):
                self.context.references += 1
                self.context.uses.append(
                    Use(
                        tag,
                        node.attrs["to"],
                        node.attrs.get("through", ""),
                        self.file,
                        node.line,
                        node.column,
                    )
                )
        elif tag == "break":
            self.check_empty(node)
            self.check_attributes(node)

    def check_inline_mixed(
        self, node: Node, allowed: frozenset[str], state: "_BlockState", ancestors: frozenset[str]
    ) -> None:
        inner = _BlockState()
        self.check_mixed(node, allowed, inner, ancestors)
        state.quotes += inner.quotes
        if not inner.has_content:
            self.at(node, "regodoc.xml.empty", f"<{node.tag}> è vuoto")

    def check_empty(self, node: Node) -> None:
        if node.children:
            self.at(node, "regodoc.xml.not_empty", f"<{node.tag}/> deve essere vuoto")

    def check_text_only(self, node: Node) -> None:
        for child in node.children:
            if isinstance(child, Node):
                self.at(
                    child,
                    "regodoc.xml.misplaced_element",
                    f"<{node.tag}> contiene solo testo, non <{child.tag}>",
                )
            elif isinstance(child, Comment):
                self.at(child, "regodoc.xml.comment_position", f"commento dentro <{node.tag}>")
            else:
                self.check_chars(child, newline=True, tab=False)
                self.context.characters += len(child.value)

    def text_of(self, node: Node) -> str:
        return "".join(child.value for child in node.children if isinstance(child, Text))

    def check_chars(self, text: Text, *, newline: bool, tab: bool) -> None:
        for chunk, line, column in text.chunks:
            for index in find_bad_chars(chunk, newline=newline, tab=tab):
                at_line, at_column = advance(line, column, chunk, index)
                self.error("regodoc.text.char", bad_char_message(chunk[index]), at_line, at_column)
                return


@dataclass
class _BlockState:
    quotes: int = 0
    has_content: bool = False
