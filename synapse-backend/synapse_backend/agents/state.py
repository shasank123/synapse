"""Shared state passed between graph nodes during a build."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class BuildState:
    # ── inputs ───────────────────────────────────────────────────────────────
    query: str = ""
    project_schema: str = ""
    working_dir: str = ""
    output_file: str = "mcp_server.py"
    context_bundle: dict[str, Any] = field(default_factory=dict)
    generate_only: bool = False
    todo_list_content: str = ""
    server_name: str = "generated_mcp"

    # ── working data ─────────────────────────────────────────────────────────
    functions: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    server_code: str = ""
    documentation: str = ""
    todo_list: str = ""

    # ── validation / repair ──────────────────────────────────────────────────
    valid: bool = False
    validation_error: str = ""
    fix_attempts: int = 0
    max_fix_attempts: int = 2

    # ── results ──────────────────────────────────────────────────────────────
    tool_count: int = 0
    resource_count: int = 0
    success: bool = False
    error: str = ""
    error_code: str = ""

    # ── callbacks (wired by the gRPC servicer) ───────────────────────────────
    # emit(stage, message, progress, agent_name, task_name)
    emit: Optional[Callable[..., None]] = None
    # call_tool(tool_name, params) -> dict  (bidirectional tool bridge to CLI)
    call_tool: Optional[Callable[[str, dict], dict]] = None

    def status(
        self,
        stage: str,
        message: str,
        progress: float,
        agent_name: str = "",
        task_name: str = "",
    ) -> None:
        if self.emit:
            self.emit(stage, message, progress, agent_name, task_name)

    def tool(self, name: str, params: dict) -> dict:
        if self.call_tool:
            try:
                return self.call_tool(name, params)
            except Exception as exc:  # noqa: BLE001 - tools are best-effort
                return {"success": False, "error": str(exc)}
        return {"success": False, "error": "no tool bridge"}
