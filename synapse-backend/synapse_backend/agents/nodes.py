"""The agent nodes: search → planner → generator → validator → fix → complete.

Each node takes and returns a ``BuildState``. On the mock path the planner and
generator use deterministic logic; with a real LLM they use prompts.py. The
graph wiring lives in pipeline.py.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any

from synapse_backend.agents import prompts
from synapse_backend.agents.codegen import generate_server_code
from synapse_backend.agents.parsing import (
    normalize_fn as _normalize_fn,
    parse_functions_from_bundle,
    parse_functions_from_query,
)
from synapse_backend.agents.state import BuildState
from synapse_backend.llm import LLMMessage, get_llm
from synapse_backend.llm.factory import is_mock
from synapse_backend.vector import qdrant_store

logger = logging.getLogger(__name__)

_MAX_FUNCS = 15


# ── nodes ────────────────────────────────────────────────────────────────────
def search_node(state: BuildState) -> BuildState:
    state.status("planning", "Searching codebase for relevant functions", 0.15,
                 agent_name="search")

    functions = parse_functions_from_bundle(state.context_bundle)
    functions += parse_functions_from_query(state.query)

    # Dedupe by (name, file_path).
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for fn in functions:
        key = (fn["name"], fn["file_path"])
        if fn["name"] and key not in seen:
            seen.add(key)
            unique.append(fn)

    # Semantic re-ranking when we have more than we need (fail-soft).
    if len(unique) > _MAX_FUNCS:
        ns = state.context_bundle.get("working_dir_hash", state.working_dir)
        indexed = qdrant_store.index_functions(unique, namespace=ns)
        if indexed:
            ranked = qdrant_store.search(state.query, namespace=ns, limit=_MAX_FUNCS)
            if ranked:
                unique = [_normalize_fn(r) for r in ranked]
        unique = unique[:_MAX_FUNCS]

    state.functions = unique
    state.status("planning", f"Found {len(unique)} relevant function(s)", 0.3,
                 agent_name="search")
    return state


def _heuristic_plan(state: BuildState) -> dict[str, Any]:
    tools = []
    used: set[str] = set()
    for fn in state.functions:
        base = f"{fn['name']}_tool"
        tool_name = base
        i = 2
        while tool_name in used:
            tool_name = f"{base}{i}"
            i += 1
        used.add(tool_name)
        tools.append(
            {
                "function_name": fn["name"],
                "file_path": fn["file_path"],
                "tool_name": tool_name,
                "signature": fn.get("signature", ""),
                "description": fn.get("docstring", "") or f"Call {fn['name']}.",
                "conversion_type": fn.get("conversion_type", "ready"),
                "param_names": fn.get("param_names", []),
            }
        )
    return {"sufficient_context": bool(tools), "tools": tools, "notes": ""}


def _llm_plan(state: BuildState) -> dict[str, Any]:
    llm = get_llm()
    messages = [
        LLMMessage(role="system", content=prompts.PLANNER_SYSTEM),
        LLMMessage(
            role="user",
            content=prompts.PLANNER_USER.format(
                query=state.query[:8000],
                functions_json=json.dumps(state.functions, indent=2)[:20000],
            ),
        ),
    ]
    data = llm.complete_json(messages)
    if not isinstance(data, dict) or "tools" not in data:
        return _heuristic_plan(state)
    # Ensure tool_name present.
    for t in data.get("tools", []):
        t.setdefault("tool_name", f"{t.get('function_name', 'tool')}_tool")
    data.setdefault("sufficient_context", bool(data.get("tools")))
    return data


def planner_node(state: BuildState) -> BuildState:
    state.status("planning", "Creating MCP tool specifications", 0.4,
                 agent_name="planner")

    plan = _heuristic_plan(state) if is_mock() else _safe(_llm_plan, state,
                                                           _heuristic_plan)
    state.plan = plan

    if not plan.get("sufficient_context") or not plan.get("tools"):
        state.error = "insufficient_context"
        state.error_code = "insufficient_context"
        state.success = False
        return state

    # Render the to-do markdown (the doc's todo_list.md artifact).
    lines = ["# MCP Server Generation Tasks", ""]
    for i, t in enumerate(plan["tools"], 1):
        lines.append(f"- [ ] Task {i}: expose `{t['function_name']}` as "
                     f"`{t['tool_name']}`")
        if t.get("file_path"):
            lines.append(f"  - File: {t['file_path']}")
    state.todo_list = "\n".join(lines)

    state.status("task_list", f"Compiled {len(plan['tools'])} tool task(s)", 0.55,
                 agent_name="planner")
    return state


def generator_node(state: BuildState) -> BuildState:
    state.status("generating", "Generating MCP server code", 0.65,
                 agent_name="generator")
    tools = state.plan.get("tools", [])

    if is_mock():
        code = generate_server_code(state.server_name, tools, state.working_dir)
    else:
        code = _safe_generate(state, tools)

    state.server_code = code
    state.status("generating", "Generated server, validating", 0.8,
                 agent_name="generator")
    return state


def validator_node(state: BuildState) -> BuildState:
    state.status("generating", "Validating generated code", 0.85,
                 agent_name="validator")
    code = state.server_code or ""
    try:
        ast.parse(code)
        compile(code, "<mcp_server>", "exec")
        state.valid = True
        state.validation_error = ""
    except SyntaxError as exc:
        state.valid = False
        state.validation_error = f"{exc.msg} (line {exc.lineno})"

    # Count tools from the source of truth (the code).
    state.tool_count = len(re.findall(r"@mcp\.tool\(\)", code))
    return state


def fix_node(state: BuildState) -> BuildState:
    state.fix_attempts += 1
    state.status("generating",
                 f"Fixing validation issue (attempt {state.fix_attempts})", 0.88,
                 agent_name="fix")
    tools = state.plan.get("tools", [])

    if is_mock():
        # Deterministic generator is always valid — regenerate from the plan.
        state.server_code = generate_server_code(
            state.server_name, tools, state.working_dir
        )
    else:
        fixed = _safe_fix(state)
        # Fall back to the deterministic generator if the LLM can't fix it.
        state.server_code = fixed or generate_server_code(
            state.server_name, tools, state.working_dir
        )
    return state


def complete_node(state: BuildState) -> BuildState:
    if state.error_code == "insufficient_context":
        state.status("complete", "No matching functions found", 1.0)
        return state

    state.success = state.valid
    state.resource_count = 0
    tools = state.plan.get("tools", [])
    doc_lines = [
        f"# {state.server_name}",
        "",
        f"Generated by Synapse. Exposes {state.tool_count} MCP tool(s).",
        "",
        "## Tools",
    ]
    for t in tools:
        doc_lines.append(f"- **{t['tool_name']}** — {t.get('description', '')}")
    doc_lines += [
        "",
        "## Run",
        "```bash",
        "pip install mcp",
        f"python {state.output_file}",
        "```",
    ]
    state.documentation = "\n".join(doc_lines)
    state.status("complete", "MCP server complete", 1.0)
    return state


# ── small resilience helpers ─────────────────────────────────────────────────
def _safe(fn, state, fallback):
    try:
        return fn(state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s failed (%s) — using fallback.", fn.__name__, exc)
        return fallback(state)


def _safe_generate(state: BuildState, tools: list[dict[str, Any]]) -> str:
    try:
        llm = get_llm()
        messages = [
            LLMMessage(role="system", content=prompts.GENERATOR_SYSTEM),
            LLMMessage(
                role="user",
                content=prompts.GENERATOR_USER.format(
                    plan_json=json.dumps(state.plan, indent=2)[:12000],
                    functions_json=json.dumps(state.functions, indent=2)[:12000],
                    server_name=state.server_name,
                ),
            ),
        ]
        code = llm.complete(messages)
        code = _strip_fences(code)
        # Sanity: must at least parse.
        ast.parse(code)
        return code
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM generate failed (%s) — deterministic codegen.", exc)
        return generate_server_code(state.server_name, tools, state.working_dir)


def _safe_fix(state: BuildState) -> str:
    try:
        llm = get_llm()
        messages = [
            LLMMessage(role="system", content=prompts.GENERATOR_SYSTEM),
            LLMMessage(
                role="user",
                content=(
                    "The following MCP server code failed validation with:\n"
                    f"{state.validation_error}\n\n"
                    "Fix it and return ONLY the corrected full Python source:\n\n"
                    f"{state.server_code}"
                ),
            ),
        ]
        code = _strip_fences(llm.complete(messages))
        ast.parse(code)
        return code
    except Exception:  # noqa: BLE001
        return ""


def _strip_fences(code: str) -> str:
    code = code.strip()
    m = re.match(r"^```(?:python)?\s*(.*?)\s*```$", code, re.DOTALL)
    return m.group(1).strip() if m else code
