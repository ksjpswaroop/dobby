"""
Research stage — parsing, safety guards, and the hand-off into the backlog.

The model is stubbed. What is tested is not whether a given local model writes
good research, but that malformed output cannot corrupt a brief and that an
unsourced statistic cannot reach the user unmarked — the failure mode that
actually showed up in live testing.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_research_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB

from fastapi.testclient import TestClient  # noqa: E402

from src.db.research_models import TRACK_KINDS  # noqa: E402
from src.main import app  # noqa: E402
from src.services import research_search as ss  # noqa: E402
from src.services import research_service as svc  # noqa: E402

PROJECT = "default-project"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


# ---------------------------------------------------------------------------
class TestParsing:
    def test_strips_bullets_numbering_and_quotes(self):
        raw = '1. first finding here\n- second finding here\n"third finding here"'
        assert svc._lines(raw, 5) == [
            "first finding here", "second finding here", "third finding here"
        ]

    def test_drops_filler_and_short_lines(self):
        raw = "Here are the queries:\nok\na genuine query line\n"
        assert svc._lines(raw, 5) == ["a genuine query line"]

    def test_ignores_code_fences(self):
        raw = "real finding number one\n```\nnot a finding at all\n```\n"
        assert svc._lines(raw, 5) == ["real finding number one"]

    def test_respects_the_limit(self):
        raw = "\n".join(f"finding number {i}" for i in range(20))
        assert len(svc._lines(raw, 3)) == 3

    @pytest.mark.parametrize("meta", [
        "The search results do not provide information on note-taking apps",
        "Search results do not contain relevant pricing information",
        "No relevant information was found about competitors",
        "Unable to determine the market size from these sources",
    ])
    def test_meta_statements_are_not_kept_as_findings(self, meta):
        """A remark about the search is not a finding about the subject."""
        raw = f"- A real finding about the market here\n- {meta}"
        kept = svc._lines(raw, 5, drop_meta=True)
        assert kept == ["A real finding about the market here"]

    def test_meta_filtering_is_opt_in(self):
        raw = "The search results do not provide information on anything"
        assert svc._lines(raw, 5) != []
        assert svc._lines(raw, 5, drop_meta=True) == []

    def test_section_extraction_is_case_insensitive(self):
        plan = "## Product\nbuild this\n## Market\nsell to them\n"
        assert svc._section(plan, "market") == "sell to them"
        assert svc._section(plan, "Nope") == ""


class TestQueryAnchoring:
    """A search engine sees only the query string, not the conversation."""

    def test_a_generic_query_gains_the_subject(self):
        out = svc._anchor_query("Industry", "Local-first note apps for consultants")
        assert out != "Industry"
        assert "consultants" in out or "local-first" in out

    def test_a_query_already_naming_the_subject_is_untouched(self):
        q = "local-first note apps pricing 2026"
        assert svc._anchor_query(q, "Local-first note apps for consultants") == q

    def test_generic_research_words_do_not_count_as_anchors(self):
        """'market size' is in every query; it cannot disambiguate anything."""
        out = svc._anchor_query("market size", "Local-first note apps for consultants")
        assert out != "market size"

    def test_an_empty_topic_leaves_the_query_alone(self):
        assert svc._anchor_query("anything", "") == "anything"


class TestUnverifiedStatisticGuard:
    """The failure that showed up live: invented figures stated as fact."""

    @pytest.mark.parametrize("text", [
        "The market is worth $10 million in 2022",
        "Growing at a CAGR of 20% from 2018",
        "A survey found 75% of consultants were dissatisfied",
        "There are 63.1 million self-employed users",
    ])
    def test_unsourced_statistics_are_flagged(self, text):
        assert svc._flag_unverified(text, grounded=False).startswith("[unverified]")

    @pytest.mark.parametrize("text", [
        "Consultants value offline access above sync",
        "Notion and Obsidian both target this segment",
    ])
    def test_non_statistical_claims_are_left_alone(self, text):
        assert svc._flag_unverified(text, grounded=False) == text

    def test_already_marked_claims_are_not_double_marked(self):
        text = "[inferred] The market is around $10 million"
        assert svc._flag_unverified(text, grounded=False) == text

    def test_grounded_findings_are_never_flagged(self):
        text = "The market is worth $10 million in 2022"
        assert svc._flag_unverified(text, grounded=True) == text


class TestSearch:
    @pytest.mark.asyncio
    async def test_none_provider_makes_no_call_and_reports_itself(self):
        out = await ss.search("anything", "none", {})
        assert out.results == [] and out.provider == "none" and out.error is None

    @pytest.mark.asyncio
    async def test_missing_credentials_degrade_rather_than_raise(self):
        out = await ss.search("anything", "tavily", {})
        assert out.results == []
        assert "API key" in out.error

    @pytest.mark.asyncio
    async def test_searxng_without_a_url_degrades(self):
        out = await ss.search("anything", "searxng", {})
        assert "SearXNG URL" in out.error

    @pytest.mark.asyncio
    async def test_search_many_preserves_order_and_length(self):
        outs = await ss.search_many(["a", "b", "c"], "none", {})
        assert len(outs) == 3

    def test_remote_providers_are_declared(self):
        assert set(ss.REMOTE_PROVIDERS) == {"tavily", "brave"}
        # Both of these run on the user's own machine, so neither is "remote".
        assert "searxng" not in ss.REMOTE_PROVIDERS
        assert "wigolo" not in ss.REMOTE_PROVIDERS

    @pytest.mark.asyncio
    async def test_wigolo_is_offered_and_needs_no_key(self):
        assert "wigolo" in ss.PROVIDERS
        # Unlike the hosted providers, a missing key is never the failure mode.
        out = await ss.search("anything", "wigolo", {"wigolo_url": "http://127.0.0.1:9"})
        assert "API key" not in (out.error or "")

    @pytest.mark.asyncio
    async def test_wigolo_not_running_explains_how_to_start_it(self):
        out = await ss.search("anything", "wigolo",
                              {"wigolo_url": "http://127.0.0.1:9"})
        assert out.results == []
        assert "wigolo serve" in out.error

    @pytest.mark.asyncio
    async def test_wigolo_parses_both_response_envelopes(self, monkeypatch):
        """The daemon has shipped results at the top level and nested in `data`."""
        import httpx

        for payload in (
            {"results": [{"title": "T", "url": "u", "snippet": "s"}]},
            {"data": {"results": [{"title": "T", "url": "u", "content": "s"}]}},
        ):
            class FakeResponse:
                status_code = 200

                def raise_for_status(self): pass

                def json(self): return payload

            class FakeClient:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
                async def post(self, *a, **k): return FakeResponse()

            monkeypatch.setattr(httpx, "AsyncClient", lambda **k: FakeClient())
            out = await ss.search("q", "wigolo", {})
            assert len(out.results) == 1
            assert out.results[0].title == "T" and out.results[0].snippet == "s"


class TestBriefs:
    def test_creating_a_brief_seeds_every_track(self, db):
        brief = svc.create_brief(db, PROJECT, "A test topic")
        assert brief["status"] == "pending"
        assert [t["kind"] for t in brief["tracks"]] == list(TRACK_KINDS)

    def test_an_empty_topic_is_rejected(self, db):
        with pytest.raises(svc.ResearchError):
            svc.create_brief(db, PROJECT, "   ")

    def test_an_unknown_project_is_rejected(self, db):
        with pytest.raises(svc.ResearchError):
            svc.create_brief(db, "no-such-project", "A topic")

    def test_delete_removes_the_brief(self, db):
        brief = svc.create_brief(db, PROJECT, "Disposable")
        assert svc.delete_brief(db, brief["id"]) is True
        assert svc.get_brief(db, brief["id"]) is None


class TestFeatureHandoff:
    def test_feature_lines_are_parsed_into_scored_proposals(self):
        line = "Offline sync | Works with no network | 9 | 4 | 3"
        m = svc._FEATURE_LINE.match(line)
        assert m and m.group(1).strip() == "Offline sync"
        assert svc._score(m.group(3)) == 9.0

    def test_scores_are_clamped_to_the_backlog_range(self):
        assert svc._clamp(99) == 10.0
        assert svc._clamp(-5) == 1.0
        assert svc._clamp("not a number") == 5.0

    def test_accepted_features_land_in_the_backlog_with_provenance(self, db, client):
        brief = svc.create_brief(db, PROJECT, "Handoff topic")
        result = svc.accept_features(db, brief["id"], [
            {"title": "Offline sync", "description": "Works offline",
             "impact": 9, "effort": 4, "risk": 3},
        ])
        assert result["created"] == 1

        from src.db.schema import FeatureBacklog

        with db.get_session() as s:
            row = (s.query(FeatureBacklog)
                   .filter(FeatureBacklog.title == "Offline sync").first())
            assert row is not None
            assert row.impact_score == 9 and row.effort_score == 4
            assert row.pareto_score > 0
            assert row.extra_metadata["brief_id"] == brief["id"]

    @pytest.mark.asyncio
    async def test_features_before_completion_are_refused(self, db):
        brief = svc.create_brief(db, PROJECT, "Not finished")
        with pytest.raises(svc.ResearchError, match="Finish the research"):
            await svc.propose_features(db, brief["id"])


class TestApi:
    def test_tracks_endpoint_lists_all_five(self, client):
        r = client.get("/api/v1/research/tracks")
        assert r.status_code == 200
        assert len(r.json()["tracks"]) == 5

    def test_providers_endpoint_declares_which_leave_the_machine(self, client):
        r = client.get("/api/v1/research/providers")
        assert r.status_code == 200
        remote = {p["id"] for p in r.json()["providers"] if p["remote"]}
        assert remote == {"tavily", "brave"}

    def test_create_list_and_fetch(self, client):
        r = client.post("/api/v1/research",
                        json={"project_id": PROJECT, "topic": "API topic"})
        assert r.status_code == 200, r.text
        bid = r.json()["id"]

        assert any(b["id"] == bid for b in
                   client.get(f"/api/v1/research/project/{PROJECT}").json()["briefs"])
        assert client.get(f"/api/v1/research/{bid}").json()["topic"] == "API topic"

    def test_missing_brief_is_404(self, client):
        assert client.get("/api/v1/research/nope").status_code == 404

    def test_empty_topic_is_a_validation_error(self, client):
        r = client.post("/api/v1/research",
                        json={"project_id": PROJECT, "topic": ""})
        assert r.status_code == 422
