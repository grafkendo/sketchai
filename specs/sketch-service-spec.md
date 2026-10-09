# Etch-A-Sketch for AI — Product Spec (v0.1)

**Status:** spec only — no code, per Mitchel's instruction (2026-10-09)
**Workstream:** Agent Tools Lab · **Direction:** 1 of 3 (sketch service)
**Parked (not dropped):** direction 2 (MCP trust/verification layer), direction 3 (agent payments/billing) — research later, on Mitchel's word
**Research basis:** `../research/landscape-report.md` (2026-10-08)

---

## 1. What it is

A managed service that lets AI agents produce visual content — storyboards, slide decks, social graphics, diagrams, thumbnails — by **programmatically assembling vector components** instead of running diffusion image generation.

The agent doesn't describe a picture in prose and hope. It calls tools to compose a scene graph from typed components (text, shapes, image slots, charts, frames), applies brand tokens, and gets back a deterministic render. Edits are surgical: change a node, re-render, same hash if nothing changed.

The one-line thesis: **agents should sketch like draftsmen (vectors + real fonts), not like painters (pixels + luck).**

### Candidate names (pick later)
- **Etch** (short, owns the seed metaphor)
- **Sketchboard**
- **Vexel** (vector + pixel)
- **Compositor**

---

## 2. Who it's for

Agents and the people who ship them — never a human design tool with an "agent mode" bolted on.

| Customer | They use it for | Why they pay |
|---|---|---|
| Agent framework devs (LangGraph, Mastra, ADK builders) | In-pipeline visual generation: reports, decks, carousels | Determinism + text accuracy they can't get from diffusion |
| Marketing/content automation shops | Social carousels, thumbnails, ad variants at scale | Cost: cents of vector render vs. dollars of diffusion lottery |
| AI media / influencer producers | Character-consistent storyboards and scene previews | Reuse of asset + token libraries across renders |
| Harnesses & marketplaces (later) | A built-in "draw" capability for their agents | Usage-based distribution |

The buyer is a developer or a platform. The *user* is an agent. Every design decision below optimizes for the agent's ergonomics: token-cheap schemas, strict validation with useful errors, idempotent calls.

---

## 3. The problem (why this wins)

From the landscape research, the pain is documented through 2026:

1. **Diffusion garbles text** — Adobe filed a two-pass text-attention patent (published Sept 2026) because this is still unsolved. Agents need real fonts, not learned glyph approximations.
2. **Regeneration is a lottery** — fix one typo and the whole image changes. No professional workflow survives that.
3. **No surgical edit loop** — current tools render once; there is no "change the headline on slide 3 and keep everything else byte-identical."
4. **Existing deterministic options each miss the mark:**
   - Bannerbear / Placid / Templated — template *fill*. The agent can't compose; it can only pour text into someone else's layout.
   - Satori — a library, not a service. Cards only, no hosted render, no brand enforcement, no MCP surface.
   - Screenshot APIs — need human-authored HTML. Agents writing raw HTML/CSS for pixel output is the worst of both worlds.
   - Mermaid / diagram-as-code — diagrams only, ugly by default, no brand story.

**The empty space:** agent-composable vector assembly as a managed service, with brand enforcement and sequencing.

---

## 4. API surface

