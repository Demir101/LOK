"""Methodology: the evaluation dimensions, assertion semantics, formulas and limitations.

Constants are read from the domain modules so this page always matches the code.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lok.domain.enums import Dimension
from lok.domain.normalization import DEFAULT_POLICY
from lok.domain.scoring import AUTOMATED_WEIGHT, HUMAN_RATING_LABELS, HUMAN_WEIGHT, PARTIAL_COVERAGE_MIN
from lok.services.reporting_service import LIMITATIONS
from lok.ui import components as ui


def render() -> None:
    ui.page_header(
        "Methodology",
        "How LOK evaluates responses, what each result means — and what it does not mean.",
        kicker="Reference",
    )
    st.markdown(
        "LOK is an **evaluation platform, not an AI model**. It never generates or judges text with a model. "
        "Evidence comes from two clearly separated sources: **deterministic automated assertions** and "
        "optional **human review**. Anything neither can verify is reported as *not assessed*."
    )

    st.subheader("The five dimensions")
    st.dataframe(
        pd.DataFrame([{"Dimension": d.label, "Question": d.summary, "Key": d.value} for d in Dimension]),
        hide_index=True,
        width="stretch",
    )
    st.markdown(
        "Every scenario states explicitly which facts are authoritative, which corrections are valid, invalid "
        "or unverified, and which facts depend on which (a directed graph defined by the author — LOK never "
        "infers dependencies from natural language)."
    )

    st.subheader("Assertions")
    st.markdown(
        f"""
| Operator | Passes when |
|---|---|
| `contains` | the normalised response contains the expected value |
| `does_not_contain` | the normalised response does not contain the expected value |
| `equals` | the whole normalised response equals the expected value (surrounding quotes/backticks and trailing sentence punctuation ignored) |
| `does_not_equal` | the whole normalised response differs from the expected value |

**Normalisation:** {DEFAULT_POLICY.describe()}. Internal punctuation is preserved, so `192.168.1.10`,
`v2.1` or `--zstd` keep their meaning.

**Boundary-aware matching** (default, per assertion): a match must not be part of a longer word or a longer
numeric value. `192.168.1.10` is *not* found in `192.168.1.100`, `3.11` is not found in `3.11.4`, `Berlin` is
not found in `Berliner`. Authors can switch it off for an assertion (plain substring match).

| Status | Meaning | Scored? |
|---|---|---|
| `passed` | the defined condition holds | yes |
| `failed` | the defined condition does not hold | yes |
| `not_evaluated` | no response, or an empty response, for the target turn | **no** |
| `error` | the assertion could not be executed (invalid operator, unknown turn, empty expected value, invalid weight) | **no** |

A missing or empty response is never a pass — not even for `does_not_contain`.
"""
    )

    st.subheader("Scoring")
    st.markdown("**Automated dimension score** — weighted pass rate over evaluated assertions:")
    st.latex(r"S_{auto} = \frac{\sum w_{passed}}{\sum w_{passed} + \sum w_{failed}} \times 100")
    st.markdown("Unavailable if a dimension has no passed or failed assertion. **Human score:**")
    st.latex(r"S_{human} = \frac{rating}{4} \times 100")
    st.markdown(" · ".join(f"**{k}** {v}" for k, v in HUMAN_RATING_LABELS.items()))
    st.markdown("**Dimension score:**")
    st.latex(rf"S_{{dim}} = {AUTOMATED_WEIGHT:.2f}\,S_{{auto}} + {HUMAN_WEIGHT:.2f}\,S_{{human}}")
    st.markdown(
        "when both exist; otherwise the one that exists; otherwise **Not Assessed**. "
        "**Overall score** — equal weights over assessed dimensions only:"
    )
    st.latex(r"S_{overall} = \frac{1}{n_{assessed}} \sum_{d\,\in\,assessed} S_{dim}(d)")
    st.markdown("Unassessed dimensions are excluded — never counted as zero. **Coverage:**")
    st.latex(r"Coverage = \frac{n_{assessed}}{5} \times 100")
    st.markdown(
        f"100 % = full coverage · {PARTIAL_COVERAGE_MIN:.0f}–99 % = partial coverage · below "
        f"{PARTIAL_COVERAGE_MIN:.0f} % = limited coverage · 0 % = no assessable evidence. "
        "Scores with different coverage are not directly comparable."
    )
    with st.expander("Worked example"):
        st.markdown(
            "Correction Accuracy has assertions weighted 2 (passed), 1 (passed) and 1 (failed): "
            "S_auto = 3 / 4 × 100 = **75.0**. A reviewer rates it 2 → S_human = 50. "
            f"S_dim = {AUTOMATED_WEIGHT} × 75 + {HUMAN_WEIGHT} × 50 = **67.5**. If only three dimensions are "
            "assessed with 67.5, 100 and 40, the overall score is (67.5 + 100 + 40) / 3 = **69.2** at "
            "**60 % coverage**."
        )

    st.subheader("Versioning and comparison")
    st.markdown(
        "Editing a scenario always creates a new immutable version. An evaluation stays pinned to the version "
        "it was created with, so its results are reproducible from the stored responses. Two sessions are "
        "compared numerically only if they share the scenario ID, the version and identical assertion "
        "definitions; coverage differences are flagged."
    )

    st.subheader("Limitations")
    for item in LIMITATIONS:
        st.markdown(f"- {item}")
