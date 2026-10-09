# Agent Tools Lab — Landscape Research Report

**Date:** 2026-10-08 · **Research only — no build decisions made**
**Purpose:** Map the agent-tooling landscape and assess Mitchel's "Etch-A-Sketch for AI" concept against it.
**Method:** Four parallel research tracks (web research, primary sources preferred). Funding numbers and market figures are dated; unverified items are flagged. Sources listed per section.

---

## Executive Summary

1. **MCP is the settled agent→tool standard.** Anthropic donated MCP to the Linux Foundation's Agentic AI Foundation (Dec 2025); Google's A2A protocol joined the same foundation (Aug 2026). Anthropic cites 10,000+ active public servers and 97M+ monthly SDK downloads (Dec 2025).
2. **Frameworks are open-source loss leaders** (LangGraph, CrewAI, OpenAI Agents SDK, Google ADK); revenue sits in runtime, observability, and model/API consumption. Frameworks are a *distribution surface*, not the product.
3. **The harnesses have the users and the money:** Claude Code ~$2.5B run-rate (Anthropic, Feb 2026), Cursor ~$2B annualized run-rate (Feb 2026), GitHub Copilot 50M users (Microsoft, Jul 2026).
4. **Agent marketplaces just opened** (OpenAI Marketplace and AWS Marketplace for AI agents, both 2026) — but neither has a mature billing/revenue-share layer yet. That missing cash register is itself an opportunity.
5. **"Tools for agents" is now a mainstream VC thesis**, not a niche. The biggest 2025–26 checks went to compute and data layers (Modal $355M, Exa $250M, Parallel $100M); strategic acquirers are entering (Nebius bought Tavily for up to $400M, Feb 2026).
6. **Usage-based metering dominates pricing** (credits, per-request, browser-hours, compute-seconds), nearly always paired with a free tier; per-seat pricing is fading except legacy iPaaS.
7. **For visuals, agents' deterministic tooling today = diagram-as-code (Mermaid), Satori (a library, not a service), template-fill image APIs (Bannerbear/Placid), and screenshot APIs.** None offers agent-composable vector assembly as a managed service.
8. **The core pain is real and still unsolved in 2026:** diffusion models garble text (Adobe filed a two-pass text-attention patent, published Sept 2026), regeneration is a non-deterministic lottery, and there is no surgical edit loop.
9. **Market sizing is honest but fuzzy:** agent tooling/infra ≈ $2.5–3.3B in 2025 (IDC "agentic AI platforms" + independent top-down models); the broader AI-agents market ≈ $7.6–7.8B (MarketsandMarkets, Grand View). Every analyst defines the category differently — quote numbers only with their definitions attached.
10. **Open gaps worth noting:** verified/trust-scored MCP servers (avg trust score 53.9/100), agent-native payments/billing rails (x402/AP2 live but immature), and a compositional vector-sketch service with brand-token enforcement and storyboard sequencing — the Etch-A-Sketch territory.

---

## Track A — Agent Tooling & Infrastructure Landscape

### MCP ecosystem
- **Protocol:** Open JSON-RPC 2.0, released by Anthropic Nov 2024; current spec 2026-07-28 is a stateless rewrite with OAuth 2.1 for remote servers.
- **Governance:** Donated Dec 9, 2025 to the Agentic AI Foundation (Linux Foundation directed fund), co-founded by Anthropic, Block, and OpenAI. Google's A2A joined AAIF Aug 17, 2026 — MCP (agent→tool) and A2A (agent→agent) now share governance.
- **Scale:** 10,000+ active public servers, 97M+ monthly SDK downloads (Anthropic, Dec 2025). Independent Sep 2026 scrape of the official registry API: ~31K distinct servers (version-inflation adjusted), 23% lacking a source repo. Reference implementation repo ~86K GitHub stars (May 2026). June 2026 trust audit of 4,584 servers: average trust 53.9/100, only 0.08% runtime-verifiable — a real quality gap.
- **Registries (fragmented, no single official marketplace):** official registry (registry.modelcontextprotocol.io, in preview), Anthropic's `claude-plugins-official` + `claude-community` directories, Smithery (~5.6–6K servers, largest third-party), Glama (quality-scored), PulseMCP (curated), mcp.so (widest, noisiest), GitHub's official MCP discovery page, Apify MCP store, Docker MCP Catalog.
- **Commercial models:** the protocol is open; money is in *hosted servers and gateways*. Composio (1,500+ toolkits, 500+ managed MCP servers): free ~100K calls/mo, Pro $29/mo, Business $229/mo. StackOne ($0.003/call) and Truto ($999/connector/year flat) show both usage and flat pricing work. Gateway vendors (Requesty, Executor.sh, TrueFoundry) sell enterprise controls — whitelisting, auth, audit — driven by the documented token overhead problem (one 2026 test: MCP schemas cost 12x vs. hardcoded functions; GitHub MCP server loads 44K tokens vs. 1.4K via CLI).

