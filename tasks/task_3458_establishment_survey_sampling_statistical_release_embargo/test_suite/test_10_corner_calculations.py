"""Corner coverage: calculation claims.

Base-weight precision, the variance proxy formula, factor-set tolerance
boundaries, the inclusive dominance threshold, the link-relative fallback
clause, and the fail side of the certification rate floor.
"""
from test_helpers import (
    ANALYST_USER_ID,
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    close_collection,
    collect_cycle,
    compute_estimates,
    create_cycle,
    create_factor_set,
    create_program,
    create_stratum,
    enroll,
    get_single_cell,
    lifecycle,
    make_estimation_analyst_headers,
    open_collection,
    register_establishment,
    set_clock,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)

COLLECTOR = TEST_USERS["collection_officer_headers"]
METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]


def test_base_weight_precision_six_decimals(api):
    """PRD §3.2: "the stratum's `frame_unit_count` divided by its `allocated_sample_size`, rounded half up to 6 decimal places."
    PRD §2.6: "**Rates, weights, and ratios** — `base_weight` on an enrollment, `weighted_response_rate` and `unweighted_response_rate` on a cycle, and `wedge_factor` on a cell estimate — are carried to exactly 6 decimal places, rounded half up."

    Design: Corner/calculations/base_weight_precision_six_decimals
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    est = register_establishment()
    enrollment = enroll(est["id"], "CES")
    assert enrollment["base_weight"] == 33.333333, (
        f"100/3 stored as exactly 33.333333 — not 33.33, not full "
        f"precision; got {enrollment['base_weight']}")


def test_cell_variance_formula_literal(api):
    """PRD §3.5: "The headline `employment_estimate` of a cell is the sum over respondents of `base_weight` times reported employment plus the sum over imputed nonrespondents of `base_weight` times imputed employment, rounded half up to a whole person."
    PRD §3.5: "Alongside it, `variance_estimate` carries a Horvitz–Thompson-style variance proxy: the sum, over the cell enrollments used in the estimate, of each enrollment's `base_weight` times that weight minus one times the square of its reported-or-imputed employment, rounded half up to a whole number."

    Design: Corner/calculations/cell_variance_formula_literal
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=4,
        strata=[create_stratum("MANUFACTURING", "SMALL", 40)])
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]
    cycle = collect_cycle("CES", "2026-09", panel["enrollments"],
                          {en1["id"]: 2, en2["id"]: 4, en3["id"]: 6})

    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 120, "10.0 x (2+4+6)"
    assert cell["variance_estimate"] == 5040, (
        f"SUM of 10 x 9 x y^2 = 90 x 56, got {cell['variance_estimate']}")
    assert cell["respondent_count"] == 3
    assert cell["suppression_status"] == "NONE", (
        "3 respondents meets the minimum cell size; max share 6/12 = 0.5 "
        "< 0.60")


def test_factor_mean_tolerance_exact_boundary(api):
    """PRD §3.6: "exactly 12 numbers for January through December, each within the inclusive range 0.2 to 5.0, whose arithmetic mean must lie within 1.0 plus or minus 0.0005, inclusive of the boundary. A set failing any of these constraints is rejected with `ERR_FACTOR_SET_INVALID`."

    Design: Corner/calculations/factor_mean_tolerance_exact_boundary
    """
    create_program(code="CES", sample_budget=3)

    ok = validate_success(api_client.create_factor_set(
        {"program_code": "CES", "industry_code": "MANUFACTURING",
         "size_class": "SMALL", "year": 2026,
         "factors": [1.0] * 11 + [1.0048]},
        METHODOLOGIST), 201)
    assert ok["set_status"] == "PROVISIONAL", (
        "mean 1.0004 is within 1.0 +/- 0.0005 inclusive")

    resp = api_client.create_factor_set(
        {"program_code": "CES", "industry_code": "MANUFACTURING",
         "size_class": "SMALL", "year": 2027,
         "factors": [1.0] * 11 + [1.0072]},
        METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_FACTOR_SET_INVALID)  # mean 1.0006

    resp = api_client.create_factor_set(
        {"program_code": "CES", "industry_code": "MANUFACTURING",
         "size_class": "SMALL", "year": 2028, "factors": [1.0] * 11},
        METHODOLOGIST)
    validate_error(resp, ApiErrorId.ERR_FACTOR_SET_INVALID)  # exactly 12


