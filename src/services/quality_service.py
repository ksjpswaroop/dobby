"""
Verification reporting, custom rules, citation checking, auto-fix
(100-Day Roadmap, Phase 9: D81, D82, D83, D85).

The existing `DeterministicVerifier` already produces a score and a list of
issues; what was missing was everything *around* it — a per-dimension
breakdown a human can navigate, user-authored rules that run alongside the
built-in seven, a check that claims in a document are actually supported, and
fixes that can be applied rather than merely described.

**Auto-fixes are deterministic and previewable.** Every fix here is a text
transformation the code performs itself — no model — and every one returns a
before/after so the user approves the exact change. A fix you cannot inspect
is one you stop applying.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.db.schema import DatabaseManager, Node
from src.db.trust_models import ConsistencyIssue

# A user-authored rule is one of a small set of shapes rather than arbitrary
# code: a rules editor that executes user code is a remote-execution hole in
# an app that also imports files from other people.
RULE_KINDS = ("required_section", "forbidden_phrase", "min_words", "max_words",
              "required_phrase", "regex_absent")

SEVERITIES = ("info", "warning", "error")

FIX_KINDS = ("strip_placeholders", "collapse_blank_lines", "normalise_headings",
             "trim_trailing_whitespace", "fix_list_markers")


class QualityError(Exception):
    pass


# ---------------------------------------------------------------------------
# Verification report (D81)
# ---------------------------------------------------------------------------
async def verification_report(db: DatabaseManager, node_id: str) -> Dict[str, Any]:
    """Run the deterministic verifier and shape its output for a human."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise QualityError("Document not found.")
        content, node_type, title = node.content or "", node.node_type, node.title

    from src.verifiers.deterministic_verifier import get_verifier

    verifier = get_verifier()
    result = await verifier.verify_section(node_id, content, node_type)
    payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)

    issues = payload.get("issues", [])

    # Group by dimension so the report is navigable rather than a flat list.
    by_dimension: Dict[str, Dict[str, Any]] = {}
    for check in payload.get("checks_performed", []):
        by_dimension[check] = {"check": check, "issues": [], "critical": 0,
                               "warning": 0, "info": 0}
    for issue in issues:
        check = issue.get("check_type", "quality")
        bucket = by_dimension.setdefault(
            check, {"check": check, "issues": [], "critical": 0, "warning": 0, "info": 0})
        bucket["issues"].append(issue)
        severity = issue.get("severity", "info")
        if severity in bucket:
            bucket[severity] += 1

    for bucket in by_dimension.values():
        # A dimension's own verdict, so a clean dimension is visibly clean.
        bucket["passed"] = bucket["critical"] == 0 and bucket["warning"] == 0
        bucket["count"] = len(bucket["issues"])

    fixable = [i for i in issues if _fix_for_issue(i)]

    return {
        "node_id": node_id,
        "title": title,
        "overall_score": payload.get("overall_score", 0),
        "passed": payload.get("passed", False),
        "dimensions": sorted(by_dimension.values(), key=lambda d: d["check"]),
        "issue_count": len(issues),
        "by_severity": {
            sev: sum(1 for i in issues if i.get("severity") == sev)
            for sev in ("critical", "warning", "info")
        },
        "fixable_count": len(fixable),
        "metrics": payload.get("metrics", {}),
        "verified_at": payload.get("verified_at"),
    }


# ---------------------------------------------------------------------------
# Custom rules (D82)
# ---------------------------------------------------------------------------
def validate_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    kind = rule.get("kind")
    if kind not in RULE_KINDS:
        raise QualityError(f"Unknown rule kind. One of: {', '.join(RULE_KINDS)}")

    severity = rule.get("severity", "warning")
    if severity not in SEVERITIES:
        raise QualityError(f"Unknown severity. One of: {', '.join(SEVERITIES)}")

    value = rule.get("value")
    if kind in ("min_words", "max_words"):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise QualityError(f"{kind} needs a number.")
        if value < 0:
            raise QualityError(f"{kind} cannot be negative.")
    else:
        value = str(value or "").strip()
        if not value:
            raise QualityError(f"{kind} needs a value.")
        if kind == "regex_absent":
            try:
                re.compile(value)
            except re.error as e:
                raise QualityError(f"That is not a valid regular expression: {e}")

    return {"kind": kind, "value": value, "severity": severity,
            "label": str(rule.get("label", "")).strip()[:200]}


