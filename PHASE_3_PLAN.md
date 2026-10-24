# Phase 3: Tauri Desktop App Implementation Plan

## Overview

Build a native macOS desktop app for Dobby v2.0 using:
- **Frontend:** React + TypeScript + Vite
- **Backend:** Rust (Tauri) + Python FastAPI
- **Database:** SQLite (~/.dobby/dobby.db)
- **LLM:** Ollama (local)

## Week 5-8 Timeline

### Week 5: Tauri App Scaffold
- Install Tauri CLI
- Create app structure
- Configure Rust backend
- Set up React frontend
- Build system configuration

### Week 6: Dashboard UI
- Project dashboard
- Graph visualization (Mermaid.js)
- Feature backlog list (with Pareto scores)
- Document library
- Progress tracking

### Week 7: Wizard UI
- 7-step wizard interface
- Real-time verification feedback
- User edit capability
- Progress persistence
- Resume functionality

### Week 8: YOLO UI
- Instant generation interface
- Review and accept/reject
- Edit before accept
- Quick mode workflow

## Technical Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri Desktop App (macOS)                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  React Frontend (TypeScript + Vite)                 │    │
│  │  - Dashboard                                        │    │
│  │  - Wizard UI                                        │    │
│  │  - YOLO UI                                          │    │
│  │  - Graph Viewer                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          │ Tauri Commands                    │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Rust Backend (Tauri)                               │    │
│  │  - File system access                               │    │
│  │  - System integration                               │    │
│  │  - Native menus                                     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ HTTP (localhost:8000)
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Backend (Python)                                   │
│  - REST API endpoints                                       │
│  - Database operations                                      │
│  - Ollama integration                                       │
│  - Wizard/YOLO pipelines                                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ SQLAlchemy
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SQLite (~/.dobby/dobby.db)                                 │
└─────────────────────────────────────────────────────────────┘
```

## Success Criteria

- ✅ Native macOS app (.app bundle)
- ✅ Dashboard shows projects, features, documents
- ✅ Graph visualization (interactive)
- ✅ Wizard mode works (7 steps)
- ✅ YOLO mode works (instant)
- ✅ Pareto prioritization visible
- ✅ State persists across sessions
- ✅ Build and run on macOS

## Files to Create

### Tauri/Rust
- `tauri-app/src-tauri/Cargo.toml`
- `tauri-app/src-tauri/tauri.conf.json`
- `tauri-app/src-tauri/src/main.rs`
- `tauri-app/src-tauri/src/commands.rs`

### React Frontend
- `tauri-app/src/main.tsx`
- `tauri-app/src/App.tsx`
- `tauri-app/src/pages/Dashboard.tsx`
- `tauri-app/src/pages/Wizard.tsx`
- `tauri-app/src/pages/Yolo.tsx`
- `tauri-app/src/components/GraphViewer.tsx`
- `tauri-app/src/components/FeatureList.tsx`
- `tauri-app/src/api/client.ts`

### Configuration
- `tauri-app/package.json`
- `tauri-app/vite.config.ts`
- `tauri-app/tsconfig.json`

## Dependencies

**Frontend:**
- React 18
- TypeScript
- Vite
- TailwindCSS
- React Router
- Mermaid.js (graph visualization)
- Axios (API client)

**Rust/Tauri:**
- Tauri 2.0
- serde
- tokio

**Python Backend:**
- FastAPI (already installed)
- SQLAlchemy (already installed)
- Ollama client (already implemented)

## Build Commands

```bash
# Install Tauri CLI
cargo install tauri-cli

# Install Node dependencies
cd tauri-app
npm install

# Development mode
npm run tauri dev

# Build for production
npm run tauri build
```

## Next Steps

1. Check if Node.js and Rust are installed
2. Install Tauri CLI
3. Create Tauri app scaffold
4. Build React frontend
5. Integrate with FastAPI backend
