"""Weighted evaluation scoring: the pinned per-dimension rounding order."""
from test_helpers import (
    HALF_CENT_DIMENSIONS,
    STANDARD_DIMENSIONS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_analyst,
    create_document,
    create_inclusion,
    create_vendor,
    get_document,
    get_success_data,
    make_analyst_headers,
    validate_error,
    validate_paginated,
)

# A third input set whose products land on half-cents as well.
THIRD_DIMENSIONS = [
    {"dimension": "PRODUCT_CAPABILITY", "raw_score": 4.45, "weight_pct": 0.30},
    {"dimension": "MARKET_EXECUTION", "raw_score": 3.80, "weight_pct": 0.25},
    {"dimension": "CUSTOMER_VOICE", "raw_score": 4.10, "weight_pct": 0.20},
    {"dimension": "INNOVATION_ROADMAP", "raw_score": 3.25, "weight_pct": 0.15},
    {"dimension": "PRICING_TRANSPARENCY", "raw_score": 2.90, "weight_pct": 0.10},
]

FOURTH_DIMENSIONS = [
    {"dimension": "PRODUCT_CAPABILITY", "raw_score": 3.35, "weight_pct": 0.30},
    {"dimension": "MARKET_EXECUTION", "raw_score": 2.50, "weight_pct": 0.25},
    {"dimension": "CUSTOMER_VOICE", "raw_score": 1.10, "weight_pct": 0.20},
    {"dimension": "INNOVATION_ROADMAP", "raw_score": 3.00, "weight_pct": 0.15},
    {"dimension": "PRICING_TRANSPARENCY", "raw_score": 4.05, "weight_pct": 0.10},
]


def _draft_with_vendor():
    lead = create_analyst()
    vendor = create_vendor()
    document = create_document(lead)
    return lead, vendor, document


def test_weighted_total_rounds_each_dimension_before_summing():
    """PRD §2.8: "each dimension's points are `weight_pct` multiplied by `raw_score`,
    rounded half up to 2 decimal places; `weighted_total_score` is then the sum of
    those already-rounded per-dimension points, rounded half up to 2 decimal places."
    PRD §2.8: "Rounding the unrounded products only once at the end is expressly
    rejected — it can produce a different cent for the same inputs (for example 3.85
    where the pinned order yields 3.86) and must not be used."

    Design: Difficulty/dual_variant_calc/evaluation_round_per_dimension_vs_total_only
    """
    _, vendor, document = _draft_with_vendor()
    inclusion = create_inclusion(document, vendor, dimensions=STANDARD_DIMENSIONS)

    assert inclusion["weighted_total_score"] == 3.86
    assert inclusion["weighted_total_score"] != 3.85
    assert inclusion["inclusion_status"] == "UNDER_EVALUATION"

    assert abs(sum([1.31, 0.95, 0.82, 0.49, 0.29]) - inclusion["weighted_total_score"]) < 1e-9, (
        "The stored total must equal the sum of the rounded per-dimension points"
    )


def test_pinned_rounding_order_holds_on_a_second_input_set():
    """PRD §2.8: "each dimension's points are `weight_pct` multiplied by `raw_score`,
    rounded half up to 2 decimal places; `weighted_total_score` is then the sum of
    those already-rounded per-dimension points, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/evaluation_round_per_dimension_vs_total_only
    """
    _, vendor, document = _draft_with_vendor()
    inclusion = create_inclusion(document, vendor, dimensions=THIRD_DIMENSIONS)

    assert inclusion["weighted_total_score"] == 3.89, (
        "1.34 + 0.95 + 0.82 + 0.49 + 0.29 after per-dimension rounding"
    )
    assert inclusion["weighted_total_score"] != 3.88, (
        "3.88 is what rounding the unrounded sum once would produce"
    )
    assert inclusion["inclusion_status"] == "UNDER_EVALUATION"


