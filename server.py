"""Entry point for running the HappyCowler MCP server.

Usage:
    python server.py          # run over stdio (for Claude Desktop / MCP clients)
    mcp dev server.py         # run with MCP inspector for testing
"""
from happycowler.mcp_server import mcp

if __name__ == "__main__":
    mcp.run()
