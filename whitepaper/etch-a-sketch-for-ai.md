# Etch-A-Sketch for AI: Deterministic Vector Composition for Autonomous Agents

**A position paper from the Agent Tools Lab**
**Author:** Mitchel — Agent Tools Lab · October 2026
**Status:** Working paper v0.1 — feedback welcome

---

## Abstract

AI agents can write, code, browse, and call APIs — but they cannot draw. When an
agent needs a storyboard, a slide deck, or a social graphic, its only serious
option is a diffusion image model: expensive, non-deterministic, and
notoriously unable to spell. This paper argues for a different primitive:
**programmatic vector composition**. Agents should assemble visuals from typed
components — text set in real fonts, shapes, charts, image slots — inside a
deterministic render pipeline with brand-token enforcement and a surgical
edit/re-render loop. We present the architecture, the economics, and the
open-core model for building it.

---

## 1. The problem: agents can't draw

Give a modern agent a visual task — "make a six-slide carousel announcing our
launch" — and watch what happens. It writes a prompt, calls an image model, and
enters a lottery. The headline renders as "LAUNCHH DAYY." Fix the typo and the
entire image changes: new layout, new colors, new mistakes. There is no "change
slide 3 and keep everything else." Every revision is a full re-roll.

This is not a temporary weakness of today's models. Three properties of
diffusion make it structurally wrong for agent-driven visual work:

1. **Text is approximated, not set.** Diffusion models learn glyph *shapes*;
   they do not lay type. Garbled text remains unsolved in 2026 — Adobe filed a
   two-pass text-attention patent (published September 2026) precisely because
   no one has cracked it. An agent that cannot reliably spell cannot ship
   professional graphics.
2. **Generation is non-deterministic.** Same prompt, different pixels. There is
   no content hash, no diff, no version you can return to. Professional
   workflows — the kind with clients, brands, and legal review — are built on
   determinism.
3. **There is no edit loop.** Diffusion renders are atomic: one in, one out.
   You cannot address "the headline on slide 3" because there is no scene
   graph, only pixels.

The workarounds agents use today each miss the mark:

- **Template-fill APIs** (Bannerbear, Placid) let an agent pour text into
  someone else's layout — but the agent cannot *compose*. Composition is the
  job.
- **Satori** is a library, not a service: cards only, no hosted render, no
  brand enforcement, no agent-native interface.
- **Screenshot APIs** require human-authored HTML. Agents writing raw HTML/CSS
  for pixel output get the worst of both worlds: fragile code and no design
  system.
- **Diagram-as-code** (Mermaid) covers diagrams and little else, with no brand
  story at all.

The gap is precise: **nothing offers agent-composable vector assembly as a
managed service.** That is what this paper proposes to build.

---

## 2. Thesis: composition over generation

The central claim: for the large and growing class of visual work that is
*structured* — decks, storyboards, carousels, thumbnails, reports, diagrams —
agents should work like draftsmen, not painters.

A draftsman assembles: rectangles, type, rules, images placed in frames. Every
element is addressable, every decision is reversible, and the output is
identical every time the same instructions run. A painter generates: pigment on
canvas, beautiful, unrepeatable, uneditable.

Diffusion is a painter. Agents need a draftsman.

This is not a new workflow — it is the workflow every human designer already
uses (Figma, Illustrator, InDesign are all vector composition tools). The
novelty is making it *agent-native*: a service an LLM calls with structured
arguments, validates against, and iterates on programmatically.

Evidence the pattern works in production: the author built a six-slide
Instagram carousel as pure vector graphics (SVG + real brand fonts, exact
hexes, rasterized server-side) in a fraction of the time and cost of diffusion
— with text accuracy diffusion could not achieve. The technique is proven; it
has simply never been productized for agents.

---

## 3. Architecture

### 3.1 The scene graph

Everything is a JSON tree. A render request is a document:

- **Containers:** `frame`, `stack` (flow layout), `grid`, `absolute` (escape hatch)
- **Content:** `text` (real font, real shaping), `shape`, `image` (asset slot),
  `chart` (bar/line/donut from data arrays), `badge`, `divider`, `curve`
- **Decor:** `shadow`, `gradient`, `clip`

Every component instance carries a stable `node_id`, making every element
addressable for later edits.

### 3.2 Constraints over coordinates

Agents are bad at absolute positioning — they cannot *see* the canvas. So the
layout engine resolves **constraints, not coordinates**: flow layout with
alignment, gap, and padding is the default; absolute positioning exists but is
discouraged. The renderer is deterministic: same scene graph, same pixels,
every time. SVG is the source of truth; PNG/PDF are delivery formats
rasterized server-side.

### 3.3 The tool surface

The service speaks MCP natively (the settled agent→tool protocol: 10,000+
public servers, 97M+ monthly SDK downloads) with a REST equivalent:

