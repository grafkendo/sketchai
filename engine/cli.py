#!/usr/bin/env python3
"""
Etch engine — cli.py

Terminal interface (Phase 0 spike deliverable: "parameterized CLI").

    python cli.py compose --scene scene.json --brand protograph --out slide.svg [--png slide.png]
    python cli.py edit    --scene scene.json --ops ops.json --out scene2.json
    python cli.py render  --scene scene.json --brand protograph --png out.png [--pdf out.pdf]

compose prints the render_id + content_hash (the identity of the render);
edit prints the diff summary as JSON (the proof of surgical edits).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from batch import batch_rows, substitute_placeholders
from components import EtchError
from provenance import manifest_for, render_id_for
from render import compose, content_hash, edit, to_pdf, to_png


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_compose(args) -> int:
    scene = _load(args.scene)
    try:
        result = compose(scene, brand_id=args.brand)
    except EtchError as e:
        print(json.dumps({"error": e.to_dict()}, indent=2))
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(result["svg"])
        print(f"wrote {args.out}")
    if args.png:
        to_png(result["svg"], args.png)
        print(f"wrote {args.png}")
    bv = result.get("brand_validation") or {}
    print(json.dumps({
        "content_hash": result["content_hash"],
        "size": f"{result['width']}x{result['height']}",
        "nodes": len(result["bboxes"]),
        "brand_passed": bv.get("passed"),
        "brand_violations": len(bv.get("violations", [])),
    }, indent=2))
    return 0


def cmd_edit(args) -> int:
    scene = _load(args.scene)
    ops = _load(args.ops)
    if isinstance(ops, dict) and "ops" in ops:
        ops = ops["ops"]
    try:
        new_scene, diff = edit(scene, ops)
    except EtchError as e:
        print(json.dumps({"error": e.to_dict()}, indent=2))
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(new_scene, f, indent=2)
        print(f"wrote {args.out}")
    before = content_hash(scene)
    print(json.dumps({
        "ops_applied": diff["ops_applied"],
        "changed": diff["changed"],
        "details": diff["details"],
        "hash_before": before[:16],
        "note": "re-compose the output scene to get hash_after",
    }, indent=2))
    return 0


def cmd_render(args) -> int:
    scene = _load(args.scene)
    try:
        result = compose(scene, brand_id=args.brand)
    except EtchError as e:
        print(json.dumps({"error": e.to_dict()}, indent=2))
        return 1
    if args.png:
        to_png(result["svg"], args.png)
        print(f"wrote {args.png}")
    if args.pdf:
        to_pdf(result["svg"], args.pdf)
        print(f"wrote {args.pdf}")
    if args.svg:
        with open(args.svg, "w", encoding="utf-8") as f:
            f.write(result["svg"])
        print(f"wrote {args.svg}")
    print(f"hash {result['content_hash'][:16]}")
    return 0


def cmd_batch(args) -> int:
    import csv
    template = _load(args.scene)
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
    try:
        prepared = batch_rows(template, rows)
    except EtchError as e:
        print(json.dumps({"error": e.to_dict()}, indent=2))
        return 1
    renders = []
    for i, scene in prepared:
        try:
            result = compose(scene, brand_id=args.brand)
        except EtchError as e:
            print(json.dumps({"error": e.to_dict(), "row_index": i}, indent=2))
            return 1
        entry = {"row_index": i,
                 "render_id": render_id_for(result["content_hash"], args.brand),
                 "content_hash": result["content_hash"]}
        if args.out_dir:
            # WHY deterministic filename by index: row order is the input
            # order, so row_0.png always means the first CSV row.
            png_path = os.path.join(args.out_dir, f"row_{i}.png")
            to_png(result["svg"], png_path)
            entry["png"] = png_path
        renders.append(entry)
    print(json.dumps({"count": len(renders), "renders": renders}, indent=2))
    return 0


def cmd_provenance(args) -> int:
    rid = render_id_for(args.hash, args.brand)
    manifest = manifest_for(rid, args.hash, args.brand, args.parent or [])
    print(json.dumps(manifest, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="etch", description="Etch vector sketch engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compose", help="compose a scene JSON -> SVG (+hash)")
    c.add_argument("--scene", required=True)
    c.add_argument("--brand", default="protograph")
    c.add_argument("--out", help="write SVG to this path")
    c.add_argument("--png", help="also rasterize to this PNG path")
    c.set_defaults(fn=cmd_compose)

    e = sub.add_parser("edit", help="apply patch ops to a scene JSON")
    e.add_argument("--scene", required=True)
    e.add_argument("--ops", required=True, help="JSON file: list of ops or {ops: [...]}")
    e.add_argument("--out", help="write new scene JSON here")
    e.set_defaults(fn=cmd_edit)

    r = sub.add_parser("render", help="compose + export PNG/PDF/SVG")
    r.add_argument("--scene", required=True)
    r.add_argument("--brand", default="protograph")
    r.add_argument("--png")
    r.add_argument("--pdf")
    r.add_argument("--svg")
    r.set_defaults(fn=cmd_render)

    b = sub.add_parser("batch", help="render one scene per CSV row (mail-merge)")
    b.add_argument("--scene", required=True, help="template scene JSON with {{placeholders}}")
    b.add_argument("--csv", required=True, help="CSV file; headers are the placeholder keys")
    b.add_argument("--brand", default="protograph")
    b.add_argument("--out-dir", help="write row_<i>.png files here")
    b.set_defaults(fn=cmd_batch)

    p = sub.add_parser("provenance", help="print the signed-render manifest for a content hash")
    p.add_argument("--hash", required=True, help="content_hash from a compose")
    p.add_argument("--brand", default="protograph")
    p.add_argument("--parent", action="append", default=[],
                   help="parent render_id (repeatable, oldest first)")
    p.set_defaults(fn=cmd_provenance)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except EtchError as e:
        print(json.dumps({"error": e.to_dict()}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
