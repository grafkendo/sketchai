#!/usr/bin/env python3
"""
test_vdiff.py — visual diff of renders.

Direct module tests (identical -> 0%, size mismatch errors) + MCP-level
tests (sketch_diff after a one-node edit flags only that node's region).
Run with:
    .venv/bin/python test_vdiff.py
"""

import base64
import io
import json
import os
import subprocess
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from diff import visual_diff  # noqa: E402
from components import EtchError  # noqa: E402
from render import compose, to_png  # noqa: E402

_req_id = 0


def _frame(msg: dict) -> bytes:
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


def _call(proc, tool: str, args: dict) -> dict:
    res = _request(proc, "tools/call", {"name": tool, "arguments": args})
    assert not res.get("isError"), f"tool {tool} errored: {res}"
    texts = [b.get("text", "") for b in res["content"] if b.get("type") == "text"]
    assert texts, f"no text content from {tool}: {res}"
    return json.loads(texts[0])


def _scene(headline: str) -> dict:
    return {
        "canvas": {"width": 400, "height": 400},
        "root": {
            "type": "frame", "node_id": "s1", "width": 400, "height": 400,
            "fill": "$colors.bg",
            "children": [
                {"type": "text", "node_id": "s1-head", "text": headline,
                 "font": "$fonts.display", "size": 60, "fill": "$colors.lime",
                 "x": 40, "y": 150},
            ],
        },
    }


def _overlaps(a: dict, b: dict) -> bool:
    return not (a["x"] + a["width"] < b["x"] or b["x"] + b["width"] < a["x"]
                or a["y"] + a["height"] < b["y"] or b["y"] + b["height"] < a["y"])


def test_module() -> None:
    png1 = to_png(compose(_scene("Hello"), brand_id="protograph")["svg"])
    png2 = to_png(compose(_scene("Hello"), brand_id="protograph")["svg"])
    assert png1 == png2, "deterministic renders must be byte-identical"
    d = visual_diff(png1, png2)
    assert d["pct_changed"] == 0.0, d["pct_changed"]
    assert d["regions"] == [], d["regions"]
    print("PASS  identical renders -> 0% changed, no regions")

    png3 = to_png(compose(_scene("Goodbye"), brand_id="protograph")["svg"])
    d2 = visual_diff(png1, png3)
    assert 0 < d2["pct_changed"] < 50, d2["pct_changed"]
    assert len(d2["regions"]) == 1, f"expected 1 region, got {d2['regions']}"
    assert d2["diff_png"][:8] == b"\x89PNG\r\n\x1a\n"
    # Deterministic: same pair, same diff bytes.
    d2b = visual_diff(png1, png3)
    assert d2b["diff_png"] == d2["diff_png"] and d2b["regions"] == d2["regions"]
    print(f"PASS  one-word change -> {d2['pct_changed']}% in 1 region, deterministic")

    small = to_png(compose(_scene("Hi"), brand_id="protograph")["svg"])
    from PIL import Image
    tiny = io.BytesIO()
    Image.open(io.BytesIO(small)).resize((200, 200)).save(tiny, "PNG")
    try:
        visual_diff(png1, tiny.getvalue())
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "differ in size" in e.reason, e.reason
    print("PASS  size mismatch errors cleanly")


def test_mcp() -> None:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_vdiff", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        names = sorted(t["name"] for t in _request(proc, "tools/list", {})["tools"])
        assert "sketch_diff" in names, names

        r1 = _call(proc, "sketch_compose", {"scene": _scene("Hello")})
        assert "error" not in r1, r1
        head_box = r1["bboxes"]["s1-head"]

        # Self-diff is zero.
        d0 = _call(proc, "sketch_diff",
                   {"render_id_a": r1["render_id"], "render_id_b": r1["render_id"]})
        assert d0["pct_changed"] == 0.0 and d0["regions"] == [], d0
        print("PASS  sketch_diff self-compare -> 0%")

        # One-node edit -> exactly that node's region flagged.
        r2 = _call(proc, "sketch_edit", {
            "render_id": r1["render_id"],
            "patch_ops": [{"op": "set_text", "node_id": "s1-head",
                            "text": "Hello, world, this is much longer"}],
        })
        d = _call(proc, "sketch_diff",
                  {"render_id_a": r1["render_id"], "render_id_b": r2["render_id"]})
        assert "error" not in d, d
        assert d["pct_changed"] > 0, d
        assert len(d["regions"]) == 1, f"expected 1 region, got {d['regions']}"
        assert _overlaps(d["regions"][0], head_box), \
            f"region {d['regions'][0]} doesn't overlap edited node {head_box}"
        assert base64.b64decode(d["diff_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"PASS  one-node edit -> {d['pct_changed']}% in 1 region overlapping the node")

        bad = _call(proc, "sketch_diff",
                    {"render_id_a": r1["render_id"], "render_id_b": "r_nope"})
        assert "error" in bad and "r_nope" in bad["error"]["reason"], bad
        print("PASS  unknown render_id errors cleanly")
        print("\nAll visual-diff tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_module()
    test_mcp()
