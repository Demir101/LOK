from lok.domain.normalization import (
    NormalizationPolicy,
    find_bounded,
    find_match,
    normalize_text,
    strip_edge_punctuation,
)


def test_case_insensitive_by_default():
    assert normalize_text("The Deadline Is MAY 22") == "the deadline is may 22"


def test_case_sensitive_policy_preserves_case():
    assert normalize_text("MAY 22", NormalizationPolicy(case_sensitive=True)) == "MAY 22"


def test_whitespace_is_collapsed_and_trimmed():
    assert normalize_text("  May\t\t22\n\n2026  ") == "may 22 2026"


def test_non_breaking_and_zero_width_spaces():
    assert normalize_text("May 22​") == "may 22"


def test_unicode_nfkc_normalization():
    # Fullwidth digits and composed/decomposed forms become identical.
    assert normalize_text("１９２") == "192"
    assert normalize_text("Café") == normalize_text("Café")


def test_typographic_quotes_become_ascii():
    assert normalize_text("“Alice’s”") == '"alice\'s"'


def test_internal_punctuation_is_preserved():
    assert normalize_text("192.168.1.10") == "192.168.1.10"
    assert normalize_text("v2.1.3-rc1") == "v2.1.3-rc1"
    assert normalize_text("2026-05-22") == "2026-05-22"
    assert normalize_text("--zstd") == "--zstd"


def test_different_technical_values_remain_different():
    assert normalize_text("192.168.1.10") != normalize_text("192.168.110")
    assert normalize_text("v2.1") != normalize_text("v21")
    assert normalize_text("10.30.8.0/24") != normalize_text("10.30.8.0/16")


def test_ip_address_not_matched_inside_longer_address():
    hay = normalize_text("The server is at 192.168.1.100 now.")
    assert find_bounded(hay, "192.168.1.10") == -1
    assert find_bounded(hay, "192.168.1.100") >= 0


def test_ip_address_not_matched_as_suffix_fragment():
    hay = normalize_text("Use 192.168.1.10 for production.")
    assert find_bounded(hay, "168.1.10") == -1


def test_ip_followed_by_sentence_period_matches():
    hay = normalize_text("The verified address is 192.168.1.10.")
    assert find_bounded(hay, "192.168.1.10") >= 0


def test_date_preserved_with_trailing_punctuation():
    hay = normalize_text("The deadline is May 22, as agreed.")
    assert find_bounded(hay, "may 22") >= 0
    assert find_bounded(normalize_text("May 225 units"), "may 22") == -1


def test_version_not_matched_inside_longer_version():
    hay = normalize_text("Requires Python 3.11.4 or newer")
    assert find_bounded(hay, "3.11") == -1
    hay2 = normalize_text("Base image python:3.12-slim")
    assert find_bounded(hay2, "3.12") >= 0


def test_word_boundaries_for_identifiers():
    hay = normalize_text("The Berliner office and ledgerline_v2")
    assert find_bounded(hay, "berlin") == -1
    assert find_bounded(hay, "ledgerline") == -1
    assert find_bounded(normalize_text("Package ledgerline is ready"), "ledgerline") >= 0


def test_plain_substring_mode_when_boundary_disabled():
    hay = normalize_text("192.168.1.100")
    assert find_match(hay, "192.168.1.10", boundary_match=False) == 0
    assert find_match(hay, "192.168.1.10", boundary_match=True) == -1


def test_needle_starting_with_punctuation():
    hay = normalize_text("Run backup --zstd --verify")
    assert find_bounded(hay, "--zstd") >= 0


def test_strip_edge_punctuation():
    assert strip_edge_punctuation('"May 22."') == "May 22"
    assert strip_edge_punctuation("192.168.1.10.") == "192.168.1.10"


def test_empty_needle_never_matches():
    assert find_bounded("anything", "") == -1
