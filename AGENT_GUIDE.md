# Etch — Instructions for AI Agents

**Who this is for:** any AI agent (Cursor, Claude Code, ChatGPT with MCP, a custom agent, etc.) that has the Etch MCP server connected and needs to *draw* something — a slide, carousel, storyboard, wireframe, chart graphic, or social post.

**What Etch is:** a vector sketch engine exposed as 14 MCP tools. You describe a scene as a graph of typed components with real fonts and exact brand colors, and Etch renders it deterministically. Same scene + same brand = same pixels, every time. Editing is surgical: change one named piece, everything else stays byte-identical.

Deep technical docs live in [engine/MCP.md](engine/MCP.md). Hands-on practice prompts live in [TEST_CASES.md](TEST_CASES.md). This file is the short, practical version — plus a directive you can paste into your own system prompt / project rules.

---

## ⭐ The Directive — paste this into your instructions

Copy everything in the box below into your system prompt, Cursor rules (`.cursor/rules`), Claude project instructions, or equivalent. It is self-contained.

```text
DIRECTIVE: Use Etch for drawing.

You have access to Etch, a vector sketch tool, through MCP tools prefixed
sketch_ / components_ / brand_ / packs_ / fonts_ / assets_.

WHEN TO USE IT: Use Etch — not image generation — whenever you need a
graphic that contains words, numbers, charts, diagrams, UI wireframes,
slides, carousels, storyboards, or anything that must match a brand or be
edited later. Image generators garble text and cannot make surgical edits;
Etch uses real fonts, exact hex colors, and deterministic renders.
Use image generation only for photographic / painterly imagery, and even
then prefer dropping the result into an Etch image slot so the text and
layout stay exact.

HOW TO WORK:
1. Discover first: call components_list and fonts_list before your first
   compose in a session. Never invent component types or font names.
2. Compose with sketch_compose. Give every node a unique node_id. Prefer
   stack / grid layout over absolute x/y coordinates — you cannot see the
   canvas, the layout engine can.
3. Use brand tokens, not raw hex, wherever a brand is in play:
   $colors.bg, $colors.lime, $colors.azure, $colors.magenta, $colors.paper,
   $fonts.display, $fonts.body. Default brand_id is "protograph".
4. Validate before you present: run brand_validate (or check the
   brand_validation field on the compose result). Fix violations, do not
   ignore them. Never use pure black — use $colors.bg.
5. Edit, never re-roll: to change a render, use sketch_edit with patch ops
   on the specific node_id. Report which node_ids changed (the diff field).
   Never recompose the whole scene for a one-word or one-color change.
6. For multi-frame work (carousels, storyboards, wireframes) use
   sketch_sequence and return the contact sheet. For many variants of one
   template use sketch_batch. For reusable fragments, check packs_list and
   sketch_from_pack before building a scene from scratch.
7. Report back: after every render, tell the user the render_id, the
   content_hash, where the PNG was saved, and show the image if you can.
   If a tool returns an "error" field, read its suggestion, fix that exact
   thing, and retry once — do not silently fall back to image generation.
8. Renders return file paths by default (png_path / svg_path under
   engine/assets/renders/). Open those files; only pass include_png=true
   when you have no filesystem access.

RULES: Determinism is a feature — re-composing an identical scene returning
the same content_hash is correct, not a bug. The render store is in-memory:
if the server restarted, old render_ids are gone, recompose from the scene.
```

---

## When to use Etch vs. the alternatives

| Need | Use |
|---|---|
| Slide, carousel, social graphic with a headline | ✅ Etch |
| UI wireframe / app screen sketch (see `examples/airport-luggage-wireframe.png`) | ✅ Etch |
| Storyboard, diagram, chart graphic, quote card | ✅ Etch |
| Anything that will need a small fix later ("make the badge magenta") | ✅ Etch (`sketch_edit`) |
| 50 variants of one card with different names/quotes | ✅ Etch (`sketch_batch`) |
| A photograph, a painting, a textured illustration | Image generation — then place it in an Etch `image` slot (`gen_prompt` or `assets_upload`) so text stays real |

## The 14 tools, in the order you'll usually use them

