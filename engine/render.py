#!/usr/bin/env python3
"""
Etch engine — render.py

compose() / edit() / exporters. This is the deterministic core.

WHY content_hash = sha256(canonical JSON of the RESOLVED scene):
  - Canonicalization (sorted keys, no whitespace) first: Python dicts
    preserve insertion order, so two semantically identical scenes built in
    different key order MUST hash the same. Hashing raw repr() would make
    the hash depend on how the dict was constructed — an accident, not a
    property of the scene.
  - Resolved (tokens substituted) rather than authored: "$colors.lime" and
    "#B6FF3B" describe the same pixels and must share a hash. Hashing the
    resolved graph makes the hash a true content fingerprint.
  - Layout is a pure function of the resolved graph, so hashing pre-layout
    is sufficient — identical resolved scenes always lay out identically.

WHY edit() deep-copies: renders are immutable versions. PATCH never mutates
a stored scene; it produces a NEW scene with a NEW hash. That gives the
version history diffusion can never offer: every version addressable,
every version re-renderable byte-identically.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys


def _ensure_cairo_dll() -> None:
    """Windows-only: make libcairo-2.dll loadable before cairosvg is imported.

    WHY this exists: cairosvg needs Cairo's native DLL, which pip cannot ship
    on Windows. The GTK3 runtime installer provides it, but (a) it doesn't
    always land on PATH, and (b) Python 3.8+ ignores PATH for DLL loading
    anyway — os.add_dll_directory() is the supported mechanism. Doing it here,
    in code, means the fix travels with the repo: it works whether the server
    is launched from a terminal, Claude Code, or Cursor, with zero user
    configuration. Respects CAIROCFFI_DLL_DIRECTORIES if the user set it.
    """
    if sys.platform != "win32" or not hasattr(os, "add_dll_directory"):
        return
    candidates: list[str] = []
    env = os.environ.get("CAIROCFFI_DLL_DIRECTORIES")
    if env:
        candidates.extend(env.split(os.pathsep))
    candidates.append(r"C:\Program Files\GTK3-Runtime Win64\bin")
    for directory in candidates:
        if directory and os.path.isdir(directory):
            try:
                os.add_dll_directory(directory)
            except OSError:
                pass


_ensure_cairo_dll()

try:
    import cairosvg
except OSError as exc:
    if sys.platform == "win32":
        raise OSError(
            "Etch needs the Cairo graphics library (libcairo-2.dll), which pip "
            "cannot ship on Windows. Install the GTK3 runtime from "
            "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases "
            "(tick 'Set up PATH' during install), restart your terminal, and re-run. "
            f"Original error: {exc}"
        ) from exc
    raise

from brands import load_brand, resolve_tokens, validate
from components import CONTAINERS, EtchError, KNOWN_TYPES
from layout import Resolver, SVGWriter


class RenderError(EtchError):
    pass


class EditError(EtchError):
    pass


# ------------------------------------------------------- canonicalization

def canonical(scene: dict) -> str:
    """Deterministic JSON: sorted keys, compact separators, no whitespace
    variants. The single source of truth for hashing AND equality checks."""
    return json.dumps(scene, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(resolved_scene: dict) -> str:
    return hashlib.sha256(canonical(resolved_scene).encode("utf-8")).hexdigest()


# ------------------------------------------------------- structural validation

def _iter_nodes(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _iter_nodes(child)


def _check_structure(scene: dict) -> None:
    """Fail fast on malformed scenes — with the node named and a fix
    suggested. WHY before layout: a missing width on a rect would otherwise
    die deep in the resolver with a confusing KeyError."""
    if not isinstance(scene, dict) or "root" not in scene:
        raise RenderError(None, "scene must be a dict with 'root' (and usually 'canvas')",
                          "Minimal scene: {'canvas': {'width': 1080, 'height': 1080}, 'root': {...}}")
    seen: dict[str, str] = {}
    for node in _iter_nodes(scene["root"]):
        nid = node.get("node_id")
        t = node.get("type")
        if t not in KNOWN_TYPES:
            raise RenderError(nid, f"unknown component type '{t}'",
                              f"Known types: {sorted(KNOWN_TYPES)}")
        if nid is not None:
            if nid in seen:
                raise RenderError(nid, f"duplicate node_id (also used by a '{seen[nid]}' node)",
                                  "node_ids must be unique — sketch.edit targets nodes by ID.")
            seen[nid] = t
        # Leaf dimension requirements (containers auto-size).
        if t == "rect" and (node.get("width") is None or node.get("height") is None):
            raise RenderError(nid, "rect needs width and height",
                              "Add width/height, or use a badge (auto-sized) instead.")
        if t == "circle" and node.get("r") is None:
            raise RenderError(nid, "circle needs r (radius)", "Add r, e.g. r=90.")
        if t == "image" and (node.get("width") is None or node.get("height") is None or not node.get("src")):
            raise RenderError(nid, "image needs src, width and height",
                              "src can be a local file path or an https:// URL.")
        if t in ("chart_bar",) and (node.get("width") is None or node.get("height") is None):
            raise RenderError(nid, f"{t} needs width and height", "")
        if t == "chart_donut" and node.get("size") is None:
            raise RenderError(nid, "chart_donut needs size", "")
        if t == "curve" and (node.get("width") is None or node.get("height") is None):
            raise RenderError(nid, "curve needs width and height", "")
        if t == "divider" and node.get("width") is None:
            raise RenderError(nid, "divider needs width", "")


# ------------------------------------------------------- compose

def compose(scene: dict, brand_id: str | None = None,
            validate_brand: bool = True) -> dict:
    """Full pipeline: validate -> copy -> resolve tokens -> layout -> SVG.

    Returns {"svg", "content_hash", "bboxes", "scene" (resolved),
             "width", "height", "brand_validation"}.

    WHY the deep copy: resolve_tokens mutates in place, and the caller's
    authored scene must keep its "$token" references so it can re-render
    under a different brand later.
    """
    _check_structure(scene)
    working = copy.deepcopy(scene)

    brand = load_brand(brand_id) if brand_id else None
    if brand is not None:
        resolve_tokens(working["root"], brand)

    resolver = Resolver()
    resolved_root = resolver.resolve(working)
    working["root"] = resolved_root

    svg = SVGWriter().write(working, resolved_root)
    h = content_hash(working)

    brand_validation = None
    if brand is not None and validate_brand:
        brand_validation = validate(working, brand)

    canvas = working.get("canvas", {})
    return {
        "svg": svg,
        "content_hash": h,
        "bboxes": resolver.bboxes,
        "scene": working,
        "width": canvas.get("width", 1080),
        "height": canvas.get("height", 1080),
        "brand_validation": brand_validation,
    }


# ------------------------------------------------------- edit

def find_node(scene: dict, node_id: str) -> dict | None:
    for node in _iter_nodes(scene["root"]):
        if node.get("node_id") == node_id:
            return node
    return None


def _find_parent(scene: dict, node_id: str) -> dict | None:
    for node in _iter_nodes(scene["root"]):
        for child in node.get("children", []):
            if child.get("node_id") == node_id:
                return node
    return None


def _available_ids(scene: dict) -> list[str]:
    return sorted(str(n.get("node_id")) for n in _iter_nodes(scene["root"]))


def edit(scene: dict, ops: list[dict]) -> tuple[dict, dict]:
    """Apply patch ops to a deep copy of scene. Each op targets a node_id.

    Supported ops:
      {"op": "set_text",   "node_id": ..., "text": ...}
      {"op": "set_fill",   "node_id": ..., "fill": ...}
      {"op": "set_attr",   "node_id": ..., "attrs": {...}}
      {"op": "replace_node","node_id": ..., "node": {...}}
      {"op": "add_node",   "parent_id": ..., "node": {...}, "index": int?}
      {"op": "remove_node","node_id": ...}

    Returns (new_scene, diff_summary) where diff_summary =
    {"ops_applied": n, "changed": [node_ids...], "details": [...]}.
    "changed" lists exactly the nodes touched — the proof of surgical edits.
    """
    new_scene = copy.deepcopy(scene)
    changed: list[str] = []
    details: list[str] = []

    def need(nid: str) -> dict:
        node = find_node(new_scene, nid)
        if node is None:
            raise EditError(nid, f"no node with node_id '{nid}' in this scene",
                            f"Available node_ids: {_available_ids(new_scene)[:20]}")
        return node

    for i, op in enumerate(ops):
        kind = op.get("op")
        nid = op.get("node_id")
        if kind in ("set_text", "set_fill", "set_attr", "replace_node", "remove_node") and not nid:
            raise EditError(None, f"op #{i} ('{kind}') is missing node_id", "")
        if kind == "set_text":
            node = need(nid)
            if node.get("type") not in ("text", "badge"):
                raise EditError(nid, f"set_text targets a '{node.get('type')}' node, not text",
                                "set_text works on text and badge nodes; use set_attr for others.")
            node["text"] = op["text"]
            changed.append(nid); details.append(f"set_text {nid}")
        elif kind == "set_fill":
            node = need(nid)
            node["fill"] = op["fill"]
            changed.append(nid); details.append(f"set_fill {nid} -> {op['fill']}")
        elif kind == "set_attr":
            node = need(nid)
            attrs = op.get("attrs", {})
            if not isinstance(attrs, dict):
                raise EditError(nid, "set_attr needs an 'attrs' dict", "")
            node.update(attrs)
            changed.append(nid); details.append(f"set_attr {nid} {sorted(attrs)}")
        elif kind == "replace_node":
            node = need(nid)
            parent = _find_parent(new_scene, nid)
            new_node = op.get("node")
            if not isinstance(new_node, dict) or "type" not in new_node:
                raise EditError(nid, "replace_node needs a 'node' dict with a 'type'", "")
            new_node.setdefault("node_id", nid)
            if parent is None:
                new_scene["root"] = new_node
            else:
                idx = next(k for k, c in enumerate(parent["children"])
                           if c.get("node_id") == nid)
                parent["children"][idx] = new_node
            changed.append(nid); details.append(f"replace_node {nid}")
        elif kind == "add_node":
            parent = need(op.get("parent_id") or "")
            new_node = op.get("node")
            if not isinstance(new_node, dict) or "type" not in new_node:
                raise EditError(op.get("parent_id"), "add_node needs a 'node' dict with a 'type'", "")
            idx = op.get("index")
            if idx is None:
                parent.setdefault("children", []).append(new_node)
            else:
                parent.setdefault("children", []).insert(idx, new_node)
            changed.append(new_node.get("node_id")); details.append(f"add_node under {parent.get('node_id')}")
        elif kind == "remove_node":
            node = need(nid)
            parent = _find_parent(new_scene, nid)
            if parent is None:
                raise EditError(nid, "cannot remove the root node", "")
            parent["children"] = [c for c in parent["children"] if c.get("node_id") != nid]
            changed.append(nid); details.append(f"remove_node {nid}")
        else:
            raise EditError(nid, f"unknown op '{kind}'",
                            "Supported ops: set_text, set_fill, set_attr, replace_node, add_node, remove_node.")

    # De-duplicate while preserving order — deterministic diff output.
    seen_ordered = list(dict.fromkeys(str(c) for c in changed))
    return new_scene, {"ops_applied": len(ops), "changed": seen_ordered, "details": details}


# ------------------------------------------------------- exporters

def to_png(svg: str, path: str | None = None, scale: float = 1.0) -> bytes:
    """Rasterize SVG to PNG bytes (optionally writing to path).

    WHY cairosvg: it resolves fonts through fontconfig, so the PNG uses the
    same real fonts the layout engine measured with — WYSIWYG between layout
    math and final pixels. (Headless-Chrome screenshots were tried on the
    Protograph work and silently failed in this environment; WeasyPrint
    crashes on modern CSS. cairosvg is the reliable path.)
    """
    data = cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=scale)
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


def to_pdf(svg: str, path: str | None = None) -> bytes:
    data = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data
