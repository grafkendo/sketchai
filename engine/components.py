#!/usr/bin/env python3
"""
Etch engine — components.py

Typed component builders. Each function returns a plain JSON-serializable
node dict: {"type": ..., "node_id": ..., <params>, "children": [...]}.

WHY functions instead of raw dicts: the builders validate required params
up front and raise ComponentError naming the exact node, the reason, and a
suggested fix. Agents iterate on errors, so errors must teach — a silent
fallback render would hide the mistake and waste the agent's next turn.

WHY plain dicts (not classes): the scene graph must survive a round-trip
through JSON (API bodies, stored renders, content hashing). Dicts are the
native language of both agents and HTTP.

Token references: any string param may use "$"-prefixed brand tokens, e.g.
fill="$colors.lime" or font="$fonts.display". Tokens are NOT resolved here —
they resolve at render time (see brands.resolve_tokens), so swapping a brand
re-skins a scene without touching its structure.
"""

from __future__ import annotations

# Every component type the engine knows. Used by render.py for structural
# validation and by api.py for the token-cheap component catalog.
KNOWN_TYPES = {
    "frame", "stack", "grid", "absolute",
    "text", "rect", "circle", "path", "image",
    "chart_bar", "chart_donut", "badge", "divider", "curve",
}

CONTAINERS = {"frame", "stack", "grid", "absolute"}


class EtchError(Exception):
    """Base error. Always carries the failing node_id so callers (API, CLI)
    can report WHICH node failed, WHY, and how to fix it."""

    def __init__(self, node_id: str | None, reason: str, suggestion: str = ""):
        self.node_id = node_id
        self.reason = reason
        self.suggestion = suggestion
        super().__init__(f"node '{node_id}': {reason}" + (f" Suggestion: {suggestion}" if suggestion else ""))

    def to_dict(self) -> dict:
        d = {"node_id": self.node_id, "reason": self.reason}
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


class ComponentError(EtchError):
    pass


def _node(type_: str, node_id: str | None, children: list[dict] | None = None, **params) -> dict:
    """Shared constructor. node_id may be None here — render.compose()
    auto-assigns deterministic IDs in traversal order for raw JSON scenes,
    but the builder functions below require it explicitly (spec: named
    nodes everywhere, so sketch.edit can target them)."""
    if type_ not in KNOWN_TYPES:
        raise ComponentError(
            node_id, f"unknown component type '{type_}'",
            f"Use one of: {sorted(KNOWN_TYPES)}. See GET /v1/components for param schemas.",
        )
    node: dict = {"type": type_, "node_id": node_id}
    node.update(params)
    if type_ in CONTAINERS:
        node["children"] = list(children or [])
    return node


def _require(node_id, params: dict, *names: str) -> None:
    missing = [n for n in names if params.get(n) is None]
    if missing:
        raise ComponentError(
            node_id,
            f"missing required param(s): {', '.join(missing)}",
            f"Add {', '.join(missing)} to this node. Containers auto-size; leaves need explicit dimensions.",
        )


# ---------------------------------------------------------------- containers

def frame(node_id: str, width: float, height: float, children: list[dict] | None = None,
          fill: str | None = None, x: float = 0, y: float = 0,
          padding: float = 0) -> dict:
    """Fixed-size canvas region. Children WITH x/y are placed absolutely;
    children WITHOUT x/y flow vertically from the padding edge. (WHY: frames
    are usually slide-sized; this rule keeps the common case terse while
    staying fully deterministic.)"""
    p = dict(width=width, height=height, x=x, y=y, padding=padding)
    if fill is not None:
        p["fill"] = fill
    _require(node_id, p, "width", "height")
    return _node("frame", node_id, children, **p)


def stack(node_id: str, children: list[dict] | None = None, direction: str = "vertical",
          gap: float = 0, padding: float = 0, align: str = "start",
          width: float | None = None, height: float | None = None,
          x: float | None = None, y: float | None = None) -> dict:
    """Flow layout container — the workhorse. WHY stacks exist: agents can't
    see the canvas, so absolute positioning is guesswork. A stack turns
    'headline, then subline, then badge, 24px apart, centered' into exact
    coordinates deterministically. direction: vertical|horizontal.
    align: start|center|end|stretch (cross-axis)."""
    if direction not in ("vertical", "horizontal"):
        raise ComponentError(node_id, f"direction must be 'vertical' or 'horizontal', got '{direction}'",
                             "Use direction='vertical' for top-to-bottom flow.")
    if align not in ("start", "center", "end", "stretch"):
        raise ComponentError(node_id, f"align must be start|center|end|stretch, got '{align}'", "")
    return _node("stack", node_id, children, direction=direction, gap=gap,
                 padding=padding, align=align, width=width, height=height,
                 x=x, y=y)


def grid(node_id: str, children: list[dict] | None = None, columns: int = 2,
         gap: float = 0, padding: float = 0,
         width: float | None = None, height: float | None = None,
         x: float | None = None, y: float | None = None) -> dict:
    """Even-column grid. Cell width derives from container width; rows size
    to their tallest child. Children flow left-to-right, top-to-bottom."""
    if columns < 1:
        raise ComponentError(node_id, f"columns must be >= 1, got {columns}", "")
    return _node("grid", node_id, children, columns=columns, gap=gap,
                 padding=padding, width=width, height=height, x=x, y=y)


