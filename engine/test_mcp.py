#!/usr/bin/env python3
"""
test_mcp.py — exercise every MCP tool over stdio JSON-RPC.

Spawns mcp_server.py as a subprocess and speaks the MCP protocol:
initialize -> notifications/initialized -> tools/list -> tools/call x N.
Asserts correct results AND sane error messages. Run with:
    .venv/bin/python test_mcp.py
"""

import base64
import io
import json
import os
import subprocess
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
SERVER = [sys.executable, os.path.join(ENGINE, "mcp_server.py")]

_req_id = 0


def _frame(msg: dict) -> bytes:
    # WHY newline-delimited: this SDK's stdio transport reads NDJSON
    # (one JSON-RPC object per line), not Content-Length framing.
    return (json.dumps(msg) + "\n").encode("utf-8")


def _read_msg(proc) -> dict:
    line = proc.stdout.readline()
    if not line:
        raise AssertionError("server closed stdout (crashed?)")
    return json.loads(line)


def _request(proc, method: str, params: dict | None = None) -> dict:
    global _req_id
    _req_id += 1
    proc.stdin.write(_frame({"jsonrpc": "2.0", "id": _req_id,
                             "method": method, "params": params or {}}))
    proc.stdin.flush()
    resp = _read_msg(proc)
    assert resp.get("id") == _req_id, f"id mismatch: {resp}"
    if "error" in resp:
        raise AssertionError(f"JSON-RPC error for {method}: {resp['error']}")
    return resp["result"]


def _notify(proc, method: str):
    proc.stdin.write(_frame({"jsonrpc": "2.0", "method": method}))
    proc.stdin.flush()


def _call(proc, tool: str, args: dict) -> dict:
    res = _request(proc, "tools/call", {"name": tool, "arguments": args})
    assert not res.get("isError"), f"tool {tool} errored: {res}"
    # FastMCP serializes dict results as a single JSON TextContent block.
    texts = [b.get("text", "") for b in res["content"] if b.get("type") == "text"]
    assert texts, f"no text content from {tool}: {res}"
    return json.loads(texts[0])


def _scene(headline: str, fill: str = "$colors.lime") -> dict:
    return {
        "canvas": {"width": 1080, "height": 1080},
        "root": {
            "type": "frame", "node_id": "s1", "width": 1080, "height": 1080,
            "fill": "$colors.bg",
            "children": [
                {"type": "text", "node_id": "s1-head", "text": headline,
                 "font": "$fonts.display", "size": 120, "fill": fill,
                 "x": 80, "y": 400},
            ],
        },
    }


