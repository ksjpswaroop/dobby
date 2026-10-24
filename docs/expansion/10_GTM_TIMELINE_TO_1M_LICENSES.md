# Go-to-Market Timeline — path to 1,000,000 licenses

**Direct answer to "when can we go to market": private beta is achievable by Sunday, Aug 2, 2026, if this week's plan (doc 09) executes. Public launch is realistically 2-3 weeks out** — gated on beta feedback, not the calendar, per the Sunday go/no-go call. GTM prep (positioning, landing page, launch assets, waitlist building) does not wait for engineering to finish — it runs in parallel starting Monday.

**Direct answer on the 1,000,000 target: it is reachable in a 18-30 month horizon, but not through direct-to-individual sales alone.** The honest math is in section 3. Read it before treating 1M as a marketing-execution problem rather than a distribution-strategy one.

---

## 1. Phased rollout

| Phase | Timing | What happens | Target |
|---|---|---|---|
| **0 — Private beta** | Aug 2–9 (Week 2) | 25-50 hand-picked users on the signed, licensed, updatable build. Feedback loop, bug triage, no public marketing. | 0 paid — this phase is about not breaking anything, not revenue |
| **1 — Soft/public launch** | Week 3 (~Aug 10-16), conditional on Phase 0 go | Product Hunt, Show HN, your existing network, launch-price ($49) individual licenses live for real payment | 300–1,500 paid individual licenses in the launch week |
| **2 — Public v1.0** | Month 2 (Sept) | Content marketing begins (comparison posts, YouTube walkthroughs), price moves to standard $79, first outbound to the white-label target list from Friday of Week 1 | cumulative 1,500–4,000 paid |
| **3 — Growth** | Months 3-6 | SEO/content compounding, first Team-tier deals closed, **first white-label pilot signed** (this is the phase where the 1M question actually gets answered directionally), marketplace beta (see §4) | cumulative 15,000–40,000 |
| **4 — Scale** | Months 6-12 | White-label program formalized with 2-3 signed partners, enterprise outbound motion (SDR + case studies), marketplace revenue share live | cumulative 100,000–300,000 |
| **5 — Push to 1M** | Year 2 | Contingent almost entirely on whether Phase 4's white-label/OEM deals include a partner with existing distribution in the hundreds of thousands to millions (an OEM bundling Dobby on shipped devices, or a platform embedding it for their own large user base) | 500,000–1,200,000 **if** 1-2 large distribution deals land; 150,000–400,000 if they don't |

## 2. Why the phasing is conservative on purpose

A tool with zero paying customers today, no signed build, and no landing page reaching "1,000,000 licenses" on an aggressive timeline is the kind of plan that looks impressive in a deck and produces nothing but disappointment in execution. The phasing above assumes normal friction: beta users find real bugs, launch week converts at realistic rates (1-3% of visitors for a $49-79 desktop tool is good, not average), and enterprise/white-label sales cycles run 2-6 months from first conversation to signed contract, not weeks. If any phase runs ahead of this, treat it as good news and pull the next phase forward — don't plan around the optimistic case.

## 3. The honest math on 1,000,000

Direct-to-individual PLG products reaching 1M *paying* individual customers exist, but they are rare, and they share a trait Dobby doesn't yet have: a viral loop or a near-zero price point (freemium apps with hundreds of millions of installs, sub-$10 price points, or network effects where each user brings others). At $49-79 for a developer/builder tool, a realistic ceiling for pure organic + content-marketing individual sales over 2 years is in the **low hundreds of thousands**, not a million — and that's a genuinely good outcome for a bootstrapped or seed-stage product.

**The lever that changes the math is white-label/OEM distribution**, because it converts "sell one license at a time" into "sell one contract that includes tens of thousands of end-user seats." Concretely:

