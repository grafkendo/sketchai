#!/usr/bin/env python3
"""
test_brands.py — smarter brand rules: contrast + max_colors + severity.

Verifies the new rules against the real demo scenes (must not block) and
against synthetic scenes (must catch violations with node + rule + measured
value + fix). Run with:
    .venv/bin/python test_brands.py
"""

import copy
import os
import sys

ENGINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE)

from brands import _contrast_ratio, load_brand, resolve_tokens, validate  # noqa: E402
from components import EtchError  # noqa: E402
from demo import build_slide  # noqa: E402
from render import compose  # noqa: E402


def _scene(nodes: list[dict], bg: str = "#171310") -> dict:
    return {
        "canvas": {"width": 400, "height": 400},
        "root": {
            "type": "frame", "node_id": "root", "width": 400, "height": 400,
            "fill": bg, "children": nodes,
        },
    }


def _text(nid: str, fill: str, text: str = "Hello") -> dict:
    return {"type": "text", "node_id": nid, "text": text,
            "font": "$fonts.display", "size": 60, "fill": fill,
            "x": 40, "y": 150}


def test_contrast_math() -> None:
    # White on black is ~21:1; same color is 1:1.
    assert abs(_contrast_ratio("#ffffff", "#000000") - 21.0) < 0.1
    assert _contrast_ratio("#B6FF3B", "#B6FF3B") == 1.0
    # Lime on Protograph bg is very high (the passing case).
    assert _contrast_ratio("#B6FF3B", "#171310") > 10
    # Dark gray on near-black fails AA.
    assert _contrast_ratio("#444444", "#171310") < 4.5
    print("PASS  WCAG contrast math sane")


def test_contrast_rule() -> None:
    brand = load_brand("protograph")
    # Failing case: dark gray text on dark bg.
    scene = _scene([_text("t1", "#444444")])
    resolve_tokens(scene["root"], brand)
    rep = validate(scene, brand)
    cv = [v for v in rep["violations"] if v["rule"] == "contrast"]
    assert len(cv) == 1, rep["violations"]
    v = cv[0]
    assert v["node_id"] == "t1", v
    assert v["severity"] == "warn", v
    assert "ratio" in v["message"] and "4.5" in v["message"], v["message"]
    assert v["suggestion"], "must suggest a fix"
    # Measured value present and below the bar.
    ratio = float(v["message"].split("ratio")[1].split("<")[0])
    assert ratio < 4.5
    print(f"PASS  contrast violation: node + rule + measured ratio {ratio:.2f} + fix")

    # Passing case: lime on bg — no contrast violation.
    scene2 = _scene([_text("t2", "$colors.lime")])
    resolve_tokens(scene2["root"], brand)
    rep2 = validate(scene2, brand)
    assert not [v for v in rep2["violations"] if v["rule"] == "contrast"], \
        rep2["violations"]
    print("PASS  high-contrast text passes")

    # Badge: text_fill vs pill fill, not vs scene bg.
    # (azure on paper = 2.45:1 — palette-clean but fails AA.)
    badge = {"type": "badge", "node_id": "b1", "text": "Hi",
             "fill": "#F7F2E8", "text_fill": "#00A3FF",
             "font": "$fonts.body", "size": 30, "x": 40, "y": 200}
    scene3 = _scene([badge])
    resolve_tokens(scene3["root"], brand)
    rep3 = validate(scene3, brand)
    cv3 = [v for v in rep3["violations"] if v["rule"] == "contrast"]
    assert len(cv3) == 1 and cv3[0]["node_id"] == "b1", rep3["violations"]
    assert "#00A3FF" in cv3[0]["message"] and "#F7F2E8" in cv3[0]["message"]
    print("PASS  badge contrast measured text_fill vs pill fill")


