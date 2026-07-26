# Real web search & classical reasoning

## Attribution and licensing

| Project | Licence | How Dobby uses it |
|---|---|---|
| [wigolo](https://github.com/KnockOutEZ/wigolo) | **AGPL-3.0-only** | Separate local daemon, called over its REST API. **No code vendored.** |
| [symbolica](https://github.com/ksjpswaroop/symbolica) | none declared (owned by this project's author) | Optional HTTP verifier. No code vendored. |

**Why wigolo is not vendored.** AGPL-3.0 is strong copyleft: copying any of it
into this repository would force Dobby to be relicensed AGPL and trigger the
network-use clause. Dobby instead runs it as an independent process and talks to
it over the REST interface wigolo's own documentation offers for exactly this
("point n8n, a Hermes-style assistant, or any self-hosted agent at it"). That is
arm's-length interprocess communication between separate programs, not a
derivative work, so Dobby stays MIT. The user installs and runs wigolo
themselves; Dobby never redistributes it.

**Symbolica has no LICENSE file.** It is your own repository so you may use it
freely, but absent a licence nobody else legally can — worth adding one before
anyone else depends on it.

## Real web search

Research is grounded through a pluggable provider. wigolo is the recommended
one because it is the only option that gives genuinely sourced research *and*
keeps the local-first promise: multi-engine search, no API key, no cloud
account, nothing leaving `~/.wigolo/`.

```bash
npx wigolo init     # one-time: browser engine, embeddings, reranker
wigolo serve        # daemon on 127.0.0.1:3333
```

Then Settings → Research search → **wigolo**.

| Provider | Leaves the machine | Key needed |
|---|---|---|
| `none` (default) | No | — |
| `wigolo` | **No** | **No** |
| `searxng` | No | No |
| `tavily` / `brave` | **Yes** | Yes |

Verified live: a five-track brief pulled **72 real sources** in ~3 minutes.

### Two bugs real search exposed

1. **Queries were not self-contained.** The model emitted the bare query
   `Industry`, which returned a TV series, an Austin restaurant, and IMDb. A
   search engine sees only the query string. Fixed in the prompt *and* with
   `_anchor_query`, which rewrites any query sharing no distinctive term with
   the topic — the prompt alone is not a guarantee.
2. **"No results found" was being stored as a finding.** A model that finds
   nothing reports that as a bullet, which then becomes evidence, appears in the
   report, and — worst — reads to the contradiction checker as a claim that
   contradicts every real claim. Meta-statements are now filtered at extraction.

## Classical reasoning

`src/reasoning/logic.py` is a complete decision procedure for classical
propositional logic: parser, evaluator, and exhaustive truth-table search. Pure
standard library, always available, no configuration.

"Complete" is the point. Entailment is *decided*, not estimated — and when a
sequent is invalid the search returns a **countermodel**, a concrete assignment
making every premise true and the conclusion false. Tests assert that every
returned countermodel genuinely witnesses the failure, so the engine cannot
claim invalidity without proof.

Covered: modus ponens, modus tollens, hypothetical and disjunctive syllogism,
constructive dilemma, both De Morgan laws, contraposition, reductio, excluded
middle, non-contradiction, biconditional elimination — and the fallacies
(affirming the consequent, denying the antecedent, converse error) must be
refuted, not merely flagged.

```python
from src.reasoning import check
check(["A -> B", "A"], "B").verdict          # 'valid'
check(["A -> B", "B"], "A").countermodel      # {'A': False, 'B': True}
```

### What it is actually for

Research fans out across five tracks, each a **separate model call**. Nothing
makes them agree. A brief can assert a growing market in one track and a
shrinking one in another — each locally plausible, so no per-claim check will
ever catch it. It only appears when claims are compared.

After every research run, `src/reasoning/audit.py` compares all findings
pairwise and reports contradictions in the UI, naming which two tracks
disagree. The heuristic only ever *proposes* a pair; `logic.py` decides.

**Tuned against live data.** The first run flagged 10 conflicts — all 10 false
positives. Eight came from one meta-statement; two from a negation heuristic
firing on claims about different products. After filtering meta-claims and
requiring near-total subject overlap for negation-only matches, the same data
yields 0, while tests confirm genuine contradictions are still caught.

### Symbolica (optional)

Set a URL in Settings → Reasoning to escalate. It adds first-order logic, Fitch
proof objects, causal/deontic/equational queries, and natural-language
formalization. When unreachable, every call falls back to the local prover and
names which engine answered, so a first-order verdict is never confused with a
propositional one.

## Statefulness & logging

Everything a research pass produces is persisted in SQLite: briefs, tracks,
findings, sources, and the audit result. The audit lives on `extra_metadata`
rather than its own column so existing databases need no migration — SQLite
cannot add a column to an existing table, and older briefs must still open.

Every stage is traced through the existing `Tracer`, so research appears in
**Logs & Traces** beside generation, streaming over the same SSE channel. A
completed run logs 20 events including `plan.start`, `audit.start`, and
`audit.done` with the conflict count. Failures are recorded on both the run and
the brief, never swallowed.
