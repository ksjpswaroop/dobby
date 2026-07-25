# Dobby v2.0 Desktop App

Native macOS desktop application for Dobby v2.0 - Interactive Document Development Platform.

## Tech Stack

- **Frontend:** React 18 + TypeScript + Vite
- **Backend:** Rust (Tauri 2.0)
- **Styling:** TailwindCSS
- **Routing:** React Router
- **Graph Visualization:** Mermaid.js (planned)

## Prerequisites

- Node.js 18+ (✅ Installed: v22.22.3)
- Rust 1.70+ (✅ Installed: rustc 1.91.1)
- Tauri CLI (✅ Installed: v2.11.4)

## Development

```bash
# Install dependencies (already done)
npm install

# Run in development mode
npm run tauri dev
```

This will:
1. Start Vite dev server on `http://localhost:1420`
2. Open the Tauri app window
3. Enable hot-reload for frontend changes

## Production Build

```bash
# Build for production
npm run tauri build
```

Output:
- `src-tauri/target/release/Dobby.app` (macOS app bundle)
- `src-tauri/target/release/dobby` (binary)

## Project Structure

```
tauri-app/
├── src-tauri/              # Rust backend
│   ├── Cargo.toml          # Rust dependencies
│   ├── tauri.conf.json     # Tauri configuration
│   └── src/
│       ├── main.rs         # App entry point
│       └── commands.rs     # Tauri commands
├── src/                    # React frontend
│   ├── App.tsx             # Main app
│   ├── main.tsx            # React entry
│   ├── index.css           # TailwindCSS
│   ├── pages/
│   │   ├── Dashboard.tsx   # Dashboard page
│   │   ├── Wizard.tsx      # 7-step wizard
│   │   └── Yolo.tsx        # Instant generation
│   └── components/         # Shared components
├── package.json            # Node dependencies
├── vite.config.ts          # Vite config
├── tsconfig.json           # TypeScript config
├── tailwind.config.js      # TailwindCSS config
└── postcss.config.js       # PostCSS config
```

## Features

### Dashboard (`/`)
- Project/Feature/Document statistics
- Today's priority feature (Pareto score)
- Quick start links

### Wizard Mode (`/wizard`)
- 7-step guided generation
- Progress tracking
- User edit capability
- Verification feedback

### YOLO Mode (`/yolo`)
- Instant generation (all 7 steps at once)
- Review and accept/reject
- Verification score display

## Integration with FastAPI Backend

The Tauri app communicates with the Python FastAPI backend via HTTP:

```rust
// Example: Call FastAPI from Rust
let client = reqwest::Client::new();
let response = client
    .post("http://localhost:8000/api/v1/projects/123/backlog")
    .json(&payload)
    .send()
    .await?;
```

## Current Status

✅ **Phase 3 Week 5 Complete: Scaffold Built**

- [x] Tauri app structure
- [x] Rust backend with 6 commands
- [x] React frontend with 3 pages
- [x] Navigation and routing
- [x] Configuration files
- [x] Dependencies installed
- [ ] Integration with FastAPI (Week 6)
- [ ] Graph visualization (Week 6)
- [ ] Production build (Week 8)

## Next Steps

1. **Week 6:** Integrate with FastAPI backend
   - Dashboard data fetching
   - Wizard command implementation
   - YOLO command implementation

2. **Week 6:** Add graph visualization
   - Install Mermaid.js
   - Create GraphViewer component
   - Render dependency graphs

3. **Week 7:** Polish UI/UX
   - Loading states
   - Error handling
   - Toast notifications
   - Keyboard shortcuts

4. **Week 8:** Production build
   - Code signing
   - Notarization (optional)
   - `.app` bundle creation

## Troubleshooting

### Tauri app won't start
```bash
# Check Rust version
rustc --version  # Should be 1.70+

# Check Node version
node --version  # Should be 18+

# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
```

### Build errors
```bash
# Clean build
cd src-tauri
cargo clean
cd ..
npm run tauri build
```

## License

MIT
