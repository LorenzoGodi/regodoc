"""Controllo d'igiene del repository e dei messaggi di commit.

Il repository è pubblico: questo controllo impedisce che vi entrino nomi vietati, righe di
attribuzione, caratteri invisibili pericolosi o file con codifica e fine riga sbagliati.

I nomi vietati non sono scritti in chiaro, perché un elenco in chiaro violerebbe la regola
stessa: il file ``hygiene_terms.sha256`` contiene le impronte sha256 dei termini in minuscolo.
Il controllo calcola l'impronta di ogni parola e di ogni sequenza di due o tre parole del
testo e la confronta con l'elenco. Le impronte non sono un segreto, servono solo a non
stampare i nomi: chi vuole aggiungere un termine usa ``--hash-term``, che legge il termine da
stdin e stampa la riga da aggiungere.

Uso:
    python tools/check_hygiene.py                 # file tracciati da git
    python tools/check_hygiene.py --commits A..B  # anche i messaggi dei commit nell'intervallo
    python tools/check_hygiene.py --hash-term < termine.txt
"""

import argparse
import hashlib
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = Path(__file__).resolve().parent / "hygiene_terms.sha256"

# File che il controllo non legge come testo: ne verifica solo il percorso.
BINARY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".pdf", ".regodoc", ".zip"})
# File in cui il carattere di tabulazione è necessario.
TAB_ALLOWED_NAMES = frozenset({"Makefile"})
MAX_NGRAM = 3

# Caratteri di controllo bidirezionale e invisibili usati per nascondere codice (Trojan Source).
_BIDI_AND_INVISIBLE = frozenset(
    "\u061c\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2060\u2066\u2067\u2068\u2069\ufeff"
)
_WORD = re.compile(r"[^\W_]+")
_FIRST_LINE = re.compile(r"L\d+: \S")
_CLOSING_KEYWORD = re.compile(
    r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[\s:]+([\w.-]+/[\w.-]+)?#\d+", re.IGNORECASE
)


@dataclass(frozen=True)
class Problem:
    """Un problema trovato, con la sua posizione."""

    where: str
    line: int
    message: str

    def __str__(self) -> str:
        """Formato «percorso:riga: messaggio», con la riga omessa se non serve."""
        if self.line:
            return f"{self.where}:{self.line}: {self.message}"
        return f"{self.where}: {self.message}"


def term_hash(term: str) -> str:
    """Impronta di un termine nella forma normalizzata usata dal controllo."""
    words = _words(term)
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def load_term_hashes(path: Path = TERMS_FILE) -> frozenset[str]:
    """Legge le impronte dei termini vietati, ignorando righe vuote e commenti."""
    hashes = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            hashes.add(line.lower())
    return frozenset(hashes)


def _words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _ngrams(words: list[str], starts: int) -> Iterator[str]:
    """Sequenze di 1..MAX_NGRAM parole che cominciano fra le prime ``starts`` parole."""
    for start in range(starts):
        for size in range(1, MAX_NGRAM + 1):
            if start + size <= len(words):
                yield " ".join(words[start : start + size])


def find_terms(text: str, hashes: frozenset[str]) -> list[int]:
    """Restituisce i numeri di riga (da 1) che contengono un termine vietato.

    Le sequenze di parole sono cercate dentro la singola riga e a cavallo di due righe
    consecutive, così un termine composto spezzato da un a capo non sfugge.
    """
    lines = text.splitlines()
    found: list[int] = []
    for index, line in enumerate(lines):
        words = _words(line)
        following = _words(lines[index + 1])[: MAX_NGRAM - 1] if index + 1 < len(lines) else []
        # Solo le sequenze che cominciano su questa riga: la riga dopo serve a completarle.
        candidates = _ngrams(words + following, len(words))
        if any(hashlib.sha256(c.encode("utf-8")).hexdigest() in hashes for c in candidates):
            found.append(index + 1)
    return found