def _apply_rule(rule: Dict[str, Any], content: str) -> Optional[Dict[str, Any]]:
    kind, value = rule["kind"], rule["value"]
    lowered = content.lower()
    words = len(content.split())

    failed, detail = False, ""
    if kind == "required_section":
        headings = [m.group(2).strip().lower()
                    for m in re.finditer(r"^(#{1,6})\s+(.*)$", content, re.M)]
        failed = str(value).lower() not in headings
        detail = f"No section titled “{value}”."
    elif kind == "required_phrase":
        failed = str(value).lower() not in lowered
        detail = f"Does not mention “{value}”."
    elif kind == "forbidden_phrase":
        failed = str(value).lower() in lowered
        detail = f"Contains “{value}”."
    elif kind == "min_words":
        failed = words < value
        detail = f"{words} words, needs at least {value}."
    elif kind == "max_words":
        failed = words > value
        detail = f"{words} words, limit is {value}."
    elif kind == "regex_absent":
        failed = re.search(str(value), content) is not None
        detail = f"Matches the pattern /{value}/."

    if not failed:
        return None
    return {"kind": kind, "severity": rule["severity"],
            "label": rule.get("label") or kind.replace("_", " ").title(),
            "detail": detail}


def run_custom_rules(db: DatabaseManager, node_id: str,
                     rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    validated = [validate_rule(r) for r in rules]
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise QualityError("Document not found.")
        content = node.content or ""

    failures = [f for f in (_apply_rule(r, content) for r in validated) if f]
    errors = sum(1 for f in failures if f["severity"] == "error")
    return {
        "node_id": node_id, "rules_run": len(validated),
        "failures": failures, "passed": errors == 0,
        "by_severity": {sev: sum(1 for f in failures if f["severity"] == sev)
                        for sev in SEVERITIES},
    }


def save_rules(db: DatabaseManager, project_id: str,
               rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rules live in settings, so they travel with the project's config."""
    validated = [validate_rule(r) for r in rules]
    from src.settings import get_settings, get_settings_store

    all_rules = dict(getattr(get_settings(), "custom_rules", None) or {})
    all_rules[project_id] = validated
    get_settings_store().update(custom_rules=all_rules)
    return {"rules": validated, "count": len(validated)}


def get_rules(project_id: str) -> List[Dict[str, Any]]:
    from src.settings import get_settings

    return list((getattr(get_settings(), "custom_rules", None) or {}).get(project_id, []))


# ---------------------------------------------------------------------------
# Citation / claim checking (D83)
# ---------------------------------------------------------------------------
# Sentences shaped like factual assertions — numbers, superlatives, and
# research-flavoured verbs — are the ones worth asking for a source.
CLAIM_PATTERNS = [
    (r"\b\d+(\.\d+)?\s*%", "a percentage"),
    (r"\b(studies|research|survey|report)s?\s+(show|shows|found|indicate)", "a research claim"),
    (r"\b(always|never|all|none|every|guaranteed|proven)\b", "an absolute claim"),
    (r"\b(fastest|best|cheapest|largest|leading|most popular)\b", "a superlative"),
    (r"\$\s?\d[\d,]*", "a monetary figure"),
    (r"\b\d{4}\b.*\b(revenue|users|customers|growth|market)\b", "a market figure"),
]

CITATION_RE = re.compile(r"(\[\d+\]|\[\[[^\]]+\]\]|https?://\S+|\(source:[^)]+\))", re.I)


def _sentences(text: str) -> List[str]:
    cleaned = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    cleaned = re.sub(r"^#{1,6}\s+.*$", " ", cleaned, flags=re.M)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def check_citations(db: DatabaseManager, node_id: str) -> Dict[str, Any]:
    """Find assertion-shaped sentences that carry no source.

    Deliberately a *prompt*, not a verdict: it cannot know whether a claim is
    true, only whether the document offers anywhere to check. Flagging is
    therefore framed as "this wants a source", never "this is wrong".
    """
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise QualityError("Document not found.")
        content, title = node.content or "", node.title

    flagged = []
    for sentence in _sentences(content):
        reasons = [label for pattern, label in CLAIM_PATTERNS
                   if re.search(pattern, sentence, re.I)]
        if not reasons:
            continue
        has_citation = bool(CITATION_RE.search(sentence))
        if not has_citation:
            flagged.append({
                "sentence": sentence[:300],
                "reasons": reasons,
                "suggestion": "Add a source, or soften the claim.",
            })

    total_claims = sum(1 for s_ in _sentences(content)
                       if any(re.search(p, s_, re.I) for p, _ in CLAIM_PATTERNS))
    cited = total_claims - len(flagged)

    return {
        "node_id": node_id, "title": title,
        "claims_found": total_claims,
        "cited": cited,
        "uncited": flagged,
        "uncited_count": len(flagged),
        "coverage": round(100.0 * cited / total_claims, 1) if total_claims else 100.0,
        "note": ("This checks whether a claim offers somewhere to verify it, "
                 "not whether the claim is true."),
    }


# ---------------------------------------------------------------------------
# Auto-fix (D85)
# ---------------------------------------------------------------------------
def _fix_strip_placeholders(text: str) -> str:
    out = []
    for line in text.split("\n"):
        if re.fullmatch(r"\s*[-*+]?\s*(TODO|TBD|FIXME|XXX)\b.*", line, re.I):
            continue
        out.append(line)
    return "\n".join(out)


def _fix_collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def _fix_normalise_headings(text: str) -> str:
    """Ensure a blank line after each heading, which most renderers require."""
    lines, out = text.split("\n"), []
    for i, line in enumerate(lines):
        out.append(line)
        if re.match(r"^#{1,6}\s+\S", line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.strip():
                out.append("")
    return "\n".join(out)


def _fix_trim_trailing_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _fix_list_markers(text: str) -> str:
    """Normalise * and + bullets to -, which is the dominant convention."""
    return re.sub(r"^(\s*)[*+](\s+)", r"\1-\2", text, flags=re.M)


FIXES = {
    "strip_placeholders": (_fix_strip_placeholders, "Remove TODO/TBD/FIXME lines"),
    "collapse_blank_lines": (_fix_collapse_blank_lines, "Collapse runs of blank lines"),
    "normalise_headings": (_fix_normalise_headings, "Add a blank line after headings"),
    "trim_trailing_whitespace": (_fix_trim_trailing_whitespace, "Trim trailing whitespace"),
    "fix_list_markers": (_fix_list_markers, "Normalise bullet markers to -"),
}


def _fix_for_issue(issue: Dict[str, Any]) -> Optional[str]:
    message = (issue.get("message") or "").lower()
    if any(m in message for m in ("todo", "tbd", "placeholder", "fixme")):
        return "strip_placeholders"
    if "whitespace" in message or "blank line" in message:
        return "collapse_blank_lines"
    if "heading" in message and "format" in message:
        return "normalise_headings"
    return None


def suggest_fixes(db: DatabaseManager, node_id: str) -> Dict[str, Any]:
    """Every fix that would actually change this document, with a preview."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise QualityError("Document not found.")
        content = node.content or ""

    suggestions = []
    for slug, (fn, label) in FIXES.items():
        fixed = fn(content)
        if fixed == content:
            continue
        suggestions.append({
            "kind": slug, "label": label,
            "chars_before": len(content), "chars_after": len(fixed),
            "lines_removed": content.count("\n") - fixed.count("\n"),
            "preview": fixed[:800],
        })

    return {"node_id": node_id, "suggestions": suggestions,
            "count": len(suggestions)}


def apply_fixes(db: DatabaseManager, node_id: str,
                kinds: List[str]) -> Dict[str, Any]:
    """Apply chosen fixes through the normal save path, so each is snapshotted."""
    unknown = [k for k in kinds if k not in FIXES]
    if unknown:
        raise QualityError(f"Unknown fixes: {', '.join(unknown)}")
    if not kinds:
        raise QualityError("Choose at least one fix.")

    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise QualityError("Document not found.")
        content = node.content or ""

    updated = content
    for kind in kinds:
        updated = FIXES[kind][0](updated)

    if updated == content:
        return {"changed": False, "applied": [], "node_id": node_id}

    from src.services import document_service as docs

    doc = docs.save_content(db, node_id, updated, reason="edit",
                            note=f"auto-fix: {', '.join(kinds)}")
    return {"changed": True, "applied": kinds, "document": doc}