def test_half_cent_dimension_products_round_up_per_dimension():
    """PRD §2.8: "each dimension's points are `weight_pct` multiplied by `raw_score`,
    rounded half up to 2 decimal places; `weighted_total_score` is then the sum of
    those already-rounded per-dimension points, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/evaluation_dimension_rounding_boundary_cent
    """
    _, vendor, document = _draft_with_vendor()
    inclusion = create_inclusion(document, vendor, dimensions=HALF_CENT_DIMENSIONS)

    assert inclusion["weighted_total_score"] == 4.06
    assert inclusion["weighted_total_score"] != 4.04, (
        "4.04 is what rounding the unrounded sum once would produce"
    )
    per_dimension = [round(row["weight_pct"] * row["raw_score"], 2)
                     for row in HALF_CENT_DIMENSIONS]
    assert abs(sum([1.31, 1.03, 0.82, 0.49, 0.41]) - inclusion["weighted_total_score"]) < 1e-9
    assert len(per_dimension) == 5


def test_half_cent_rounding_on_a_second_dimension_set():
    """PRD §2.8: "each dimension's points are `weight_pct` multiplied by `raw_score`,
    rounded half up to 2 decimal places; `weighted_total_score` is then the sum of
    those already-rounded per-dimension points, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/evaluation_dimension_rounding_boundary_cent
    """
    _, vendor, document = _draft_with_vendor()
    inclusion = create_inclusion(document, vendor, dimensions=FOURTH_DIMENSIONS)

    assert inclusion["weighted_total_score"] == 2.72, (
        "1.01 + 0.63 + 0.22 + 0.45 + 0.41 after per-dimension rounding"
    )
    assert inclusion["weighted_total_score"] != 2.71
    assert inclusion["inclusion_status"] == "UNDER_EVALUATION"


def test_finalize_include_is_refused_below_the_criteria_floor():
    """PRD §3.7: "An `INCLUDE` requires the inclusion to be `UNDER_EVALUATION`,
    `inclusion_criteria_met_count` to be at least 4 of the six published criteria, and
    `weighted_total_score` to be at least 2.50; a finalization that misses either
    threshold is rejected with `ERR_INCLUSION_CRITERIA_NOT_MET` (HTTP 409)."

    Design: Corner/errors/finalize_include_below_the_criteria_floor_returns_inclusion_criteria_not_met
    """
    _, vendor, document = _draft_with_vendor()
    inclusion = create_inclusion(
        document, vendor, dimensions=HALF_CENT_DIMENSIONS,
        inclusion_criteria_met_count=3,
    )
    assert inclusion["weighted_total_score"] == 4.06, (
        "The score half of the gate is satisfied; only the criteria count fails"
    )

    resp = api_client.finalize_inclusion(
        inclusion["id"], {"outcome": "INCLUDE"}, TEST_USERS["research_director_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INCLUSION_CRITERIA_NOT_MET)

    unchanged = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert unchanged["inclusion_status"] == "UNDER_EVALUATION"


def test_stale_document_version_blocks_the_second_inclusion():
    """PRD §2.12: "Creating a vendor inclusion on a document requires
    `expected_document_version`; if it does not equal the document's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "The parent document's `version` is incremented by the create itself."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_document_version_on_the_second_inclusion
    """
    lead = create_analyst()
    first_vendor = create_vendor()
    second_vendor = create_vendor(
        vendor_name="Bluepeak Systems", hq_region="EMEA", employee_count_band="MIDMARKET"
    )
    document = create_document(lead)
    observed_version = document["version"]

    create_inclusion(document, first_vendor)

    after_first = get_document(document)
    assert after_first["version"] == observed_version + 1

    stale = api_client.create_inclusion(
        document["id"],
        {
            "vendor_id": second_vendor["id"],
            "dimension_scores": [dict(row) for row in STANDARD_DIMENSIONS],
            "inclusion_criteria_met_count": 5,
            "expected_document_version": observed_version,
            "reprint_tier": "NONE",
            "permitted_marketing_use": "NO_USE",
            "reprint_copies_authorized": 0,
        },
        make_analyst_headers(lead["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_document(document)
    retried = create_inclusion(fresh, second_vendor)
    assert retried["inclusion_status"] == "UNDER_EVALUATION"

    rows, meta = validate_paginated(
        api_client.list_inclusions(
            TEST_USERS["research_director_headers"],
            params={"document_id": document["id"]},
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
