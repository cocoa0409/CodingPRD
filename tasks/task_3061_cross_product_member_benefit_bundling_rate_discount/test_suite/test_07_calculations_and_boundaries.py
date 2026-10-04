"""Calculated values and their boundary precision."""
from test_helpers import (
    TEST_USERS,
    create_active_enrollment,
    create_adopted_holding,
    fetch_enrollment,
    fetch_member,
    post_deposit,
    register_member,
    setup_cumulative_autopay_stack,
    setup_member_near_band_boundary,
    validate_error,
    validate_success,
)


def test_the_first_band_is_earned_at_exactly_the_threshold(api):
    """PRD §2.6: "Balances of at least 1,000 dollars earn the first band of 25
    basis points; balances of at least 5,000 dollars earn the second band of 50
    basis points; balances of at least 25,000 dollars earn the third band of 75
    basis points. The highest matching band wins, and every band's lower bound is
    inclusive, so a balance of exactly 1,000 dollars earns the first band while a
    balance one cent below earns nothing."

    Design: Difficulty/boundary_precision_check/deposit_balance_band_boundary_at_exactly_the_minimum
    """
    setup = setup_member_near_band_boundary(100000, threshold=100000,
                                            with_deposit_entitlement=True)
    member = fetch_member(setup["member"]["id"])
    assert member["qualifying_deposit_balance_cents"] == 100000, (
        "the payroll posting credits the holding exactly to the band floor"
    )

    holding = setup["holding"]
    assert holding["deposit_rate_eligible"] is True
    assert setup["enrollment"]["status"] == "ACTIVE"


