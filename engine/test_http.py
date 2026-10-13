#!/usr/bin/env python3
"""
test_http.py — hosted HTTP mode: transport selection, API-key auth, metering.

Spawns mcp_server.py with ETCH_TRANSPORT=http and exercises it over real
HTTP: 401s without the key, the SDK client with the key, and the meter log.
Run with:
    .venv/bin/python test_http.py
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

KEY = "test-key-123"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 25.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"server did not open port {port} in {timeout}s")


def _spawn(extra_env: dict) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(extra_env)
    return subprocess.Popen(
        [sys.executable, os.path.join(ENGINE, "mcp_server.py")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, cwd=ENGINE, env=env,
    )


def _raw_post(url: str, body: dict, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _scene() -> dict:
    return {
        "canvas": {"width": 400, "height": 400},
        "root": {
            "type": "frame", "node_id": "s1", "width": 400, "height": 400,
            "fill": "$colors.bg",
            "children": [
                {"type": "text", "node_id": "s1-head", "text": "HTTP mode",
                 "font": "$fonts.display", "size": 60, "fill": "$colors.lime",
                 "x": 40, "y": 150},
            ],
        },
    }



def _no_proxy_client_factory(headers=None, timeout=None, auth=None):
    """httpx client factory with trust_env=False.

    WHY: this sandbox sets exotic proxy env vars (IPv6 entries in no_proxy)
    that httpx's trust_env parsing chokes on (InvalidURL on client build).
    The test target is 127.0.0.1 — no proxy should ever be involved.
    """
    import httpx
    from mcp.shared._httpx_utils import (MCP_DEFAULT_TIMEOUT,
                                         MCP_DEFAULT_SSE_READ_TIMEOUT)
    if timeout is None:
        timeout = httpx.Timeout(MCP_DEFAULT_TIMEOUT,
                                read=MCP_DEFAULT_SSE_READ_TIMEOUT)
    kw = {"timeout": timeout, "trust_env": False}
    if headers is not None:
        kw["headers"] = headers
    if auth is not None:
        kw["auth"] = auth
    return httpx.AsyncClient(**kw)

async def _sdk_session(port: int, key: str | None):
    """Run initialize -> list_tools -> call sketch_compose via the SDK client."""
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession
    factory = _no_proxy_client_factory
    headers = {"x-api-key": key} if key else None
    url = f"http://127.0.0.1:{port}/mcp"
    async with streamablehttp_client(url, headers=headers,
                                     httpx_client_factory=factory) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            result = await session.call_tool("sketch_compose", {"scene": _scene()})
            text = result.content[0].text
            return names, json.loads(text)


def test_auth_and_tools() -> None:
    tmp = tempfile.mkdtemp(prefix="etch-http-")
    meter = os.path.join(tmp, "meter.jsonl")
    port = _free_port()
    proc = _spawn({"ETCH_TRANSPORT": "http", "ETCH_PORT": str(port),
                   "ETCH_API_KEY": KEY, "ETCH_METER_LOG": meter})
    try:
        _wait_port(port)
        url = f"http://127.0.0.1:{port}/mcp"

        # 1. No key -> 401 on POST and GET.
        init_body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05",
                                "capabilities": {},
                                "clientInfo": {"name": "t", "version": "0.1"}}}
        code, body = _raw_post(url, init_body)
        assert code == 401, f"expected 401, got {code}"
        assert b"X-API-Key" in body, body[:200]
        print("PASS  POST without key -> 401 naming X-API-Key")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp", timeout=10)
            raise AssertionError("GET without key should 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
        print("PASS  GET without key -> 401")

        # 2. Wrong key -> rejected.
        try:
            asyncio.run(_sdk_session(port, "wrong-key"))
            raise AssertionError("wrong key should fail")
        except BaseException as e:
            texts = [str(e)]
            if isinstance(e, BaseExceptionGroup):
                texts += [str(sub) for sub in e.exceptions]
            assert any("401" in t for t in texts), f"expected 401, got: {texts}"[:300]
        print("PASS  wrong API key -> rejected")

        # 3. Right key -> full session works.
        names, r1 = asyncio.run(_sdk_session(port, KEY))
        assert len(names) == 14, names
        assert "sketch_compose" in names and "sketch_animate" in names
        assert r1["render_id"].startswith("r_"), r1
        assert r1["provenance"]["render_id"] == r1["render_id"]
        print(f"PASS  SDK client with key: 14 tools, compose -> {r1['render_id']}")

        # 4. Meter log: compose line with 1 credit + render_id.
        lines = [json.loads(l) for l in open(meter, encoding="utf-8")]
        comp = [l for l in lines if l["tool"] == "sketch_compose"]
        assert comp, f"no compose line in meter log: {lines}"
        assert comp[0]["credits"] == 1, comp[0]
        assert comp[0]["render_id"] == r1["render_id"], comp[0]
        assert comp[0]["content_hash"] == r1["content_hash"]
        assert comp[0]["ts"], "meter line needs a timestamp"
        print("PASS  meter log: sketch_compose -> 1 credit + render_id + ts")

        # 5. Zero-credit tool still logs a line (audit trail).
        async def _list():
            from mcp.client.streamable_http import streamablehttp_client
            from mcp import ClientSession
            factory = _no_proxy_client_factory
            async with streamablehttp_client(
                    url, headers={"x-api-key": KEY},
                    httpx_client_factory=factory) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool("components_list", {})
        asyncio.run(_list())
        lines = [json.loads(l) for l in open(meter, encoding="utf-8")]
        cl = [l for l in lines if l["tool"] == "components_list"]
        assert cl and cl[0]["credits"] == 0, lines
        print("PASS  meter log: components_list -> 0 credits")
        print("\nAll HTTP auth/tool/meter tests passed.")
    finally:
        proc.kill()
        proc.wait()


def test_open_mode() -> None:
    # No ETCH_API_KEY -> open server (dev default).
    tmp = tempfile.mkdtemp(prefix="etch-http-open-")
    port = _free_port()
    proc = _spawn({"ETCH_TRANSPORT": "http", "ETCH_PORT": str(port),
                   "ETCH_METER_LOG": os.path.join(tmp, "m.jsonl")})
    try:
        _wait_port(port)
        code, _ = _raw_post(f"http://127.0.0.1:{port}/mcp",
                            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05",
                                        "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "0.1"}}})
        # 200 (JSON) or 406/400 from the MCP layer are all "not 401".
        assert code != 401, f"open mode must not 401, got {code}"
        print(f"PASS  no ETCH_API_KEY -> open mode (initialize -> {code})")
    finally:
        proc.kill()
        proc.wait()


def test_bad_transport() -> None:
    proc = _spawn({"ETCH_TRANSPORT": "carrier-pigeon"})
    try:
        rc = proc.wait(timeout=15)
        assert rc != 0, "bad transport must fail fast"
        print("PASS  unknown ETCH_TRANSPORT fails fast")
    finally:
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    test_auth_and_tools()
    test_open_mode()
    test_bad_transport()
    print("\nAll HTTP-mode tests passed.")
