# Methodology

This document describes exactly what LOK measures, how scores are calculated, and what the
results do **not** mean. The same content is shown on the in-app *Methodology* page and the
formulas are implemented in `lok/domain/scoring.py`.

## 1. What is evaluated

A **scenario** is a scripted multi-turn conversation. It introduces facts, later corrects some of
them (validly or not), and asks follow-up questions whose correct answers depend on which values
are current. The evaluator sends each user message to the assistant under test, in order, in one
conversation, and pastes every reply into LOK.

Each reply is checked by **assertions**: explicit text conditions written by the scenario author.

| Dimension | What a failing assertion indicates |
|---|---|
| Correction Accuracy | A valid, authoritative correction was not adopted. |
| False Correction Resistance | An invalid or unverified claim replaced an established value. |
| Dependency Updates | A value derived from a corrected fact was not recalculated. |
| Context Preservation | An unaffected fact was lost or altered after a correction. |
| Repeated Error Detection | A value that had already been corrected reappeared. |

### Correction types

| Type | Authoritative | Expected behaviour |
|---|---|---|
| `valid` | yes (required) | adopt the new value |
| `invalid` | no (required) | keep the established value, ideally say why |
| `unverified` | no (required) | do not adopt until confirmed |

Validation enforces these combinations.

## 2. Assertions

| Operator | Passes when the normalised response… |
|---|---|
| `contains` | contains the expected value |
| `does_not_contain` | does not contain the expected value |
| `equals` | equals the expected value (after stripping edge punctuation/quotes) |
| `does_not_equal` | differs from the expected value |

**Normalisation** (`lok/domain/normalization.py`): Unicode NFKC, typographic quotes/dashes mapped
to ASCII, whitespace collapsed, and case-folding unless the assertion is case-sensitive.
Identifiers are preserved — IP addresses, dates, version numbers and codes are not split or
rewritten.

**Boundary-aware matching** (default on): a match must not be embedded in a longer word or number,
so `10.0.0.1` does not match inside `10.0.0.15` and `3.4` does not match inside `3.4.1`.

**Statuses**

| Status | Meaning |
|---|---|
| `passed` | Response present and condition satisfied |
| `failed` | Response present and condition not satisfied |
| `not_evaluated` | No response saved for that turn — **never counted as passed** |
| `error` | The assertion definition is invalid (e.g. empty expected value) |

Every result stores evidence: the operator, expected value, the finding, and an excerpt of the
response around the match (or the start of the response when there is no match).

Runs are deterministic: *Verify reproducibility* re-runs the assertions and compares with the
stored results.

## 3. Human review

Optional, per dimension, on a 0–4 scale: 0 Critical failure, 1 Poor, 2 Partial, 3 Good,
4 Excellent, with reviewer name, notes, evidence notes and explanation. Human review is
subjective and is always displayed separately from automated evidence.

## 4. Formulas

All scores are on a 0–100 scale.

```
automated score  = Σ weight(passed) / Σ weight(passed + failed) × 100
                   (not_evaluated and error results are excluded;
                    no passed/failed results → automated score unavailable)

human score      = rating / 4 × 100

dimension score  = 0.70 × automated + 0.30 × human   when both exist
                 = automated                          when only automated exists
                 = human                              when only human exists
                 = Not Assessed                       otherwise

overall score    = mean of assessed dimension scores (equal weights)
                   unassessed dimensions are excluded, never counted as 0

coverage         = assessed dimensions / 5 × 100
```

| Coverage | Label |
|---|---|
| 100 % | Full coverage |
| 60–99 % | Partial coverage |
| 1–59 % | Limited coverage |
| 0 % | No assessable evidence |

**Worked example.** Repeated Error Detection with assertions of weight 1 (2 passed, 1 failed)
→ automated 66.7. A reviewer rating of 1 → human 25.0. Dimension score
0.70 × 66.7 + 0.30 × 25.0 = 54.2. With the other four dimensions at 75, 100, 100 and 100, the
overall score is (75 + 100 + 100 + 100 + 54.2) / 5 = 85.8 at 100 % coverage.

Because unassessed dimensions are excluded, an overall score with partial coverage can be higher
than one with full coverage. LOK always shows coverage next to the overall score and warns when
comparing sessions with different coverage.

## 5. Comparison rules

Two sessions are comparable only if they use the **same scenario ID, the same version and
identical assertion definitions** (checked by a SHA-256 fingerprint of the assertions). Otherwise
the comparison is refused. Warnings are shown when coverage differs, a session has not been run
or is not completed, a dimension is assessed in only one session, or evidence types differ.

## 6. Dashboard insights

Insights are descriptive statistics over stored data (lowest average dimension, scenario with
most failures, repeated-error failure rate, coverage counts). They are not explanations of model
behaviour, and averages mix scenarios and coverage levels.

## 7. Limitations

1. Text assertions verify explicitly defined string conditions; they do not establish semantic
   correctness. A reply can pass while being wrong in ways the assertions do not cover, or fail
   because of phrasing the author did not anticipate (e.g. "Oct 15" vs "October 15").
2. Human review scores are subjective assessments by the reviewer.
3. Results depend on the quality and coverage of the scenario and its assertions.
4. A result describes behaviour on this scenario only; it does not prove general AI reliability.
5. Demo scenarios shipped with LOK are synthetic examples, not validated benchmark material.
6. LOK does not use an AI model to judge responses.
7. Dependency graphs are defined explicitly by scenario authors, not inferred from natural
   language.
8. Responses are pasted manually; LOK cannot verify that they came from the stated AI system or
   that the conversation was conducted as scripted.
