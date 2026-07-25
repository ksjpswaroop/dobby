# Dobby — Business & Resourcing Plan (Pre-seed / Seed, 12-Month Build)

**Positioning:** "The local-first AI workbench where builders turn ideas into shipped software and content — private, offline, and extensible."

Dobby is a single, minimal, categorized desktop app (Tauri 2 + React + FastAPI + SQLite, LLM via local Ollama/llama.cpp, bring-your-own-model, zero cloud dependency) that lets builders **capture → generate → automate → build → ship** fully on-device, with an on-device marketplace of skills, flows, and apps that later publishes to a shared marketplace.

> All revenue and unit-economics figures in this document are **illustrative projections** for planning and fundraising conversations, not forecasts or commitments.

---

## 1. Business Model

Four complementary revenue streams, sequenced so the free product builds distribution first and monetization rails arrive with the marketplace (P5–P6):

1. **Freemium desktop app.** The core workbench is free and local: Workspace, Generate, Studio basics, Search, Command Center. This is the top of the funnel and the reason to install. Bring-your-own-model means a user can get full value at zero marginal cost to us — the local-first architecture is the growth engine, not a cost center.
2. **Pro / Team subscriptions.** Paid tiers unlock power features (advanced Skill/Flow Builder capacity, Control Center orchestration, Prototype Builder + Test, Video Studio, priority builds) and, for Team, shared workspaces, admin/permissions, and optional encrypted cloud sync.
3. **Marketplace take-rate.** Once publishing goes live (P6), creators sell skills, flows, and app templates. Dobby takes a percentage of each transaction. This is the long-term compounding stream: it scales with ecosystem supply, not with our headcount.
4. **Optional cloud sync (add-on).** For users who want cross-device sync and backup without giving up local-first defaults — a metered add-on, opt-in, priced to cover its own infra with margin.

**Why local-first is a business advantage:** inference and storage happen on the user's machine, so gross margin on subscriptions is exceptionally high (no per-user GPU/token cost floor), and privacy is a genuine differentiator for the target personas (solo founders, indie devs, PMs, technical creators, small team leads) who are wary of sending code and ideas to third-party clouds.

---

## 2. Pricing Tiers

| Tier | Price | Who it's for | What's included |
|------|-------|--------------|-----------------|
| **Free** | $0 | Trial users, hobbyists, evaluators | Full local workbench: Workspace, Generate (Wizard/YOLO/Bulk), Studio basics (transcription, notes), Global Search, Command Center, Logs & Traces. Bring your own local model. |
| **Pro** | **$20 / user / mo** ($192/yr) | Solo founders, indie devs, technical creators | Everything in Free + Skill Builder, Flow Builder, Control Center, Prototype Builder + Test, Video Studio, embedded Terminal, unlimited runs, priority updates. |
| **Team** | **$40 / user / mo** ($384/yr, 3-seat min) | Small teams, product squads | Everything in Pro + shared workspaces, admin & permissions, encrypted cloud sync included, team marketplace/private skills, SSO (later), priority support. |
| **Cloud Sync add-on** | **$6 / user / mo** | Free/Pro users wanting sync | Cross-device encrypted sync & backup (included in Team). Metered infra, priced for margin. |
| **Marketplace** | **15% take-rate** | Creators & buyers | Dobby retains 15% of each skill/flow/app sale; creator keeps 85%. (Compares favorably to 30% app-store norms — a supply-side acquisition lever.) |

Annual billing offered at ~2 months free (~17% discount) to improve cash collection and retention.

---

## 3. Unit Economics Hypotheses (illustrative)

