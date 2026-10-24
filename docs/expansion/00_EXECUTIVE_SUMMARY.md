# Dobby — Expansion to a Local-First AI Workbench · Executive Summary

## The one-liner
**Dobby is the local-first AI workbench where builders turn ideas into shipped software and content — private, offline, and extensible.** It already turns an idea into verified engineering documents; this plan expands it into a single, minimal, categorized app to **capture → generate → automate → build → ship**, all on-device, with a marketplace of skills, flows, and apps.

## Why now
Open, local models (Ollama/llama.cpp) are now good enough to run real work on-device. Builders are stitching together 5–8 tools (AI IDE, agent runner, notetaker, automation, transcription, video) that all ship data to the cloud. Dobby collapses that stack into one private, bring-your-own-model workbench — the calm, categorized home a builder opens first.

## What we're building (12-month plan, 6 phases)
| Phase | Months | Theme | Headline features |
|---|---|---|---|
| P1 | 1–2 | Foundations & Findability | Categorized minimal UI redesign, Global Search, Command Center (⌘K), Logs & Traces |
| P2 | 3–4 | Media & Capture Studio | Embedded Terminal, Audio Transcription, YouTube → Notes, Notes Builder |
| P3 | 5–6 | Automation | Skill Builder, Flow Builder, Control Center |
| P4 | 7–8 | Build & Generate | Prototype Builder + Test, Video Generation |
| P5 | 9–10 | Local Marketplace | Install skills/flows/apps locally; extensibility SDK |
| P6 | 11–12 | Publish & Cloud | Publish to a shared marketplace, sync, monetization rails |

Total build effort: **~247 person-weeks** across a team scaling from 3 → 6.

## The ask
- **Raising: $2.2M seed** for **~18 months** of runway.
- 12-month operating plan: **~$1.13M** (Base). Scenarios: Lean $720K · Base $1.13M · Ambitious $1.72M.
- Team: 6 fully-loaded roles (Founder/Product, Sr Full-stack, Backend/AI, ML/Media, Designer, DevRel).
- Local-first = **near-zero inference/cloud cost** — capital goes to people and community, not GPU bills.

## Market
- **TAM ≈ $48B** (the adjacent tool budgets one workbench absorbs) · **SAM ≈ $6.2B** (privacy-sensitive, local-first/BYO-model users) · **SOM (3-yr) ≈ $42M**.
- Business model: free desktop app → **Pro/Team subscriptions** + **marketplace take-rate** on published skills/flows/apps + optional cloud sync.
- Moat: the **local-first + marketplace flywheel** — private by default, and every published skill/flow/app makes the workbench more valuable.

## What's already real (de-risks execution)
A working local-first desktop app (Tauri 2 + React + FastAPI + SQLite + Ollama): multi-project workspaces, idea → **7 verified engineering documents** (Wizard / YOLO / Bulk), a deterministic (non-LLM) verifier, a Pareto backlog, a dependency graph, and a document library — all running offline. **The categorized minimal UI redesign in this plan is already implemented.**

## Document set
1. `01_VISION_AND_UX.md` — vision, information architecture, minimal design system, per-feature UX.
2. `02_FEATURE_SPECS.md` — build-ready specs for the 13 new features.
3. `03_ARCHITECTURE.md` — system + per-feature architecture, diagrams, key decisions.
4. `04_ROADMAP_AND_PROJECT_PLAN.md` — phased roadmap, milestones, dependencies, risks, DoD.
5. `05_BUSINESS_PLAN.md` — business model, pricing, unit economics, use of funds.
6. `06_MARKET_ANALYSIS.md` — TAM/SAM/SOM, competition, ICP, GTM, differentiation.
7. `Dobby_Expansion_Plan.xlsx` (repo root) — feature specs, roadmap, effort, budget, team, market, milestones tabs.
8. `Dobby_Investor_Deck.pptx` (repo root) — 16-slide seed pitch.

*All financial and market figures are illustrative planning estimates, not audited forecasts.*