| Step | Tool | What it does |
|---|---|---|
| 1 | `components_list` | The component catalog (14 types). Filter: `all` / `container` / `leaf` |
| 1 | `fonts_list` | Fonts actually installed on this machine — only use names from here |
| 2 | `packs_list` | Ready-made fragments (e.g. `carousel-basics`: `hook`, `content`, `cta`) |
| 2 | `brand_apply` | Resolve `$tokens` on a scene without rendering — good for debugging |
| 2 | `brand_validate` | Check palette / fonts / contrast / max-colors rules without rendering |
| 3 | `sketch_compose` | Scene graph → PNG + SVG. Returns `render_id`, `content_hash`, `provenance` |
| 3 | `sketch_from_pack` | Render a pack fragment with `params` instead of building a scene |
| 3 | `sketch_sequence` | Several scenes → storyboard + tiled contact-sheet PNG |
| 3 | `sketch_batch` | One template with `{{placeholders}}` + many rows → one render per row |
| 4 | `sketch_edit` | Patch ops on `node_id`s → new render + `diff.changed` list |
| 4 | `sketch_diff` | Two renders → diff PNG (changes in red) + % changed |
| 5 | `sketch_animate` | Renders / a storyboard → deterministic animated GIF |
| 5 | `sketch_provenance` | Signed manifest for a render (who/what/when + edit lineage) |
| — | `assets_upload` | Store a PNG/JPEG and get a path to use as an `image` node's `src` |

## Component cheat sheet (14)

**Containers:** `frame` (fixed region), `stack` (flow layout — prefer this), `grid` (even columns), `absolute` (escape hatch, every child needs x/y).

**Leaves:** `text` (real fonts, `\n` breaks lines), `rect`, `circle`, `path` (raw SVG path), `image` (asset slot), `chart_bar`, `chart_donut`, `badge` (pill label, auto-sized), `divider`, `curve` (decorative band).

Every node needs: `type`, a unique `node_id`, and its required params (marked `!` in `components_list` output).

## A minimal working scene

```json
{
  "brand_id": "protograph",
  "scene": {
    "canvas": {"width": 1080, "height": 1080},
    "root": {
      "type": "frame", "node_id": "s1", "width": 1080, "height": 1080,
      "fill": "$colors.bg",
      "children": [
        {"type": "text", "node_id": "s1-head", "text": "Launch Day",
         "font": "$fonts.display", "size": 140, "fill": "$colors.lime",
         "x": 80, "y": 420},
        {"type": "curve", "node_id": "s1-curve", "width": 1080, "height": 260,
         "fill": "$colors.magenta", "x": 0, "y": 820}
      ]
    }
  }
}
```

Then edit it surgically (only `s1-head` changes):

```json
{"render_id": "<from compose>", "patch_ops": [
  {"op": "set_text", "node_id": "s1-head", "text": "Launch Week"}
]}
```

## Common mistakes — don't do these

1. **Inventing a component or font.** If it's not in `components_list` / `fonts_list`, it doesn't exist.
2. **Absolute-positioning everything.** You can't see the canvas. Use `stack` / `grid` and let the layout engine place things.
3. **Recomposing to fix a typo.** That's what `sketch_edit` exists for. Recomposing wastes the determinism guarantee.
4. **Raw hex everywhere.** Use `$colors.*` / `$fonts.*` tokens so a brand swap is one change, and validation can protect you.
5. **Ignoring the `error` field.** Errors come back as `{"error": {"node_id", "reason", "suggestion"}}`. Follow the suggestion literally.
6. **Expecting old renders after a restart.** The store is in-memory. Keep the scene JSON if you may need the graphic again.
7. **Pure black (`#000000`).** Brand rule forbids it — use `$colors.bg` (#171310).

## Setup (one time, for the human reading over the agent's shoulder)

Point any MCP client at the server over stdio:

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

On Windows, use the venv's `python.exe` and the full Windows path to `mcp_server.py`, and make sure the GTK3 runtime is installed (Cairo DLL) — see [engine/MCP.md](engine/MCP.md). Verify with: *"Use Etch to list fonts and components"* — you should get real answers from both tools before trying to compose.
