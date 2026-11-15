"""Le variabili calcolate di ``variables.toml`` (specifica, §3.3).

Una formula ha le quattro operazioni, le parentesi, nomi di variabili numeriche e numeri
italiani senza segno. La legge un lettore scritto a mano, un tokenizzatore e una discesa
ricorsiva: niente valutazione dinamica. L'aritmetica è esatta, con ``Fraction``; si arrotonda
solo alla fine di ogni variabile, al mezzo superiore, e il valore arrotondato è quello che
entra nelle altre formule e che il testo stampa.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from regodoc.declaration import CONTENT_LIMITS
from regodoc.diagnostics import Collector

# I limiti di una formula (§3.3).
MAX_CHARACTERS = 500
MAX_OPERANDS = 64
MAX_DEPTH = 16
_MAX_ABS = Fraction(int(CONTENT_LIMITS["number_abs_max"]))

SCALARS = frozenset({"number", "count", "percent"})
UNITS = frozenset({"eur", "gb", "tb", "hours", "days", "months"})
# Tipi che ammettono valori negativi (§3.1), come in tomlfiles.
_NEGATIVE = frozenset({"number", "percent", "eur"})
# Tipi che si scrivono anche come intero TOML: il risultato intero resta un intero, così
# l'unità al singolare vale per un risultato uguale a 1 come per il valore scritto 1.
_INTEGER_TYPES = frozenset({"count", "number", "hours", "days", "months"})
OPERATORS = "+-*/"

_NAME = re.compile(r"[a-z][A-Za-z0-9]{0,47}")
_NUMBER = re.compile(r"(?:0|[1-9]\d{0,2}(?:\.\d{3})*)(?:,\d+)?")
_WORD = re.compile(r"[A-Za-z0-9]+")
_DIGITS = re.compile(r"[0-9A-Za-z.,]+")


class FormulaError(Exception):
    """Una formula che non si può leggere o calcolare: codice e messaggio del rapporto."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Token:
    kind: str  # "name", "number", "op", "(" oppure ")"
    text: str
    column: int  # da 1, nella formula


@dataclass(frozen=True)
class Node:
    """Un nodo della formula: una foglia ("name", "number") o un'operazione ("+", …)."""

    kind: str
    text: str  # il testo della foglia, o della sottoformula per un'operazione
    left: "Node | None" = None
    right: "Node | None" = None


@dataclass(frozen=True)
class Formula:
    source: str
    tree: Node
    names: tuple[str, ...]  # i nomi richiamati, nell'ordine in cui compaiono, senza ripetizioni


def _syntax(column: int, message: str) -> FormulaError:
    return FormulaError(
        "regodoc.toml.calc_syntax", f"{message}, alla colonna {column} della formula"
    )


def tokenize(source: str) -> list[Token]:
    """I simboli della formula; solo spazi fra un simbolo e l'altro."""
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        column = index + 1
        if char == " ":
            index += 1
            continue
        if char in OPERATORS:
            tokens.append(Token("op", char, column))
            index += 1
            continue
        if char in "()":
            tokens.append(Token(char, char, column))
            index += 1
            continue
        if char.isascii() and char.isalpha():
            word = _WORD.match(source, index)
            text = word.group() if word else char
            if not _NAME.fullmatch(text):
                raise _syntax(column, f"«{text}» non è un nome di variabile valido")
            tokens.append(Token("name", text, column))
            index += len(text)
            continue
        if char.isascii() and char.isdigit():
            run = _DIGITS.match(source, index)
            text = run.group() if run else char
            if not _NUMBER.fullmatch(text):
                raise _syntax(
                    column,
                    f"«{text}» non è un numero italiano senza segno, come 2, 0,5 o 1.000",
                )
            tokens.append(Token("number", text, column))
            index += len(text)
            continue
        raise _syntax(column, f"«{char}» non è ammesso: solo nomi, numeri, + - * / e parentesi")
    return tokens


