#!/usr/bin/env python3
"""
test_motion.py — frame-sequence animation.

Direct module tests (frame count, order, determinism) + MCP-level tests
(sketch_animate via render_ids and storyboard_id). Run with:
    .venv/bin/python test_motion.py
"""

import io
import json
import os
import subprocess
import sys
import tempfile

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from motion import animate_gif, gif_frame_count  # noqa: E402
from components import EtchError  # noqa: E402

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


def _solid(color: tuple[int, int, int], size: int = 64) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


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


def test_module() -> None:
    frames = [_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))]
    tmp = tempfile.mkdtemp(prefix="etch-motion-")
    out = os.path.join(tmp, "test.gif")
    r1 = animate_gif(frames, 250, out_path=out)
    assert r1["frames"] == 3 and r1["ms_per_frame"] == 250
    assert os.path.isfile(out)
    with open(out, "rb") as f:
        data = f.read()
    assert gif_frame_count(data) == 3, "GIF must have 3 frames"
    # Frame ORDER: seek each frame and check the dominant color.
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    expected = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for i, color in enumerate(expected):
        im.seek(i)
        px = im.convert("RGB").getpixel((32, 32))
        # GIF quantizes; allow small drift.
        assert all(abs(a - b) < 30 for a, b in zip(px, color)), (i, px, color)
    print("PASS  3 frames -> GIF with 3 frames in order")

    # Deterministic: same frames, same bytes.
    r2 = animate_gif(frames, 250, out_path=os.path.join(tmp, "test2.gif"))
    with open(r2["path"], "rb") as f:
        assert f.read() == data, "GIF bytes must be deterministic"
    print("PASS  GIF bytes deterministic")

    # Duration recorded per frame.
    im = Image.open(io.BytesIO(data))
    assert im.info.get("duration") == 250, im.info
    print("PASS  ms_per_frame honored")

    # Error paths.
    for bad_frames, bad_ms in (([], 250), (frames, 0), (frames, -5)):
        try:
            animate_gif(bad_frames, bad_ms, out_path=os.path.join(tmp, "x.gif"))
            raise AssertionError("should have raised")
        except EtchError:
            pass
    print("PASS  empty frames / bad duration error cleanly")


def test_mcp() -> None:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_motion", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        names = sorted(t["name"] for t in _request(proc, "tools/list", {})["tools"])
        assert "sketch_animate" in names, names

        rids = []
        for word in ("One", "Two", "Three"):
            r = _call(proc, "sketch_compose", {"scene": _scene(word)})
            assert "error" not in r, r
            rids.append(r["render_id"])

        a = _call(proc, "sketch_animate",
                  {"render_ids": rids, "ms_per_frame": 300})
        assert "error" not in a, a
        assert a["frames"] == 3 and a["ms_per_frame"] == 300
        assert a["render_ids"] == rids
        assert os.path.isfile(a["gif_path"])
        with open(a["gif_path"], "rb") as f:
            assert gif_frame_count(f.read()) == 3
        print(f"PASS  sketch_animate(render_ids) -> 3-frame GIF at {a['gif_path']}")

        # Deterministic path: same inputs -> same file (no duplicate).
        a2 = _call(proc, "sketch_animate",
                   {"render_ids": rids, "ms_per_frame": 300})
        assert a2["gif_path"] == a["gif_path"], "same frames must reuse the GIF"
        print("PASS  identical animation reuses the cached GIF path")

        # Storyboard path.
        sq = _call(proc, "sketch_sequence",
                   {"scenes": [_scene("A"), _scene("B")]})
        a3 = _call(proc, "sketch_animate",
                   {"storyboard_id": sq["storyboard_id"]})
        assert a3["frames"] == 2, a3
        print("PASS  sketch_animate(storyboard_id) -> 2 frames")

        # Error paths.
        bad = _call(proc, "sketch_animate", {"render_ids": ["r_nope"]})
        assert "error" in bad and "r_nope" in bad["error"]["reason"], bad
        both = _call(proc, "sketch_animate",
                     {"render_ids": rids, "storyboard_id": sq["storyboard_id"]})
        assert "error" in both and "exactly one" in both["error"]["reason"], both
        neither = _call(proc, "sketch_animate", {})
        assert "error" in neither, neither
        print("PASS  bad render_id / ambiguous args error cleanly")
        print("\nAll motion tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_module()
    test_mcp()
