# Roadmap — Etch-A-Sketch for AI

**Model:** open core (MIT) + hosted SaaS. The engine and MCP server are free for
everyone; revenue comes from the managed cloud, pack marketplace, and enterprise.
**Status:** spec + research + whitepaper complete (Oct 2026). Build starts on
Mitchel's go-ahead.

Related docs: [service spec](specs/sketch-service-spec.md) ·
[whitepaper](whitepaper/etch-a-sketch-for-ai.md) ·
[landscape research](research/landscape-report.md)

---

## Phase 0 — Spike (days)

Harden the proven Protograph carousel builder into a parameterized CLI:
components as functions, brand tokens as a JSON file, `compose → SVG → PNG`.
Goal: prove the engine shape. Throwaway-friendly.

**Exit:** one command renders a 6-slide branded carousel from a token file.

## Phase 1 — MVP API (2–3 weeks)

- Render service (FastAPI) + 10 core components
- `compose` / `edit` with content hashing; SVG source of truth, PNG/PDF export
- API-key auth; metering logged but not billed

**Exit / demo:** an agent builds a 6-slide carousel from a prompt, then edits
slide 3 — diff summary confirms only slide 3 changed.

## Phase 2 — Agent-native (2–3 weeks)

- MCP server exposing `sketch.compose` / `sketch.edit` / `sketch.sequence` /
  `components.list` / `brand.apply` / `brand.validate` / `assets.upload`
- Brand-token enforcement + pre-render validation
- Font library (open fonts first: Bricolage Grotesk, Hanken Grotesk, Inter…)
- Publish to Smithery + official MCP registry; agent-oriented docs

**Exit:** any MCP-capable agent can install the server and render on first try.

## Phase 3 — Storyboards, packs & billing (3–4 weeks)

- `sketch.sequence` storyboards, chart components, component packs v1
- Brand rule engine (custom rules, not just tokens)
- Stripe metering live: free tier + Hobby/Pro/Scale (per spec §8)

**Exit:** first paying user; first third-party component pack published.

## Phase 4 — Distribution (ongoing)

- OpenAI / AWS agent marketplace listings (as their billing layers mature)
- Harness partnerships — a built-in "draw" tool inside coding agents
- Pack marketplace with 70/30 revenue share to authors
- Trust program: signed renders, public validation reports, published uptime

**Exit:** the tool ships wherever agents ship.

---

## Open-source / SaaS split

| Open (MIT, in this repo) | Hosted (SaaS, private) |
|---|---|
| Render engine, component model | Metered multi-tenant cloud |
| MCP server + REST API | Brand-pack hosting & font licensing |
| CLI + docs + examples | Pack marketplace + billing |
| Reference component packs | SSO, audit, private assets, SLAs |

## Deliberately out of scope

Photoreal generation (diffusion assets plug in as image slots — we own layout
+ type, not pixels), video, real-time collaboration, a human design UI beyond
a minimal preview/debug page.

## Parked (not dropped)

- **MCP trust/verification layer** — scoring/verification service for the noisy
  registry (avg trust 53.9/100). Research later.
- **Agent payments/billing** — cash-register layer for agent marketplaces.
  Research later.