def test_dominance_share_exactly_at_threshold_flags_primary(api):
    """PRD §3.5: "The dominance flag is true when the largest single-establishment weighted contribution in the cell — one establishment's `base_weight` times its reported or imputed employment — reaches at least 60 percent of the cell's `employment_estimate`; the comparison is inclusive, so a contribution of exactly 60 percent is dominant, and when the cell estimate is 0 the flag is false by definition."
    PRD §3.5: "a cell is marked `PRIMARY` if and only if its `respondent_count` is below 3 — the minimum cell size — or its `dominance_flag` is true."

    Design: Corner/calculations/dominance_share_exactly_at_threshold_flags_primary
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=12,
        strata=[create_stratum("MANUFACTURING", "SMALL", 40),
                create_stratum("RETAIL", "SMALL", 40),
                create_stratum("HEALTHCARE", "SMALL", 40)])
    # allocations 4/4/4 -> weight 10.0 in each stratum
    panel = setup_enrolled_panel(
        "CES", specs=[("MANUFACTURING", "SMALL", 3),
                      ("RETAIL", "SMALL", 3),
                      ("HEALTHCARE", "SMALL", 2)])
    a1, a2, a3, b1, b2, b3, h1, h2 = panel["enrollments"]

    cycle = collect_cycle("CES", "2026-09", panel["enrollments"], {
        a1["id"]: 15, a2["id"]: 5, a3["id"]: 5,       # A: 250, share 0.6
        b1["id"]: 14, b2["id"]: 5, b3["id"]: 5,       # B: 240, share 0.583333
        h1["id"]: 3, h2["id"]: 3,                     # H: 60, 2 respondents
    })

    cell_a = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell_a["employment_estimate"] == 250
    assert cell_a["dominance_flag"] is True, (
        "150/250 == 0.60 meets the inclusive >= threshold")
    assert cell_a["suppression_status"] == "PRIMARY"

    cell_b = get_single_cell(cycle["id"], "RETAIL", "SMALL")
    assert cell_b["employment_estimate"] == 240
    assert cell_b["dominance_flag"] is False, "140/240 == 0.583333 below"
    assert cell_b["suppression_status"] == "NONE"

    cell_h = get_single_cell(cycle["id"], "HEALTHCARE", "SMALL")
    assert cell_h["employment_estimate"] == 60
    assert cell_h["suppression_status"] == "PRIMARY", (
        "respondent_count 2 < 3")
    # The SMALL column then holds exactly 2 suppressed cells, so no
    # complementary suppression fires anywhere in this compute.


def test_imputation_fallback_without_prior_uses_stratum_mean(api):
    """PRD §3.5: "Two fallbacks collapse to the simpler recipe per establishment: a cell with no matched pairs at all, and any nonrespondent without a prior-cycle `ACCEPTED` report, are imputed at `STRATUM_MEAN`."
    PRD §3.5: "During the preliminary pass the variant is `LINK_RELATIVE`."

    Design: Corner/calculations/imputation_fallback_without_prior_uses_stratum_mean
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=2)
    en1, en2 = panel["enrollments"]

    # September: only E1, E2 exist in the panel (9, 11 accepted).
    collect_cycle("CES", "2026-09", panel["enrollments"],
                  {en1["id"]: 9, en2["id"]: 11})

    # E3 joins AFTER the September close: no prior-cycle report exists.
    e3 = register_establishment()
    en3 = lifecycle(enroll(e3["id"], "CES"), "ACCEPT")

    # October: E1=10, E2=12 accepted; E3 silent.
    enrollments = panel["enrollments"] + [en3]
    cyc_oct = collect_cycle("CES", "2026-10", enrollments,
                            {en1["id"]: 10, en2["id"]: 12})

    cell = get_single_cell(cyc_oct["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 1100, (
        "E3 has no prior-cycle accepted report, so the link-relative 9 is "
        "not available; the fallback imputes the weighted respondent mean "
        f"round_half_up((10+12)/2) == 11, giving 33.333333 x 33 == 1100, "
        f"got {cell['employment_estimate']}")
    assert cell["imputation_variant"] == "LINK_RELATIVE", (
        "the pass label, even though E3 used the fallback")


def test_certify_below_threshold_rejected(api):
    """PRD §3.5: "It demands that estimates have been computed since the last close or reopen — otherwise the advance is rejected with `ERR_ESTIMATES_NOT_COMPUTED` — and that the `weighted_response_rate` reaches at least 0.600000, with a null rate treated as 0, otherwise the advance is rejected with `ERR_RESPONSE_RATE_BELOW_MINIMUM`."

    Design: Corner/calculations/certify_below_threshold_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1 = panel["enrollments"][0]

    # Only E1's report is accepted: 1 of 3, equal weights.
    cycle = collect_cycle("CES", "2026-09", panel["enrollments"],
                          {en1["id"]: 9})
    assert cycle["weighted_response_rate"] == 0.333333, (
        f"1 of 3 responded, got {cycle['weighted_response_rate']}")

    resp = api_client.advance_cycle(
        cycle["id"], {"action": "CERTIFY"},
        make_estimation_analyst_headers(ANALYST_USER_ID))
    validate_error(resp, ApiErrorId.ERR_RESPONSE_RATE_BELOW_MINIMUM)  # 422

    rows, _meta = validate_paginated(api_client.list_cycles(
        COLLECTOR, params={"program_code": "CES"}))
    assert rows[0]["cycle_status"] == "PROCESSING", "the cycle stays PROCESSING"
