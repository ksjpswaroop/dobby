# Week Plan — Jul 27 to Aug 2, 2026

**Goal of the week:** close the commercialization gap from doc 07 far enough to run a **private beta with real paying customers by Sunday night.** Not a public launch — a public launch needs a beta feedback cycle first (Week 2, see doc 10). This week builds the floor everything else stands on: you can charge someone money, give them a build that opens without a security warning, and have somewhere to send them.

Each day has a **You** column (needs your identity, accounts, or judgment — I cannot do these) and an **Engineering** column (code, config, content I can build directly). Do the **You** items first thing each morning; they often have processing delays that should run in the background while engineering work happens.

**Start today (Sunday), not Monday** — two items have external processing time:
- Enroll in the **Apple Developer Program** ($99/year, developer.apple.com) — needed for Wednesday's signing work.
- Create accounts with **Lemon Squeezy** (or Paddle) and **Stripe** — needed for Tuesday. Lemon Squeezy in particular has a store-approval review that can take a few hours to a day.

---

## Monday, Jul 27 — Decisions locked + Licensing v1

**You:**
- Confirm the three decisions from doc 08 §5 (open-core, perpetual+annual pricing, payment processor). Everything below assumes the recommended answers unless you say otherwise.
- Register a domain if you don't have one (needed Thursday). Suggest checking `dobby.app`, `usedobby.com`, `getdobby.ai` availability now.

**Engineering:**
- `src/licensing/` module: license record model (SQLite table: id, tier, seats, email, issued_at, updates_until, revoked_at), Ed25519 or RSA key-pair signing, `issue_license()`, `verify_license(key) -> LicenseInfo`.
- Local verification against a public key embedded in the build — **no network call required to run**. Grace logic: an expired/missing license runs the free (open-core) feature set; a valid-but-update-expired license keeps running its already-unlocked features, just stops auto-updating.
- CLI: `dobby license issue --email --tier --seats` for manually issuing keys before the payment webhook exists (unblocks Tuesday and lets you hand-issue beta keys tonight if needed).
- Settings UI: an "Activate license" field, "Your plan: Free / Pro / Team" indicator.

**Definition of Done:** `dobby license issue` produces a key; pasting it into the app activates Pro features locally with zero network calls; deleting the license file gracefully falls back to Free rather than crashing.

---

## Tuesday, Jul 28 — Payments live

