#!/usr/bin/env python3
"""
Etch engine — batch.py

Data-driven rendering: one scene template + N data rows = N renders.

Placeholders look like {{name}} and may appear in any string param (text,
fill, src, ...). Each row is a dict of values; substitution is a pure
function, so the same (template, row) always produces the same render —
batch is just N deterministic composes, and each keeps its own content_hash.

WHY a separate module, not inline in the MCP server: packs.py (component
packs) needs the same placeholder substitution for fragment params, and the
CLI needs it for CSV mode. One implementation, three callers.
"""

from __future__ import annotations

import copy
import re

from components import EtchError

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class BatchError(EtchError):
    pass


def substitute_placeholders(scene: dict, values: dict,
                            context: str = "row") -> dict:
    """Deep-copy scene, replacing every {{key}} with values[key].

    Missing key → BatchError naming the placeholder and the available keys.
    Leftover placeholders after substitution → BatchError (a typo like
    {{nmae}} must fail loudly, never render literally).
    """
    if not isinstance(values, dict):
        raise BatchError(None, f"{context} must be a dict of values",
                         "Pass e.g. {'name': 'Ada', 'color': '#B6FF3B'}.")
    working = copy.deepcopy(scene)

    def sub_string(s: str, node_id: str | None) -> str:
        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key not in values:
                raise BatchError(
                    node_id,
                    f"placeholder '{{{{{key}}}}}' has no value in this {context}",
                    f"Available keys: {sorted(values) or '(none)'} — add '{key}' "
                    f"to the {context} or remove the placeholder.",
                )
            return str(values[key])
        return PLACEHOLDER_RE.sub(repl, s)

    def walk(n: dict) -> None:
        nid = n.get("node_id")
        for k, v in list(n.items()):
            if k in ("type", "children"):
                continue
            if isinstance(v, str):
                n[k] = sub_string(v, nid)
            elif isinstance(v, dict):
                walk(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        walk(item)
        for child in n.get("children", []):
            walk(child)

    if "root" not in working:
        raise BatchError(None, "template scene must be a dict with 'root'",
                         "Minimal template: {'canvas': {...}, 'root': {...}}.")
    walk(working["root"])

    # Leftover check: catch typos the row couldn't satisfy.
    leftovers: set[str] = set()
    def scan(n: dict) -> None:
        for k, v in n.items():
            if k == "children":
                continue
            if isinstance(v, str):
                leftovers.update(PLACEHOLDER_RE.findall(v))
            elif isinstance(v, dict):
                scan(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        scan(item)
        for child in n.get("children", []):
            scan(child)
    scan(working["root"])
    if leftovers:
        raise BatchError(
            None,
            f"unsubstituted placeholder(s) remain: {sorted(leftovers)}",
            "Every {{key}} in the template needs a matching key in each row.",
        )
    return working


def batch_rows(template_scene: dict, rows: list[dict]) -> list[dict]:
    """Validate rows and return [(index, substituted_scene)]. Raises on the
    first bad row, naming its index — a bad row shouldn't silently poison a
    10,000-row run."""
    if not isinstance(rows, list) or not rows:
        raise BatchError(None, "rows must be a non-empty list of dicts",
                         "Pass e.g. rows=[{'name': 'Ada'}, {'name': 'Grace'}].")
    out = []
    for i, row in enumerate(rows):
        try:
            out.append((i, substitute_placeholders(template_scene, row,
                                                   context=f"row #{i}")))
        except BatchError as e:
            # substitute_placeholders already names the row index in its
            # messages via context= — re-raise unchanged.
            raise
    return out
