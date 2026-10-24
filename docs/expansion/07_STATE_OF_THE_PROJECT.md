# Dobby — State of the Project

**As of:** Sunday, 2026-07-26 · **Branch:** `feat/dobby-v2-workbench` · **PR:** [#1](https://github.com/ksjpswaroop/dobby/pull/1)

This is the ground truth the rest of this week's planning is built on. Everything below was verified today, not recalled from memory — test counts, file checks, and the roadmap tab were re-read before writing this.

---

## 1. What Dobby is, today

A local-first desktop app (Tauri 2 + React + FastAPI + SQLite, inference via Ollama or any OpenAI-compatible/Anthropic endpoint) that takes a product idea through: **Ideate → Research → Create → Automate**, with nothing required to leave the machine.

**Health snapshot:**

| Measure | Value |
|---|---|
| Backend tests | **588 passing** |
| OW · Features roadmap tab | **40 Done / 12 Partial / 2 Planned / 1 N/A** (of 55 reverse-engineered OpenWorker features) |
| App version | `0.1.0` (pyproject) / `2.0.0` (Tauri bundle identifier) — **pre-1.0, not yet version-numbered for release** |
| Code signing | **None** (`signingIdentity: null` in `tauri.conf.json`) |
| CI/CD | **None** (`.github/workflows/` does not exist) |
| License | **MIT**, whole repository |
| Licensing/entitlement system | **Does not exist** |
| Payment integration | **Does not exist** |
| Website / landing page | **Does not exist** |

### What's genuinely built and verified (last ten days of work)

Not scaffolding — each of these was tested against a real backend, real model, or real external service before being called done:

- **Generation core:** Wizard (7-step guided), YOLO (one-shot), Bulk (parallel), deterministic verifier, dependency graph, mind mapping with markdown-outline interchange and AI chat editing.
- **Research stage:** five-track product research (product/market/competition/business/technical), real web search via a local search daemon (wigolo, zero cloud calls), a from-scratch classical-logic prover that catches contradictions between research tracks, findings promotable into the backlog.
- **Automations:** a full cron scheduler (hand-written parser, no dependency), catch-up on restart, skip-on-overlap, run history, unread badges.
- **Approvals & Inbox:** every consequential action (shell exec, network fetch, sending a message, installing a persona/connector) is gated behind a human decision or a narrowly-scoped standing grant. Denial and timeout both mean no — this is tested explicitly.
- **Security:** per-launch API token (no more unauthenticated localhost API), sandboxed approval-gated terminal (no shell — argv only, so injection strings are inert), hard denylist that approval cannot override (`rm -rf`, `sudo`, disk ops).
- **MCP client:** full Model Context Protocol client (stdio + Streamable HTTP), verified against a real MCP server (wigolo) — 10 tools discovered and called live.
- **Attachments:** local file upload with PDF/text extraction (pypdf → macOS textutil → honest "needs OCR" fallback), feeding research and generation.
- **Multi-provider model routing:** Ollama, any OpenAI-compatible endpoint (LM Studio, vLLM, OpenRouter...), Anthropic — with capability-based routing that prefers local models.
- **Durable sessions:** suspend/resume, three permission modes (`ask` / `unattended` / `readonly`), readonly checked *before* standing grants so a mode can't be silently defeated.
- **Personas:** four built-ins (Dobby, Researcher, Engineer, Ops), markdown-manifest format, install-with-consent for third-party personas, prompt-injection phrase detection on the consent card.
- **Local speech-to-text:** whisper.cpp integration, verified against real synthesized speech (1.1s transcription, fully offline).
- **Messaging connectors:** Slack + Telegram, real HMAC signature verification, dead-letter store, pre-approved replies in threads where Dobby was addressed.
- **Terminal:** docked at the bottom of the shell (⌃`), not a nav page — scrollback and history survive navigation.

### What is explicitly NOT built (the commercialization gap)

This is the honest part, and it's the whole subject of this week's plan. None of the following exist yet:

1. **A license or entitlement system of any kind.** There is no concept of "paid" vs "free" in the code. Every feature above is available to anyone who clones the repo.
2. **Payment processing.** No Stripe, Paddle, Lemon Squeezy, or invoicing integration.
3. **Code signing / notarization.** The macOS build is unsigned. On a clean Mac, Gatekeeper will block it outright ("app is damaged and can't be opened") unless the user right-clicks → Open, which kills conversion for anyone unfamiliar with that workaround. There is no Windows build verified either.
4. **Auto-update.** Tauri supports this natively, but it isn't wired up. Every update today means "download the DMG again."
5. **A website.** No landing page, no pricing page, no docs site. `find` confirms nothing matching landing/website exists in the repo.
6. **Legal.** No EULA, no privacy policy, no refund policy, no terms of service.
7. **CI/CD.** Every build today is manual, on your machine.
8. **White-label packaging.** No config-driven rebrand path (swap name/logo/color and produce a distinct build) exists.
9. **Onboarding.** First run drops a user on a dashboard with 45 seeded features and no explanation of Wizard vs. YOLO vs. Bulk, or what to do first.

None of these are hard, individually. Together, they are the entire distance between "an impressive local codebase" and "a thing a stranger can pay for and trust." That distance is what next week closes.

---

## 2. Existing strategy documents (already written, still valid)

This week's plan does not replace these — it operationalizes them:

- [00_EXECUTIVE_SUMMARY.md](00_EXECUTIVE_SUMMARY.md) — positioning and pitch
- [05_BUSINESS_PLAN.md](05_BUSINESS_PLAN.md) — the original subscription-first model ($20/mo Pro, $40/mo Team, 15% marketplace take rate). **This week's pricing doc (08) reconciles that model against a "sell licenses" framing** — see the decision required there.
- [06_MARKET_ANALYSIS.md](06_MARKET_ANALYSIS.md) — market fit
- `FEATURE_TRACKER.md` (repo root) — the living feature list, superseding loose phase notes
- `Dobby_100_Day_Roadmap.xlsx` — the OW · Features tab tracked against real OpenWorker feature parity (40/55 Done as of today)

---

## 3. The one decision that blocks everything else

**The repository is MIT-licensed.** MIT permits anyone to take the entire codebase, compile it themselves, and use, modify, or redistribute it — including as a free competing product — with zero obligation to pay you anything.

Selling "licenses" to software that is simultaneously free and legally forkable by anyone is not a contradiction, but it does mean **the thing being sold cannot be "the code."** It has to be something the free/open path doesn't give you: a signed & notarized build, automatic updates, hosted infrastructure, support, a brand/trademark, or contractual rights (white-label, resale, indemnification).

This is spelled out fully in [08_LICENSING_AND_PRICING_DECISION.md](08_LICENSING_AND_PRICING_DECISION.md), which needs a decision from you before Monday's engineering work starts, because it determines what the entitlement system actually checks.
