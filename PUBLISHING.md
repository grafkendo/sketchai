# Publishing checklist — Etch MCP server

Everything code-side is ready. Every step below needs Mitchel (accounts,
logins, and button-clicks live in his browser — I can't do those for him).

## 0. Prerequisites (do once)

- [ ] Repo is **public** on GitHub (`grafkendo/sketchai`). Registries can't
      ingest a private repo. (Settings → General → Danger Zone → Change visibility.)
- [ ] `main` branch contains: `smithery.yaml`, `server.json`, `Dockerfile`,
      `engine/` (all pushed).

## 1. Smithery (smithery.ai) — one-click installs

1. [ ] Go to **https://smithery.ai/new** and sign in with GitHub.
2. [ ] Paste the repo URL `https://github.com/grafkendo/sketchai` and submit.
     Smithery reads `smithery.yaml` at the repo root (stdio start command,
     no config needed) — the listing should configure itself.
3. [ ] Verify: open the listing, click the install command for Claude Code,
     run it in a terminal, then ask Claude Code to call `components_list`.
     Expected: the 14-component catalog.
4. [ ] ⚠️ If Smithery's intake no longer offers the repo-URL flow (their docs
     have been shifting toward `.mcpb` bundles / Streamable-HTTP for hosted
     servers), fall back to: **Settings → Deployments** in the Smithery
     dashboard, or package an `.mcpb` bundle from this repo. The stdio server
     itself needs no changes.

## 2. Official MCP registry (registry.modelcontextprotocol.io)

Uses `server.json` at the repo root + the `mcp-publisher` CLI.

1. [ ] Install: `brew install mcp-publisher` (or the release tarball from
     `modelcontextprotocol/registry` on GitHub).
2. [ ] **Build + push the Docker image** (the registry entry points at it):
     ```bash
     cd <path-to-sketchai>   # the sketchai repo root
     docker build -t ghcr.io/grafkendo/sketchai-mcp:0.2.0 -t ghcr.io/grafkendo/sketchai-mcp:latest .
     docker push ghcr.io/grafkendo/sketchai-mcp:0.2.0
     docker push ghcr.io/grafkendo/sketchai-mcp:latest
     ```
     (Both tags: `server.json`'s package identifier points at `:latest`;
     its version fields say 0.2.0. Push both or the registry entry 404s.)
     (Needs `docker login ghcr.io` with a classic PAT that has
     `write:packages` scope. Make the package **public** after pushing:
     github.com → your profile → Packages → sketchai-mcp → Package settings.)
3. [ ] From the repo root: `mcp-publisher validate server.json` — fix whatever
     it flags. (`server.json` was written against the documented shape; the
     schema evolves, so treat the validator as truth.)
4. [ ] `mcp-publisher login github` (device flow; grants `io.github.grafkendo/*`).
5. [ ] `mcp-publisher publish` from the repo root.
6. [ ] Verify: `curl "https://registry.modelcontextprotocol.io/v0/servers?search=sketchai"`
     should list `io.github.grafkendo/sketchai`.

## 3. Nice-to-have directories (5 min each, real discovery traffic)

- [ ] **Glama** (glama.ai/mcp/servers → "Add MCP Server"): paste the repo URL,
      claim ownership via the `glama.json` flow on the server page.
- [ ] **mcpservers.org/submit**: name "Etch — vector sketching for agents",
      link the repo, category Development.
- [ ] **PulseMCP** (pulsemcp.com): submit form, same details.

## 4. After publishing — smoke test from a clean machine

On any machine with an MCP client (no repo clone):

1. [ ] Install via the Smithery one-click command (or `docker run -i` + manual config).
2. [ ] Call `fonts_list` → confirm Bricolage Grotesk / Hanken Grotesk resolve
     (they ship inside the image via `engine/fonts/`).
3. [ ] Call `sketch_compose` with the worked example from `engine/MCP.md`.
4. [ ] Call `sketch_edit` on the result → confirm `diff.changed` names only
     the edited node.

## What I deliberately did NOT do

- No accounts created, nothing submitted, no visibility changed — all yours.
- `server.json` references a Docker image tag (`0.2.0`) that doesn't exist
  until you run step 2.2. Don't publish the registry entry before the image.
- The MCP server is **stdio-only**. Smithery *hosted* (cloud) mode and some
  directories prefer Streamable-HTTP — that's Phase 3 work (FastAPI already
  exists; it needs the MCP-over-HTTP transport added).
