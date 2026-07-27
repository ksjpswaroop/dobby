"""
Classical propositional logic — parser, evaluator, and decision procedure.

This is real deduction, not an LLM asked to be careful. Entailment is decided by
exhaustive truth-table search, which for propositional logic is *complete*: a
sequent is valid or it is not, and when it is not the search hands back a
concrete countermodel — an assignment making every premise true and the
conclusion false.

Pure standard library and fully offline, because it has to work on the same
terms as the rest of Dobby. Symbolica (`src/reasoning/symbolica.py`) is the
optional escalation for first-order logic, Fitch proofs, and causal queries;
this module is what runs when nothing else is configured.

Syntax accepted (ASCII and unicode, case-insensitive keywords):

    ~ ! ¬ not          negation
    & ^ ∧ and          conjunction
    | ∨ or             disjunction
    -> => → implies    material conditional
    <-> <=> ↔ iff      biconditional
    ( )                grouping

Atoms are identifiers: ``A``, ``B12``, ``rains``. Bare ``true``/``false`` are
recognised as constants.

Precedence, loosest to tightest: ↔, →, ∨, ∧, ¬.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

MAX_ATOMS = 16  # 2**16 rows is the practical ceiling for exhaustive search


class LogicError(ValueError):
    """A formula could not be parsed. Message is user-facing."""


# ---------------------------------------------------------------------------
# AST
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Formula:
    """A propositional formula.

    ``kind`` is one of: atom, const, not, and, or, implies, iff.
    """

    kind: str
    name: str = ""
    args: Tuple["Formula", ...] = ()

    def atoms(self) -> Set[str]:
        if self.kind == "atom":
            return {self.name}
        return set().union(*(a.atoms() for a in self.args)) if self.args else set()

    def evaluate(self, model: Dict[str, bool]) -> bool:
        k = self.kind
        if k == "atom":
            return model.get(self.name, False)
        if k == "const":
            return self.name == "true"
        if k == "not":
            return not self.args[0].evaluate(model)
        if k == "and":
            return all(a.evaluate(model) for a in self.args)
        if k == "or":
            return any(a.evaluate(model) for a in self.args)
        if k == "implies":
            return (not self.args[0].evaluate(model)) or self.args[1].evaluate(model)
        if k == "iff":
            return self.args[0].evaluate(model) == self.args[1].evaluate(model)
        raise LogicError(f"Unknown connective: {k}")

    def __str__(self) -> str:
        k = self.kind
        if k in ("atom", "const"):
            return self.name
        if k == "not":
            return f"¬{self.args[0]}"
        glyph = {"and": "∧", "or": "∨", "implies": "→", "iff": "↔"}[k]
        return f"({self.args[0]} {glyph} {self.args[1]})"


# ---------------------------------------------------------------------------
# Tokenizer + parser (recursive descent)
# ---------------------------------------------------------------------------
_TOKENS = [
    ("IFF", r"<->|<=>|↔|\biff\b"),
    ("IMPLIES", r"->|=>|→|\bimplies\b"),
    ("OR", r"\||∨|\bor\b"),
    ("AND", r"&|\^|∧|\band\b"),
    ("NOT", r"~|!|¬|\bnot\b"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("ATOM", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("WS", r"\s+"),
]
_TOKEN_RE = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _TOKENS), re.I)


def _tokenize(text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise LogicError(f"Unexpected character {text[pos]!r} at position {pos}.")
        kind = m.lastgroup or ""
        if kind != "WS":
            out.append((kind, m.group()))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, tokens: List[Tuple[str, str]], source: str):
        self.tokens = tokens
        self.i = 0
        self.source = source

    def peek(self) -> Optional[str]:
        return self.tokens[self.i][0] if self.i < len(self.tokens) else None

    def take(self, kind: str) -> str:
        if self.peek() != kind:
            raise LogicError(f"Expected {kind.lower()} in {self.source!r}.")
        val = self.tokens[self.i][1]
        self.i += 1
        return val

    def parse(self) -> Formula:
        f = self.iff()
        if self.i != len(self.tokens):
            raise LogicError(f"Unexpected trailing input in {self.source!r}.")
        return f

    def iff(self) -> Formula:
        left = self.implies()
        while self.peek() == "IFF":
            self.take("IFF")
            left = Formula("iff", args=(left, self.implies()))
        return left

    def implies(self) -> Formula:
        left = self.disjunction()
        if self.peek() == "IMPLIES":
            self.take("IMPLIES")
            # Right-associative: A -> B -> C is A -> (B -> C).
            return Formula("implies", args=(left, self.implies()))
        return left

    def disjunction(self) -> Formula:
        left = self.conjunction()
        while self.peek() == "OR":
            self.take("OR")
            left = Formula("or", args=(left, self.conjunction()))
        return left

    def conjunction(self) -> Formula:
        left = self.unary()
        while self.peek() == "AND":
            self.take("AND")
            left = Formula("and", args=(left, self.unary()))
        return left

    def unary(self) -> Formula:
        if self.peek() == "NOT":
            self.take("NOT")
            return Formula("not", args=(self.unary(),))
        if self.peek() == "LPAREN":
            self.take("LPAREN")
            inner = self.iff()
            self.take("RPAREN")
            return inner
        if self.peek() == "ATOM":
            name = self.take("ATOM")
            if name.lower() in ("true", "false"):
                return Formula("const", name.lower())
            return Formula("atom", name)
        raise LogicError(f"Expected a formula in {self.source!r}.")


def parse(text: str) -> Formula:
    """Parse one formula. Raises `LogicError` with a user-facing message."""
    if not (text or "").strip():
        raise LogicError("Empty formula.")
    return _Parser(_tokenize(text), text.strip()).parse()


# ---------------------------------------------------------------------------
# Decision procedures
# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    """The result of a deductive check."""

    verdict: str                       # valid | invalid | unknown
    countermodel: Optional[Dict[str, bool]] = None
    reason: str = ""
    checked_rows: int = 0

    @property
    def ok(self) -> bool:
        return self.verdict == "valid"


def _models(atoms: Sequence[str]) -> Iterable[Dict[str, bool]]:
    for combo in itertools.product([False, True], repeat=len(atoms)):
        yield dict(zip(atoms, combo))


def entails(premises: Sequence[Formula], conclusion: Formula) -> Verdict:
    """Does `conclusion` follow from `premises` in classical logic?

    Complete for propositional logic: every assignment is examined, so a
    negative answer always carries a witness. Beyond `MAX_ATOMS` distinct atoms
    the search is refused rather than run — an honest `unknown` is better than
    an hour of CPU.
    """
    atoms = sorted(set().union(*(p.atoms() for p in premises), conclusion.atoms())
                   if premises else conclusion.atoms())
    if len(atoms) > MAX_ATOMS:
        return Verdict("unknown", reason=(
            f"{len(atoms)} distinct atoms exceeds the {MAX_ATOMS} this engine "
            "will search exhaustively."
        ))

    rows = 0
    for model in _models(atoms):
        rows += 1
        if all(p.evaluate(model) for p in premises) and not conclusion.evaluate(model):
            return Verdict("invalid", countermodel=model, checked_rows=rows, reason=(
                "There is an assignment making every premise true and the "
                "conclusion false."
            ))
    return Verdict("valid", checked_rows=rows,
                   reason="No assignment makes the premises true and the conclusion false.")


def is_consistent(formulas: Sequence[Formula]) -> Verdict:
    """Can all of these be true at once?

    `valid` here means "consistent" — a satisfying model exists and is returned
    as the countermodel field (a witness, not a counterexample).
    """
    if not formulas:
        return Verdict("valid", reason="An empty set is trivially consistent.")
    atoms = sorted(set().union(*(f.atoms() for f in formulas)))
    if len(atoms) > MAX_ATOMS:
        return Verdict("unknown", reason=f"{len(atoms)} atoms exceeds the search limit.")

    rows = 0
    for model in _models(atoms):
        rows += 1
        if all(f.evaluate(model) for f in formulas):
            return Verdict("valid", countermodel=model, checked_rows=rows,
                           reason="Found an assignment satisfying every statement.")
    return Verdict("invalid", checked_rows=rows,
                   reason="No assignment satisfies all of these at once — they contradict.")


def find_contradictions(formulas: Sequence[Formula]) -> List[Tuple[int, int]]:
    """Index pairs that cannot both be true.

    Pairwise rather than a minimal unsatisfiable core: the point is to tell a
    user *which two claims* clash, and a pair is what they can act on. Reported
    only when each formula is individually satisfiable, so a self-contradictory
    statement is not blamed on its neighbour.
    """
    clashes: List[Tuple[int, int]] = []
    satisfiable = [is_consistent([f]).verdict == "valid" for f in formulas]
    for i in range(len(formulas)):
        if not satisfiable[i]:
            continue
        for j in range(i + 1, len(formulas)):
            if not satisfiable[j]:
                continue
            if is_consistent([formulas[i], formulas[j]]).verdict == "invalid":
                clashes.append((i, j))
    return clashes


def is_tautology(formula: Formula) -> bool:
    return entails([], formula).verdict == "valid"


def check(premises: Sequence[str], conclusion: str) -> Verdict:
    """Parse-and-decide convenience wrapper over `entails`."""
    try:
        parsed = [parse(p) for p in premises]
        goal = parse(conclusion)
    except LogicError as e:
        return Verdict("unknown", reason=str(e))
    return entails(parsed, goal)
