"""
Pluggable web search for the Research stage.

Dobby's whole premise is that it runs locally with nothing leaving the machine,
and web search is the one capability that cannot honour that by definition. The
resolution here is that search is **opt-in and honest about itself**:

* ``none`` (default) — no network calls. Research runs on the model's own
  knowledge plus the project's own context. Findings are recorded with
  ``kind="model"`` so nothing pretends to be sourced when it is not.
* ``wigolo`` — **the recommended provider.** A local daemon that does real
  multi-engine web search with no API keys and no cloud account. It is the only
  option that gives genuinely sourced research while keeping Dobby's
  local-first promise.
* ``searxng`` — a self-hosted meta-search instance. Also stays local.
* ``tavily`` / ``brave`` — hosted APIs, user-supplied key. These *do* send the
  query off the machine, which the UI states plainly before enabling them.

**On wigolo and licensing.** wigolo is AGPL-3.0-only; Dobby is MIT and
commercial. None of its code is here and none is redistributed. Dobby talks to
it the way its own documentation prescribes — as a separate process over its
REST API — which is arm's-length interprocess communication between independent
programs, not a derivative work. The user installs and runs wigolo themselves
(``npx wigolo init && wigolo serve``). Vendoring any part of it into this
repository would relicense Dobby, so it must not happen.

Provider shapes follow the set in u14app/deep-research (MIT); the
implementations here are written against our async httpx stack.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import structlog

logger = structlog.get_logger()

PROVIDERS = ("none", "wigolo", "searxng", "tavily", "brave")

# Providers that send the query to a third party. The UI warns on these.
# wigolo and searxng run on the user's own machine, so neither appears here.
REMOTE_PROVIDERS = ("tavily", "brave")

DEFAULT_WIGOLO_URL = "http://127.0.0.1:3333"

TIMEOUT = 20.0
MAX_RESULTS = 6
MAX_SNIPPET = 1200


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class SearchOutcome:
    """What a search attempt produced, including why it produced nothing."""

    results: List[SearchResult] = field(default_factory=list)
    provider: str = "none"
    # Set when a configured provider failed. Research continues on model
    # knowledge rather than aborting, but the reason is surfaced.
    error: Optional[str] = None


class SearchUnavailable(Exception):
    """A provider is selected but not usable (missing key, unreachable host)."""


def _clip(text: Any) -> str:
    return str(text or "").strip()[:MAX_SNIPPET]


async def _wigolo(query: str, cfg: Dict[str, str]) -> List[SearchResult]:
    """Search through a locally running wigolo daemon.

    Separate process, plain REST — no wigolo code is linked into Dobby. The
    daemon is keyless, so unlike the hosted providers there is nothing to
    configure beyond having it running.
    """
    base = (cfg.get("wigolo_url") or DEFAULT_WIGOLO_URL).rstrip("/")
    headers = {"Content-Type": "application/json"}
    token = cfg.get("wigolo_token")
    if token:  # only needed when the daemon is bound past loopback
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{base}/v1/search", headers=headers,
                             json={"query": query, "max_results": MAX_RESULTS})
            r.raise_for_status()
            data = r.json()
    except (httpx.ConnectError, httpx.ReadTimeout):
        raise SearchUnavailable(
            "wigolo is not running. Start it with `wigolo serve` "
            "(install once with `npx wigolo init`)."
        )

    # The envelope has varied across versions; accept the common shapes rather
    # than breaking on a minor release.
    items = data.get("results")
    if items is None and isinstance(data.get("data"), dict):
        items = data["data"].get("results")
    return [
        SearchResult(
            _clip(i.get("title")),
            _clip(i.get("url")),
            _clip(i.get("snippet") or i.get("content") or i.get("description")),
        )
        for i in (items or [])[:MAX_RESULTS]
    ]


async def _searxng(query: str, cfg: Dict[str, str]) -> List[SearchResult]:
    base = (cfg.get("searxng_url") or "").rstrip("/")
    if not base:
        raise SearchUnavailable("Set the SearXNG URL in Settings to search with it.")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{base}/search",
                        params={"q": query, "format": "json", "language": "en"})
        r.raise_for_status()
        data = r.json()
    return [
        SearchResult(_clip(i.get("title")), _clip(i.get("url")), _clip(i.get("content")))
        for i in (data.get("results") or [])[:MAX_RESULTS]
    ]


async def _tavily(query: str, cfg: Dict[str, str]) -> List[SearchResult]:
    key = cfg.get("tavily_api_key")
    if not key:
        raise SearchUnavailable("Add a Tavily API key in Settings to search with it.")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": MAX_RESULTS,
                  "search_depth": "advanced", "include_answer": False},
        )
        r.raise_for_status()
        data = r.json()
    return [
        SearchResult(_clip(i.get("title")), _clip(i.get("url")), _clip(i.get("content")))
        for i in (data.get("results") or [])[:MAX_RESULTS]
    ]


async def _brave(query: str, cfg: Dict[str, str]) -> List[SearchResult]:
    key = cfg.get("brave_api_key")
    if not key:
        raise SearchUnavailable("Add a Brave Search API key in Settings to search with it.")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": MAX_RESULTS},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    return [
        SearchResult(_clip(i.get("title")), _clip(i.get("url")), _clip(i.get("description")))
        for i in ((data.get("web") or {}).get("results") or [])[:MAX_RESULTS]
    ]


_IMPL = {"wigolo": _wigolo, "searxng": _searxng, "tavily": _tavily, "brave": _brave}


async def search(query: str, provider: str, cfg: Dict[str, str]) -> SearchOutcome:
    """Run one search. Never raises — a failed search degrades, it does not abort.

    A research pass that dies because one query 404'd is worse than one that
    reports what it could not reach and carries on with the rest.
    """
    if provider == "none" or provider not in _IMPL:
        return SearchOutcome(provider="none")
    try:
        results = await _IMPL[provider](query, cfg)
        return SearchOutcome(results=results, provider=provider)
    except SearchUnavailable as e:
        return SearchOutcome(provider=provider, error=str(e))
    except httpx.HTTPStatusError as e:
        return SearchOutcome(provider=provider,
                             error=f"{provider} returned {e.response.status_code}.")
    except Exception as e:  # network down, malformed JSON, timeout
        logger.warning("research_search_failed", provider=provider, error=str(e))
        return SearchOutcome(provider=provider, error=f"{provider} search failed: {e}")


async def search_many(queries: List[str], provider: str,
                      cfg: Dict[str, str]) -> List[SearchOutcome]:
    """Search several queries concurrently, preserving order."""
    if provider == "none":
        return [SearchOutcome(provider="none") for _ in queries]
    return list(await asyncio.gather(*(search(q, provider, cfg) for q in queries)))
