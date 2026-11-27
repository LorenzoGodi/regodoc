"""L'ingresso Markdown md/1 (docs/spec/md-1.md): da document.md a un pacchetto canonico.

Il lettore di ``markdown.py`` dà l'albero dei blocchi. Qui l'albero diventa i file di un
pacchetto nella grammatica corrente: ``structure.toml``, una parte XML per l'apertura e per
ogni parte, e le immagini dell'ingresso. Il pacchetto si valida e si scrive in forma canonica
come fa ``canon``. Ogni riga dei file generati ricorda la riga del Markdown da cui viene:
così un problema che la validazione trova nel pacchetto torna a ``document.md``.
"""

import dataclasses
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from regodoc import canon, canonical, markdown
from regodoc.declaration import GRAMMAR_CURRENT, PACKAGE_MIMETYPE
from regodoc.diagnostics import Collector
from regodoc.parts import XML_DECLARATION
from regodoc.source import ID, MARKDOWN, read_package
from regodoc.tomlfiles import ACCENTS
from regodoc.validate import Validation

SOURCE = "document.md"
_KEY = re.compile(r"«(header|part\[[0-9]+\])[.»]")
OPENING_ID = "opening"


@dataclass
class Generated:
    """I file del pacchetto generato e, per ognuno, la riga del Markdown di ogni sua riga."""

    files: dict[str, bytes] = field(default_factory=dict)
    origins: dict[str, list[int]] = field(default_factory=dict)
    # Le voci di structure.toml che i messaggi nominano («part[2].title»), con la riga del
    # Markdown: i problemi di structure.toml non hanno sempre una riga.
    keys: dict[str, int] = field(default_factory=dict)


class _Writer:
    """Righe di un file, ognuna con la riga del Markdown da cui viene."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.origins: list[int] = []

    def add(self, text: str, origin: int) -> None:
        self.lines.append(text)
        self.origins.append(origin)

    def data(self) -> bytes:
        return ("\n".join(self.lines) + "\n").encode("utf-8")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inlines(nodes: list[markdown.Inline]) -> str:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, markdown.Text):
            out.append(_escape(node.text))
        elif isinstance(node, markdown.Code):
            out.append(f"<code>{_escape(node.text)}</code>")
        elif isinstance(node, markdown.Strong):
            out.append(f"<b>{_inlines(node.children)}</b>")
        else:
            out.append(f"<i>{_inlines(node.children)}</i>")
    return "".join(out)


def _toml_string(text: str) -> str:
    # json.dumps scrive \" e \\ e i caratteri di controllo come \uXXXX, che il TOML legge.
    return json.dumps(text, ensure_ascii=False)


def part_id(title: str, used: set[str]) -> str:
    """L'id di una parte dal suo titolo: ASCII minuscolo con i trattini (md-1.md, §3)."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    pieces: list[str] = []
    word: list[str] = []
    for char in folded.lower():
        if "a" <= char <= "z" or "0" <= char <= "9":
            word.append(char)
        elif word:
            pieces.append("".join(word))
            word = []
    if word:
        pieces.append("".join(word))
    base = "-".join(pieces)
    if not base or not base[0].isalpha():
        base = f"parte-{base}" if base else "parte"
    base = base[:48].rstrip("-")
    candidate = base
    counter = 2
    while candidate in used or not ID.fullmatch(candidate):
        suffix = f"-{counter}"
        candidate = base[: 48 - len(suffix)].rstrip("-") + suffix
        counter += 1
    used.add(candidate)
    return candidate