def main() -> None:
    proc = subprocess.Popen(
        SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE,
    )
    try:
        init = _request(proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test_mcp", "version": "0.1"},
        })
        assert "serverInfo" in init, f"bad initialize: {init}"
        _notify(proc, "notifications/initialized")

        tools = _request(proc, "tools/list", {})["tools"]
        names = sorted(t["name"] for t in tools)
        expected = sorted(["sketch_compose", "sketch_edit", "sketch_sequence",
                           "sketch_batch", "sketch_diff", "sketch_animate",
                           "sketch_provenance", "components_list",
                           "brand_apply", "brand_validate", "assets_upload",
                           "fonts_list", "packs_list", "sketch_from_pack"])
        assert names == expected, f"tool mismatch: {names}"
        print(f"PASS  tools/list -> {len(names)} tools")

        # 1. compose a 2-node scene
        r1 = _call(proc, "sketch_compose", {"scene": _scene("Hello")})
        assert "error" not in r1, r1
        assert r1["render_id"].startswith("r_") and len(r1["content_hash"]) == 64
        png = base64.b64decode(r1["png_base64"])
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
        assert r1["svg"].lstrip().startswith("<svg")
        assert "s1-head" in r1["bboxes"], "bboxes missing node"
        assert r1["brand_validation"]["passed"] is True
        print(f"PASS  sketch_compose -> {r1['render_id']} hash={r1['content_hash'][:12]}")

        # 2. idempotent re-compose -> same render_id
        r1b = _call(proc, "sketch_compose", {"scene": _scene("Hello")})
        assert r1b["render_id"] == r1["render_id"], "compose not idempotent"
        print("PASS  sketch_compose idempotent (same scene -> same render_id)")

        # 3. surgical edit
        r2 = _call(proc, "sketch_edit", {
            "render_id": r1["render_id"],
            "patch_ops": [{"op": "set_text", "node_id": "s1-head", "text": "World"}],
        })
        assert "error" not in r2, r2
        assert r2["render_id"] != r1["render_id"], "edit must change the hash"
        assert r2["diff"]["changed"] == ["s1-head"], r2["diff"]
        assert r2["previous_render_id"] == r1["render_id"]
        print(f"PASS  sketch_edit -> diff.changed={r2['diff']['changed']}")

        # 4. bad edit -> structured error naming the node
        bad = _call(proc, "sketch_edit", {
            "render_id": r1["render_id"],
            "patch_ops": [{"op": "set_text", "node_id": "nope", "text": "x"}],
        })
        assert "error" in bad and bad["error"]["node_id"] == "nope", bad
        assert bad["error"]["suggestion"], "error must suggest a fix"
        print(f"PASS  bad edit -> error names node: {bad['error']['reason'][:60]}...")

        # 5. sequence of 2 scenes
        sq = _call(proc, "sketch_sequence",
                   {"scenes": [_scene("One"), _scene("Two", "$colors.azure")]})
        assert "error" not in sq, sq
        assert sq["storyboard_id"].startswith("sb_")
        assert len(sq["renders"]) == 2
        sheet = base64.b64decode(sq["contact_sheet_base64"])
        assert sheet[:8] == b"\x89PNG\r\n\x1a\n", "contact sheet not a PNG"
        print(f"PASS  sketch_sequence -> {sq['storyboard_id']} + contact sheet")

        # 6. components_list (filtered)
        cat = _call(proc, "components_list", {"type_filter": "leaf"})
        assert "error" not in cat, cat
        assert all(c["kind"] == "leaf" for c in cat["components"])
        assert any(c["name"] == "text" for c in cat["components"])
        print(f"PASS  components_list -> {len(cat['components'])} leaf components")

        # 7. brand_validate catches a violation
        bad_scene = _scene("Hi")
        bad_scene["root"]["children"][0]["fill"] = "#123456"
        bv = _call(proc, "brand_validate",
                   {"brand_id": "protograph", "scene": bad_scene})
        assert bv["passed"] is False, bv
        pal = [v for v in bv["violations"] if v["rule"] == "palette"]
        assert pal and pal[0]["node_id"] == "s1-head", bv["violations"]
        print(f"PASS  brand_validate -> violation on {pal[0]['node_id']}")

        # 8. brand_apply resolves tokens without rendering
        ba = _call(proc, "brand_apply",
                   {"brand_id": "protograph", "scene": _scene("Hi")})
        assert "error" not in ba, ba
        head = ba["resolved_scene"]["root"]["children"][0]
        assert head["fill"] == "#B6FF3B", f"token not resolved: {head['fill']}"
        print("PASS  brand_apply -> $colors.lime resolved to #B6FF3B")

        # 9. assets_upload stores a tiny PNG
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, "PNG")
        up = _call(proc, "assets_upload",
                   {"name": "red.png",
                    "data_base64": base64.b64encode(buf.getvalue()).decode()})
        assert "error" not in up, up
        assert up["asset_id"].startswith("a_") and os.path.exists(up["path"])
        assert (up["width"], up["height"]) == (4, 4)
        print(f"PASS  assets_upload -> {up['asset_id']} at {up['path']}")

        # 10. fonts_list shows the real brand fonts
        fl = _call(proc, "fonts_list", {})
        fams = [f["family"] for f in fl["fonts"]]
        assert any("Bricolage" in f for f in fams), fams
        assert any("Hanken" in f for f in fams), fams
        print(f"PASS  fonts_list -> {len(fams)} families incl. Bricolage Grotesk, Hanken Grotesk")

        # 11. malformed compose -> structured error (not a crash)
        m = _call(proc, "sketch_compose",
                  {"scene": {"canvas": {"width": 100, "height": 100},
                             "root": {"type": "frobnicate", "node_id": "x"}}})
        assert "error" in m and m["error"]["node_id"] == "x", m
        print(f"PASS  bad component -> error: {m['error']['reason'][:60]}...")

        print("\nAll MCP tool tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    main()
