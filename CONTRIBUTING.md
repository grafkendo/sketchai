# Contributing to Etch

Thanks for being here. Etch is an "Etch-A-Sketch for AI": a deterministic
vector sketch engine that AI agents use to compose graphics from typed
components instead of rolling diffusion dice. Every design decision optimizes
for agents, not humans.

## Dev setup

```bash
git clone https://github.com/grafkendo/sketchai.git
cd sketchai
python -m venv engine/.venv
engine/.venv/bin/pip install -r engine/requirements.txt   # Windows: engine\.venv\Scripts\pip
```

**Windows only:** cairosvg needs the native Cairo library (`libcairo-2.dll`),
which pip cannot ship. Install the GTK3 runtime from
https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases
(tick **"Set up PATH"**), restart your terminal, and verify with:

```bash
python -c "import cairosvg; print('cairo ok')"
```

`render.py` auto-registers the GTK `bin` directory at import, so no manual
configuration is needed beyond installing the runtime. Full details:
[engine/MCP.md](engine/MCP.md).

## Running the tests

```bash
cd engine
.venv/bin/python test_determinism.py   # render core: hashing, edits, brand rules
.venv/bin/python test_mcp.py           # MCP server: all 8 tools over stdio
```

Both suites must be fully green before you open a PR.

## The hard rules

These are non-negotiable — they *are* the product:

1. **Determinism.** Renders are pure functions of the scene graph. No
   randomness, no timestamps, no iteration-order leaks in output. Same scene +
   same brand = same `content_hash` = byte-identical bytes, always.
2. **Errors teach.** A failed call names the offending `node_id` (or param),
   says *why* it failed, and suggests a fix. Never a silent fallback, never a
   bare stack trace to the agent.
3. **Real fonts only.** Text is set from real TTFs resolved through
   `layout.resolve_font`. Never pretend a font is used when it isn't — the
   `was_fallback` flag exists so substitutions are always reported, never
   silent.
4. **Comments explain WHY.** Mitchel's rule: when something works, the code
   should say *why* the mechanism was chosen, not just what it does.
5. **Don't break the launch paths.** After your change, all of these must
   still work:
   - `cd engine && python test_mcp.py`
   - `cd engine && python test_determinism.py`
   - `cd engine && python demo.py`
   - direct launch: `python engine/mcp_server.py` (from repo root)
   - bare sibling imports (`from components import ...`) when run from inside
     `engine/` — no renames of engine files, no import-path restructuring.

## PR expectations

- Tests green on Linux **and** Windows (CI runs both).
- Keep tool schemas token-cheap: enums over free text, defaults everywhere,
  one example per tool description. Agents pay per token.
- Keep `engine/fonts/` pinned: if you add a font, commit the TTF and note why
  in `engine/BUILD_NOTES.md`.
- Update `engine/BUILD_NOTES.md` when you change engine behavior.

## What NOT to do

- Don't add photoreal/diffusion generation to the render path. Diffusion
  output enters as `image`-slot *input* — Etch owns layout + type, not pixels.
- Don't widen the MCP surface without a spec note. The tool surface is the
  API contract; propose first in an issue.
