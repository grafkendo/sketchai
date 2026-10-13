#!/usr/bin/env python3
"""
test_imagegen.py — diffusion bridge (interface only).

The fake "provider" is a tiny python script writing a solid PNG: it proves
the command-provider plumbing end-to-end without any external service.
Module tests + render.compose integration + MCP-level test. Run with:
    .venv/bin/python test_imagegen.py
"""

import json
import os
import subprocess
import sys
import tempfile

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

FAKE_GEN = """\
import sys
from PIL import Image
prompt = sys.argv[sys.argv.index("--prompt") + 1]
out = sys.argv[sys.argv.index("--out") + 1]
# Deterministic "generation": color derived from the prompt.
h = sum(prompt.encode()) % 256
Image.new("RGB", (64, 64), (h, 30, 90)).save(out, "PNG")
"""

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


def _gen_scene(prompt: str = "neon city bus") -> dict:
    return {
        "canvas": {"width": 400, "height": 400},
        "root": {
            "type": "frame", "node_id": "s1", "width": 400, "height": 400,
            "fill": "$colors.bg",
            "children": [
                {"type": "image", "node_id": "s1-img", "gen_prompt": prompt,
                 "width": 300, "height": 200, "x": 50, "y": 100},
            ],
        },
    }


def _with_env(**kw):
    """Context manager swapping env vars (restores after)."""
    class _Ctx:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in kw}
            for k, v in kw.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            return self

        def __exit__(self, *a):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _Ctx()


def test_module(tmp: str, fake_gen: str) -> None:
    from imagegen import resolve_gen_prompt, ImageGenError

    # 1. provider=none (default): error names the missing provider + node.
    with _with_env(ETCH_IMAGE_PROVIDER=None):
        try:
            resolve_gen_prompt("n1", "a bus")
            raise AssertionError("should have raised")
        except ImageGenError as e:
            msg = str(e).replace("\n", " ")
            assert "n1" in msg and "ETCH_IMAGE_PROVIDER" in msg, msg
    print("PASS  provider=none errors naming node + missing provider")

    # 2. command provider: runs the template, returns the asset path.
    cmd = f"{sys.executable} {fake_gen} --prompt {{prompt}} --out {{out}}"
    with _with_env(ETCH_IMAGE_PROVIDER="command", ETCH_IMAGE_COMMAND=cmd):
        path = resolve_gen_prompt("n1", "a red bus")
        assert os.path.isfile(path), path
        assert path.startswith(os.path.join(ENGINE, "assets", "generated"))
        from PIL import Image
        with Image.open(path) as im:
            assert im.size == (64, 64)
    print(f"PASS  command provider generated {os.path.basename(path)}")

    # 3. cache: delete the generator, same command -> same path, no re-run.
    os.remove(fake_gen)
    with _with_env(ETCH_IMAGE_PROVIDER="command", ETCH_IMAGE_COMMAND=cmd):
        path2 = resolve_gen_prompt("n1", "a red bus")
        assert path2 == path, (path, path2)
    print("PASS  cache hit: same prompt+command reuses the asset")

    # 4. error paths: missing placeholders, failing command, bad output.
    with open(fake_gen, "w") as f:
        f.write(FAKE_GEN)
    with _with_env(ETCH_IMAGE_PROVIDER="command",
                   ETCH_IMAGE_COMMAND=f"{sys.executable} {fake_gen} --out {{out}}"):
        try:
            resolve_gen_prompt("n2", "x")
            raise AssertionError("should have raised")
        except ImageGenError as e:
            assert "{prompt}" in str(e).replace("\n", " "), str(e)[:150]
    print("PASS  command missing {prompt} errors with a fix")

    with _with_env(ETCH_IMAGE_PROVIDER="command",
                   ETCH_IMAGE_COMMAND="false --prompt {prompt} --out {out}"):
        try:
            resolve_gen_prompt("n3", "x")
            raise AssertionError("should have raised")
        except ImageGenError as e:
            assert "exit 1" in str(e).replace("\n", " "), str(e)[:150]
    print("PASS  failing command errors with exit code + stderr")

    with _with_env(ETCH_IMAGE_PROVIDER="bogus"):
        try:
            resolve_gen_prompt("n4", "x")
            raise AssertionError("should have raised")
        except ImageGenError as e:
            assert "bogus" in str(e).replace("\n", " "), str(e)[:150]
    print("PASS  unknown provider errors naming it")


def test_compose(tmp: str, fake_gen: str) -> None:
    from render import compose
    from components import image, ComponentError

    cmd = f"{sys.executable} {fake_gen} --prompt {{prompt}} --out {{out}}"
    with _with_env(ETCH_IMAGE_PROVIDER="command", ETCH_IMAGE_COMMAND=cmd):
        scene = _gen_scene()
        r1 = compose(scene)
        node = r1["scene"]["root"]["children"][0]
        assert node["src"] and os.path.isfile(node["src"]), node
        # Caller scene keeps gen_prompt, gains no src.
        assert scene["root"]["children"][0].get("src") is None
        r2 = compose(_gen_scene())
        assert r2["content_hash"] == r1["content_hash"], "hash must be stable"
    print("PASS  compose resolves gen_prompt -> src, hash deterministic")

    # provider=none -> compose error names node + provider.
    with _with_env(ETCH_IMAGE_PROVIDER=None):
        try:
            compose(_gen_scene())
            raise AssertionError("should have raised")
        except Exception as e:
            msg = str(e).replace("\n", " ")
            assert "s1-img" in msg and "ETCH_IMAGE_PROVIDER" in msg, msg
    print("PASS  compose with provider=none errors naming node + provider")

    # Builder: gen_prompt alternative; neither -> ComponentError.
    n = image("img1", None, 100, 50, gen_prompt="a red bus")
    assert n["gen_prompt"] == "a red bus"
    try:
        image("img2", None, 100, 50)
        raise AssertionError("should have raised")
    except ComponentError as e:
        assert "gen_prompt" in str(e).replace("\n", " "), str(e)[:120]
    # src still works as before (positional).
    n2 = image("img3", "pic.png", 100, 50)
    assert n2["src"] == "pic.png"
    print("PASS  components.image: gen_prompt alternative, src unchanged")


def test_mcp(tmp: str, fake_gen: str) -> None:
    cmd = f"{sys.executable} {fake_gen} --prompt {{prompt}} --out {{out}}"
    env = dict(os.environ, ETCH_IMAGE_PROVIDER="command",
               ETCH_IMAGE_COMMAND=cmd,
               ETCH_METER_LOG=os.path.join(tmp, "meter.jsonl"))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=ENGINE, env=env,
    )
    try:
        _request(proc, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test_imagegen", "version": "0.1"}})
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()

        r = _call(proc, "sketch_compose", {"scene": _gen_scene("desert road")})
        assert "error" not in r, r
        assert r["render_id"].startswith("r_")
        print(f"PASS  sketch_compose with gen_prompt -> {r['render_id']}")
        print("\nAll imagegen tests passed.")
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="etch-imagegen-")
    fake_gen = os.path.join(tmp, "fake_gen.py")
    with open(fake_gen, "w") as f:
        f.write(FAKE_GEN)
    test_module(tmp, fake_gen)
    test_compose(tmp, fake_gen)
    test_mcp(tmp, fake_gen)
