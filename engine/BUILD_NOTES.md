# Etch engine — BUILD NOTES (Phase 0 + Phase 1)

Built 2026-10-12. Spec: `../specs/sketch-service-spec.md` (§4, §5, §7).
Roadmap: `../ROADMAP.md` (Phase 0 + Phase 1 exit criteria — both met).

## What was built

`~/workspace/agent-tools-lab/engine/` — pure Python vector sketch engine:

| File | Role |
|---|---|
| `components.py` | 14 typed component builders returning JSON scene nodes (`frame`, `stack`, `grid`, `absolute`, `text`, `rect`, `circle`, `path`, `image`, `chart_bar`, `chart_donut`, `badge`, `divider`, `curve`). Every builder validates its params and raises `ComponentError(node_id, reason, suggestion)`. Includes `COMPONENT_CATALOG` (token-cheap schema listing for agents). |
| `layout.py` | Constraint/flow resolver (stack/grid/frame/absolute) + real-font text measurement (PIL against fontconfig-resolved TTFs) + deterministic SVG emitter. |
| `brands.py` | Brand JSON loading, `$token` resolution at render time, rule engine (`palette`, `fonts`, `no_pure_black`) returning structured violations. |
| `brands/protograph.json` | Real Protograph tokens: bg `#171310`, lime `#B6FF3B`, azure `#00A3FF`, magenta `#FF2E9D`, paper `#F7F2E8`; display "Bricolage Grotesk", body "Hanken Grotesk". |
| `render.py` | `compose()` (validate → copy → resolve tokens → layout → SVG → sha256), `edit()` (6 patch ops, non-mutating, diff summary), `to_png`/`to_pdf` via cairosvg. |
| `api.py` | FastAPI: `POST /v1/renders`, `PATCH /v1/renders/{id}`, `GET /v1/renders/{id}`, `GET /v1/components`, `POST /v1/brands/validate`. Content-addressed render IDs (re-POST = same ID). 422s name the node + reason + suggested fix. Metering logged to stdout. |
| `cli.py` | `compose` / `edit` / `render` terminal commands. |
| `demo.py` | Phase-1 exit demo (see below). |
| `test_determinism.py` | Determinism + brand-validation assertions (see below). |

## How to run

```bash
cd ~/workspace/agent-tools-lab/engine
.venv/bin/python demo.py                  # 6-slide carousel + surgical edit -> demo_out/
.venv/bin/python test_determinism.py      # determinism assertions
.venv/bin/python api.py                   # FastAPI on :8000
.venv/bin/python cli.py compose --scene scene.json --brand protograph --png out.png
```

Always use `.venv/bin/python` — the venv holds fastapi/uvicorn/cairosvg/Pillow
(system python has cairosvg+Pillow but no fastapi; PEP 668 blocks system pip).

## Demo results (2026-10-12)

`demo.py` builds a 6-slide 1080×1080 carousel from a structured "prompt" table
using Protograph brand tokens → `demo_out/slide-1.png` … `slide-6.png`
(all brand validation passed). Then a surgical edit on slide 3 only:

- `set_text s3-headline` → "HOW-TO GUIDES", `set_fill s3-curve1` → magenta
- hash before `9c6c535d…`, after `63b31490…` (changed, as it must)
- `diff.changed == ["s3-headline", "s3-curve1"]` — nothing else touched
- slides 1, 2, 4, 5, 6 re-compose to their original hashes (byte-identical)

`test_determinism.py`: identical scene → identical sha256 **and byte-identical
PNGs**; one-node edit → hash changes; unedited original re-renders to its
original hash; off-palette color correctly rejected naming node + rule.

## Environment notes

- **Fonts: NO fallback needed.** Bricolage Grotesque (ExtraBold file) and
  Hanken Grotesk (Medium file) are installed at `~/.fonts/` and resolve via
  fontconfig — the demo PNGs use the real brand fonts. Weight requests map to
  the closest installed style (800→ExtraBold, 500→Medium); anything else falls
  back to the single installed cut, then DejaVu Sans (reported, never silent).
- cairosvg 2.9.1 + Pillow 12.3.0 (venv), Python 3.12.3. PNG output verified
  byte-deterministic; SVG attribute order is fixed at every call site.
- `content_hash` is over the **resolved** scene graph (tokens substituted),
  not the SVG bytes — so `$colors.lime` and `#B6FF3B` hash identically, and
  emitter fixes don't invalidate existing hashes.

## Known limitations (honest)

1. **PDF bytes are not guaranteed stable** — cairosvg embeds metadata; don't
   hash PDFs. SVG/PNG are the deterministic artifacts.
2. **URL image slots are passed through, never fetched** — render can't change
   under you, but a dead URL means a broken `<image>` (validation only checks
   local files exist).
3. **Text measurement == layout truth only for installed fonts.** On a machine
   without Bricolage/Hanken, output silently uses fallback metrics — same
   machine = deterministic, cross-machine = may differ. Phase 2 should pin
   font files in-repo.
4. **Charts are simple** (bar + donut); no axes, legends, or line charts yet.
5. **No `sketch.sequence`/storyboard endpoint yet** — demo does 6 separate
   renders; sequencing is Phase 3 per roadmap.
6. **Auth**: `ETCH_API_KEY` env enables X-API-Key checks; unset = open (dev).
   Store is in-memory (process lifetime). Both are Phase-1-per-spec; Phase 3
   adds DB + Stripe metering.

## Bugs found and fixed during build

