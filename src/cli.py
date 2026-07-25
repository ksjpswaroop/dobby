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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
