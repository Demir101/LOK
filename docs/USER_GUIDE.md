# User guide

Start LOK with `streamlit run app.py` and open <http://localhost:8501>. The sidebar groups the
pages into **Overview**, **Evaluate**, **Scenarios** and **Reference**.

## 1. Choose a scenario — Scenario Library

1. Search titles and descriptions, or filter by category, difficulty, dimension, tag or origin (demo/custom).
2. Pick a scenario in the table or with **Open scenario**. The detail view shows the objective,
   facts with their history, correction events, the conversation, assertions, expected outcomes
   and the fact dependency graph (corrected facts and the facts that depend on them are
   highlighted).
3. Click **Start evaluation** to open it in Run Evaluation.

Demo scenarios are synthetic and read-only. Use **Duplicate** to make an editable custom copy.
Custom scenarios can be deleted only when no evaluation session uses them.

**Import / export** (tab in the library): export selected scenarios to a `lok.scenarios` JSON
file; import shows a preview with validation errors per scenario before anything is written.
Replacing existing custom scenarios requires ticking the confirmation and creates new versions.

## 2. Run an evaluation — Run Evaluation

1. Enter the **AI system** (e.g. product name) and a **model / version label**, choose the
   scenario, and create the session. It is pinned to the scenario's current version.
2. **Responses tab.** Open a fresh conversation with the assistant you are testing. Send each user
   message in order and paste each reply into the matching field. Leave a field empty if you have
   no reply — it will be *not evaluated*, never passed. Unsaved edits are kept while you visit
   other pages within the same browser session (the header shows "unsaved response changes").
3. Click **Save & run evaluation**. LOK saves the responses and runs every assertion.
4. **Results & evidence tab.** Overall score, coverage, per-dimension scores and every assertion
   with its operator, expected value, finding and response excerpt. **Verify reproducibility**
   re-runs the checks and compares them with the stored results.
5. **Human review tab (optional).** For each dimension give a 0–4 rating with reviewer, notes,
   evidence notes and explanation. Ratings are combined 70 % automated / 30 % human.
6. **Complete & export tab.** The checklist shows what is missing. **Mark as completed** is
   available once every required response is saved and the assertions were run on the current
   responses. Download the JSON report, Markdown report, assertions CSV or dimensions CSV.
   Completed sessions can be reopened; sessions can be deleted after confirmation.

Changing a saved response clears the old results; run the evaluation again afterwards.

## 3. Review results — Dashboard and Evaluation History

- **Dashboard**: session/scenario counts, average score and coverage, dimension comparison,
  score history by AI system, assertion result distribution, coverage distribution, scenario
  categories, dimension performance by AI system, recent activity and descriptive insights.
  With no sessions it shows an empty state with next steps.
- **Evaluation History**: search, filter (AI system, scenario, status, date range), sort and page
  through all sessions; export the filtered list as CSV; open a session to see its details.

## 4. Compare two sessions — Comparison

Pick session A; session B can only be a session on the same scenario, version and identical
assertions. LOK shows score and coverage deltas, a dimension chart, assertion-level differences
(optionally only changed results) and repeated-error results, plus warnings for anything that
weakens the comparison.

## 5. Write your own scenario — Scenario Builder

1. **Use template** (a small working example) or **Start blank**; or pick a custom scenario to
   edit.
2. Fill **Basics** (ID, title, description, objective, category, difficulty, tags).
3. Edit the tables: **Facts**, **Conversation** (turns, event types, which turns need a reply),
   **Corrections** (valid / invalid / unverified, authoritative flag, the turn where it happens),
   **Dependencies** (source fact → dependent fact), **Assertions** (turn, dimension, operator,
   expected value, weight, case sensitivity, boundary matching), **Outcomes**.
4. Open **Validate & save**. Errors are listed with their location; your draft is kept until you
   fix them (the sidebar warns while a builder draft has unsaved changes). Warnings (e.g. a turn checked only by negative assertions) do not block saving.
5. Saving an edit creates a new version; earlier sessions keep their original version.

Tips for good assertions:

- Pair a negative check (`does_not_contain` the old value) with a positive one (`contains` the
  new value) so an empty or evasive reply cannot pass.
- Keep boundary matching on for numbers, IPs and versions.
- Write expected values in the form you ask the assistant to use (ask for "October 15", not a
  date in any format).

## 6. Settings

Shows the database location, schema version, counts and configuration values, the privacy
settings in effect, and bulk exports. Maintenance actions: restore missing demo scenarios, clear
the Scenario Builder draft, and delete all evaluations (behind a confirmation dialog). Configuration itself is changed through
environment variables or `.env` (see README).

## Privacy

Everything stays on this machine: data is stored in the local SQLite file, LOK makes no network
requests, Streamlit usage statistics are disabled and the server listens on `localhost` only.
Your browser still loads the page from that local server.