def _blocks(writer: _Writer, blocks: list[markdown.Block], indent: str) -> None:
    for block in blocks:
        if isinstance(block, markdown.Paragraph):
            writer.add(f"{indent}<p>{_inlines(block.inlines)}</p>", block.line)
        elif isinstance(block, markdown.ListBlock):
            _list(writer, block, indent)
        elif isinstance(block, markdown.Table):
            _table(writer, block, indent)
        elif isinstance(block, markdown.Listing):
            writer.add(f"{indent}<listing>", block.line)
            for offset, line in enumerate(block.text.split("\n"), 1):
                writer.add(_escape(line), block.line + offset)
            writer.add("</listing>", block.line)
        elif block.caption:
            writer.add(f'{indent}<figure file="{block.path}">', block.line)
            writer.add(f"{indent}  <caption>{_inlines(block.caption)}</caption>", block.line)
            writer.add(f"{indent}</figure>", block.line)
        else:
            writer.add(f'{indent}<figure file="{block.path}"/>', block.line)


def _list(writer: _Writer, block: markdown.ListBlock, indent: str) -> None:
    kind = ' type="numbered"' if block.numbered else ""
    writer.add(f"{indent}<list{kind}>", block.line)
    for item in block.items:
        text = _inlines(item.inlines)
        if item.sublist is None:
            writer.add(f"{indent}  <item>{text}</item>", item.line)
        else:
            writer.add(f"{indent}  <item>{text}", item.line)
            _list(writer, item.sublist, indent + "    ")
            writer.add(f"{indent}  </item>", item.line)
    writer.add(f"{indent}</list>", block.line)


def _table(writer: _Writer, table: markdown.Table, indent: str) -> None:
    columns = " ".join("*" for _ in table.align)
    align = f' align="{" ".join(table.align)}"' if "right" in table.align else ""
    writer.add(f'{indent}<table columns="{columns}"{align}>', table.line)

    def cells(row: list[list[markdown.Inline]], line: int) -> None:
        for cell in row:
            text = _inlines(cell)
            writer.add(f"{indent}    <cell>{text}</cell>" if text else f"{indent}    <cell/>", line)

    writer.add(f"{indent}  <head>", table.line)
    cells(table.head, table.line)
    writer.add(f"{indent}  </head>", table.line)
    for row, line in zip(table.rows, table.row_lines, strict=True):
        writer.add(f"{indent}  <row>", line)
        cells(row, line)
        writer.add(f"{indent}  </row>", line)
    writer.add(f"{indent}</table>", table.line)


def _sections(writer: _Writer, sections: list[markdown.Section], indent: str) -> None:
    for section in sections:
        writer.add(f"{indent}<section>", section.line)
        writer.add(f"{indent}  <title>{_inlines(section.title)}</title>", section.line)
        _blocks(writer, section.blocks, indent + "  ")
        _sections(writer, section.sections, indent + "  ")
        writer.add(f"{indent}</section>", section.line)


def _chapter(chapter: markdown.Chapter, root: str) -> _Writer:
    writer = _Writer()
    writer.add(XML_DECLARATION.decode("ascii").rstrip("\n"), chapter.line)
    writer.add(f"<{root}>", chapter.line)
    _blocks(writer, chapter.blocks, "  ")
    _sections(writer, chapter.sections, "  ")
    writer.add(f"</{root}>", chapter.line)
    return writer


