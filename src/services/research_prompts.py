"""
Prompts for the Research stage.

Pipeline shape — plan → queries → gather → distil learnings → review → synthesize
— follows u14app/deep-research (MIT, © 2024 u14app). The prompt text here is
rewritten for Dobby's purpose: this is not a general research agent producing a
report, it is a product research pass whose output has to feed the backlog.

The concrete departures from the upstream design:

* **Five fixed tracks** instead of a model-invented section list. A founder's
  questions are known in advance — what to build, who wants it, who else is
  doing it, how it makes money, whether we can build it — and fixing them makes
  the output comparable between briefs and mappable onto the backlog.
* **Findings are structured, not prose.** Each track emits discrete learnings so
  a single finding can be promoted into a feature.
* **Grounding is explicit.** When no search provider is configured the model is
  told to say so and flag speculation, rather than writing with borrowed
  confidence.
"""

from __future__ import annotations

from typing import Dict, List

TRACK_BRIEFS: Dict[str, str] = {
    "product": (
        "What should be built. The jobs users are hiring this for, the "
        "workflows it has to fit into, the capabilities that are table stakes "
        "versus the ones that would differentiate, and what users of adjacent "
        "tools complain about today."
    ),
    "market": (
        "Who wants it and how many. Named segments with their characteristics, "
        "rough size and growth where it can be estimated, buying triggers, "
        "budget-holder versus end-user, and the trends moving demand."
    ),
    "competition": (
        "Who else is doing this. Named products and companies, what each is "
        "good and bad at, how they price, where they are strong, and the gap "
        "a new entrant could occupy."
    ),
    "business": (
        "How it makes money. Plausible pricing and packaging, the revenue "
        "model, unit economics and cost drivers, acquisition channels, and "
        "what has to be true for it to work."
    ),
    "technical": (
        "Whether it can be built. Architecture options, key dependencies and "
        "their maturity, the hard problems, data and privacy constraints, and "
        "the biggest technical risks."
    ),
}

SYSTEM = (
    "You are a product research analyst. You are precise, concrete, and "
    "sceptical.\n"
    "- Name real entities: companies, products, tools, standards, numbers, dates.\n"
    "- Prefer a specific claim you can defend to a general one that sounds safe.\n"
    "- When you are inferring or estimating rather than reporting, say so "
    "explicitly in that sentence.\n"
    "- Never invent a statistic, a source, or a URL. If you do not know a "
    "number, say what it depends on instead.\n"
    "- The reader is an expert. Do not pad, hedge, or restate the question."
)

UNGROUNDED_NOTE = (
    "IMPORTANT: no web search is configured, so you are working from your own "
    "training knowledge only. It may be out of date and you cannot cite "
    "sources. Write what you know, mark anything time-sensitive as needing "
    "verification, and never present a recalled figure as a current fact."
)

GROUNDED_NOTE = (
    "Ground every claim you can in the supplied search results. Where the "
    "results do not cover something and you fall back on your own knowledge, "
    "mark that sentence as unverified."
)


def plan_prompt(topic: str, context: str, project_context: str) -> str:
    """Ask for the angle each track should take on this specific topic."""
    tracks = "\n".join(f"- **{k}**: {v}" for k, v in TRACK_BRIEFS.items())
    extra = f"\nWhat the user told us:\n{context}\n" if context.strip() else ""
    proj = f"\nThe project this is for:\n{project_context}\n" if project_context.strip() else ""
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\n{extra}{proj}\n"
        "Write a short research plan covering these five tracks:\n"
        f"{tracks}\n\n"
        "For each track, give two or three sentences on what specifically needs "
        "answering *for this topic* — not the generic description above. Be "
        "concrete about which questions matter here and which do not.\n\n"
        "Use `## Product`, `## Market`, `## Competition`, `## Business model`, "
        "`## Technical feasibility` as the headings, in that order. No preamble."
    )


def queries_prompt(topic: str, track: str, plan: str, count: int = 3) -> str:
    """Search queries for one track. Plain list — no JSON, easier for small models."""
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\n\n"
        f"RESEARCH PLAN:\n{plan}\n\n"
        f"You are researching the **{track}** track.\n\n"
        f"Write exactly {count} web search queries that would find real evidence "
        f"for this track. Rules:\n"
        "- Each query must be different from the others in what it would return.\n"
        "- Write them as someone would actually type into a search engine — "
        "keywords, not questions in full sentences.\n"
        "- No quotes, no numbering, no commentary.\n"
        f"- Output exactly {count} lines, one query per line, nothing else."
    )


