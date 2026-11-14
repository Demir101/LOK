"""Text normalization and boundary-aware matching.

Design goals:

* Make cosmetic differences irrelevant (Unicode compatibility forms, typographic
  quotes, non-breaking spaces, repeated whitespace, letter case).
* Never make *different technical values* equivalent. Internal punctuation is
  kept as-is, so ``192.168.1.10`` and ``192.168.110`` stay different, and
  ``v2.1`` and ``v21`` stay different.
* Boundary-aware ``contains`` matching: ``192.168.1.10`` is *not* found inside
  ``192.168.1.100``, ``Berlin`` is not found inside ``Berliner`` and ``3.11`` is
  not found inside ``3.11.4``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Typographic characters mapped to their plain ASCII equivalents.
_CHARACTER_MAP = str.maketrans(
    {
        "‘": "'",  # left single quotation mark
        "’": "'",  # right single quotation mark / apostrophe
        "‚": "'",
        "‛": "'",
        "′": "'",  # prime
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
        "«": '"',
        "»": '"',
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "–": "-",  # en dash, as used in ranges such as 09:00–13:00
        "−": "-",  # minus sign
    }
)

#: Zero-width and formatting characters removed entirely.
_INVISIBLE = re.compile("[​‌‍⁠﻿­]")
_WHITESPACE = re.compile(r"\s+")

#: Characters that join numeric parts (dates, IPs, versions, decimals, CIDR).
_NUMERIC_JOINERS = frozenset(".,:-/")

#: Trailing sentence punctuation ignored by ``equals`` comparisons.
_EDGE_PUNCTUATION = " .!?;:,\"'`"


@dataclass(frozen=True)
class NormalizationPolicy:
    """Settings that control how text is normalised before comparison."""

    case_sensitive: bool = False
    unicode_form: str = "NFKC"
    collapse_whitespace: bool = True
    normalize_typography: bool = True

    def describe(self) -> str:
        parts = [
            f"Unicode {self.unicode_form}",
            "typographic quotes/hyphens mapped to ASCII" if self.normalize_typography else "",
            "whitespace collapsed" if self.collapse_whitespace else "",
            "case-sensitive" if self.case_sensitive else "case-insensitive",
        ]
        return ", ".join(part for part in parts if part)


DEFAULT_POLICY = NormalizationPolicy()


def normalize_text(text: str, policy: NormalizationPolicy = DEFAULT_POLICY) -> str:
    """Normalise ``text`` for comparison according to ``policy``.

    Internal punctuation is preserved; only cosmetic variation is removed.
    """
    result = unicodedata.normalize(policy.unicode_form, text)
    result = _INVISIBLE.sub("", result)
    if policy.normalize_typography:
        result = result.translate(_CHARACTER_MAP)
    if policy.collapse_whitespace:
        result = _WHITESPACE.sub(" ", result).strip()
    if not policy.case_sensitive:
        result = result.casefold()
    return result


def strip_edge_punctuation(text: str) -> str:
    """Remove surrounding whitespace, quotes and trailing sentence punctuation."""
    return text.strip(_EDGE_PUNCTUATION)


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _boundary_ok_before(haystack: str, start: int, needle: str) -> bool:
    if start == 0 or not _is_word_char(needle[0]):
        return True
    previous = haystack[start - 1]
    if _is_word_char(previous):
        return False
    # "168.1.10" must not match inside "192.168.1.10": a numeric joiner preceded
    # by a digit continues the same technical value.
    if needle[0].isdigit() and previous in _NUMERIC_JOINERS and start >= 2:
        return not haystack[start - 2].isdigit()
    return True


def _boundary_ok_after(haystack: str, end: int, needle: str) -> bool:
    if end >= len(haystack) or not _is_word_char(needle[-1]):
        return True
    following = haystack[end]
    if _is_word_char(following):
        return False
    # "3.11" must not match inside "3.11.4"; "May 22" may be followed by "." or ",".
    if needle[-1].isdigit() and following in _NUMERIC_JOINERS and end + 1 < len(haystack):
        return not haystack[end + 1].isdigit()
    return True


def find_bounded(haystack: str, needle: str) -> int:
    """Return the index of the first boundary-respecting match, or ``-1``.

    Both strings must already be normalised. A match is rejected when it is a
    fragment of a longer word or of a longer numeric/technical value.
    """
    if not needle:
        return -1
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        if _boundary_ok_before(haystack, start, needle) and _boundary_ok_after(haystack, end, needle):
            return start
        start = haystack.find(needle, start + 1)
    return -1


def find_match(haystack: str, needle: str, *, boundary_match: bool = True) -> int:
    """Find ``needle`` in ``haystack`` using bounded or plain substring matching."""
    if boundary_match:
        return find_bounded(haystack, needle)
    return haystack.find(needle) if needle else -1


def excerpt_around(text: str, start: int, length: int, radius: int = 60) -> str:
    """Return a short excerpt of ``text`` around a match, with ellipses."""
    if start < 0:
        return truncate(text, radius * 2)
    left = max(0, start - radius)
    right = min(len(text), start + length + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def truncate(text: str, limit: int = 160) -> str:
    """Truncate ``text`` to ``limit`` characters, adding an ellipsis if needed."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"