def generate(document: markdown.Document, images: dict[str, bytes], language: str) -> Generated:
    """I file del pacchetto da un documento letto senza problemi."""
    generated = Generated()
    structure = _Writer()
    structure.add(f"language = {_toml_string(language)}", document.title_line)
    structure.add("", document.title_line)
    structure.add("[header]", document.title_line)
    structure.add(f"title = {_toml_string(document.title)}", document.title_line)
    generated.keys["header"] = document.title_line
    used = {OPENING_ID}
    chapters: list[tuple[str, markdown.Chapter, str]] = []
    if document.opening is not None:
        structure.add("", document.opening.line)
        structure.add("[[opening]]", document.opening.line)
        structure.add(f'id = "{OPENING_ID}"', document.opening.line)
        chapters.append((OPENING_ID, document.opening, "opening"))
    for index, chapter in enumerate(document.parts):
        generated.keys[f"part[{index + 1}]"] = chapter.line
        identifier = part_id(chapter.title, used)
        structure.add("", chapter.line)
        structure.add("[[part]]", chapter.line)
        structure.add(f'id = "{identifier}"', chapter.line)
        structure.add(f"title = {_toml_string(chapter.title)}", chapter.line)
        structure.add(f'accent = "{ACCENTS[index % len(ACCENTS)]}"', chapter.line)
        chapters.append((identifier, chapter, "part"))
    generated.files["mimetype"] = PACKAGE_MIMETYPE.encode("ascii")
    generated.files["manifest.json"] = canonical.manifest_json(
        {"format": "regodoc", "grammar": GRAMMAR_CURRENT}
    )
    generated.files["structure.toml"] = structure.data()
    generated.origins["structure.toml"] = structure.origins
    for identifier, chapter, root in chapters:
        writer = _chapter(chapter, root)
        path = f"parts/{identifier}.xml"
        generated.files[path] = writer.data()
        generated.origins[path] = writer.origins
    generated.files.update(sorted(images.items()))
    return generated


def _figures(document: markdown.Document) -> list[markdown.Figure]:
    found: list[markdown.Figure] = []
    pending: list[list[markdown.Block]] = []
    chapters = ([document.opening] if document.opening else []) + document.parts
    for chapter in chapters:
        pending.append(chapter.blocks)
        stack = list(chapter.sections)
        while stack:
            section = stack.pop()
            pending.append(section.blocks)
            stack.extend(section.sections)
    for blocks in pending:
        found.extend(block for block in blocks if isinstance(block, markdown.Figure))
    return sorted(found, key=lambda figure: figure.line)


def _relocate(report: Collector, generated: Generated) -> None:
    """Riporta a ``document.md`` i problemi dei file generati."""
    for index, item in enumerate(report.items):
        lines = generated.origins.get(item.file)
        if lines is None:
            continue
        if 0 < item.line <= len(lines):
            line = lines[item.line - 1]
        else:
            key = _KEY.search(item.message) if item.file == "structure.toml" else None
            line = generated.keys.get(key.group(1), 0) if key else (lines[0] if lines else 0)
        report.items[index] = dataclasses.replace(item, file=SOURCE, line=line, column=0)


def run(
    source: Path,
    output: str,
    *,
    language: str,
    document_id: str | None,
    strict: bool,
) -> canon.Outcome:
    """Esegue ``import --from markdown``: il codice 0 con l'uscita scritta, 1 se rifiutato."""
    report = Collector()
    bundle = read_package(source, report, layout=MARKDOWN)
    if bundle is not None and "document.md" not in bundle.files:
        report.error("regodoc.package.missing", "manca document.md", SOURCE)
    if bundle is None or report.has_errors():
        return _refused(report)
    document = markdown.read(bundle.files["document.md"])
    for problem in document.problems:
        report.error(problem.code, problem.message, SOURCE, problem.line, problem.column)
    images = {path: data for path, data in bundle.files.items() if path.startswith("images/")}
    for figure in _figures(document):
        if figure.path not in images:
            report.error(
                "regodoc.markdown.image",
                f"«{figure.path}» non è fra i file dell'ingresso",
                SOURCE,
                figure.line,
            )
    if report.has_errors():
        return _refused(report)
    generated = generate(document, images, language)
    data = canonical.archive(list(generated.files.items()))
    outcome = canon.run(
        source,
        output,
        document=document_id,
        base_version=None,
        files_dir=None,
        strict=strict,
        data=data,
    )
    _relocate(outcome.validation.report, generated)
    outcome.validation.input_sha256 = None
    outcome.validation.input_bytes = None
    return outcome


def _refused(report: Collector) -> canon.Outcome:
    report.finish()
    validation = Validation()
    validation.report = report
    return canon.Outcome(1, validation, {})
