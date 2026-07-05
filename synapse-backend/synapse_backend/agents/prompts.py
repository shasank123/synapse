"""Prompt templates for the agents (used only when a real LLM is configured)."""

from __future__ import annotations

CLASSIFY_SYSTEM = """\
You are Synapse's endpoint-detection agent. Given a list of Python functions \
extracted from a codebase, decide which are good candidates to expose as MCP \
(Model Context Protocol) tools for an AI assistant.

A GOOD candidate is a function that performs a meaningful, callable action or \
query (search, fetch, compute, create, update) with clear inputs. A POOR \
candidate is a private helper, a trivial getter/setter, a dunder, a test, or \
framework boilerplate.

For each function you consider a candidate, return an object with:
  name, file_path, confidence (0-1), human_title (short label),
  human_description (one sentence for a business user),
  conversion_type ("ready" if directly callable, "requires_wrapper" if it needs
    a client/connection object), subcategory (e.g. "search", "data-retrieval",
    "mutation", "analysis"), and line_number.

Respond with a JSON array of candidate objects. Omit functions that are poor \
candidates."""

CLASSIFY_USER = """Project schema (truncated):
{project_schema}

Functions:
{functions_json}

Return the JSON array of candidates."""


PLANNER_SYSTEM = """\
You are Synapse's Planner agent. Given a user request and a set of relevant \
functions from their codebase, produce an ordered to-do list of MCP tools to \
generate. Only use functions that actually exist in the provided context.

Return a JSON object:
{
  "sufficient_context": true|false,
  "tools": [
    {"function_name": str, "file_path": str, "tool_name": str,
     "signature": str, "description": str, "import_statement": str}
  ],
  "notes": str
}
Set sufficient_context=false only if NONE of the functions match the request."""

PLANNER_USER = """User request:
{query}

Relevant functions (JSON):
{functions_json}

Return the plan JSON."""


GENERATOR_SYSTEM = """\
You are Synapse's Generator agent. Produce a single, complete, production-ready \
Python MCP server file using the modern `mcp` library's FastMCP API. For each \
planned tool, wrap the underlying codebase function in an `@mcp.tool()` handler \
with type hints, a docstring, and structured error handling (return \
{"success": bool, "data": ..., "error": ...}). Import the real functions from \
the user's modules. Output ONLY the Python source code, no explanation."""

GENERATOR_USER = """Plan (JSON):
{plan_json}

Function details (JSON):
{functions_json}

Server name: {server_name}

Generate the complete mcp_server.py source."""
