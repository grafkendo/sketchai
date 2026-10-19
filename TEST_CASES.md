# Etch — hands-on test cases

Paste each prompt into Cursor's agent chat (with the Etch MCP server running).
After each one, check the **Pass if** line.

> Tip: restart the MCP server in Cursor first if it still shows the old 8-tool list — it should show 14 tools now.

## 0. Sanity check (2 min)
**Prompt:** `Use Etch to list the fonts available, and then list all the leaf components.`
**Pass if:** Fonts include Bricolage Grotesque and Hanken Grotesk. Components list returns 14 typed components.

## 1. First compose
**Prompt:** `Use Etch sketch_compose to make a 1080x1080 Protograph slide: dark background, the word HELLO in huge lime display type in the center, and a magenta curve along the bottom. Save the PNG and show me the render_id and content_hash.`
**Pass if:** You get a real PNG, text is perfectly spelled, colors are lime #B6FF3B / magenta #FF2E9D on #171310.

## 2. Surgical edit — the killer feature
**Prompt:** `Now use sketch_edit on that render: change only the headline text to GOODBYE and its color to azure. Tell me which node_ids changed.`
**Pass if:** Diff says ONLY the headline node changed. Background and curve are byte-identical.

## 3. Determinism check
**Prompt:** `Compose the exact same original HELLO scene again, from scratch. Compare the content_hash to the first one.`
**Pass if:** Hashes match exactly. Same input = same output, every time.

## 4. Carousel sequence
**Prompt:** `Use sketch_sequence to make a 3-slide Protograph carousel about "Why agents need sketch tools": slide 1 is the hook, slide 2 is the problem with image generators garbling text, slide 3 is a call to action. Give me the contact sheet.`
**Pass if:** 3 slides + 1 tiled contact-sheet PNG, consistent brand across all slides.

## 5. Brand rule — try to break it
**Prompt:** `Use brand_validate on a scene that puts light grey body text on the paper background color. Do not render it, just validate.`
**Pass if:** Validation FAILS with a contrast violation. Then ask it to fix the color and re-validate — it should pass.

## 6. Component pack
**Prompt:** `List the Etch packs, then use sketch_from_pack to render the hook fragment from carousel-basics with the headline "Stop re-rolling images".`
**Pass if:** Pack lists `hook`, `content`, `cta` fragments, and the hook renders without you building a scene from scratch.

## 7. Batch rendering
**Prompt:** `Use sketch_batch: take a simple quote-card template with a {{name}} and {{quote}} placeholder, and render it for 3 rows: Ada — "Ship it", Grace — "Debug boldly", Alan — "Think clearly".`
**Pass if:** 3 separate PNGs, each with the right name/quote, identical layout.

## 8. Visual diff + animation
**Prompt:** `Take the HELLO and GOODBYE renders and run sketch_diff on them. Then use sketch_animate to turn the carousel from test 4 into a GIF.`
**Pass if:** Diff PNG highlights the changed headline area in red with a % changed figure. GIF animates and is saved under engine/assets/animated/.

## 9. Provenance
**Prompt:** `Get the provenance manifest for the last render and explain each field to me.`
**Pass if:** Manifest shows render_id, content_hash, brand_id, engine_version, and parent lineage if it was an edit. Note: `signed` will be false unless ETCH_SIGNING_KEY is set on the server — that's expected.

## Stretch test
**Prompt:** `Make me a product launch graphic for a fictional coffee brand: warm paper background, big display headline "FIRST LIGHT ROAST", smaller body text underneath, and one azure badge that says NEW. Then change only the badge to magenta and show me the diff.`
**Pass if:** Two renders, clean diff, zero garbled text anywhere.
