# Licensing & Pricing — the decision that gates Monday

This document exists because "sell 1 million licenses" and "the repo is MIT" are two true statements that need one reconciling decision before any entitlement code gets written. Read this before Day 1 of the week plan.

---

## 1. What MIT actually means for you here

Anyone can `git clone`, build, and run every feature described in doc 07 — the full generation pipeline, research, automations, approvals, MCP, personas, transcription, messaging — for free, forever, including modifying and redistributing it. This was a deliberate choice recorded in project memory (*"MIT + commercial, so no NC/copyleft third-party code"*), and it's a legitimate model — Sentry, GitLab CE, n8n (pre-license-change), and Docker all monetized around genuinely open code. But it means **you cannot sell "access to the features."** You can only sell things the free path doesn't include.

## 2. What is actually sellable

| Sellable | Why the free/OSS path doesn't include it |
|---|---|
| A signed & notarized build | Building it yourself requires an Apple Developer account, a Windows code-signing cert, and knowing how to configure Tauri's signing pipeline. Most buyers won't. |
| Automatic updates | Requires an update server and a private signing key you control. A self-built copy has no update channel. |
| Support & SLA | Cannot be forked. |
| Hosted add-ons (optional cloud sync, hosted model access) | Requires infrastructure you run. |
| The brand / trademark ("Dobby") | Someone can fork the code but cannot legally call their fork "Dobby" or use your marks. |
| White-label / resale rights | A contractual grant, not a code feature — this is licensing in the legal sense, not the software-gate sense. |
| Marketplace access (once built) | A hosted service, not local code. |

**Recommendation: open-core.** Keep the current MIT core as the free tier — it's already true today, costs nothing to maintain as a decision, and is a genuine PLG asset (developers trust and share tools they can audit). Sell the six rows above as **Dobby Pro / Team / White-Label**, delivered as: a signed installer + license key that unlocks auto-update and a small number of hosted conveniences, checked with a generous offline grace period so it never breaks the local-first promise for a legitimate paying user who's on a plane.

This needs your explicit sign-off — it changes what Monday's entitlement system checks (a build/update gate, not a feature gate) and what marketing says ("free forever, core" vs. "free trial").

**If you'd rather go closed-source for new work going forward** (dual-license: MIT for everything already committed, proprietary for new premium modules), that's also viable and common (Elastic, MongoDB did versions of this) — flag it now, because it changes which files the entitlement check needs to gate and adds a CLA/contribution question. Absent a decision, **the plan below assumes open-core.**

---

## 3. Pricing — reconciling "sell licenses" with the existing subscription plan

`05_BUSINESS_PLAN.md` already specifies a SaaS-subscription model ($20/mo Pro, $40/mo Team, 15% marketplace take-rate). That model is fine for a Team/Corporate tier but doesn't match "license" framing well for individuals, and pure monthly subscription is a slower path to unit volume than a low-friction one-time or annual purchase — the friction of a recurring card charge is the single biggest drop-off point for desktop tools sold direct to individuals.

**Recommended structure — three tracks, matching your three stated markets:**

### Individual — "Dobby Pro"
- **$79 one-time** (perpetual license, includes 1 year of updates) — the primary volume driver. Familiar pattern (Sublime Text, Tower, CleanMyMac).
- **$29/year** to continue receiving updates after year one (skippable — an unrenewed license keeps working, just stops updating).
- Launch price: **$49** for the first 30 days / first 1,000 licenses, to reward early adopters and create urgency without discounting forever.
- What it unlocks beyond free: signed/notarized build, auto-update, priority model-routing defaults, cloud sync add-on eligibility.

### Corporate / Team — "Dobby Team"
- **$299/seat/year**, 5-seat minimum, volume discounts at 25/100 seats.
- Adds: shared workspace config, admin/permission controls, SSO (when built), priority support, invoicing (not just card checkout).
- This is the existing `05_BUSINESS_PLAN.md` Team tier, repriced as an annual license rather than $40/mo, because procurement teams buy annual licenses more readily than they approve recurring monthly SaaS line items below a certain deal size.

### White-Label / OEM
- **$15,000–$50,000 setup/license fee** (covers rebrand engineering support, brand-clearance review, dedicated Slack channel) **+ either:**
  - a **15–25% revenue share** on the partner's resale price, or
  - a **flat wholesale rate** (e.g., $15–25/seat/year) if the partner is bundling Dobby into a much larger existing product or device at volume.
- This tier is the one that actually gets you to 1,000,000 units in a plausible timeframe — see doc 10, section 3. Treat it as a top GTM priority starting Day 1, not something to defer until direct sales prove the concept.

### Blended economics — say it out loud
At the $79 individual price, 1,000,000 licenses = **$79M** in gross license revenue if every unit were sold at retail. That will not happen — white-label wholesale units will sell far below $79 each. A more honest blended estimate across a realistic mix (mostly white-label volume, a minority of direct retail) is **$15–40 effective average per license**, i.e. **$15M–$40M** at 1,000,000 units. Both are large, credible outcomes for a two-year horizon *if* one or two white-label deals land — and correspondingly small if they don't. Doc 10 makes this explicit.

---

## 4. What Monday's entitlement system needs to check

Given the open-core decision above, the technical shape is narrow and buildable in a day:

- A **license record**: id, tier (`pro` / `team` / `white_label`), seats, issued-to, expiry (updates-expiry, not usage-expiry — a lapsed license still runs).
- A **license key** (signed JWT or similar), issued at purchase, validated locally against a public key baked into the signed build — **no phone-home required for the app to run**, preserving local-first. An optional, non-blocking "check for updates" ping is fine; a mandatory online activation is not, and would contradict everything Dobby stands for.
- **Grace, not lockout.** An expired update-license should never stop the app working — it should just stop offering updates and gently suggest renewal. A local-first tool that bricks itself offline is a trust-destroying bug, not a licensing feature.
- **A generator/admin tool** (internal, CLI is fine) to issue keys after a successful payment webhook — this is the piece that connects Tuesday's payment integration to Monday's license system.

Full spec lives in [09_WEEK_PLAN.md](09_WEEK_PLAN.md), Day 1 and Day 2.

---

## 5. Decisions needed from you before Monday

1. **Open-core (recommended) vs. dual-license going forward?**
2. **Perpetual + annual-update pricing (recommended) vs. pure subscription (the existing doc)?**
3. **Payment processor:** recommend **Lemon Squeezy or Paddle** over raw Stripe for the individual tier — both act as Merchant of Record, meaning *they* handle global sales-tax/VAT compliance, which raw Stripe does not. This matters immediately if you're selling to individuals worldwide. Stripe Billing is fine for the Corporate tier (invoiced, fewer, larger transactions, less tax complexity per deal).
4. **Apple Developer Program enrollment** ($99/year) — needs your Apple ID and payment to start; this has a real-world processing delay (usually same-day, occasionally 24-48h) so it should be started **today**, not Monday, so it isn't the thing blocking Wednesday's signing work.
5. **White-label as a Day-1 GTM priority, not a Month-6 one** — confirm this reprioritization, since it changes what "GTM" work happens in parallel with engineering this week (doc 10 assumes yes).