def test_one_cent_below_the_band_floor_earns_no_boost(api):
    """PRD §2.6: "Balances of at least 1,000 dollars earn the first band of 25
    basis points ... every band's lower bound is inclusive, so a balance of exactly
    1,000 dollars earns the first band while a balance one cent below earns
    nothing. When an enrolment is anything other than active the boost is zero."

    Design: Difficulty/boundary_precision_check/deposit_balance_band_boundary_at_exactly_the_minimum
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    # The BANKING holding is pre-funded one cent under the first band; a separate
    # qualifying posting (credited to no holding) activates the enrolment, so the
    # member's qualifying deposit balance lands on exactly 99,999 cents.
    member = register_member(member_number="M-CALC-05C", email="vera.c.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 99999)
    create_active_enrollment(
        member["id"], required_monthly_amount_cents=100000,
        amount_cents=100000, posted_at="2026-09-01T00:00:00Z", holding_id=None,
    )

    below = fetch_member(member["id"])
    assert below["qualifying_deposit_balance_cents"] == 99999
    projection = validate_success(api.get_deposit_rate_projection(
        member["id"], TEST_USERS["platform_admin_headers"]))
    assert projection["current_boost_bps"] == 0, (
        "one cent below the inclusive first-band floor earns no boost"
    )

    exact = setup_member_near_band_boundary(100000, threshold=100000)
    assert exact["member"]["qualifying_deposit_balance_cents"] == 100000
    assert exact["member"]["qualifying_deposit_balance_cents"] - 1 == 99999
    assert holding["id"]  # the pre-funded holding is the premise of the reading


def test_an_inactive_enrollment_yields_no_deposit_boost_at_any_balance(api):
    """PRD §2.6: "When an enrolment is anything other than active the boost is
    zero."
    PRD §2.4: "`deposit_rate_eligible` is true only when the holding's product
    line is `BANKING`, its adoption status is `ADOPTED`, and the member's
    direct-deposit enrolment is `ACTIVE`."

    Design: Corner/calculations/deposit_rate_boost_uses_the_highest_matching_band_not_a_marginal_sum
    """
    member = register_member(member_number="M-CALC-05B", email="vera.c.b@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 0)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    post_deposit(member["id"], enrollment["id"], 2600000, "2026-09-01T00:00:00Z",
                 holding_id=holding["id"])
    # The enrolment is still PENDING_VERIFICATION, so it prices nothing.
    current = fetch_enrollment(enrollment["id"])
    assert current["status"] == "PENDING_VERIFICATION"
    assert fetch_member(member["id"])["qualifying_deposit_balance_cents"] == 2600000

    activated = validate_success(api.activate_enrollment(enrollment["id"],
                                                         TEST_USERS["platform_admin_headers"]))
    assert activated["status"] == "ACTIVE"
    assert activated["required_monthly_amount_cents"] == 100000


def test_the_member_tier_feeds_the_stack_through_the_top_down_threshold_rule(api):
    """PRD §2.4: "Tier is derived from adoption breadth by a top-down threshold
    rule; the first clause satisfied determines the result."
    PRD §3.5: "The surviving magnitudes are summed and the sum is capped at 400
    basis points; the capped value is what the loan stores as its discount stack."

    Design: Difficulty/combinatorial_formula/member_tier_then_base_apr_evaluation_order_pins_the_final_apr
    """
    setup = setup_cumulative_autopay_stack(base_apr_bps=1200, base_bps=250, autopay_bps=75)
    member = fetch_member(setup["member"]["id"])
    assert member["member_tier"] == "PLUS"
    assert member["product_adoption_count"] == 2
    assert member["product_line_set"] == ["LENDING", "BANKING"]

    loan = setup["loan"]
    assert loan["discount_stack_bps"] == 325
    assert loan["effective_apr_bps"] == 875


def test_the_consecutive_month_run_resets_on_a_non_qualifying_month(api):
    """PRD §2.6: "The computed `consecutive_qualifying_months` counts the
    maximal trailing run of consecutive calendar months, ending at the logical
    month containing the current logical instant, in which the enrolment's
    posted deposits met `required_monthly_amount_cents`."

    Design: Corner/calculations/consecutive_qualifying_months_resets_on_a_single_non_qualifying_month
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-CALC-06", email="wes.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 500000)
    enrollment = create_active_enrollment(
        member["id"], required_monthly_amount_cents=100000,
        amount_cents=200000, posted_at="2026-09-01T00:00:00Z", holding_id=holding["id"],
    )

    # October and November carry no posting at all, and December — the month
    # containing the current instant — is unfunded too.
    validate_success(api.set_current_utc({"current_utc": "2026-12-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    after = fetch_enrollment(enrollment["id"])
    assert after["consecutive_qualifying_months"] == 0, (
        "the run ends at the logical month containing the current instant; that "
        "month is unfunded, so the trailing run is zero"
    )
    assert after["requalification_due_at"] == "2026-12-01T00:00:00Z", (
        "the first instant three whole logical months after the qualification instant"
    )


def test_an_early_cycle_evaluation_is_refused_on_the_temporal_precondition(api):
    """PRD §3.6: "An operator evaluates an open cycle, and the evaluation cannot
    occur before the cycle's `due_at`; an attempt beforehand is refused with
    `ERR_REQUALIFICATION_WINDOW_OPEN`."

    Design: Corner/state_machines/requalification_evaluate_before_due_returns_window_open
    """
    setup = setup_cumulative_autopay_stack()
    member = fetch_member(setup["member"]["id"])
    cycle = validate_success(api.open_requalification_cycle(
        member["id"], {"expected_member_version": member["version"]},
        TEST_USERS["platform_admin_headers"],
    ), expected_status=201)
    assert cycle["due_at"] == "2026-12-01T00:00:00Z"

    resp = api.evaluate_cycle(cycle["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_REQUALIFICATION_WINDOW_OPEN", expected_status=409)

    still = validate_success(api.get_requalification_cycle(cycle["id"],
                                                           TEST_USERS["platform_admin_headers"]))
    assert still["status"] == "OPEN"
    assert still["evaluated_at"] is None


def test_a_cycle_short_of_the_required_months_evaluates_to_failed(api):
    """PRD §3.6: "When the qualifying month count falls short of 3, the cycle is
    marked `FAILED`: every finally priced loan of the member falls back to
    `PROVISIONAL` and is repriced, every granted loan-rate-discount entitlement
    of the member is demoted to `PENDING_REQUALIFICATION`, and the churn score is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/loan_finalize_requires_the_latest_requalification_cycle_passed
    """
    validate_success(api.set_current_utc({"current_utc": "2026-06-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-3061-013", email="mila.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "REFINANCE",
         "principal_cents": 2500000, "base_apr_bps": 1150},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    assert loan["pricing_status"] == "PROVISIONAL"

    fresh = fetch_member(member["id"])
    cycle = validate_success(api.open_requalification_cycle(
        member["id"], {"expected_member_version": fresh["version"]},
        TEST_USERS["platform_admin_headers"],
    ), expected_status=201)

    validate_success(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    evaluated = validate_success(api.evaluate_cycle(cycle["id"], TEST_USERS["platform_admin_headers"]))
    assert evaluated["status"] == "FAILED", (
        f"qualifying month count {evaluated['qualifying_month_count']} is short of the required 3"
    )


def test_a_failed_cycle_blocks_the_loan_from_finalizing(api):
    """PRD §3.5: "a loan begins `PROVISIONAL` and is promoted to `FINAL` by an
    underwriter; promotion requires that the member's most recent requalification
    cycle has passed, or that the member has no cycle at all, and that the member
    is `MEMBER_ACTIVE` or `MEMBER_AT_RISK`."

    Design: Difficulty/cross_entity_state_dependency/loan_finalize_requires_the_latest_requalification_cycle_passed
    """
    validate_success(api.set_current_utc({"current_utc": "2026-06-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-3061-013B", email="mila.c.b@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "REFINANCE",
         "principal_cents": 2500000, "base_apr_bps": 1150},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    fresh = fetch_member(member["id"])
    cycle = validate_success(api.open_requalification_cycle(
        member["id"], {"expected_member_version": fresh["version"]},
        TEST_USERS["platform_admin_headers"],
    ), expected_status=201)
    validate_success(api.set_current_utc({"current_utc": "2026-09-02T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    assert validate_success(api.evaluate_cycle(cycle["id"],
                                               TEST_USERS["platform_admin_headers"]))["status"] == "FAILED"

    resp = api.finalize_pricing(loan["id"], TEST_USERS["underwriter_headers"])
    assert resp.status_code >= 400, (
        "a failed cycle blocks promotion of the loan"
    )
    after = validate_success(api.get_loan_account(loan["id"], TEST_USERS["underwriter_headers"]))
    assert after["pricing_status"] == "PROVISIONAL", (
        "the loan's own fields never decided the outcome; the cycle's status did"
    )


def test_the_member_with_no_cycle_can_still_finalize_a_loan(api):
    """PRD §3.5: "promotion requires that the member's most recent
    requalification cycle has passed, or that the member has no cycle at all,
    and that the member is `MEMBER_ACTIVE` or `MEMBER_AT_RISK`."

    Design: Difficulty/cross_entity_state_dependency/loan_finalize_requires_the_latest_requalification_cycle_passed
    """
    member = register_member(member_number="M-NOCYC", email="nocyc@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 300000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    assert validate_success(api.list_requalification_cycles(
        TEST_USERS["platform_admin_headers"],
        params={"member_id": member["id"]})) == []

    finalized = validate_success(api.finalize_pricing(loan["id"], TEST_USERS["underwriter_headers"]))
    assert finalized["pricing_status"] == "FINAL", (
        "a member with no cycle at all is admitted to promotion"
    )