"""Combinatorial formula tests (PRD §3.7 neglect scoring and proration
rounding order, §3.9 reman invoice evaluation order).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    ApiErrorId,
    add_maintenance_record,
    adjudicate,
    assert_claim_financials_balance,
    assert_fleet,
    assert_reman_order,
    assert_service_center,
    assert_warranty_claim,
    grade_core,
    ingest_snapshot,
    make_service_advisor_headers,
    make_warranty_adjudicator_headers,
    set_logical_clock,
    setup_claim_under_review,
    setup_engine_unit,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    setup_reman_order_core_received,
    validate_error,
    validate_success,
)

CLAIM_CLOCK = "2026-12-01T00:00:00Z"  # 91 whole days after in-service 2026-09-01


def _environment_with_neglected_unit(serial, miles, hours, def_odometer, def_gal):
    """Canonical program plus one unit whose history carries zero OIL_CHANGE
    records, one DEF_SERVICE with def_quality_ok false, and no CRITICAL-fault
    snapshots. The neglect score lands wherever the mileage puts it."""
    env = setup_full_environment()
    family, fleet = env["family"], env["fleet"]
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number=serial)
    ingest_snapshot(
        unit["id"], recorded_at="2026-10-15T00:00:00Z", odometer_miles=miles,
        engine_hours=hours, fault_codes=[], def_consumption_gal=def_gal,
        nox_sensor_drift_ppm=5,
    )
    add_maintenance_record(
        unit["id"], fleet_id=fleet["id"], performed_at="2026-10-20T00:00:00Z",
        maintenance_type="DEF_SERVICE", odometer_at_service=def_odometer,
        def_quality_ok=False,
    )
    set_logical_clock(CLAIM_CLOCK)
    return env, unit


def _claim_under_review(env, unit, component_class, failure_code, amount):
    return setup_claim_under_review(
        unit, env["center"], failed_component_class=component_class,
        failure_code=failure_code, claimed_amount_cents=amount,
    )


# ---------------------------------------------------------------------------
# neglect score tiered band gating (score 65 -> DENY band)
# ---------------------------------------------------------------------------
def test_approve_full_rejected_when_neglect_score_in_deny_band(api, admin_headers):
    """PRD §3.7: "The score bands are binding on the decision: a score below 30 is consistent only with an `APPROVE_FULL` decision; a score of at least 30 and below 60 is consistent only with `APPROVE_PARTIAL`; a score of at least 60 is consistent only with `DENY_NEGLECT`."
    PRD §3.7: "A `decision` that falls outside its band is rejected with `ERR_DECISION_INCONSISTENT_WITH_SCORE` (HTTP 422)."
    PRD §3.7: "Expected oil changes are the unit's `accumulated_miles` divided by the 15,000-mile maintenance interval, floored to a whole number; missed oil changes are that expectation minus the count of the unit's `OIL_CHANGE` records, and never less than zero."

    35000 miles -> floor(35000 / 15000) = 2 missed oil changes (50 points) plus
    one bad DEF_SERVICE (15 points) = 65, inside the DENY band, so APPROVE_FULL
    is rejected and the claim stays UNDER_REVIEW.

    Design: Difficulty/combinatorial_formula/neglect_score_tiered_band_gating
    """
    env, unit = _environment_with_neglected_unit("UN-401", 35000, 700, 33000, 80.0)
    claim = _claim_under_review(env, unit, "EGR_SYSTEM", "FC-egr", 60000)

    resp = api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE_FULL"},
        make_warranty_adjudicator_headers(ADJUDICATOR_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_INCONSISTENT_WITH_SCORE)

    claim_now = validate_success(api.get_warranty_claim(claim["id"], admin_headers))
    assert claim_now["status"] == "UNDER_REVIEW", (
        f"a rejected decision must not move the claim, got {claim_now['status']}"
    )


def test_deny_neglect_decision_succeeds_and_increments_fleet_count(api, admin_headers):
    """PRD §3.7: "On `DENY_NEGLECT` the claim moves to `DENIED_NEGLECT` with `approved_amount_cents` set to 0 and `customer_share_cents` equal to the full `claimed_amount_cents`."
    PRD §3.7: "The unit's fleet has its `neglect_denial_count` incremented by 1 — a mutation of the fleet that increments the fleet's `version` — and when that count reaches 3, the fleet transitions from `ACTIVE` to `SUSPENDED`, a second fleet mutation within the same adjudication request."
    PRD §3.7: "Each missed oil change contributes 25 points. Each `DEF_SERVICE` record with `def_quality_ok` set false contributes 15 points. Each telematics snapshot whose `fault_codes` contain at least one `CRITICAL` entry contributes 20 points. The score is the sum, capped at 100."

    After the out-of-band APPROVE_FULL is rejected, DENY_NEGLECT on the same
    score-65 claim succeeds; the fleet's first denial leaves it ACTIVE (below
    the suspension threshold of 3).

    Design: Difficulty/combinatorial_formula/neglect_score_tiered_band_gating
    """
    env, unit = _environment_with_neglected_unit("UN-401", 35000, 700, 33000, 80.0)
    claim = _claim_under_review(env, unit, "EGR_SYSTEM", "FC-egr", 60000)

    rejected = api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE_FULL"},
        make_warranty_adjudicator_headers(ADJUDICATOR_USER_ID),
    )
    validate_error(rejected, ApiErrorId.ERR_DECISION_INCONSISTENT_WITH_SCORE)

    decided = adjudicate(claim["id"], "DENY_NEGLECT")
    assert_warranty_claim(decided)
    assert decided["status"] == "DENIED_NEGLECT"
    assert decided["neglect_score"] == 65, (
        f"2 missed intervals x 25 + 1 bad DEF x 15 = 65, got {decided['neglect_score']}"
    )
    assert decided["approved_amount_cents"] == 0
    assert decided["customer_share_cents"] == 60000
    assert_claim_financials_balance(decided)

    fleet_now = validate_success(api.get_fleet(env["fleet"]["id"], admin_headers))
    assert_fleet(fleet_now)
    assert fleet_now["neglect_denial_count"] == 1, (
        f"one denial increments the count to 1, got {fleet_now['neglect_denial_count']}"
    )
    assert fleet_now["status"] == "ACTIVE", (
        f"count 1 is below the suspension threshold 3, got {fleet_now['status']}"
    )


# ---------------------------------------------------------------------------
# proration pinned rounding order (rate rounded first, then multiplied)
# ---------------------------------------------------------------------------
def test_partial_proration_rounds_daily_rate_before_multiplying(api, admin_headers):
    """PRD §3.7: "On `APPROVE_PARTIAL` the claim moves to `APPROVED_PARTIAL` after a proration whose variant is selected by the stamped `coverage_variant`, with a pinned rounding order — the per-unit rate is rounded first, then multiplied."
    PRD §2.6: "All monetary amounts are represented as integer cents; every monetary computation rounds half-up to whole cents at each rounding step the business narrative names, and where a calculation contains several rounding steps the narrative pins their order, because rounding a rate before multiplying is deliberately not the same as multiplying first and rounding the product."

    Claimed 99991 over a 730-day term with 91 elapsed days: the pinned order
    rounds the daily rate first — round_half_up(99991 / 730) = 137 — then
    multiplies, giving 12467; the multiply-first alternative
    round_half_up(99991 x 91 / 730) = 12465 is the forbidden order.

    Design: Difficulty/combinatorial_formula/proration_daily_rate_rounding_order
    """
    env, unit = _environment_with_neglected_unit("UN-402", 15000, 400, 14000, 40.0)
    claim = _claim_under_review(env, unit, "ENGINE_BASE", "FC-base", 99991)

    decided = adjudicate(claim["id"], "APPROVE_PARTIAL")
    assert_warranty_claim(decided)
    assert decided["neglect_score"] == 40, (
        f"1 missed interval x 25 + 1 bad DEF x 15 = 40, got {decided['neglect_score']}"
    )
    assert decided["customer_share_cents"] == 12467, (
        "rate-first rounding: round_half_up(99991/730) = 137, 137 x 91 = 12467; "
        f"got {decided['customer_share_cents']}"
    )
    assert decided["customer_share_cents"] != 12465, (
        "12465 is the multiply-first order the PRD forbids"
    )
    assert decided["approved_amount_cents"] == 87524, (
        f"99991 - 12467 = 87524, got {decided['approved_amount_cents']}"
    )


def test_partial_proration_share_capped_at_half_and_money_balances(api, admin_headers):
    """PRD §3.7: "Under both variants the share is then capped: the cap is half of `claimed_amount_cents` rounded half-up to whole cents, `customer_share_cents` is the smaller of the raw share and the cap, and `approved_amount_cents` is the remainder of the claim after the customer share."
    PRD §3.7: "The base warranty window is open when the logical clock is strictly earlier than the unit's `in_service_date` plus the standard's `base_warranty_years` calendar years, and the unit's `accumulated_miles` is strictly less than the standard's `base_warranty_miles`; engine hours play no part in the base window."

    The raw share 12467 is below the cap round_half_up(99991 x 0.5) = 49996, so
    the raw share stands; approved is the remainder and the claim's money adds
    back up to the claimed amount.

    Design: Difficulty/combinatorial_formula/proration_daily_rate_rounding_order
    """
    env, unit = _environment_with_neglected_unit("UN-402", 15000, 400, 14000, 40.0)
    claim = _claim_under_review(env, unit, "ENGINE_BASE", "FC-base", 99991)

    decided = adjudicate(claim["id"], "APPROVE_PARTIAL")
    assert decided["status"] == "APPROVED_PARTIAL"
    assert decided["coverage_variant"] == "BASE_WARRANTY", (
        f"ENGINE_BASE can only carry BASE_WARRANTY, got {decided['coverage_variant']}"
    )
    assert decided["customer_share_cents"] == 12467
    assert decided["customer_share_cents"] < 49996, (
        "the raw share is below the half-of-claimed cap, so the cap does not bind"
    )
    assert decided["approved_amount_cents"] == 87524
    assert_claim_financials_balance(decided)


# ---------------------------------------------------------------------------
# reman invoice evaluation order (surcharge -> effective price -> cap -> total)
# ---------------------------------------------------------------------------
def _plus_component_order_received(env, unit):
    """QUOTED -> AWAITING_CORE -> CORE_RECEIVED for a COMPONENT/TURBO order at
    spec_level PLUS, quoted price 400000, quoted core value 300000."""
    return setup_reman_order_core_received(
        unit["id"], env["center"]["id"], reman_scope="COMPONENT",
        component_type="TURBO", spec_level="PLUS", quoted_price_cents=400000,
        quoted_core_value_cents=300000, expected_core_return_by="2027-03-01T00:00:00Z",
    )


def test_final_core_credit_capped_against_effective_price_with_surcharge(api, admin_headers):
    """PRD §3.9: "First the `spec_level_surcharge_cents`: the `quoted_price_cents` multiplied by the spec-level multiplier minus one, rounded half-up to whole cents, where the multiplier is 1.0 for `STANDARD` (a surcharge of zero), 1.15 for `PLUS`, and 1.3 for `PREMIUM`."
    PRD §3.9: "The cap is computed against the effective price including the spec-level surcharge, never against the bare quoted price — that alternative order is expressly forbidden."

    PLUS surcharge round_half_up(400000 x 0.15) = 60000, effective price
    460000; grade A value 300000 exceeds the cap round_half_up(460000 x 0.4) =
    184000, so the final credit is 184000 — not the 160000 a bare-price cap
    would give.

    Design: Difficulty/combinatorial_formula/reman_invoice_evaluation_order
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-403")
    set_logical_clock(CLAIM_CLOCK)

    order = _plus_component_order_received(env, unit)
    assert order["spec_level_surcharge_cents"] == 60000, (
        f"round_half_up(400000 x 0.15) = 60000, got {order['spec_level_surcharge_cents']}"
    )
    assert order["provisional_core_credit_cents"] == 180000, (
        f"round_half_up(300000 x 0.6) = 180000, got {order['provisional_core_credit_cents']}"
    )

    graded = grade_core(order["id"], "A")
    assert_reman_order(graded)
    assert graded["status"] == "CREDIT_ISSUED"
    assert graded["final_core_credit_cents"] == 184000, (
        "cap against effective price: round_half_up(460000 x 0.4) = 184000 binds; "
        f"got {graded['final_core_credit_cents']}"
    )
    assert graded["final_core_credit_cents"] != 160000, (
        "160000 is the bare-price cap the PRD expressly forbids"
    )


def test_invoice_total_is_effective_price_minus_final_credit(api, admin_headers):
    """PRD §3.9: "The `invoice_total_cents` is then the effective price minus the final credit."
    PRD §3.9: "The center's ledger absorbs the difference: `core_credit_balance_cents` moves by the final credit minus the provisional credit, with the center's `version` incrementing."

    Invoice total 460000 - 184000 = 276000; the ledger walks 180000 (provisional
    posted at confirm) to 184000 (delta 4000 at grading).

    Design: Difficulty/combinatorial_formula/reman_invoice_evaluation_order
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-403")
    set_logical_clock(CLAIM_CLOCK)

    order = _plus_component_order_received(env, unit)
    graded = grade_core(order["id"], "A")

    assert graded["invoice_total_cents"] == 276000, (
        f"effective price 460000 - final credit 184000 = 276000, got {graded['invoice_total_cents']}"
    )

    center_now = validate_success(api.get_service_center(env["center"]["id"], admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 184000, (
        "180000 provisional + (184000 - 180000) delta = 184000, "
        f"got {center_now['core_credit_balance_cents']}"
    )