- One mid-size white-label partner (an agency or platform with 20,000 existing customers) bundling Dobby access adds 20,000 units in one signed deal — equivalent to roughly a year of organic direct sales.
- One larger OEM/platform deal (a company shipping to millions of devices or users, licensing Dobby's local-AI-workbench capability as an embedded feature) is the only realistic single event that gets the cumulative number into 7 figures within 24 months.

**This is why doc 09 puts white-label target-list-building on Day 5 of Week 1, not Month 6.** Treat direct individual sales as the credibility engine (real users, real reviews, real revenue, a working funnel to show partners) and white-label/OEM conversations as the volume engine, run in parallel from the start rather than sequentially.

**What you should actually track weekly** is not "progress toward 1,000,000" as a single number — it's three separate funnels: (a) individual conversion rate and MRR, (b) number of white-label conversations in each stage (contacted / demoed / negotiating / signed), (c) marketplace supply once it exists. The 1M outcome is a function of (b) far more than (a).

## 4. "Add more apps as we go along" — the technical path is already half-built

This maps directly onto work already shipped in the last two weeks, which is worth knowing because it means this isn't a new engineering track — it's packaging what exists:

- **Personas** (built, tested, shipped) are already "a named way of working" — a system prompt, declared capabilities, recommended connections, an install-with-consent flow. An "app" in the marketplace sense is a persona bundled with a specific workflow and a curated set of MCP connectors.
- **The MCP client** (built, tested, verified against a real server) means any of the hundreds of existing MCP servers in the wild — filesystem tools, database connectors, SaaS integrations — can become a Dobby capability without custom integration work per app.
- **The Inbox/approval gate** means a third-party "app" installing declared capabilities is already safe by construction — capabilities are a ceiling the Inbox enforces, not a grant the app author controls.

**Recommended sequencing for "more apps":**
1. **Now–Month 2:** ship 3-5 first-party "app packs" yourselves (e.g., "Competitive Research Pack," "Weekly Ops Digest Pack," "Codebase Onboarding Pack") using the persona + MCP-connector combination that already exists — this proves the packaging format before anyone else uses it.
2. **Month 3-6:** open a private submission process for a handful of trusted third-party app authors, reusing the existing persona install-consent-with-warnings flow as the review gate.
3. **Month 6-12:** a real marketplace surface (the roadmap already has this at P5/P6 in `04_ROADMAP_AND_PROJECT_PLAN.md`) with the 15% take-rate model from `05_BUSINESS_PLAN.md` — by this point there's real usage data on which app packs people actually want, rather than guessing up front.

## 5. What "GTM" work starts this week, in parallel with engineering

To be explicit, since doc 09 is engineering-day-shaped: GTM is not a Week-3 activity that waits for a finished product.

- **This week:** landing page copy, pricing page, the white-label target list (doc 09, Friday), the Product Hunt/Show HN draft (doc 09, Sunday), beta-invite list of 25-50 names.
- **Week 2:** beta feedback → testimonial/quote mining (ask every beta user if you can quote them — this is next week's launch-page social proof, and it doesn't exist yet), first outbound emails to the white-label list (a conversation-starter, not a pitch — "we're building X, thought it might be relevant to what you do, worth 15 minutes?").
- **Week 3 (launch):** the actual Product Hunt/HN post, a short demo video (screen recording of Wizard → generated spec → automation running unattended is the single most convincing 90 seconds you can show), and direct outreach to any journalists/newsletter writers who cover local-first/AI-dev-tools.

## 6. Risks worth naming now, not discovering in Week 3

- **The unsigned-build trust problem is real and immediate.** If Wednesday's Apple Developer enrollment is delayed, do not launch publicly on an unsigned build — the Gatekeeper warning will tank conversion and the support burden of talking strangers through "right-click → Open" doesn't scale past a trusted-friends beta.
- **Local-first is a genuine differentiator, but it cuts against instant frictionless SaaS onboarding** (no "sign up in your browser in 10 seconds" — there's a download and an install). Lean into privacy/ownership as the pitch rather than fighting the friction; don't try to make Dobby feel like a web app, it isn't one and shouldn't pretend to be.
- **White-label deals take real time and a real point of contact.** Starting the target list this week (doc 09, Friday) is about not losing 2-3 months of sales-cycle time to a late start, not about closing anything quickly.
- **The MIT/open-core tension (doc 08) needs to be genuinely resolved, not left ambiguous.** A prospective white-label partner's first question will be "what exactly am I licensing if the code is public?" — have a crisp answer (signed builds, brand rights, support, updates) before that conversation happens, not during it.
