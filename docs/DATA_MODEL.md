# Data model

## Scenario (domain)

| Element | Key fields | Notes |
|---|---|---|
| Scenario | `scenario_id`, `version`, `title`, `description`, `objective`, `category`, `difficulty` (easy/medium/hard), `tags`, `origin` (demo/custom), `change_note` | IDs match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` |
| Fact | `fact_id`, `name`, `initial_value`, `expected_current_value`, `status` (active/corrected/superseded/unverified), `description` | History is derived from the correction events targeting it |
| Correction event | `correction_id`, `target_fact_id`, `original_value`, `proposed_value`, `correction_type` (valid/invalid/unverified), `is_authoritative`, `turn_id`, `expected_behavior`, `explanation` | `valid` ⇒ authoritative; `invalid`/`unverified` ⇒ not authoritative |
| Conversation turn | `turn_id`, `order`, `event_type`, `user_message`, `requires_response`, `correction_id`, `notes` | A correction turn must reference its correction, whose `turn_id` must point back |
| Dependency edge | `source_fact_id` → `target_fact_id`, `explanation` | Must form a directed acyclic graph |
| Assertion | `assertion_id`, `turn_id`, `dimension`, `description`, `operator`, `expected_value`, `weight` (> 0), `explanation`, `case_sensitive` (default false), `boundary_match` (default true) | Its turn must require a response |
| Expected outcome | `outcome_id`, `description`, optional `dimension` and `turn_id` | Documentation of intended behaviour |

Validation (`lok/domain/validation.py`) also warns when a turn is checked only by negative
assertions (`does_not_contain` / `does_not_equal`), since an empty or evasive reply could pass.

## Evaluation (domain)

| Element | Key fields |
|---|---|
| Evaluation session | `evaluation_id` (`EV-YYYYMMDD-XXXXXX`), `ai_system`, `model_label`, `scenario_id`, `scenario_version`, `status` (draft/in_progress/completed), timestamps, `notes` |
| Assistant response | `turn_id`, `response_text` (blank responses are not stored) |
| Assertion result | `assertion_id`, `turn_id`, `dimension`, `status`, `evidence`, `response_excerpt`, `weight`, `evaluated_at` |
| Human review | `dimension`, `rating` (0–4), `reviewer`, `reviewer_notes`, `evidence_notes`, `explanation`, `reviewed_at` |
| Dimension score | automated / human / combined score, evidence type, pass/fail/not-evaluated/error counts |

## Database schema (SQLite, schema version 1)

File: `data/lok.db` by default (`LOK_DB_PATH`). Foreign keys are enforced; migrations are tracked
in `PRAGMA user_version`.

| Table | Primary key | Purpose |
|---|---|---|
| `app_meta` | `key` | Internal metadata (e.g. seeding marker) |
| `scenarios` | `scenario_id` | Scenario identity, origin, current version |
| `scenario_versions` | (`scenario_id`, `version`) | Immutable version content (basics, change note) |
| `scenario_tags` | (`scenario_id`, `version`, `tag`) | Tags per version |
| `facts` | (`scenario_id`, `version`, `fact_id`) | Facts per version |
| `conversation_turns` | (`scenario_id`, `version`, `turn_id`) | Turns per version |
| `correction_events` | (`scenario_id`, `version`, `correction_id`) | Corrections (deferred FKs to facts and turns) |
| `fact_dependencies` | (`scenario_id`, `version`, `source_fact_id`, `target_fact_id`) | Dependency edges |
| `assertions` | (`scenario_id`, `version`, `assertion_id`) | Assertions with CHECK constraints on dimension, operator, weight |
| `expected_outcomes` | (`scenario_id`, `version`, `outcome_id`) | Expected outcomes |
| `evaluation_sessions` | `evaluation_id` | Sessions; FK to `scenario_versions` with `ON DELETE RESTRICT` |
| `assistant_responses` | (`evaluation_id`, `turn_id`) | Saved responses |
| `assertion_results` | (`evaluation_id`, `assertion_id`) | Results with evidence |
| `human_reviews` | (`evaluation_id`, `dimension`) | Optional reviews, rating CHECK 0–4 |
| `dimension_scores` | (`evaluation_id`, `dimension`) | Cached per-dimension scores for dashboards |

Indexes: `scenario_versions(scenario_id)`, `conversation_turns(scenario_id, version, turn_order)`,
`assertions(scenario_id, version, turn_id)`, `evaluation_sessions(scenario_id, scenario_version)`,
`evaluation_sessions(updated_at)`, `evaluation_sessions(status)`, `evaluation_sessions(ai_system)`,
`assertion_results(status)`.

Child rows of a scenario version cascade on delete; a version referenced by any session cannot be
deleted.

## File formats

### Scenario import/export (`lok.scenarios`, schema version 1)

```json
{
  "format": "lok.scenarios",
  "schema_version": 1,
  "exported_at": "2026-11-14T21:00:00+00:00",
  "scenarios": [ { "scenario_id": "...", "title": "...", "facts": [], "turns": [],
                   "corrections": [], "dependencies": [], "assertions": [],
                   "expected_outcomes": [] } ]
}
```

Import rules: maximum size `LOK_MAX_IMPORT_BYTES` (default 2 MiB), UTF-8 JSON only (parsed with
`json`, never evaluated), matching `format` and `schema_version`, each scenario fully validated,
no duplicate IDs in one file, demo scenarios cannot be replaced. Existing custom IDs are only
replaced after explicit confirmation and become a new version. The import is all-or-nothing.

### Evaluation report (`lok.evaluation_report`, schema version 1)

JSON report with evaluation metadata, AI system, scenario reference, dimension scores, overall
score and coverage, all assertion results with evidence, human reviews, responses, methodology
constants and limitations. The Markdown report presents the same data for reading. CSV exports
(assertions, dimensions, filtered history) are UTF-8 with BOM for spreadsheet compatibility.
