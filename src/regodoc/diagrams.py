"""La disposizione dei diagrammi (specifica §4.5): le coordinate le calcola il motore.

Le misure sono in centesimi della larghezza della figura, calcolate con frazioni esatte e
scritte con al massimo due decimali: lo stesso documento dà sempre lo stesso testo LaTeX. In
orizzontale ogni posizione è fissata qui; in verticale le righe di un albero o di un
diagramma a barre si appoggiano alla riga di sopra, perché l'altezza del testo la conosce solo
TeX. TikZ disegna, non dispone: nessuna libreria di disposizione.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

# Lo spazio fra due scatole di una sequenza, il margine che resta alle cornici dei nodi e le
# misure fisse delle barre, in centesimi della larghezza.
SEQUENCE_GAP = Fraction(6)
FRAME = Fraction(4)
BAR_LABEL = Fraction(30)
BAR_LENGTH = Fraction(50)
TREE_INDENT = Fraction(6)


def number(value: Fraction) -> str:
    """Una misura con al massimo due decimali, senza zeri finali: 12, 12.5, 12.33."""
    scaled = value * 100
    whole, rest = divmod(scaled.numerator, scaled.denominator)
    if 2 * rest >= scaled.denominator:
        whole += 1
    sign = "-" if whole < 0 else ""
    units, cents = divmod(abs(whole), 100)
    if not cents:
        return f"{sign}{units}"
    return f"{sign}{units}.{cents:02d}".rstrip("0")


@dataclass(frozen=True)
class Bar:
    label: str
    value: Fraction
    shown: str


@dataclass(frozen=True)
class TreeNode:
    label: str
    children: tuple["TreeNode", ...]


def sequence(labels: Sequence[str]) -> list[str]:
    """Le scatole in fila, da sinistra, con le frecce fra l'una e l'altra."""
    count = len(labels)
    slot = (100 + SEQUENCE_GAP) / count
    width = slot - SEQUENCE_GAP - FRAME
    lines = []
    for index, label in enumerate(labels):
        lines.append(
            rf"\RdDiagramBox{{rd{index}}}{{{number(slot * index)}}}{{{number(width)}}}{{{label}}}"
        )
    lines.extend(rf"\RdDiagramArrow{{rd{index}}}{{rd{index + 1}}}" for index in range(count - 1))
    return lines


def timeline(events: Sequence[tuple[str, str]]) -> list[str]:
    """L'asse, e gli eventi a passo uguale nell'ordine: il testo sopra, la data sotto."""
    count = len(events)
    slot = Fraction(100, count)
    width = slot - FRAME
    lines = [rf"\RdDiagramAxis{{0}}{{{number(100 - FRAME / 2)}}}"]
    for index, (date, label) in enumerate(events):
        x = slot * index + slot / 2
        lines.append(rf"\RdDiagramEvent{{{number(x)}}}{{{number(width)}}}{{{date}}}{{{label}}}")
    return lines


def bars(items: Sequence[Bar]) -> list[str]:
    """Una barra per riga, da zero, in scala lineare fino al valore più grande."""
    top = max(item.value for item in items)
    lines = []
    previous = ""
    for index, item in enumerate(items):
        length = item.value / top * BAR_LENGTH if top > 0 else Fraction(0)
        lines.append(
            rf"\RdDiagramBar{{rd{index}}}{{{previous}}}{{{number(BAR_LABEL)}}}"
            rf"{{{number(length)}}}{{{item.label}}}{{{item.shown}}}"
        )
        previous = f"rd{index}"
    return lines


def tree(root: TreeNode) -> list[str]:
    """L'albero rientrato: un nodo per riga in ordine anticipato, i figli più a destra del
    padre, con un tratto dal padre a ogni figlio."""
    lines: list[str] = []
    edges: list[str] = []
    previous = ""
    pending: list[tuple[TreeNode, int, str]] = [(root, 0, "")]
    counter = 0
    while pending:
        node, depth, parent = pending.pop()
        name = f"rd{counter}"
        counter += 1
        x = TREE_INDENT * depth
        width = 100 - x - FRAME
        lines.append(
            rf"\RdDiagramNode{{{name}}}{{{previous}}}{{{number(x)}}}{{{number(width)}}}"
            rf"{{{node.label}}}"
        )
        if parent:
            edges.append(rf"\RdDiagramEdge{{{parent}}}{{{name}}}")
        previous = name
        pending.extend((child, depth + 1, name) for child in reversed(node.children))
    return lines + edges