- **Double-translation**: container `<g>` elements emitted `translate(x,y)`
  while children already carried absolute coordinates → nested content
  drifted down-right and some text rendered off-canvas. Fix: groups carry no
  transform (children are absolute by construction).
- **Anchor semantics**: `anchor="end"` with `x=1000` previously ended text at
  `1000+width` (clipped page numbers). Now `x` is the anchor *point* —
  matches SVG `text-anchor` behavior.
- `stack()`/`grid()` gained optional `x`/`y` position hints (used by the demo).

## What Phase 2 adds (per roadmap)

MCP server (`sketch.compose/edit/sequence`, `components.list`,
`brand.apply/validate`, `assets.upload`, `fonts.list`), font files pinned
in-repo, publish to Smithery + official registry, agent-oriented docs.

---

# Phase 2 — MCP server (built 2026-10-12)

## What was added

| File | Role |
|---|---|
| `engine/mcp_server.py` | FastMCP (mcp 1.30, stdio) wrapping the engine: 8 tools. Thin wrappers — zero render logic duplicated. |
| `engine/test_mcp.py` | Spawns the server over stdio, speaks JSON-RPC, exercises all 8 tools + error paths. 12 assertions, all pass. |
| `engine/MCP.md` | Agent-oriented docs: install, Claude Code/Cursor/generic config, tool table, worked compose→edit→sequence session. |
| `engine/requirements.txt` | Pinned deps (mcp 1.30, cairosvg 2.9.1, Pillow 12.3.0, fastapi 0.143, uvicorn 0.54). |
| `engine/fonts/` | Pinned brand TTFs (BricolageGrotesque-ExtraBold, HankenGrotesk-Medium) — the "pin fonts in-repo" item from Phase 1 notes. |
| `engine/assets/` | Created at runtime by `assets_upload` (git-ignored by nature — user content). |
| `smithery.yaml` | Repo-root Smithery manifest (stdio, no config needed). |
| `Dockerfile` | Repo-root container image: python:3.12-slim + cairo/pango system libs + pinned fonts installed to the system font dir. |
| `server.json` | Official MCP registry entry (draft — must pass `mcp-publisher validate`). |
| `PUBLISHING.md` | Repo-root checklist for Mitchel: public repo, Smithery submit, Docker build+push to GHCR, `mcp-publisher` flow, Glama/mcpservers.org/PulseMCP, clean-machine smoke test. |

Launch: `engine/.venv/bin/python engine/mcp_server.py` (stdio).

## The 8 tools

`sketch_compose` (scene → render_id, content_hash, svg, png_base64, bboxes,
brand_validation; idempotent), `sketch_edit` (render_id + patch_ops → new
render + diff.changed), `sketch_sequence` (scenes[] → storyboard_id, per-scene
renders, contact-sheet PNG), `components_list` (token-cheap catalog),
`brand_apply` (token resolution preview, no render), `brand_validate`
(rules check, no render), `assets_upload` (base64 PNG/JPEG → asset_id + path),
`fonts_list` (fontconfig families → styles → files).

## Design decisions (why)

- **Errors as `{"error": {...}}` dicts, not raised exceptions.** Spec §4:
  the agent needs WHICH node/param failed, WHY, and a suggested fix in a
  parseable shape. `EtchError.to_dict()` already carries it.
- **Duplicated ~20 lines of store/compose logic instead of importing api.py.**
  `api._do_compose` prints metering to stdout — and on stdio transport,
  stdout IS the protocol. A stray log line would corrupt JSON-RPC framing.
- **Pinned `mcp<2` (1.30.0).** mcp 2.x renamed FastMCP→MCPServer and changed
  the server API; the stdio wire protocol is identical, so clients can't tell
  the difference, but the v1 Python API is the battle-tested one.
- **This SDK's stdio = newline-delimited JSON-RPC**, not Content-Length
  framing. `test_mcp.py` speaks NDJSON (found the hard way: first version
  hung; the server tried to parse `Content-Length:` as JSON).
- **`assets_upload` returns a filesystem path for image `src`.** The engine
  already embeds local files as base64 — no engine changes needed. An
  `asset://` URI scheme would be nicer; deferred to Phase 3.
- **Contact sheet via Pillow tiling**, not SVG: keeps the storyboard path
  free of a second layout pass; per-scene renders stay individually
  addressable.

## Test results (2026-10-12)

`test_mcp.py`: 12/12 pass — tools/list shows 8 tools; compose returns PNG
bytes + SVG + bboxes; re-compose is idempotent; edit changes exactly
`["s1-head"]`; bad node_id returns a structured error with a suggestion;
2-scene sequence returns storyboard + decodable contact sheet; leaf filter
returns 10 components; off-palette fill fails brand_validate naming the node;
`$colors.lime` resolves to `#B6FF3B`; 4×4 PNG upload round-trips; fonts_list
shows Bricolage Grotesk + Hanken Grotesk; unknown component type errors
cleanly.

## Known limitations (honest)

1. **stdio-only.** No Streamable-HTTP transport yet — Smithery *hosted* mode
   and some clients want HTTP. Phase 3 (the FastAPI app already exists).
2. **In-memory stores** (renders, storyboards) — process lifetime, same as
   Phase 1 API. Restart = fresh.
3. **`server.json` is draft** — written against the documented registry shape;
   `mcp-publisher validate` is the authority at publish time.
4. **Docker image untested end-to-end here** — the Dockerfile installs the
   same pinned deps + fonts, but the image build/push is Mitchel's step
   (needs his Docker Hub/GHCR login).
5. `assets_upload` has no size cap and no auth — fine for a local stdio
   process; the hosted service (Phase 3) needs both.
