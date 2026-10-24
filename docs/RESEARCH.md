# Research — the stage before Create

## Attribution

The pipeline design — plan → queries → search → distil learnings → review →
synthesize — is adapted from
[u14app/deep-research](https://github.com/u14app/deep-research), **MIT licensed,
© 2024 u14app**. Its licence is compatible with this repository's MIT licence
and permits commercial use.

What was taken: the loop shape, the review-and-iterate step, and the set of
search-provider integrations. What was not: any code. Upstream is Next.js 15 +
React 19 on the Vercel AI SDK; Dobby's backend is Python/FastAPI over Ollama, so
the pipeline is a reimplementation rather than a port.

Where the design deliberately diverges, and why:

| Upstream | Dobby | Why |
|---|---|---|
| Model invents the report's section list | **Five fixed tracks** | A founder's questions are known in advance. Fixing them makes briefs comparable and mappable onto the backlog. |
| Output is a report | Output is **structured findings + sections** | A finding has to be promotable into a feature. Prose is not. |
| Search is required | Search is **optional, default off** | Dobby's premise is that nothing leaves the machine unless asked. |
| JSON schema for query generation | Plain line-delimited output | Small local models handle lines far more reliably than JSON, and a mangled line degrades instead of failing. |

## The five tracks

Not "a research report" — five separate investigations, run concurrently:

| Track | Answers |
|---|---|
| **Product** | What to build. Jobs to be done, table stakes vs. differentiators, complaints about adjacent tools. |
| **Market** | Who wants it. Segments, size and growth, buying triggers, budget-holder vs. end-user. |
| **Competition** | Who else is doing it. Named products, strengths, pricing, the gap. |
| **Business model** | How it makes money. Pricing, revenue model, unit economics, channels. |
| **Technical feasibility** | Whether it can be built. Architecture, dependencies, hard problems, risks. |

Each track: generates its own search queries, gathers evidence, distils discrete
findings, reviews whether anything important is missing (one follow-up round),
then writes its section ending in **So what** — what this means for the build
decision.

## Grounding, and the fabrication problem

**This is the part that matters most.** With no search provider configured, the
model writes from training knowledge — and small models invent statistics that
read exactly like real ones. In live testing, llama3.2 produced:

> "The market ... is estimated to be around **$10 million in 2022, growing at a
> CAGR of 20%**" and "A survey of independent consultants found that **75%**
> reported..."

Both fabricated. Neither carried the `[inferred]` marker the prompt asks for.

Three defences, because prompt instructions alone demonstrably fail:

1. **The prompt** forbids inventing figures and requires marking inference.
   Necessary, not sufficient.
2. **A mechanical backstop** (`_flag_unverified`). When ungrounded, any finding
   containing a statistic — currency amount, percentage, magnitude, CAGR —
   that is not already marked gets prefixed `[unverified]`.
3. **The UI** shows a persistent banner when search is off, and renders
   `unverified` / `inferred` as a warning chip on the finding itself with a
   tooltip: *treat as a lead to verify, not a fact*.

Sources are recorded with `kind="model"` when nothing was retrieved, so a
brief grounded in nothing never looks like one grounded in sources.

## Search providers

Default **off**. Configure in Settings → Research search.

| Provider | Leaves the machine | Notes |
|---|---|---|
| `none` | No | Model knowledge only. Findings flagged as above. |
| `searxng` | No | Self-hosted meta-search. Keeps the local-first guarantee. |
| `tavily` | **Yes** | Built for agents. Needs an API key. |
| `brave` | **Yes** | Independent index. Needs an API key. |

Keys live in `~/.dobby/settings.json`. The UI labels remote providers *leaves
device* before you pick one.

A failed search **degrades, never aborts** — a research pass that dies because
one query timed out is worse than one that reports what it could not reach.

## Research → Create

The reason this stage sits before Create in the nav: its output is Create's
input.

`Send to backlog` asks the model for concrete features the research justifies,
each scored for impact / effort / risk. These are **proposals only** — you pick
which to keep, then they are written into the feature backlog with their Pareto
score computed by the existing scorer, and `metadata.brief_id` recording which
research justified them.

From there the normal flow applies: Backlog → Wizard / YOLO / Bulk.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/research/tracks` | The five track kinds |
| `GET` | `/api/v1/research/providers` | Providers and which are remote |
| `GET` | `/api/v1/research/project/{id}` | Briefs for a project |
| `POST` | `/api/v1/research` | Create a brief |
| `GET` | `/api/v1/research/{id}` | Full brief with tracks, findings, sources |
| `POST` | `/api/v1/research/{id}/run` | Start it (returns immediately) |
| `DELETE` | `/api/v1/research/{id}` | Delete |
| `POST` | `/api/v1/research/{id}/features` | Propose backlog features |
| `POST` | `/api/v1/research/{id}/features/accept` | Write accepted ones to the backlog |

Running is asynchronous: research takes minutes, so `/run` returns at once and
progress arrives on the existing `/api/v1/runs/stream` SSE channel — a research
pass appears in Logs & Traces like any generation.

## Performance

Five tracks concurrently, up to two rounds each. On `llama3.2` with no search,
a full brief took roughly **4 minutes** and produced 12 findings per track.
