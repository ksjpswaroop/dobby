"""
Next-best-action suggestions (100-Day Roadmap, Day 22).

The ranking is **deterministic**. Signals come from real state — unresolved
approvals, failed verifications, untriaged captures, high-Pareto work that
has not started — and each carries a fixed weight. The local model is used
only to phrase the top suggestion more naturally, and if it is unavailable
the deterministic reason is shown verbatim.

That split matters: a recommendation engine that hallucinates its reasoning
is one the user learns to ignore. Here the *why* is always literally true,
because it is computed, and only the wording is generated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.db.document_models import Comment, DocumentMeta
from src.db.idea_models import Idea
from src.db.inbox_models import Ask
from src.db.run_models import Run
from src.db.schema import DatabaseManager, FeatureBacklog, Node

# Higher weight = more urgent. Ordering these is the actual product decision:
# something blocking (an approval you must answer) outranks something merely
# valuable (a high-scoring feature you could start).
WEIGHTS = {
    "pending_ask": 100,
    # An overdue decision outranks a failed run: everything waiting behind an
    # untaken fork is stalled, whereas a failed run has usually stalled one
    # thing. Listed in descending order so the ranking is readable here.
    "overdue_decision": 95,
    "failed_run": 90,
    "failed_verification": 85,
    "decision_due_soon": 65,
    "decision_blocking": 62,
    "untriaged_ideas": 60,
    "unresolved_comments": 55,
    "review_waiting": 50,
    "high_pareto_unstarted": 40,
    "missing_documents": 30,
    "empty_project": 20,
}


def _suggest(kind: str, title: str, reason: str, route: str,
             count: int = 1) -> Dict[str, Any]:
    return {
        "kind": kind, "title": title, "reason": reason, "route": route,
        "count": count, "weight": WEIGHTS.get(kind, 0),
    }


def compute(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    """Every applicable suggestion, most urgent first."""
    out: List[Dict[str, Any]] = []

    with db.get_session() as s:
        pending = s.query(Ask).filter(Ask.project_id == project_id,
                                      Ask.state == "pending").count()
        if pending:
            out.append(_suggest(
                "pending_ask",
                f"Answer {pending} approval{'s' if pending > 1 else ''}",
                "Work is parked waiting on your decision.",
                "/inbox", pending))

        failed = (s.query(Run)
                  .filter(Run.project_id == project_id, Run.status == "failed")
                  .count())
        if failed:
            out.append(_suggest(
                "failed_run",
                f"Look at {failed} failed run{'s' if failed > 1 else ''}",
                "Something you started did not finish.",
                "/logs", failed))

    # Decisions are read through their own service so the open/overdue rules
    # live in one place rather than being re-derived here.
    from src.services import decision_service

    pending = decision_service.pending_summary(db, project_id)
    urgent = pending.get("most_urgent")
    if urgent:
        if urgent["overdue"]:
            out.append(_suggest(
                "overdue_decision", f"Decide: {urgent['title']}",
                "This was due already and work is waiting behind it."
                if urgent["blocking_count"] else "This was due already.",
                "/decisions"))
        elif urgent["due_soon"]:
            out.append(_suggest(
                "decision_due_soon", f"Decide: {urgent['title']}",
                f"Due in {urgent['days_until_due']} day"
                f"{'s' if urgent['days_until_due'] != 1 else ''}.",
                "/decisions"))
        elif urgent["blocking_count"]:
            out.append(_suggest(
                "decision_blocking", f"Decide: {urgent['title']}",
                f"{urgent['blocking_count']} piece"
                f"{'s' if urgent['blocking_count'] != 1 else ''} of work "
                "cannot start until this is settled.",
                "/decisions", urgent["blocking_count"]))

    with db.get_session() as s:
        untriaged = s.query(Idea).filter(Idea.project_id == project_id,
                                         Idea.status == "inbox").count()
        if untriaged:
            out.append(_suggest(
                "untriaged_ideas",
                f"Triage {untriaged} idea{'s' if untriaged > 1 else ''}",
                "Captured but not yet turned into anything.",
                "/ideas", untriaged))

        open_comments = (s.query(Comment)
                         .filter(Comment.project_id == project_id, Comment.resolved == 0)
                         .count())
        if open_comments:
            out.append(_suggest(
                "unresolved_comments",
                f"Resolve {open_comments} comment{'s' if open_comments > 1 else ''}",
                "Notes you left yourself are still open.",
                "/documents", open_comments))

        in_review = (s.query(DocumentMeta)
                     .filter(DocumentMeta.project_id == project_id,
                             DocumentMeta.status == "in_review")
                     .count())
        if in_review:
            out.append(_suggest(
                "review_waiting",
                f"Review {in_review} document{'s' if in_review > 1 else ''}",
                "Sent to review and waiting on a decision.",
                "/documents", in_review))

        top = (s.query(FeatureBacklog)
               .filter(FeatureBacklog.project_id == project_id,
                       FeatureBacklog.status == "backlog")
               .order_by(FeatureBacklog.pareto_score.desc()).first())
        if top:
            out.append(_suggest(
                "high_pareto_unstarted",
                f"Start: {top.title}",
                f"Highest Pareto score in the backlog ({top.pareto_score:.2f}) and not started.",
                "/backlog"))

        node_count = s.query(Node).filter(Node.project_id == project_id).count()
        feature_count = (s.query(FeatureBacklog)
                         .filter(FeatureBacklog.project_id == project_id).count())
        if node_count == 0 and feature_count == 0:
            out.append(_suggest(
                "empty_project",
                "Generate your first documents",
                "This project has no documents or backlog yet.",
                "/yolo"))
        elif feature_count and node_count < feature_count:
            gap = feature_count - node_count
            out.append(_suggest(
                "missing_documents",
                f"{gap} backlog item{'s' if gap > 1 else ''} have no documents",
                "Features are prioritized but nothing is written yet.",
                "/wizard", gap))

    out.sort(key=lambda x: -x["weight"])
    return out


async def next_best_action(db: DatabaseManager, project_id: str,
                           phrase: bool = True, model: str = "") -> Dict[str, Any]:
    """The single most valuable next step, optionally phrased by the model."""
    suggestions = compute(db, project_id)
    if not suggestions:
        return {
            "suggestion": None,
            "alternatives": [],
            "message": "Nothing needs you right now. Capture an idea or start something new.",
            "phrased_by_model": False,
        }

    top = suggestions[0]
    message = f"{top['title']} — {top['reason']}"
    phrased = False

    if phrase:
        from src.services import model_routing

        try:
            prompt = (
                "Rewrite this suggestion as one short, direct sentence to a builder "
                "starting their day. Keep the specifics and the numbers. "
                "No greeting, no emoji, no preamble.\n\n"
                f"{message}"
            )
            out = await model_routing.call(db, "chat", prompt, model=model,
                                           project_id=project_id, max_tokens=120,
                                           temperature=0.5)
            if out and out.strip():
                message = out.strip().strip('"')
                phrased = True
        except Exception:
            # Deterministic wording is a perfectly good answer; the model is
            # a nicety, never a dependency.
            pass

    return {
        "suggestion": top,
        "alternatives": suggestions[1:4],
        "message": message,
        "phrased_by_model": phrased,
    }
