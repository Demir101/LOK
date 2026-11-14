import pytest

from lok.domain.dependency_graph import DependencyGraph, GraphValidationError


def build():
    return DependencyGraph.build(
        ["deadline", "reminder", "milestone", "review", "budget"],
        [
            ("deadline", "reminder", "2 days before"),
            ("deadline", "milestone"),
            ("milestone", "review"),
        ],
    )


def test_valid_directed_graph():
    graph = build()
    assert graph.edges == [("deadline", "reminder"), ("deadline", "milestone"), ("milestone", "review")]
    assert graph.explanation("deadline", "reminder") == "2 days before"


def test_multiple_and_transitive_dependencies():
    graph = build()
    assert graph.direct_dependents("deadline") == ["reminder", "milestone"]
    assert graph.dependents("deadline") == ["reminder", "milestone", "review"]
    assert graph.direct_prerequisites("review") == ["milestone"]
    assert graph.unaffected_by(["deadline"]) == ["budget"]


def test_direction_matters():
    graph = build()
    assert graph.dependents("reminder") == []
    assert "deadline" not in graph.dependents("review")


def test_missing_nodes_rejected():
    with pytest.raises(GraphValidationError, match="not a known fact"):
        DependencyGraph.build(["a"], [("a", "ghost")])


def test_duplicate_nodes_and_edges_rejected():
    with pytest.raises(GraphValidationError, match="Duplicate node"):
        DependencyGraph.build(["a", "a"], [])
    with pytest.raises(GraphValidationError, match="Duplicate dependency"):
        DependencyGraph.build(["a", "b"], [("a", "b"), ("a", "b")])


def test_self_loop_rejected():
    with pytest.raises(GraphValidationError, match="itself"):
        DependencyGraph.build(["a"], [("a", "a")])


def test_circular_dependency_detected_on_build():
    with pytest.raises(GraphValidationError, match="Circular dependency"):
        DependencyGraph.build(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])


def test_find_cycle_returns_path():
    graph = DependencyGraph.build(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")], allow_cycles=True)
    cycle = graph.find_cycle()
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}


def test_add_edge_creating_cycle_is_rolled_back():
    graph = build()
    with pytest.raises(GraphValidationError):
        graph.add_edge("review", "deadline")
    assert ("review", "deadline") not in graph.edges
    assert graph.find_cycle() is None


def test_remove_edge():
    graph = build()
    graph.remove_edge("deadline", "reminder")
    assert graph.dependents("deadline") == ["milestone", "review"]
    with pytest.raises(GraphValidationError):
        graph.remove_edge("deadline", "reminder")


def test_topological_order():
    order = build().topological_order()
    assert order.index("deadline") < order.index("milestone") < order.index("review")


def test_serialization_round_trip():
    graph = build()
    restored = DependencyGraph.from_dict(graph.to_dict())
    assert restored.nodes == graph.nodes
    assert restored.edges == graph.edges
    assert restored.explanation("deadline", "reminder") == "2 days before"


def test_malformed_graph_data():
    with pytest.raises(GraphValidationError):
        DependencyGraph.from_dict({"nodes": ["a"]})


def test_dot_output_contains_direction_and_labels():
    dot = build().to_dot(labels={"deadline": 'Project "deadline"'}, highlight=["deadline"])
    assert '"deadline" -> "reminder";' in dot
    assert 'Project \\"deadline\\"' in dot
    assert dot.startswith("digraph")
