"""Boundary precision tests (PRD §3.4 conformity ratio inclusive threshold,
§3.9 core return deadline inclusive boundary).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    assert_engine_family,
    assert_in_use_compliance_result,
    assert_reman_order,
    assert_service_center,
    compute_conformity_ratio,
    create_in_use_result_payload,
    forfeit_core,
    get_family,
    is_iso8601_timestamp,
    make_service_advisor_headers,
    set_logical_clock,
    setup_engine_unit,
    setup_family_in_production,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# conformity ratio: exactly 0.9000 conforms (inclusive threshold)
# ---------------------------------------------------------------------------
def test_conformity_ratio_exactly_at_threshold_conforms(api, officer_headers, admin_headers):
    """PRD §3.4: "The record's `conformity_ratio` is the passing count divided by the sample size, rounded half-up to 4 decimal places; its `outcome` is `CONFORMING` when that rounded ratio is at least 0.9 — a ratio of exactly 0.9000 conforms, because the threshold is inclusive — and `NON_CONFORMING` otherwise."
    PRD §3.4: "The family's `in_use_compliance_status` is then stamped from the latest result recorded for the family's `test_period_label`: recording order decides, never an average across results, and the stamp is a mutation of the family, so the family's `version` increments."

    9 passing out of 10 rounds to exactly 0.9000, which meets the inclusive
    threshold, and the family's standing follows the record.

    Design: Difficulty/boundary_precision_check/conformity_ratio_exactly_at_threshold_conforms
    """
    env = setup_family_in_production()
    family_id = env["family"]["id"]
    set_logical_clock("2027-06-01T00:00:00Z")

    resp = api.create_in_use_result(
        family_id,
        create_in_use_result_payload(
            test_period_label="2027-MY-Q2", sample_size=10, passing_units=9,
        ),
        officer_headers,
    )
    record = validate_success(resp, 201)
    assert_in_use_compliance_result(record)
    assert record["conformity_ratio"] == compute_conformity_ratio(9, 10) == 0.9, (
        f"round_half_up(9/10, 4) = 0.9 exactly, got {record['conformity_ratio']}"
    )
    assert record["outcome"] == "CONFORMING", (
        f"the 0.9 threshold is inclusive, got {record['outcome']}"
    )

    family_now = get_family(family_id)
    assert_engine_family(family_now)
    assert family_now["in_use_compliance_status"] == "CONFORMING", (
        f"the family is stamped from the latest record, got {family_now['in_use_compliance_status']}"
    )


def test_conformity_ratio_below_threshold_restamps_family_non_conforming(api, officer_headers, admin_headers):
    """PRD §3.4: "its `outcome` is `CONFORMING` when that rounded ratio is at least 0.9 — a ratio of exactly 0.9000 conforms, because the threshold is inclusive — and `NON_CONFORMING` otherwise."
    PRD §3.4: "This latest-result rule is what lets a confirmatory test under a repeated `test_period_label` reverse a family's standing from `NON_CONFORMING` back to `CONFORMING`, or the reverse."

    8 passing out of 9 rounds to 0.8889, below the threshold, and recording it
    after a conforming record flips the family's standing to NON_CONFORMING —
    one unit of sample mass changes the compliance posture.

    Design: Difficulty/boundary_precision_check/conformity_ratio_exactly_at_threshold_conforms
    """
    env = setup_family_in_production()
    family_id = env["family"]["id"]
    set_logical_clock("2027-06-01T00:00:00Z")

    first = validate_success(
        api.create_in_use_result(
            family_id,
            create_in_use_result_payload(
                test_period_label="2027-MY-Q2", sample_size=10, passing_units=9,
            ),
            officer_headers,
        ),
        201,
    )
    assert first["outcome"] == "CONFORMING"

    second = validate_success(
        api.create_in_use_result(
            family_id,
            create_in_use_result_payload(
                test_period_label="2027-MY-Q3", sample_size=9, passing_units=8,
            ),
            officer_headers,
        ),
        201,
    )
    assert_in_use_compliance_result(second)
    assert second["conformity_ratio"] == compute_conformity_ratio(8, 9) == 0.8889, (
        f"round_half_up(8/9, 4) = 0.8889, got {second['conformity_ratio']}"
    )
    assert second["outcome"] == "NON_CONFORMING", (
        f"0.8889 < 0.9 must not conform, got {second['outcome']}"
    )

    family_now = get_family(family_id)
    assert family_now["in_use_compliance_status"] == "NON_CONFORMING", (
        "recording order decides: the latest record stamps the family, "
        f"got {family_now['in_use_compliance_status']}"
    )


# ---------------------------------------------------------------------------
# core return deadline: exactly on the due instant is on time
# ---------------------------------------------------------------------------
def _two_confirmed_orders_due_2027_03_01():
    """Two units (UN-821/UN-822), each with a confirmed reman order quoting
    price 500000 / core 200000 (provisional 120000 posted per confirm), both
    with expected_core_return_by 2027-03-01T00:00:00Z."""
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit_a = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-821")
    unit_b = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-822")
    set_logical_clock("2026-12-01T00:00:00Z")
    order_a = setup_reman_order_awaiting_core(
        unit_a["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    order_b = setup_reman_order_awaiting_core(
        unit_b["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    return env, order_a, order_b


def test_core_received_exactly_at_return_deadline_accepted(api, admin_headers):
    """PRD §3.9: "Core receipt moves the order from `AWAITING_CORE` to `CORE_RECEIVED` and is only possible while the logical clock is at or before `expected_core_return_by` — the boundary is inclusive, so a core arriving at exactly the deadline is on time; a later arrival is rejected with `ERR_CORE_RETURN_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.9: "Receipt stamps `core_returned_at` from the clock."

    With the logical clock at exactly 2027-03-01T00:00:00Z — the order's
    expected_core_return_by instant — the receipt is accepted.

    Design: Difficulty/boundary_precision_check/core_return_exactly_on_due_date_accepted
    """
    env, order_a, order_b = _two_confirmed_orders_due_2027_03_01()
    center_id = env["center"]["id"]
    set_logical_clock("2027-03-01T00:00:00Z")

    received = validate_success(
        api.receive_core(order_a["id"], make_service_advisor_headers(center_id))
    )
    assert_reman_order(received)
    assert received["status"] == "CORE_RECEIVED", (
        f"the due instant is inside the inclusive window, got {received['status']}"
    )
    assert is_iso8601_timestamp(received["core_returned_at"]), (
        "receipt stamps core_returned_at from the logical clock"
    )


def test_core_received_one_day_late_rejected_then_forfeits(api, admin_headers):
    """PRD §3.9: "a later arrival is rejected with `ERR_CORE_RETURN_WINDOW_CLOSED` (HTTP 409)."
    PRD §3.9: "From `AWAITING_CORE`, a `ServiceAdvisor` (own center) or a `RemanPlanner` may forfeit the core, but only when the logical clock is strictly after `expected_core_return_by`; on or before the deadline the attempt is rejected with `ERR_CORE_NOT_YET_LATE` (HTTP 409)."
    PRD §3.9: "Forfeiture moves the order to `CORE_FORFEIT`, sets `final_core_credit_cents` to 0, and applies the same reversal cascade as a rejected core: the provisional credit is withdrawn from the center's balance, `core_reversal_count` increments, and the center suspends at 2 reversals."

    Order A is received on the due instant; one day later order B's receipt is
    rejected and its core is forfeited, withdrawing its 120000 provisional so
    the ledger keeps exactly order A's provisional.

    Design: Difficulty/boundary_precision_check/core_return_exactly_on_due_date_accepted
    """
    env, order_a, order_b = _two_confirmed_orders_due_2027_03_01()
    center_id = env["center"]["id"]
    advisor = make_service_advisor_headers(center_id)
    set_logical_clock("2027-03-01T00:00:00Z")
    validate_success(api.receive_core(order_a["id"], advisor))

    set_logical_clock("2027-03-02T00:00:00Z")
    late = api.receive_core(order_b["id"], advisor)
    validate_error(late, ApiErrorId.ERR_CORE_RETURN_WINDOW_CLOSED)

    forfeited = forfeit_core(order_b["id"], center_id)
    assert_reman_order(forfeited)
    assert forfeited["status"] == "CORE_FORFEIT"
    assert forfeited["final_core_credit_cents"] == 0

    center_now = validate_success(api.get_service_center(center_id, admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 120000, (
        "order A's provisional stands and order B's 120000 provisional is "
        f"withdrawn: 240000 - 120000 = 120000, got {center_now['core_credit_balance_cents']}"
    )
    assert center_now["core_reversal_count"] == 1