### Agent frameworks
- **LangGraph/LangChain:** default for production agents; ~34.5M monthly downloads; monetize via LangSmith (~$39/seat/mo) + deployment.
- **CrewAI:** ~44.6K stars, ~5.2M downloads; open source + CrewAI Pro $25/mo.
- **AutoGen (Microsoft):** effectively sunset — maintenance mode, pointing to Microsoft Agent Framework 1.0 (successor to AutoGen + Semantic Kernel).
- **OpenAI Agents SDK:** ~10.3M downloads; free SDK, monetized via OpenAI API usage.
- **Google ADK:** Apache 2.0, ~17.6K stars; monetizes via GCP consumption.
- **Risers:** Mastra (TypeScript, ~21K stars; powers Replit Agent 3), Pydantic AI, Dify (131K stars; cloud $59–159/mo), AWS Strands, Anthropic Claude Agent SDK ("rent Anthropic's harness" as a library).
- **Pattern:** frameworks are open source; revenue in runtime, observability, deployment, model consumption.

### Agent IDEs & harnesses (the demand side)
1. **Claude Code** — leader: 46% "most loved" (Pragmatic Engineer survey, 15K devs, Feb 2026); ~$2.5B run-rate (Anthropic, Feb 2026); 300K+ business customers.
2. **GitHub Copilot** — 50M users (Microsoft, Jul 2026); 4.7M+ paid subscribers (Jan 2026); Pro $10/mo.
3. **Cursor** — $2B annualized run-rate (Feb 2026); Cursor 3 (Apr 2026) added a plugin marketplace.
4. **Devin Desktop (Cognition)** — Google paid $2.4B to license Windsurf tech (2025); Cognition acquired remaining IP ~$250M (Dec 2025).
5. **Google Antigravity** — 2.4M+ weekly active users (Alphabet, Jul 2026).
6. **OpenAI Codex** — bundled in ChatGPT plans (1.2B weekly ChatGPT users).
- Open harnesses (OpenHands, OpenCode, Cline) matter as the install surface for third-party tools — no platform gatekeeper.
- Commercial model: seat subscriptions ($10–40/mo) + usage/credit overage is now universal.

### App stores / marketplaces for agents (the 2026 land grab)
- **OpenAI Marketplace (launched DevDay 2026):** consumer in-conversation app discovery in ChatGPT (4,000+ apps via ChatGPT Apps SDK; 16 launch partners incl. Devin, Notion, Vercel) + enterprise marketplace (30+ launch partners incl. Adobe, Figma, Salesforce). **No revenue-share/billing system announced yet** — discovery live, cash register missing.
- **AWS Marketplace for AI agents & tools:** discover/buy/run pre-built agents and tools on Bedrock AgentCore (Runtime, Memory, Identity, Gateway, Browser, Code Interpreter, Observability). AgentCore Gateway turns APIs into MCP-ready tools. Pay-as-you-go + contracts via AWS billing; AWS put $100M into its Generative AI Innovation Centre for agents.
- Anthropic plugin marketplaces + claude.ai/directory; Cursor plugin marketplace (Apr 2026).

*Track A sources: dev.to MCP registry analysis (Sep 14, 2026) https://dev.to/leroy_jenkins_951c84b2838/i-counted-the-mcp-registry-101219-entries-are-31309-servers-and-23-have-no-source-repo-33a6; digitalapplied.com (May 2026) https://www.digitalapplied.com/blog/mcp-adoption-statistics-2026-model-context-protocol; temperature2.com (Sep 2026) https://temperature2.com/p/2026-09-11-guide-what-is-mcp/; requesty.ai https://requesty.ai/blog/mcp-ecosystem-2026-building-agent-tool-infrastructure-that-scales; secondtalent.com (Sep 2026) https://www.secondtalent.com/resources/ai-coding-assistant-statistics/; techcrunch.com (Sep 29, 2026) https://techcrunch.com/2026/09/29/openais-latest-features-take-direct-aim-at-the-app-store-model/; aws.amazon.com Bedrock AgentCore https://aws.amazon.com/blogs/aws/introducing-amazon-bedrock-agentcore-securely-deploy-and-operate-ai-agents-at-any-scale/*

---

## Track B — Companies Building Tools *for* Agents

