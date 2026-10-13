#!/usr/bin/env python3
"""
Etch — MCP server (Phase 2).

Exposes the deterministic vector sketch engine to any MCP-capable agent
over stdio. Thin wrappers over render.py / brands.py / components.py —
all the real logic stays in the engine.

Run:  .venv/bin/python mcp_server.py        (stdio transport)
Test: .venv/bin/python test_mcp.py

WHY stdio: it's the universal MCP transport — Claude Code, Cursor, and
every generic client speak it with zero network config. (SSE/HTTP comes
in Phase 3 with the hosted service.)

WHY errors are returned as {"error": {...}} dicts instead of raised:
spec §4 — a bad call must tell the agent WHICH node/param failed, WHY,
and how to fix it, in a shape the agent can parse and iterate on.
EtchError.to_dict() already carries exactly that shape.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from brands import load_brand, resolve_tokens, validate
from components import COMPONENT_CATALOG, EtchError
from layout import _fontconfig_index
from render import compose, edit, to_png

mcp = FastMCP("etch")

# In-memory stores (process lifetime — same pattern as api.py).
# WHY not import api.py's store: api._do_compose prints metering to stdout,
# and on stdio transport stdout IS the protocol. Duplicating the ~20 lines
# here keeps the wire clean. Noted in BUILD_NOTES.md.
RENDERS: dict[str, dict] = {}
STORYBOARDS: dict[str, dict] = {}
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# ------------------------------------------------------- helpers

def _render_id(content_hash: str, brand_id: str | None) -> str:
    # WHY include brand_id: same scene under two brands = two renders.
    # Content-addressed: re-compose is a cache hit, not a new render.
    seed = f"{content_hash}|{brand_id or ''}"
    return "r_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _err(e: EtchError) -> dict:
    return {"error": e.to_dict()}


def _do_compose(scene: dict, brand_id: str | None, strict: bool) -> dict:
    """Shared compose path. Raises EtchError on any problem."""
    result = compose(scene, brand_id=brand_id, validate_brand=True)
    bv = result.get("brand_validation")
    if bv and not bv["passed"] and strict:
        lines = [f"[{v['node_id']}] {v['rule']}: {v['message']}"
                 for v in bv["violations"]]
        raise EtchError(
            None,
            "brand validation failed: " + "; ".join(lines),
            "Fix the violations, or call with strict=false for warn mode.",
        )
    rid = _render_id(result["content_hash"], brand_id)
    record = {
        "render_id": rid,
        "content_hash": result["content_hash"],
        "brand_id": brand_id,
        "width": result["width"],
        "height": result["height"],
        "bboxes": result["bboxes"],
        "svg": result["svg"],
        "brand_validation": bv,
        "scene": result["scene"],  # resolved (tokens substituted)
    }
    RENDERS[rid] = record
    return record


def _public(record: dict) -> dict:
    return {k: record[k] for k in ("render_id", "content_hash", "brand_id",
                                   "width", "height", "bboxes", "brand_validation")}


# ------------------------------------------------------- tools

@mcp.tool()
def sketch_compose(scene: dict, brand_id: str | None = "protograph",
                   strict: bool = True) -> dict:
    """Compose a scene graph into a deterministic render.

    scene: {"canvas": {"width": 1080, "height": 1080}, "root": {...node tree...}}.
    Every node needs a unique node_id (used by sketch_edit). Use
    components_list to see the 14 component types and their params.
    Example scene root: {"type": "frame", "node_id": "s1", "width": 1080,
    "height": 1080, "fill": "$colors.bg", "children": [
      {"type": "text", "node_id": "s1-head", "text": "Hello",
       "font": "$fonts.display", "size": 120, "fill": "$colors.lime"}]}.
    Returns render_id, content_hash, bboxes, brand_validation, svg,
    and png_base64. Same scene+brand = same content_hash (idempotent).
    """
    try:
        record = _do_compose(scene, brand_id, strict)
    except EtchError as e:
        return _err(e)
    png = to_png(record["svg"])
    out = _public(record)
    out["svg"] = record["svg"]
    out["png_base64"] = base64.b64encode(png).decode("ascii")
    return out


@mcp.tool()
def sketch_edit(render_id: str, patch_ops: list[dict]) -> dict:
    """Surgically edit a previous render. patch_ops target node_ids.

    Ops: set_text {node_id, text}, set_fill {node_id, fill},
    set_attr {node_id, attrs}, replace_node {node_id, node},
    add_node {parent_id, node, index?}, remove_node {node_id}.
    Example: [{"op": "set_text", "node_id": "s1-head", "text": "New headline"}].
    Returns new render_id, new hash, diff.changed (exactly the nodes
    touched), and previous_render_id. Untouched content is byte-identical.
    """
    record = RENDERS.get(render_id)
    if record is None:
        return {"error": {"node_id": None,
                          "reason": f"unknown render_id '{render_id}'",
                          "suggestion": "Compose a scene with sketch_compose first; "
                                        "render_ids live for the server process lifetime."}}
    try:
        new_scene, diff = edit(record["scene"], patch_ops)
        new_record = _do_compose(new_scene, record["brand_id"], strict=True)
    except EtchError as e:
        return _err(e)
    png = to_png(new_record["svg"])
    out = _public(new_record)
    out["svg"] = new_record["svg"]
    out["png_base64"] = base64.b64encode(png).decode("ascii")
    out["diff"] = diff
    out["previous_render_id"] = render_id
    return out


@mcp.tool()
def sketch_sequence(scenes: list[dict], brand_id: str | None = "protograph",
                    columns: int = 2) -> dict:
    """Render multiple scenes as a storyboard.

    Each scene renders independently (deterministic, like sketch_compose).
    Returns storyboard_id, per-scene render_ids + content_hashes, and a
    contact_sheet_base64 PNG tiling all scenes in a grid (columns wide).
    Example: scenes=[scene1, scene2] for a 2-frame storyboard.
    """
    if not scenes:
        return {"error": {"node_id": None, "reason": "scenes is empty",
                          "suggestion": "Pass 2+ scene dicts, each like sketch_compose's scene."}}
    try:
        records = [_do_compose(s, brand_id, strict=True) for s in scenes]
    except EtchError as e:
        return _err(e)

    # Deterministic storyboard ID from the scene hashes (no timestamps).
    seed = "|".join(r["content_hash"] for r in records) + f"|{brand_id or ''}"
    sb_id = "sb_" + hashlib.sha256(seed.encode()).hexdigest()[:16]
    STORYBOARDS[sb_id] = {"storyboard_id": sb_id,
                          "render_ids": [r["render_id"] for r in records]}

    # Contact sheet: tile PNGs in a columns-wide grid with Pillow.
    from PIL import Image
    imgs = [Image.open(io.BytesIO(to_png(r["svg"]))) for r in records]
    cw, chh = max(i.width for i in imgs), max(i.height for i in imgs)
    rows = (len(imgs) + columns - 1) // columns
    sheet = Image.new("RGB", (cw * columns, chh * rows), (23, 19, 16))
    for i, im in enumerate(imgs):
        sheet.paste(im, ((i % columns) * cw, (i // columns) * chh))
    buf = io.BytesIO()
    sheet.save(buf, "PNG")
    return {
        "storyboard_id": sb_id,
        "renders": [{"render_id": r["render_id"],
                     "content_hash": r["content_hash"]} for r in records],
        "contact_sheet_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
    }


@mcp.tool()
def components_list(type_filter: str = "all") -> dict:
    """List the component catalog (token-cheap: names + compact params).

    type_filter: "all" | "container" | "leaf". Start here before composing —
    it shows every component, its kind, and its params (a "!" means required,
    "?" optional, "=x" the default, "a|b" an enum).
    """
    if type_filter not in ("all", "container", "leaf"):
        return {"error": {"node_id": None,
                          "reason": f"unknown type_filter '{type_filter}'",
                          "suggestion": "Use 'all', 'container', or 'leaf'."}}
    items = [c for c in COMPONENT_CATALOG
             if type_filter == "all" or c["kind"] == type_filter]
    return {"components": items}


@mcp.tool()
def brand_apply(brand_id: str, scene: dict) -> dict:
    """Preview what a brand does to a scene: resolve $tokens, no render.

    Returns the scene with every $colors.* / $fonts.* / $spacing.* token
    substituted. Useful before sketch_compose, or to re-skin one scene
    under several brands deterministically.
    """
    try:
        brand = load_brand(brand_id)
    except EtchError as e:
        return _err(e)
    working = copy.deepcopy(scene)
    if "root" not in working:
        return {"error": {"node_id": None,
                          "reason": "scene must be a dict with 'root'",
                          "suggestion": "Minimal scene: {'canvas': {...}, 'root': {...}}."}}
    resolve_tokens(working["root"], brand)
    return {"brand_id": brand_id, "resolved_scene": working}


@mcp.tool()
def brand_validate(brand_id: str, scene: dict) -> dict:
    """Check a scene against a brand's rules WITHOUT rendering.

    Returns {"brand_id", "passed", "violations": [{node_id, rule, message,
    suggestion}]}. Rules: palette (only brand hexes), fonts (only brand
    fonts), no_pure_black. Fix violations before sketch_compose, or compose
    with strict=false for warn mode.
    """
    try:
        brand = load_brand(brand_id)
    except EtchError as e:
        return _err(e)
    working = copy.deepcopy(scene)
    if "root" not in working:
        return {"error": {"node_id": None,
                          "reason": "scene must be a dict with 'root'",
                          "suggestion": "Minimal scene: {'canvas': {...}, 'root': {...}}."}}
    resolve_tokens(working["root"], brand)
    report = validate(working, brand)
    return {"brand_id": brand_id, **report}


@mcp.tool()
def assets_upload(name: str, data_base64: str) -> dict:
    """Store an image asset for use in image slots. No generation — only
    stores what you give it.

    name: filename like "hero.png". data_base64: PNG/JPEG bytes, base64.
    Returns asset_id and path — pass the path as an image node's "src".
    Example: {"type": "image", "node_id": "img1", "src": "<path>",
    "width": 400, "height": 300}.
    """
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except Exception:
        return {"error": {"node_id": None, "reason": "data_base64 is not valid base64",
                          "suggestion": "Base64-encode the raw PNG/JPEG bytes."}}
    from PIL import Image as PILImage
    try:
        im = PILImage.open(io.BytesIO(raw))
        im.verify()
    except Exception:
        return {"error": {"node_id": None, "reason": "bytes are not a valid image",
                          "suggestion": "Upload PNG or JPEG bytes only."}}
    safe = "".join(c for c in os.path.basename(name) if c.isalnum() or c in "._-") or "asset"
    aid = "a_" + hashlib.sha256((safe + data_base64).encode()).hexdigest()[:16]
    os.makedirs(ASSETS_DIR, exist_ok=True)
    path = os.path.join(ASSETS_DIR, f"{aid}_{safe}")
    with open(path, "wb") as f:
        f.write(raw)
    im = PILImage.open(io.BytesIO(raw))  # re-open: verify() closes the file
    return {"asset_id": aid, "path": path, "width": im.width, "height": im.height,
            "use_as_src": path}


@mcp.tool()
def fonts_list() -> dict:
    """List fonts actually resolvable on this machine via fontconfig.

    Returns families with their installed styles and file paths — the same
    fonts the layout engine measures with and the renderer draws with, so
    measurement and pixels can never disagree.
    """
    fams: dict[str, dict[str, str]] = {}
    for path, family, style in sorted(_fontconfig_index()):
        fams.setdefault(family, {})[style] = path
    return {"fonts": [{"family": fam,
                       "styles": [{"style": s, "file": f}
                                  for s, f in sorted(styles.items())]}
                      for fam, styles in sorted(fams.items())]}


if __name__ == "__main__":
    mcp.run()  # stdio transport
