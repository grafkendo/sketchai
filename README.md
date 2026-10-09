# Sketch — AI sketch service (working title)

An "Etch-A-Sketch for AI": a managed, MCP-native service that lets AI agents
compose storyboards, slides, and social graphics from vector components —
instead of full prompt-to-image renders.

Thesis: far less compute, deterministic editing, real fonts, surgical revisions.

## Docs

- [Service spec](specs/sketch-service-spec.md) — API surface (`sketch.compose` /
  `sketch.edit` / `sketch.sequence`), component model, brand-token enforcement,
  deterministic edit/re-render loop, metering, phased plan, risks.
- [Landscape research](research/landscape-report.md) — market and competitive
  research behind the spec.

## Status

Spec phase. No code yet — implementation starts once the open questions in the
spec are resolved.
