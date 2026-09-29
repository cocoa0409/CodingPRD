"""Two inclusive thresholds probed at the boundary and one unit below it.

The Rule-of-75 point gate is exercised at 75 and 74 points, and the standard
Part D net benchmark at 7450 and 7449 basis points.
"""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ACTUARY_1,
    ANALYST_1,
    make_actuary_headers,
    make_eligibility_analyst_headers,
)


def _open_year_with_both_retirees(api):
    """An OPEN plan year 2027 plus R1 (150 credited months) and R3 (143), whose
    only difference is credited service.

    Returns {"plan_year_id", "r1", "r3"} with each retiree row as created.
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    r1 = fx.make_retiree_r1(api)
    r3 = fx.make_retiree_r3(api)
    assert r1["grandfathered_group"] == "GRANDFATHERED_A"
    assert r3["grandfathered_group"] == "GRANDFATHERED_A"
    return {"plan_year_id": plan_year["id"], "r1": r1, "r3": r3}


def test_rule_of_75_is_eligible_at_exactly_seventy_five_points(api):
    """63 years of age plus 12 service years is exactly 75 points and ELIGIBLE.

    PRD 3.3: "Under `RULE_OF_75_GRANDFATHERED`, the retiree is `ELIGIBLE` when
    three conditions all hold: the sum of completed age at retirement and service
    years is at least 75 points, completed age at retirement is at least 55 years,
    and service years is at least 10. Exactly 75 points is `ELIGIBLE`." The
    determination freezes the inputs it decided on, because PRD 3.4 says
    "`age_years_at_retirement` and `service_years` record the two derived
    quantities as of the determination, `points` records their sum, and `outcome`
    records the verdict."

    Design: Difficulty/boundary_precision_check/rule_of_75_points_exactly_at_inclusive_threshold
    """
    state = _open_year_with_both_retirees(api)
    r1 = state["r1"]

    determination = validate_success(
        api.create_determination(
            f.determination_payload(r1["id"], state["plan_year_id"], r1["version"]),
            make_eligibility_analyst_headers(ANALYST_1),
        ),
        expected_status=201,
    )

    assert determination["age_years_at_retirement"] == 63
    assert determination["service_years"] == 12
    assert determination["points"] == 75
    assert determination["outcome"] == "ELIGIBLE"
    assert determination["rule_set_code"] == "RULE_OF_75_GRANDFATHERED"
    assert determination["grandfathered_group"] == "GRANDFATHERED_A"
    assert determination["status"] == "DRAFT"

    assert fx.reload_retiree(api, r1["id"])["eligibility_points"] == 75


def test_rule_of_75_is_ineligible_one_point_below_the_threshold(api):
    """143 credited months truncate to 11 service years, 74 points, INELIGIBLE.

    PRD 3.3: "**Service years** is `credited_service_months` divided by 12 and
    truncated down to a whole number, so 143 months is 11 service years and 144
    months is 12." The two subordinate gates still pass — age 63 clears 55 and 11
    service years clears 10 — so the single point shortfall is the only reason the
    verdict flips, and it is a recorded outcome rather than an error: the
    determination is created successfully with HTTP 201.

    Design: Difficulty/boundary_precision_check/rule_of_75_points_exactly_at_inclusive_threshold
    """
    state = _open_year_with_both_retirees(api)
    r3 = state["r3"]

    determination = validate_success(
        api.create_determination(
            f.determination_payload(r3["id"], state["plan_year_id"], r3["version"]),
            make_eligibility_analyst_headers(ANALYST_1),
        ),
        expected_status=201,
    )

    assert determination["service_years"] == 11
    assert determination["service_years"] != 12
    assert determination["age_years_at_retirement"] == 63
    assert determination["points"] == 74
    assert determination["outcome"] == "INELIGIBLE"
    assert determination["rule_set_code"] == "RULE_OF_75_GRANDFATHERED"

    assert fx.reload_retiree(api, r3["id"])["eligibility_points"] == 74


def _draft_egwp_option(api):
    """A DRAFT MED-WRAP option carrying seeded values of 10500 and 7800 basis
    points and a NOT_STARTED certification dimension."""
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_med_wrap(
        api, plan_year["id"], activate=False, attest=False, certify=False
    )
    assert option["status"] == "DRAFT"
    assert option["subsidy_certification_status"] == "NOT_STARTED"
    assert option["rx_gross_value_bps"] == 10500
    assert option["rx_net_value_bps"] == 7800
    assert option["attested_by_user_id"] is None
    return option


def test_net_equivalence_test_fails_one_basis_point_below_the_benchmark(api):
    """A net value of 7449 basis points is refused and writes nothing.

    PRD 3.2: "The net test compares the attested net value against the standard
    Part D net value of 7450 basis points, and `net_test_passed` is true when the
    attested net value is at least that benchmark." The gross value is held at
    exactly 10000, which passes its own inclusive test, so the reported failure
    must be the net one: PRD 2.8 rung 27 reads "For an employer-group-waiver
    option, the attested net prescription-drug value is at least the standard net
    benchmark, evaluated only after the gross test has passed →
    `ERR_ACTUARIAL_NET_TEST_FAILED` (422), on attestation."

    Design: Difficulty/boundary_precision_check/part_d_net_value_exactly_at_inclusive_threshold
    """
    option = _draft_egwp_option(api)

    response = api.attest_plan_option(
        option["id"],
        f.attest_payload(10000, 7449),
        make_actuary_headers(ACTUARY_1),
    )

    error = validate_error(
        response, ApiErrorId.ERR_ACTUARIAL_NET_TEST_FAILED.value, expected_status=422
    )
    assert error["error_id"] != ApiErrorId.ERR_ACTUARIAL_GROSS_TEST_FAILED.value

    unchanged = fx.reload_plan_option(api, option["id"])
    assert unchanged["subsidy_certification_status"] == "NOT_STARTED"
    assert unchanged["rx_net_value_bps"] == 7800
    assert unchanged["rx_gross_value_bps"] == 10500
    assert unchanged["attested_by_user_id"] is None


def test_net_equivalence_test_passes_at_exactly_the_benchmark_with_zero_margin(api):
    """A net value of exactly 7450 passes and records a signed margin of 0.

    PRD 3.2: "Both thresholds are inclusive: an attested net value of exactly 7450
    basis points passes and yields an `equivalence_margin_bps` of exactly 0." The
    successful attestation is also a write: "A successful attestation writes
    `gross_test_passed`, `net_test_passed` and `equivalence_margin_bps`, records
    `attested_by_user_id` as the acting `Actuary`'s `X-User-ID`, and moves
    `subsidy_certification_status` to `ATTESTED`." The attested figures overwrite
    the 10500 and 7800 seeded at creation, and the availability dimension is
    untouched, so the option is still DRAFT.

    Design: Difficulty/boundary_precision_check/part_d_net_value_exactly_at_inclusive_threshold
    """
    option = _draft_egwp_option(api)

    attested = validate_success(
        api.attest_plan_option(
            option["id"],
            f.attest_payload(10000, 7450),
            make_actuary_headers(ACTUARY_1),
        ),
        expected_status=200,
    )

    assert attested["gross_test_passed"] is True
    assert attested["net_test_passed"] is True
    assert attested["equivalence_margin_bps"] == 0
    assert attested["subsidy_certification_status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == ACTUARY_1
    assert attested["rx_gross_value_bps"] == 10000
    assert attested["rx_net_value_bps"] == 7450
    assert attested["status"] == "DRAFT"
