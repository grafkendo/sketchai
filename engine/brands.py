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

# Brand files live in a fixed directory and are addressed by name only.
# WHY a strict name pattern: brand_id arrives from tool and API callers, and
# os.path.join(brands_dir, f"{brand_id}.json") would otherwise follow "../"
# out of the brands directory.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class BrandError(EtchError):
    pass


def load_brand(brand_id: str, brands_dir: str = BRANDS_DIR) -> dict:
    if not isinstance(brand_id, str) or not _SAFE_NAME.match(brand_id):
        raise BrandError(
            None, f"invalid brand_id '{brand_id}'",
            "brand_id must contain only letters, digits, '_' or '-'.",
        )
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


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance. WHY strip alpha: contrast is about the
    opaque color; alpha compositing against unknown backdrops is out of
    scope for a static rule."""
    c = _norm_hex(hex_color)[:7]
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast_ratio(c1: str, c2: str) -> float:
    hi, lo = max(_luminance(c1), _luminance(c2)), min(_luminance(c1), _luminance(c2))
    return (hi + 0.05) / (lo + 0.05)


def _scene_background(root: dict) -> str | None:
    """The canvas color text sits on: the root frame's resolved fill.
    None when the root has no solid fill — contrast can't be computed
    against transparency, so the rule skips those scenes silently."""
    fill = root.get("fill")
    return fill if isinstance(fill, str) and _HEX.match(fill) else None


def validate(scene: dict, brand: dict) -> dict:
    """Check the (token-resolved) scene against the brand's rules.

    Returns {"passed": bool, "violations": [{node_id, rule, severity,
    message, suggestion}]}. WHY return-not-raise: the API needs warn mode,
    and a single report listing ALL violations is far more useful to an
    iterating agent than fail-fast on the first one.

    Severity: each rule may declare "severity": "warn" (default "error").
    "passed" is False if ANY violation exists (warn or error) — but strict
    mode (the compose path) only BLOCKS on severity=="error". Warnings are
    for guidance ("this headline is low-contrast") that shouldn't stop an
    iterating agent.
    """
    violations: list[dict] = []
    rules = brand.get("rules", [])
    palette = {_norm_hex(c) for c in brand.get("colors", {}).values()}
    neutrals = {_norm_hex(c) for c in brand.get("neutrals", ["#FFFFFF"])}
    allowed_fonts = {f.strip().lower() for f in brand.get("fonts", {}).values()}

    def add(node_id, rule, message, suggestion="", severity="error"):
        v = {"node_id": node_id, "rule": rule, "severity": severity,
             "message": message}
        if suggestion:
            v["suggestion"] = suggestion
        violations.append(v)

    root = scene.get("root", {})
    bg = _scene_background(root)
    for node in _iter_nodes(root):
        nid = node.get("node_id")
        for rule in rules:
            rtype = rule.get("type")
            sev = rule.get("severity", "error")
            if rtype == "palette":
                for param, color in _color_params(node):
                    if not _HEX.match(color):
                        add(nid, "palette",
                            f"{param}='{color}' is not a valid hex color",
                            "Use #RRGGBB, or a $colors.* brand token.", sev)
                    elif _norm_hex(color) not in palette | neutrals:
                        add(nid, "palette",
                            f"{param}='{color}' is not in the '{brand.get('id')}' palette",
                            f"Use one of: {', '.join(sorted(palette))} (or add it to the brand).", sev)
            elif rtype == "fonts":
                fam = node.get("font")
                if isinstance(fam, str) and fam.strip().lower() not in allowed_fonts:
                    add(nid, "fonts",
                        f"font='{fam}' is not a brand font",
                        f"Use one of: {', '.join(sorted(allowed_fonts))} (or $fonts.display / $fonts.body tokens).", sev)
            elif rtype == "no_pure_black":
                for param, color in _color_params(node):
                    if _norm_hex(color) == "#000000":
                        add(nid, "no_pure_black",
                            f"{param} uses pure black #000000",
                            "Use the brand's near-black instead (e.g. $colors.bg).", sev)
            elif rtype == "contrast":
                # Text legibility: text fill vs. what it sits on. For badge
                # nodes the text sits on the pill (text_fill vs fill); for
                # text nodes it sits on the scene background.
                min_ratio = rule.get("min_ratio", 4.5)
                fg, against = None, None
                if node.get("type") == "badge":
                    fg, against = node.get("text_fill"), node.get("fill")
                elif node.get("type") == "text":
                    fg, against = node.get("fill"), bg
                if (isinstance(fg, str) and _HEX.match(fg)
                        and isinstance(against, str) and _HEX.match(against)):
                    ratio = _contrast_ratio(fg, against)
                    if ratio < min_ratio:
                        add(nid, "contrast",
                            f"text contrast ratio {ratio:.2f} < {min_ratio} "
                            f"({fg} on {against})",
                            "Lighten the text fill or darken the background — "
                            "4.5:1 is the WCAG AA bar for body text.", sev)
    # Scene-level rules (no single node to blame).
    for rule in rules:
        sev = rule.get("severity", "error")
        if rule.get("type") == "max_colors":
            # WHY neutrals are free: white/black text is typography, not
            # "using another brand color". Counting them would punish every
            # scene with readable type.
            used: set[str] = set()
            for node in _iter_nodes(root):
                for _, color in _color_params(node):
                    nc = _norm_hex(color)
                    if nc not in neutrals:
                        used.add(nc)
            max_n = rule.get("max", 6)
            if len(used) > max_n:
                add(None, "max_colors",
                    f"scene uses {len(used)} distinct colors, max is {max_n}: "
                    f"{', '.join(sorted(used))}",
                    "Consolidate fills onto palette colors, or raise the "
                    "brand's max.", sev)
    # Deterministic violation order: sort by (node_id, rule, message) so two
    # runs over the same scene report identically.
    violations.sort(key=lambda v: (str(v["node_id"]), v["rule"], v["message"]))
    return {"passed": not violations, "violations": violations}
