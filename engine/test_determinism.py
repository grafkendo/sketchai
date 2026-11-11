#!/usr/bin/env python3
"""
Etch engine — test_determinism.py

The product promise, as executable assertions:

1. Same scene composed twice -> identical sha256 AND byte-identical PNGs.
   (WHY both: the hash covers the resolved scene graph; the PNG bytes cover
   the rasterizer too. A hash match with different PNG bytes would mean
   cairosvg is non-deterministic — we check the whole chain.)
2. Editing one node -> hash changes.
3. Re-composing the UNEDITED original -> still matches its original hash.
   (WHY: proves edit() didn't mutate the input scene — renders are immutable
   versions, and history stays addressable.)

Run:  python test_determinism.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import components as C
from render import compose, edit, to_png


def make_scene() -> dict:
    root = C.frame("t-root", 800, 600, fill="$colors.bg", children=[
        C.stack("t-stack", direction="vertical", gap=20, align="center",
                x=0, y=60, width=800, children=[
                    C.badge("t-badge", "DETERMINISM", fill="$colors.lime"),
                    C.text("t-head", "Same pixels, every time.", size=56,
                           fill="$colors.paper"),
                    C.divider("t-div", 400),
                    C.chart_bar("t-chart",
                                [{"label": "A", "value": 30},
                                 {"label": "B", "value": 70},
                                 {"label": "C", "value": 50}],
                                width=400, height=220),
                ]),
    ])
    return {"canvas": {"width": 800, "height": 600}, "root": root}


def main() -> None:
    scene = make_scene()

    r1 = compose(scene, brand_id="protograph")
    r2 = compose(scene, brand_id="protograph")
    png1 = to_png(r1["svg"])
    png2 = to_png(r2["svg"])

    assert r1["content_hash"] == r2["content_hash"], "hash mismatch on identical scene"
    print(f"PASS  identical scene -> identical sha256 ({r1['content_hash'][:16]})")
    assert png1 == png2, "PNG bytes differ on identical scene"
    print(f"PASS  identical scene -> byte-identical PNG ({len(png1)} bytes)")

    edited, diff = edit(scene, [
        {"op": "set_text", "node_id": "t-head", "text": "Changed."},
    ])
    r3 = compose(edited, brand_id="protograph")
    assert r3["content_hash"] != r1["content_hash"], "edit did not change hash"
    assert diff["changed"] == ["t-head"], f"unexpected diff: {diff['changed']}"
    print(f"PASS  one-node edit -> hash changed, diff={diff['changed']}")

    r4 = compose(scene, brand_id="protograph")
    assert r4["content_hash"] == r1["content_hash"], "original scene hash drifted after edit"
    print("PASS  unedited original re-renders to its original hash (edit is non-mutating)")

    # Attribute values are caller-supplied, so a quote or angle bracket in a
    # param must be escaped into the SVG, never injected as raw markup.
    evil = make_scene()
    evil["root"]["fill"] = '#fff" /><text id="injected">pwned</text><rect fill="'
    revil = compose(evil, brand_id="protograph")
    assert '<text id="injected">' not in revil["svg"], revil["svg"]
    assert "&quot;" in revil["svg"] and "&lt;" in revil["svg"], revil["svg"]
    print("PASS  attribute values are XML-escaped (no markup injection)")

    # Brand validation sanity: off-palette color must be caught, naming the node.
    bad = make_scene()
    bad["root"]["children"][0]["children"][0] = C.badge(
        "t-badge", "DETERMINISM", fill="#123456")  # not in Protograph palette
    rb = compose(bad, brand_id="protograph")
    assert not rb["brand_validation"]["passed"]
    pal = [v for v in rb["brand_validation"]["violations"]
           if v["rule"] == "palette"]
    assert pal and pal[0]["node_id"] == "t-badge", rb["brand_validation"]["violations"]
    v = pal[0]
    print(f"PASS  brand violation caught: [{v['node_id']}] {v['rule']} — {v['message'][:60]}...")

    print("\nAll determinism tests passed.")


if __name__ == "__main__":
    main()
