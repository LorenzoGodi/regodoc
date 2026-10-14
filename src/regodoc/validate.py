"""Validazione completa di un pacchetto ``.regodoc``: involucro, manifesto, TOML, parti, immagini.

``validate_package`` non solleva mai eccezioni per un pacchetto sbagliato: ogni problema
diventa un ``Diagnostic`` nel ``Collector``.
"""

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from regodoc import __version__
from regodoc.declaration import CONTENT_LIMITS, ENVELOPE_LIMITS, GRAMMAR_CURRENT, GRAMMARS_READ
from regodoc.diagnostics import Collector, TooManyProblems, clip
from regodoc.images import check_image
from regodoc.parts import Context, PartChecker, Target, Use, parse_part
from regodoc.source import IMAGE_PATH, PART_PATH, PackageFiles, is_allowed_path, read_package
from regodoc.tomlfiles import (
    NUMERIC_TYPES,
    Structure,
    Variable,
    read_structure,
    read_variables,
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_DOCUMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_GRAMMAR = re.compile(r"rego/([1-9][0-9]{0,3})")
_MANIFEST_KEYS = ("format", "grammar", "document", "base_version", "files", "generator")


# File del pacchetto che non sono contenuto: non entrano nell'elenco dei file né nella loro
# impronta d'insieme (contratto, §4.1).
ENVELOPE_FILES = frozenset({"mimetype", "manifest.json", "README.md"})


@dataclass
class Validation:
    """Esito della validazione: problemi, grammatica letta e ciò che il motore restituisce del
    pacchetto a chi lo chiama (contratto, §4.1)."""

    report: Collector = field(default_factory=Collector)
    grammar: str | None = None
    structure: Structure | None = None
    variables: dict[str, Variable] = field(default_factory=dict)
    manifest: dict[str, object] = field(default_factory=dict)
    package: PackageFiles | None = None
    input_sha256: str | None = None
    input_bytes: int | None = None

    def files(self) -> list[dict[str, object]]:
        """I file di contenuto, nell'ordine canonico, con impronta e dimensione."""
        if self.package is None:
            return []
        return [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for path, data in canonical_files(self.package, self.structure)
        ]

    def summary(self) -> dict[str, object]:
        """Ciò che il rapporto dice del pacchetto: grammatica, manifesto, file, intestazione."""
        files = self.files()
        header: dict[str, object] | None = None
        if self.structure is not None:
            date = self.structure.header.get("date")
            header = {
                "title": self.structure.header.get("title"),
                "subject": self.structure.header.get("subject"),
                "reference": self.structure.header.get("reference"),
                "date": date.isoformat() if date is not None else None,  # type: ignore[attr-defined]
                "language": self.structure.language,
            }
        return {
            "grammar": self.grammar,
            "generator": well_formed_generator(self.manifest.get("generator")),
            "document": _valid_or_none(self.manifest.get("document"), _DOCUMENT),
            "base_version": _valid_or_none(self.manifest.get("base_version"), _DIGEST),
            "files": files if self.package is not None else None,
            "files_sha256": files_digest(files) if self.package is not None else None,
            "package_header": header,
        }


def well_formed_generator(value: object) -> dict[str, str] | None:
    """``generator`` del manifesto se ha esattamente ``engine`` e ``version``, testi da 1 a
    64 caratteri; altrimenti None, così il rapporto non ripete valori arbitrari."""
    if not isinstance(value, dict) or set(value) != {"engine", "version"}:
        return None
    if any(not isinstance(v, str) or not 0 < len(v) <= 64 for v in value.values()):
        return None
    return {"engine": value["engine"], "version": value["version"]}


def _valid_or_none(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def canonical_files(package: PackageFiles, structure: Structure | None) -> list[tuple[str, bytes]]:
    """I file di contenuto nell'ordine canonico (specifica, §9): structure.toml,
    variables.toml, le parti nell'ordine di structure.toml, le immagini in ordine alfabetico.
    Le parti che structure.toml non nomina vengono dopo, in ordine alfabetico."""
    order: list[str] = ["structure.toml", "variables.toml"]
    if structure is not None:
        order += [f"parts/{entry.id}.xml" for entry in structure.entries]
    rest = sorted(
        path for path in package.files if path not in order and path not in ENVELOPE_FILES
    )
    parts = [path for path in rest if path.startswith("parts/")]
    images = [path for path in rest if not path.startswith("parts/")]
    return [
        (path, package.files[path]) for path in [*order, *parts, *images] if path in package.files
    ]


def files_digest(files: list[dict[str, object]]) -> str:
    """L'impronta dell'insieme dei file (contratto, §4.1).

    È lo sha256 di un testo UTF-8 con una riga per file, nell'ordine canonico:
    ``<sha256 esadecimale> <byte> <percorso>`` seguito da un a capo.
    """
    text = "".join(f"{f['sha256']} {f['bytes']} {f['path']}\n" for f in files)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_package(path: Path) -> Validation:
    """Valida il pacchetto in ``path``, archivio o cartella."""
    result = Validation()
    if path.is_file():
        with path.open("rb") as handle:
            data = handle.read(ENVELOPE_LIMITS["compressed_bytes"] + 1)
        if len(data) <= ENVELOPE_LIMITS["compressed_bytes"]:
            result.input_sha256 = hashlib.sha256(data).hexdigest()
            result.input_bytes = len(data)
    with contextlib.suppress(TooManyProblems):
        _validate(path, result)
    return result


def _validate(path: Path, result: Validation) -> None:
    report = result.report
    package = read_package(path, report)
    if package is None:
        return
    result.package = package
    readme = package.get("README.md")
    if readme is not None and len(readme) > CONTENT_LIMITS["readme_bytes"]:
        # README.md non si legge, ma non può gonfiare l'involucro senza limite.
        report.error(
            "regodoc.limit.file_size",
            f"README.md è di {len(readme)} byte, il massimo è {CONTENT_LIMITS['readme_bytes']}",
            "README.md",
        )
    result.grammar = _check_manifest(package, report, result.manifest)
    if result.grammar is None:
        return
    structure_data = package.get("structure.toml")
    if structure_data is None:
        report.error("regodoc.package.missing", "manca structure.toml", "structure.toml")
        return
    structure = read_structure(structure_data, report)
    if structure is None:
        return
    result.structure = structure
    variables_data = package.get("variables.toml")
    variables = read_variables(variables_data, report) if variables_data is not None else None
    result.variables = variables.valid if variables is not None else {}
    declared = variables.declared if variables is not None else set()
    _check_parts(package, structure, result.variables, declared, report)


def _check_manifest(
    package: PackageFiles, report: Collector, keep: dict[str, object]
) -> str | None:
    """Legge il manifesto (§1.3) e restituisce la grammatica, o None se non si può proseguire."""
    file = "manifest.json"
    data = package.get(file)
    if data is None:
        report.error("regodoc.manifest.missing", "manca manifest.json", file)
        return None
    if len(data) > CONTENT_LIMITS["manifest_bytes"]:
        report.error("regodoc.limit.file_size", "manifest.json supera 64 KiB", file)
        return None

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        keys = [key for key, _ in items]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"chiave ripetuta «{sorted(duplicates)[0]}»")
        return dict(items)

    def constant(name: str) -> object:
        raise ValueError(f"valore non ammesso «{name}»")

    try:
        manifest = json.loads(
            data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
        )
    except UnicodeDecodeError:
        report.error("regodoc.text.encoding", "manifest.json non è UTF-8 valido", file)
        return None
    except json.JSONDecodeError as error:
        report.error(
            "regodoc.manifest.syntax",
            "manifest.json non è JSON valido",
            file,
            error.lineno,
            error.colno,
        )
        return None
    except (ValueError, RecursionError) as error:
        report.error("regodoc.manifest.syntax", f"manifest.json: {error}", file)
        return None
    if not isinstance(manifest, dict):
        report.error("regodoc.manifest.type", "manifest.json deve essere un oggetto", file)
        return None
    for key in manifest:
        if key not in _MANIFEST_KEYS:
            report.error("regodoc.manifest.unknown_key", f"chiave «{key}» non prevista", file)
    if manifest.get("format") != "regodoc":
        report.error("regodoc.manifest.format", "«format» deve valere «regodoc»", file)
        return None
    grammar = manifest.get("grammar")
    match = _GRAMMAR.fullmatch(grammar) if isinstance(grammar, str) else None
    if match is None:
        report.error("regodoc.manifest.grammar", "«grammar» non è una grammatica valida", file)
        return None
    if grammar not in GRAMMARS_READ:
        current = _GRAMMAR.fullmatch(GRAMMAR_CURRENT)
        if current and int(match.group(1)) > int(current.group(1)):
            writer = ""
            generator = well_formed_generator(manifest.get("generator"))
            if generator is not None:
                writer = f", scritto da {clip(generator['engine'])} {clip(generator['version'])}"
            report.error(
                "regodoc.manifest.grammar_newer",
                f"il pacchetto usa la grammatica «{grammar}»{writer}, più nuova di quelle che "
                f"questo motore ({__version__}) sa leggere ({', '.join(GRAMMARS_READ)}): "
                "serve una versione più recente di regodoc",
                file,
            )
        else:
            report.error("regodoc.manifest.grammar", f"grammatica «{grammar}» sconosciuta", file)
        return None
    _check_manifest_optional(manifest, report)
    keep.update(manifest)
    return grammar


def _check_manifest_optional(manifest: dict[str, object], report: Collector) -> None:
    file = "manifest.json"
    document = manifest.get("document")
    if document is not None and not (isinstance(document, str) and _DOCUMENT.fullmatch(document)):
        report.error("regodoc.manifest.value", "«document» non è un identificatore valido", file)
    base = manifest.get("base_version")
    if base is not None and not (isinstance(base, str) and _DIGEST.fullmatch(base)):
        report.error(
            "regodoc.manifest.value", "«base_version» deve essere sha256: e 64 cifre", file
        )
    files = manifest.get("files")
    if files is not None:
        if not isinstance(files, dict):
            report.error("regodoc.manifest.type", "«files» deve essere un oggetto", file)
        else:
            for path, digest in files.items():
                if path in ("mimetype", "manifest.json") or not is_allowed_path(path):
                    report.error(
                        "regodoc.manifest.value", f"«files»: percorso non ammesso «{path}»", file
                    )
                elif not (isinstance(digest, str) and _DIGEST.fullmatch(digest)):
                    report.error(
                        "regodoc.manifest.value",
                        f"«files»: impronta non valida per «{path}»",
                        file,
                    )
    generator = manifest.get("generator")
    if generator is not None:
        if not isinstance(generator, dict) or set(generator) - {"engine", "version"}:
            report.error(
                "regodoc.manifest.value", "«generator» ammette solo «engine» e «version»", file
            )
        elif any(not isinstance(v, str) or not 0 < len(v) <= 64 for v in generator.values()):
            report.error("regodoc.manifest.value", "«generator»: testi da 1 a 64 caratteri", file)


def _check_parts(
    package: PackageFiles,
    structure: Structure,
    variables: dict[str, Variable],
    declared: set[str] | None,
    report: Collector,
) -> None:
    entries = {entry.id: entry for entry in structure.entries}
    context = Context(report, variables, entries)
    context.declared_variables = declared
    for entry in structure.entries:
        context.define(entry.id, Target(entry.kind, "structure.toml", 0, 0, entry.id))
    # Falso se una parte manca, non si legge o non si legge affatto perché orfana, o se una
    # voce di structure.toml è esclusa: allora gli id e gli usi raccolti sono incompleti, e
    # «non esiste» o «mai usata» potrebbero essere falsi (§6).
    complete = structure.invalid_entries == 0
    declared = {f"parts/{entry.id}.xml" for entry in structure.entries}
    for path in package.files:
        if PART_PATH.fullmatch(path) and path not in declared:
            complete = False
            if structure.invalid_entries:
                continue  # il file potrebbe essere di una voce con l'id sbagliato
            report.error(
                "regodoc.package.orphan_part",
                "il file non corrisponde a nessun id di structure.toml",
                path,
            )
    for entry in structure.entries:
        path = f"parts/{entry.id}.xml"
        data = package.get(path)
        if data is None:
            complete = False
            report.error(
                "regodoc.package.missing_part",
                f"manca il file della {'parte' if entry.kind == 'part' else 'apertura'} "
                f"«{entry.id}»",
                path,
            )
            continue
        root = parse_part(data, path, report)
        if root is None:
            complete = False
        else:
            PartChecker(context, path, entry).check_root(root)
    images = {path for path in package.files if IMAGE_PATH.fullmatch(path)}
    if len(images) > CONTENT_LIMITS["images"]:
        report.error(
            "regodoc.limit.images",
            f"{len(images)} immagini, il massimo è {CONTENT_LIMITS['images']}",
        )
    for path in sorted(images):
        check_image(path, package.files[path], report)
    context.complete = complete
    _check_uses(context, images, complete=complete)
    _check_totals(context)


def _check_uses(context: Context, images: set[str], *, complete: bool) -> None:
    report = context.report
    used_variables: set[str] = set()
    used_images: set[str] = set()
    for use in context.uses:
        where = (use.file, use.line, use.column)
        if use.kind == "var":
            variable = context.variables.get(use.name)
            declared = context.declared_variables
            if variable is None and (declared is None or use.name in declared):
                # Il file è illeggibile, o la variabile c'è ma non è valida: l'errore è già
                # nel rapporto, e dire «non esiste» sarebbe falso.
                used_variables.add(use.name)
                continue
            if variable is None:
                report.error(
                    "regodoc.xml.unknown_variable",
                    f"la variabile «{use.name}» non esiste in variables.toml",
                    *where,
                )
                continue
            used_variables.add(use.name)
            if use.extra == "number" and variable.type not in NUMERIC_TYPES:
                report.error(
                    "regodoc.xml.var_form",
                    f'form="number" vale solo per variabili numeriche, «{use.name}» è '
                    f"di tipo «{variable.type}»",
                    *where,
                )
            if use.extra in ("min", "max") and not variable.is_range:
                report.error(
                    "regodoc.xml.var_form",
                    f'form="{use.extra}" vale solo per gli intervalli, «{use.name}» non lo è',
                    *where,
                )
        elif use.kind == "figure":
            if use.name not in images:
                report.error(
                    "regodoc.xml.missing_image",
                    f"l'immagine «{use.name}» non c'è nel pacchetto",
                    *where,
                )
            used_images.add(use.name)
        elif use.kind == "cite":
            target = context.targets.get(use.name)
            if target is None and not complete:
                continue  # l'id potrebbe stare in una parte non letta
            if target is None:
                report.error("regodoc.xml.unknown_id", f"l'id «{use.name}» non esiste", *where)
            elif target.kind != "source":
                report.error(
                    "regodoc.xml.cite_target",
                    f"«{use.name}» non è una fonte: <cite/> cita solo le <source>",
                    *where,
                )
        elif use.kind == "reference":
            _check_reference(context, use)
    if not complete:
        return  # con una parte illeggibile, «mai usata» potrebbe essere falso
    for name, variable in context.variables.items():
        if name not in used_variables:
            report.warning(
                "regodoc.toml.unused_variable",
                f"la variabile «{name}» non è mai usata",
                "variables.toml",
                variable.line,
            )
    for path in sorted(images - used_images):
        report.warning("regodoc.image.unused", "l'immagine non è mai usata", path)


def _check_reference(context: Context, use: Use) -> None:
    report = context.report
    where = (use.file, use.line, use.column)
    target = context.targets.get(use.name)
    if target is None:
        if context.complete:
            report.error("regodoc.xml.unknown_id", f"l'id «{use.name}» non esiste", *where)
        return
    if target.kind == "source":
        report.error(
            "regodoc.xml.reference_target",
            f"«{use.name}» è una fonte: si cita con <cite/>, non con <reference/>",
            *where,
        )
        return
    if target.kind not in ("part", "section"):
        report.error(
            "regodoc.xml.reference_target",
            f"«{use.name}» non è una parte né una sezione: non ha titolo né numero",
            *where,
        )
        return
    if not use.extra:
        return
    end = context.targets.get(use.extra)
    if end is None and not context.complete:
        return  # l'id finale potrebbe stare in una parte non letta
    if target.kind != "part" or end is None or end.kind != "part":
        report.error(
            "regodoc.xml.reference_through",
            "«through» si usa solo fra due parti",
            *where,
        )
        return
    if context.entries[use.extra].number <= context.entries[use.name].number:
        report.error(
            "regodoc.xml.reference_through",
            f"la parte «{use.extra}» deve venire dopo «{use.name}»",
            *where,
        )


def _check_totals(context: Context) -> None:
    report = context.report
    if context.characters > CONTENT_LIMITS["characters"]:
        report.error(
            "regodoc.limit.characters",
            f"il testo conta {context.characters} caratteri, il massimo è "
            f"{CONTENT_LIMITS['characters']}",
        )
    if context.references > CONTENT_LIMITS["references"]:
        report.error(
            "regodoc.limit.references",
            f"{context.references} rimandi e citazioni, il massimo è "
            f"{CONTENT_LIMITS['references']}",
        )
    if context.sources > CONTENT_LIMITS["sources"]:
        report.error(
            "regodoc.limit.sources",
            f"{context.sources} fonti, il massimo è {CONTENT_LIMITS['sources']}",
        )
