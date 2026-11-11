#!/usr/bin/env python3
"""
Etch engine — api.py

FastAPI render service (Phase 1 MVP). Run with:
    python api.py                      # serves on :8000
    uvicorn api:app --port 8000

Endpoints:
  POST /v1/renders          compose a scene -> render (idempotent)
  PATCH /v1/renders/{id}    surgical edit -> new render version
  GET  /v1/renders/{id}     render metadata (+svg)
  GET  /v1/components       token-cheap component catalog
  POST /v1/brands/validate  brand-rule check without rendering

WHY render_id is derived from the content hash: identical scene + brand
always yields the same ID, so re-POSTing a scene is a cache hit, not a new
render. Agents can treat renders as immutable, content-addressed values —
the same mental model as git blobs.

WHY strict validation errors name the node: spec §4 — a bad call returns
WHICH node failed, WHY, and a suggested fix. HTTP 422 with a structured
body, never a silent fallback render.

Auth (Phase 1, per spec: "no auth beyond API keys"): if ETCH_API_KEY is set
in the environment, clients must send it as X-API-Key. Unset = open (dev).
Metering is logged to stdout per render (billing comes in Phase 3).
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from brands import load_brand, validate
from components import COMPONENT_CATALOG, EtchError
from render import canonical, compose, edit

API_KEY = os.environ.get("ETCH_API_KEY", "")

app = FastAPI(title="Etch — vector sketch service (MVP)", version="0.3.0")

# In-memory render store: render_id -> record. (Phase 3 replaces this with
# a real DB; for the MVP the process lifetime is the store lifetime.)
STORE: dict[str, dict] = {}


# ------------------------------------------------------- models

class ComposeBody(BaseModel):
    scene: dict
    brand_id: str | None = "protograph"
    strict: bool = True  # strict=True: brand violations -> 422


class EditBody(BaseModel):
    ops: list[dict]


class ValidateBody(BaseModel):
    scene: dict
    brand_id: str = "protograph"


# ------------------------------------------------------- helpers

def _check_auth(x_api_key: str | None) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def _err(e: EtchError) -> JSONResponse:
    # The whole point: WHICH node, WHY, and how to fix it.
    return JSONResponse(status_code=422, content={"error": e.to_dict()})


def _render_id(content_hash: str, brand_id: str | None) -> str:
    # WHY include brand_id: the same scene under two brands is two renders.
    seed = f"{content_hash}|{brand_id or ''}"
    return "r_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _do_compose(scene: dict, brand_id: str | None, strict: bool) -> dict:
    """Shared by POST /v1/renders. Raises EtchError on any problem."""
    t0 = time.perf_counter()
    result = compose(scene, brand_id=brand_id, validate_brand=True)
    bv = result.get("brand_validation")
    # Strict blocks only on severity=="error" (see mcp_server._do_compose):
    # "warn" rules guide but never stop a draft.
    errs = [v for v in (bv.get("violations", []) if bv else [])
            if v.get("severity", "error") == "error"]
    if errs and strict:
        # Strict mode: brand violations block the render. Raise a single
        # EtchError carrying the full violation list as the reason so the
        # agent sees every problem in one round trip (not fail-fast).
        lines = [f"[{v['node_id']}] {v['rule']}: {v['message']}" for v in errs]
        raise EtchError(
            None,
            "brand validation failed: " + "; ".join(lines),
            "Fix the violations, or re-POST with strict=false for warn mode.",
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
        "scene": result["scene"],  # resolved scene (tokens substituted)
    }
    STORE[rid] = record
    dt = (time.perf_counter() - t0) * 1000
    # Metering hook (Phase 1: log only — billing lands in Phase 3).
    print(f"[meter] render_id={rid} hash={result['content_hash'][:12]} "
          f"{result['width']}x{result['height']} {dt:.1f}ms", flush=True)
    return record


def _public(record: dict, include_svg: bool = True) -> dict:
    d = {k: record[k] for k in ("render_id", "content_hash", "brand_id",
                                "width", "height", "bboxes", "brand_validation")}
    if include_svg:
        d["svg"] = record["svg"]
    return d


# ------------------------------------------------------- routes

@app.post("/v1/renders")
def post_renders(body: ComposeBody, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    try:
        record = _do_compose(body.scene, body.brand_id, body.strict)
    except EtchError as e:
        return _err(e)
    return _public(record)


@app.patch("/v1/renders/{render_id}")
def patch_render(render_id: str, body: EditBody, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    record = STORE.get(render_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown render_id '{render_id}'")
    try:
        # WHY edit the RESOLVED scene: tokens are already substituted, so
        # set_fill with a literal hex behaves exactly as the agent sees it.
        # (The authored scene with $tokens is the client's to keep.)
        new_scene, diff = edit(record["scene"], body.ops)
    except EtchError as e:
        return _err(e)
    try:
        new_record = _do_compose(new_scene, record["brand_id"], strict=True)
    except EtchError as e:
        return _err(e)
    return {**_public(new_record), "diff": diff,
            "previous_render_id": render_id}


@app.get("/v1/renders/{render_id}")
def get_render(render_id: str, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    record = STORE.get(render_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown render_id '{render_id}'")
    return _public(record)


@app.get("/v1/components")
def get_components():
    # Token-cheap by design: names + compact param specs, not full schemas.
    return {"components": COMPONENT_CATALOG}


@app.post("/v1/brands/validate")
def post_validate(body: ValidateBody):
    try:
        brand = load_brand(body.brand_id)
    except EtchError as e:
        return _err(e)
    try:
        # Validate the resolved scene (tokens substituted) — same input the
        # renderer would check.
        result = compose(body.scene, brand_id=body.brand_id, validate_brand=True)
        report = result["brand_validation"]
    except EtchError as e:
        return _err(e)
    return {"brand_id": body.brand_id, **report}


@app.get("/health")
def health():
    return {"ok": True, "renders_stored": len(STORE)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
