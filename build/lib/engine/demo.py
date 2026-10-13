#!/usr/bin/env python3
"""
Etch engine — demo.py (Phase 1 exit demo)

"An agent builds a 6-slide carousel from a prompt, then edits slide 3 —
diff summary confirms only slide 3 changed." (ROADMAP.md)

The SLIDES table below stands in for what an agent would produce from a
prompt: structured content (lines, accent, subline), not prose. build_slide()
turns each row into a scene graph using the Protograph brand tokens; the
engine does the rest. No coordinates are hand-placed for the text block —
a stack flows headline -> subline with a fixed gap, so the layout is
computed, not guessed.

Run:  python demo.py
Out:  engine/demo_out/slide-1.png ... slide-6.png, slide-3-edited.png
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import components as C
from render import compose, content_hash, edit, to_png

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_out")
BRAND = "protograph"

# The "prompt", as structured data: (headline lines, accent token, subline, curve colors)
SLIDES = [
    (["What does an AI", "media company", "actually make?"], "$colors.lime",
     "A new kind of studio.", ("$colors.magenta", "$colors.azure"), 112),
    (["AI INFLUENCERS"], "$colors.magenta",
     "Virtual faces. Real audiences.", ("$colors.lime", "$colors.azure"), 150),
    (["TUTORIALS"], "$colors.azure",
     "Learn the craft. Fast.", ("$colors.lime", "$colors.magenta"), 150),
    (["PRODUCT VIDEOS"], "$colors.lime",
     "Your product, cinematic.", ("$colors.magenta", "$colors.azure"), 112),
    (["PODCASTS"], "$colors.magenta",
     "Conversations that travel.", ("$colors.lime", "$colors.azure"), 150),
    (["FACEBOOK", "CONTENT", "PACKAGES"], "$colors.azure",
     "Follow for the drops.", ("$colors.lime", "$colors.magenta"), 118),
]


def build_slide(i: int) -> dict:
    """Row i of SLIDES -> full scene graph. node_ids are namespaced per
    slide (s3-headline, s3-curve1, ...) so edits can target them exactly."""
    lines, accent, sub, (c1, c2), size = SLIDES[i]
    n = i + 1
    tag = f"s{n}"
    headline = "\n".join(lines)
    copy_block = C.stack(
        f"{tag}-copy", direction="vertical", gap=28, align="start",
        x=80, y=330, children=[
            C.text(f"{tag}-headline", headline, font="$fonts.display",
                   size=size, weight=800, fill=accent, line_height=1.06,
                   max_width=920),
            C.text(f"{tag}-sub", sub, font="$fonts.body", size=46,
                   weight=500, fill="$colors.paper"),
        ])
    root = C.frame(
        f"{tag}-root", width=1080, height=1080, fill="$colors.bg", children=[
            C.curve(f"{tag}-curve1", 1080, 1080, fill=c1, bulge=0.16, thickness=0.13),
            C.curve(f"{tag}-curve2", 1080, 1080, fill=c2, bulge=0.10, thickness=0.09),
            C.text(f"{tag}-kicker", "PROTOGRAPH", font="$fonts.body", size=34,
                   weight=500, fill="$colors.paper", x=80, y=105, letter_spacing=8),
            C.text(f"{tag}-pagenum", f"0{n} / 06", font="$fonts.body", size=34,
                   weight=500, fill="$colors.paper", x=1000, y=105, anchor="end"),
            copy_block,
        ])
    return {"canvas": {"width": 1080, "height": 1080}, "brand_id": BRAND, "root": root}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    print("== Etch Phase-1 demo: 6-slide carousel, Protograph brand ==\n")

    hashes = {}
    for i in range(6):
        scene = build_slide(i)
        result = compose(scene, brand_id=BRAND)
        bv = result["brand_validation"]
        assert bv["passed"], f"slide {i+1} brand violations: {bv['violations']}"
        # Determinism spot-check: compose twice, hashes must match.
        again = compose(scene, brand_id=BRAND)
        assert again["content_hash"] == result["content_hash"], "NON-DETERMINISTIC compose!"
        path = os.path.join(OUT, f"slide-{i+1}.png")
        to_png(result["svg"], path)
        hashes[i] = result["content_hash"]
        print(f"slide-{i+1}.png  hash {result['content_hash'][:16]}  "
              f"brand ok  ({len(result['bboxes'])} nodes)")

    # -- surgical edit: slide 3 ONLY -------------------------------------
    print("\n-- surgical edit on slide 3: headline text + accent color --")
    scene3 = build_slide(2)
    before = compose(scene3, brand_id=BRAND)
    ops = [
        {"op": "set_text", "node_id": "s3-headline", "text": "HOW-TO GUIDES"},
        {"op": "set_fill", "node_id": "s3-curve1", "fill": "$colors.magenta"},
    ]
    scene3b, diff = edit(scene3, ops)
    after = compose(scene3b, brand_id=BRAND)
    to_png(after["svg"], os.path.join(OUT, "slide-3-edited.png"))

    print(f"hash before: {before['content_hash']}")
    print(f"hash after:  {after['content_hash']}")
    print(f"changed:     {diff['changed']}")
    print(f"details:     {diff['details']}")

    assert before["content_hash"] != after["content_hash"], "edit did not change the render!"
    assert diff["changed"] == ["s3-headline", "s3-curve1"], \
        f"edit touched unexpected nodes: {diff['changed']}"
    assert all(c.startswith("s3-") for c in diff["changed"])
    # Untouched slides are byte-identical to before.
    for i in (0, 1, 3, 4, 5):
        assert compose(build_slide(i), brand_id=BRAND)["content_hash"] == hashes[i]

    print("\nOK: only slide-3 nodes changed; all other slides byte-identical.")
    print(f"PNGs in {OUT}/")


if __name__ == "__main__":
    main()
