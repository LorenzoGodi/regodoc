"""Controllo d'igiene del repository e dei messaggi di commit.

Il repository è pubblico: questo controllo impedisce che vi entrino nomi vietati, righe di
attribuzione, caratteri invisibili pericolosi o file con codifica e fine riga sbagliati.

I nomi vietati non sono scritti in chiaro, perché un elenco in chiaro violerebbe la regola
stessa: il file ``hygiene_terms.sha256`` contiene, per ogni termine, il modo di confronto, la
lunghezza e l'impronta sha256 della forma normalizzata (minuscole, ogni sequenza di caratteri
non alfanumerici ridotta a uno spazio). I modi sono due:

- ``s``, sottostringa: il controllo calcola l'impronta di ogni sottostringa del testo lunga
  quanto un termine registrato, così un nome vietato è trovato anche dentro un'altra parola;
- ``w``, parola intera: per i pochi termini che sono anche pezzi di parole comuni, dove il
  confronto per sottostringa darebbe falsi allarmi continui; il controllo confronta parole e
  sequenze di due o tre parole.

Le impronte non sono un segreto, servono solo a non stampare i nomi: chi vuole aggiungere un
termine usa ``--hash-term`` (o ``--hash-term --word``), che legge il termine da stdin e
stampa la riga da aggiungere. L'elenco in chiaro sta fuori dal repository.

Uso:
    python tools/check_hygiene.py                 # file tracciati da git
    python tools/check_hygiene.py --commits A..B  # anche i messaggi dei commit nell'intervallo
    python tools/check_hygiene.py --hash-term [--word] < termine.txt
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
# File che per specifica non hanno l'a capo finale: se ne verifica solo il percorso.
EXACT_BYTES_NAMES = frozenset({"mimetype"})
# File in cui il carattere di tabulazione è necessario.
TAB_ALLOWED_NAMES = frozenset({"Makefile"})
MAX_NGRAM = 3
# Identità di autore e committente di ogni commit.
EXPECTED_IDENTITY = "Lorenzo Godi <34336808+LorenzoGodi@users.noreply.github.com>"

# Caratteri di controllo bidirezionale e invisibili usati per nascondere codice (Trojan Source).
_BIDI_AND_INVISIBLE = frozenset(
    "\u061c\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2060\u2066\u2067\u2068\u2069\ufeff"
)
_WORD = re.compile(r"[^\W_]+")
_WORD_OR_NUMBER = re.compile(r"[^\W\d_]+|\d+")
# Un lotto («L5: ») o una revisione fuori dai lotti («A11: »).
_FIRST_LINE = re.compile(r"[LA]\d+: \S")
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


@dataclass(frozen=True)
class Terms:
    """Impronte dei termini vietati: per sottostringa, raggruppate per lunghezza, e per parola."""

    substrings: dict[int, frozenset[bytes]]
    words: frozenset[bytes]

    @property
    def longest(self) -> int:
        """La lunghezza del termine per sottostringa più lungo."""
        return max(self.substrings, default=0)


def normalize(text: str) -> str:
    """Forma normalizzata: NFKC, minuscole, non alfanumerici ridotti a uno spazio."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def term_line(term: str, *, word: bool = False) -> str:
    """La riga da aggiungere a ``hygiene_terms.sha256`` per un termine."""
    normal = normalize(term)
    return f"{'w' if word else 's'} {len(normal)} {_digest(normal).hex()}"


def load_terms(path: Path = TERMS_FILE) -> Terms:
    """Legge le impronte dei termini vietati, ignorando righe vuote e commenti."""
    substrings: dict[int, set[bytes]] = {}
    words: set[bytes] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3 or parts[0] not in ("s", "w") or not parts[1].isdigit():
            raise ValueError(f"{path.name}:{number}: riga non valida")
        digest = bytes.fromhex(parts[2])
        if parts[0] == "w":
            words.add(digest)
        else:
            substrings.setdefault(int(parts[1]), set()).add(digest)
    return Terms({k: frozenset(v) for k, v in substrings.items()}, frozenset(words))


def _words(text: str) -> list[str]:
    """Parole per il confronto a parola intera: si separano anche fra lettere e cifre, così
    un nome seguito da un numero di versione senza separatore è riconosciuto."""
    return _WORD_OR_NUMBER.findall(unicodedata.normalize("NFKC", text).casefold())


def _ngrams(words: list[str], starts: int) -> Iterator[str]:
    """Sequenze di 1..MAX_NGRAM parole che cominciano fra le prime ``starts`` parole."""
    for start in range(starts):
        for size in range(1, MAX_NGRAM + 1):
            if start + size <= len(words):
                yield " ".join(words[start : start + size])


def _has_substring(normal: str, starts: int, terms: Terms) -> bool:
    """Vero se una sottostringa che comincia fra i primi ``starts`` caratteri è vietata."""
    for length, digests in terms.substrings.items():
        for start in range(min(starts, len(normal) - length + 1)):
            if _digest(normal[start : start + length]) in digests:
                return True
    return False


