"""
Project and global copilot (100-Day Roadmap, Days 21 & 26).

Retrieval is deliberately lexical (scored term overlap over node titles and
content) rather than embedding-based. Two reasons: it works with zero setup
on a machine that may have no embedding model pulled, and it is deterministic
— the same question retrieves the same documents, which matters a great deal
when the answer carries citations the user is meant to trust.

Every assistant turn stores the nodes it was grounded on. An answer whose
claims cannot be traced back to a document the user owns is worse than no
answer, so the prompt instructs the model to say it does not know rather than
fill the gap, and the UI shows the citations alongside.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.db.copilot_models import ChatMessage, ChatThread
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project
from src.services import model_routing

logger = structlog.get_logger()

TOP_K = 6
SNIPPET_CHARS = 1200
MAX_HISTORY = 8

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "for", "on", "at",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these",
    "those", "with", "as", "by", "from", "what", "which", "who", "how", "why",
    "do", "does", "did", "i", "we", "you", "my", "our", "me", "any", "all",
}


class CopilotError(Exception):
    pass


def _terms(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOPWORDS]


def _score(question_terms: List[str], title: str, content: str) -> float:
    """Title matches weigh more — a document *about* the topic beats one that
    merely mentions it in passing."""
    if not question_terms:
        return 0.0
    title_l = (title or "").lower()
    content_l = (content or "").lower()
    score = 0.0
    for t in set(question_terms):
        if t in title_l:
            score += 3.0
        c = content_l.count(t)
        if c:
            score += min(c, 5) * 0.5
    return score


def retrieve(db: DatabaseManager, question: str,
             project_id: Optional[str] = None, k: int = TOP_K) -> List[Dict[str, Any]]:
    """Find the nodes most relevant to a question, project-scoped or global."""
    terms = _terms(question)
    with db.get_session() as s:
        q = s.query(Node)
        if project_id:
            q = q.filter(Node.project_id == project_id)
        nodes = q.all()

        project_names = {p.id: p.name for p in s.query(Project).all()}

        scored = []
        for n in nodes:
            sc = _score(terms, n.title, n.content or "")
            if sc > 0:
                scored.append((sc, n))
        scored.sort(key=lambda x: (-x[0], x[1].title or ""))

        out = []
        for sc, n in scored[:k]:
            content = n.content or ""
            # Window the snippet around the first matching term so the model
            # sees the relevant passage, not just the document's opening.
            start = 0
            for t in terms:
                idx = content.lower().find(t)
                if idx > 0:
                    start = max(0, idx - 200)
                    break
            out.append({
                "node_id": n.id,
                "title": n.title,
                "node_type": n.node_type,
                "project_id": n.project_id,
                "project_name": project_names.get(n.project_id, ""),
                "score": round(sc, 2),
                "snippet": content[start:start + SNIPPET_CHARS],
            })
        return out


def _backlog_context(db: DatabaseManager, project_id: str, limit: int = 8) -> str:
    with db.get_session() as s:
        rows = (s.query(FeatureBacklog)
                .filter(FeatureBacklog.project_id == project_id)
                .order_by(FeatureBacklog.pareto_score.desc()).limit(limit).all())
        if not rows:
            return ""
        lines = [f"- {f.title} (pareto {f.pareto_score:.2f}, {f.status})" for f in rows]
        return "Top backlog items:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------
def create_thread(db: DatabaseManager, project_id: Optional[str] = None,
                  title: str = "New chat") -> Dict[str, Any]:
    with db.get_session() as s:
        t = ChatThread(id=str(uuid.uuid4()), project_id=project_id,
                       title=title[:200], scope="project" if project_id else "global")
        s.add(t)
        s.commit()
        return _thread_dict(t)


def _thread_dict(t: ChatThread) -> Dict[str, Any]:
    return {
        "id": t.id, "project_id": t.project_id, "title": t.title, "scope": t.scope,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def list_threads(db: DatabaseManager, project_id: Optional[str] = None,
                 scope: str = "project") -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(ChatThread).filter(ChatThread.scope == scope)
        if scope == "project" and project_id:
            q = q.filter(ChatThread.project_id == project_id)
        return [_thread_dict(t) for t in q.order_by(ChatThread.updated_at.desc()).all()]


def _message_dict(m: ChatMessage) -> Dict[str, Any]:
    return {
        "id": m.id, "role": m.role, "content": m.content,
        "citations": m.citations or [], "model": m.model, "latency_ms": m.latency_ms,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def list_messages(db: DatabaseManager, thread_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(ChatMessage).filter(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.created_at).all())
        return [_message_dict(m) for m in rows]


def delete_thread(db: DatabaseManager, thread_id: str) -> bool:
    with db.get_session() as s:
        t = s.get(ChatThread, thread_id)
        if not t:
            return False
        for m in s.query(ChatMessage).filter(ChatMessage.thread_id == thread_id).all():
            s.delete(m)
        s.flush()
        s.delete(t)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------
async def ask(db: DatabaseManager, thread_id: str, question: str,
              model: str = "") -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise CopilotError("Ask something first.")

    with db.get_session() as s:
        thread = s.get(ChatThread, thread_id)
        if not thread:
            raise CopilotError("Chat thread not found.")
        project_id = thread.project_id
        scope = thread.scope
        history = (s.query(ChatMessage)
                   .filter(ChatMessage.thread_id == thread_id)
                   .order_by(ChatMessage.created_at.desc())
                   .limit(MAX_HISTORY).all())
        history = list(reversed(history))
        first_turn = len(history) == 0

    hits = retrieve(db, question, project_id if scope == "project" else None)

    if hits:
        context = "\n\n".join(
            f"[{i + 1}] {h['title']}"
            + (f" (project: {h['project_name']})" if scope == "global" else "")
            + f"\n{h['snippet']}"
            for i, h in enumerate(hits)
        )
    else:
        context = "(no matching documents found)"

    extra = _backlog_context(db, project_id) if scope == "project" and project_id else ""

    convo = "\n".join(f"{m.role}: {m.content}" for m in history[-4:])

    prompt = (
        f"You are answering a question about {'this project' if scope == 'project' else 'the user''s projects'}.\n\n"
        f"Documents retrieved:\n---\n{context}\n---\n"
        + (f"\n{extra}\n" if extra else "")
        + (f"\nEarlier in this conversation:\n{convo}\n" if convo else "")
        + f"\nQuestion: {question}\n\n"
        "Answer using ONLY the documents above. Cite them inline as [1], [2] where used. "
        "If the documents do not contain the answer, say so plainly — do not invent details. "
        "Be concise."
    )

    started = time.monotonic()
    try:
        answer = await model_routing.call(
            db, "chat", prompt, model=model, project_id=project_id,
            max_tokens=1200, temperature=0.3,
        )
    except Exception as e:
        raise CopilotError(f"The model could not be reached: {e}")

    latency_ms = int((time.monotonic() - started) * 1000)
    citations = [
        {"index": i + 1, "node_id": h["node_id"], "title": h["title"],
         "project_id": h["project_id"], "score": h["score"]}
        for i, h in enumerate(hits)
    ]

    with db.get_session() as s:
        s.add(ChatMessage(id=str(uuid.uuid4()), thread_id=thread_id,
                          role="user", content=question))
        assistant = ChatMessage(
            id=str(uuid.uuid4()), thread_id=thread_id, role="assistant",
            content=(answer or "").strip(), citations=citations,
            model=model_routing.resolve("chat", model) or "default",
            latency_ms=latency_ms,
        )
        s.add(assistant)
        t = s.get(ChatThread, thread_id)
        if t and first_turn:
            # Name the thread after the opening question — an untitled list of
            # "New chat" rows is unusable after a few days.
            t.title = question[:80]
        s.commit()
        return _message_dict(assistant)
