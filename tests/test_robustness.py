"""Mutazioni casuali dei due esempi: il motore non solleva mai un'eccezione grezza, i rapporti
sono deterministici, restano piccoli e usano solo codici dell'indice della specifica."""

import json
import os
import random
import re
import unittest
from pathlib import Path

from regodoc.text import find_bad_chars, is_allowed_char
from tests.support import EXAMPLE, LONG_EXAMPLE, build_zip, example_files, validate_bytes

SPEC = (Path(__file__).resolve().parent.parent / "docs" / "spec" / "rego-1.md").read_text(
    encoding="utf-8"
)
INDEXED = set(re.findall(r"^\| `(regodoc\.[a-z0-9_.]+)` \|", SPEC, re.M))
# REGODOC_FUZZ alza il numero di mutazioni per una prova lunga, fuori dalla CI.
ROUNDS = int(os.environ.get("REGODOC_FUZZ", "120"))
TEXT_FILES = ("structure.toml", "variables.toml", "manifest.json")


def mutate(data: bytes, generator: random.Random) -> bytes:
    """Una mutazione fra byte, righe e frammenti di sintassi del formato."""
    choice = generator.randrange(8)
    if not data:
        return b"x"
    position = generator.randrange(len(data))
    if choice == 0:  # un byte cambiato
        return data[:position] + bytes([generator.randrange(256)]) + data[position + 1 :]
    if choice == 1:  # troncato
        return data[:position]
    if choice == 2:  # un pezzo ripetuto
        end = min(len(data), position + generator.randint(1, 200))
        return data[:end] + data[position:end] + data[end:]
    if choice == 3:  # un pezzo tolto
        return data[:position] + data[position + generator.randint(1, 200) :]
    lines = data.split(b"\n")
    index = generator.randrange(len(lines))
    if choice == 4:  # una riga tolta
        return b"\n".join(lines[:index] + lines[index + 1 :])
    if choice == 5:  # due righe scambiate
        other = generator.randrange(len(lines))
        lines[index], lines[other] = lines[other], lines[index]
        return b"\n".join(lines)
    fragments = (
        b"<",
        b"&",
        b"]]>",
        b"<!--",
        b'"',
        b"--",
        b"\xe2\x80\xae",
        b"\x00",
        b"<var/>",
        b'<reference to="x" through="y"/>',
        b'<cite to="sources"/>',
        b"<section>",
        b"[[part]]",
        b'= { eur = ["9", "1"] }',
        b"#",
        b"\r",
        b"\t",
        b"\xff",
    )
    insert = generator.choice(fragments)
    return data[:position] + insert + data[position:]


def report(data: bytes) -> list[dict[str, object]]:
    return [d.to_json() for d in validate_bytes(data).report.items]


class MutationTest(unittest.TestCase):
    def test_mutations_never_raise_and_reports_are_stable(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            generator = random.Random(f"{root.name}-2026")  # noqa: S311 - prova ripetibile
            original = example_files(root)
            targets = [p for p in original if p.endswith(".xml") or p in TEXT_FILES]
            for round_number in range(ROUNDS):
                files = dict(original)
                for _ in range(generator.randint(1, 3)):
                    path = generator.choice(targets)
                    files[path] = mutate(files[path], generator)
                data = build_zip(files)
                with self.subTest(root=root.name, round=round_number):
                    first = report(data)
                    self.assertEqual(first, report(data), "rapporto non deterministico")
                    size = len(json.dumps(first, ensure_ascii=False).encode())
                    self.assertLess(size, 1024 * 1024)
                    unknown = {item["code"] for item in first} - INDEXED
                    self.assertEqual(unknown, set(), "codici fuori dall'indice")
                    for item in first:
                        self.assertLessEqual(len(str(item["message"])), 500)

    def test_archive_mutations_never_raise(self) -> None:
        for root in (EXAMPLE, LONG_EXAMPLE):
            generator = random.Random(f"zip-{root.name}")  # noqa: S311 - prova ripetibile
            original = build_zip(example_files(root))
            for round_number in range(ROUNDS):
                data = bytearray(original)
                for _ in range(generator.randint(1, 4)):
                    data[generator.randrange(len(data))] = generator.randrange(256)
                with self.subTest(root=root.name, round=round_number):
                    found = report(bytes(data))
                    self.assertEqual({item["code"] for item in found} - INDEXED, set())

    def test_messages_never_carry_raw_package_text_beyond_the_clip(self) -> None:
        long_id = "x" * 5000
        files = example_files()
        files["parts/backup.xml"] = files["parts/backup.xml"].replace(
            b'<reference to="offsite"/>', f'<reference to="{long_id}"/>'.encode()
        )
        for item in report(build_zip(files)):
            self.assertNotIn("x" * 81, str(item["message"]))
            self.assertLessEqual(len(str(item["message"])), 500)


class CharacterSetTest(unittest.TestCase):
    def test_fast_scan_matches_the_rule(self) -> None:
        # La ricerca con l'espressione regolare coincide con la regola carattere per
        # carattere del §5.2, sui primi 12.288 punti di codice e su un campione oltre.
        points = [*range(0x3000), 0xFEFF, 0xFFFD, 0x1F600, 0x10FFFF]
        text = "".join(chr(c) for c in points if not 0xD800 <= c <= 0xDFFF)
        for newline in (False, True):
            for tab in (False, True):
                with self.subTest(newline=newline, tab=tab):
                    expected = [
                        i
                        for i, char in enumerate(text)
                        if not is_allowed_char(char, newline=newline, tab=tab)
                    ]
                    found = list(find_bad_chars(text, newline=newline, tab=tab))
                    self.assertEqual(found, expected)


if __name__ == "__main__":
    unittest.main()
