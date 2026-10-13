# Etch MCP Server — agent docs

**What this is:** the Etch vector sketch engine as an MCP server. Call tools,
get deterministic renders back. Same scene + brand = same pixels, every time.

## Install

```bash
cd ~/workspace/agent-tools-lab/engine
.venv/bin/python -c "import mcp"   # already installed in the venv
```

### Windows note: the Cairo DLL

`cairosvg` needs the native Cairo library (`libcairo-2.dll`), which pip cannot
ship on Windows. Two steps:

1. Install the GTK3 runtime from
   https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
   (run the `gtk3-runtime-...-ts-win64.exe`, tick **"Set up PATH"**).
2. Restart your terminal. That's it — `render.py` registers the GTK `bin`
   directory via `os.add_dll_directory()` at import time, so no manual PATH or
   env-var configuration is needed, including when Claude Code/Cursor spawns
   the server.

Verify: `engine\.venv\Scripts\python -c "import cairosvg; print('cairo ok')"`

The server runs over **stdio** (newline-delimited JSON-RPC). Launch command:

```
~/workspace/agent-tools-lab/engine/.venv/bin/python ~/workspace/agent-tools-lab/engine/mcp_server.py
```

## Client config

**Claude Code:**
```bash
claude mcp add etch -- /home/YOU/workspace/agent-tools-lab/engine/.venv/bin/python /home/YOU/workspace/agent-tools-lab/engine/mcp_server.py
```

**Cursor** (`~/.cursor/mcp.json` on macOS/Linux, `%USERPROFILE%\.cursor\mcp.json` on Windows):
```json
{
  "mcpServers": {
    "etch": {
      "command": "/home/YOU/workspace/agent-tools-lab/engine/.venv/bin/python",
      "args": ["/home/YOU/workspace/agent-tools-lab/engine/mcp_server.py"]
    }
  }
}
```

Windows example (paths must point at this repo's venv + `mcp_server.py`):
```json
{
  "mcpServers": {
    "etch": {
      "command": "C:\\\\Users\\\\YOU\\\\Documents\\\\projects\\\\sketchai\\\\engine\\\\.venv\\\\Scripts\\\\python.exe",
      "args": ["C:\\\\Users\\\\YOU\\\\Documents\\\\projects\\\\sketchai\\\\engine\\\\mcp_server.py"]
    }
  }
}
```

**Generic MCP client:** stdio transport, command + args as above.

## Tools (8)

| Tool | One-liner |
|---|---|
| `sketch_compose` | Scene graph → render (`render_id`, `content_hash`, `svg`, `png_base64`, bboxes) |
| `sketch_edit` | Patch ops on `node_id`s → new render + `diff.changed` |
| `sketch_sequence` | Scenes[] → storyboard + contact-sheet PNG |
| `components_list` | Token-cheap catalog (`type_filter`: `all`\|`container`\|`leaf`) |
| `brand_apply` | Resolve `$tokens` on a scene without rendering |
| `brand_validate` | Rule check without rendering → `passed` + `violations` |
| `assets_upload` | Store PNG/JPEG → `asset_id` + `path` (use `path` as image `src`) |
| `fonts_list` | Fonts actually installed here (family → styles → files) |

**Errors:** every tool returns `{"error": {"node_id", "reason", "suggestion"}}`
on failure — never a silent fallback. Check for the `"error"` key.

**Conventions:** `brand_id` defaults to `"protograph"`. Every node needs a
unique `node_id`. Prefer `stack`/`grid` over absolute coordinates (you can't
see the canvas; the layout engine can). `strict=true` blocks renders that
violate brand rules; `strict=false` warns instead.

## Worked example: the edit loop

**1. Discover components:**
```json
{"name": "components_list", "arguments": {"type_filter": "leaf"}}
```

**2. Compose a slide:**
```json
{"name": "sketch_compose", "arguments": {
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
}}
```
→ `{"render_id": "r_...", "content_hash": "6bed...", "png_base64": "iVBOR...",
"brand_validation": {"passed": true, ...}, ...}`

**3. Edit the headline (surgical — everything else byte-identical):**
```json
{"name": "sketch_edit", "arguments": {
  "render_id": "r_...",
  "patch_ops": [{"op": "set_text", "node_id": "s1-head", "text": "Launch Week"}]
}}
```
→ `{"render_id": "r_... (new)", "diff": {"changed": ["s1-head"], ...},
"previous_render_id": "r_..."}`

**4. Storyboard two frames + contact sheet:**
```json
{"name": "sketch_sequence", "arguments": {
  "brand_id": "protograph",
  "scenes": [<scene1>, <scene2>]
}}
```

## Notes

- **Not image generation.** Etch is a deterministic vector layout engine
  (scene graph → SVG → PNG). No diffusion / latent models — same scene + brand
  yields the same `content_hash` and pixels.
- Renders are **content-addressed**: re-composing an identical scene returns
  the existing `render_id` (cache hit, not a new render).
- Store is **in-memory** (process lifetime). Restart the server = fresh store.
- `png_base64` decodes to a standard PNG. `svg` is the editable source of truth.
- Determinism: no randomness, no timestamps in any tool output.
- Prefer brand font tokens (`$fonts.display` / `$fonts.body`) on text and
  badges. If `font` is omitted, layout uses bundled Hanken Grotesk (not DejaVu).
