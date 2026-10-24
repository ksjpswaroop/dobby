# Phase 3 Week 8: Production Build Plan

## Overview

Complete Phase 3 by building the Dobby v2.0 desktop app for production distribution on macOS.

---

## Goals

1. **Production Build** - Create optimized, minified build
2. **Code Signing** - Sign with Apple Developer certificate
3. **Notarization** - Submit to Apple for notarization (optional but recommended)
4. **.app Bundle** - Create installable macOS application
5. **Testing** - Verify all features work in production build
6. **Documentation** - User guide and release notes

---

## Task 1: Production Build

### Prerequisites Check
```bash
# Verify Node.js
node --version  # Should be 18+

# Verify Rust
rustc --version  # Should be 1.70+

# Verify Tauri CLI
cargo tauri --version  # Should be 2.x
```

### Build Commands
```bash
cd ~/projects/dobby/tauri-app

# Install dependencies (if not already done)
npm install

# Build for production
npm run tauri build
```

### Expected Output
```
tauri-app/src-tauri/target/release/Dobby.app    # macOS app bundle
tauri-app/src-tauri/target/release/dobby        # Binary
tauri-app/dist/                                  # Web assets
```

### Build Configuration

**tauri.conf.json:**
```json
{
  "productName": "Dobby",
  "version": "2.0.0",
  "identifier": "com.dobby.app",
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://localhost:1420",
    "beforeBuildCommand": "npm run build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "title": "Dobby v2.0",
        "width": 1400,
        "height": 900,
        "resizable": true
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": ["app", "dmg"],
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ],
    "macOS": {
      "signingIdentity": "Developer ID Application: YOUR_NAME",
      "entitlements": null,
      "provisioningProfile": null
    }
  }
}
```

---

## Task 2: Code Signing (macOS)

### Requirements
- Apple Developer account ($99/year)
- Developer ID Application certificate
- Access to keychain with certificate

### Steps

1. **Get Certificate Name**
```bash
security find-identity -v -s "Developer ID Application"
```

Output example:
```
1) ABC123DEF456 "Developer ID Application: Your Name (TEAMID)"
```

2. **Update tauri.conf.json**
```json
{
  "bundle": {
    "macOS": {
      "signingIdentity": "Developer ID Application: Your Name (TEAMID)"
    }
  }
}
```

3. **Build with Signing**
```bash
npm run tauri build
```

### Verification
```bash
# Check if app is signed
codesign -dv --verbose=4 src-tauri/target/release/Dobby.app

# Verify signature
codesign --verify src-tauri/target/release/Dobby.app
```

---

## Task 3: Notarization (Optional but Recommended)

### Why Notarize?
- Required for macOS Catalina (10.15) and later
- Prevents "App can't be opened" warnings
- Increases user trust

### Steps

1. **Create App-Specific Password**
   - Go to appleid.apple.com
   - Sign in with Apple ID
   - Create app-specific password

2. **Submit for Notarization**
```bash
xcrun notarytool submit \
  src-tauri/target/release/Dobby.app \
  --apple-id "your@email.com" \
  --password "app-specific-password" \
  --team-id "TEAMID" \
  --wait
```

3. **Staple Notarization Ticket**
```bash
xcrun stapler staple src-tauri/target/release/Dobby.app
```

4. **Verify**
```bash
xcrun notarytool info --apple-id "your@email.com" --password "app-specific-password" --team-id "TEAMID" <submission-id>
```

---

## Task 4: Create .app Bundle

### Automatic (via Tauri)
Tauri automatically creates the .app bundle during build.

Output location:
```
tauri-app/src-tauri/target/release/Dobby.app
```

### Manual Verification
```bash
# Check bundle structure
ls -la src-tauri/target/release/Dobby.app/Contents/

# Should contain:
# - Info.plist
# - MacOS/dobby (binary)
# - Resources/ (assets)
# - Frameworks/ (dependencies)
```

### Create DMG (Disk Image)
```bash
npm run tauri build -- --target universal-apple-darwin
```

Output:
```
tauri-app/src-tauri/target/release/bundle/dmg/Dobby_2.0.0.dmg
```

---

## Task 5: Test Production Build

### Functional Testing Checklist

**Dashboard:**
- [ ] Stats cards show correct counts
- [ ] Today's priority feature displays
- [ ] Quick start links work
- [ ] Recently completed features list

**Backlog:**
- [ ] Feature list loads
- [ ] Filter by status works
- [ ] Sort by Pareto works
- [ ] Click to start wizard works

**Wizard:**
- [ ] Feature input form works
- [ ] 7-step progress bar
- [ ] Generate button calls API
- [ ] Verification scores display
- [ ] Skip button works
- [ ] Completion screen shows

**YOLO:**
- [ ] Feature input form works
- [ ] Generate starts background process
- [ ] Loading state shows
- [ ] Verification result displays
- [ ] Accept/Reject buttons work

**Graph:**
- [ ] Graph renders
- [ ] Zoom in/out works
- [ ] Reset zoom works
- [ ] Legend displays correctly
- [ ] Max nodes selector works

**Navigation:**
- [ ] All 5 nav links work
- [ ] Back button works
- [ ] URL routing works

**Error Handling:**
- [ ] Offline detection
- [ ] Error messages display
- [ ] Retry buttons work

### Performance Testing
- [ ] App loads in <3 seconds
- [ ] Dashboard loads in <2 seconds
- [ ] Graph renders in <5 seconds
- [ ] No memory leaks (Activity Monitor)

### Compatibility Testing
- [ ] macOS 12.0+ (Monterey)
- [ ] macOS 13.0+ (Ventura)
- [ ] macOS 14.0+ (Sonoma)
- [ ] Apple Silicon (M1/M2/M3)
- [ ] Intel Macs

---

## Task 6: User Documentation

### README.md (Root)
- Project overview
- Features
- Screenshots
- Installation
- Quick start
- Development

### USER_GUIDE.md
- Getting started
- Dashboard overview
- Using Wizard mode
- Using YOLO mode
- Understanding the graph
- Managing features
- Keyboard shortcuts
- Troubleshooting
- FAQ

### RELEASE_NOTES.md
- Version 2.0.0
- New features
- Bug fixes
- Known issues
- Upgrade notes

---

## Timeline

| Day | Task | Hours |
|-----|------|-------|
| **Day 1** | Production build + signing | 4 |
| **Day 2** | Notarization + testing | 4 |
| **Day 3** | Documentation | 3 |
| **Total** | | **11 hours** |

---

## Success Criteria

- ✅ Production build completes without errors
- ✅ App is code-signed
- ✅ App is notarized (optional)
- ✅ .app bundle created
- ✅ All 5 pages pass functional testing
- ✅ Performance targets met
- ✅ User documentation complete
- ✅ Release notes published

---

## Next Steps (Phase 4)

After Phase 3 completion:
1. **Template Editor** - In-app template customization
2. **Collaboration** - Multi-user support
3. **Export Formats** - PDF, DOCX, Markdown
4. **Backup/Restore** - Database backup functionality
5. **Auto-updates** - Tauri updater integration

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Code signing fails | Medium | High | Test with dev cert first |
| Notarization rejected | Low | High | Fix entitlements, resubmit |
| Build errors | Medium | Medium | Clean build, check deps |
| Performance issues | Low | Medium | Profile, optimize bundle |
| Feature bugs | Medium | Medium | Comprehensive testing |

---

**Ready to begin production build!** 🚀
