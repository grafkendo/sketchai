# Etch — "Etch-A-Sketch for AI" (working title)

A service that lets **AI agents draw** — composing storyboards, slides, and
social graphics from vector components instead of full prompt-to-image renders.

**Thesis:** agents should sketch like draftsmen (vectors + real fonts),
not like painters (pixels + luck). Far less compute, deterministic editing,
real fonts, surgical revisions.

**Model:** open core (MIT) + hosted SaaS. The engine and MCP server are free
for everyone; revenue comes from the managed cloud, pack marketplace, and
enterprise tiers.

## Docs

- [Whitepaper](whitepaper/etch-a-sketch-for-ai.md) — the argument: why agents
  can't draw, the composition-over-generation thesis, architecture, economics,
  and the open-core model.
- [Service spec](specs/sketch-service-spec.md) — API surface (`sketch.compose` /
  `sketch.edit` / `sketch.sequence`), component model, brand-token enforcement,
  deterministic edit/re-render loop, metering, risks.
- [Roadmap](ROADMAP.md) — phased build plan: spike → MVP API → MCP-native →
  storyboards/packs/billing → distribution.
- [Landscape research](research/landscape-report.md) — market and competitive
  research behind the spec.

## Status

Spec + research + whitepaper complete (Oct 2026). **No code yet** —
implementation starts on the author's go-ahead. Open questions (name, build
surface, photoreal bridge, first demo vertical) are listed in the spec §11.

## Also parked (not dropped)

- MCP trust/verification layer for the noisy server registry
- Agent payments/billing rails for marketplaces
