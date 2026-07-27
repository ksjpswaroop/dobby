"""
Changelog, PDF, and offline bundles (100-Day Roadmap: D66, D67, D68, D69).

All four are *outputs* — things that leave Dobby and get read somewhere else,
so each is self-contained by construction:

* The **static bundle** (D69) and **docs site** (D67) inline every stylesheet
  and resolve every internal link to a local file. Opened from a USB stick
  with no network, they render identically.
* The **PDF** (D68) is generated with ReportLab rather than by driving a
  headless browser, so it needs no Chrome and produces the same bytes on any
  machine.
* The **changelog** (D66) is built from real status transitions and version
  history — the things that actually happened — not from a model's summary of
  them.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.db.document_models import DocumentMeta, NodeVersion
from src.db.planning_models import FeatureStatusChange
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()

SITE_CSS = """
:root { --ink:#1a1523; --muted:#6b7280; --line:#e5e7eb; --bg:#faf9fc;
        --surface:#fff; --brand:#7c3aed; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#ede9f5; --muted:#a1a1aa; --line:#2a2532; --bg:#141019;
          --surface:#1c1724; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; }
.wrap { max-width:1100px; margin:0 auto; padding:32px 20px 64px; }
.layout { display:grid; grid-template-columns:240px 1fr; gap:32px; }
@media (max-width:820px){ .layout{ grid-template-columns:1fr; } }
nav { position:sticky; top:24px; align-self:start; }
nav a { display:block; padding:6px 10px; border-radius:8px; color:var(--muted);
        text-decoration:none; font-size:13px; }
nav a:hover { background:var(--surface); color:var(--ink); }
article { background:var(--surface); border:1px solid var(--line);
          border-radius:16px; padding:28px 32px; margin-bottom:20px; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:-.02em; }
h2 { font-size:20px; margin:28px 0 8px; }
h3 { font-size:16px; margin:22px 0 6px; }
p, li { color:var(--ink); }
code { background:var(--bg); border:1px solid var(--line); border-radius:5px;
       padding:1px 5px; font-size:.9em; }
pre { background:var(--bg); border:1px solid var(--line); border-radius:12px;
      padding:14px; overflow-x:auto; }
pre code { border:0; padding:0; }
.meta { color:var(--muted); font-size:12px; margin-bottom:18px; }
.badge { display:inline-block; background:var(--brand); color:#fff;
         border-radius:20px; padding:2px 10px; font-size:11px; }
table { border-collapse:collapse; width:100%; overflow-x:auto; display:block; }
td, th { border:1px solid var(--line); padding:6px 10px; text-align:left; }
footer { color:var(--muted); font-size:12px; text-align:center; padding-top:24px; }
"""


class PublishError(Exception):
    pass


# ---------------------------------------------------------------------------
# Markdown -> HTML (escaping first, same rule as the in-app preview)
# ---------------------------------------------------------------------------
def markdown_to_html(source: str) -> str:
    """A small renderer that escapes before formatting.

    Document content can come from a local model or an imported archive, and
    these bundles get opened in a browser — so an unescaped `<script>` here
    would be a stored-XSS hole shipped on a USB stick.
    """
    lines = (source or "").split("\n")
    out: List[str] = []
    in_fence = False
    fence_buf: List[str] = []
    list_type: Optional[str] = None

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    def inline(text: str) -> str:
        escaped = html.escape(text, quote=False)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\[\[([^\[\]]+)\]\]", r"<em>\1</em>", escaped)
        escaped = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            r'<a href="\2" rel="noopener noreferrer">\1</a>', escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1<em>\2</em>", escaped)
        return escaped

    for raw in lines:
        if re.match(r"^\s*(```|~~~)", raw):
            if in_fence:
                out.append(f"<pre><code>{html.escape(chr(10).join(fence_buf))}</code></pre>")
                fence_buf, in_fence = [], False
            else:
                close_list()
                in_fence = True
            continue
        if in_fence:
            fence_buf.append(raw)
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 1, 6)  # h1 is the page title
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^\s*[-*+]\s+(.*)$", raw)
        numbered = re.match(r"^\s*\d+\.\s+(.*)$", raw)
        if bullet or numbered:
            want = "ul" if bullet else "ol"
            if list_type != want:
                close_list()
                list_type = want
                out.append(f"<{want}>")
            out.append(f"<li>{inline((bullet or numbered).group(1))}</li>")
            continue

        if not raw.strip():
            close_list()
            continue

        close_list()
        out.append(f"<p>{inline(raw)}</p>")

    if in_fence and fence_buf:
        out.append(f"<pre><code>{html.escape(chr(10).join(fence_buf))}</code></pre>")
    close_list()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Changelog (D66)
# ---------------------------------------------------------------------------
def changelog(db: DatabaseManager, project_id: str,
              days: int = 30) -> Dict[str, Any]:
    """Built from what actually happened, not from a summary of it."""
    since = datetime.utcnow() - timedelta(days=days)

    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise PublishError("Project not found.")

        completed_changes = (s.query(FeatureStatusChange)
                             .filter(FeatureStatusChange.project_id == project_id,
                                     FeatureStatusChange.to_column == "done",
                                     FeatureStatusChange.created_at >= since)
                             .order_by(FeatureStatusChange.created_at).all())
        titles = {f.id: f.title for f in s.query(FeatureBacklog)
                  .filter(FeatureBacklog.project_id == project_id).all()}

        seen, shipped = set(), []
        for c in completed_changes:
            if c.feature_id in seen:
                continue
            seen.add(c.feature_id)
            shipped.append({"title": titles.get(c.feature_id, "(removed)"),
                            "date": c.created_at.date().isoformat()
                            if c.created_at else None})

        approved = (s.query(DocumentMeta, Node)
                    .join(Node, Node.id == DocumentMeta.node_id)
                    .filter(DocumentMeta.project_id == project_id,
                            DocumentMeta.status == "approved",
                            DocumentMeta.status_changed_at >= since).all())
        approved_docs = [{"title": n.title, "node_id": n.id,
                          "date": m.status_changed_at.date().isoformat()
                          if m.status_changed_at else None}
                         for m, n in approved]

        node_ids = [n.id for n in s.query(Node)
                    .filter(Node.project_id == project_id).all()]
        revisions = 0
        if node_ids:
            revisions = (s.query(NodeVersion)
                         .filter(NodeVersion.node_id.in_(node_ids),
                                 NodeVersion.created_at >= since).count())

    lines = [f"# {project.name} — what changed",
             f"\n_Covering the last {days} days._\n"]
    if shipped:
        lines.append("## Shipped\n")
        lines += [f"- {s_['title']} ({s_['date']})" for s_ in shipped]
        lines.append("")
    if approved_docs:
        lines.append("## Documents approved\n")
        lines += [f"- {d['title']} ({d['date']})" for d in approved_docs]
        lines.append("")
    if revisions:
        lines.append(f"## Revisions\n\n{revisions} document revisions were recorded.\n")
    if not (shipped or approved_docs or revisions):
        lines.append("_Nothing was completed or approved in this window._\n")

    return {
        "markdown": "\n".join(lines),
        "shipped": shipped, "approved": approved_docs, "revisions": revisions,
        "period_days": days,
        "basis": "Built from real status transitions and version history.",
    }


# ---------------------------------------------------------------------------
# Static bundle & docs site (D67, D69)
# ---------------------------------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "doc"


def _page(title: str, body_html: str, nav_html: str, subtitle: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>{SITE_CSS}</style>
</head><body><div class="wrap"><div class="layout">
<nav>{nav_html}</nav>
<main>
<article>
<h1>{html.escape(title)}</h1>
{f'<p class="meta">{html.escape(subtitle)}</p>' if subtitle else ''}
{body_html}
</article>
<footer>Generated locally by Dobby · works offline</footer>
</main>
</div></div></body></html>"""


def build_site(db: DatabaseManager, project_id: str) -> Dict[str, str]:
    """Every page as {filename: html}. Fully self-contained and link-resolved."""
    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise PublishError("Project not found.")
        nodes = (s.query(Node).filter(Node.project_id == project_id)
                 .order_by(Node.node_type, Node.title).all())
        docs = [{"id": n.id, "title": n.title or "Untitled",
                 "node_type": n.node_type, "content": n.content or ""}
                for n in nodes]

    if not docs:
        raise PublishError("This project has no documents to publish.")

    # Unique filenames, since two documents can share a title.
    used: Dict[str, int] = {}
    for d in docs:
        base = _slug(d["title"])
        used[base] = used.get(base, 0) + 1
        d["file"] = f"{base}.html" if used[base] == 1 else f"{base}-{used[base]}.html"

    nav_html = ('<a href="index.html">Overview</a>'
                + "".join(f'<a href="{d["file"]}">{html.escape(d["title"])}</a>'
                          for d in docs))

    files: Dict[str, str] = {}

    index_body = [f'<p>{len(docs)} documents.</p><ul>']
    for d in docs:
        words = len(d["content"].split())
        index_body.append(
            f'<li><a href="{d["file"]}">{html.escape(d["title"])}</a> '
            f'<span class="meta">— {html.escape(d["node_type"])}, {words} words</span></li>')
    index_body.append("</ul>")
    files["index.html"] = _page(project.name, "\n".join(index_body), nav_html,
                                project.description or "")

    by_title = {d["title"].lower(): d["file"] for d in docs}
    for d in docs:
        body = markdown_to_html(d["content"])
        # Resolve [[wiki links]] to real local files so the bundle is navigable
        # offline; unresolved ones stay as plain emphasis rather than dead links.
        def repl(m):
            target = by_title.get(m.group(1).lower())
            label = html.escape(m.group(1))
            return f'<a href="{target}">{label}</a>' if target else f"<em>{label}</em>"

        body = re.sub(r"<em>([^<]+)</em>", lambda m: repl(m), body)
        files[d["file"]] = _page(d["title"], body, nav_html,
                                 f"{d['node_type']} · {len(d['content'].split())} words")

    return files


def build_bundle(db: DatabaseManager, project_id: str) -> bytes:
    """The site as a single .zip — the offline-bundle deliverable."""
    files = build_site(db, project_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        z.writestr("README.txt",
                   "Open index.html in any browser. No network required.\n"
                   "Generated locally by Dobby.\n")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF (D68)
# ---------------------------------------------------------------------------
def build_pdf(db: DatabaseManager, project_id: str,
              node_id: Optional[str] = None) -> bytes:
    """Render to PDF with ReportLab — no headless browser, no network."""
    try:
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer,
        )
    except ImportError:
        raise PublishError(
            "PDF export needs reportlab. Install it with: pip install reportlab")

    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise PublishError("Project not found.")
        q = s.query(Node).filter(Node.project_id == project_id)
        if node_id:
            q = q.filter(Node.id == node_id)
        nodes = q.order_by(Node.node_type, Node.title).all()
        docs = [{"title": n.title or "Untitled", "node_type": n.node_type,
                 "content": n.content or ""} for n in nodes]

    if not docs:
        raise PublishError("Nothing to export.")

    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=10, leading=14.5, spaceAfter=6, alignment=TA_LEFT)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=18, spaceAfter=10)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                        fontSize=13, spaceBefore=12, spaceAfter=6)
    meta = ParagraphStyle("Meta", parent=body, textColor="#6b7280", fontSize=9)
    mono = ParagraphStyle("Mono", parent=body, fontName="Courier", fontSize=8.5,
                          leading=11)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=project.name,
                            author="Dobby", leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)

    def esc(text: str) -> str:
        # ReportLab paragraphs accept a mini-HTML; unescaped user text would
        # otherwise break the parser on a stray "&" or "<".
        return html.escape(text, quote=False)

    flow: List[Any] = []
    for i, d in enumerate(docs):
        if i:
            flow.append(PageBreak())
        flow.append(Paragraph(esc(d["title"]), h1))
        flow.append(Paragraph(esc(d["node_type"]), meta))
        flow.append(Spacer(1, 6))

        in_fence, fence_buf = False, []
        for line in d["content"].split("\n"):
            if re.match(r"^\s*(```|~~~)", line):
                if in_fence:
                    flow.append(Preformatted("\n".join(fence_buf), mono))
                    fence_buf, in_fence = [], False
                else:
                    in_fence = True
                continue
            if in_fence:
                fence_buf.append(line)
                continue

            heading = re.match(r"^(#{1,6})\s+(.*)$", line)
            if heading:
                flow.append(Paragraph(esc(heading.group(2)), h2))
                continue
            bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
            if bullet:
                flow.append(Paragraph("• " + esc(bullet.group(1)), body))
                continue
            if line.strip():
                clean = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc(line))
                flow.append(Paragraph(clean, body))

        if in_fence and fence_buf:
            flow.append(Preformatted("\n".join(fence_buf), mono))

    doc.build(flow)
    return buf.getvalue()