def find_terms(text: str, terms: Terms) -> list[int]:
    """Restituisce i numeri di riga (da 1) che contengono un termine vietato.

    Le ricerche coprono la singola riga e il passaggio alla riga dopo, così un termine
    spezzato da un a capo non sfugge; un termine si attribuisce alla riga dove comincia.
    """
    lines = text.splitlines()
    found: list[int] = []
    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ""
        normal = normalize(line)
        joined = f"{normal} {normalize(following)[: terms.longest]}".rstrip()
        words = _words(line)
        candidates = _ngrams(words + _words(following)[: MAX_NGRAM - 1], len(words))
        if _has_substring(joined, len(normal), terms) or any(
            _digest(c) in terms.words for c in candidates
        ):
            found.append(index + 1)
    return found


def check_text(where: str, data: bytes, terms: Terms, *, tabs: bool) -> list[Problem]:
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
            if char in _BIDI_AND_INVISIBLE or unicodedata.category(char) == "Cf":
                name = unicodedata.name(char, f"U+{ord(char):04X}")
                problems.append(Problem(where, number, f"carattere invisibile {name}"))
            elif char == "\t":
                if not tabs:
                    problems.append(Problem(where, number, "tabulazione"))
            elif unicodedata.category(char) == "Cc":
                problems.append(Problem(where, number, f"carattere di controllo U+{ord(char):04X}"))
    problems.extend(Problem(where, n, "contiene un nome vietato") for n in find_terms(text, terms))
    return problems


def check_file(root: Path, relative: str, terms: Terms) -> list[Problem]:
    """Controlla percorso e contenuto di un file del repository."""
    problems = (
        [Problem(relative, 0, "il percorso contiene un nome vietato")]
        if find_terms(relative, terms)
        else []
    )
    path = root / relative
    if path.is_symlink():
        return [*problems, Problem(relative, 0, "è un collegamento simbolico: non è ammesso")]
    if not path.is_file():
        return problems
    if path.suffix.lower() in BINARY_SUFFIXES or path.name in EXACT_BYTES_NAMES:
        return problems
    tabs = path.name in TAB_ALLOWED_NAMES
    return problems + check_text(relative, path.read_bytes(), terms, tabs=tabs)


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


def check_message(where: str, message: str, terms: Terms) -> list[Problem]:
    """Controlla il messaggio di un commit secondo le regole del repository."""
    problems: list[Problem] = []
    lines = message.splitlines()
    first = lines[0] if lines else ""
    if not _FIRST_LINE.match(first):
        problems.append(
            Problem(where, 1, "la prima riga deve cominciare con il lotto, «Ln: » o «An: »")
        )
    for number, line in enumerate(lines, start=1):
        if line.startswith("#"):
            problems.append(Problem(where, number, "riga che comincia con #"))
        if _CLOSING_KEYWORD.search(line):
            problems.append(Problem(where, number, "parola di chiusura con riferimento a issue"))
    problems.extend(Problem(where, 0, f"trailer non ammesso: {t}") for t in trailers(message))
    problems.extend(
        Problem(where, n, "contiene un nome vietato") for n in find_terms(message, terms)
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


@dataclass(frozen=True)
class Commit:
    """Un commit da controllare: sha breve, autore, committente e messaggio."""

    sha: str
    author: str
    committer: str
    message: str


def check_identity(where: str, commit: Commit) -> list[Problem]:
    """Autore e committente devono essere l'identità del repository."""
    problems = []
    for role, identity in (("autore", commit.author), ("committente", commit.committer)):
        if identity != EXPECTED_IDENTITY:
            problems.append(
                Problem(where, 0, f"{role} «{identity}» diverso da «{EXPECTED_IDENTITY}»")
            )
    return problems


def commits(root: Path, revision_range: str) -> Iterator[Commit]:
    """I commit dell'intervallo, dal più recente."""
    result = subprocess.run(
        ["git", "log", "--format=%h%x00%an <%ae>%x00%cn <%ce>%x00%B%x00", revision_range],  # noqa: S607
        cwd=root,
        capture_output=True,
        check=True,
    )
    fields = result.stdout.decode("utf-8").split("\0")
    for index in range(0, len(fields) - 3, 4):
        sha, author, committer, body = fields[index : index + 4]
        yield Commit(sha.strip(), author, committer, body.strip("\n"))


def run(root: Path, files: Iterable[str], revision_range: str | None) -> list[Problem]:
    """Esegue tutti i controlli e restituisce i problemi trovati."""
    terms = load_terms()
    problems: list[Problem] = []
    for relative in files:
        problems.extend(check_file(root, relative, terms))
    if revision_range:
        for commit in commits(root, revision_range):
            where = f"commit {commit.sha}"
            problems.extend(check_identity(where, commit))
            problems.extend(check_message(where, commit.message, terms))
    return problems


def main(argv: list[str] | None = None) -> int:
    """Punto d'ingresso: 0 se tutto è in ordine, 1 se ci sono problemi."""
    parser = argparse.ArgumentParser(description="Controllo d'igiene del repository.")
    parser.add_argument("--commits", metavar="INTERVALLO", help="intervallo di commit, A..B")
    parser.add_argument("--hash-term", action="store_true", help="impronta di un termine da stdin")
    parser.add_argument("--word", action="store_true", help="con --hash-term: parola intera")
    args = parser.parse_args(argv)
    if args.hash_term:
        print(term_line(sys.stdin.read(), word=args.word))
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
