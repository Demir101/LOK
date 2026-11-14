"""Directed dependency graph between scenario facts.

An edge ``source -> target`` means *target depends on source*: when the source
fact is corrected, the target fact may need to be updated. Edges are defined
explicitly by the scenario author; LOK never infers them from natural language.

Implemented with the standard library only (adjacency sets + DFS) to avoid an
extra dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class GraphValidationError(ValueError):
    """Raised when a dependency graph is structurally invalid."""


@dataclass
class DependencyGraph:
    """A validated directed acyclic graph of fact IDs."""

    nodes: list[str] = field(default_factory=list)
    _adjacency: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)

    # -- construction -----------------------------------------------------------

    @classmethod
    def build(
        cls,
        nodes: Iterable[str],
        edges: Iterable[tuple[str, str] | tuple[str, str, str]],
        *,
        allow_cycles: bool = False,
    ) -> DependencyGraph:
        """Create a graph. Raises :class:`GraphValidationError` on invalid input."""
        graph = cls()
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            source, target = edge[0], edge[1]
            explanation = edge[2] if len(edge) > 2 else ""  # type: ignore[misc]
            graph.add_edge(source, target, explanation, check_cycle=False)
        if not allow_cycles:
            cycle = graph.find_cycle()
            if cycle:
                raise GraphValidationError(f"Circular dependency: {' -> '.join(cycle)}")
        return graph

    def add_node(self, node: str) -> None:
        if not node or not node.strip():
            raise GraphValidationError("Node IDs must be non-empty.")
        if node in self._adjacency:
            raise GraphValidationError(f"Duplicate node '{node}'.")
        self.nodes.append(node)
        self._adjacency[node] = {}

    def add_edge(self, source: str, target: str, explanation: str = "", *, check_cycle: bool = True) -> None:
        for endpoint, role in ((source, "source"), (target, "target")):
            if endpoint not in self._adjacency:
                raise GraphValidationError(f"Edge {role} '{endpoint}' is not a known fact.")
        if source == target:
            raise GraphValidationError(f"Fact '{source}' cannot depend on itself.")
        if target in self._adjacency[source]:
            raise GraphValidationError(f"Duplicate dependency {source} -> {target}.")
        self._adjacency[source][target] = explanation
        if check_cycle:
            cycle = self.find_cycle()
            if cycle:
                del self._adjacency[source][target]
                raise GraphValidationError(f"Circular dependency: {' -> '.join(cycle)}")

    def remove_edge(self, source: str, target: str) -> None:
        if target not in self._adjacency.get(source, {}):
            raise GraphValidationError(f"No dependency {source} -> {target}.")
        del self._adjacency[source][target]

    # -- queries ----------------------------------------------------------------

    @property
    def edges(self) -> list[tuple[str, str]]:
        return [(source, target) for source in self.nodes for target in self._adjacency[source]]

    def explanation(self, source: str, target: str) -> str:
        return self._adjacency.get(source, {}).get(target, "")

    def direct_dependents(self, node: str) -> list[str]:
        """Facts that directly depend on ``node``."""
        return list(self._adjacency.get(node, {}))

    def direct_prerequisites(self, node: str) -> list[str]:
        """Facts that ``node`` directly depends on."""
        return [source for source in self.nodes if node in self._adjacency[source]]

    def dependents(self, node: str) -> list[str]:
        """All facts transitively affected by a change to ``node`` (BFS order)."""
        seen: list[str] = []
        queue = list(self._adjacency.get(node, {}))
        while queue:
            current = queue.pop(0)
            if current in seen or current == node:
                continue
            seen.append(current)
            queue.extend(self._adjacency.get(current, {}))
        return seen

    def unaffected_by(self, nodes: Iterable[str]) -> list[str]:
        """Facts neither in ``nodes`` nor transitively dependent on them."""
        changed = set(nodes)
        affected = set(changed)
        for node in changed:
            affected.update(self.dependents(node))
        return [node for node in self.nodes if node not in affected]

    def find_cycle(self) -> list[str] | None:
        """Return one cycle as a node path (first node repeated at the end), or ``None``."""
        white, grey, black = 0, 1, 2
        colour = dict.fromkeys(self.nodes, white)
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
            colour[node] = grey
            stack.append(node)
            for nxt in self._adjacency[node]:
                if colour[nxt] == grey:
                    return [*stack[stack.index(nxt) :], nxt]
                if colour[nxt] == white:
                    found = visit(nxt)
                    if found:
                        return found
            stack.pop()
            colour[node] = black
            return None

        for node in self.nodes:
            if colour[node] == white:
                cycle = visit(node)
                if cycle:
                    return cycle
        return None

    def topological_order(self) -> list[str]:
        """Return nodes so that every prerequisite precedes its dependents."""
        if self.find_cycle():
            raise GraphValidationError("A cyclic graph has no topological order.")
        indegree = dict.fromkeys(self.nodes, 0)
        for _, target in self.edges:
            indegree[target] += 1
        ready = [node for node in self.nodes if indegree[node] == 0]
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for target in self._adjacency[node]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        return order

    # -- serialisation and visualisation ----------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": list(self.nodes),
            "edges": [
                {"source": s, "target": t, "explanation": self.explanation(s, t)} for s, t in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DependencyGraph:
        try:
            nodes = [str(node) for node in data["nodes"]]
            edges = [
                (str(e["source"]), str(e["target"]), str(e.get("explanation", ""))) for e in data["edges"]
            ]
        except (KeyError, TypeError) as exc:
            raise GraphValidationError(f"Malformed graph data: {exc}") from exc
        return cls.build(nodes, edges)

    def to_dot(
        self,
        labels: Mapping[str, str] | None = None,
        highlight: Iterable[str] = (),
        affected: Iterable[str] = (),
    ) -> str:
        """Render the graph as Graphviz DOT (displayed with ``st.graphviz_chart``)."""
        labels = labels or {}
        highlight_set, affected_set = set(highlight), set(affected)
        lines = [
            "digraph dependencies {",
            '  rankdir="LR"; bgcolor="transparent";',
            '  node [shape="box", style="rounded,filled", fontname="Helvetica", fontsize="11",'
            ' color="#94A3B8", fillcolor="#F8FAFC", fontcolor="#0F172A", penwidth="1.2"];',
            '  edge [color="#64748B", arrowsize="0.7", fontname="Helvetica", fontsize="9",'
            ' fontcolor="#475569"];',
        ]
        for node in self.nodes:
            label = _dot_escape(labels.get(node, node))
            attrs = [f'label="{label}\\n({_dot_escape(node)})"']
            if node in highlight_set:
                attrs.append('fillcolor="#E0E7FF", color="#3B4FD8", penwidth="2"')
            elif node in affected_set:
                attrs.append('fillcolor="#FEF3C7", color="#B45309"')
            lines.append(f'  "{_dot_escape(node)}" [{", ".join(attrs)}];')
        for source, target in self.edges:
            lines.append(f'  "{_dot_escape(source)}" -> "{_dot_escape(target)}";')
        lines.append("}")
        return "\n".join(lines)


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
