# AGENTS.md — CETACEA AI Photo Workbench (phase1)

Hard rules (do not relax, do not weaken tests to pass):
- Source (card) directories are READ-ONLY inputs: never write/delete/rename/chmod there. Open with O_RDONLY|O_NOFOLLOW.
- Never overwrite an existing destination file. Atomic no-overwrite commit only.
- "Verified" means: bytes were re-read from the destination and SHA-256 compared. Size/name/DB history alone never counts.
- Never touch Lightroom .lrcat directly. Never modify existing XMP/ACR sidecars.
- No arbitrary-path, shell, or delete tools exposed through MCP. Tools accept only registered IDs.
- Mock Lightroom output must always carry an explicit MOCK marker. Never claim real-Lightroom or macOS verification.
- No network calls, no API keys, no git push.
- Python 3.13, venv at .venv (`.venv/bin/python -m pytest`). MCP SDK is `mcp` 2.x (use `from mcp.server.mcpserver import MCPServer`; inspect installed package source for the real API).
- Test failures must be recorded honestly (docs/KNOWN_RISKS.md), never hidden.
