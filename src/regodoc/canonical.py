"""La forma canonica (specifica, §9): parti XML, TOML, manifesto, README e archivio.

Si scrive solo da un pacchetto valido. Le parti si scrivono dagli alberi già letti, i TOML
dal loro testo validato. Gli spazi del testo misto si mettono dove il generatore LaTeX li
scriverebbe (§5.1): così la forma canonica non cambia nulla nel PDF, e una prova lo verifica
confrontando il LaTeX dei due pacchetti.
"""

import datetime
import hashlib
import json
import re
import struct
import tomllib
import zlib
from collections.abc import Iterable

from regodoc import __version__
from regodoc.declaration import ENGINE_NAME, PACKAGE_MIMETYPE
from regodoc.parts import XML_DECLARATION, Comment, Node, Text
from regodoc.readme import render_readme
from regodoc.validate import Validation, canonical_files

_SPACES = re.compile(r"[ \t\n\r]+")

# Ordine degli attributi: quello delle tabelle del §4 della specifica.
ATTRIBUTE_ORDER = {
    "source": ("id", "href", "publisher", "accessed"),
    "figure": ("file", "width"),
    "table": ("columns", "orientation"),
    "reference": ("to", "through"),
    "var": ("name", "form"),
}

# Blocchi che sono sempre testo misto (§4.2); <item> e <cell> lo sono a seconda del contenuto.
_MIXED = frozenset({"p", "summary", "title", "caption"})
_GROUPS = frozenset({"b", "i", "tone", "link"})

# Chiavi di structure.toml nell'ordine della tabella del §2.
_ROOT_KEYS = ("language", "toc")
_HEADER_KEYS = ("title", "subject", "reference", "date", "version_label")
_ENTRY_KEYS = {"opening": ("id",), "part": ("id", "title", "accent")}


# --- XML -------------------------------------------------------------------------------------


def _text(value: str) -> str:
    """Un testo XML: solo «<» e «&» come riferimenti, più «>» dopo «]]» (§5.4)."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace("]]>", "]]&gt;")


def _attribute(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def _open(node: Node, *, empty: bool = False) -> str:
    order = ATTRIBUTE_ORDER.get(node.tag, ())
    names = [name for name in order if name in node.attrs]
    names += sorted(name for name in node.attrs if name not in order)
    attributes = "".join(f' {name}="{_attribute(node.attrs[name])}"' for name in names)
    return f"<{node.tag}{attributes}{'/' if empty else ''}>"


def _text_of(node: Node) -> str:
    return "".join(child.value for child in node.children if isinstance(child, Text))


class _MixedWriter:
    """Una riga di testo misto, con gli spazi dove li scriverebbe il generatore LaTeX: mai
    all'inizio o alla fine del blocco, mai accanto a un <break/>, mai due di fila."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.started = False
        self.pending = False
        self.spaced = False

    def space(self) -> None:
        if self.pending and self.started and not self.spaced:
            self.out.append(" ")
            self.spaced = True
        self.pending = False

    def content(self, text: str) -> None:
        self.space()
        self.started = True
        self.spaced = False
        self.out.append(text)

    def children(self, children: Iterable[Node | Text | Comment]) -> None:
        for child in children:
            if isinstance(child, Text):
                for position, word in enumerate(_SPACES.split(child.value)):
                    if position:
                        self.pending = True
                    if word:
                        self.content(_text(word))
            elif isinstance(child, Node):
                self.element(child)

    def element(self, node: Node) -> None:
        tag = node.tag
        if tag in _GROUPS:
            self.space()
            self.out.append(_open(node))
            self.children(node.children)
            self.out.append(f"</{tag}>")
        elif tag == "code":
            value = _SPACES.sub(" ", _text_of(node))
            if value.startswith(" "):
                self.pending = True
            self.content(f"<code>{_text(value.strip(' '))}</code>")
            if value.endswith(" "):
                self.pending = True
        elif tag == "address":
            self.content(f"<address>{_text(_text_of(node).strip())}</address>")
        elif tag == "break":
            self.out.append("<break/>")
            self.pending = False
            self.started = False
        else:  # <var/>, <label/>, <reference/>, <cite/>
            self.content(_open(node, empty=True))