class _Parser:
    def __init__(self, source: str, tokens: list[Token]) -> None:
        self.source = source
        self.tokens = tokens
        self.index = 0
        self.depth = 0
        self.operands = 0

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def column(self) -> int:
        token = self.peek()
        return token.column if token is not None else len(self.source) + 1

    def formula(self) -> Node:
        start = self.column()
        node = self.term()
        while (token := self.peek()) is not None and token.text in "+-" and token.kind == "op":
            self.index += 1
            right = self.term()
            node = Node(token.text, self._span(start), node, right)
        return node

    def term(self) -> Node:
        start = self.column()
        node = self.factor()
        while (token := self.peek()) is not None and token.text in "*/" and token.kind == "op":
            self.index += 1
            right = self.factor()
            node = Node(token.text, self._span(start), node, right)
        return node

    def factor(self) -> Node:
        token = self.peek()
        if token is None:
            raise _syntax(self.column(), "la formula finisce dove serve un nome, un numero o «(»")
        self.index += 1
        if token.kind in ("name", "number"):
            self.operands += 1
            if self.operands > MAX_OPERANDS:
                raise FormulaError(
                    "regodoc.limit.calc", f"più di {MAX_OPERANDS} operandi nella formula"
                )
            return Node(token.kind, token.text)
        if token.kind == "(":
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise FormulaError(
                    "regodoc.limit.calc", f"più di {MAX_DEPTH} livelli di parentesi nella formula"
                )
            inner = self.formula()
            closing = self.peek()
            if closing is None or closing.kind != ")":
                raise _syntax(self.column(), "manca «)»")
            self.index += 1
            self.depth -= 1
            return inner
        raise _syntax(token.column, f"«{token.text}» dove serve un nome, un numero o «(»")

    def _span(self, start: int) -> str:
        end = self.tokens[self.index - 1]
        return self.source[start - 1 : end.column - 1 + len(end.text)]


def parse(source: str) -> Formula:
    """Legge una formula; ``FormulaError`` se non è nella grammatica o supera i limiti."""
    if len(source) > MAX_CHARACTERS:
        raise FormulaError(
            "regodoc.limit.calc",
            f"la formula ha {len(source)} caratteri, il massimo è {MAX_CHARACTERS}",
        )
    tokens = tokenize(source)
    if not tokens:
        raise _syntax(1, "la formula è vuota")
    parser = _Parser(source, tokens)
    tree = parser.formula()
    extra = parser.peek()
    if extra is not None:
        raise _syntax(extra.column, f"«{extra.text}» dove serve un operatore o la fine")
    names = tuple(dict.fromkeys(t.text for t in tokens if t.kind == "name"))
    return Formula(source, tree, names)


def normalize(source: str) -> str:
    """La formula in forma canonica: uno spazio prima e dopo + - * /, nessuno dentro le
    parentesi; nomi e numeri come scritti."""
    out = []
    for token in tokenize(source):
        out.append(f" {token.text} " if token.kind == "op" else token.text)
    return "".join(out)


# --- Tipi e valori --------------------------------------------------------------------------


def _type_error(message: str) -> FormulaError:
    return FormulaError("regodoc.toml.calc_type", message)


def _operands(node: Node) -> tuple[Node, Node]:
    if node.left is None or node.right is None:  # pragma: no cover - il lettore li mette
        raise ValueError(node)
    return node.left, node.right


def result_type(node: Node, types: dict[str, str]) -> str:
    """Il tipo di una formula (§3.3), dai tipi delle variabili richiamate."""
    if node.kind == "number":
        return "number"
    if node.kind == "name":
        return types[node.text]
    first, second = _operands(node)
    left = result_type(first, types)
    right = result_type(second, types)
    if node.kind in "+-":
        if left != right:
            raise _type_error(
                f"«{node.text}»: «{node.kind}» vuole due operandi dello stesso tipo, "
                f"non «{left}» e «{right}»"
            )
        return left
    if node.kind == "*":
        if left in UNITS and right in UNITS:
            raise _type_error(
                f"«{node.text}»: due unità, «{left}» e «{right}», non si moltiplicano"
            )
        return left if left in UNITS else right if right in UNITS else "number"
    # Divisione.
    if left in UNITS and right in SCALARS:
        return left
    if left in SCALARS and right in SCALARS:
        return "number"
    if left == right:
        return "number"
    raise _type_error(f"«{node.text}»: «{left}» non si divide per «{right}»")


