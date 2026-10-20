# Project Deviser

A clean-room effort to understand, document, and eventually reimplement
an Inventor-class parametric CAD system — starting from format
interoperability with Autodesk Inventor files.

## Naming (decided 2026-10-19)

The system/software is called **Deviser**. Its file formats:

| Deviser type | Extension | Inventor equivalent |
|---|---|---|
| Part (Enkelt del) | `.devp` | `.ipt` Part |
| Assembly (Samling) | `.deva` | `.iam` Assembly |
| Drawing (Tegning) | `.devd` | `.idw`/`.dwg` Drawing |
| Presentation (Eksploderet visning) | `.devx` | `.ipn` Presentation |

## Ground rules (fixed)

1. **Clean-room only.** All format knowledge derives from black-box
   observation: container parsing, string scans, controlled sample diffs.
   No decompilation, no disassembly of Autodesk binaries, no leaked or
   decompiled code as input. This keeps the spec and any code legally
   publishable.
2. No licensing/DRM circumvention work of any kind.
3. Every finding gets validated against ground-truth samples before it
   enters the spec (lesson from the "MyLength false positive", session 3).

## Current state

- `spec/ipt-format-notes.md` — observational spec of `.ipt`
  (container, property sets fully decoded, thumbnail, RSe metadata).
  Note: spec documents the Inventor format as input interop target;
  Deviser's own `.devp` format is a future design task.
- `tools/iptinfo` — CLI: metadata, parameters, ASM geometry. `tools/ipt2obj` — OBJ mesh exporter (sketch+extrude).
  locale/timestamps/thumbnail from `.ipt`. Tested on 4 real samples.
- Samples A–D in `samples/` (from the analysis sessions).

## Current state (updated session 17)

- `spec/ipt-format-notes.md` — the master spec, sessions 1-17: container,
  property sets, zstd RSe payloads, parameters + expression links,
  ASM binary B-rep, feature grammars (fillet/chamfer/hole/boss),
  .iam assembly tree + occurrence records + transforms.
- `tools/iptinfo` — CLI: metadata, parameters, links, ASM geometry,
  assembly tree + occurrences + placed transforms.
- `tools/ipt2obj`, `tools/ipt2step` — mesh/STEP exporters.
- `tools/ipt2devp` — native **.devp** part format (zstd+JSON),
  feature replay via CadQuery — volumes verified exact on the corpus.
- `tools/ipt2deva` — native **.deva** assembly format: occurrences,
  origin features, transforms, constraints (round-trip verified).
- AppImages in repo root: latest **Deviser-AS-1.6** (parameter editor,
  feature replay, New Part, .devp save, .iam open, .deva save).

## Open frontier

- Transform semantics: row/column-major + translation slot — needs ONE
  ground-truth assembly with a known linear offset (e.g. 50 mm along X).
- E5: sketch-canvas UI (freehand sketch editor).
- `.devd` drawings / `.devx` presentations.

## Roadmap (rough)

1. RSe payload encoding (experiment A and successors)
2. Parameter table read support
3. Sketch/geometry read support (B-rep is the deep end; STEP export
   via documented API is the practical interop route meanwhile)
4. Design `.devp`/`.deva`/`.devd`/`.devx` formats (likely OLE/zip-based,
   standing on everything learned)
5. Clean-room application work on an OCC-based kernel
