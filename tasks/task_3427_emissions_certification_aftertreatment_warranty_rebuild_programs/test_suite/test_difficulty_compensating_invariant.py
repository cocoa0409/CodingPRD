"""Compensating invariant tests (PRD §3.8 bay-day occupancy restored by
cancellation, §3.9 core-credit ledger netted to zero drift by forfeiture).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    assert_engine_unit,
    assert_reman_order,
    assert_service_center,
    cancel_work_order,
    create_campaign_work_order_payload,
    forfeit_core,
    get_unit,
    grade_core,
    make_service_advisor_headers,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    setup_reman_order_core_received,
    setup_service_center,
    stamp_family_non_conforming,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# conserved quantity: occupied bay-days per day-bucket
# ---------------------------------------------------------------------------
def _single_bay_campaign():
    """Center 'Single Bay Garage' (bay_capacity_per_day 1) with a LEVEL_1
    endorsed technician and a calibrated tool; RECALL campaign CMP-6
    IN_PROGRESS over units UN-921/UN-922."""
    env = setup_family_in_production()
    family = env["family"]
    fleet = setup_fleet()
    network = setup_service_center(
        bay_capacity_per_day=1, certification_level="LEVEL_1",
        name="Single Bay Garage", region="NE",
    )
    center, tech = network["center"], network["technician"]
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-921")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-922")
    stamp_family_non_conforming(
        family["id"], test_period_label="2027-MY-Q1", sample_size=10, passing_units=8,
    )
    set_logical_clock("2026-12-15T00:00:00Z")
    campaign = setup_campaign_in_progress(
        family["id"], campaign_code="CMP-6", campaign_type="RECALL",
        defect_summary="ASC ammonia slip",
        remedy_description="Replace ASC brick", remedy_bay_days=1,
    )
    return env, fleet, center, tech, unit_a, unit_b, campaign


def _order_payload(unit, center, tech):
    return create_campaign_work_order_payload(
        engine_unit_id=unit["id"], service_center_id=center["id"],
        assigned_technician_id=tech["id"],
        scheduled_start_day="2027-03-01T00:00:00Z", bay_days=1,
    )


def test_overlapping_order_rejected_while_single_bay_occupied(api, admin_headers):
    """PRD §3.8: "For each day in that span, the system counts the center's other work orders in `SCHEDULED` or `IN_BAY` status whose own spans cover that day; the create is valid exactly when, for every day of the new span, that occupied count plus one is no greater than the center's `bay_capacity_per_day`. Days on which the span would exceed capacity reject the create with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    WO-1 occupies the center's only bay on 2027-03-01, so the identical WO-2
    on the same day is rejected.

    Design: Difficulty/compensating_invariant/bay_day_occupancy_restored_by_cancel
    """
    env, fleet, center, tech, unit_a, unit_b, campaign = _single_bay_campaign()
    wo_a = schedule_work_order(
        campaign["id"], unit_a["id"], center["id"], tech["id"],
        scheduled_start_day="2027-03-01T00:00:00Z", bay_days=1,
    )
    assert wo_a["status"] == "SCHEDULED"

    resp = api.create_campaign_work_order(
        campaign["id"], _order_payload(unit_b, center, tech),
        make_service_advisor_headers(center["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_cancelling_order_restores_bay_capacity(api, admin_headers):
    """PRD §3.8: "Work orders in `COMPLETED`, `VERIFIED`, or `CANCELLED` status occupy nothing, so completion, verification, and cancellation all release bays."
    PRD §3.8: "Cancellation is available from `SCHEDULED`, moves the order to `CANCELLED`, and releases its occupied bay-days, restoring the capacity invariant."

    After the compensating cancel of WO-1, the identical WO-2 create succeeds:
    the forward booking plus its compensation leave the 2027-03-01 day bucket
    exactly as it was, and neither unit leaves CAMPAIGN_OPEN.

    Design: Difficulty/compensating_invariant/bay_day_occupancy_restored_by_cancel
    """
    env, fleet, center, tech, unit_a, unit_b, campaign = _single_bay_campaign()
    wo_a = schedule_work_order(
        campaign["id"], unit_a["id"], center["id"], tech["id"],
        scheduled_start_day="2027-03-01T00:00:00Z", bay_days=1,
    )
    blocked = api.create_campaign_work_order(
        campaign["id"], _order_payload(unit_b, center, tech),
        make_service_advisor_headers(center["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    cancelled = cancel_work_order(wo_a["id"], center["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"the compensating cancel releases the bay, got {cancelled['status']}"
    )

    wo_b = schedule_work_order(
        campaign["id"], unit_b["id"], center["id"], tech["id"],
        scheduled_start_day="2027-03-01T00:00:00Z", bay_days=1,
    )
    assert wo_b["status"] == "SCHEDULED", (
        "the identical booking succeeds once the occupancy is restored"
    )

    for unit in (unit_a, unit_b):
        unit_now = get_unit(unit["id"])
        assert_engine_unit(unit_now)
        assert unit_now["campaign_compliance"] == "CAMPAIGN_OPEN", (
            "a cancelled booking remediates nothing; both units stay open"
        )


# ---------------------------------------------------------------------------
# conserved quantity: the center core-credit ledger in cents
# ---------------------------------------------------------------------------
def _ledger_scenario():
    """Order A (unit UN-931): price 500000, core 200000 -> provisional 120000,
    confirmed, core received, graded B -> final 150000 (delta +30000). Order B
    (unit UN-932): price 300000, core 100000 -> provisional 60000, confirmed,
    never received. Ledger walk: 0 -> 120000 -> 180000 -> 210000."""
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-931")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-932")
    set_logical_clock("2026-12-01T00:00:00Z")
    order_a = setup_reman_order_core_received(
        unit_a["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    order_b = setup_reman_order_awaiting_core(
        unit_b["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=300000, quoted_core_value_cents=100000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    graded_a = grade_core(order_a["id"], "B")
    return env, order_a, order_b, graded_a


def test_core_credit_ledger_tracks_confirm_and_grade_delta(api, admin_headers):
    """PRD §3.9: "Confirmation moves the order from `QUOTED` to `AWAITING_CORE` and posts the provisional credit: the center's `core_credit_balance_cents` increases by `provisional_core_credit_cents`, a center mutation that increments the center's `version`."
    PRD §3.9: "The center's ledger absorbs the difference: `core_credit_balance_cents` moves by the final credit minus the provisional credit, with the center's `version` incrementing."
    PRD §3.9: "Because the provisional credit is a flat 60 percent of quoted core value with no price cap, the provisional and final figures diverge whenever the grade is not `A` or the 40-percent cap binds, and the ledger delta at grading is exactly that divergence."

    Two confirms post 120000 + 60000; grading order A at B settles final
    150000 against its provisional 120000, a +30000 delta, walking the ledger
    to 210000.

    Design: Difficulty/compensating_invariant/core_credit_ledger_confirm_then_forfeit_nets_zero
    """
    env, order_a, order_b, graded_a = _ledger_scenario()
    center_id = env["center"]["id"]

    assert_reman_order(graded_a)
    assert graded_a["status"] == "CREDIT_ISSUED"
    assert graded_a["provisional_core_credit_cents"] == 120000
    assert graded_a["final_core_credit_cents"] == 150000, (
        "grade B value min(round_half_up(200000 x 0.75) = 150000, "
        f"round_half_up(500000 x 0.4) = 200000) = 150000, got {graded_a['final_core_credit_cents']}"
    )
    assert graded_a["invoice_total_cents"] == 350000

    order_b_now = validate_success(api.get_reman_order(order_b["id"], admin_headers))
    assert order_b_now["status"] == "AWAITING_CORE"
    assert order_b_now["provisional_core_credit_cents"] == 60000, (
        f"round_half_up(100000 x 0.6) = 60000, got {order_b_now['provisional_core_credit_cents']}"
    )

    center_now = validate_success(api.get_service_center(center_id, admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 210000, (
        "120000 + 60000 confirmed, +30000 grading delta = 210000, "
        f"got {center_now['core_credit_balance_cents']}"
    )
    assert center_now["core_reversal_count"] == 0


def test_compensating_forfeit_returns_ledger_to_effective_credit_sum(api, admin_headers):
    """PRD §3.9: "Forfeiture moves the order to `CORE_FORFEIT`, sets `final_core_credit_cents` to 0, and applies the same reversal cascade as a rejected core: the provisional credit is withdrawn from the center's balance, `core_reversal_count` increments, and the center suspends at 2 reversals."
    PRD §3.9: "From `AWAITING_CORE`, a `ServiceAdvisor` (own center) or a `RemanPlanner` may forfeit the core, but only when the logical clock is strictly after `expected_core_return_by`; on or before the deadline the attempt is rejected with `ERR_CORE_NOT_YET_LATE` (HTTP 409)."

    One day past the deadline, forfeiting order B withdraws exactly its 60000
    provisional: the ledger returns to 150000 — precisely order A's final
    credit, the sum over non-reversed orders — with zero drift, and the single
    reversal leaves the center AUTHORIZED.

    Design: Difficulty/compensating_invariant/core_credit_ledger_confirm_then_forfeit_nets_zero
    """
    env, order_a, order_b, graded_a = _ledger_scenario()
    center_id = env["center"]["id"]
    set_logical_clock("2027-03-02T00:00:00Z")

    forfeited = forfeit_core(order_b["id"], center_id)
    assert_reman_order(forfeited)
    assert forfeited["status"] == "CORE_FORFEIT"
    assert forfeited["final_core_credit_cents"] == 0

    center_now = validate_success(api.get_service_center(center_id, admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 150000, (
        "the compensating forfeit removes exactly the 60000 provisional: "
        "210000 - 60000 = 150000, equal to order A's final credit; "
        f"got {center_now['core_credit_balance_cents']}"
    )
    assert center_now["core_reversal_count"] == 1, (
        f"one reversal is below the suspension threshold 2, got {center_now['core_reversal_count']}"
    )
    assert center_now["auth_status"] == "AUTHORIZED"
