#!/usr/bin/env python3
"""
Etch engine — brands.py

Brand tokens + enforcement.

A brand is a JSON file: exact color hexes, font pairings, spacing, radius,
and a list of rules. The critical design decision (spec §6): tokens resolve
AT RENDER TIME, not when the scene is authored. The scene graph holds
references ("$colors.lime"); the renderer substitutes values. WHY: swap the
brand_id and an entire deck re-skins deterministically — the same scene is
Protograph-dark today and client-light tomorrow, with byte-identical
structure. If tokens were baked in at authoring time, re-skinning would mean
rewriting every node.

Validation returns structured violations (node_id + rule broken + suggested
fix) instead of raising, because brand checking has two modes: strict (block
the render — the API's default) and warn (annotate and continue — useful
while an agent is iterating on a draft).
"""

from __future__ import annotations

import json
import os
import re

from components import EtchError

BRANDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brands")

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class BrandError(EtchError):
    pass


def load_brand(brand_id: str, brands_dir: str = BRANDS_DIR) -> dict:
    path = os.path.join(brands_dir, f"{brand_id}.json")
    if not os.path.isfile(path):
        available = sorted(
            f[:-5] for f in os.listdir(brands_dir) if f.endswith(".json")
        ) if os.path.isdir(brands_dir) else []
        raise BrandError(
            None, f"unknown brand_id '{brand_id}'",
            f"Available brands: {available or '(none)'} — or omit brand_id to render unbranded.",
        )
    with open(path, encoding="utf-8") as f:
        brand = json.load(f)
    brand.setdefault("id", brand_id)
    return brand


def _norm_hex(c: str) -> str:
    """Normalize #RGB -> #RRGGBB, lowercase. WHY: '#FFF' vs '#ffffff' vs
    '#FFFFFF' are the same color; palette checks must not fail on spelling."""
    c = c.strip()
    m = re.match(r"^#([0-9a-fA-F]{3})$", c)
    if m:
        c = "#" + "".join(ch * 2 for ch in m.group(1))
    return c.lower()


def resolve_tokens(node: dict, brand: dict) -> None:
    """In-place: replace every "$dotted.path" string with the brand value.

    WHY in-place on a deep copy (render.compose copies first): resolution is
    a render-time concern; the stored/authored scene keeps its references so
    the SAME scene can render under a different brand later.
    """
    def lookup(token: str, node_id: str | None) -> str:
        path = token[1:].split(".")
        cur: object = brand
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                keys = sorted(brand.get("colors", {})) + sorted(brand.get("fonts", {}))
                raise BrandError(
                    node_id, f"unknown brand token '{token}'",
                    f"Available tokens include: {', '.join('$' + k for k in keys[:12])}… "
                    f"(brand '{brand.get('id')}')",
                )
        if not isinstance(cur, (str, int, float)):
            raise BrandError(node_id, f"brand token '{token}' does not resolve to a scalar", "")
        return str(cur)

    def walk(n: dict) -> None:
        nid = n.get("node_id")
        for k, v in list(n.items()):
            if k in ("type", "node_id", "children", "_x", "_y", "_w", "_h", "_lines"):
                continue
            if isinstance(v, str) and v.startswith("$"):
                n[k] = lookup(v, nid)
            elif isinstance(v, dict):
                walk(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        walk(item)
        for child in n.get("children", []):
            walk(child)

    walk(node)


# ------------------------------------------------------- rule engine

def _iter_nodes(node: dict):
    yield node
    for child in node.get("children", []):
        yield from _iter_nodes(child)


def _color_params(node: dict) -> list[tuple[str, str]]:
    """(param_name, value) for every color-ish param on a node."""
    out = []
    for key in ("fill", "stroke", "bar_fill", "label_fill", "text_fill"):
        v = node.get(key)
        if isinstance(v, str) and v.startswith("#"):
            out.append((key, v))
    colors = node.get("colors")
    if isinstance(colors, list):
        for i, c in enumerate(colors):
            if isinstance(c, str) and c.startswith("#"):
                out.append((f"colors[{i}]", c))
    return out


def validate(scene: dict, brand: dict) -> dict:
    """Check the (token-resolved) scene against the brand's rules.

    Returns {"passed": bool, "violations": [{node_id, rule, message,
    suggestion}]}. WHY return-not-raise: the API needs warn mode, and a
    single report listing ALL violations is far more useful to an iterating
    agent than fail-fast on the first one.
    """
    violations: list[dict] = []
    rules = brand.get("rules", [])
    palette = {_norm_hex(c) for c in brand.get("colors", {}).values()}
    neutrals = {_norm_hex(c) for c in brand.get("neutrals", ["#FFFFFF"])}
    allowed_fonts = {f.strip().lower() for f in brand.get("fonts", {}).values()}

    def add(node_id, rule, message, suggestion=""):
        v = {"node_id": node_id, "rule": rule, "message": message}
        if suggestion:
            v["suggestion"] = suggestion
        violations.append(v)

    root = scene.get("root", {})
    for node in _iter_nodes(root):
        nid = node.get("node_id")
        for rule in rules:
            rtype = rule.get("type")
            if rtype == "palette":
                for param, color in _color_params(node):
                    if not _HEX.match(color):
                        add(nid, "palette",
                            f"{param}='{color}' is not a valid hex color",
                            "Use #RRGGBB, or a $colors.* brand token.")
                    elif _norm_hex(color) not in palette | neutrals:
                        add(nid, "palette",
                            f"{param}='{color}' is not in the '{brand.get('id')}' palette",
                            f"Use one of: {', '.join(sorted(palette))} (or add it to the brand).")
            elif rtype == "fonts":
                fam = node.get("font")
                if isinstance(fam, str) and fam.strip().lower() not in allowed_fonts:
                    add(nid, "fonts",
                        f"font='{fam}' is not a brand font",
                        f"Use one of: {', '.join(sorted(allowed_fonts))} (or $fonts.display / $fonts.body tokens).")
            elif rtype == "no_pure_black":
                for param, color in _color_params(node):
                    if _norm_hex(color) == "#000000":
                        add(nid, "no_pure_black",
                            f"{param} uses pure black #000000",
                            "Use the brand's near-black instead (e.g. $colors.bg).")
    # Deterministic violation order: sort by (node_id, rule, message) so two
    # runs over the same scene report identically.
    violations.sort(key=lambda v: (str(v["node_id"]), v["rule"], v["message"]))
    return {"passed": not violations, "violations": violations}