def accepts(declared: str, computed: str) -> bool:
    """Se una formula del tipo ``computed`` vale per una variabile di tipo ``declared``."""
    if computed in UNITS:
        return declared == computed
    return declared in SCALARS


def _bounded(value: Fraction, node: Node) -> Fraction:
    if abs(value) > _MAX_ABS:
        raise FormulaError(
            "regodoc.toml.calc_value",
            f"«{node.text}» vale più di {int(_MAX_ABS)} in valore assoluto",
        )
    return value


def evaluate(node: Node, values: dict[str, Fraction]) -> Fraction:
    """Il valore esatto di una formula; ``values`` dà il valore di ogni nome."""
    if node.kind == "number":
        return Fraction(Decimal(node.text.replace(".", "").replace(",", ".")))
    if node.kind == "name":
        return values[node.text]
    first, second = _operands(node)
    left = evaluate(first, values)
    right = evaluate(second, values)
    if node.kind == "+":
        result = left + right
    elif node.kind == "-":
        result = left - right
    elif node.kind == "*":
        result = left * right
    else:
        if right == 0:
            raise FormulaError(
                "regodoc.toml.calc_division", f"«{second.text}» vale zero: divisione per zero"
            )
        result = left / right
    return _bounded(result, node)


def round_half_up(value: Fraction, decimals: int) -> Fraction:
    """Arrotonda al mezzo superiore in valore assoluto: 0,005 → 0,01 e −0,005 → −0,01."""
    scale = 10**decimals
    numerator = abs(value.numerator) * scale
    whole, rest = divmod(numerator, value.denominator)
    if 2 * rest >= value.denominator:
        whole += 1
    return Fraction(-whole if value < 0 else whole, scale)


def italian(value: Fraction) -> str:
    """Un valore con al massimo due decimali come numero italiano, senza zeri finali."""
    sign = "-" if value < 0 else ""
    cents = abs(value) * 100
    if cents.denominator != 1:  # pragma: no cover - si chiama solo su valori arrotondati
        raise ValueError(value)
    units, rest = divmod(int(cents), 100)
    digits = str(units)
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    text = ".".join(groups)
    if rest:
        text += "," + f"{rest:02d}".rstrip("0")
    return sign + text


def stored(kind: str, value: Fraction, source: str) -> object:
    """Il valore arrotondato di una variabile calcolata, nella forma di un valore scritto:
    un intero per un risultato intero dei tipi che lo ammettono, altrimenti un numero
    italiano. ``percent`` si scrive come percentuale (0,725 → "72,5")."""
    shown = value * 100 if kind == "percent" else value
    if kind == "count":
        if shown.denominator != 1:
            raise FormulaError(
                "regodoc.toml.calc_value",
                f"«{source}» non dà un intero: un conteggio non si arrotonda, "
                "chi vuole i decimali dichiara «number»",
            )
        rounded = shown
    else:
        rounded = round_half_up(shown, 2)
    if kind not in _NEGATIVE and rounded < 0:
        raise FormulaError(
            "regodoc.toml.calc_value", f"«{source}» è negativa, e il tipo «{kind}» non lo ammette"
        )
    if abs(rounded) > _MAX_ABS:
        raise FormulaError(
            "regodoc.toml.calc_value", f"«{source}» vale più di {int(_MAX_ABS)} in valore assoluto"
        )
    if rounded.denominator == 1 and kind in _INTEGER_TYPES:
        return int(rounded)
    return italian(rounded)


def written_value(kind: str, value: object) -> Fraction:
    """Il valore esatto di un valore scritto (o già calcolato) di una variabile numerica."""
    if isinstance(value, int):
        number = Fraction(value)
    else:
        number = Fraction(Decimal(str(value).replace(".", "").replace(",", ".")))
    return number / 100 if kind == "percent" else number


