#!/usr/bin/env python3
"""
Etch engine — packs.py

Component packs: shareable libraries of named scene fragments.

A pack is a JSON file in engine/packs/<name>.json:
  {"name": ..., "description": ..., "brand": "protograph",
   "fragments": {
     "hook": {"description": ..., "params": ["headline", "subline"],
              "scene": {<scene graph with {{headline}} placeholders>}},
     ...
   }}

WHY packs instead of more components: components are the vocabulary;
fragments are phrases. An agent composing a carousel shouldn't re-derive
"headline over two curves with a kicker" from boxes every time — it picks
the hook fragment, fills two params, and gets a compositionally sound
slide. Packs are also the unit of the future marketplace (spec §8):
versioned, shareable, revenue-shareable.

Fragments substitute {{params}} with the same engine as batch rows
(batch.substitute_placeholders) — one substitution implementation, and its
leftover-placeholder check catches param typos loudly.
"""

from __future__ import annotations

import json
import os
import re

from batch import substitute_placeholders
from components import EtchError

PACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs")

# Pack files live in a fixed directory and are addressed by name only.
# WHY a strict name pattern: pack names arrive from tool callers, and
# os.path.join(PACKS_DIR, f"{pack_name}.json") would otherwise follow "../"
# out of the packs directory.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class PackError(EtchError):
    pass


def _available_packs() -> list[str]:
    if not os.path.isdir(PACKS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(PACKS_DIR) if f.endswith(".json"))


def load_pack(pack_name: str) -> dict:
    if not isinstance(pack_name, str) or not _SAFE_NAME.match(pack_name):
        raise PackError(
            None, f"invalid pack name '{pack_name}'",
            "Pack names must contain only letters, digits, '_' or '-'.",
        )
    path = os.path.join(PACKS_DIR, f"{pack_name}.json")
    if not os.path.isfile(path):
        raise PackError(
            None, f"unknown pack '{pack_name}'",
            f"Available packs: {_available_packs() or '(none)'} — "
            f"see packs_list.",
        )
    with open(path, encoding="utf-8") as f:
        pack = json.load(f)
    if not isinstance(pack.get("fragments"), dict) or not pack["fragments"]:
        raise PackError(None, f"pack '{pack_name}' has no fragments",
                        "A pack needs a non-empty 'fragments' dict.")
    return pack


def list_packs() -> list[dict]:
    """Catalog for agents: pack names, descriptions, and each fragment's
    params — everything needed to call sketch_from_pack without guessing."""
    out = []
    for name in _available_packs():
        pack = load_pack(name)
        out.append({
            "name": name,
            "description": pack.get("description", ""),
            "brand": pack.get("brand"),
            "fragments": [
                {"name": fname,
                 "description": f.get("description", ""),
                 "params": list(f.get("params", []))}
                for fname, f in pack["fragments"].items()
            ],
        })
    return out


def get_fragment_scene(pack_name: str, fragment_name: str,
                       params: dict | None) -> tuple[dict, dict]:
    """Return (substituted scene, pack) for a fragment. Raises PackError
    naming what's available when the pack, fragment, or a param is wrong."""
    pack = load_pack(pack_name)
    fragments = pack["fragments"]
    if fragment_name not in fragments:
        raise PackError(
            None, f"unknown fragment '{fragment_name}' in pack '{pack_name}'",
            f"Available fragments: {sorted(fragments)}.",
        )
    fragment = fragments[fragment_name]
    params = params or {}
    declared = fragment.get("params", [])
    missing = [p for p in declared if p not in params]
    if missing:
        raise PackError(
            None,
            f"fragment '{fragment_name}' is missing param(s): {', '.join(missing)}",
            f"Pass params with keys: {declared}.",
        )
    scene = substitute_placeholders(fragment["scene"], params,
                                    context=f"fragment '{fragment_name}'")
    return scene, pack
