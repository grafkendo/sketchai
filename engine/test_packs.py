#!/usr/bin/env python3
"""
test_packs.py — component packs.

Direct module tests (pack loading, fragment substitution, error paths) +
MCP-level tests (packs_list, sketch_from_pack for all 3 fragments).
Run with:
    .venv/bin/python test_packs.py
"""

import base64
import json
import os
import subprocess
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from packs import get_fragment_scene, list_packs, load_pack  # noqa: E402
from components import EtchError  # noqa: E402
from render import compose  # noqa: E402

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


_PARAMS = {
    "hook": {"headline": "What does an AI\nmedia company\nactually make?",
             "subline": "A new kind of studio."},
    "content": {"kicker": "TUTORIALS", "headline": "Learn the craft.",
                "subline": "Fast, visual lessons."},
    "cta": {"headline": "Follow for the drops.", "cta_label": "Follow"},
}


def test_module() -> None:
    packs = list_packs()
    names = [p["name"] for p in packs]
    assert "carousel-basics" in names, names
    cb = next(p for p in packs if p["name"] == "carousel-basics")
    frags = {f["name"]: f for f in cb["fragments"]}
    assert set(frags) == {"hook", "content", "cta"}, frags.keys()
    assert frags["hook"]["params"] == ["headline", "subline"]
    print("PASS  packs_list shows carousel-basics with 3 fragments + params")

    # Pack names come from tool callers and are joined onto the packs
    # directory, so anything but a plain name must be rejected.
    for bad in ("../brands/protograph", "carousel-basics/../../x", "a b"):
        try:
            load_pack(bad)
            raise AssertionError(f"should have rejected {bad!r}")
        except EtchError as e:
            assert "invalid pack name" in e.reason, e.reason
    print("PASS  pack name must be a plain name (no path traversal)")

    # Each fragment substitutes and composes cleanly.
    for fname, params in _PARAMS.items():
        scene, pack = get_fragment_scene("carousel-basics", fname, params)
        result = compose(scene, brand_id="protograph")
        assert result["brand_validation"]["passed"] is True, \
            f"{fname}: {result['brand_validation']['violations']}"
        head_text = params.get("headline", "").split("\n")[0]
        # Headlines may wrap across tspans — check distinctive words.
        words = [w for w in head_text.replace(".", "").split() if len(w) > 3]
        assert words and all(w in result["svg"] for w in words), \
            f"{fname}: headline words missing from SVG"
    print("PASS  all 3 fragments render with brand validation passing")

    # Unknown pack names what's available.
    try:
        load_pack("nope")
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "carousel-basics" in e.suggestion, e.suggestion
    print("PASS  unknown pack errors listing available packs")

    # Unknown fragment names what's available.
    try:
        get_fragment_scene("carousel-basics", "nope", {})
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "hook" in e.suggestion and "content" in e.suggestion, e.suggestion
    print("PASS  unknown fragment errors listing available fragments")

    # Missing param names the param.
    try:
        get_fragment_scene("carousel-basics", "hook", {"headline": "Hi"})
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "subline" in e.reason, e.reason
    print("PASS  missing param errors naming it")


def test_mcp() -> None:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_packs", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        names = sorted(t["name"] for t in _request(proc, "tools/list", {})["tools"])
        assert "packs_list" in names and "sketch_from_pack" in names, names

        pl = _call(proc, "packs_list", {})
        assert any(p["name"] == "carousel-basics" for p in pl["packs"]), pl
        print("PASS  packs_list over MCP")

        hashes = set()
        for fname, params in _PARAMS.items():
            r = _call(proc, "sketch_from_pack",
                      {"pack": "carousel-basics", "fragment": fname,
                       "params": params})
            assert "error" not in r, r
            assert r["pack"] == "carousel-basics" and r["fragment"] == fname
            assert r["render_id"].startswith("r_")
            assert "png_base64" not in r
            assert os.path.isfile(r["png_path"]), r["png_path"]
            with open(r["png_path"], "rb") as f:
                assert f.read(8) == b"\x89PNG\r\n\x1a\n"
            assert r["brand_validation"]["passed"] is True
            hashes.add(r["content_hash"])
        assert len(hashes) == 3
        print("PASS  sketch_from_pack renders all 3 fragments -> 3 hashes")

        # Deterministic: same fragment+params, same hash.
        r2 = _call(proc, "sketch_from_pack",
                   {"pack": "carousel-basics", "fragment": "hook",
                    "params": _PARAMS["hook"]})
        assert r2["content_hash"] in hashes
        print("PASS  sketch_from_pack is deterministic")

        bad = _call(proc, "sketch_from_pack",
                    {"pack": "nope", "fragment": "hook", "params": {}})
        assert "error" in bad and "carousel-basics" in bad["error"]["suggestion"], bad
        print("PASS  unknown pack errors over MCP with available packs")
        print("\nAll pack tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_module()
    test_mcp()
