"""Assemble and run the build graph.

    search → planner → generator → validator ─(valid?)─> complete
                           ▲                    │
                           └──────── fix ◀──────┘ (if invalid & attempts left)

``run_build`` builds the graph, runs it against a BuildState, and returns a
result dict shaped for the gRPC ``BuildResult`` message.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from synapse_backend.agents.graph import END, StateGraph
from synapse_backend.agents.nodes import (
    complete_node,
    fix_node,
    generator_node,
    planner_node,
    search_node,
    validator_node,
)
from synapse_backend.agents.state import BuildState

logger = logging.getLogger(__name__)


def _server_name_from(output_file: str, query: str) -> str:
    base = re.sub(r"\.py$", "", output_file or "generated_mcp")
    base = re.sub(r"[^0-9a-zA-Z_]", "_", base).strip("_") or "generated_mcp"
    return base


def build_graph() -> StateGraph:
    g = StateGraph()
    g.add_node("search", search_node)
    g.add_node("planner", planner_node)
    g.add_node("generator", generator_node)
    g.add_node("validator", validator_node)
    g.add_node("fix", fix_node)
    g.add_node("complete", complete_node)

    g.set_entry("search")
    g.add_edge("search", "planner")

    # Planner may short-circuit to complete on insufficient context.
    g.add_conditional_edges(
        "planner",
        lambda s: "complete" if s.error_code == "insufficient_context" else "generator",
    )
    g.add_edge("generator", "validator")

    # validator → complete if valid or out of attempts, else → fix → validator.
    g.add_conditional_edges(
        "validator",
        lambda s: "complete"
        if (s.valid or s.fix_attempts >= s.max_fix_attempts)
        else "fix",
    )
    g.add_edge("fix", "validator")
    g.add_edge("complete", END)
    return g


def run_build(
    *,
    query: str,
    project_schema: str,
    working_dir: str,
    output_file: str = "mcp_server.py",
    context_bundle: Optional[dict[str, Any]] = None,
    generate_only: bool = False,
    todo_list_content: str = "",
    emit: Optional[Callable[..., None]] = None,
    call_tool: Optional[Callable[[str, dict], dict]] = None,
) -> dict[str, Any]:
    """Run the agentic build pipeline and return a BuildResult-shaped dict."""
    state = BuildState(
        query=query,
        project_schema=project_schema,
        working_dir=working_dir,
        output_file=output_file,
        context_bundle=context_bundle or {},
        generate_only=generate_only,
        todo_list_content=todo_list_content,
        server_name=_server_name_from(output_file, query),
        emit=emit,
        call_tool=call_tool,
    )

    if emit:
        emit("initializing", "Initializing build pipeline", 0.05, "orchestrator", "")

    try:
        state = build_graph().run(state)  # type: ignore[assignment]
    except Exception as exc:  # noqa: BLE001
        logger.exception("build graph crashed")
        return {
            "success": False,
            "server_code": "",
            "tool_count": 0,
            "resource_count": 0,
            "documentation": "",
            "todo_list": "",
            "error": str(exc),
        }

    if state.error_code == "insufficient_context":
        return {
            "success": False,
            "server_code": "",
            "tool_count": 0,
            "resource_count": 0,
            "documentation": "",
            "todo_list": state.todo_list,
            "error": "insufficient_context",
        }

    return {
        "success": state.success,
        "server_code": state.server_code,
        "tool_count": state.tool_count,
        "resource_count": state.resource_count,
        "documentation": state.documentation,
        "todo_list": state.todo_list,
        "error": state.error,
    }
