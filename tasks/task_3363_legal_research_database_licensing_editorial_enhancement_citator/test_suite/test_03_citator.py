"""Citator scoring and editorial override: the weight matrix, the RED/YELLOW
thresholds, the AUTO_DERIVED vs EDITORIAL_OVERRIDE variants, and the OCC guard
(PRD §2.6, §2.8, §3.2)."""
from test_helpers import (
    ApiErrorId,
    citator_override,
    create_citing_document,
    create_published_document,
    get_document,
    make_attorney_editor_headers,
    validate_error,
)


def test_citator_red_at_exactly_80(api):
    """PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below
    that, a score of at least 40 yields `YELLOW`; anything lower — including
    negative scores — yields `GREEN`."
    PRD §2.6: "An `OVERRULED` treatment contributes 100 points when `EXAMINED`, 80
    when `DISCUSSED`, 50 when `CITED`, and 20 when `MENTIONED`."

    Design: Corner/calculations/citator_red_at_exactly_80
    """
    doc_b = create_published_document(
        title="B v. Eighty", raw_citation_string="60 U.S. 80", decision_date="2026-01-01",
    )
    create_citing_document(
        doc_b["id"], "OVERRULED", "DISCUSSED",
        title="A v. Eighty", raw_citation_string="61 U.S. 81", decision_date="2026-02-01",
    )
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 80, f"expected score 80, got {doc_b['citator_score']}"
    assert doc_b["citator_signal"] == "RED", "the >= 80 boundary is inclusive"


def test_citator_yellow_at_exactly_40(api):
    """PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below
    that, a score of at least 40 yields `YELLOW`; anything lower — including
    negative scores — yields `GREEN`."
    PRD §2.6: "A `DISTINGUISHED` treatment contributes 20, 15, 8, and 3."

    Design: Corner/calculations/citator_yellow_at_exactly_40
    """
    doc_b = create_published_document(
        title="B v. Forty", raw_citation_string="62 U.S. 40", decision_date="2026-01-01",
    )
    create_citing_document(
        doc_b["id"], "DISTINGUISHED", "EXAMINED",
        title="A1 v. Forty", raw_citation_string="63 U.S. 41", decision_date="2026-02-01",
    )
    create_citing_document(
        doc_b["id"], "DISTINGUISHED", "EXAMINED",
        title="A2 v. Forty", raw_citation_string="64 U.S. 42", decision_date="2026-03-01",
    )
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 40, f"expected score 40 (20 + 20), got {doc_b['citator_score']}"
    assert doc_b["citator_signal"] == "YELLOW"


def test_citator_negative_weight_offsets_to_green(api):
    """PRD §2.6: "A `FOLLOWED` treatment is favorable authority and subtracts: minus
    30, minus 20, minus 10, and minus 4 across the four depths."
    PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below that,
    a score of at least 40 yields `YELLOW`; anything lower — including negative
    scores — yields `GREEN`."

    Design: Corner/calculations/citator_negative_weight_offsets_to_green
    """
    doc_b = create_published_document(
        title="B v. Offset", raw_citation_string="65 U.S. 20", decision_date="2026-01-01",
    )
    create_citing_document(
        doc_b["id"], "OVERRULED", "CITED",
        title="A1 v. Offset", raw_citation_string="66 U.S. 21", decision_date="2026-02-01",
    )
    create_citing_document(
        doc_b["id"], "FOLLOWED", "EXAMINED",
        title="A2 v. Offset", raw_citation_string="67 U.S. 22", decision_date="2026-03-01",
    )
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 20, f"expected score 20 (50 - 30), got {doc_b['citator_score']}"
    assert doc_b["citator_signal"] == "GREEN"


def test_weighted_matrix_mixed_treatments_score(api):
    """PRD §2.6: "A `QUESTIONED` treatment contributes 50, 35, 20, and 8. A
    `DISTINGUISHED` treatment contributes 20, 15, 8, and 3. A `FOLLOWED` treatment
    is favorable authority and subtracts: minus 30, minus 20, minus 10, and minus 4
    across the four depths."

    Design: Difficulty/combinatorial_formula/citator_weighted_matrix_mixed_treatments_score
    """
    doc_b = create_published_document(
        title="B v. Matrix", raw_citation_string="600 U.S. 1", decision_date="2026-01-01",
    )
    create_citing_document(
        doc_b["id"], "QUESTIONED", "EXAMINED",
        title="A1 v. Q", raw_citation_string="601 U.S. 11", decision_date="2026-02-01",
    )
    create_citing_document(
        doc_b["id"], "DISTINGUISHED", "DISCUSSED",
        title="A2 v. D", raw_citation_string="602 U.S. 22", decision_date="2026-03-01",
    )
    create_citing_document(
        doc_b["id"], "FOLLOWED", "CITED",
        title="A3 v. F", raw_citation_string="603 U.S. 33", decision_date="2026-04-01",
    )
    doc_b = get_document(doc_b["id"])
    assert doc_b["citator_score"] == 55, (
        f"expected 50 + 15 - 10 = 55, got {doc_b['citator_score']}"
    )


