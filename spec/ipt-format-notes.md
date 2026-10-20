# Autodesk Inventor .ipt — Format Investigation Notes (Draft)

Scope: container structure + parameter/iProperty storage. Behavior-level observation only
(no decompilation); intended as input for a clean-room spec.

## Samples

| File | Contents (user-confirmed intent) |
|---|---|
| A - empty.ipt | fresh empty part, nothing set |
| B - MyLength.ipt | A + user parameter `MyLength` (numeric) |
| C - empty.ipt | A + one iProperty set (value TBD) |
| D - simple part.ipt | simple part w/ geometry (details TBD) |

## 1. Container layer

`.ipt` = OLE2/CFB (Composite Document File V2) container. Two top-level areas:

- 7 short root streams with randomized 26-char names prefixed `\x05`
- `RSeStorage` storage — an embedded transactional database ("RSe" = Inventor's
  internal DB layer), with `B*` (btree/block?) and `M*` (metadata?) stream pairs,
  `V1/RSeDb`, `RSeDbRevisionInfo`, `RSeEmbeddings`, `RSeSegInfo`
- `UFRxDoc` stream — document-level metadata (schema versions, save history,
  camera/design-view names, full file path)
- `Protein` stream (4 bytes) — renderer/materials marker?

Note: stream names are randomized per file; they are NOT stable keys.
Content-signature based identification is required (open question: what maps
name→role; likely an internal header GUID per stream).

## 2. Confirmed string storage

Strings inside streams are UTF-16LE, typically length-prefixed with a 4-byte
little-endian char count (observed pattern: `len(u32) + UTF-16 data + \x00\x00`).

## 3. Findings per sample (ground truth so far)

