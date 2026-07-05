"""Deterministic MCP server code generation (the mock/fallback generator).

Given planned tools + function metadata, emit a complete, importable FastMCP
server. Used directly on the mock path and as a safety net if an LLM produces
code that fails validation.

Design choices that keep generated code valid without executing user code:
* ``from __future__ import annotations`` — parameter annotations become strings,
  so exotic/return types referenced in signatures never raise NameError.
* Each tool reuses the original parameter list verbatim (minus self/cls) and
  forwards by keyword, wrapping the call in structured error handling.
"""

from __future__ import annotations

import os
import re
from typing import Any


def module_path_from_file(file_path: str, working_dir: str = "") -> str:
    """Turn 'pkg/sub/mod.py' into 'pkg.sub.mod'."""
    path = file_path
    if working_dir and os.path.isabs(path):
        try:
            path = os.path.relpath(path, working_dir)
        except ValueError:
            pass
    path = path.replace("\\", "/").lstrip("./")
    if path.endswith(".py"):
        path = path[:-3]
    parts = [p for p in path.split("/") if p and p != "__init__"]
    return ".".join(parts)


def _split_top_level(param_str: str) -> list[str]:
    """Split a parameter string on top-level commas (ignoring [], (), {})."""
    parts, depth, buf = [], 0, ""
    for ch in param_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def parse_params(signature: str, param_names: list[str] | None = None) -> tuple[str, str]:
    """Return (param_decl, call_args) for the wrapper.

    param_decl: verbatim params (minus self/cls) for the wrapper signature.
    call_args:  keyword-forwarding args, e.g. "supplier_id=supplier_id".
    Falls back to param_names, then to (**kwargs / **kwargs) passthrough.
    """
    inner = ""
    if signature:
        m = re.search(r"\((.*)\)", signature, re.DOTALL)
        if m:
            inner = m.group(1).strip()

    raw_params = _split_top_level(inner) if inner else []
    decls: list[str] = []
    calls: list[str] = []
    for p in raw_params:
        if not p:
            continue
        # Identify the bare name (before ':' or '=' and after * markers).
        name = re.split(r"[:=]", p, maxsplit=1)[0].strip()
        stars = ""
        while name.startswith("*"):
            stars += "*"
            name = name[1:].strip()
        if name in ("self", "cls"):
            continue
        if name in ("", "/"):  # positional-only marker
            continue
        decls.append(p)
        if stars == "*":
            calls.append(f"*{name}")
        elif stars == "**":
            calls.append(f"**{name}")
        else:
            calls.append(f"{name}={name}")

    if decls:
        return ", ".join(decls), ", ".join(calls)

    # Fallback to declared names without types.
    names = [n for n in (param_names or []) if n not in ("self", "cls")]
    if names:
        return ", ".join(names), ", ".join(f"{n}={n}" for n in names)

    # Last resort: passthrough.
    return "**kwargs", "**kwargs"


def _tool_block(tool: dict[str, Any]) -> str:
    tool_name = tool["tool_name"]
    func_name = tool["function_name"]
    signature = tool.get("signature", "")
    description = (tool.get("description") or f"Call {func_name}.").replace('"""', "'''")
    param_decl, call_args = parse_params(signature, tool.get("param_names"))
    note = ""
    if tool.get("conversion_type") == "requires_wrapper":
        note = (
            "    # NOTE: this function needs a client/connection object. Construct\n"
            "    # it here (e.g. from env vars) before calling if required.\n"
        )
    return (
        f"@mcp.tool()\n"
        f"def {tool_name}({param_decl}) -> dict:\n"
        f'    """{description}"""\n'
        f"{note}"
        f"    try:\n"
        f"        logger.info(\"tool {tool_name} invoked\")\n"
        f"        result = {func_name}({call_args})\n"
        f'        return {{"success": True, "data": result, "error": None}}\n'
        f"    except Exception as exc:  # noqa: BLE001\n"
        f'        logger.exception("{tool_name} failed")\n'
        f'        return {{"success": False, "data": None, "error": str(exc)}}\n'
    )


def generate_server_code(
    server_name: str,
    tools: list[dict[str, Any]],
    working_dir: str = "",
) -> str:
    """Render a full mcp_server.py from planned tools."""
    # Group imports by module.
    imports: dict[str, set[str]] = {}
    for t in tools:
        mod = module_path_from_file(t.get("file_path", ""), working_dir)
        if mod:
            imports.setdefault(mod, set()).add(t["function_name"])

    import_lines = [
        f"from {mod} import {', '.join(sorted(names))}"
        for mod, names in sorted(imports.items())
    ]
    import_block = "\n".join(import_lines) if import_lines else "# (no user imports resolved)"

    tool_blocks = "\n\n".join(_tool_block(t) for t in tools) if tools else (
        '@mcp.tool()\n'
        'def ping() -> dict:\n'
        '    """Health check — no codebase tools were resolved."""\n'
        '    return {"success": True, "data": "pong", "error": None}\n'
    )

    return f'''#!/usr/bin/env python3
"""
{server_name} — MCP server generated by Synapse.

Auto-generated. Exposes selected functions from the codebase as MCP tools so any
MCP-compatible AI host (Claude Desktop, etc.) can call them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional  # noqa: F401

from mcp.server.fastmcp import FastMCP

# ── Imports from your codebase ────────────────────────────────────────────────
{import_block}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("{server_name}")

mcp = FastMCP("{server_name}")


# ── Tools ─────────────────────────────────────────────────────────────────────
{tool_blocks}

if __name__ == "__main__":
    mcp.run()
'''
