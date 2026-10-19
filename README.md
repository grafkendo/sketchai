# Etch — "Etch-A-Sketch for AI" (working title)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/grafkendo/sketchai/actions/workflows/ci.yml/badge.svg)](https://github.com/grafkendo/sketchai/actions/workflows/ci.yml)

A service that lets **AI agents draw** — composing storyboards, slides, and
social graphics from vector components instead of full prompt-to-image renders.

**Thesis:** agents should sketch like draftsmen (vectors + real fonts),
not like painters (pixels + luck). Far less compute, deterministic editing,
real fonts, surgical revisions.

## ✏️ Editable in Illustrator & Figma — not a flat picture

Every Etch render is a **real SVG file first**, and a PNG second. The SVG is
the source of truth, so anything Etch makes can be opened and manipulated in
professional design tools:

- **Adobe Illustrator:** open the `.svg` (or the PDF export) directly — every shape is a real vector.
- **Figma:** drag the `.svg` onto the canvas — it imports as editable vector and text layers.
- **Text stays text.** Headlines are real `<text>` elements in a named font (not outlines, not pixels), so you can retype them in either tool.
- **Every component is a named layer.** A node's `node_id` becomes its SVG id/group (`s1-head`, `s1-curve`, …), so pieces arrive labeled, not as anonymous blobs.
- **Fonts travel with the repo** in `engine/fonts/` (Bricolage Grotesque + Hanken Grotesk). Install those, or Illustrator/Figma will substitute a fallback font.
- One honest limit: Etch's stack/grid layout becomes flat positions in the SVG. Moving a piece in Figma won't reflow the rest — for reflow-style edits, use Etch's own `sketch_edit`, then re-export.

Try it: download [`examples/hello-editable.svg`](examples/hello-editable.svg), drag it into Figma or open it in Illustrator, and retype the headline.

**Model:** open core (MIT) + hosted SaaS. The engine and MCP server are free
for everyone; revenue comes from the managed cloud, pack marketplace, and
enterprise tiers.

## Quickstart

```bash
git clone https://github.com/grafkendo/sketchai.git
cd sketchai
python -m venv engine/.venv
engine/.venv/bin/pip install -r engine/requirements.txt
cd engine && ../engine/.venv/bin/python test_mcp.py   # 12/12 green = you're live
```

> **Windows:** `cairosvg` needs the native Cairo library. Install the GTK3
> runtime from
> https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
> (tick **"Set up PATH"**), restart your terminal, then run the tests.

To give your agent the tools, point any MCP client at the server over stdio:

```json
{
  "mcpServers": {
    "etch": {
      "command": "/path/to/sketchai/engine/.venv/bin/python",
      "args": ["/path/to/sketchai/engine/mcp_server.py"]
    }
  }
}
```

Full client setup (Claude Code, Cursor, generic): [engine/MCP.md](engine/MCP.md).

## Demo

A 6-slide branded carousel composed programmatically, then a surgical edit
(headline + accent color changed on slide 3 only — everything else
byte-identical):

![Demo carousel slide 1](engine/demo_out/slide-1.png)
*Slide 1 of the demo carousel — real Bricolage Grotesque type, exact brand hexes*

![First Cursor-driven render](engine/hello_magenta.png)
*The first render driven by an agent in Cursor: composed "HELLO", then edited to magenta*

![Editable SVG example](examples/hello-editable.svg)
*The same kind of render as an editable SVG: [examples/hello-editable.svg](examples/hello-editable.svg) — download it and open it in Illustrator or Figma. The headline is live text, and every element is a named, movable layer.*

![Game level layout](examples/game-level-layout.png)
*An agent-composed game level layout (1280×720): HUD with score / coins / world / time, a lives badge, platforms, question blocks, coins, a character, and a pipe — all vector components with real type. Etch works for level design and storyboarding, not just slides.*

## Docs

- [Agent Guide](AGENT_GUIDE.md) — **instructions for AI agents using Etch**, including a paste-in directive for system prompts / Cursor rules / project instructions.
- [Test Cases](TEST_CASES.md) — 10 hands-on prompts with pass/fail checks.
- [Whitepaper](whitepaper/etch-a-sketch-for-ai.md) — the argument: why agents
  can't draw, the composition-over-generation thesis, architecture, economics,
  and the open-core model.
- [Service spec](specs/sketch-service-spec.md) — API surface (`sketch.compose` /
  `sketch.edit` / `sketch.sequence`), component model, brand-token enforcement,
  deterministic edit/re-render loop, metering, risks.
- [Roadmap](ROADMAP.md) — phased build plan: spike → MVP API → MCP-native →
  storyboards/packs/billing → distribution.
- [Landscape research](research/landscape-report.md) — market and competitive
  research behind the spec.

## Status

Spec + research + whitepaper complete (Oct 2026). **Phase 0+1 engine built
(Oct 12, 2026):** `engine/` holds the deterministic render core — 14 typed
components, constraint/flow layout, brand-token enforcement at render time,
content-hashed compose/edit loop, FastAPI service (`POST /v1/renders`,
`PATCH /v1/renders/{id}`), CLI, and a 6-slide demo proving surgical edits
(`engine/demo_out/`). **Phase 2 MCP server built (Oct 12, 2026):** `engine/mcp_server.py`
exposes 8 tools over stdio (`sketch_compose/edit/sequence`, `components_list`,
`brand_apply`/`brand_validate`, `assets_upload`, `fonts_list`) — 12/12 tool tests
green; `engine/MCP.md` has client setup docs; `smithery.yaml` + `Dockerfile` +
`server.json` + `PUBLISHING.md` ready for registry publishing (needs repo public
+ his accounts). **Open-source prep done (Oct 13, 2026):** MIT `LICENSE`,
`CONTRIBUTING.md`, `SECURITY.md`, CI on Linux + Windows
(`.github/workflows/ci.yml`), `pyproject.toml` for `pip install`. Phase 3
(storyboards, packs, hosted SaaS billing) is next. The repo goes public when
the author flips it.

## Also parked (not dropped)

- MCP trust/verification layer for the noisy server registry
- Agent payments/billing rails for marketplaces