### Browser-for-agents
- **Browserbase** — hosted headless browsers ("AWS Lambda for Chrome"); Stagehand + Director. $40M Series B (Jun 2025, Notable Capital; $300M post-money; $67.5M total). Pricing ~$29/$49/$99/mo + $0.10–0.12/browser-hour overage. Customers: Perplexity, Vercel.
- **Steel (Steel.dev)** — open-source browser API for agents; funding unverified (likely unfunded).
- **Anchor Browser** — security-first cloud browser for agents; $6M seed (Oct 2025, Blumberg Capital).
- **Browser Use (browser-use)** — open-source library making pages agent-readable; $17M (Mar 2025, Felicis).

### Sandboxes / compute for agents
- **E2B** — Firecracker-microVM sandboxes, "the cloud designed for AI agents"; $21M Series A (Jul 2025, Insight). Customers: Hugging Face, Perplexity, Groq, Manus.
- **Daytona** — pivoted from dev-workspaces to agent infra (Dec 2024); $24M Series A (Feb 2026, FirstMark; Datadog, Figma Ventures strategic).
- **Modal** — serverless GPU/Python; $87M Series B (Sep 2025, $1.1B) → $355M Series C (May 2026, $4.65B) → ~$750M raise pending at ~$15–16B (Sep 2026). 1B+ sandbox launches.
- **Fly.io** — re-anchored on "computers for agents"; $25M Series D (Jul 2025).
- Also: Restate $20M Series A (Sep 2026, durable execution), Runloop $7M seed, Boxd $2M pre-seed.

### Search / data APIs for agents
- **Exa** — "the search engine for AI"; $85M Series B (Sep 2025, Benchmark) → $250M (May 2026, a16z; **$2.2B valuation**).
- **Tavily** — agentic search; **acquired by Nebius Feb 2026: $275M upfront, up to $400M with earnouts.**
- **Parallel Web Systems** — $100M Series B (Apr 2026, $2B valuation).
- **Firecrawl** — web→LLM-ready data; $14.5M Series A (Aug 2025) → ~$75–82M raise reported (Sep 2026).
- **Seltz** — $12.5M seed (Jun 2026, structured evidence for agents).

### Tool connectivity / universal tool APIs
- **Composio** — 1,000+ apps / 20,000+ tools via unified MCP endpoint; $4M seed + $25M Series A (Jul 2025, Lightspeed; >$1M ARR claimed).
- **Arcade (arcade.dev)** — MCP runtime with per-user identity/OAuth scoping; ~$12M seed (third-party reporting; primary announcement not located).
- **Paragon** — embedded iPaaS pivoting to agents (ActionKit, MCP handlers); $13M Series A (Jul 2022).
- **Nango** — open-source integrations, agent-driven positioning; funding figures conflict across sources (unverified).
- Adjacent: n8n raised to $2.5B valuation (Oct 2025).

### Voice / comms
- **Vapi** — voice-agent platform; $20M Series A (Dec 2024, Bessemer) → $50M Series B (May 2026, Peak XV; $500M val). 1B+ calls handled.
- **Retell AI** — $4.6M seed (Aug 2024); third-party revenue estimates (~$80M ARR) unverified.

### Agent payments
- **Skyfire** — "Visa for AI": agent wallets, spending policies; $8.5M seed (Aug 2024); takes 2–3% of transaction volume.
- Adjacent rails: Coinbase **x402** (HTTP micropayments, USDC; 10,000+ payable endpoints in x402 Bazaar; ~100M agentic transactions on Base in ~9 months per Chainalysis via community repo — not a Chainalysis primary release); Google **AP2** (60+ partners incl. Visa, Mastercard, Stripe, PayPal); AWS Bedrock AgentCore added payments (May 2026, built with Stripe/Privy + Coinbase).

### Where the money flows
Capital concentrates in agent infrastructure, biggest checks to compute and data: Modal ($355M+), Exa ($250M), Parallel ($100M), Baseten ($300M, Feb 2026, $5B — now in talks at $26B). Seed activity hot (Anchor $6M, Seltz $12.5M, Boxd $2M, Restate $20M). Strategic acquirers entering (Nebius→Tavily; Datadog/Figma strategic in Daytona). Security-for-agents is a parallel money magnet (Island, Cyera — $400M each, Oct 2026) but out of scope.
### Pricing
Usage-based metering dominates: credits (Firecrawl, Tavily), per-request (Exa), browser-hours (Browserbase), compute-seconds (Modal), call-minutes (Vapi). Free tier + tiered plans + overages is the norm; agent payments monetize via take-rate (Skyfire 2–3%). Per-seat is fading. One 2026 benchmark: 100K agent searches/mo costs $100–$1,300 across vendors — expect margin compression where primitives commoditize (browsers, search) and durability where scarce (GPU compute, licensed data).

*Track B sources: siliconangle.com funding coverage (2025–26); prnewswire.com E2B Series A; cryptobriefing.com Modal funding; calcalistech.com Tavily acquisition; devtoollab.com search-API pricing benchmark; pul
...[truncated 6601 chars]