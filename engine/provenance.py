#!/usr/bin/env python3
"""
Etch engine — provenance.py

Signed-render manifests: who made this render, from what, with what.

Every compose/edit produces a manifest:
  {render_id, content_hash, brand_id, parents, engine_version, signed[, signature]}

- parents: edit lineage (render_ids this render was derived from), oldest-first.
  compose() → []; edit() → [previous_render_id]. This is the version history
  diffusion can never offer, made auditable.
- If ETCH_SIGNING_KEY is set, the manifest carries an HMAC-SHA256 signature
  over the canonical manifest body. Anyone with the key can verify a render
  came from this engine untampered — the trust story for registries and
  client handoffs.
- If the key is unset, the manifest is returned unsigned (signed: False)
  rather than failing — local/dev workflows shouldn't need key management.

WHY no timestamps anywhere in the manifest: the manifest must be a pure
function of its inputs, so re-signing the same render yields the identical
signature. A timestamp would make every signature unique and break the
determinism rule that content_hash depends on. (Audit trails that need
wall-clock belong in the meter log, not the manifest.)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

# WHY a literal instead of importing engine.__version__: provenance is
# imported by mcp_server before the package init runs in some launch paths.
# Keep this in step with pyproject.toml and engine/__init__.py on every release.
ENGINE_VERSION = "0.3.0"


def render_id_for(content_hash: str, brand_id: str | None) -> str:
    """Content-addressed render ID. WHY include brand_id: the same scene
    under two brands is two different renders (different pixels)."""
    seed = f"{content_hash}|{brand_id or ''}"
    return "r_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def canonical_manifest(manifest: dict) -> str:
    """Deterministic JSON for signing: sorted keys, compact separators."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def build_manifest(render_id: str, content_hash: str,
                   brand_id: str | None = None,
                   parents: list[str] | None = None) -> dict:
    """Build the unsigned manifest. Pure function of its inputs."""
    return {
        "render_id": render_id,
        "content_hash": content_hash,
        "brand_id": brand_id,
        "parents": list(parents or []),
        "engine_version": ENGINE_VERSION,
        "signed": False,
    }


def sign_manifest(manifest: dict, key: str | None = None) -> dict:
    """Add HMAC-SHA256 signature if a key is available.

    key defaults to the ETCH_SIGNING_KEY env var. The signature covers the
    canonical manifest body EXCLUDING the signature field itself. Returns a
    new dict; the input is not mutated.
    """
    key = key if key is not None else os.environ.get("ETCH_SIGNING_KEY")
    out = dict(manifest)
    if not key:
        out["signed"] = False
        out.pop("signature", None)
        return out
    out["signed"] = True
    body = {k: v for k, v in out.items() if k != "signature"}
    out["signature"] = hmac.new(
        key.encode("utf-8"), canonical_manifest(body).encode("utf-8"),
        hashlib.sha256).hexdigest()
    return out


def verify_manifest(manifest: dict, key: str | None = None) -> bool:
    """Recompute the signature and compare. False if unsigned, key missing,
    key wrong, or any field tampered with."""
    key = key if key is not None else os.environ.get("ETCH_SIGNING_KEY")
    if not key or not manifest.get("signed") or "signature" not in manifest:
        return False
    expected = sign_manifest(
        {k: v for k, v in manifest.items() if k != "signature"}, key)
    return hmac.compare_digest(expected.get("signature", ""), manifest["signature"])


def manifest_for(render_id: str, content_hash: str,
                 brand_id: str | None = None,
                 parents: list[str] | None = None) -> dict:
    """Build + sign (if key configured) in one call. The MCP/CLI entry point."""
    return sign_manifest(build_manifest(render_id, content_hash, brand_id, parents))
