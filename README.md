# Dobby 🧝

**Local-first, interactive document development platform.**

Dobby turns a feature idea into a verified set of engineering artifacts —
specification, user story, functional analysis, flowchart, pseudocode, TDD
tests, and documentation — using a local LLM via [Ollama](https://ollama.com).
Everything runs on your machine: no API keys, no data leaves the box.

## How it works

Dobby is a graph-of-nodes model backed by SQLite, driven by two generation modes:

- **Wizard** — a 7-step guided flow. Each step is generated, then checked by a
  **deterministic verifier** (rule-based, no second LLM), and only saved once it
  passes the quality bar. You can edit and regenerate any step.
- **YOLO** — generate all 7 artifacts in one pass, review the result, then
  accept (finalize) or reject (discard).
- **Bulk** — paste many ideas at once and generate every document for all of
  them concurrently, with a coverage matrix showing each document's score and
  any gaps.

Both write to a dependency **graph** you can visualize, and features are ranked
in a **backlog** by a Pareto score: `impact·0.6 − effort·0.3 − risk·0.1`.

## Architecture

```
┌──────────────┐    Tauri IPC / HTTP    ┌──────────────┐     ┌──────────┐
│  Desktop UI  │ ─────────────────────▶ │  FastAPI     │ ──▶ │  SQLite  │
│ (React/Tauri)│                        │  (src/api)   │     │  graph   │
└──────────────┘                        └──────┬───────┘     └──────────┘
                                               │
                                     ┌─────────┴──────────┐
                                     │ Wizard / YOLO       │
                                     │ pipelines           │
                                     │  • OllamaClient      │
                                     │  • DeterministicVerifier
                                     └─────────┬──────────┘
                                               ▼
                                          ┌──────────┐
                                          │  Ollama  │ (llama.cpp)
                                          └──────────┘
```

The desktop UI uses **dual transport**: Tauri IPC when packaged, or plain HTTP
to the FastAPI backend when run as a web app.

## Quickstart

```bash
# 1. Backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
dobby serve                      # FastAPI on http://localhost:8000

# 2. Ollama (in another shell)
ollama serve
ollama pull llama3.2

# 3. Desktop UI
cd tauri-app
npm install
npm run tauri dev                # or `npm run dev` for the browser (web) app
```

## CLI

```bash
dobby serve [--host H --port P --reload]   # run the API server
dobby models                               # list installed Ollama models (* = active)
dobby version
dobby health                               # check a running backend
```

## Managing models

The desktop app's **Settings** screen lists installed Ollama models and lets you
set the active model, pull new ones, remove downloads, change the Ollama host,
and see app / Python / Ollama versions. Changes persist to
`~/.dobby/settings.json` and take effect on the next generation.

## REST API (selected)

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/v1/projects/{id}/dashboard` | Dashboard stats |
| GET/POST | `/api/v1/projects/{id}/backlog` | List / add features |
| GET  | `/api/v1/projects/{id}/graph` | Graph + Mermaid syntax |
| POST | `/api/v1/projects/{id}/wizard/start` | Start a wizard session |
| POST | `/api/v1/wizard/{session_id}/execute` | Run next verified step |
| POST | `/api/v1/projects/{id}/yolo/generate` | One-shot generate |
| POST | `/api/v1/projects/{id}/yolo/accept` | Finalize a YOLO run |
| POST | `/api/v1/projects/{id}/bulk/generate` | Generate all docs for many ideas + coverage report |
| GET/PUT | `/api/v1/settings` | Read / update settings |
| GET  | `/api/v1/models` · POST `/api/v1/models/pull` | Model management |
| GET  | `/api/v1/system/info` | Versions + connectivity |

Full interactive docs at `/docs` when the server is running.

## Project structure

```
src/
  main.py                 # FastAPI app + router wiring
  cli.py                  # dobby CLI
  api/                    # routes, dashboard_routes, generation_routes, settings_routes
  pipeline/               # wizard, yolo, pareto
  llm/ollama_client.py    # Ollama client
  verifiers/              # deterministic verifier (7 rule-based checks)
  graph/ · db/ · sessions/ · audit/ · settings/
tauri-app/                # React + Vite + Tauri desktop UI
tests/                    # pytest suite
```

## Testing

```bash
pytest tests/ -o addopts=""
```

## Configuration

`~/.dobby/settings.json` (managed from the UI) — `ollama_host`, `model`,
`theme`, `verification_threshold`. The database lives at `~/.dobby/dobby.db`.

## License

MIT — see [LICENSE](LICENSE).

## Author

Swaroop <ksjpswaroop@gmail.com>
