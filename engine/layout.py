#!/usr/bin/env python3
"""
Etch engine — layout.py

Constraint/flow layout resolver + SVG emitter.

WHY a layout engine at all: agents cannot see the canvas, so asking them for
pixel coordinates is asking them to guess. The resolver turns constraints
("vertical stack, 24px gaps, centered") into exact coordinates. Because the
resolver is a pure function of the scene graph — no randomness, no wall-clock,
no iteration order leaking in — the same scene always produces the same
pixels. That determinism is the product.

Text measurement uses the REAL font files (via fontconfig + PIL), not
estimates. WHY: if the engine guessed text widths, stacks would overlap or
leave gaps differently than the final raster — the agent would be designing
against a lie. Measuring with the same fonts cairo uses keeps layout and
render in agreement.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import lru_cache
from xml.sax.saxutils import escape as xml_escape

from PIL import ImageFont

from components import CONTAINERS, EtchError


class LayoutError(EtchError):
    pass


# ------------------------------------------------------- font resolution

_WEIGHT_NAMES = {  # style substring -> numeric weight, checked in order
    "extrabold": 800, "bold": 700, "semibold": 600, "medium": 500,
    "regular": 400, "light": 300, "thin": 100,
}


def _ttf_name_table(directory: str) -> list[tuple[str, str, str]]:
    """Read (file, family, style) from every TTF/OTF in a directory via PIL.

    Used for the bundled engine/fonts/ and for C:\\Windows\\Fonts — no
    fontconfig needed, so this works on machines where fc-list is absent.
    """
    out: list[tuple[str, str, str]] = []
    if not os.path.isdir(directory):
        return out
    for fn in sorted(os.listdir(directory)):
        if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
            continue
        path = os.path.join(directory, fn)
        try:
            family, style = ImageFont.truetype(path, 16).getname()
            out.append((path, family, style))
        except OSError:
            continue
    return out


@lru_cache(maxsize=1)
def _fontconfig_index() -> list[tuple[str, str, str]]:
    """Font index: [(file, family, style)].

    Bundled fonts (engine/fonts/) come FIRST, then Windows system fonts, then
    fontconfig results. WHY bundled-first: cross-machine determinism — the same
    TTF file measures and renders identically everywhere, while system
    fontconfig varies by machine and doesn't exist on Windows at all.
    resolve_font() picks by family match + closest weight, so bundled fonts
    win ties.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    out: list[tuple[str, str, str]] = _ttf_name_table(os.path.join(here, "fonts"))
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        out.extend(_ttf_name_table(os.path.join(windir, "Fonts")))
    try:
        raw = subprocess.run(
            ["fc-list", ":", "file", "family", "style"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return out
    for line in raw.splitlines():
        # format: "/path/file.ttf: Family Name:style=StyleName"
        m = re.match(r"^(.*?):\s*(.*?):style=(.*)$", line.strip())
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def resolve_font(family: str, weight: int = 400) -> tuple[str, int, bool]:
    """Return (font_file, matched_weight, was_fallback).

    Matches family case-insensitively, then picks the installed style whose
    weight is closest to the request. Falls back to DejaVu Sans, and reports
    it — the engine never silently pretends a font is used when it isn't.
    """
    index = _fontconfig_index()
    fam = family.strip().lower()

    def style_weight(style: str) -> int:
        s = style.lower()
        for name, w in _WEIGHT_NAMES.items():
            if name in s:
                return w
        return 400

    candidates = [(f, style_weight(st)) for (f, fa, st) in index
                  if fam in fa.lower()]
    if candidates:
        # Closest weight wins; ties prefer the heavier cut (display type
        # usually wants the bolder option when exact weight is missing).
        best = min(candidates, key=lambda c: (abs(c[1] - weight), -c[1]))
        return best[0], best[1], best[1] != weight

    # Ultimate fallback: DejaVu Sans ships with virtually every Linux.
    fb = [(f, style_weight(st)) for (f, fa, st) in index if "dejavu sans" in fa.lower()]
    if fb:
        best = min(fb, key=lambda c: (abs(c[1] - weight), -c[1]))
        return best[0], best[1], True
    raise LayoutError(None, f"no usable font found for '{family}' and no DejaVu fallback",
                      "Add the TTF to engine/fonts/ or install the family on this system.")


@lru_cache(maxsize=512)
def _pil_font(font_file: str, size: int):
    # WHY cache: measurement happens per text node per layout pass; reloading
    # the TTF each time would dominate render cost. size is int because PIL
    # wants ints and fractional sizes buy nothing for layout.
    return ImageFont.truetype(font_file, size)


def measure_text(text: str, family: str, size: float, weight: int = 400,
                 line_height: float = 1.15, max_width: float | None = None,
                 letter_spacing: float = 0) -> tuple[float, list[str], float]:
    """Return (width, lines, height) for text, wrapping greedily at
    max_width when given. Lines split on '\\n' first, then wrap.

    WHY measure instead of estimate: see module docstring. WHY greedy wrap:
    optimal (Knuth-Plass) wrapping is overkill for labels/headlines, and
    greedy is deterministic and easy for an agent to reason about.
    """
    font_file, _, _ = resolve_font(family, weight)
    size_i = max(1, int(round(size)))
    font = _pil_font(font_file, size_i)
    ascent, descent = font.getmetrics()

    def w(s: str) -> float:
        if not s:
            return 0.0
        box = font.getbbox(s)
        # letter_spacing adds per-character tracking (brand typography often
        # uses wide-tracked kickers, e.g. the Protograph wordmark).
        return (box[2] - box[0]) + letter_spacing * max(0, len(s) - 1)

    lines: list[str] = []
    for para in text.split("\n"):
        if max_width is None or w(para) <= max_width:
            lines.append(para)
            continue
        cur: list[str] = []
        for word in para.split(" "):
            trial = " ".join(cur + [word]) if cur else word
            if cur and w(trial) > max_width:
                lines.append(" ".join(cur))
                cur = [word]
            else:
                cur.append(word)
        lines.append(" ".join(cur))

    width = max([w(l) for l in lines] + [0.0])
    # Line box = ascent + descent scaled by line_height; using font metrics
    # (not getbbox) keeps multi-line rhythm stable regardless of glyphs.
    height = (ascent + descent) * line_height * len(lines)
    return round(width, 2), lines, round(height, 2)


# ------------------------------------------------------- layout resolver

def _pad(padding) -> tuple[float, float, float, float]:
    """Normalize padding to (top, right, bottom, left)."""
    if isinstance(padding, (int, float)):
        return (padding, padding, padding, padding)
    if isinstance(padding, (list, tuple)) and len(padding) == 4:
        return tuple(padding)  # type: ignore[return-value]
    raise LayoutError(None, f"padding must be a number or [t,r,b,l], got {padding!r}", "")


def _r2(v: float) -> float:
    # WHY round to 2 decimals: float repr noise (0.1+0.2) would otherwise make
    # SVG output — and therefore PNG bytes — depend on operation order rather
    # than on the scene. Rounding keeps output a pure function of input.
    return round(float(v), 2)


class Resolver:
    """Walks the scene tree, assigning every node _x/_y/_w/_h and recording
    bounding boxes keyed by node_id (so agents can reason about layout
    programmatically — spec §10)."""

    def __init__(self, brand: dict | None = None):
        self.brand = brand or {}
        self.bboxes: dict[str, dict] = {}
        self._auto = 0

    # -- public ------------------------------------------------------

    def resolve(self, scene: dict) -> dict:
        canvas = scene.get("canvas", {})
        cw = canvas.get("width", 1080)
        ch = canvas.get("height", 1080)
        root = scene["root"]
        self._layout_node(root, 0, 0, cw, ch)
        return root

    # -- dispatch ----------------------------------------------------

    def _layout_node(self, node: dict, x: float, y: float,
                     avail_w: float, avail_h: float) -> tuple[float, float]:
        """Lay out node at (x, y) within available space. Returns (w, h)."""
        t = node["type"]
        if node.get("node_id") is None:
            self._auto += 1
            # WHY deterministic auto-IDs: traversal order is fixed, so the
            # same scene always gets the same IDs — required for stable
            # content hashes of raw JSON scenes.
            node["node_id"] = f"{t}_{self._auto:03d}"

        handler = getattr(self, f"_lay_{t}", None)
        if handler is None:
            raise LayoutError(node.get("node_id"),
                              f"no layout handler for type '{t}'", "")
        w, h = handler(node, x, y, avail_w, avail_h)
        if t == "text":
            # WHY anchor shifts the box: x is the ANCHOR POINT, not the box
            # origin — matching SVG's text-anchor semantics. anchor="end"
            # with x=1000 means "right edge at 1000", so the box starts at
            # 1000 - width. Without this, end-anchored text would run off
            # the canvas (the classic cut-off page number bug).
            anchor = node.get("anchor", "start")
            if anchor == "end":
                x -= w
            elif anchor == "middle":
                x -= w / 2
        node["_x"], node["_y"], node["_w"], node["_h"] = _r2(x), _r2(y), _r2(w), _r2(h)
        self.bboxes[node["node_id"]] = {"x": _r2(x), "y": _r2(y),
                                        "width": _r2(w), "height": _r2(h)}
        return w, h

    def _child_xy(self, node: dict) -> tuple[float | None, float | None]:
        return node.get("x"), node.get("y")

    # -- containers --------------------------------------------------

    def _lay_frame(self, node, x, y, avail_w, avail_h):
        w, h = node["width"], node["height"]
        pad_t, pad_r, pad_b, pad_l = _pad(node.get("padding", 0))
        flow_y = y + pad_t  # children without x/y stack vertically from here
        for child in node.get("children", []):
            cx, cy = self._child_xy(child)
            if cx is None or cy is None:
                cw, chh = self._layout_node(child, x + pad_l, flow_y,
                                            w - pad_l - pad_r, h)
                flow_y += chh
            else:
                self._layout_node(child, x + cx, y + cy, w, h)
        return w, h

    def _lay_absolute(self, node, x, y, avail_w, avail_h):
        w, h = node["width"], node["height"]
        for child in node.get("children", []):
            cx, cy = self._child_xy(child)
            if cx is None or cy is None:
                raise LayoutError(
                    child.get("node_id"),
                    f"child of absolute container '{node.get('node_id')}' is missing x/y",
                    "Give this child explicit x and y, or use a stack/grid container instead.",
                )
            self._layout_node(child, x + cx, y + cy, w, h)
        return w, h

    def _lay_stack(self, node, x, y, avail_w, avail_h):
        direction = node.get("direction", "vertical")
        gap = node.get("gap", 0)
        align = node.get("align", "start")
        pad_t, pad_r, pad_b, pad_l = _pad(node.get("padding", 0))
        width = node.get("width") or (avail_w if direction == "vertical" else None)
        height = node.get("height")

        children = node.get("children", [])
        sizes: list[tuple[float, float]] = []
        # First pass: intrinsic sizes (laid out at 0,0; repositioned after).
        for child in children:
            cw, chh = self._layout_node(child, 0, 0, avail_w, avail_h)
            sizes.append((cw, chh))

        if direction == "vertical":
            inner_w = (width - pad_l - pad_r) if width else max((s[0] for s in sizes), default=0)
            cursor = y + pad_t
            for child, (cw, chh) in zip(children, sizes):
                cx = {"start": x + pad_l,
                      "center": x + pad_l + (inner_w - cw) / 2,
                      "end": x + width - pad_r - cw if width else x + pad_l + inner_w - cw,
                      "stretch": x + pad_l}[align]
                if align == "stretch":
                    cw = inner_w
                self._reposition(child, cx, cursor, cw, chh)
                cursor += chh + gap
            total_h = (cursor - gap - y) + pad_b if children else pad_t + pad_b
            w = width if width else inner_w + pad_l + pad_r
            h = height if height else total_h
        else:
            inner_h = (height - pad_t - pad_b) if height else max((s[1] for s in sizes), default=0)
            cursor = x + pad_l
            for child, (cw, chh) in zip(children, sizes):
                cy = {"start": y + pad_t,
                      "center": y + pad_t + (inner_h - chh) / 2,
                      "end": y + height - pad_b - chh if height else y + pad_t + inner_h - chh,
                      "stretch": y + pad_t}[align]
                if align == "stretch":
                    chh = inner_h
                self._reposition(child, cursor, cy, cw, chh)
                cursor += cw + gap
            total_w = (cursor - gap - x) + pad_r if children else pad_l + pad_r
            w = width if width else total_w
            h = height if height else inner_h + pad_t + pad_b
        return w, h

    def _lay_grid(self, node, x, y, avail_w, avail_h):
        columns = node.get("columns", 2)
        gap = node.get("gap", 0)
        pad_t, pad_r, pad_b, pad_l = _pad(node.get("padding", 0))
        width = node.get("width") or avail_w
        col_w = (width - pad_l - pad_r - gap * (columns - 1)) / columns
        children = node.get("children", [])
        # Intrinsic sizes first.
        sizes = [self._layout_node(c, 0, 0, col_w, avail_h) for c in children]
        cursor_y = y + pad_t
        i = 0
        while i < len(children):
            row = children[i:i + columns]
            row_sizes = sizes[i:i + columns]
            row_h = max((s[1] for s in row_sizes), default=0)
            for j, (child, (cw, chh)) in enumerate(zip(row, row_sizes)):
                cx = x + pad_l + j * (col_w + gap)
                self._reposition(child, cx, cursor_y, cw, chh)
            cursor_y += row_h + gap
            i += columns
        h = node.get("height") or ((cursor_y - gap - y) + pad_b if children else pad_t + pad_b)
        return width, h

    def _reposition(self, node: dict, x: float, y: float, w: float, h: float) -> None:
        """Move an already-laid-out subtree. WHY needed: stacks/grids must
        measure children before knowing where they go — two-pass layout.
        Children of positioned nodes carry relative offsets, so the whole
        subtree shifts by the delta."""
        dx, dy = x - node["_x"], y - node["_y"]
        if dx == 0 and dy == 0 and w == node["_w"] and h == node["_h"]:
            return
        self._shift(node, dx, dy)
        node["_x"], node["_y"], node["_w"], node["_h"] = _r2(x), _r2(y), _r2(w), _r2(h)
        self.bboxes[node["node_id"]] = {"x": _r2(x), "y": _r2(y),
                                        "width": _r2(w), "height": _r2(h)}

    def _shift(self, node: dict, dx: float, dy: float) -> None:
        node["_x"] = _r2(node["_x"] + dx)
        node["_y"] = _r2(node["_y"] + dy)
        self.bboxes[node["node_id"]] = {"x": node["_x"], "y": node["_y"],
                                        "width": node["_w"], "height": node["_h"]}
        for child in node.get("children", []):
            if "_x" in child:
                self._shift(child, dx, dy)

    # -- leaves ------------------------------------------------------

    def _lay_text(self, node, x, y, avail_w, avail_h):
        width, lines, height = measure_text(
            node.get("text", ""), node.get("font", "DejaVu Sans"),
            node.get("size", 48), node.get("weight", 400),
            node.get("line_height", 1.15), node.get("max_width"),
            node.get("letter_spacing", 0))
        node["_lines"] = lines  # stashed for the SVG emitter
        return width, height

    def _lay_rect(self, node, x, y, avail_w, avail_h):
        return node["width"], node["height"]

    def _lay_circle(self, node, x, y, avail_w, avail_h):
        d = node["r"] * 2
        return d, d

    def _lay_path(self, node, x, y, avail_w, avail_h):
        return node["width"], node["height"]

    def _lay_image(self, node, x, y, avail_w, avail_h):
        return node["width"], node["height"]

    def _lay_chart_bar(self, node, x, y, avail_w, avail_h):
        return node["width"], node["height"]

    def _lay_chart_donut(self, node, x, y, avail_w, avail_h):
        s = node["size"]
        return s, s

    def _lay_badge(self, node, x, y, avail_w, avail_h):
        tw, _, th = measure_text(node.get("text", ""), node.get("font", "DejaVu Sans"),
                                 node.get("size", 30), node.get("weight", 700))
        w = tw + 2 * node.get("padding_x", 28)
        h = th + 2 * node.get("padding_y", 14)
        return w, h

    def _lay_divider(self, node, x, y, avail_w, avail_h):
        return node["width"], max(node.get("stroke_width", 2), 1)

    def _lay_curve(self, node, x, y, avail_w, avail_h):
        return node["width"], node["height"]


# ------------------------------------------------------- SVG emission

def _attrs(**kw) -> str:
    """Serialize attributes in a FIXED order (insertion order of kwargs as
    written at each call site). WHY: attribute order doesn't change rendering,
    but it changes bytes — and byte-stability is the product."""
    parts = []
    for k, v in kw.items():
        if v is None:
            continue
        parts.append(f'{k}="{v}"')
    return " ".join(parts)


def _esc(s: str) -> str:
    return xml_escape(s, {'"': "&quot;"})


class SVGWriter:
    """Walks a resolved tree (nodes carry _x/_y/_w/_h) and emits SVG."""

    def __init__(self):
        self._defs: list[str] = []
        self._clip_n = 0

    def write(self, scene: dict, root: dict) -> str:
        canvas = scene.get("canvas", {})
        w, h = canvas.get("width", 1080), canvas.get("height", 1080)
        body = self._emit(root)
        defs = f"<defs>{''.join(self._defs)}</defs>" if self._defs else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'{_attrs(width=w, height=h, viewBox=f"0 0 {w} {h}")}>'
            f"{defs}{body}</svg>"
        )

    # -- dispatch ----------------------------------------------------

    def _emit(self, node: dict) -> str:
        t = node["type"]
        if t in CONTAINERS:
            inner = "".join(self._emit(c) for c in node.get("children", []))
            bg = ""
            if node.get("fill"):
                bg = (f"<rect {_attrs(x=node['_x'], y=node['_y'], width=node['_w'], height=node['_h'], fill=node['fill'])} />")
            # WHY no transform on the group: children already carry ABSOLUTE
            # canvas coordinates from the resolver. Translating the group too
            # would shift every nested child twice (the classic "everything
            # drifts down-right" bug). Groups are logical structure only.
            return "<g " + _attrs(id=node["node_id"]) + ">" + bg + inner + "</g>"
        # Leaf dispatch. WHY getattr, not a dict: new component types only
        # need a new _emit_<type> method — the dispatch picks it up.
        fn = getattr(self, f"_emit_{t}", self._emit_unknown)
        return fn(node)

    def _emit_unknown(self, node: dict) -> str:
        raise LayoutError(node.get("node_id"),
                          f"no SVG emitter for type '{node.get('type')}'", "")

    # -- leaves ------------------------------------------------------
    # Every emitter reads the resolved _x/_y/_w/_h. Attribute order at each
    # call site is fixed (see _attrs) so bytes are stable.

    def _emit_text(self, node: dict) -> str:
        x0, y0 = node["_x"], node["_y"]
        size = node.get("size", 48)
        # Baseline from real font metrics: first-line ascent below the top
        # of the layout box. WHY metrics, not a magic 0.8*size: different
        # fonts have different ascents; metrics keep every font honest.
        font_file, _, _ = resolve_font(node.get("font", "DejaVu Sans"),
                                       node.get("weight", 400))
        ascent = _pil_font(font_file, max(1, int(round(size)))).getmetrics()[0]
        lh = (node.get("size", 48)) * node.get("line_height", 1.15)
        anchor = node.get("anchor", "start")
        tx = {"start": x0, "middle": x0 + node["_w"] / 2, "end": x0 + node["_w"]}[anchor]
        tspans = "".join(
            f"<tspan {_attrs(x=round(tx, 2), dy=round(lh if i else 0, 2))}>{_esc(line)}</tspan>"
            for i, line in enumerate(node.get("_lines", [node.get("text", "")]))
        )
        return (
            f"<text {_attrs(id=node['node_id'], x=round(tx, 2), y=round(y0 + ascent, 2))} "
            f"{_attrs(**{'font-family': node.get('font', 'DejaVu Sans')})} "
            f"{_attrs(**{'font-size': size, 'font-weight': node.get('weight', 400), 'text-anchor': anchor, 'fill': node.get('fill', '#000000'), 'letter-spacing': node.get('letter_spacing', 0) or None})}>"
            f"{tspans}</text>"
        )

    def _emit_rect(self, node: dict) -> str:
        return (
            f"<rect {_attrs(id=node['node_id'], x=node['_x'], y=node['_y'], width=node['_w'], height=node['_h'], rx=node.get('rx', 0) or None, fill=node['fill'])} "
            f"{_attrs(stroke=node.get('stroke'), **{'stroke-width': node.get('stroke_width', 0) or None}, opacity=node.get('opacity', 1) if node.get('opacity', 1) != 1 else None)} />"
        )

    def _emit_circle(self, node: dict) -> str:
        if node.get("cx") is not None:
            cx, cy = node["_x"] + node["cx"], node["_y"] + node["cy"]
        else:
            cx, cy = node["_x"] + node["r"], node["_y"] + node["r"]
        return (
            f"<circle {_attrs(id=node['node_id'], cx=round(cx, 2), cy=round(cy, 2), r=node['r'], fill=node['fill'])} "
            f"{_attrs(stroke=node.get('stroke'), **{'stroke-width': node.get('stroke_width', 0) or None})} />"
        )

    def _emit_path(self, node: dict) -> str:
        return (
            f"<path {_attrs(id=node['node_id'], transform='translate(%s %s)' % (node['_x'], node['_y']), d=node['d'], fill=node['fill'])} "
            f"{_attrs(stroke=node.get('stroke'), **{'stroke-width': node.get('stroke_width', 0) or None})} />"
        )

    def _emit_image(self, node: dict) -> str:
        src = node["src"]
        clip_id = None
        if node.get("clip") == "circle":
            self._clip_n += 1
            clip_id = f"clip{self._clip_n}"
            cx, cy, r = node["_x"] + node["_w"] / 2, node["_y"] + node["_h"] / 2, min(node["_w"], node["_h"]) / 2
            self._defs.append(
                f"<clipPath id=\"{clip_id}\"><circle {_attrs(cx=round(cx, 2), cy=round(cy, 2), r=round(r, 2))} /></clipPath>")
        elif node.get("clip") == "rounded":
            self._clip_n += 1
            clip_id = f"clip{self._clip_n}"
            self._defs.append(
                f"<clipPath id=\"{clip_id}\"><rect {_attrs(x=node['_x'], y=node['_y'], width=node['_w'], height=node['_h'], rx=32)} /></clipPath>")
        par = "xMidYMid slice" if node.get("fit", "cover") == "cover" else "xMidYMid meet"
        clip_attr = f' clip-path="url(#{clip_id})"' if clip_id else ""
        return (
            f"<image {_attrs(id=node['node_id'], x=node['_x'], y=node['_y'], width=node['_w'], height=node['_h'], href=src)} "
            f"preserveAspectRatio=\"{par}\"{clip_attr} "
            f"{_attrs(opacity=node.get('opacity', 1) if node.get('opacity', 1) != 1 else None)} />"
        )

    def _emit_chart_bar(self, node: dict) -> str:
        data = node["data"]
        x0, y0, w, h = node["_x"], node["_y"], node["_w"], node["_h"]
        label_h = 44
        plot_h = h - label_h
        max_v = max((d["value"] for d in data), default=1) or 1
        n = len(data)
        gap = node.get("gap", 24)
        bw = (w - gap * (n - 1)) / n if n else 0
        parts = []
        for i, d in enumerate(data):
            bh = plot_h * (d["value"] / max_v)
            bx = x0 + i * (bw + gap)
            by = y0 + plot_h - bh
            parts.append(
                f"<rect {_attrs(x=round(bx, 2), y=round(by, 2), width=round(bw, 2), height=round(bh, 2), rx=6, fill=node['bar_fill'])} />")
            parts.append(
                f"<text {_attrs(x=round(bx + bw / 2, 2), y=round(y0 + plot_h + 34, 2), **{'font-family': node.get('font', 'DejaVu Sans')})} "
                f"{_attrs(**{'font-size': node.get('label_size', 28), 'text-anchor': 'middle', 'fill': node.get('label_fill', '#fff')})}>"
                f"{_esc(str(d['label']))}</text>")
        return f"<g {_attrs(id=node['node_id'])}>{''.join(parts)}</g>"

    def _emit_chart_donut(self, node: dict) -> str:
        import math
        data = node["data"]
        x0, y0, s = node["_x"], node["_y"], node["size"]
        cx, cy, r = x0 + s / 2, y0 + s / 2, s / 2
        thick = s * node.get("thickness", 0.35)
        colors = node.get("colors") or ["#B6FF3B", "#00A3FF", "#FF2E9D", "#F7F2E8"]
        total = sum(d["value"] for d in data) or 1
        parts, ang = [], -90.0
        for i, d in enumerate(data):
            frac = d["value"] / total
            a0, a1 = math.radians(ang), math.radians(ang + frac * 360)
            # Donut segment as a stroked arc: simpler and exact — a circle
            # with thick stroke and dasharray proportional to the fraction.
            parts.append(
                f"<circle {_attrs(cx=round(cx, 2), cy=round(cy, 2), r=round(r - thick / 2, 2), fill='none', stroke=colors[i % len(colors)], **{'stroke-width': round(thick, 2), 'stroke-dasharray': f'{round(frac * 100, 2)} {round(100 - frac * 100, 2)}', 'pathLength': 100})} "
                f"transform=\"rotate({round(ang, 2)} {round(cx, 2)} {round(cy, 2)})\" />")
            ang += frac * 360
            a0 = a1
        return f"<g {_attrs(id=node['node_id'])}>{''.join(parts)}</g>"

    def _emit_badge(self, node: dict) -> str:
        x0, y0, w, h = node["_x"], node["_y"], node["_w"], node["_h"]
        font_file, _, _ = resolve_font(node.get("font", "DejaVu Sans"), node.get("weight", 700))
        size_i = max(1, int(round(node.get("size", 30))))
        ascent = _pil_font(font_file, size_i).getmetrics()[0]
        return (
            f"<g {_attrs(id=node['node_id'])}>"
            f"<rect {_attrs(x=x0, y=y0, width=w, height=h, rx=round(h / 2, 2), fill=node['fill'])} />"
            f"<text {_attrs(x=round(x0 + w / 2, 2), y=round(y0 + (h + ascent) / 2 - 2, 2))} "
            f"{_attrs(**{'font-family': node.get('font', 'DejaVu Sans')})} "
            f"{_attrs(**{'font-size': node.get('size', 30), 'font-weight': node.get('weight', 700), 'text-anchor': 'middle', 'fill': node.get('text_fill', '#000')})}>"
            f"{_esc(node.get('text', ''))}</text></g>"
        )

    def _emit_divider(self, node: dict) -> str:
        x0, y0 = node["_x"], node["_y"]
        sw = node.get("stroke_width", 2)
        return (f"<line {_attrs(id=node['node_id'], x1=x0, y1=y0, x2=round(x0 + node['_w'], 2), y2=y0, stroke=node.get('stroke', '#fff'), **{'stroke-width': sw}, opacity=node.get('opacity', 0.25))} />")

    def _emit_curve(self, node: dict) -> str:
        # Decorative bezier band. Bottom band: starts left at y0, quadratic
        # wave to the right edge, closes along the bottom. flip=True mirrors
        # to the top. WHY quadratic (not cubic): one control point = one
        # smooth arch, fully determined by bulge/thickness — fewer knobs,
        # same signature look as the Protograph carousel.
        w, h = node["_w"], node["_h"]
        x0, y0 = node["_x"], node["_y"]
        bulge, thick = node.get("bulge", 0.16), node.get("thickness", 0.13)
        if not node.get("flip"):
            y_top = y0 + h * (1 - bulge - thick)
            y_bot = y0 + h
            ctrl = y0 + h * (1 - thick) - h * bulge * 1.6
            d = (f"M {x0 - 60} {round(y_top, 2)} Q {round(x0 + w / 2, 2)} {round(ctrl, 2)} "
                 f"{round(x0 + w + 60, 2)} {round(y_top + h * bulge * 0.4, 2)} "
                 f"L {round(x0 + w + 60, 2)} {round(y_bot, 2)} L {x0 - 60} {round(y_bot, 2)} Z")
        else:
            y_top = y0
            y_bot = y0 + h * (bulge + thick)
            ctrl = y0 + h * thick + h * bulge * 1.6
            d = (f"M {x0 - 60} {round(y_bot, 2)} Q {round(x0 + w / 2, 2)} {round(ctrl, 2)} "
                 f"{round(x0 + w + 60, 2)} {round(y_bot - h * bulge * 0.4, 2)} "
                 f"L {round(x0 + w + 60, 2)} {round(y_top, 2)} L {x0 - 60} {round(y_top, 2)} Z")
        return (f"<path {_attrs(id=node['node_id'], d=d, fill=node['fill'], opacity=node.get('opacity', 1) if node.get('opacity', 1) != 1 else None)} />")