def learnings_prompt(topic: str, track: str, focus: str,
                     evidence: str, grounded: bool) -> str:
    """Distil discrete findings — the unit that can become a backlog item."""
    note = GROUNDED_NOTE if grounded else UNGROUNDED_NOTE
    ev = f"\nSEARCH RESULTS:\n{evidence}\n" if grounded else ""
    return (
        f"{SYSTEM}\n\n{note}\n\n"
        f"TOPIC: {topic}\n\n"
        f"TRACK: {track}\n"
        f"WHAT THIS TRACK NEEDS TO ANSWER:\n{focus}\n"
        f"{ev}\n"
        "Write 5 to 8 findings for this track. Rules:\n"
        "- One finding per line, starting with `- `.\n"
        "- Each finding is a complete, self-contained claim someone could act "
        "on or check. Not a topic label.\n"
        "- Include names, numbers, and dates wherever you legitimately can.\n"
        "- No two findings may make the same point.\n"
        "- Prefix any finding that is inference rather than fact with "
        "`[inferred]`.\n"
        "- Output only the findings. No heading, no preamble, no closing."
    )


def review_prompt(topic: str, track: str, focus: str, learnings: List[str]) -> str:
    """Decide whether this track needs another search round."""
    found = "\n".join(f"- {l}" for l in learnings)
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\nTRACK: {track}\n"
        f"WHAT THIS TRACK NEEDS TO ANSWER:\n{focus}\n\n"
        f"FINDINGS SO FAR:\n{found}\n\n"
        "Is anything important still missing?\n"
        "- If the track is adequately covered, output exactly: COMPLETE\n"
        "- If not, output up to 2 further search queries, one per line, that "
        "would close the biggest gaps. Keywords only, no commentary.\n"
        "Output either COMPLETE or the queries. Nothing else."
    )


def synthesis_prompt(topic: str, track: str, focus: str,
                     learnings: List[str], grounded: bool) -> str:
    """Turn findings into the track's written section."""
    found = "\n".join(f"- {l}" for l in learnings)
    caveat = "" if grounded else (
        "\nOpen with one italic line noting this section is from model knowledge "
        "without web verification.\n"
    )
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\n"
        f"TRACK: {track}\n"
        f"WHAT THIS TRACK NEEDS TO ANSWER:\n{focus}\n\n"
        f"FINDINGS:\n{found}\n{caveat}\n"
        "Write this track's section of the research brief.\n"
        "- Start at `## ` heading level; the track name is the heading.\n"
        "- Organise the findings into a short argument, do not just relist them.\n"
        "- Use a table where you are comparing things (segments, competitors, "
        "pricing tiers). Markdown tables only.\n"
        "- End with `### So what` — two or three bullets on what this means for "
        "someone deciding whether and how to build this.\n"
        "- Keep it under 400 words. Density over length."
    )


def summary_prompt(topic: str, sections: str) -> str:
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\n\n"
        f"RESEARCH:\n{sections}\n\n"
        "Write the executive summary.\n"
        "- Lead with the single most decision-relevant conclusion.\n"
        "- Then 3 to 5 bullets: the opportunity, the main risk, the "
        "differentiator, and what to validate next.\n"
        "- Under 200 words. No heading — the body only."
    )


def features_prompt(topic: str, sections: str, count: int = 8) -> str:
    """The bridge into Create: research findings become candidate backlog items."""
    return (
        f"{SYSTEM}\n\n"
        f"TOPIC: {topic}\n\n"
        f"RESEARCH:\n{sections}\n\n"
        f"Propose up to {count} concrete product features this research "
        "justifies. Each must trace back to something in the research above.\n"
        "Format — one feature per line, exactly:\n"
        "`Title | one-sentence description | impact 1-10 | effort 1-10 | risk 1-10`\n"
        "- Title under 8 words, naming a capability, not a theme.\n"
        "- Score impact on user value, effort on build cost, risk on uncertainty.\n"
        "- Output only those lines. No heading, no numbering, no commentary."
    )