def check_text(where: str, data: bytes, hashes: frozenset[str], *, tabs: bool) -> list[Problem]:
    """Controlla il contenuto di un file di testo."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return [Problem(where, 0, f"non è UTF-8 valido (byte {error.start})")]
    problems: list[Problem] = []
    if text.startswith("\ufeff"):
        problems.append(Problem(where, 1, "comincia con un BOM"))
    if "\r" in text:
        problems.append(Problem(where, text[: text.index("\r")].count("\n") + 1, "fine riga CR"))
    if text and not text.endswith("\n"):
        problems.append(Problem(where, text.count("\n") + 1, "manca l'a capo finale"))
    for number, line in enumerate(text.split("\n"), start=1):
        if line != line.rstrip(" \t"):
            problems.append(Problem(where, number, "spazi in fondo alla riga"))
        for char in line:
            if char in _BIDI_AND_INVISIBLE:
                name = unicodedata.name(char, f"U+{ord(char):04X}")
                problems.append(Problem(where, number, f"carattere invisibile {name}"))
            elif char == "\t":
                if not tabs:
                    problems.append(Problem(where, number, "tabulazione"))
            elif unicodedata.category(char) == "Cc":
                problems.append(Problem(where, number, f"carattere di controllo U+{ord(char):04X}"))
    problems.extend(Problem(where, n, "contiene un nome vietato") for n in find_terms(text, hashes))
    return problems


def check_file(root: Path, relative: str, hashes: frozenset[str]) -> list[Problem]:
    """Controlla percorso e contenuto di un file del repository."""
    problems = (
        [Problem(relative, 0, "il percorso contiene un nome vietato")]
        if find_terms(relative, hashes)
        else []
    )
    path = root / relative
    if path.is_symlink() or not path.is_file():
        return problems
    if path.suffix.lower() in BINARY_SUFFIXES:
        return problems
    tabs = path.name in TAB_ALLOWED_NAMES
    return problems + check_text(relative, path.read_bytes(), hashes, tabs=tabs)


def trailers(message: str) -> list[str]:
    """Restituisce i trailer che git riconosce nel messaggio di un commit."""
    result = subprocess.run(
        ["git", "interpret-trailers", "--parse", "--no-divider"],  # noqa: S607 - git dal PATH
        input=message,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def check_message(where: str, message: str, hashes: frozenset[str]) -> list[Problem]:
    """Controlla il messaggio di un commit secondo le regole del repository."""
    problems: list[Problem] = []
    lines = message.splitlines()
    first = lines[0] if lines else ""
    if not _FIRST_LINE.match(first):
        problems.append(Problem(where, 1, "la prima riga deve cominciare con il lotto, «Ln: »"))
    for number, line in enumerate(lines, start=1):
        if line.startswith("#"):
            problems.append(Problem(where, number, "riga che comincia con #"))
        if _CLOSING_KEYWORD.search(line):
            problems.append(Problem(where, number, "parola di chiusura con riferimento a issue"))
    problems.extend(Problem(where, 0, f"trailer non ammesso: {t}") for t in trailers(message))
    problems.extend(
        Problem(where, n, "contiene un nome vietato") for n in find_terms(message, hashes)
    )
    return problems


def tracked_files(root: Path) -> list[str]:
    """Elenca i file tracciati da git."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 - git dal PATH
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def commit_messages(root: Path, revision_range: str) -> Iterator[tuple[str, str]]:
    """Restituisce coppie (sha breve, messaggio) dei commit nell'intervallo."""
    result = subprocess.run(
        ["git", "log", "--format=%h%x00%B%x00", revision_range],  # noqa: S607 - git dal PATH
        cwd=root,
        capture_output=True,
        check=True,
    )
    fields = result.stdout.decode("utf-8").split("\0")
    for sha, body in zip(fields[0::2], fields[1::2], strict=False):
        yield sha.strip(), body.strip("\n")


def run(root: Path, files: Iterable[str], revision_range: str | None) -> list[Problem]:
    """Esegue tutti i controlli e restituisce i problemi trovati."""
    hashes = load_term_hashes()
    problems: list[Problem] = []
    for relative in files:
        problems.extend(check_file(root, relative, hashes))
    if revision_range:
        for sha, message in commit_messages(root, revision_range):
            problems.extend(check_message(f"commit {sha}", message, hashes))
    return problems


def main(argv: list[str] | None = None) -> int:
    """Punto d'ingresso: 0 se tutto è in ordine, 1 se ci sono problemi."""
    parser = argparse.ArgumentParser(description="Controllo d'igiene del repository.")
    parser.add_argument("--commits", metavar="INTERVALLO", help="intervallo di commit, A..B")
    parser.add_argument("--hash-term", action="store_true", help="impronta di un termine da stdin")
    args = parser.parse_args(argv)
    if args.hash_term:
        print(term_hash(sys.stdin.read()))
        return 0
    problems = run(ROOT, tracked_files(ROOT), args.commits)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"igiene: {len(problems)} problemi", file=sys.stderr)
        return 1
    print("igiene: nessun problema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