def absolute(node_id: str, width: float, height: float, children: list[dict] | None = None,
             fill: str | None = None) -> dict:
    """Escape hatch: children MUST carry x/y. The layout engine rejects
    children without coordinates here (with a named error) because silent
    (0,0) stacking would pile everything in a corner."""
    p = dict(width=width, height=height)
    if fill is not None:
        p["fill"] = fill
    _require(node_id, p, "width", "height")
    return _node("absolute", node_id, children, **p)


# ------------------------------------------------------------------- leaves

def text(node_id: str, text: str, font: str = "$fonts.display", size: float = 48,
         weight: int = 800, fill: str = "$colors.paper", x: float | None = None,
         y: float | None = None, anchor: str = "start", line_height: float = 1.15,
         max_width: float | None = None, letter_spacing: float = 0) -> dict:
    """Real-font text — the thing diffusion can't do. '\\n' forces line
    breaks; max_width enables greedy word-wrap. Size is auto-measured via
    the actual font file (see layout.measure_text), so stacks can flow
    around text without the agent guessing pixel widths."""
    if anchor not in ("start", "middle", "end"):
        raise ComponentError(node_id, f"anchor must be start|middle|end, got '{anchor}'", "")
    return _node("text", node_id, text=text, font=font, size=size, weight=weight,
                 fill=fill, x=x, y=y, anchor=anchor, line_height=line_height,
                 max_width=max_width, letter_spacing=letter_spacing)


def rect(node_id: str, width: float, height: float, fill: str,
         rx: float = 0, x: float | None = None, y: float | None = None,
         stroke: str | None = None, stroke_width: float = 0,
         opacity: float = 1) -> dict:
    p = dict(width=width, height=height, fill=fill, rx=rx, x=x, y=y,
             stroke=stroke, stroke_width=stroke_width, opacity=opacity)
    _require(node_id, p, "width", "height", "fill")
    return _node("rect", node_id, **p)


def circle(node_id: str, r: float, fill: str, cx: float | None = None,
           cy: float | None = None, x: float | None = None, y: float | None = None,
           stroke: str | None = None, stroke_width: float = 0) -> dict:
    """x/y = top-left of bounding box; cx/cy = center. Provide one pair."""
    p = dict(r=r, fill=fill, cx=cx, cy=cy, x=x, y=y, stroke=stroke, stroke_width=stroke_width)
    _require(node_id, p, "r", "fill")
    return _node("circle", node_id, **p)


def path(node_id: str, d: str, fill: str, width: float, height: float,
         x: float | None = None, y: float | None = None,
         stroke: str | None = None, stroke_width: float = 0) -> dict:
    """Raw SVG path. width/height declare the layout bbox (paths can't be
    measured cheaply); the path data itself is drawn as given."""
    p = dict(d=d, fill=fill, width=width, height=height, x=x, y=y,
             stroke=stroke, stroke_width=stroke_width)
    _require(node_id, p, "d", "fill", "width", "height")
    return _node("path", node_id, **p)


def image(node_id: str, src: str, width: float, height: float,
          x: float | None = None, y: float | None = None,
          fit: str = "cover", clip: str | None = None,
          opacity: float = 1) -> dict:
    """Asset slot. src = local file path (embedded as base64 — deterministic)
    or http(s) URL (passed through as href; never fetched at render time, so
    renders can't change under you). fit: cover|contain. clip: circle|rounded."""
    if fit not in ("cover", "contain"):
        raise ComponentError(node_id, f"fit must be 'cover' or 'contain', got '{fit}'", "")
    p = dict(src=src, width=width, height=height, x=x, y=y, fit=fit,
             clip=clip, opacity=opacity)
    _require(node_id, p, "src", "width", "height")
    return _node("image", node_id, **p)


def chart_bar(node_id: str, data: list[dict], width: float, height: float,
              bar_fill: str = "$colors.lime", label_fill: str = "$colors.paper",
              font: str = "$fonts.body", label_size: float = 28,
              gap: float = 24, x: float | None = None, y: float | None = None) -> dict:
    """data: [{"label": str, "value": number}, ...]. Bars scale to the max
    value; labels sit under each bar. Agents love charts because data is
    already structured — this turns rows into a graphic with zero guessing."""
    if not data:
        raise ComponentError(node_id, "chart_bar needs at least one data point",
                             "Pass data=[{'label': 'Q1', 'value': 42}, ...].")
    return _node("chart_bar", node_id, data=data, width=width, height=height,
                 bar_fill=bar_fill, label_fill=label_fill, font=font,
                 label_size=label_size, gap=gap, x=x, y=y)


