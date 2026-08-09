# ADR-0003: MCP over a custom protocol for the Agent Interface

## Status
Accepted

## Context
The platform needs to expose an agent-callable interface (`run_scenario`, `verify_keyboard`,
etc.) usable by multiple, independently-developed AI coding agents — Claude Code, Codex, Gemini
CLI, and future agents — not just one specific tool.

## Decision
Expose the Agent Interface as an MCP (Model Context Protocol) server, using the Python `mcp` SDK.

## Consequences
**Positive:**
- Zero custom protocol design or client-side integration work — any MCP-compatible host already
  knows how to discover and call tools, read schemas, and handle results.
- Directly satisfies the "Claude Code, Codex, Gemini CLI, and future agents" requirement — MCP is
  the emerging cross-vendor standard for exactly this integration point, rather than a
  single-vendor mechanism.
- Tool schemas (input/output types) double as machine-readable documentation for agents — no
  separate API reference needed for basic discoverability (further enhanced by the introspection
  tools in architecture §9).

**Negative:**
- Tied to MCP's request/response tool-call model — no persistent bidirectional streaming beyond
  what MCP itself supports. Acceptable: every tool in our surface (§9) is naturally call/response
  shaped; nothing in the platform's design requires a different interaction model.
- Requires running an MCP server process (stdio or HTTP transport) as part of the deployment story
  for CI or headless use, in addition to the CLI. Acceptable: the CLI (Phase 1) and MCP server
  (Phase 3) share the same core engine — the MCP server is a thin wrapper, not a second
  implementation.

## Alternatives Considered
- **Bespoke REST or gRPC API.** Rejected: every agent host would need custom integration code
  written specifically for this platform, defeating the goal of working with multiple agent tools
  without per-agent glue code.
- **LangChain tool/agent framework integration.** Rejected: couples the interface to one specific
  agent framework rather than a host-agnostic protocol, and doesn't help agents outside that
  ecosystem (e.g. Claude Code, which speaks MCP natively).