# --- Il grafo delle variabili ---------------------------------------------------------------


@dataclass(frozen=True)
class Pending:
    """Una variabile calcolata letta, in attesa del valore."""

    name: str
    type: str
    formula: Formula
    line: int


def _order(pending: dict[str, Pending]) -> tuple[list[str], list[list[str]]]:
    """L'ordine di calcolo, ogni variabile dopo quelle che usa, e i cicli trovati.

    Una visita in profondità con una pila esplicita: una catena lunga quanto il file non
    consuma la ricorsione di Python.
    """
    order: list[str] = []
    cycles: list[list[str]] = []
    state: dict[str, int] = {}  # 1 sul cammino, 2 finita
    for root, entry in pending.items():
        if root in state:
            continue
        path = [root]
        state[root] = 1
        walk = [iter([n for n in entry.formula.names if n in pending])]
        while walk:
            following = next(walk[-1], None)
            if following is None:
                walk.pop()
                done = path.pop()
                state[done] = 2
                order.append(done)
            elif state.get(following) == 1:
                cycles.append([*path[path.index(following) :], following])
            elif following not in state:
                state[following] = 1
                path.append(following)
                names = pending[following].formula.names
                walk.append(iter([n for n in names if n in pending]))
    return order, cycles


def resolve(
    pending: dict[str, Pending],
    known: dict[str, tuple[str, object, bool]],
    declared: set[str],
    file: str,
    report: Collector,
) -> dict[str, object]:
    """Calcola le variabili di ``pending`` nell'ordine delle dipendenze.

    ``known`` dà tipo, valore e intervallo delle variabili scritte valide; ``declared`` tutti
    i nomi del file. Restituisce il valore arrotondato di ogni variabile calcolata riuscita;
    le altre hanno il loro errore nel rapporto, o restano fuori in silenzio quando l'errore è
    di una variabile da cui dipendono.
    """
    done: dict[str, object] = {}
    failed: set[str] = set()

    def error(entry: Pending, code: str, message: str) -> None:
        report.error(code, f"«{entry.name}»: {message}", file, entry.line)
        failed.add(entry.name)

    order, cycles = _order(pending)
    for cycle in cycles:
        if not failed & set(cycle):
            error(
                pending[cycle[0]],
                "regodoc.toml.calc_cycle",
                "ciclo fra variabili: " + " → ".join(cycle),
            )
        failed.update(cycle)

    def compute(entry: Pending) -> None:
        types: dict[str, str] = {}
        values: dict[str, Fraction] = {}
        for used in entry.formula.names:
            if used in pending:
                if used not in done:
                    failed.add(entry.name)  # l'errore è sulla variabile usata
                    return
                types[used] = pending[used].type
                values[used] = written_value(pending[used].type, done[used])
                continue
            if used not in declared:
                error(entry, "regodoc.toml.calc_name", f"la variabile «{used}» non esiste")
                return
            if used not in known:
                failed.add(entry.name)  # la variabile c'è ma è sbagliata: l'errore è già lì
                return
            kind, value, is_range = known[used]
            if kind not in SCALARS | UNITS:
                error(
                    entry,
                    "regodoc.toml.calc_name",
                    f"«{used}» è di tipo «{kind}»: una formula usa solo variabili numeriche",
                )
                return
            if is_range:
                error(
                    entry,
                    "regodoc.toml.calc_name",
                    f"«{used}» è un intervallo: una formula usa solo valori singoli",
                )
                return
            types[used] = kind
            values[used] = written_value(kind, value)
        try:
            computed = result_type(entry.formula.tree, types)
            if not accepts(entry.type, computed):
                raise _type_error(
                    f"la formula dà «{computed}», la variabile è dichiarata «{entry.type}»"
                )
            value = evaluate(entry.formula.tree, values)
            done[entry.name] = stored(entry.type, value, entry.formula.source)
        except FormulaError as problem:
            error(entry, problem.code, problem.message)

    for name in order:
        if name not in failed:
            compute(pending[name])
    return done