| Tool | Purpose |
|---|---|
| `sketch.compose` | Scene graph in → render out (`render_id`, URLs, content hash, bounding boxes) |
| `sketch.edit` | JSON-patch ops on named nodes → new render + diff summary |
| `sketch.sequence` | Scenes in → storyboard out (per-scene renders + contact sheet) |
| `components.list` | Token-cheap typed component catalog |
| `brand.apply` / `brand.validate` | Token enforcement and pre-render validation |
| `assets.upload` | Image bytes/URL → addressable asset IDs |

Three design rules govern the surface: **token-cheap schemas** (MCP schema
bloat is a documented ~12× overhead problem — enums over free text, defaults
everywhere), **strict validation with useful errors** (a failed call names the
node and the rule, and suggests the fix — agents iterate on errors, so errors
must teach), and **idempotent renders** (identical input → identical
`content_hash`, enabling aggressive caching).

### 3.4 The edit loop

This is the feature diffusion can never offer:

1. Agent composes → receives `render_id` + `content_hash`.
2. Reviewer (human or agent): "make the headline bigger, swap slide 2's accent
   to magenta."
3. Agent sends two patch ops → new render, new hash, **diff summary**
   confirming only those nodes changed.
4. Repeat. Every version addressable; any version re-renders byte-identically.

---

## 4. Brand tokens: the durable layer

A brand is a token set: exact color hexes, display/body font pairings, spacing
scales, radius values — plus *rules* ("headlines always set in Bricolage
Grotesk 800", "never use pure black"). Tokens resolve **at render time**, not
baked into components: swap the brand ID and an entire deck re-skins
deterministically.

Pre-render validation checks every node against the token set and returns
structured violations. Named asset sets pin character and motif consistency
across renders (a character bible, enforced by software).

Why this matters commercially: templates don't do this, and libraries can't do
it as a service. Brand-safe design automation is what agencies and media
companies pay for. The renderer is a commodity; the *system* — components +
tokens + edit loop + agent ergonomics — is the moat.

---

## 5. Economics

A diffusion render costs on the order of cents to dollars per image — and the
lottery means you pay for five to ship one. A vector render costs a fraction
of a cent of CPU and is right the first time, because the agent specified it
exactly.

Metering follows the market norm for agent infrastructure: **usage-based with a
free tier** — per render, with no-change edits (hash match) free to encourage
iteration. This matches how the entire agent-tooling market prices (credits,
per-request, compute-seconds), and it aligns incentives: the service wins when
agents render more, and agents render more when each render is cheap and
correct.

---

## 6. Open core: how this becomes everyone's tool

Distribution is the strategy. The core — render engine, component model, MCP
server — is **open source (MIT)**. Anyone can self-host; every agent framework
can bundle it; every harness can ship a "draw" capability on day one. Openness
is how a tool becomes infrastructure, and infrastructure is how a name gets
made.

Revenue lives in the hosted layer, following the proven open-core playbook:

- **Hosted cloud** with metering, brand-pack hosting, font licensing, and SLAs
- **Component-pack marketplace** with revenue share to pack authors
- **Enterprise**: SSO, audit, private font/asset hosting, custom SLAs

Open source earns adoption and reputation; the managed service earns revenue.
Neither works as well alone.

---

## 7. Roadmap (summary)

- **Phase 0 — Spike:** parameterize the proven carousel builder into a
  component CLI. Days, throwaway-friendly.
- **Phase 1 — MVP API:** render service + core components + compose/edit with
  content hashing. Demo: agent builds a six-slide carousel, then edits slide 3.
- **Phase 2 — Agent-native:** MCP server, brand validation, asset upload, font
  library. Publish to registries.
- **Phase 3 — Storyboards & packs:** sequencing, charts, component packs,
  brand rule engine, live metering and billing.
- **Phase 4 — Distribution:** marketplace listings, harness partnerships, pack
  marketplace with revenue share.

Deliberately out of scope: photoreal generation (diffusion assets plug in as
image slots — we own the layout and type layer, not the pixels), video,
real-time collaboration.

## 8. Risks, answered honestly

- **Photoreal ceiling.** We never replace diffusion for photographic imagery —
  and we don't try. Diffusion output enters as image-slot *input*.
- **Someone wraps Satori as a service.** Satori covers cards, not composition,
  sequencing, or brand enforcement. The moat is the system, not the renderer.
  Speed of distribution is the defense.
- **Margin compression.** Compete on the system (brand enforcement, packs,
  edit loop), not per-render price. Workflow lock-in outlasts compute pricing.
- **Noisy registries.** Ship as the trustworthy server: signed renders,
  content hashes, public validation. Trust becomes a selling point.

---

## 9. Call to action

If you build agents, try breaking your visual tasks into components instead of
prompts — you'll feel the difference immediately. If you want to help build
the draftsman layer for the agent era, the spec, research, and roadmap are
open, and the conversation is just starting.

*— Mitchel, Agent Tools Lab, October 2026*