def chart_donut(node_id: str, data: list[dict], size: float,
                colors: list[str] | None = None, thickness: float = 0.35,
                x: float | None = None, y: float | None = None) -> dict:
    """data: [{"label": str, "value": number}, ...]. thickness = ring width
    as a fraction of radius."""
    if not data:
        raise ComponentError(node_id, "chart_donut needs at least one data point",
                             "Pass data=[{'label': 'A', 'value': 60}, ...].")
    return _node("chart_donut", node_id, data=data, size=size,
                 colors=colors or [], thickness=thickness, x=x, y=y)


def badge(node_id: str, text: str, fill: str = "$colors.lime",
          text_fill: str = "$colors.bg", font: str = "$fonts.body",
          size: float = 30, weight: int = 700, padding_x: float = 28,
          padding_y: float = 14, x: float | None = None,
          y: float | None = None) -> dict:
    """Pill label. Auto-sizes to the measured text plus padding — the agent
    never computes the pill width itself."""
    return _node("badge", node_id, text=text, fill=fill, text_fill=text_fill,
                 font=font, size=size, weight=weight, padding_x=padding_x,
                 padding_y=padding_y, x=x, y=y)


def divider(node_id: str, width: float, stroke: str = "$colors.paper",
            stroke_width: float = 2, opacity: float = 0.25,
            x: float | None = None, y: float | None = None) -> dict:
    p = dict(width=width, stroke=stroke, stroke_width=stroke_width,
             opacity=opacity, x=x, y=y)
    _require(node_id, p, "width")
    return _node("divider", node_id, **p)


def curve(node_id: str, width: float, height: float, fill: str,
          bulge: float = 0.16, thickness: float = 0.13, flip: bool = False,
          x: float = 0, y: float = 0, opacity: float = 1) -> dict:
    """Decorative bezier band (the Protograph carousel's signature). A smooth
    quadratic wave across the bottom (or top when flip=True). bulge controls
    the wave height as a fraction of height; thickness the band depth."""
    p = dict(width=width, height=height, fill=fill, bulge=bulge,
             thickness=thickness, flip=flip, x=x, y=y, opacity=opacity)
    _require(node_id, p, "width", "height", "fill")
    return _node("curve", node_id, **p)


# ------------------------------------------------------- component catalog
# Token-cheap schema listing for agents (GET /v1/components). Names + params,
# not full SVG — MCP schema bloat is a documented cost problem.

COMPONENT_CATALOG = [
    {"name": "frame", "kind": "container",
     "desc": "Fixed-size region. Children with x/y are absolute; others flow vertically.",
     "params": {"width": "number!", "height": "number!", "fill": "color?", "padding": "number=0"}},
    {"name": "stack", "kind": "container",
     "desc": "Flow layout. Use instead of guessing coordinates.",
     "params": {"direction": "vertical|horizontal=vertical", "gap": "number=0",
                "padding": "number=0", "align": "start|center|end|stretch=start"}},
    {"name": "grid", "kind": "container",
     "desc": "Even columns; rows size to tallest child.",
     "params": {"columns": "int!=2", "gap": "number=0", "padding": "number=0"}},
    {"name": "absolute", "kind": "container",
     "desc": "Escape hatch. Every child MUST carry x/y.",
     "params": {"width": "number!", "height": "number!"}},
    {"name": "text", "kind": "leaf",
     "desc": "Real-font text. \\n breaks lines; max_width wraps.",
     "params": {"text": "string!", "font": "token=$fonts.display", "size": "number=48",
                "weight": "int=800", "fill": "color=$colors.paper", "anchor": "start|middle|end=start"}},
    {"name": "rect", "kind": "leaf",
     "desc": "Rectangle, optional rounded corners.",
     "params": {"width": "number!", "height": "number!", "fill": "color!", "rx": "number=0"}},
    {"name": "circle", "kind": "leaf",
     "desc": "Circle. x/y = bbox top-left, or cx/cy = center.",
     "params": {"r": "number!", "fill": "color!"}},
    {"name": "path", "kind": "leaf",
     "desc": "Raw SVG path. width/height declare the layout bbox.",
     "params": {"d": "string!", "fill": "color!", "width": "number!", "height": "number!"}},
    {"name": "image", "kind": "leaf",
     "desc": "Asset slot. Local path embeds as base64; URL passes through (never fetched).",
     "params": {"src": "path|url!", "width": "number!", "height": "number!", "fit": "cover|contain=cover"}},
    {"name": "chart_bar", "kind": "leaf",
     "desc": "Bar chart from data points.",
     "params": {"data": "[{label,value}]!", "width": "number!", "height": "number!"}},
    {"name": "chart_donut", "kind": "leaf",
     "desc": "Donut chart from data points.",
     "params": {"data": "[{label,value}]!", "size": "number!"}},
    {"name": "badge", "kind": "leaf",
     "desc": "Pill label, auto-sized to its text.",
     "params": {"text": "string!", "fill": "color=$colors.lime"}},
    {"name": "divider", "kind": "leaf",
     "desc": "Horizontal rule.",
     "params": {"width": "number!"}},
    {"name": "curve", "kind": "leaf",
     "desc": "Decorative bezier band across bottom (flip for top).",
     "params": {"width": "number!", "height": "number!", "fill": "color!"}},
]
