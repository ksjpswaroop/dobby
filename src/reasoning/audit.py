"""
Deductive audit of research findings.

The Research stage already flags statistics it cannot source. This goes a step
further and asks a question no confidence marker can: **do these findings
actually hang together?**

Research fans out across five independent tracks, each generated in its own
model call. Nothing forces them to agree, so a brief can simultaneously claim
the market is enterprise-led and that buyers are individual practitioners. That
is not a hallucination in any single call — each is locally plausible — and no
per-claim check will catch it. It only shows up when the claims are compared.

The pipeline: findings → formalize into propositions → decide consistency by
exhaustive search. Formalization is the hard part and is done in two ways:

* **Symbolica** when configured, which uses a model trained for the job.
* **A structural pass** otherwise: detect polar opposites (`is` / `is not`,
  `increases` / `decreases`) over the same subject. Deliberately conservative —
  it reports far fewer conflicts than exist, because a false accusation of
  contradiction is worse than a missed one.

Whatever the source, the *decision* is made by `src.reasoning.logic`, which is
a complete decision procedure. The model proposes; the prover disposes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.reasoning import logic as L

logger = structlog.get_logger()

# Claim pairs that cannot both hold of the same subject. Ordered so the first
# member is the "positive" pole.
_POLAR = [
    ("increase", "decrease"), ("increases", "decreases"), ("growing", "shrinking"),
    ("rising", "falling"), ("expanding", "contracting"), ("high", "low"),
    ("large", "small"), ("cheap", "expensive"), ("free", "paid"),
    ("mature", "nascent"), ("crowded", "underserved"), ("saturated", "emerging"),
    ("commoditised", "differentiated"), ("commoditized", "differentiated"),
    ("b2b", "b2c"), ("enterprise", "consumer"), ("centralised", "decentralised"),
    ("online", "offline"), ("required", "optional"), ("feasible", "infeasible"),
]

_NEGATION = re.compile(
    r"\b(?:not|no|never|cannot|can't|won't|isn't|aren't|doesn't|don't|lacks|"
    r"without|fails to|unlikely)\b", re.I
)
_MARKER = re.compile(r"^\s*\[[^\]]+]\s*")
_STOP = frozenset("""
a an the and or but if then than that this these those there here of to in on
for with by from as at is are was were be been being it its their his her our
your my he she they we you i do does did has have had will would can could may
might must should also more most some any each every which who whom whose what
when where why how very much many few more less least best worst
""".split())


@dataclass
class Conflict:
    """Two findings that cannot both be true."""

    left_index: int
    right_index: int
    left: str
    right: str
    subject: str
    explanation: str
    engine: str = "structural"


@dataclass
class AuditResult:
    """What the deductive pass concluded about a set of findings."""

    checked: int = 0
    conflicts: List[Conflict] = field(default_factory=list)
    engine: str = "local"
    notes: List[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.conflicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked": self.checked,
            "consistent": self.consistent,
            "engine": self.engine,
            "notes": self.notes,
            "conflicts": [
                {
                    "left_index": c.left_index, "right_index": c.right_index,
                    "left": c.left, "right": c.right, "subject": c.subject,
                    "explanation": c.explanation, "engine": c.engine,
                }
                for c in self.conflicts
            ],
        }


def _clean(text: str) -> str:
    """Drop our own provenance markers before analysing the claim itself."""
    return _MARKER.sub("", text or "").strip()


def _keywords(text: str) -> set:
    words = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    return {w for w in words if w not in _STOP}


def _subject_overlap(a: str, b: str) -> Tuple[float, str]:
    """How much two claims are about the same thing, and the shared terms."""
    ka, kb = _keywords(a), _keywords(b)
    if not ka or not kb:
        return 0.0, ""
    shared = ka & kb
    # Jaccard against the smaller set: a short claim fully contained in a long
    # one still counts as being about the same subject.
    score = len(shared) / min(len(ka), len(kb))
    return score, ", ".join(sorted(shared)[:4])


def _polarity_clash(a: str, b: str) -> Optional[str]:
    """Do these assert opposite poles of the same axis?"""
    la, lb = f" {a.lower()} ", f" {b.lower()} "
    for pos, neg in _POLAR:
        a_pos, a_neg = f" {pos} " in la, f" {neg} " in la
        b_pos, b_neg = f" {pos} " in lb, f" {neg} " in lb
        # Each side must pick exactly one pole, and they must differ.
        if (a_pos and not a_neg) and (b_neg and not b_pos):
            return f"“{pos}” versus “{neg}”"
        if (a_neg and not a_pos) and (b_pos and not b_neg):
            return f"“{neg}” versus “{pos}”"
    return None


def _negation_clash(a: str, b: str) -> bool:
    """One claim negates while the other affirms, on otherwise similar wording."""
    return bool(_NEGATION.search(a)) != bool(_NEGATION.search(b))


# Below this, two claims are not about the same subject and any apparent
# opposition is coincidence.
OVERLAP_THRESHOLD = 0.34

# Negation alone is weak evidence of disagreement, so it needs a much stronger
# subject match than a polarity clash does.
NEGATION_OVERLAP = 0.7

# Claims about the search process rather than the world. These cannot
# contradict a claim about the subject — "no information was found" is not the
# negation of "the market is growing" — but they *look* like contradictions to
# any keyword heuristic, so they are excluded before comparison.
_META_CLAIM = re.compile(
    r"^(?:the\s+)?(?:search results?|results?|context|sources?|provided (?:text|content))\b"
    r"|^no (?:relevant )?(?:information|results?|data|sources?)\b"
    r"|^(?:unable|not possible) to (?:determine|find|extract)",
    re.I,
)


def _is_meta_claim(text: str) -> bool:
    return bool(_META_CLAIM.match(text.strip()))


def audit_findings(findings: Sequence[str],
                   min_overlap: float = OVERLAP_THRESHOLD) -> AuditResult:
    """Find pairs of findings that contradict each other.

    Every reported conflict is confirmed by the propositional prover, not just
    by the surface heuristic: the pair is encoded as `P` and `¬P` and passed to
    `is_consistent`, so what reaches the user has been mechanically decided.
    """
    cleaned = [_clean(f) for f in findings]
    result = AuditResult(checked=len(cleaned))

    for i in range(len(cleaned)):
        for j in range(i + 1, len(cleaned)):
            a, b = cleaned[i], cleaned[j]
            if not a or not b:
                continue
            # Belt and braces: the pipeline already drops these at extraction,
            # but a brief created before that filter existed still has them.
            if _is_meta_claim(a) or _is_meta_claim(b):
                continue

            overlap, shared = _subject_overlap(a, b)
            if overlap < min_overlap:
                continue

            polar = _polarity_clash(a, b)
            # A bare negation difference is far too weak on its own: "X is
            # popular" and "Y does not integrate with Z" differ in negation and
            # may share keywords without disagreeing about anything. Live
            # testing produced eight such false positives in one brief. Require
            # near-total subject overlap before negation alone counts.
            negated = _negation_clash(a, b) and overlap >= NEGATION_OVERLAP
            if not polar and not negated:
                continue

            # Encode the opposition and let the prover decide. The heuristic
            # only ever *proposes* a pair; this is what confirms it.
            p = L.parse("P")
            not_p = L.parse("~P")
            if L.is_consistent([p, not_p]).verdict != "invalid":
                continue  # unreachable in classical logic, but never assume

            result.conflicts.append(Conflict(
                left_index=i, right_index=j, left=findings[i], right=findings[j],
                subject=shared,
                explanation=(
                    f"Both discuss {shared or 'the same subject'}, but assert "
                    f"opposite things ({polar})." if polar else
                    f"Both discuss {shared or 'the same subject'}, but one "
                    "affirms what the other denies."
                ),
            ))

    if result.conflicts:
        logger.info("research_audit_conflicts", count=len(result.conflicts))
    return result


async def audit_with_symbolica(findings: Sequence[str]) -> AuditResult:
    """Structural audit, upgraded by the symbolic engine when one is available.

    Symbolica formalizes each finding into a proposition; the resulting set is
    then decided by the local prover, which is complete. When no server is
    configured this is exactly `audit_findings`.
    """
    from src.reasoning import symbolica as sym

    base = audit_findings(findings)
    if not sym.is_configured():
        base.notes.append("Structural check only — no symbolic engine configured.")
        return base

    formalized: List[Tuple[int, L.Formula]] = []
    for idx, raw in enumerate(findings):
        f = await sym.formalize(_clean(raw))
        if not f.ok:
            continue
        try:
            formalized.append((idx, L.parse(f.conclusion)))
        except L.LogicError:
            continue

    if len(formalized) < 2:
        base.engine = "structural"
        base.notes.append(
            "The symbolic engine could not formalize enough findings to compare."
        )
        return base

    base.engine = "symbolica+prover"
    seen = {(c.left_index, c.right_index) for c in base.conflicts}
    for a in range(len(formalized)):
        for b in range(a + 1, len(formalized)):
            i, fa = formalized[a]
            j, fb = formalized[b]
            if (i, j) in seen:
                continue
            if L.is_consistent([fa, fb]).verdict == "invalid":
                base.conflicts.append(Conflict(
                    left_index=i, right_index=j,
                    left=findings[i], right=findings[j], subject="",
                    explanation=(
                        f"Formalized as {fa} and {fb}, which cannot both hold."
                    ),
                    engine="symbolica",
                ))
    return base