Two surfaces, one engine. MCP first (that's where agents live), REST for everything else.

### MCP tools (primary)

| Tool | Agent calls with | Gets back |
|---|---|---|
| `sketch.compose` | `components[]` (scene graph), `canvas` (size/format), optional `brand_id` | `render_id`, `svg_url`, `png_url`, `content_hash`, per-node bounding boxes |
| `sketch.edit` | `render_id` + `patch[]` (JSON-patch-style ops on named nodes) | New `render_id`, new hash, diff summary (what changed) |
| `sketch.sequence` | Array of scenes → storyboard; per-scene transitions/notes | `storyboard_id`, per-scene renders, a single contact-sheet PNG |
| `components.list` | Filter by type/tag | Typed component catalog with schemas (token-cheap: names + params, not full SVG) |
| `brand.apply` / `brand.validate` | `brand_id` or inline tokens | Validation report: pass/fail per rule, offending nodes |
| `assets.upload` | Image bytes or URL | `asset_id` for use in image slots |
| `fonts.list` | — | Available real fonts (licensed/hosted server-side — agent never touches font files) |

### Design rules for agent ergonomics
- **Token-cheap schemas.** The registry's documented problem: MCP schemas cost ~12× vs. hardcoded functions. Component schemas must be tight — enums over free text, defaults everywhere, examples in descriptions.
- **Strict validation, useful errors.** A bad compose call returns *which node failed and why*, plus a suggested fix — never a silent fallback render. Agents iterate on errors; make the errors teach.
- **Idempotent renders.** Same scene graph + same brand = same `content_hash`. Agents can cache aggressively and diff cheaply.
- **Named nodes everywhere.** Every component instance gets a stable `node_id` so `sketch.edit` can target "headline-slide-3" without resending the world.

### REST (secondary)
`POST /v1/renders`, `PATCH /v1/renders/{id}`, `POST /v1/storyboards`, `GET /v1/components`, `POST /v1/brands/validate` — same semantics, for pipelines and non-MCP agents.

---

## 5. Component model

The compositional primitive set. Small on purpose — composition beats catalog size.

**Layout containers:** `frame`, `stack` (vertical/horizontal flow), `grid`, `absolute` (escape hatch, x/y)
**Content:** `text` (real font, real shaping), `shape` (rect/circle/path with fill/stroke/gradient), `image` (asset slot with fit/crop/clip), `chart` (bar/line/donut from data arrays — agents love this), `badge`, `divider`, `curve` (decorative bezier band — the Protograph carousel proved agents want these)
**Decor:** `shadow`, `gradient`, `clip` (circle/rounded-rect masks)

**Layout philosophy: constraints over coordinates.** Agents are bad at absolute positioning (they can't *see*). Default to flow layout with alignment/gap/padding; `absolute` exists but is discouraged in docs. The renderer resolves constraints deterministically — same input, same pixels, every time.

**Scene graph:** a JSON tree. Rendered server-side to SVG (source of truth), then rasterized to PNG/PDF on demand. SVG stays editable; PNG is the delivery format. This mirrors the proven Protograph pipeline (SVG + real type → cairosvg rasterize), which beat diffusion on speed, cost, and text accuracy in production.

**Component packs (later):** versioned, shareable packs — e.g. a "carousel pack" with 6 slide layouts, an "origami accent pack." Packs are how the marketplace story starts.

---

## 6. Brand-token enforcement

The moat candidate. Templates don't do this; libraries can't do this as a service.

- A **brand** = tokens: `colors.*` (exact hexes), `fonts.display` / `fonts.body`, `spacing.*`, `radius`, plus rules ("headlines always Bricolage Grotesk 800", "never use pure black", "origami accents: inanimate objects only").
- Tokens are resolved **at render time**, not baked into components. Swap `brand_id` → whole deck re-skins deterministically.
- `brand.validate` runs pre-render: every node checked against the token set. Violations return as structured errors with the offending node and the rule broken. Strict mode blocks render; warn mode annotates.
- **Character/asset consistency** follows the character-bible pattern (proven 2026-10-08): named asset sets pinned per brand — "Nova always = blue bob + lime streak, these exact asset IDs" — so agents can't drift a character across a storyboard.

This is what turns the tool from "SVG generator" into "brand-safe design automation." Agencies and media companies pay for the second one.

---

## 7. Deterministic edit / re-render loop

The workflow that diffusion can never offer:

1. Agent composes → gets `render_id` + `content_hash`.
2. Human (or agent reviewer) says "make the headline bigger, swap slide 2's accent to magenta."
3. Agent calls `sketch.edit` with two patch ops → new render, new hash, **diff summary** confirming only those nodes changed.
4. Repeat. Every version is addressable; any version re-renders byte-identically.

No lottery. No "the whole image changed." This is the feature you demo.

---

## 8. Metering & billing

Follow the market norm from the research: **usage-based metering + free tier**, not per-seat.

- **Meter:** per render (SVG = 1 credit; PNG/PDF export = +1; storyboard scene = per scene). Edits that change nothing (hash match) are free — encourages iteration.
- **Free tier:** ~500 renders/mo — enough for a dev to fall in love, not enough to run production.
- **Tiers:** Hobby ($19/mo, 5K renders), Pro ($99/mo, 50K renders + brand packs + priority render), Scale (custom, SLA, dedicated font/asset hosting, SSO).
- **Overage:** flat per-1K renders, published. No surprise bills — agents spending autonomously is a trust issue; hard caps + alerts are a feature.
- **Later:** take-rate on component-pack marketplace (70/30 to pack authors, mirroring the missing marketplace cash-register gap).

---

## 9. Phased build plan (MVP first)

**Phase 0 — Spike (1–2 days):** harden the Protograph carousel builder into a parameterized CLI: components as functions, brand tokens as a JSON file, `compose → SVG → PNG`. Proves the engine shape. Throwaway-friendly.

**Phase 1 — MVP API (2–3 weeks):** render service (FastAPI) + component model (10 core components) + SVG/PNG output + `compose`/`edit` with content hashing. One demo: "agent builds a 6-slide carousel from a prompt, then edits slide 3." No auth beyond API keys, no billing — meter in logs.

**Phase 2 — Agent-native (2–3 weeks):** MCP server exposing the tool surface; `brand.apply`/`brand.validate`; asset upload; font library (start with open fonts: Bricolage Grotesk, Hanken Grotesk, Inter, etc.). Publish to Smithery + official registry. Docs written for agents (tight schemas, error-driven iteration examples).

**Phase 3 — Storyboards & packs (3–4 weeks):** `sketch.sequence`, chart components, component packs v1, brand rule engine (custom rules, not just tokens). Stripe metering + tiers live.

**Phase 4 — Distribution (ongoing):** OpenAI/AWS marketplace listings when their billing layers mature; harness partnerships (a "draw" tool inside coding agents); pack marketplace with revenue share.

**Deliberately out of scope:** photoreal generation (diffusion's job — integrate as an *image-slot source*, don't compete), video, real-time collaboration, a human design UI beyond a minimal preview/debug page.

---

## 10. Risks from the research — and the spec's answers

| Risk | Answer in this spec |
|---|---|
| **Photoreal ceiling** — this never replaces diffusion for photographic imagery | Don't compete: `image` slots accept diffusion/AI-generated assets as *inputs*. Position as "the layout and type layer agents are missing," composable with image gen, not a replacement. |
| **Someone wraps Satori as a service** | Satori covers cards, not composition/sequencing/brand enforcement. The moat is the *system* (components + tokens + edit loop + MCP ergonomics), not the renderer. Move fast on Phase 2 distribution. |
| **Margin compression** as primitives commoditize | Brand enforcement + packs + character consistency are the durable layer — workflow lock-in, not render-price competition. Metered pricing with a free tier matches market norms; compete on the system, not per-render cost. |
| **Noisy MCP registry** (53.9/100 avg trust) | Ship with verification in mind: signed renders, content hashes, public validation reports. Be the trustworthy server in a sketchy registry — it becomes a selling point. |
| **Agents can't do layout** (they can't see) | Constraints-over-coordinates (§5), tight schemas, error messages that teach (§4). Plus: every render returns bounding boxes so agents can *reason* about layout programmatically. |

---

## 11. Open questions (for Mitchel)

1. **Name** — Etch / Sketchboard / Vexel / Compositor, or something else?
2. **Build surface** — local-first on the RTX 5070 box, or cloud API from day one? (Cloud = revenue; local = zero marginal cost while iterating.)
3. **Photoreal bridge** — in MVP, should `image` slots call a diffusion API under the hood (Higgsfield/Veo), or stay pure-vector until Phase 2?
4. **First demo vertical** — social carousels (proven), slide decks, or YouTube thumbnails?

---

*End of spec v0.1 — awaiting Mitchel's direction before any build.*