**You:**
- Finish Lemon Squeezy/Paddle store setup: product listing for "Dobby Pro" ($49 launch price), webhook secret, test-mode API key.
- Set up Stripe (or your processor's equivalent) for the Team tier as an invoiced/manual-approval flow rather than instant self-serve, since seats and terms vary per deal.

**Engineering:**
- `src/api/billing_routes.py`: webhook receiver for `order_created`/`payment_succeeded` events, signature-verified (same pattern as the Slack/Telegram webhook work already in the codebase — verify before parsing, never trust an unsigned payload).
- On a verified successful payment: call `issue_license()`, then email the key using the processor's built-in email or a simple transactional-email hook (Postmark/Resend — pick one, needs an account, ~10 minutes).
- A minimal `/checkout` redirect page (can be a Lemon Squeezy-hosted checkout link embedded on the landing page — no need to build a custom checkout form for v1).
- Test end-to-end in the processor's test mode: fake purchase → webhook fires → license key emailed.

**Definition of Done:** a test-mode purchase results in a real license key landing in an inbox within seconds, with zero manual steps.

---

## Wednesday, Jul 29 — Signed, notarized, auto-updating

**You:**
- Confirm Apple Developer enrollment has completed (started Sunday); if there's a delay, this day's macOS signing work blocks — have a fallback ready (ship Day 1 beta unsigned with explicit "right-click → Open" instructions to the 20-30 people you already trust; do not let this block Sunday's beta invite if enrollment is still pending).

**Engineering:**
- Wire `signingIdentity` in `tauri.conf.json` to the Developer ID certificate; add notarization step (`xcrun notarytool`) to the build script.
- Configure the Tauri updater plugin: a static JSON manifest hosted wherever the landing page lives (even a GitHub Pages/S3 file is fine for v1 — no need for a dynamic update server yet), signed with a dedicated update-signing key (separate from the license-signing key).
- Bump version to `1.0.0-beta.1` across `pyproject.toml` and `tauri.conf.json` — today is the day this stops being an internal `0.1.0`/`2.0.0` mismatch and becomes a real, coherent version a beta user can reference when reporting a bug.
- Produce the first signed DMG and confirm it opens cleanly on a **different** Mac than your dev machine (borrow one, or a clean VM) — this is the test that actually matters; your own machine has your dev certs and Gatekeeper exceptions already trusting things.

**Definition of Done:** a signed DMG opens with no Gatekeeper warning on a machine that has never seen this app before. Auto-update manifest is reachable at a public URL.

---

## Thursday, Jul 30 — Landing page, pricing, legal

**You:**
- Write (or review a draft I produce) the actual product copy — voice and positioning decisions are yours; I can draft, you should not ship copy you haven't read.
- Pick which legal templates to use (Termly, GetTerms, or a lawyer if you have one on retainer) — I can draft an EULA/Privacy Policy/Refund Policy from the standard local-first/no-telemetry-by-default facts of this app, but **have someone with legal authority sign off before it's live**, especially the refund policy tied to real payments going live tomorrow.

**Engineering:**
- A single-page static site (plain HTML/CSS, no framework needed for v1 — speed to ship beats polish this week): hero, three pricing cards matching doc 08 §3, feature highlights pulled honestly from doc 07's "genuinely built" list (not aspirational features), a beta-waitlist form, embedded Lemon Squeezy checkout buttons for the two self-serve tiers.
- Draft EULA, Privacy Policy (should state plainly: local-first, no telemetry unless the user opts into remote model providers, which the app already discloses per-provider), Refund Policy (recommend: no-questions 14-day refund on the individual tier — it removes the single biggest purchase-hesitation for a $49-79 tool).
- Deploy to the domain from Monday.

**Definition of Done:** the domain resolves to a live pricing page; a real (test-mode) purchase completes from the page to an inbox; legal pages are linked from the checkout flow, not just floating unlinked in a footer.

---

## Friday, Jul 31 — White-label packaging + Team tier + onboarding

**You:**
- Identify 3-5 realistic white-label conversation targets this weekend (agencies serving your target customer segments, or a company already building on Ollama/local-LLM tooling that would rather license than build). This is outreach-list-building, not a call yet — that starts Week 2 per doc 10.

**Engineering:**
- Config-driven rebrand: extract app name, icon, and accent color into a single `brand.json` consumed at build time, so producing "Acme AI Workbench powered by Dobby" is a build-flag away, not a fork. This is the technical core of the white-label offer — without it, every white-label deal requires bespoke engineering, which kills the economics.
- Team tier: multi-seat license activation (one key, N machines, seat count enforced client-side with server-side seat-count truth once there's a server — v1 can be honor-system with a visible seat counter, tightened later).
- First-run onboarding: a 3-step "what do you want to do" flow (Generate a spec / Research a topic / Automate something) replacing the current cold-dashboard-with-45-seeded-features experience, since that's real conversion friction for a first-time paying user.

**Definition of Done:** running the build script with a different `brand.json` produces a distinctly-branded DMG without touching application code; a first-time user reaches their first generated document within 3 clicks of opening the app.

---

## Saturday, Aug 1 — QA pass + closed beta invite

**You:**
- Personally run the app start-to-finish on a machine you don't normally use, pretending to be a stranger. This finds more real bugs in an hour than a week of you using your dev setup.
- Send the beta invite (with the real, signed, updatable, licensed build) to 25-50 people — mix of individuals who'd pay $49-79 and 1-2 people at organizations who might plausibly buy Team seats.

**Engineering:**
- Fix whatever your Saturday-morning stranger-test surfaces — reserve the day for this rather than new features. A rough rule: if it's not on the critical path (install → activate → generate one document successfully), it waits until Week 2.
- Set up the simplest possible feedback channel (a shared form, or a dedicated Slack/Discord channel, or just "reply to this email") — don't build a support ticketing system this week, that's premature.

**Definition of Done:** 25+ real humans outside your household have the app installed and running, and you have a way to hear from them when something breaks.

---

## Sunday, Aug 2 — Launch assets + Week 2 go/no-go

**You:**
- Read every piece of beta feedback that's come in over ~18 hours. Triage: does anything block a public launch (data loss, crash on first run, payment failure) vs. can wait?
- Make the go/no-go call for Week 2's public launch (doc 10, Phase 1) based on that triage — don't launch publicly on a broken payment flow just because the calendar says Week 2.

**Engineering:**
- Draft the Product Hunt / Show HN launch post and a one-page press kit (screenshots, one-paragraph description, pricing, your name/contact) — drafts I can write from doc 07's real feature list; you should be the one who publishes.
- Stand up a public "join the waitlist" or "we're in beta" state on the landing page if the go/no-go call is "not quite yet" — never leave the domain looking abandoned.

**Definition of Done:** a written go/no-go decision for Monday, with the top 3 blocking issues (if any) named explicitly, and launch assets ready to ship the moment the answer is "go."

---

## What this week does *not* attempt

Being explicit about scope protects the plan. Not this week: the marketplace/apps ecosystem, SSO, enterprise procurement paperwork (SOC2 questionnaires, MSAs), localization, mobile, a dynamic (non-static-JSON) update server, or server-side seat-count enforcement for Team licenses. All of these are real, and all of them are Week 2+ or later — see doc 10.
