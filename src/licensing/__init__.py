"""
Licensing v1 — the verification mechanism, built ahead of billing.

Per the locked decision (docs/expansion/08_LICENSING_AND_PRICING_DECISION.md
§7): billing integration (Lemon Squeezy/Paddle/Stripe checkout) is deferred
until the product is feature-complete and has 1,000 beta users. The
license-key *verification* mechanism has no dependency on that and is built
now — keys can be hand-issued via the `dobby license issue` CLI until checkout
exists.

Two roles, kept in separate modules on purpose:

* **Authority** (`authority.py`) — issues and revokes licenses, holds the
  Ed25519 *private* key. This is what would run on a real license server at
  launch. It is reachable here as ordinary API routes for development
  convenience, but the moment there is a real deployed server, this is the
  half that moves there and never ships inside the desktop build.
* **Client** (`client.py`) — verifies a license the user has activated, holds
  only the *public* key, and detects a rolled-back system clock. This is what
  actually ships in the app.

Mixing these into one process today is a deliberate, temporary simplification
for development, not the target architecture — see the module docstrings for
where the seam is.
"""
