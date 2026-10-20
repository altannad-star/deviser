# Deviser

Clean-room viewer/exporter for Inventor `.ipt` part files — built
entirely from observational format analysis (no decompilation).

## What it does

- **New Part…** — create Deviser-native parts from scratch (rect/circle, extrude, fillet)
- **Inspect** `.ipt` files: title, author, material, parameters (length/angle/
  text/model dims), dependency graph, topology, thumbnail
- **Edit** parameters (E1): change any dimension → solid rebuilds → export the edited solid
- **Save/Load .devp** — Deviser's native format (zstd+JSON, versioned)
- **Multi-body parts** (E3): stacked/added/cut features
- **Export OBJ** (tessellated mesh, mm)
- **Export STEP** (exact analytic solids via OpenCascade; fillet replay
  verified to 4 decimals)
- **Save JSON** (all extracted data)

## One-file app (Linux / Bazzite KDE)

```bash
bash build-deviser.sh        # builds Deviser-1.0-x86_64.AppImage (~10 min)
./deviser-build/Deviser-1.0-x86_64.AppImage &
```

Optional (enables exact STEP export in-app):
```bash
pip install --user cadquery
```

## CLI tools

```bash
iptinfo FILE.ipt                 # inspect
ipt2obj FILE.ipt -o out.obj      # mesh export
ipt2step FILE.ipt -o out.step    # exact CAD export (needs: pip install cadquery)
```

## Layout

- `tools/` — iptinfo, ipt2obj, ipt2step, install/verify scripts
- `apps/` — Qt-native app + web-fallback app sources
- `spec/` — the complete observational format spec (12 sessions)
- `samples/` — ground-truth .ipt test files
- `build-deviser.sh` — one-command AppImage builder

## Legal

All knowledge derived from black-box observation: container parsing,
controlled diffs of user-authored samples, and geometry validation against
OpenCascade. No Autodesk code was decompiled or included.
