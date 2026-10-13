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
import datetime
import functools
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from brands import load_brand, resolve_tokens, validate
from components import COMPONENT_CATALOG, EtchError
from layout import _fontconfig_index
from provenance import manifest_for, render_id_for
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
    # Single derivation lives in provenance.py (the CLI uses it too).
    return render_id_for(content_hash, brand_id)


def _err(e: EtchError) -> dict:
    return {"error": e.to_dict()}


def _provenance_for(record: dict) -> dict:
    return manifest_for(record["render_id"], record["content_hash"],
                        record["brand_id"], record.get("parents", []))


# ------------------------------------------------------- metering

def _meter_log_path() -> str:
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meter.jsonl")
    return os.environ.get("ETCH_METER_LOG", default)


def _meter(tool: str, credits: int, render_id: str | None = None,
           content_hash: str | None = None, extra: dict | None = None) -> None:
    """Append one JSON line per successful tool call.

    Line: {ts, tool, credits, render_id, content_hash, ...extra}. WHY a
    timestamp here but never in render outputs: the meter log is an
    operational billing record, not a render artifact — wall-clock belongs
    here, and content_hash determinism is untouched. WHY swallowing errors:
    metering must never break a render; a full disk shouldn't fail the
    tool call (the failure goes to stderr, which is safe on stdio).
    """
    line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tool": tool, "credits": credits,
            "render_id": render_id, "content_hash": content_hash}
    if extra:
        line.update(extra)
    try:
        with open(_meter_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError as e:
        print(f"etch: meter log write failed: {e}", file=sys.stderr)


def _metered(credits):
    """Decorator: meter successful tool calls.

    credits: int, or callable(kwargs) -> int for dynamic schedules
    (sequence = per scene, batch = per row). Failed calls ({"error": ...}
    results) accrue nothing — there's no render to bill.
    WHY a decorator: 14 tools × manual _meter() calls is 14 chances to
    forget one; the decorator makes metering impossible to skip.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            result = fn(**kwargs)
            if isinstance(result, dict) and "error" not in result:
                c = credits(kwargs) if callable(credits) else credits
                _meter(fn.__name__, c,
                       result.get("render_id"), result.get("content_hash"))
            return result
        return wrapper
    return deco


def _do_compose(scene: dict, brand_id: str | None, strict: bool,
                parents: list[str] | None = None) -> dict:
    """Shared compose path. Raises EtchError on any problem."""
    result = compose(scene, brand_id=brand_id, validate_brand=True)
    bv = result.get("brand_validation")
    # WHY strict blocks only on severity=="error": "warn" rules (contrast
    # hints, color budgets) guide an iterating agent but must never stop a
    # draft from rendering. bv["passed"] is False if ANY violation exists.
    errs = [v for v in (bv.get("violations", []) if bv else [])
            if v.get("severity", "error") == "error"]
    if errs and strict:
        lines = [f"[{v['node_id']}] {v['rule']}: {v['message']}" for v in errs]
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
        "parents": list(parents or []),
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


def _full_response(record: dict) -> dict:
    """The standard render payload: metadata + svg + PNG + provenance."""
    png = to_png(record["svg"])
    out = _public(record)
    out["svg"] = record["svg"]
    out["png_base64"] = base64.b64encode(png).decode("ascii")
    out["provenance"] = _provenance_for(record)
    return out


# ------------------------------------------------------- tools

@mcp.tool()
@_metered(1)
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
    return _full_response(record)


@mcp.tool()
@_metered(0)
def packs_list() -> dict:
    """List available component packs and their fragments.

    A pack is a library of named scene fragments (e.g. carousel slides) with
    {{param}} placeholders. Returns [{name, description, brand, fragments:
    [{name, description, params}]}]. Use sketch_from_pack to render one.
    """
    from packs import list_packs
    try:
        return {"packs": list_packs()}
    except EtchError as e:
        return _err(e)


@mcp.tool()
@_metered(0)
def sketch_from_pack(pack: str, fragment: str, params: dict | None = None,
                     brand_id: str | None = "protograph",
                     strict: bool = True) -> dict:
    """Render a pack fragment with params filled in.

    Example: sketch_from_pack("carousel-basics", "hook",
    {"headline": "Hello", "subline": "World"}). Missing params error naming
    exactly which ones. Returns the standard render payload (render_id,
    content_hash, svg, png_base64, provenance, brand_validation).
    """
    from packs import get_fragment_scene
    try:
        scene, pack_data = get_fragment_scene(pack, fragment, params)
        record = _do_compose(scene, brand_id or pack_data.get("brand"), strict)
    except EtchError as e:
        return _err(e)
    out = _full_response(record)
    out["pack"] = pack
    out["fragment"] = fragment
    return out


@mcp.tool()
@_metered(lambda kw: len(kw.get("rows", [])))
def sketch_batch(template_scene: dict, rows: list[dict],
                 brand_id: str | None = "protograph",
                 strict: bool = True) -> dict:
    """Render one scene per data row (mail-merge for graphics).

    template_scene: a scene with {{placeholder}} strings in any text/fill/src
    param. rows: list of dicts, e.g. [{"name": "Ada", "role": "Engineer"}].
    Each row renders deterministically — same template+row = same hash.
    Returns {"renders": [{row_index, row, render_id, content_hash}],
    "count"}. A bad row fails the whole call, naming the row index and the
    missing placeholder.
    """
    from batch import batch_rows
    try:
        prepared = batch_rows(template_scene, rows)
    except EtchError as e:
        return _err(e)
    renders = []
    try:
        for i, scene in prepared:
            record = _do_compose(scene, brand_id, strict)
            renders.append({"row_index": i, "row": rows[i],
                            "render_id": record["render_id"],
                            "content_hash": record["content_hash"]})
    except EtchError as e:
        return _err(e)
    return {"renders": renders, "count": len(renders),
            "brand_id": brand_id}


@mcp.tool()
@_metered(0)
def sketch_diff(render_id_a: str, render_id_b: str) -> dict:
    """Visual diff: pixel-compare two renders, highlight what changed.

    Returns {"render_id_a", "render_id_b", "pct_changed" (0-100),
    "regions": [{x, y, width, height}] bounding boxes of changed areas,
    "diff_base64": PNG with changed pixels painted red on a dimmed base}.
    Use after sketch_edit to VERIFY only the intended nodes moved.
    Both renders must share a canvas size.
    """
    from diff import visual_diff
    ra = RENDERS.get(render_id_a)
    rb = RENDERS.get(render_id_b)
    missing = [rid for rid, r in ((render_id_a, ra), (render_id_b, rb)) if r is None]
    if missing:
        return {"error": {"node_id": None,
                          "reason": f"unknown render_id(s): {', '.join(missing)}",
                          "suggestion": "Compose scenes with sketch_compose first; "
                                        "render_ids live for the server process lifetime."}}
    try:
        result = visual_diff(to_png(ra["svg"]), to_png(rb["svg"]))
    except EtchError as e:
        return _err(e)
    return {
        "render_id_a": render_id_a,
        "render_id_b": render_id_b,
        "content_hash_a": ra["content_hash"],
        "content_hash_b": rb["content_hash"],
        "pct_changed": result["pct_changed"],
        "regions": result["regions"],
        "diff_base64": base64.b64encode(result["diff_png"]).decode("ascii"),
    }


@mcp.tool()
@_metered(0)
def sketch_animate(render_ids: list[str] | None = None,
                   storyboard_id: str | None = None,
                   ms_per_frame: int = 500) -> dict:
    """Animate renders into a GIF: frames in order, ms_per_frame each.

    Pass EITHER render_ids (explicit frame order) OR storyboard_id (frames
    in storyboard order). Classic use: successive sketch_edit versions of
    one scene, or sketch_sequence output. Returns {"gif_path", "frames",
    "ms_per_frame"}. The GIF is deterministic — same frames, same bytes.
    """
    from motion import animate_gif
    if (render_ids is None) == (storyboard_id is None):
        return {"error": {"node_id": None,
                          "reason": "pass exactly one of render_ids or storyboard_id",
                          "suggestion": "render_ids=[...] for explicit order, or "
                                        "storyboard_id from sketch_sequence."}}
    if storyboard_id is not None:
        sb = STORYBOARDS.get(storyboard_id)
        if sb is None:
            return {"error": {"node_id": None,
                              "reason": f"unknown storyboard_id '{storyboard_id}'",
                              "suggestion": "Create one with sketch_sequence first."}}
        rids = list(sb["render_ids"])
    else:
        rids = list(render_ids or [])
    missing = [rid for rid in rids if rid not in RENDERS]
    if missing:
        return {"error": {"node_id": None,
                          "reason": f"unknown render_id(s): {', '.join(missing)}",
                          "suggestion": "Compose scenes with sketch_compose first."}}
    try:
        frames = [to_png(RENDERS[rid]["svg"]) for rid in rids]
        result = animate_gif(frames, ms_per_frame)
    except EtchError as e:
        return _err(e)
    return {"gif_path": result["path"], "frames": result["frames"],
            "ms_per_frame": result["ms_per_frame"],
            "bytes": result["bytes"], "render_ids": rids}


@mcp.tool()
@_metered(0)
def sketch_provenance(render_id: str) -> dict:
    """Return the signed-render manifest for a render_id.

    Manifest: {render_id, content_hash, brand_id, parents (edit lineage),
    engine_version, signed, signature?}. If ETCH_SIGNING_KEY is set on the
    server, signature is HMAC-SHA256 over the canonical manifest — verify it
    with the same key. Deterministic: no timestamps, re-signing is stable.
    """
    record = RENDERS.get(render_id)
    if record is None:
        return {"error": {"node_id": None,
                          "reason": f"unknown render_id '{render_id}'",
                          "suggestion": "Compose a scene with sketch_compose first; "
                                        "render_ids live for the server process lifetime."}}
    return {"provenance": _provenance_for(record)}


@mcp.tool()
@_metered(1)
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
        new_record = _do_compose(new_scene, record["brand_id"], strict=True,
                                 parents=[render_id])
    except EtchError as e:
        return _err(e)
    png = to_png(new_record["svg"])
    out = _public(new_record)
    out["svg"] = new_record["svg"]
    out["png_base64"] = base64.b64encode(png).decode("ascii")
    out["provenance"] = _provenance_for(new_record)
    out["diff"] = diff
    out["previous_render_id"] = render_id
    return out


@mcp.tool()
@_metered(lambda kw: len(kw.get("scenes", [])))
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
@_metered(0)
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
@_metered(0)
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
@_metered(0)
def brand_validate(brand_id: str, scene: dict) -> dict:
    """Check a scene against a brand's rules WITHOUT rendering.

    Returns {"brand_id", "passed", "violations": [{node_id, rule, severity,
    message, suggestion}]}. Rules: palette (only brand hexes), fonts (only
    brand fonts), no_pure_black, contrast (text fill vs. background >=
    min_ratio, default 4.5), max_colors (scene color budget, neutrals free).
    severity is "error" (blocks strict composes) or "warn" (reported, never
    blocks). Fix violations before sketch_compose, or compose with
    strict=false for warn mode.
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
@_metered(0)
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
@_metered(0)
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


class _ApiKeyMiddleware:
    """Pure-ASGI API-key gate for HTTP mode.

    WHY pure ASGI instead of Starlette's BaseHTTPMiddleware: it wraps
    whatever app FastMCP builds with zero dependence on Starlette version
    internals. Lifespan and non-HTTP scopes pass through untouched.
    Rejects with 401 unless the X-API-Key header matches ETCH_API_KEY.
    """

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1"): v.decode("latin-1")
                       for k, v in scope.get("headers", [])}
            if headers.get("x-api-key") != self.api_key:
                body = json.dumps({"error": {
                    "reason": "missing or invalid X-API-Key",
                    "suggestion": "Set the X-API-Key header to the server's "
                                  "ETCH_API_KEY value."}}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def _run_http() -> None:
    """Streamable-HTTP transport: the hosted mode.

    ETCH_HOST (default 127.0.0.1), ETCH_PORT (default 8000). If ETCH_API_KEY
    is set, every request needs a matching X-API-Key header (401 otherwise).
    WHY build the app manually instead of mcp.run(transport="http"): we need
    to wrap it in the API-key middleware, which run() doesn't support.
    """
    import uvicorn

    host = os.environ.get("ETCH_HOST", "127.0.0.1")
    port = int(os.environ.get("ETCH_PORT", "8000"))
    api_key = os.environ.get("ETCH_API_KEY")
    app = mcp.streamable_http_app()
    if api_key:
        app = _ApiKeyMiddleware(app, api_key)
        print(f"etch: http mode on {host}:{port} (API key required)",
              file=sys.stderr)
    else:
        print(f"etch: http mode on {host}:{port} (no API key — open)",
              file=sys.stderr)
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    """Console-script entry point (``etch-mcp``) for the pip-installed package.

    ETCH_TRANSPORT selects the transport: "stdio" (default — Claude Code,
    Cursor, any MCP client, zero network config) or "http" (Streamable HTTP,
    the hosted mode with optional API-key auth and usage metering).
    """
    transport = os.environ.get("ETCH_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        mcp.run()  # stdio transport
    elif transport == "http":
        _run_http()
    else:
        raise ValueError(
            f"unknown ETCH_TRANSPORT '{transport}' (use 'stdio' or 'http')")


if __name__ == "__main__":
    main()