def _mixed(children: Iterable[Node | Text | Comment]) -> str:
    writer = _MixedWriter()
    writer.children(children)
    return "".join(writer.out)


def _is_mixed(node: Node) -> bool:
    if node.tag in _MIXED:
        return True
    if node.tag == "cell":
        return not any(child.tag in ("p", "list") for child in node.elements())
    return False


def _write(node: Node, depth: int, lines: list[str]) -> None:
    indent = "  " * depth
    if node.tag == "listing":
        body = _text_of(node).removeprefix("\n").removesuffix("\n")
        lines.append(f"{indent}<listing>\n{_text(body)}\n</listing>")
        return
    if node.tag == "source":
        title = _SPACES.sub(" ", _text_of(node)).strip()
        lines.append(f"{indent}{_open(node)}{_text(title)}</source>")
        return
    if node.tag == "item":
        nested = [child for child in node.elements() if child.tag == "list"]
        if nested:
            position = node.children.index(nested[-1])
            lines.append(f"{indent}<item>{_mixed(node.children[:position])}")
            _write(nested[-1], depth + 1, lines)
            lines.append(f"{indent}</item>")
            return
        lines.append(f"{indent}<item>{_mixed(node.children)}</item>")
        return
    if _is_mixed(node):
        text = _mixed(node.children)
        if text:
            lines.append(f"{indent}{_open(node)}{text}</{node.tag}>")
        else:
            lines.append(f"{indent}{_open(node, empty=True)}")
        return
    children = [child for child in node.children if not isinstance(child, Text)]
    if not children:
        lines.append(f"{indent}{_open(node, empty=True)}")
        return
    lines.append(f"{indent}{_open(node)}")
    for child in children:
        if isinstance(child, Comment):
            lines.append(f"{indent}  <!--{child.value}-->")
        else:
            _write(child, depth + 1, lines)
    lines.append(f"{indent}</{node.tag}>")


def part_xml(root: Node) -> bytes:
    """Una parte in forma canonica, dall'albero letto."""
    lines = [XML_DECLARATION.decode("ascii")]
    _write(root, 0, lines)
    return ("\n".join(lines) + "\n").encode("utf-8")


# --- TOML ------------------------------------------------------------------------------------

_TOML_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f"}
_TOML_SPECIAL = re.compile(r'["\\\x00-\x1f\x7f]')


def _toml_string(value: str) -> str:
    def escape(match: re.Match[str]) -> str:
        char = match.group()
        return _TOML_ESCAPES.get(char, f"\\u{ord(char):04X}")

    return '"' + _TOML_SPECIAL.sub(escape, value) + '"'


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError(f"valore TOML non previsto: {type(value).__name__}")


def structure_toml(data: bytes) -> bytes:
    """``structure.toml`` in forma canonica, dal testo di un pacchetto valido."""
    document = tomllib.loads(data.decode("utf-8"))
    lines: list[str] = []

    def table(name: str, values: dict[str, object], keys: tuple[str, ...]) -> None:
        if lines:
            lines.append("")
        lines.append(name)
        lines.extend(f"{key} = {_toml_value(values[key])}" for key in keys if key in values)

    lines.extend(f"{key} = {_toml_value(document[key])}" for key in _ROOT_KEYS if key in document)
    table("[header]", document["header"], _HEADER_KEYS)
    for kind, keys in _ENTRY_KEYS.items():
        for entry in document.get(kind, []):
            table(f"[[{kind}]]", entry, keys)
    return ("\n".join(lines) + "\n").encode("utf-8")


