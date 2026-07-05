"""A tiny state-graph runner mirroring the doc's LangGraph pipeline.

Deliberately dependency-free: nodes are ``(state) -> state`` callables, edges are
either a fixed next-node name or a conditional router ``(state) -> name``. This
keeps the POC self-contained while matching the LangGraph shape 1:1, so it can be
swapped for real LangGraph later with the same node functions.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

START = "__start__"
END = "__end__"

Node = Callable[[object], object]
Router = Callable[[object], str]


class StateGraph:
    def __init__(self) -> None:
        self._nodes: Dict[str, Node] = {}
        self._edges: Dict[str, str] = {}
        self._routers: Dict[str, Router] = {}
        self._entry: Optional[str] = None

    def add_node(self, name: str, fn: Node) -> "StateGraph":
        self._nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self._edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router: Router) -> "StateGraph":
        self._routers[src] = router
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self._entry = name
        return self

    def run(self, state: object, max_steps: int = 50) -> object:
        if self._entry is None:
            raise ValueError("graph has no entry node")
        current = self._entry
        steps = 0
        while current != END:
            if steps >= max_steps:
                raise RuntimeError("graph exceeded max_steps (possible cycle)")
            steps += 1
            node = self._nodes.get(current)
            if node is None:
                raise KeyError(f"unknown node: {current}")
            state = node(state)
            if current in self._routers:
                current = self._routers[current](state)
            elif current in self._edges:
                current = self._edges[current]
            else:
                current = END
        return state
