#!/usr/bin/env python3
"""
test_batch.py — data-driven batch rendering.

Direct module tests (placeholder substitution, missing-key errors, leftover
detection) + MCP-level test (sketch_batch: 3 rows -> 3 distinct hashes) +
CLI test (CSV -> renders + PNGs). Run with:
    .venv/bin/python test_batch.py
"""

import csv
import json
import os
import subprocess
import sys
import tempfile

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from batch import batch_rows, substitute_placeholders  # noqa: E402
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


def _template() -> dict:
    return {
        "canvas": {"width": 1080, "height": 1080},
        "root": {
            "type": "frame", "node_id": "s1", "width": 1080, "height": 1080,
            "fill": "$colors.bg",
            "children": [
                {"type": "text", "node_id": "s1-head", "text": "Hello, {{name}}!",
                 "font": "$fonts.display", "size": 120, "fill": "{{accent}}",
                 "x": 80, "y": 400},
                {"type": "badge", "node_id": "s1-role", "text": "{{role}}",
                 "fill": "$colors.lime", "x": 80, "y": 600},
            ],
        },
    }


def test_module() -> None:
    rows = [
        {"name": "Ada", "role": "Engineer", "accent": "$colors.lime"},
        {"name": "Grace", "role": "Admiral", "accent": "$colors.azure"},
        {"name": "Hopper", "role": "Pioneer", "accent": "$colors.magenta"},
    ]
    prepared = batch_rows(_template(), rows)
    assert len(prepared) == 3
    hashes = set()
    for i, scene in prepared:
        head = scene["root"]["children"][0]
        badge = scene["root"]["children"][1]
        assert head["text"] == f"Hello, {rows[i]['name']}!", head["text"]
        assert badge["text"] == rows[i]["role"]
        # Template itself untouched (substitution works on a copy).
        assert "{{name}}" in _template()["root"]["children"][0]["text"]
        result = compose(scene, brand_id="protograph")
        hashes.add(result["content_hash"])
        # Tokens inside substituted values still resolve at render time.
        assert "B6FF3B" in result["svg"] or "00A3FF" in result["svg"] \
            or "FF2E9D" in result["svg"]
    assert len(hashes) == 3, "each row must produce a distinct render"
    print("PASS  3 rows -> 3 distinct hashes, placeholders substituted")

    # Missing key names the placeholder and the available keys.
    try:
        substitute_placeholders(_template(), {"name": "Ada"})
        raise AssertionError("should have raised")
    except EtchError as e:
        # Fails fast on the first missing key ({{accent}} in fill).
        assert "accent" in e.reason, e.reason
        assert "'name'" in e.suggestion or "name" in e.suggestion, e.suggestion
        assert e.suggestion, "must suggest a fix"
    print("PASS  missing placeholder key errors with available keys")

    # Typo'd placeholder fails loudly instead of rendering literally.
    bad = _template()
    bad["root"]["children"][0]["text"] = "Hello, {{nmae}}!"
    try:
        substitute_placeholders(bad, {"name": "Ada", "role": "x", "accent": "#fff"})
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "nmae" in e.reason, e.reason
    print("PASS  typo'd placeholder fails loudly")

    # Empty rows rejected.
    try:
        batch_rows(_template(), [])
        raise AssertionError("should have raised")
    except EtchError as e:
        assert "non-empty" in e.reason
    print("PASS  empty rows rejected")


def test_cli() -> None:
    tmp = tempfile.mkdtemp(prefix="etch-batch-")
    scene_path = os.path.join(tmp, "template.json")
    csv_path = os.path.join(tmp, "rows.csv")
    out_dir = os.path.join(tmp, "out")
    with open(scene_path, "w", encoding="utf-8") as f:
        json.dump(_template(), f)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "role", "accent"])
        w.writeheader()
        w.writerow({"name": "Ada", "role": "Engineer", "accent": "$colors.lime"})
        w.writerow({"name": "Grace", "role": "Admiral", "accent": "$colors.azure"})
    proc = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "cli.py"), "batch",
         "--scene", scene_path, "--csv", csv_path,
         "--brand", "protograph", "--out-dir", out_dir],
        capture_output=True, text=True, cwd=ENGINE)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["count"] == 2, data
    assert data["renders"][0]["content_hash"] != data["renders"][1]["content_hash"]
    assert os.path.isfile(os.path.join(out_dir, "row_0.png"))
    assert os.path.isfile(os.path.join(out_dir, "row_1.png"))
    print("PASS  CLI batch: CSV -> 2 renders + PNGs")


def test_mcp() -> None:
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_batch", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        names = sorted(t["name"] for t in _request(proc, "tools/list", {})["tools"])
        assert "sketch_batch" in names, names

        rows = [{"name": n, "role": "Tester", "accent": "$colors.lime"}
                for n in ("Ada", "Grace", "Hopper")]
        r = _call(proc, "sketch_batch",
                  {"template_scene": _template(), "rows": rows})
        assert "error" not in r, r
        assert r["count"] == 3
        hashes = [x["content_hash"] for x in r["renders"]]
        assert len(set(hashes)) == 3, "rows must differ"
        assert [x["row_index"] for x in r["renders"]] == [0, 1, 2]
        assert all(x["render_id"].startswith("r_") for x in r["renders"])
        print("PASS  sketch_batch: 3 rows -> 3 distinct render_ids + hashes")

        # Batch is deterministic: same call, same hashes.
        r2 = _call(proc, "sketch_batch",
                   {"template_scene": _template(), "rows": rows})
        assert [x["content_hash"] for x in r2["renders"]] == hashes
        print("PASS  sketch_batch is deterministic")

        bad = _call(proc, "sketch_batch",
                    {"template_scene": _template(),
                     "rows": [{"name": "Ada"}]})
        assert "error" in bad and "row #0" in bad["error"]["reason"], bad
        print("PASS  bad row errors naming row index + placeholder")
        print("\nAll batch tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_module()
    test_cli()
    test_mcp()