def test_max_colors_rule() -> None:
    brand = load_brand("protograph")
    colors = ["#111111", "#222222", "#333333", "#444444",
              "#555555", "#666666", "#777777"]
    nodes = [{"type": "rect", "node_id": f"c{i}", "width": 10, "height": 10,
              "fill": c, "x": i * 12, "y": 10} for i, c in enumerate(colors)]
    scene = _scene(nodes)
    resolve_tokens(scene["root"], brand)
    rep = validate(scene, brand)
    mv = [v for v in rep["violations"] if v["rule"] == "max_colors"]
    assert len(mv) == 1, rep["violations"]
    v = mv[0]
    assert "7" in v["message"] and "6" in v["message"], v["message"]
    assert v["severity"] == "warn"
    assert v["suggestion"]
    assert v["node_id"] is None, "scene-level rule has no node"
    print("PASS  max_colors violation names count + budget + fix")

    # Neutrals are free: a synthetic brand with 8 palette colors, max 3.
    # 3 colors + white text -> fine; a 4th color -> violation.
    synth = {
        "id": "synth",
        "colors": {f"c{i}": c for i, c in enumerate(
            ["#111111", "#222222", "#333333", "#444444",
             "#555555", "#666666", "#777777", "#888888"])},
        "neutrals": ["#FFFFFF"],
        "fonts": {"display": "Bricolage Grotesk", "body": "Hanken Grotesk"},
        "rules": [{"type": "max_colors", "max": 3, "severity": "warn"}],
    }
    ok_nodes = [{"type": "rect", "node_id": f"o{i}", "width": 10, "height": 10,
                 "fill": c, "x": i * 12, "y": 10}
                for i, c in enumerate(["#111111", "#222222", "#333333"])]
    ok_nodes.append(_text("t-white", "#FFFFFF"))
    scene_ok = _scene(ok_nodes, bg="#111111")
    rep_ok = validate(scene_ok, synth)
    assert not [v for v in rep_ok["violations"] if v["rule"] == "max_colors"], \
        rep_ok["violations"]
    print("PASS  neutrals don't count toward max_colors")

    bad_nodes = ok_nodes + [{"type": "rect", "node_id": "o4", "width": 10,
                             "height": 10, "fill": "#444444", "x": 60, "y": 10}]
    scene_bad = _scene(bad_nodes, bg="#111111")
    rep_bad = validate(scene_bad, synth)
    mv_bad = [v for v in rep_bad["violations"] if v["rule"] == "max_colors"]
    assert len(mv_bad) == 1 and "4" in mv_bad[0]["message"], rep_bad["violations"]
    print("PASS  4th color trips max_colors")


def test_severity_semantics() -> None:
    # The strict gate lives in _do_compose (MCP server / API), not in
    # render.compose — test through the real gate.
    from mcp_server import _do_compose  # noqa: E402
    from components import EtchError as _EE  # noqa: E402

    # Warn-only scene: strict compose must NOT block.
    # (bg-colored text on bg = 1.0:1 contrast, but palette-clean —
    #  the only Protograph-palette combo that fails contrast.)
    scene = _scene([_text("t1", "#171310")])
    record = _do_compose(copy.deepcopy(scene), "protograph", strict=True)
    bv = record["brand_validation"]
    warns = [v for v in bv["violations"] if v.get("severity") == "warn"]
    assert warns, "expected warn-level violations"
    print(f"PASS  warn violations reported ({len(warns)}) but strict compose succeeds")

    # Error-severity still blocks: off-palette color is an error.
    bad = _scene([_text("t2", "#123456")])
    try:
        _do_compose(bad, "protograph", strict=True)
        raise AssertionError("should have raised")
    except _EE as e:
        assert "palette" in e.reason, e.reason
    print("PASS  error-severity violations still block strict compose")

    # ...but not in warn mode (strict=False).
    record2 = _do_compose(copy.deepcopy(bad), "protograph", strict=False)
    assert record2["render_id"].startswith("r_")
    print("PASS  strict=false renders despite error-severity violations")


def test_demo_scenes_unaffected() -> None:
    # The 6 real demo slides must render strict with zero NEW violations
    # blocking them (the rules were added as warnings after verifying this).
    brand = load_brand("protograph")
    assert any(r.get("type") == "contrast" for r in brand["rules"])
    assert any(r.get("type") == "max_colors" for r in brand["rules"])
    for i in range(6):
        result = compose(build_slide(i), brand_id="protograph")
        errs = [v for v in result["brand_validation"]["violations"]
                if v.get("severity", "error") == "error"]
        assert not errs, f"slide {i+1}: {errs}"
    print("PASS  all 6 demo slides compose strict with the new rules in place")


if __name__ == "__main__":
    test_contrast_math()
    test_contrast_rule()
    test_max_colors_rule()
    test_severity_semantics()
    test_demo_scenes_unaffected()
    print("\nAll brand-rule tests passed.")