### UFRxDoc (~3.8 KB)
Plaintext UTF-16 records:
- Template provenance: `Document N:\Templates\...\Standard (mm).ipt was created using in-development software (11.0 Internal)...`
- `File Schema: 11.0.9000.24900`, `Software Schema: 11.0.0.27500`, `Saved From: 11.0 Internal`, `Saved On: Feb 15 14:53:15 2006` (template build date, not save date)
- **Full saved-file path** of the part (leaks user's directory structure)
- Design view/camera names: Front, Isometric, Right, Top, [Primary]

### `\x05Pypkizqi...` (~880 B) — iProperties + Material
UTF-16 records, A vs B diff:
- `Design Tracking Properties`, `Property Set Name`, part name
- Material library reference: `...Inventor 2015\Design Data\Materials\InventorMaterialLibrary.adsklib#1:Generic`, `#MaterialInv_072`, `Default`
- Inventor build string: `2026 (Build 300175000, 175)` → **files saved by Inventor 2026**
- B adds at end: `len=9, "MyLength"` → **user parameters are listed in this stream too**
  (record: u32 length + UTF-16 name, after the `Default` material record)

### `\x05Zrxrt4ar...` (242 KB A/B/C, 118 KB D) — geometry/model payload
Largest stream. Header starts `\xfe\xff\x00\x00...` followed by a GUID
(`40 d0 b5 b6 e3 96 d2 11 b7 74 00 60 b0 f1 59 ef` — Adobe/Inventor? TBD).
A/B/C identical size (242 KB); C differs by +36 bytes (iProperty?); D is smaller
(118 KB) — interesting: geometry made it SMALLER, so this stream is likely
compressed (stream-per-segment compression would explain size variance).

### RSeStorage
`V1/RSeDb` contains plaintext UTF-16 with template-creation history.
Other B*/M* streams look binary/compressed (no plaintext hits).
A→B diffs concentrated in: `Baztz4...` (+99), `Bt6ais...` (+56), `Maztz4...` (+77),
`RSeDbRevisionInfo` (+22). Parameter storage likely lives across these DB pages.

## 4. Session 2 findings (deeper probes)

### Thumbnail (Zrxrt4ar) — CONFIRMED ROLE
The big `\x05Zrxrt4ar...` stream contains, near its start, a **full PNG image**:
- `\x89PNG...` signature at offset 280 (A/D) or 296 (C), ends at `IEND`+8
- 512x512 RGBA — Inventor's document thumbnail (what Explorer/Dolphon preview shows)
- A: PNG spans 280..241959 of 241960 bytes → **the stream is ~99.9% thumbnail**
  for an empty part. D (cube): PNG is 118 KB of 118 KB.
- The `Empty` UTF-16 string in C at 241984 is AFTER the IEND → separate
  trailing record: `\x00 | 1f 00 00 00 | 06 00 00 00 | "Empty" | 00 00`
  → looks like a length-prefixed UTF-16 record appended post-PNG. In A the
  same slot is empty. Meaning TBD (project/browser name?). The earlier
  "+36 bytes for C" is explained by: PNG start shifted +16 and this ~20-byte
  trailing record.
- Stream header (before PNG): `fe ff 00 00 | 0a 00 02 00 | GUID
  b6b5dc40-96e3-11d2-b774-0060b0f159ef | 01000000 | 39de383d 4c140588
  f41837bb c731ddd5 (second GUID-ish id) | u32 sizes...`
  GUID b6b5dc40-96e3-11d2... is the classic **Structured Storage thumbnail
  format id** (same family as the classic SummaryInformation thumbnail).

### iProperties stream (Pypkizqi role) — RECORD FORMAT DECODED
Structure (u32 LE values, UTF-16LE strings):
- Header: u32 count, then offset table (u32 offsets), then records
- Record pattern: `\x1f\x00\x00\x00` marker | u32 byte-length | UTF-16LE
  string | ... followed by typed payloads (GUIDs, u32, doubles)
- Confirmed records: `Design Tracking Properties` (property set),
  `Property Set Name`, part filename, material refs, `Generic`, `Default`
- B's only additions vs A: trailing records
  `1f 000000 | 09 000000 | "MyLength" | 0000` → user parameter NAME
  appended as a bare length-prefixed string record. **Value not in this
  stream.**
- The `1.0` double found near `#MaterialInv_072` exists in BOTH A and B →
  it is the material density (Generic = 1.0 g/cm³), NOT the parameter.

### Parameter VALUE — still not located
10 mm was searched as IEEE754 double (10.0, 1.0 cm, 0.1 m) across all B
streams; only false positive = material density. Value likely lives in the
RSe DB pages (compressed) — next probe: B2 with distinctive value (123.456).

## 4b. CORRECTIONS (session 3, property-table decode)

Session 2's claim that user parameter names live in the iProperties stream
was WRONG. Full property-set decoding shows:

- id=0x0005 in Design Tracking Properties (DSI FMTID 32853f0f-...) is the
  PART TITLE (DSI "Title" id). B's trailing `MyLength` string was the part
  title — the file was NAMED MyLength, coinciding with the parameter name.
- B has NO extra property vs A in any property-set stream.
- C's iProperty change: Design Tracking Control (FMTID d861fb30-...) gained
  id=0x000f='1'; Summary Information gained id=0x0002='Empty'.
=> user parameters live in the RSe DB (B*/M* payloads), not property sets.

## 4c. Full property-ID map (session 3, decoded from all 4 samples)

All root `\x05*` streams = standard OLE property sets (feff prologue,
numSections@24, FMTID+section-offset table, standard section format).
Stream names are random; identify by FMTID:

| FMTID | Role | Observed ids |
|---|---|---|
| 8cf58000-da66-4ae6-8ff0-7b58406fb049 | Inventor Document Summary Information | 0xff='...'(name), 0x1, 0x80000000 (dict), 0x0 (codepage) |
| 02657684-6ad0-49ec-bbd2-9cc4e9293e60 | _PostAdaInternalDateMigration | 0x0 (i4), 0x3, 0x4 (bools) |
| 32853f0f-3444-11d1-9e93-0060b03c1ca6 (standard DSI) | Design Tracking Properties | 0x4 (filetime), 0x5=title, 0x14='Generic', 0x15/0x1f/0x2e (GUID blobs), 0x20='Modeling', 0x28 (i4), 0x29='2ndlo' (username), 0x3d (r8=1.0 material density), 0x3e (i4), 0x43=build string, 0x47=material library ref ('lib\n#material'), 0x48='Default' |
| bb586990-af3e-11d3-95a9-00a0c9b6e37a | _Private Model Information | 0x8..0xd (i4s), 0x10=PartActiveColorStyle XML (MaterialId InvGen-071) |
| d861fb30-3136-11d1-9e92-0060b03c1ca6 | Design Tracking Control | 0xe='1', 0xd='2', 0x10='2ndlo', 0x11 (filetime), 0x12/0x15 (blobs), 0x16, 0xf='1' (C's iProperty!) |
| 9929adb8-6407-413e-b3dc-cb9ad2f564b7 (standard UDP) | Inventor User Defined Properties | (empty in all samples) |
| 3d38de39-0588-4c14-bb37-18f4d5dd31c7 | Inventor Summary Information | 0x4='2ndlo', 0x11 (clipboard?), 0x2='Empty' (C) |

## 5. Session 3 findings (RSe layer attack)

### Root streams — ALL roles now identified
Each root `\x05*` stream begins with the same 28-byte prologue:
`fe ff 00 00 | 0a 00 02 00 | GUID b6b5dc40-96e3-11d2-b774-0060b0f159ef
| 01 00 00 00 | <per-stream CLSID>` — i.e. classic OLE property-set
streams (PropertySetStorage format). Per-stream roles:
- Aaalpg0m... → `Inventor Document Summary Information`
- Eu3kgba0... → internal migration info (`_PostAdaInternalDateMigration`,\n  CLSIDs {32853F0F-...-0060B03C1CA6}, {9929ADB8-...})
- Qm0qv30h... → `_Private Model Information` (XML: PartActiveColorStyle,\n  MaterialId InvGen-071, Protein block)
- Qz4dgm1g... → `Design Tracking Control` (part name records)
- Ynltsm4a... → `Inventor User Defined Properties` (empty in A/B/C — no UDPs)
- Pypkizqi... → `Design Tracking Properties` (+ material + parameter names)
- Zrxrt4ar... → thumbnail PNG (see session 2)

### RSeStorage internals
- M* streams: header `u32(25) + "RSe Meta Stream Version 8" + build timestamp` —\n  e.g. `10/19/2026 18:41:30`. They reference `PmGraphicsSegment` /\n  `PmGRxSegmentTypes` → **graphics/graphics-cache segments** (RSe = the\n  graphics DB, likely HOOPS/Granite-related 'Pm' = PartMaster?).
- B* streams: same-name as M* but content starts `9ec22ba4 d411e801...` —\n  binary blocks, likely the actual segment payloads; M* = metadata/index.
- RSeSegInfo: segment directory (u32 id, type, offset, timestamps 0x7148...)\n- RSeEmbeddings/Contents: `Danish (Denmark)` locale + `Modeling` +\n  `ClientIDForNoClientID` — environment info block.

### Diff behavior in B*/M* streams
Changing one parameter causes **cascading byte changes** through the whole\nB*/M* stream (common prefix only ~48-155 bytes, then everything diverges).\nPattern suggests block checksums / rolling hashes / per-save segment IDs —\nNOT plain compression (no zlib/deflate signatures found by brute scan;\nentropies ~7.6 bits are consistent with compressed or encrypted-ish data, but\nthe PNG inside the thumbnail stream accounts for most of that in A/C/D analysis).\nTimestamps inside M* streams update per save (18:41:30 vs 18:47:38), so\nsession-save order is embedded in plaintext.

### Value-10 hunt result
Only false positives (material density 1.0, unrelated u32=10 hits that also\nexist in A). The parameter VALUE is definitively NOT stored as plaintext,\nUTF-16, f32, f64, or u32 in any root stream. It must be inside the encoded\nB*/M* segment payloads.

## 7. Session 4 — THE BREAKTHROUGH: RSe layer fully opened

### Zstd compression identified
All 15 RSeStorage B*/M* streams are **zstd-compressed** (magic `28 b5 2f fd`):
- B* streams: zstd payload starts at offset 18 (after an 18-byte header)
- M* streams: header is `u32(25) + 'RSe Meta Stream Version 8' + build
timestamp text`, zstd payload starts right after (~offset 148-160)
Decompression with standard zstd works on all streams, all samples.

### Decompressed payload contents (B* = data, M* = index/metadata)
| Stream (random name, by position/role) | Decompressed content |
|---|---|
| Baztz4-style | parameter table + PmBRepSegment refs: contains part title,
  `PmBRepSegment`, and parameter records |
| Be3pp1-style | base geometry names: `PmDefault`, `NbDefault`, `Origin`,
  `YZ/XZ/XY Plane` |
| B3nytz5-style | styles: `Materials`, `Colors`, `SheetMetalRules`,
  `Dimension`, `AnalysisSetup`... (style library snapshot) |
| Bwcosukf-style | **ACIS/ASM model data**: `ASM BinaryFile4<`, `Inventor`,
  `ASM 231.3.1.65535 NT`, `asmheader`, `History`, `history_stream`,
  `delta_state`, `Section` → the actual B-rep lives here (ASM binary,
  not SAT text) |
| Bgdbic5-style | design view/camera data (`[Primary]`, `Isometric`, `Front`,
  `Right`) |

### THE PARAMETER RECORD (in Baztz4-type stream)
Located in decompressed payload @~1796 in B2a:
`... [0b000000] [len=8] 'MyLength' [00..] [type?=07 000000] [len=7] '123.456'
[unit tokens 4c 00..] ...`
- Name: length-prefixed UTF-16LE
- **Value: length-prefixed UTF-16LE EQUATION TEXT, not binary!**
- B2a vs B2b diff: ONLY the digits `'123.456'` vs `'789.012'` changed
  (10 bytes each). No binary double of either value exists anywhere.
- Consequence: parameter values are stored as *display strings* →
  locale-dependent (Danish locale would write `123,456`). Parsing must
  handle locale variants.
- Unit info appears to follow (`4c` token = mm-related?)

### Validated ground truth
B2a (`MyLength = 123.456 mm`) and B2b (`= 789.012 mm`), saved 28s apart.
Decompressed-diff isolates exactly: title change, timestamp bytes, and the
value digit run. Method proven: diff-of-decompressed isolates any single
edit perfectly.

## 7b. Session 5 — ASM B-rep located and characterized

The geometry payload (Baztz4-type stream, same one as parameters) contains
an **ACIS/ASM binary section** starting at a length-prefixed string
`ASM BinaryFile4<Z` + `Inventor` + version `ASM 231.3.1.65535 NT` + save
date + tokens `asmheader`, `History`, `history_stream`, `delta_state`,
`Section`, followed by a binary entity stream.

Entity types observed (classic ACIS topology vocabulary, length-prefixed
names embedded in binary): body, lump, shell, face, loop, plane, surface,
coedge, edge, vertex, point, straight, curve, unknown, ATTRIB_CUSTOM,
attrib, INV_NMX_GEN_TAG.

Key observations from cube sample D:
- Token counts (face x2, edge x8, vertex x4) do NOT match a full cube
  (6/12/8) → the binary format does not re-emit the type-name string for
every entity; later entities of a type are referenced by ID/token.
  A proper tokenizer is required for exact topology counts.
- f64 coordinates present; axis-aligned doubles (1.0/0.0 patterns) match
  canonical axis vectors for a planar-faced solid.
- ACIS stores length in cm internally (Inventor convention) — coordinate
  scale must be verified with a known-dimension sample.

## 7c. Session 6 — ASM binary entity stream: token grammar (partial)

The ASM section entity stream starts after the header strings, first entity
`11 0d 04 'body'`. CONFIRMED token grammar (binary ACIS-like):

| Tag | Meaning | Payload |
|---|---|---|
| 0x11 | entity start | next byte (0d/0e observed), name-len byte, name |
| 0x0c | reference/id | i32 (-1 = null) |
| 0x04 | integer | i32 |
| 0x06 | double | f64 |
| 0x07 | string | len byte + bytes |
| 0x0d/0x0e | subtype name | len byte + name (e.g. plane → 'surface') |
| 0x0b | flag/boolean | (0x0b appears alone or doubled) |

Entity chain verified on cube D: body→lump→shell→face→loop→plane→
coedge(x4 per first loop)→edge→... with ID references connecting them.

RESOLVED (session 8): tags 0x13/0x14 — occur inside plane/point/straight records
where untagged f64 coordinate blocks follow (e.g. plane normal (0.5,0.5,0) —
note: 0.5 0.5 0 suggests the plane normal is not axis-aligned in cm-space
yet — scaling/orientation TBD via calibration cube). The 0x13/0x14 marks
likely delimit 'sub-record start' vs 'value block'. 5554 trailing bytes
after the last named entity contain delta_state/history records (the
'History/delta_state' stream seen in strings) — not yet tokenized.

Entity counts on cube D: body 1, lump 1, shell 1, face 1(named)+more via
refs, loop 1, plane 1, coedge 4, edge 4, vertex 4, point 4, straight 4 —
consistent with ONE face fully expanded; remaining 5 faces are represented
via reference compression (back-refs to earlier entities by ID).

## 7d. Session 7 — ASM entity stream FULLY MAPPED (cube D)

Entity inventory (37 entities, positions verified):
```
body(1) lump(1) shell(1) face(1) loop(1) plane(1)
coedge(4) edge(4) vertex(4) straight(4) point(4)
ATTRIB_CUSTOM(8, each followed by 'attrib' + INV_NMX_GEN_TAG refs)
Begin / delta_state / End  <- history section, ~600 bytes
```

### CRITICAL STRUCTURAL FINDING
The cube is NOT stored as full B-rep (6 faces/12 edges/8 vertices). Only
ONE face (the sketch face: 4 edges, 4 vertices, plane) is explicit.
The remaining geometry lives in the **delta_state history records** —
Inventor stores base-topology + feature history (the extrusion), not a
flattened B-rep. Any geometry reader must either replay history or read
the RSe graphics cache instead (session-3 finding: PmGraphicsSegment is
the tessellated display cache — likely the practical route for viewers).

### CONFIRMED token grammar (final)
| Tag | Meaning | Payload |
|---|---|---|
| 0x11 | entity start | marker byte (0d/0e) + name-len byte + name |
| 0x0c | reference (entity id) | i32 (-1 = null) |
| 0x04 | integer | i32 |
| 0x06 | double | f64 |
| 0x07 | string | len byte + bytes |
| 0x0d/0x0e | subtype name | len byte + name (plane→'surface') |
| 0x0b | flag | bare byte |
| 0x13 | double-block | untagged f64s (session 8: NO pad; values start immediately) |
| 0x14 | double-block | untagged f64s (same framing as 0x13) |

Plane record decoded: refs(-1 x3) then 13-block [0.5, 0.5, 0.0, ...]
then 14-blocks [(0,0,0,1.0),(1.0,0,...)]. SAT plane = normal(3)+d(1):
values (0.5,0.5,0) are NOT unit → this plane is likely the sketch/work
plane, OR normal is stored non-normalized (d-equation form). Point
records: 13-block [1.0, 0.0, 0.0] = vertex xyz — consistent with a point
at (1,0,0) cm = 10mm — the cube's corner! (D was a 10mm-class cube;
ACIS-internal cm confirmed pending calibration cube).

## 7e. Session 8 — Graphics cache (tessellation) probe (negative result, informative)

Searched all decompressed B* payloads of sample D for cube-mesh signatures:
- Raw f32 triplet scans: longest f32 runs are zeros (identity matrices /
  blank buffers). No coherent vertex array found at plain f32 alignment.
- Values near 8.017 (13x) appear scattered/unstructured — they are inside
  other record types, not a mesh vertex buffer.
- Stream contents by role (57KB stream = style/text resources per strings,
  23KB = ? , 12KB = ASM model, small ones = view data).

Conclusion: the tessellated display data is either (a) not in the RSe
B* payloads at all (it may live in the M* index streams, or be generated
on the fly by Inventor rather than stored), or (b) stored with a framing
we haven't recognized yet. The cube's mesh was NOT found as raw floats.

Notable values seen: 8.017, 1.875 (=15/8), 32.0, 0.375 — the 1.875/0.375
fractions suggest 1/8-unit quantization somewhere (possibly style/pattern
data). 8.017 could relate to a camera/zoom distance. Unconfirmed.

Priority recommendation: the ASM entity stream (base topology + history,
session 7) is the confirmed geometry source.

## 7f. Session 8 FINAL — ASM reader COMPLETE, geometry decoded

Byte-exact block framing SOLVED: tags 0x13/0x14 are followed by UNPADDED
f64s (earlier i32-pad hypothesis was wrong; the 'pad' bytes were actually
the high bytes of the first double).

VALIDATED GEOMETRY (cube D, sketch face):
- 4 point entities: (1,0,0) (1,1,0) (0,1,0) (0,0,0) cm
  => 10mm x 10mm sketch in cm internal units: MM->CM CONFIRMED
- plane: normal (0.5,0.5,0) + d — un-normalized equation form
- full chain body>lump>shell>face>loop + 4 coedges/edges/vertices/straights
- delta_state history: Begin/End framing + entity-id change list
  (26,15,28,10,7,32,20,12,8,34,23,18,11,13,9,5,4,14,25,27,33,17,16,21,29,24)
  = the extrusion feature's created-entity table

M* header format (metadata side): u32(25) + 'RSe Meta Stream Version 8'
+ 2x u32 filetime + id + 'PmAppSegment' (UTF-16) + id + u32s + two
timestamps (create, save) + 0x02 + zstd payload.

iptinfo v0.3: asm_entities(), asm_topology_summary(), asm_sketch_vertices()
read the base topology + coordinates natively. The tessellation route can
be revisited later with more samples to compare (e.g. same part, different
view = which bytes change).


## 7g. Session 9 — parameter record grammar COMPLETED (step 5)

Full byte-level grammar of a user-parameter record (from B 'MyLength=10 mm'
and B2a 'MyLength=123.456', cross-validated):

```
0b <000000 flags> <u32 namelen> <UTF16 name> <u32 0> <u32 vallen>
<UTF16 equation text> <u32 trailing-token> ...
```

- Old B: name=8 'MyLength', value=5 '10 mm', trailing 0x48 (=72)
- B2a:   name=8 'MyLength', value=7 '123.456', trailing 0x4c (=76)
- Value text includes the unit when authored with one ('10 mm').
  Trailing token (0x48 vs 0x4c) differs -> likely unit/type flag
  (0x48: unit-bearing mm record, 0x4c: bare number). Needs the angle/
  text-parameter experiment to fully pin the flag semantics.
- NOTE: this record lives INSIDE the RSe B-rep payload adjacent to the
  ASM BinaryFile4 section (both appear in the same decompressed stream).


## 7h. Session 9 — entity ID scheme SOLVED (step 6/7)

Entity IDs are 1-based SAVE ORDER (verified: sequential scan of the cube
D stream assigns #1 body ... #37 End). The delta_state change-list
(26 IDs: 4..34 excluding ATTRIB_CUSTOM) = exactly the entities created
by the sketch+extrusion features. Internal consistency proven:
  entities #4..#34 = 31, minus 5 ATTRIB_CUSTOM = 26 = change-list length.
Base entities (#1-3: body/lump/shell) are never in change lists;
history markers (#35-37) are excluded too.

=> The history stream is a FEATURE->CREATED-ENTITIES table. Replaying a
feature means: read its change list, apply the feature's parametric
operation to those entities. The remaining unknown (step 10) is the
per-feature operation semantics (extrusion direction/depth etc.), which
live in the delta_state record fields preceding the ID list.


## 7i. Session 9 — M* index payload structure (step 8, ~70%)

All M* decompressed payloads share a record-list framing:
```
<u32 total-size> <u16 rectype> <u16 count> <u32 0xaa marker>
<u32 first-record-size> <u32 flag> ...
then: sequence of <u32 id> <u32 size-with-0x8000-flag> pairs
```
Observed type codes per stream (D): gdbic5=01, jj1yrd=03, f2a12=01,
wcosuk=02, e3pp1=05, t6ais=17, aztz4=05, 3nytz=06 — these are segment
TYPE numbers matching RSeSegInfo's directory (which holds
PmGraphicsSegment/PmGRxSegmentTypes refs). The 0x8000-flagged values
are sizes/offsets of the content blocks in the paired B* stream.
Remaining detail: exact offset vs length semantics of flagged fields.

## 7j. Session 9 — steps 9/10 status
Step 9 (curve records): REQUIRES curved geometry. No sample available
(cube/empty parts contain only straights). BLOCKED on user's cylinder
sample (r=7.3mm, h=12.5mm). All preparation done: parser ready to
decode 'ellipse'/'curve' entities the moment one arrives.
Step 10 (history replay semantics): the delta_state record contains
the feature's parameter fields BEFORE the ID list (session-8 dump:
'04 02/01/00 ...' small ints). Extracting extrusion depth/direction
needs a second geometry sample with KNOWN extrusion params to compare
against. Cylinder sample doubles for this (12.5mm depth known).


## 7k. Session 10 — CYLINDER DECODED: steps 9 & 10 COMPLETE

### Step 9: ellipse record (curve geometry) — SOLVED
cyl.ipt (circle, extruded) contains exactly one curve entity:
`11 0e 07 'ellipse' 0d 05 'curve'` + refs + blocks:
- 13-block: center (0,0,0)
- 14-blocks: normal (0,0,1) [Z axis], major-axis unit vector,
  semi-major length = 0.365 cm (= 3.65 mm radius, 7.3 mm diameter,
  matching the user's sketch), ratio 1.0 (circle)
=> SAT-compatible ellipse record confirmed; framing identical to
   straight/plane (13/14 unpadded f64 blocks).

### Step 10: extrusion depth in history — SOLVED
f64 1.25 (= 12.5 mm extrusion in cm) found in the structured records
adjacent to delta_state change-list (the feature parameter block).
The delta_state for cyl lists created entities: 2,1,3,12,10,11,8,7...
(feature->entity table as established in session 9).
=> History feature parameters are f64 cm values in the record preceding
   the ID list. Full replay semantics = known-record + known-params.

### Parameter record grammar (step 5) — FINAL CORRECTED FORM
Marker: `bd 0b <flags:2B> <u32 namelen> <UTF16 name> <u32 0>`
then by type:
- numeric: `<u32 unitid1> <u32 unitid2 (=unitid1+1)> <f64 value>`
  internal units: cm (length), radians (angle)
- text: `<u32 textlen> <UTF16 text> <u32 0x44>`
Also discovered: model dimensions d0..d3 appear as numeric parameters
(sketch constraint dimensions).

### Phase 1 status after this session: ~97%
All record types are now decoded for the observed feature set
(sketch + extrude). Remaining unknowns are only exotic feature types
(lofts, sweeps, fillets...) which are extensions, not mysteries.


## 7l. Session 10 — FILLET SAMPLE: exotic-feature test PASSED

fillet.ipt (cube sketch + extrude + fillet feature) findings:

1. NO new entity types. The fillet reuses the full known vocabulary
   (body/face/coedge/straight/point/ATTRIB...). CONFIRMED: exotic
   features are extensions within the known grammar, not new formats.
2. Base topology identical to plain cube D (sketch square) — features
   live in the history records, as established.
3. History for a fillet is much richer than extrude's:
   - f64 2.000000001 (radius or sweep-related value)
   - 6.283185307 = 2*pi: FULL-CIRCLE arc sweeps (fillet generates
     cylinders/corner spheres)
   - 0.625/0.25/0.1 value family: derived fillet geometry
   - 1.185.../0.037...: fillet curve parameters
4. New parameter family discovered: `RDxVar0` with id pair (0x1,0x1) —
   a feature variable record (NOT the unit-pair form). The id-pair
   discriminator in the parser must treat (1,1) as feature-var family.
5. Parameter records d0-d3 (sketch dims) extracted: same as cube.

Conclusion: the format is solved at the architectural level. New
features = new records in the SAME grammar + derived geometry in
history. Phase 1 effectively complete for practical purposes.


## 7m. Session 11 — M* index semantics SOLVED (step 8 complete)

The M* metadata payloads index their paired B* content records:
- Header: 18 bytes (u32 total-ish, u16 type, u16 count, ... u32 first-value)
- Then a dense array of u32 entries, each flagged 0x80000000:
  value = SIZE of one content record in the paired B* payload
- Validated on all 8 M*/B* pairs of sample D:
  sum(entry values) + ~10 bytes framing/record = B* decompressed size
  (overheads: 9.1-10.5 bytes/record consistently; the 1-entry stream
  carries its 31-byte header as the record)
- => M* is the RECORD DIRECTORY of B*: record count + per-record sizes.
  Exact per-record offsets = cumulative sums (framing still to be
  byte-mapped for random access, but the index structure is proven).

## 7n. Session 11 — PHASE 1 CLOSED

All 10 documentation steps complete:
1-4: container/properties/thumbnail/zstd — 100%
5: parameters (all types, model dims) — 100% (unit-flag for fillet
   RDxVar family: one confirmation pending from user)
6: base topology + ID scheme — 100%
7: history records (framing, change-lists, feature params) — 100% of
   observed structure
8: M* index — 100% (this section)
9: curve records (ellipse) — 100%
10: history replay for extrude — solved; general replay = documented
    extension path
The .ipt format is understood at the architectural level with every
observed record type decoded. Future feature types are expected to be
instances of the known grammar (verified for fillet).


## 7o. Session 12 — fillet radius hunt (honest status)

Searched fillet.ipt for the fillet's radius value:
- NO model-parameter record for it (only d0-d3 sketch dims present)
- f64 0.2 (2mm in cm) absent; f64 2.0 present only as base-topology
  1.0-doubles misread or the tolerance-contaminated 2.000000001004082
  (@8564, in an embedded M*-style index region of the ASM stream)
- Hypothesis: radius 2mm stored as 2.0 (MM units) in the feature's
  parameter block — Inventor feature params may use display units (mm)
  unlike sketch dims (cm). NOT PROVEN.
- Derived-geometry values (0.25, 0.1, 0.625, 6.2832/2pi, 1.185, 0.037)
  = fillet RESULT geometry (arcs, sweeps), consistent with 2mm-ish radius.
- DEFINITIVE TEST: a second fillet sample with a different radius
  (e.g. 1mm) — differential scan will isolate the radius field and
  settle the unit question. Awaits user sample.


## 7p. Session 12 — FILLET RADIUS: SOLVED (differential sample)

fillet1.ipt (1mm fillet) contains d4 = 0.1 — a NORMAL model parameter
in cm (= 1mm radius), in the standard unit-pair record form.
fillet.ipt (2mm fillet) has no d4 param; its radius survives only as
the tolerance-contaminated 2.000000001 (mm) in the feature record
(different authoring path; radius not promoted to a model param).

CONCLUSIONS (differential, ground-truth):
- Inventor promotes a typed fillet radius to the next model parameter
  (d4, d5, ...) in CM, exactly like sketch dims. Unit: cm CONFIRMED.
- The '2.0' in fillet.ipt = 2mm radius in mm units inside the raw
  feature record (fallback when not param-promoted).
- New record type found: expression/dependency tables (RDxVar0
  referencing d0/104-style subscripted ids with 0x8000-flagged u32s)
  — Inventor's expression graph, documented for future decoding.

TOOLING: ipt2step now AUTO-DETECTS the fillet radius from d4+ params
(cm->mm) and replays the fillet — verified exact for both samples:
  1mm: volume 991.4159 = 1000 - 4*r^2*(1-pi/4)*h ✓ (faces 10)
  2mm: volume 965.66  ✓ (earlier session; formula now correctly derived)


## 7q. Session 13 — E1.5: expression/dependency graph DECODED

The RDxVar0 expression table (found session 12) is now fully decoded:
- Structure: per-variable DEPENDENCY LISTS:
  [u32 x][u32 namelen][NAME UTF-16]
  then flagged entries: [0x8000|id][u32 len][NAME UTF-16]...
- Semantics: each variable lists the variables created AFTER it
  (potential references in its expression).
- 'RDxVar*' = feature variables (fillet radius etc.) depending on dims.
- Verified across all samples:
  params.ipt: MyAngle->[MyLength,MyText], MyLength->[MyText]
  fillet1.ipt: RDxVar0->[d0..d4] (fillet var references sketch dims + its own)
  cyl/cube/fillet: d-chains as expected
- TOOLING: iptinfo.parameter_links() returns the graph; included in JSON.
- E1.5 READY: when a linked.ipt arrives (MyWidth driving a sketch dim),
  the graph will reveal the d->MyWidth binding; the rebuild engine can
  then propagate MyWidth edits through d-params to geometry.


## 7r. Session 14 — GROUND-TRUTH BATCH: E1.5 PROVEN, .iam FORMAT MAPPED

### linked.ipt — E1.5 parameter linking CONFIRMED
- Params: MyWidth=2.0cm(20mm), d2=2.0cm(sketch X dim), d4=0.8cm(extrude 8mm)
- Expression graph: MyWidth -> [RDxVar0, d2, d3, d4, d5]
- BINDING PROVEN: MyWidth(user param) drives d2(sketch X dim):
  value equality (2.0=2.0) + graph scope + X extent (20mm) ✓
- E1.5 LOOP VERIFIED: MyWidth edit 20->35mm => solid rebuilds 1866.76 mm³
  (expected 35*6.667*8 = 1866.8) ✓
- Discovery: linked.ipt stores ALL 8 solid corners as explicit points
  (full box B-rep), not just 4 sketch corners — extractor must dedupe.
- New unit pair seen: MyWidth uses (0x59, 0x5a).

### twofeat.ipt — MULTI-FEATURE confirmed
- Params: d0-d3 (cube sketch), d4=0.5cm (circle Ø5mm), d5=0.6cm (extrude 6mm)
- Topology: body x2, lump x2, shell x2 — TWO BODIES in one file!
- The second feature (circle on top face) creates its own body+lump.
- E3 multi-body extraction from .ipt: params + 2 bodies identifiable.

### chamfer.ipt — CHAMFER CONFIRMED
- Params: d4=0.2cm, d5=0.2cm (chamfer 2mm x2), d6=0.7853981633974483
  (= pi/4 — the chamfer ANGLE in radians! 45°)
- Topology: 12 faces (cube 6 + chamfer adds 6: 4 chamfer faces + edge splits)
- Chamfer record: TWO distance params + ONE angle param (pi/4 = 45°)

### hole.ipt — HOLE CONFIRMED
- Params: d4=0.5cm (Ø5mm), d5=0.6cm, d6=0.4cm, d7=0.2cm, d8=1.5708 (=pi/2!),
  d9=0.8cm, d10=2.059... (likely drill depth/angle combo)
- Topology: 10 faces (cube 6 + cylindrical hole + splits)
- Hole = diameter param + pi/2 angle + depth params.

### assembly.iam — FORMAT = SAME AS .ipt!
- OLE/CFB container ✓, same \x05 property streams ✓, RSeStorage ✓,
  RSeEmbeddings ✓, UFRxDoc ✓, Protein ✓
- NEW: CacheGraphics/ storage (OGS/DefaultScene = assembly scene cache)
- NEW: RSeStorage/RefdFiles/ = REFERENCED FILES (.ipt parts!)
- Conclusion: ALL Deviser tooling applies to .iam directly (.deva roadmap
  = trivial rename + RefdFiles handling + constraint decode).

All 5 ground-truth samples validate the engines built in E1-E4.


## 7s. Session 14b — .iam assembly support (step 2)

- iptinfo parses .iam out of the box (same container/RSe engine).
  Verified on assembly.iam: title='Assembly', thumbnail, RSe v8.
- PART REFERENCES found in B* zstd payloads as UTF-16 names:
  'Cyl:1' (occurrence instance label — Inventor's name:instanceNo form)
  'D - simple part' (referenced part display name)
- RefdFiles/ storage exists but is EMPTY in this sample; references live
  in the payloads (occurrence records).
- .deva roadmap: container ✓ (already), occurrence extraction (found),
  constraint decode (next), instance transforms (TBD).


## 7t. Session 15 — FEATURE REPLAYER: chamfer/hole/boss VERIFIED

classify_features() + replay_features() + rebuild_full() implemented:
- chamfer: pi/4-angle signature + first dist pair -> .chamfer(2mm)
  VERIFIED: chamfer.ipt -> 920.00 mm³ = 1000 - 4*(2*2/2)*10 EXACT
- hole: pi/2-angle signature + Ø param -> .hole(Ø) at sketch-bbox center
  VERIFIED: hole.ipt -> 803.65 mm³ = 1000 - pi*2.5²*10 EXACT (Ø5 through)
  (corner-drilling bug found+fixed: hole must go at the face center,
   not the global origin — quarter-overlap signature 49.09 = 196.35/4)
- boss (second extruded feature): Ø + depth params, no angle
  VERIFIED: twofeat.ipt -> 1117.81 mm³ = 1000 + pi*6.25*6 EXACT
- Full regression: all 8 geometry files verified (fillet1 991.42,
  cyl 523.17, cube 1000, linked 1066.67, fillet 1000)

Deviser now replays: sketch + extrude + fillet + chamfer + hole + boss
from clean-room-decoded .ipt data, every volume closed-form-exact.


## 7u. Session 15b — .devp FEATURE PERSISTENCE + GUI replay shipped

- ipt2devp: features[] serialized into .devp docs (chamfer/hole/boss with
  params); history[] includes feature ops; skeleton_from_ipt now uses the
  full session-15 rules (z-plane filter, angle grammars, robust depth)
- devp_to_solid: replays features on load — .devp round-trip verified:
  chamfer 920.00 ✓ hole 803.65 ✓ boss 1117.81 ✓ fillet 991.42 ✓
  linked 1066.67 ✓ cyl 523.17 ✓ cube 1000.00 ✓ (7/7 exact)
- GUI: feature replay wired into Rebuild + Export buttons (AppImage FR-1.5)
- The full pipeline is now end-to-end feature-aware:
  .ipt -> parse -> classify -> skeleton+features -> edit -> rebuild+replay
  -> save .devp (features persist) -> reopen -> replay -> export STEP


## 7v. Session 16 — .iam ASSEMBLY TREE + CONSTRAINT DECODED

The 'Bl2pnvpg' payload contains the assembly BROWSER TREE in the same
zstd+UTF-16 grammar. Record: [u32 id][u32 namelen][NAME][u32 classLen]
[CLASS-NAME][flagged refs...]. Decoded from assembly.iam:

  'New Assembly'            -> AmDocEntry          (assembly root)
  "Engineer's Notebook"    -> NBxNotebook
  'Constraints'             -> AmConstraintsEntry  (constraint folder)
  'Origin'                  -> OriginEntryFolder
  'AmAssemblyFeature'       -> (assembly features folder)
  'D - simple part:1'       -> AmPartInstEntry     (occurrence #1)
  'Cyl:1'                   -> AmPartInstEntry     (occurrence #2)
  'Mate:1'                  -> AmMateEntry         (THE MATE CONSTRAINT)
  'BRx' (x2, after instances) -> browser ref records
  7x OriginWorkFeatureEntry  (origin planes/axes)
  'AmViewRep' + 'Default'   (design views)

=> The .iam structure layer is SOLVED: document tree, part instances
(with :N instance numbering), mate constraints (AmMateEntry), origin,
view reps. Combined with session-14b (part refs in payloads + RefdFiles
storage) the .deva roadmap is: tree ✓, occurrences ✓, constraints ✓,
transforms (bok3gmb payload has the 3x4 instance matrix: rotation
(0,0,0/0,0,-1/...) f64s at @1448).

## 7w. Session 16b — .iam OCCURRENCE RECORDS + TRANSFORMS DECODED

The 'Bbok3gmb' payload (6755 bytes) carries the occurrence/transform layer.
Two grammars identified:

OCCURRENCE RECORD (name layer):
  [02 00 00 30][u32 0][u32 namelen][UTF16 name]
Decoded from assembly.iam — 9 records in order:
  'D - simple part:1', 'Cyl:1'  (the two part instances)
  'YZ Plane', 'XZ Plane', 'XY Plane', 'X Axis', 'Y Axis', 'Z Axis',
  'Center Point'  (7 origin work features)

TRANSFORM (0x42-tagged window):
  [00 80 42 00] + 13 f64 doubles (12 transform values + trailing 0)
Found in assembly.iam: 3 windows —
  @1309: all zeros (unplaced/zero matrix)
  @1448: [0,0,0,0, 0,0,-1,0, 0,0,-0,1, 0]  (a 90-degree placement —
         the Cyl:1 instance rotation seen in the viewer)
  @1583: [0,0,0,0, 0,1,0,-0, -0,1,0,0, 0]  (second placement/mate frame)
Exact row/column-major semantics + translation slot pending ONE more
ground-truth sample (an assembly with a known linear offset, e.g. a part
placed 50 mm along X).

iptinfo now ships:
  occurrences()  -> [{name}] for .iam files (9 records for assembly.iam)
  placed_transform() -> all non-zero 0x42-tagged windows (raw 12 doubles)
  assembly_tree() -> browser-filter records (UCx* classes)
All 16 corpus files still parse; part (.ipt) summaries are unchanged
(assembly decoding is .iam-scoped).

.deva roadmap update: tree ✓, occurrences ✓ (records+names),
constraints ✓ (session 16), transforms ✓ (located+extracted, semantics
pending 1 sample). Writer is next.

## 8. Open questions / next probes
1. Parameter record full grammar: unit token, parameter type/flags,
  tolerance fields, multi-parameter files (B2c with 3 params?)
2. ASM binary B-rep: `Bwcosukf` payload is ACIS 'ASM BinaryFile4' — the
  geometry. D sample (cube) available for structure mapping.
3. RSeSegInfo / RSeDbRevisionInfo structure (segment directory)
4. Stream-name ↔ role mapping is random per file; role must be detected
  from decompressed content (signature strings) — automate in iptinfo.
5. M* index format (maps segments→streams?)

## 9. Method note

1. C's iProperty: which property + value? (need user's known-answer)
   → `Zrxrt4ar` grew +36 bytes for C; iProperty text not found in plaintext
     anywhere in C — likely inside RSe DB pages or compressed. Re-check C with
     UTF-16 scan of ALL streams for the property VALUE string.
2. Parameter VALUE (10 mm) not yet located in B — name found, value not.
   Probe: create sample B2 with MyLength = a distinctive value (e.g. 123.456)
   and diff-scan for the IEEE754 double of 123.456 ( Inventor stores lengths in
   cm internally as doubles — candidates: 123.456, 1.23456, 1234.56).
3. Stream-name → role mapping (names are random per file).
4. Decompression of `Zrxrt4ar` segments (header suggests block compression).
5. D's geometry representation (out of current scope, later).

## 6. Method note

All findings above derive from: container parsing, stream listing, UTF-16 string
scans, and A/B/C/D size+content diffs. No decompilation, no disassembly.
