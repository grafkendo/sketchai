#!/usr/bin/env python3
"""
Etch engine — diff.py

Visual diff: pixel-compare two renders and highlight what changed.

Given two PNGs of the same size, produces:
  - diff_png: the base image dimmed to 35%, changed pixels painted pure red
  - pct_changed: percentage of pixels that differ (0-100)
  - regions: bounding boxes of changed areas, [{x, y, width, height}]

WHY all C-speed Pillow ops (ImageChops, point LUTs, composite): a 1080x1080
image has 1.16M pixels — a Python per-pixel loop takes seconds per diff.
Chops/difference + LUT mapping + composite run in C and finish in
milliseconds. Every op is deterministic: same two PNGs, same diff, always.

Region detection: connected components (4-connectivity, iterative flood
fill) on an 8x-downsampled change mask, boxes scaled back to full-res
pixels. WHY downsampled: components over the full mask would be 1.16M
cells; 135x135 is exact enough to answer "which node changed".

This is the visual counterpart to edit()'s diff.changed list: the edit loop
tells you WHICH nodes changed; the visual diff shows you WHERE on the
canvas. Together they make "nothing else moved" verifiable, not just
claimed.
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageStat

from components import EtchError

_DOWNSAMPLE = 8


class DiffError(EtchError):
    pass


def _dilate(mask: list[list[bool]]) -> list[list[bool]]:
    """Expand every marked cell by 1 in all 8 directions.

    WHY: antialiased text edges leave 1-cell gaps in the change mask, which
    would split one visual change into several regions. Dilation absorbs the
    speckle so "the headline changed" reports as one region, not five.
    """
    h, w = len(mask), len(mask[0])
    out = [row[:] for row in mask]
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w:
                            out[ny][nx] = True
    return out


def _components(mask: list[list[bool]]) -> list[tuple[int, int, int, int]]:
    """4-connected components on a boolean grid. Returns (x0, y0, x1, y1)
    cell boxes, sorted by (y, x) for deterministic output."""
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    boxes = []
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            # Flood fill (iterative — no recursion-depth risk).
            stack = [(x0, y0)]
            seen[y0][x0] = True
            x1 = x2 = x0
            y1 = y2 = y0
            while stack:
                x, y = stack.pop()
                x1, x2 = min(x1, x), max(x2, x)
                y1, y2 = min(y1, y), max(y2, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            boxes.append((x1, y1, x2, y2))
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


def visual_diff(png_a: bytes, png_b: bytes) -> dict:
    """Compare two PNGs. Returns {"diff_png", "pct_changed", "regions"}.

    Raises DiffError if the images differ in size — a diff across sizes is
    meaningless, and failing loudly beats stretching one to fit.
    """
    a = Image.open(io.BytesIO(png_a)).convert("RGB")
    b = Image.open(io.BytesIO(png_b)).convert("RGB")
    if a.size != b.size:
        raise DiffError(
            None,
            f"images differ in size: {a.size[0]}x{a.size[1]} vs {b.size[0]}x{b.size[1]}",
            "Diff renders of the same canvas size — check the scenes' canvas blocks.",
        )
    w, h = a.size

    # Per-pixel difference, then collapse to a 0/1 change map (C-speed).
    gray = ImageChops.difference(a, b).convert("L")
    changed_map = gray.point([0] + [1] * 255)
    changed = int(ImageStat.Stat(changed_map).sum[0])

    # Dimmed base + red overlay composited through the change mask.
    # WHY LUT * 3: point() on an RGB image needs 256 entries per band.
    dimmed = a.point([int(v * 0.35) for v in range(256)] * 3)
    red = Image.new("RGB", a.size, (255, 0, 0))
    mask_img = gray.point([0] + [255] * 255)
    out = Image.composite(red, dimmed, mask_img.convert("L"))

    # Region boxes: any-change test per downsampled cell (crop+getbbox in C).
    gw, gh = (w + _DOWNSAMPLE - 1) // _DOWNSAMPLE, (h + _DOWNSAMPLE - 1) // _DOWNSAMPLE
    mask = [[False] * gw for _ in range(gh)]
    for gy in range(gh):
        for gx in range(gw):
            cell = gray.crop((gx * _DOWNSAMPLE, gy * _DOWNSAMPLE,
                              min((gx + 1) * _DOWNSAMPLE, w),
                              min((gy + 1) * _DOWNSAMPLE, h)))
            if cell.getbbox() is not None:
                mask[gy][gx] = True
    regions = []
    for (x1, y1, x2, y2) in _components(_dilate(mask)):
        # Scale cell boxes back to full-res pixels, clamped to the canvas.
        regions.append({
            "x": x1 * _DOWNSAMPLE,
            "y": y1 * _DOWNSAMPLE,
            "width": min((x2 - x1 + 1) * _DOWNSAMPLE, w - x1 * _DOWNSAMPLE),
            "height": min((y2 - y1 + 1) * _DOWNSAMPLE, h - y1 * _DOWNSAMPLE),
        })

    buf = io.BytesIO()
    out.save(buf, "PNG")
    return {
        "diff_png": buf.getvalue(),
        "pct_changed": round(100.0 * changed / (w * h), 3),
        "regions": regions,
        "size": {"width": w, "height": h},
    }