- **Subscription gross margin: ~90%+.** Local-first means no inference/token cost per user; COGS is limited to payments processing (~3%), optional sync infra for the minority who use it, and support.
- **Blended ARPU (paying users): ~$22/mo** as the mix skews Pro-heavy early, rising as Team adoption grows.
- **Free → Paid conversion hypothesis: 3–5%** of active installs (typical for a genuinely useful freemium dev tool with strong paid triggers behind Automate/Build features).
- **CAC: low.** Distribution is developer-community-led (open ecosystem, launch moments, word-of-mouth, marketplace creators as advocates), targeting a **CAC payback < 4 months** and **LTV:CAC > 4:1**.
- **Logo churn hypothesis: ~4–5%/mo early, trending to ~2–3%** as Automate/Build workflows create switching cost (a user's skills, flows, and app scaffolds live in Dobby).
- **Marketplace contribution:** at 15% take-rate, marketplace revenue is high-margin and grows with supply; modeled as a small contributor in year 1 and a meaningful third leg by year 2+.

---

## 4. Illustrative Revenue Ramp (12–24 months)

Assumes public beta at end of P4 (~Mo 8), paid tiers live at P5, marketplace transactions at P6. **Illustrative only.**

| Milestone | ~Timing | Active installs | Paying users | MRR (illustrative) | Notes |
|-----------|---------|-----------------|--------------|--------------------|-------|
| Beta launch | Mo 8 (end P4) | 3,000 | 0 | $0 | Free, community-seeded |
| Paid live | Mo 10 (P5) | 8,000 | ~250 | ~$5.5k | First Pro conversions |
| Marketplace live | Mo 12 (P6) | 15,000 | ~600 | ~$14k | + early take-rate |
| Mo 18 | +6 mo | 40,000 | ~1,800 | ~$45k | Team traction begins |
| Mo 24 | +12 mo | 90,000 | ~4,500 | ~$120k | Marketplace ~15% of revenue; approaching ~$1.4M ARR run-rate |

This ramp underwrites the Series A milestone (~$1M+ ARR run-rate with healthy retention and a live two-sided marketplace) within the 18-month funded runway.

---

## 5. Use of Funds ($2.2M seed, ~18-month runway)

- **People — 78%.** The build is the moat; nearly all capital converts to engineering, product, design, and (later) DevRel. See `team.json`.
- **Infrastructure & Compute — 6%.** CI/CD, cross-platform code signing/notarization, P4 GPU for media/video model dev, and the lean P6 sync/marketplace backend. Kept small by local-first design.
- **Marketing & Community — 6%.** Launch moments, developer-ecosystem seeding, and creator acquisition for the marketplace.
- **Tools & Software — 3%.** SaaS stack.
- **Legal & Compliance — 3%.** Formation, IP, and marketplace terms/revenue-share/content policy.
- **Contingency — 4%.** Reserve for hiring slips and unplanned spend.

The 12-month build plan totals ~$1.13M (see `budget.json`); the ask sizes ~18 months so the team can hit the Series A milestone without an emergency re-raise.

---

## 6. Resourcing Plan (narrative)

The team ramps deliberately from ~3.5 FTE-equivalent to 6, tracking the phased roadmap so we never carry capacity ahead of the work:

- **P1 (Mo 1–2, Foundations & Findability):** Founder/Product, Senior Full-stack (Tauri/React), and Backend/AI engineer, plus a part-time designer. This trio ships the categorized 6-group UI redesign, Global Search (local embeddings + full-text), Command Center (⌘K), and Logs & Traces — the findability foundation everything else plugs into.
- **P2 (Mo 3–4, Media & Capture Studio):** ML/Media engineer joins to own local Whisper/STT transcription, YouTube→Notes, and Notes Builder, while the full-stack/backend pair adds the sandboxed, approval-gated Terminal.
- **P3 (Mo 5–6, Automation):** Backend/AI leads the Skill Builder runtime, Flow Builder engine, and Control Center (agents/permissions/orchestration); full-stack builds the visual builder UIs. This is the phase that turns Dobby from tools into a platform.
- **P4 (Mo 7–8, Build & Generate):** Designer converts to full-time as surface area explodes. ML/Media leads Video Generation; full-stack + backend build Prototype Builder + Test. Public beta ships at the end of this phase.
- **P5 (Mo 9–10, Local Marketplace):** DevRel/Community lead joins to seed the ecosystem and ship the publishing SDK/docs; engineering delivers local install/manage of skills/flows/apps and the SDK. Paid tiers go live.
- **P6 (Mo 11–12, Publish & Cloud):** Publish-to-shared-marketplace, encrypted cloud sync, and monetization rails (subscriptions + take-rate). The lean cloud backend is introduced here and nowhere earlier.

Hiring is staged to phase need, keeping burn low early and concentrating spend when the roadmap demands specialized skills (media in P2/P4, ecosystem in P5/P6).

---

## 7. Key Financial Risks

- **Concentration in People.** ~78% of spend is headcount; a mis-hire or comp overrun materially moves burn. Mitigation: staged hiring against phase gates, contract-to-hire for design, and a contingency reserve.
- **Monetization timing.** Revenue only starts at P5 and marketplace take-rate at P6, so all of year 1 is pre-revenue burn. Mitigation: 18-month runway buffer beyond the 12-month build; ability to pull the paid tier forward if beta demand is strong.
- **Marketplace cold-start (two-sided).** Take-rate revenue depends on creator supply and buyer demand arriving together. Mitigation: DevRel-led supply seeding, favorable 15% (vs. 30%) split, and dogfooded first-party skills/flows.
- **Freemium conversion uncertainty.** The 3–5% conversion hypothesis is unproven for this product; local-first also means we see less usage telemetry to optimize with. Mitigation: clear paid triggers behind Automate/Build, privacy-respecting opt-in analytics, and fast iteration on the paywall.
- **Bring-your-own-model UX friction.** Requiring users to run local models can raise setup friction and support load, dampening top-of-funnel. Mitigation: guided model setup, sensible defaults, and optional cloud fallback for onboarding.
- **Platform/distribution dependence.** Desktop code signing, notarization, and OS policy changes across macOS/Windows/Linux add cost and risk. Mitigation: budgeted signing infra and cross-platform CI from P1.
- **Fundraising-market risk.** The plan assumes a Series A is reachable on ~$1M+ ARR run-rate within 18 months; a slower ramp compresses runway. Mitigation: the Lean scenario ($720k, 4 people) is a viable fallback that still ships P1–P4 on a smaller raise.
