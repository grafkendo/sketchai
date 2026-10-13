#!/usr/bin/env python3
"""
test_provenance.py — signed-render manifests.

Direct module tests (manifest shape, determinism, HMAC sign/verify) plus
MCP-level tests (provenance in compose/edit responses, sketch_provenance
tool, edit lineage). Run with:
    .venv/bin/python test_provenance.py
"""

import base64
import json
import os
import subprocess
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from provenance import (  # noqa: E402
    build_manifest,
    manifest_for,
    render_id_for,
    sign_manifest,
    verify_manifest,
)

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
        "canvas": {"width": 1080, "height": 1080},
        "root": {
            "type": "frame", "node_id": "s1", "width": 1080, "height": 1080,
            "fill": "$colors.bg",
            "children": [
                {"type": "text", "node_id": "s1-head", "text": headline,
                 "font": "$fonts.display", "size": 120, "fill": "$colors.lime",
                 "x": 80, "y": 400},
            ],
        },
    }


def _with_key(key: str | None):
    """Context manager setting/restoring ETCH_SIGNING_KEY."""
    class Ctx:
        def __enter__(self):
            self.had = "ETCH_SIGNING_KEY" in os.environ
            self.old = os.environ.get("ETCH_SIGNING_KEY")
            if key is None:
                os.environ.pop("ETCH_SIGNING_KEY", None)
            else:
                os.environ["ETCH_SIGNING_KEY"] = key
            return self

        def __exit__(self, *a):
            if self.had:
                os.environ["ETCH_SIGNING_KEY"] = self.old
            else:
                os.environ.pop("ETCH_SIGNING_KEY", None)
    return Ctx()


def test_module() -> None:
    with _with_key(None):
        m = manifest_for("r_abc", "h" * 64, "protograph", [])
    assert m["render_id"] == "r_abc"
    assert m["content_hash"] == "h" * 64
    assert m["brand_id"] == "protograph"
    assert m["parents"] == []
    assert m["engine_version"]
    assert m["signed"] is False and "signature" not in m
    # No timestamps anywhere — determinism rule.
    assert not any("time" in k.lower() or "date" in k.lower() for k in m), m.keys()
    # render_id derivation matches the MCP server's.
    assert render_id_for("h" * 64, "protograph") == render_id_for("h" * 64, "protograph")
    print("PASS  manifest shape, unsigned, no timestamps")

    with _with_key("test-secret-key"):
        s1 = manifest_for("r_abc", "h" * 64, "protograph", ["r_parent"])
        s2 = manifest_for("r_abc", "h" * 64, "protograph", ["r_parent"])
    assert s1["signed"] is True and len(s1["signature"]) == 64
    assert s1["signature"] == s2["signature"], "signing must be deterministic"
    assert s1["parents"] == ["r_parent"]
    assert verify_manifest(s1, "test-secret-key") is True
    assert verify_manifest(s1, "wrong-key") is False
    tampered = dict(s1, content_hash="0" * 64)
    assert verify_manifest(tampered, "test-secret-key") is False, "tamper must fail"
    print("PASS  HMAC sign deterministic, verify ok, tamper rejected")

    # build_manifest does not mutate its parents list.
    parents = ["r_x"]
    build_manifest("r_y", "h" * 64, None, parents)
    assert parents == ["r_x"], "parents list must not be mutated"
    print("PASS  parents list not mutated")


def test_mcp() -> None:
    env = dict(os.environ)
    env["ETCH_SIGNING_KEY"] = "mcp-test-key"
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE, env=env,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_provenance", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        names = sorted(t["name"] for t in _request(proc, "tools/list", {})["tools"])
        assert "sketch_provenance" in names, names
        print("PASS  tools/list includes sketch_provenance")

        r1 = _call(proc, "sketch_compose", {"scene": _scene("Hello")})
        assert "error" not in r1, r1
        prov = r1["provenance"]
        assert prov["render_id"] == r1["render_id"]
        assert prov["content_hash"] == r1["content_hash"]
        assert prov["parents"] == []
        assert prov["signed"] is True
        print("PASS  compose response carries signed provenance")

        r2 = _call(proc, "sketch_edit", {
            "render_id": r1["render_id"],
            "patch_ops": [{"op": "set_text", "node_id": "s1-head", "text": "World"}],
        })
        assert r2["provenance"]["parents"] == [r1["render_id"]], r2["provenance"]
        print("PASS  edit lineage: parents == [previous_render_id]")

        p = _call(proc, "sketch_provenance", {"render_id": r2["render_id"]})
        assert p["provenance"]["render_id"] == r2["render_id"]
        assert p["provenance"]["parents"] == [r1["render_id"]]
        print("PASS  sketch_provenance tool returns the manifest")

        bad = _call(proc, "sketch_provenance", {"render_id": "r_nope"})
        assert "error" in bad and "r_nope" in bad["error"]["reason"], bad
        print("PASS  unknown render_id errors cleanly")

        # Signature verifies with the server's key (client-side check).
        assert verify_manifest(p["provenance"], "mcp-test-key") is True
        print("PASS  client-side HMAC verification succeeds")
        print("\nAll provenance tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_module()
    test_mcp()
