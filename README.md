# LOK — LOOK FOR IT

**AI Correction & Context Integrity Benchmark**

LOK is a local, offline tool for testing whether an AI assistant handles **corrections and
changing context** correctly over a multi-turn conversation. You run a scripted scenario with
any assistant, paste its replies into LOK, and LOK checks each reply against explicitly defined
text assertions, records optional human review, and produces evidence-backed scores and reports.

It measures five dimensions:

| Dimension | Question it asks |
|---|---|
| Correction Accuracy | Does the assistant adopt valid, authoritative corrections? |
| False Correction Resistance | Does it refuse invalid or unverified "corrections"? |
| Dependency Updates | Are values derived from a corrected fact recalculated? |
| Context Preservation | Are unaffected facts kept intact after a correction? |
| Repeated Error Detection | Does an already-corrected value come back later? |

> **What LOK does not do.** A passed assertion means a defined text condition held — not that
> the assistant *understood* the conversation. LOK does not call any AI model, does not judge
> meaning, and a score describes behaviour on one scenario only. See
> [docs/METHODOLOGY.md](docs/METHODOLOGY.md) for formulas and limitations.

## Features

- **Scenario library** — 16 synthetic demo scenarios (read-only) across 16 categories, search and
  filters, dependency-graph view, duplicate to an editable copy, JSON import/export.
- **Scenario builder** — facts with history, conversation turns, correction events
  (valid / invalid / unverified), a fact dependency graph with cycle detection, weighted
  assertions (`contains`, `does_not_contain`, `equals`, `does_not_equal`), expected outcomes.
  Every save is validated; edits create a new immutable version.
- **Run evaluation** — sessions pinned to a scenario version, response drafts that survive page
  changes, deterministic assertion runs with per-assertion evidence, optional 0–4 human review per
  dimension, completion checklist, reproducibility check.
- **Dashboard** — summary cards, six charts, recent activity, descriptive (not causal) insights.
- **History** — search, filters, sorting, pagination, CSV export.
- **Comparison** — only between sessions on the same scenario, version and identical assertion
  definitions, with explicit warnings (coverage differences, unrun/incomplete sessions, evidence
  type differences).
- **Exports** — versioned JSON report, Markdown report, assertion CSV, dimension CSV, history CSV.
- **Local and private** — SQLite storage, no network calls, Streamlit telemetry disabled, server
  bound to `localhost`.

## Requirements

- Python **3.11+** (developed and tested with Python 3.13.15)
- Runtime: `streamlit==1.67.0`, `pandas==3.1.1`, `plotly==7.1.0`
- Development: `pytest==9.2.0`, `ruff==0.14.14`

## Installation

### Windows (PowerShell)

```powershell
cd LOK
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

### Linux / macOS

```bash
cd LOK
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Use `requirements.txt` instead of `requirements-dev.txt` if you do not need tests or linting.

## Launch

```bash
streamlit run app.py
```

Open <http://localhost:8501>. On first start LOK creates `data/lok.db`, applies migrations and
inserts the demo scenarios (once — restarts do not duplicate them).

## Tests and linting

```bash
python -m pytest
```

```bash
python -m ruff check .
```

```bash
python -m ruff format --check .
```

## Configuration

Copy `.env.example` to `.env` or set environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `LOK_DB_PATH` | `data/lok.db` | SQLite file (relative paths resolve against the project root) |
| `LOK_MAX_IMPORT_BYTES` | `2097152` | Maximum scenario import file size |
| `LOK_HISTORY_PAGE_SIZE` | `25` | Rows per page in Evaluation History |

The database file is excluded from Git (`.gitignore`).

## Project layout

```
app.py                  Streamlit entry point and navigation
lok/domain/             Pure logic: models, normalisation, assertions, scoring, graph, validation
lok/storage/            SQLite database, migrations, repositories
lok/services/           Scenario, evaluation, comparison, import/export and reporting services
lok/seed/scenarios.json Synthetic demo scenarios
lok/ui/                 Streamlit pages, shared components, session state helpers
tests/                  pytest suite (domain, storage, services, exports, headless UI smoke tests)
docs/                   Architecture, methodology, data model, user guide
```

## Documentation

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — how to run an evaluation end to end
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — what is measured, formulas, limitations
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, flows, design decisions
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — scenario model, database schema, file formats

## License

MIT — see [LICENSE](LICENSE).