def variables_toml(data: bytes) -> bytes | None:
    """``variables.toml`` in forma canonica; None se non ha variabili, perché allora il file
    si omette dall'archivio."""
    document = tomllib.loads(data.decode("utf-8"))
    if not document:
        return None
    lines = []
    for name, spec in document.items():
        keys = [key for key in spec if key != "note"] + (["note"] if "note" in spec else [])
        inner = ", ".join(f"{key} = {_toml_value(spec[key])}" for key in keys)
        lines.append(f"{name} = {{ {inner} }}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def content_files(validation: Validation) -> list[tuple[str, bytes]]:
    """I file di contenuto di un pacchetto valido in forma canonica, nell'ordine del §9:
    i TOML e le parti riscritti, le immagini così come sono."""
    if validation.package is None or validation.report.errors:
        raise ValueError("solo un pacchetto valido ha una forma canonica")
    out: list[tuple[str, bytes]] = []
    for path, data in canonical_files(validation.package, validation.structure):
        if path == "structure.toml":
            out.append((path, structure_toml(data)))
        elif path == "variables.toml":
            text = variables_toml(data)
            if text is not None:
                out.append((path, text))
        elif path.startswith("parts/"):
            out.append((path, part_xml(validation.roots[path.removeprefix("parts/")[:-4]])))
        else:
            out.append((path, data))
    return out


# --- Manifesto -------------------------------------------------------------------------------


def manifest_json(manifest: dict[str, object]) -> bytes:
    """Un manifesto in forma canonica: chiavi in ordine alfabetico, rientro di due spazi."""
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    return (text + "\n").encode("utf-8")


def package_files(
    content: list[tuple[str, bytes]],
    *,
    grammar: str,
    title: str,
    language: str,
    document: str | None,
    base_version: str | None,
) -> list[tuple[str, bytes]]:
    """Tutti i file dell'archivio canonico nel loro ordine (§9): ``mimetype``, manifesto,
    ``README.md``, poi i file di contenuto, già canonici e già in ordine."""
    readme = render_readme(title, language).encode("utf-8")
    hashed = [("README.md", readme), *content]
    manifest: dict[str, object] = {"format": "regodoc", "grammar": grammar}
    if document is not None:
        manifest["document"] = document
    if base_version is not None:
        manifest["base_version"] = base_version
    manifest["files"] = {
        path: "sha256:" + hashlib.sha256(data).hexdigest() for path, data in hashed
    }
    manifest["generator"] = {"engine": ENGINE_NAME, "version": __version__}
    return [
        ("mimetype", PACKAGE_MIMETYPE.encode("ascii")),
        ("manifest.json", manifest_json(manifest)),
        *hashed,
    ]


# --- Archivio --------------------------------------------------------------------------------

_MADE_BY = (3 << 8) | 30  # Unix, 3.0
_NEEDED = 20  # 2.0
_DOS_TIME = 0  # 00:00:00
_DOS_DATE = (0 << 9) | (1 << 5) | 1  # 1980-01-01
_EXTERNAL = 0o100644 << 16


def _deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def archive(files: list[tuple[str, bytes]]) -> bytes:
    """L'archivio ZIP canonico (§9): voci nell'ordine dato, ``mimetype`` non compressa, le
    altre con deflate al livello 9, data e attributi fissi, nessun campo extra, commento o
    descrittore di dati."""
    body = bytearray()
    central = bytearray()
    for name, data in files:
        stored = name == "mimetype"
        packed = data if stored else _deflate(data)
        method = 0 if stored else 8
        crc = zlib.crc32(data) & 0xFFFFFFFF
        encoded = name.encode("utf-8")
        offset = len(body)
        body += struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            _NEEDED,
            0,
            method,
            _DOS_TIME,
            _DOS_DATE,
            crc,
            len(packed),
            len(data),
            len(encoded),
            0,
        )
        body += encoded + packed
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            _MADE_BY,
            _NEEDED,
            0,
            method,
            _DOS_TIME,
            _DOS_DATE,
            crc,
            len(packed),
            len(data),
            len(encoded),
            0,
            0,
            0,
            0,
            _EXTERNAL,
            offset,
        )
        central += encoded
    end = struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, len(files), len(files), len(central), len(body), 0
    )
    return bytes(body + central + end)
