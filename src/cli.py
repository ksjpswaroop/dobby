"""
Dobby command-line interface.

A small, dependency-light CLI (stdlib argparse + httpx) that replaces the old,
broken `src.cli:app` entry point. It manages the local service rather than
re-implementing generation — the desktop app and REST API are the primary UI.

Usage:
    dobby serve [--host H] [--port P] [--reload]
    dobby version
    dobby models
    dobby health
"""

from __future__ import annotations

import argparse
import sys

from src.settings.store import APP_VERSION, get_settings


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def _version(_args: argparse.Namespace) -> int:
    print(f"Dobby v{APP_VERSION}")
    return 0


def _models(_args: argparse.Namespace) -> int:
    import httpx

    host = get_settings().ollama_host
    try:
        resp = httpx.get(f"{host}/api/tags", timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        print(f"Cannot reach Ollama at {host}: {e}", file=sys.stderr)
        return 1

    models = resp.json().get("models", [])
    if not models:
        print("No models installed. Pull one with: ollama pull llama3.2")
        return 0
    active = get_settings().model
    for m in models:
        name = m.get("name", "")
        size_gb = (m.get("size", 0) or 0) / 1e9
        marker = "*" if name == active or name.split(":")[0] == active else " "
        print(f" {marker} {name:<32} {size_gb:6.1f} GB")
    print("\n* = active model")
    return 0


def _license_db():
    import os
    from pathlib import Path

    from src.db.schema import init_database

    path = os.environ.get("DOBBY_DB_PATH", str(Path.home() / ".dobby" / "dobby.db"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return init_database(path)


def _license_issue(args: argparse.Namespace) -> int:
    """Hand-issue a license key. Works with the server stopped — this and the
    payment webhook (once it exists) are the only two things that ever call
    `authority.issue()`; everything else only verifies."""
    from src.licensing import authority

    try:
        out = authority.issue(_license_db(), args.tier, args.email, args.seats,
                              args.update_days)
    except authority.LicenseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"License {out['license_id']} ({out['tier']}, {out['seats']} seat(s))")
    print(f"Updates until: {out['updates_until'] or 'never expires'}")
    print(f"\n{out['token']}")
    return 0


def _license_revoke(args: argparse.Namespace) -> int:
    from src.licensing import authority

    if authority.revoke(_license_db(), args.license_id):
        print(f"Revoked {args.license_id}")
        return 0
    print(f"No such license: {args.license_id}", file=sys.stderr)
    return 1


def _license_verify(args: argparse.Namespace) -> int:
    from src.licensing import authority

    try:
        result = authority.verify(_license_db(), args.token)
    except authority.LicenseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(result)
    return 0 if result["valid"] else 1


def _health(_args: argparse.Namespace) -> int:
    import httpx

    try:
        resp = httpx.get("http://localhost:8000/health", timeout=5.0)
        resp.raise_for_status()
        print(resp.json())
        return 0
    except httpx.HTTPError as e:
        print(f"Backend not reachable: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dobby", description="Dobby document platform")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_serve)

    sub.add_parser("version", help="Print version").set_defaults(func=_version)
    sub.add_parser("models", help="List installed Ollama models").set_defaults(func=_models)
    sub.add_parser("health", help="Check backend health").set_defaults(func=_health)

    p_license = sub.add_parser("license", help="Manage licenses").add_subparsers(
        dest="license_command", required=True
    )
    p_issue = p_license.add_parser("issue", help="Issue a new license key")
    p_issue.add_argument("--tier", required=True, choices=("pro", "team", "white_label"))
    p_issue.add_argument("--email", default="")
    p_issue.add_argument("--seats", type=int, default=1)
    p_issue.add_argument("--update-days", type=int, default=365, dest="update_days",
                         help="Days of updates included; omit/0 for perpetual")
    p_issue.set_defaults(func=_license_issue)

    p_revoke = p_license.add_parser("revoke", help="Revoke a license")
    p_revoke.add_argument("license_id")
    p_revoke.set_defaults(func=_license_revoke)

    p_verify = p_license.add_parser("verify", help="Verify a license token")
    p_verify.add_argument("token")
    p_verify.set_defaults(func=_license_verify)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
