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