def test_weighted_matrix_mixed_treatments_signal_yellow(api):
    """PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below
    that, a score of at least 40 yields `YELLOW`; anything lower — including
    negative scores — yields `GREEN`."

    Design: Difficulty/combinatorial_formula/citator_weighted_matrix_mixed_treatments_score
    """
    doc_b = create_published_document(
        title="B v. Matrix", raw_citation_string="600 U.S. 1", decision_date="2026-01-01",
    )
    create_citing_document(
        doc_b["id"], "QUESTIONED", "EXAMINED",
        title="A1 v. Q", raw_citation_string="601 U.S. 11", decision_date="2026-02-01",
    )
    create_citing_document(
        doc_b["id"], "DISTINGUISHED", "DISCUSSED",
        title="A2 v. D", raw_citation_string="602 U.S. 22", decision_date="2026-03-01",
    )
    create_citing_document(
        doc_b["id"], "FOLLOWED", "CITED",
        title="A3 v. F", raw_citation_string="603 U.S. 33", decision_date="2026-04-01",
    )
    doc_b = get_document(doc_b["id"])
    assert 40 <= doc_b["citator_score"] < 80
    assert doc_b["citator_signal"] == "YELLOW", (
        f"score {doc_b['citator_score']} in [40, 80) must yield YELLOW"
    )


def test_auto_derived_signal_baseline_red(api):
    """PRD §2.6: "This threshold derivation applies only while the document's
    `editorial_override_signal` is unset."
    PRD §2.6: "When the score reaches at least 80 the signal is `RED`; below that,
    a score of at least 40 yields `YELLOW`; anything lower — including negative
    scores — yields `GREEN`."

    Design: Difficulty/dual_variant_calc/citator_auto_vs_editorial_override_divergence
    """
    doc_b = create_published_document(
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="B v. Base", raw_citation_string="500 F.3d 100", decision_date="2026-01-10",
    )
    create_citing_document(
        doc_b["id"], "OVERRULED", "EXAMINED",
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="A v. Cites", raw_citation_string="501 F.3d 200", decision_date="2026-02-10",
    )
    doc_b = get_document(doc_b["id"])
    assert doc_b["editorial_override_signal"] is None
    assert doc_b["citator_score"] == 100
    assert doc_b["citator_signal"] == "RED", "AUTO_DERIVED on score 100 must be RED (100 >= 80)"


def test_editorial_override_pins_signal(api):
    """PRD §3.2: "the `citator_signal` field then reports the pinned value under the
    EDITORIAL_OVERRIDE variant, while `citator_score` continues to be computed and
    stored from the live reference set. The document's `version` increments by one
    on every override."

    Design: Difficulty/dual_variant_calc/citator_auto_vs_editorial_override_divergence
    """
    doc_b = create_published_document(
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="B v. Base", raw_citation_string="500 F.3d 100", decision_date="2026-01-10",
    )
    create_citing_document(
        doc_b["id"], "OVERRULED", "EXAMINED",
        source_type="COURT", jurisdiction_code="CA9", document_type="CASE",
        title="A v. Cites", raw_citation_string="501 F.3d 200", decision_date="2026-02-10",
    )
    before = get_document(doc_b["id"])
    updated = citator_override(
        doc_b["id"], "YELLOW", before["version"],
        rationale="Editorial analysis: overruling limited to facts",
    )
    assert updated["citator_score"] == 100, "the score is still computed from the reference set"
    assert updated["citator_signal"] == "YELLOW", "override pins YELLOW where AUTO_DERIVED gives RED"
    assert updated["editorial_override_signal"] == "YELLOW"
    assert updated["version"] == before["version"] + 1


def test_occ_citator_override_stale_then_fresh(api):
    """PRD §2.8: "Because a new override supersedes any earlier override on the same
    document, a second write is never blocked by the first one's state — but when
    the document's `version` has advanced past the supplied value since the client
    last read it (another override, or a cascade recompute that landed meanwhile),
    the write is rejected as stale with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_citator_override_stale_then_fresh
    """
    doc = create_published_document(
        source_type="COURT", jurisdiction_code="MT", document_type="CASE",
        title="Occ v. Doc", raw_citation_string="99 P.3d 7", decision_date="2026-01-01",
    )
    v0 = get_document(doc["id"])["version"]
    citator_override(doc["id"], "YELLOW", v0, rationale="first")

    stale = api.citator_override(
        doc["id"],
        {"override_signal": "RED", "rationale": "stale second writer", "expected_document_version": v0},
        headers={"X-User-ID": "test-citator-analyst-1", "X-User-Role": "CitatorAnalyst"},
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    v1 = get_document(doc["id"])["version"]
    retried = citator_override(doc["id"], "RED", v1, rationale="fresh retry")
    assert retried["editorial_override_signal"] == "RED"
    assert retried["citator_signal"] == "RED"
    assert retried["version"] == v1 + 1


def test_citator_override_requires_analyst_role(api):
    """PRD §2.1: "Each endpoint admits a specific subset of these roles; a request
    whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/citator_override_requires_analyst_role
    """
    doc = create_published_document(
        source_type="COURT", jurisdiction_code="UT", document_type="CASE",
        title="Role v. Override", raw_citation_string="98 P.3d 6", decision_date="2026-01-01",
    )
    version = get_document(doc["id"])["version"]
    resp = api.citator_override(
        doc["id"],
        {"override_signal": "GREEN", "expected_document_version": version},
        headers=make_attorney_editor_headers("ed-author-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert get_document(doc["id"])["editorial_override_signal"] is None
