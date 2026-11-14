# Architecture

LOK is a single-process Streamlit application with a strictly layered Python package. Business
logic never lives in UI code, and the domain layer has no dependency on Streamlit or SQLite.

```
app.py (Streamlit entry, navigation)
   │
   ▼
lok/ui/          pages + shared components + session-state helpers
   │  calls
   ▼
lok/services/    use cases: scenarios, evaluations, comparison, import/export, reporting
   │  uses                         │ uses
   ▼                               ▼
lok/storage/     SQLite          lok/domain/   pure logic (models, normalisation,
                 repositories                  assertions, scoring, graph, validation)
```

## Layers

### `lok/domain` — pure logic

| Module | Responsibility |
|---|---|
| `enums.py` | Dimensions, event types, fact statuses, correction types, operators, statuses |
| `models.py` | Dataclasses: `Scenario`, `Fact`, `CorrectionEvent`, `ConversationTurn`, `DependencyEdge`, `Assertion`, `ExpectedOutcome`, `EvaluationSession`, `AssertionResult`, `HumanReview`, `DimensionScore`, `ScoreSummary`; fact-history derivation |
| `normalization.py` | Text normalisation and boundary-aware matching |
| `assertions.py` | Deterministic assertion evaluation with evidence |
| `scoring.py` | All scoring formulas (see METHODOLOGY.md) |
| `dependency_graph.py` | Directed fact graph: transitive dependents, cycle detection (DFS), topological order, DOT rendering |
| `validation.py` | Structural parsing and semantic validation of scenarios, returning located issues (error / warning) |

Everything here is deterministic and covered by unit tests.

### `lok/storage` — persistence

- `database.py` — opens SQLite with `PRAGMA foreign_keys=ON`, provides `transaction()`
  (`BEGIN IMMEDIATE` … `COMMIT` / `ROLLBACK`).
- `migrations.py` — ordered migrations tracked with `PRAGMA user_version`; currently schema v1.
- `scenario_repository.py` — immutable scenario versions; inserting a changed scenario always
  creates `version = current + 1`. Deleting a scenario that has evaluation sessions is refused.
- `evaluation_repository.py` — sessions, responses, results, reviews and a cached
  `dimension_scores` table; `save()` replaces a session's children atomically.

All SQL values are parameterised. Only constant fragments (table names, fixed `WHERE` clauses)
are interpolated, which is why Ruff's S608 rule is disabled for this package.

### `lok/services` — use cases

| Service | Responsibility |
|---|---|
| `ScenarioService` | list/filter, create, update (new version), duplicate, delete, idempotent demo seeding; demo scenarios are read-only |
| `import_export_service` | `lok.scenarios` JSON format v1; preview (size, encoding, format, schema version, per-scenario validation, conflicts) then all-or-nothing apply |
| `EvaluationService` | session lifecycle, saving responses, running assertions, human review, completion rules, reproducibility check |
| `comparison_service` | compatibility check (scenario, version, assertion fingerprint) and deltas/warnings |
| `reporting_service` | JSON / Markdown reports and CSV exports, built only from stored data |
| `container.py` | wires repositories and services; `create_services()` initialises and seeds the DB |

### `lok/ui` — Streamlit

- `state.py` — cached services (`st.cache_resource`, keyed by DB path), stable `lok_*`
  session-state keys, flash messages, page switching.
- `components.py` — palette, badges, CSS (with `prefers-reduced-motion`), score cards, charts,
  assertion evidence view, dependency graph, empty states, a selectbox synced with table
  selection (keyboard-accessible alternative to clicking dataframe rows).
- `pages/` — one module per page, each exposing `render()`.

## Key flows

**Running an evaluation.** `start()` pins the session to the scenario's current version →
responses are typed into drafts held in `st.session_state` (they survive page switches) →
*Save & run* calls `save_responses()` (blank → missing; any change clears stale results) then
`run_evaluation()` → assertions run against the pinned version → results, overall score and
coverage are persisted in one transaction.

**Completion.** `complete()` requires every response-requiring turn to have a saved response and
assertions to have been run on the current responses; otherwise `EvaluationIncompleteError`
lists what is missing. A completed session can be reopened.

**Editing a scenario.** The builder edits a draft dictionary in session state; tables use
`st.data_editor` deltas applied in `on_change` callbacks. *Validate & save* parses and validates
the draft; errors are listed with locations and the draft is kept. Saving an edit inserts a new
version; existing sessions keep pointing at the version they were run against.

## Design decisions

- **Own dependency-graph implementation** instead of a graph library: the needs (dependents,
  cycles, topological order) are small and this keeps runtime dependencies to three packages.
- **Deferred foreign keys** for the circular reference between turns and correction events.
- **`ON DELETE RESTRICT`** from sessions to scenario versions so evidence can never lose its
  scenario.
- **No AI judge.** Assertion checks are deterministic string conditions; meaning is left to
  optional human review.
- **Privacy.** No outbound network code; `.streamlit/config.toml` disables usage statistics and
  binds the server to `localhost`.

## Testing

`tests/` contains unit tests for the domain layer, repository/migration tests against temporary
SQLite files, service tests, export tests, and headless UI smoke tests using Streamlit's
`AppTest` (every page renders without exception; the builder template can be completed and
saved). Visual layout is not covered by automated tests.
