"""
Generation API — wires the Wizard and YOLO pipelines to HTTP.

These endpoints were previously missing, so the desktop app's generation calls
had nothing to hit. They expose the v2 graph + generation loop:

- POST /projects/{id}/wizard/start        -> begin a guided session
- POST /wizard/{session_id}/execute       -> run the next verified step
- POST /projects/{id}/yolo/generate       -> one-shot generate all 7 artifacts
- POST /projects/{id}/yolo/accept|reject  -> finalize or discard a YOLO run
- GET  /nodes/{node_id}                    -> fetch a single node's content
"""

import asyncio
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.db.schema import DatabaseManager, Node
from src.llm.ollama_client import OllamaConnectionError
from src.pipeline.wizard import get_wizard_pipeline
from src.pipeline.yolo import get_yolo_pipeline
from src.verifiers.deterministic_verifier import get_verifier

# The 7 document types, mapping the YOLO content key -> verifier node_type.
DOC_TYPES: List[tuple[str, str]] = [
    ("feature_spec", "feature"),
    ("user_story", "user_story"),
    ("functional_analysis", "functional_analysis"),
    ("flowchart", "flowchart"),
    ("pseudocode", "pseudocode"),
    ("tdd_tests", "tdd_tests"),
    ("documentation", "documentation"),
]

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["Generation"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


# ============================================================================
# Schemas
# ============================================================================
class FeatureRequest(BaseModel):
    title: str
    description: str = ""


class WizardStepRequest(BaseModel):
    user_edit: Optional[str] = None
    force: bool = False


class AcceptRequest(BaseModel):
    feature_node_id: str


class BulkIdea(BaseModel):
    title: str
    description: str = ""


class BulkRequest(BaseModel):
    ideas: List[BulkIdea]
    concurrency: int = 3


# ============================================================================
# Wizard
# ============================================================================
@router.post("/projects/{project_id}/wizard/start")
async def wizard_start(project_id: str, req: FeatureRequest, db: DatabaseManager = Depends(get_db)):
    try:
        pipeline = await get_wizard_pipeline(db)
    except OllamaConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        session_id = await pipeline.start_wizard(project_id, req.title, req.description)
        state = pipeline.session_manager.load_wizard_state(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "feature_node_id": state.feature_id if state else "",
        }
    finally:
        await pipeline.close()


@router.post("/wizard/{session_id}/execute")
async def wizard_execute(
    session_id: str, req: WizardStepRequest, db: DatabaseManager = Depends(get_db)
):
    try:
        pipeline = await get_wizard_pipeline(db)
    except OllamaConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        result = await pipeline.execute_step(session_id, req.user_edit, force=req.force)
        return {
            "success": result.success,
            "step": result.step.value,
            "content": result.content,
            "verification_score": result.verification.overall_score if result.verification else 0.0,
            "passed": result.verification.passed if result.verification else False,
            "error": result.error,
        }
    finally:
        await pipeline.close()


# ============================================================================
# YOLO
# ============================================================================
@router.post("/projects/{project_id}/yolo/generate")
async def yolo_generate(project_id: str, req: FeatureRequest, db: DatabaseManager = Depends(get_db)):
    try:
        pipeline = await get_yolo_pipeline(db)
    except OllamaConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        result = await pipeline.generate_instant(project_id, req.title, req.description)
        return {
            "success": result.success,
            "feature_node_id": result.feature_node_id,
            "verification_score": result.verification.overall_score if result.verification else 0.0,
            "passed": result.verification.passed if result.verification else False,
            "all_content": result.all_content,
            "error": result.error,
        }
    finally:
        await pipeline.close()


@router.post("/projects/{project_id}/yolo/accept")
async def yolo_accept(project_id: str, req: AcceptRequest, db: DatabaseManager = Depends(get_db)):
    # accept/reject don't need Ollama; use the pipeline class directly.
    from src.pipeline.yolo import YOLOPipeline

    yolo = YOLOPipeline(db)
    result = await yolo.accept_generation(project_id, req.feature_node_id)
    if not result.success:
        raise HTTPException(status_code=404, detail=result.message)
    return {"success": True, "feature_node_id": result.feature_node_id}


@router.post("/projects/{project_id}/yolo/reject")
async def yolo_reject(project_id: str, req: AcceptRequest, db: DatabaseManager = Depends(get_db)):
    from src.pipeline.yolo import YOLOPipeline

    yolo = YOLOPipeline(db)
    ok = await yolo.reject_generation(project_id, req.feature_node_id)
    return {"success": ok}


# ============================================================================
# Bulk generation (feature + full-coverage stress test)
# ============================================================================
@router.post("/projects/{project_id}/bulk/generate")
async def bulk_generate(project_id: str, req: BulkRequest, db: DatabaseManager = Depends(get_db)):
    """Generate all 7 documents for many ideas concurrently.

    Each idea runs through the YOLO pipeline; every one of the 7 documents is
    then verified individually so the response is a precise coverage report —
    which documents were produced, their word counts and scores, and any gaps.
    """
    ideas = [i for i in req.ideas if i.title.strip()]
    if not ideas:
        raise HTTPException(status_code=400, detail="No ideas provided")

    try:
        pipeline = await get_yolo_pipeline(db)
    except OllamaConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    verifier = get_verifier()
    sem = asyncio.Semaphore(max(1, min(req.concurrency, 5)))

    async def run_one(idea: BulkIdea) -> Dict[str, Any]:
        async with sem:
            res = await pipeline.generate_instant(project_id, idea.title, idea.description)
            docs: List[Dict[str, Any]] = []
            for key, node_type in DOC_TYPES:
                content = (res.all_content or {}).get(key, "") or ""
                present = bool(content.strip())
                score, passed, words = 0.0, False, 0
                if present:
                    v = await verifier.verify_section(
                        section_id=f"{res.feature_node_id}_{key}",
                        content=content,
                        node_type=node_type,
                        context={"terminology": {}, "all_sections": []},
                    )
                    score, passed, words = v.overall_score, v.passed, len(content.split())
                docs.append(
                    {
                        "name": key,
                        "present": present,
                        "words": words,
                        "score": round(score, 1),
                        "passed": passed,
                    }
                )
            return {
                "title": idea.title,
                "feature_node_id": res.feature_node_id,
                "success": res.success,
                "overall_score": round(res.verification.overall_score, 1) if res.verification else 0.0,
                "overall_passed": res.verification.passed if res.verification else False,
                "documents": docs,
                "error": res.error,
            }

    try:
        raw = await asyncio.gather(*[run_one(i) for i in ideas], return_exceptions=True)
    finally:
        await pipeline.close()

    results: List[Dict[str, Any]] = []
    for idea, r in zip(ideas, raw):
        if isinstance(r, Exception):
            logger.error("bulk_idea_failed", title=idea.title, error=str(r))
            results.append(
                {
                    "title": idea.title,
                    "feature_node_id": "",
                    "success": False,
                    "overall_score": 0.0,
                    "overall_passed": False,
                    "documents": [
                        {"name": k, "present": False, "words": 0, "score": 0.0, "passed": False}
                        for k, _ in DOC_TYPES
                    ],
                    "error": str(r),
                }
            )
        else:
            results.append(r)

    expected = len(ideas) * len(DOC_TYPES)
    generated = sum(1 for r in results for d in r["documents"] if d["present"])
    passed_docs = sum(1 for r in results for d in r["documents"] if d["passed"])
    gaps = [
        {"idea": r["title"], "missing": [d["name"] for d in r["documents"] if not d["present"]]}
        for r in results
        if any(not d["present"] for d in r["documents"])
    ]
    return {
        "total_ideas": len(results),
        "ideas_ok": sum(1 for r in results if r["success"]),
        "documents_expected": expected,
        "documents_generated": generated,
        "documents_passed": passed_docs,
        "gaps": gaps,
        "results": results,
    }


# ============================================================================
# Node content (for the graph viewer)
# ============================================================================
@router.get("/nodes/{node_id}")
async def get_node(node_id: str, db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
    with db.get_session() as session:
        node = session.query(Node).filter(Node.id == node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        return {
            "id": node.id,
            "project_id": node.project_id,
            "node_type": node.node_type,
            "title": node.title,
            "content": node.content,
            "status": node.status,
            "parent_id": node.parent_id,
        }


# ============================================================================
# Documents — a project's generated docs grouped by feature (for the doc viewer)
# ============================================================================
@router.get("/projects/{project_id}/documents")
async def list_documents(project_id: str, db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
    """Return every generated document for a project, grouped under its feature.

    Each feature (a root node) carries its child artifacts (spec, story, analysis,
    flowchart, pseudocode, tests, docs) with full content so the UI can render a
    readable document library without N+1 calls.
    """
    with db.get_session() as session:
        nodes = session.query(Node).filter(Node.project_id == project_id).all()

    by_parent: Dict[str, List[Node]] = {}
    features: List[Node] = []
    for n in nodes:
        if n.parent_id:
            by_parent.setdefault(n.parent_id, []).append(n)
        if n.node_type == "feature" or n.parent_id is None:
            features.append(n)

    def doc(n: Node) -> Dict[str, Any]:
        return {
            "id": n.id,
            "node_type": n.node_type,
            "title": n.title,
            "status": n.status,
            "content": n.content or "",
            "word_count": len((n.content or "").split()),
        }

    groups = []
    for f in features:
        children = sorted(by_parent.get(f.id, []), key=lambda c: c.created_at or f.created_at)
        groups.append({
            "feature": {"id": f.id, "title": f.title, "status": f.status},
            "documents": [doc(c) for c in children],
            "document_count": len(children),
        })
    # newest features first
    groups.sort(key=lambda g: g["feature"]["title"].lower())
    return {"project_id": project_id, "feature_count": len(groups), "features": groups}
