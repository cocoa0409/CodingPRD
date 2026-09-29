"""Refusals that guard payroll, the remake grace, driver qualification, insurance
at commitment, the cash-conservation identity, the delivery-area window and the
two identity headers.

Every test here fires exactly one refusal through the documented endpoint and then
proves the refusal was silent: the entity the call named is re-read and shown not
to have moved its status or its ``version``, and no child record or reimbursement
ledger line was written. Where the rule draws a strict boundary the neighbouring
value that must be accepted is pinned alongside it, so the tests separate "inside
the window" from "on the window's edge".
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import (
    DEFAULT_CLOCK,
    MVR_POINTS_MAX,
    NOON_CLOCK,
    REMAKE_GRACE_MINUTES,
    SAFE_DROP_VOID_WINDOW_SECONDS,
)
from test_helpers.test_users import (
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    DISPATCHER_HEADERS,
    SECOND_COMPLIANCE_HEADERS,
    SECOND_COMPLIANCE_OFFICER_USER_ID,
    headers_for,
    make_driver_headers,
    make_manager_headers,
)

PLANNED_DEPART_AT = "2026-08-05T12:05:00Z"
UNKNOWN_STORE_ID = "00000000-0000-0000-0000-000000000000"


def _deliver_one_order(
    door_arrival_at,
    actual_miles=3.4,
    order_overrides=None,
    store_overrides=None,
    driver_overrides=None,
):
    """Take one order to a knocked-on door at a chosen instant.

    The order is placed at noon against a 30-minute promise and the driver leaves
    at 12:05, so the door instant alone decides the order-to-door stopwatch. Cash
    is handed over only when the order was taken as a cash order.
    """
    world = fx.setup_route(
        "EN_ROUTE",
        ("A",),
        planned_depart_at=PLANNED_DEPART_AT,
        order_overrides=order_overrides,
        clock=NOON_CLOCK,
        store_overrides=store_overrides,
        driver_overrides=driver_overrides,
    )
    order = world["orders"][0]
    cash = order["total_charge_cents"] if order["payment_method"] == "CASH" else None
    fx.set_clock(door_arrival_at)
    fx.arrive_at_door(
        world["dispatch"]["id"],
        world["stops"][0]["id"],
        world["driver"]["id"],
        actual_miles,
        cash,
    )
    world["orders"] = [fx.read_order(o["id"]) for o in world["orders"]]
    world["stops"] = fx.list_route_stops(world["dispatch"]["id"])
    world["dispatch"] = fx.read_dispatch(world["dispatch"]["id"])
    return world


def test_settling_a_route_whose_delivered_stop_has_no_odometer_reading_is_refused():
    """Payroll refuses a checked-in route whose delivered stop never had its mileage read.

    PRD: "Every stop whose status is `DELIVERED` or `REMADE` must have an `actual_miles` reading on file, or settlement is refused with `ERR_ODOMETER_MISSING` — the actual variant of the waterfall is undefined without every odometer reading, and the service refuses rather than silently falling back to planned mileage."
    Design: Corner/validations/settling_a_route_with_a_missing_odometer_reading_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:36:00Z", actual_miles=None)
    dispatch_id = world["dispatch"]["id"]
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    manager_headers = make_manager_headers(store_id)

    stop = world["stops"][0]
    assert stop["status"] == "DELIVERED"
    assert stop["actual_miles"] is None

    returned = fx.check_in_route(dispatch_id, driver_id)
    assert returned["status"] == "RETURNED"

    validate_error(
        api_client.settle_dispatch(dispatch_id, manager_headers),
        ApiErrorId.ERR_ODOMETER_MISSING.value,
    )

    after = fx.read_dispatch(dispatch_id)
    assert after["status"] == "RETURNED"
    assert after["version"] == returned["version"]
    assert after["actual_reimbursement_cents"] is None
    assert after["reimbursement_variance_cents"] is None
    assert after["estimated_reimbursement_cents"] == 336

    lines = fx.list_route_lines(dispatch_id, manager_headers)
    assert [line["line_type"] for line in lines] == ["PROVISIONAL_STOP"]
    assert lines[0]["status"] == "PROVISIONAL"

    order = fx.read_order(world["orders"][0]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settlement_status"] == "CHARGED"
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 0


def test_settling_a_route_once_every_odometer_reading_is_on_file_is_accepted():
    """The same payroll run goes through as soon as the delivered stop carries its mileage.

    PRD: "Every stop whose status is `DELIVERED` or `REMADE` must have an `actual_miles` reading on file, or settlement is refused with `ERR_ODOMETER_MISSING` — the actual variant of the waterfall is undefined without every odometer reading, and the service refuses rather than silently falling back to planned mileage."
    Design: Corner/validations/settling_a_route_with_a_missing_odometer_reading_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:36:00Z", actual_miles=3.4)
    dispatch_id = world["dispatch"]["id"]
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    manager_headers = make_manager_headers(store_id)

    stop = world["stops"][0]
    assert stop["status"] == "DELIVERED"
    assert stop["actual_miles"] == 3.4

    fx.check_in_route(dispatch_id, driver_id)
    settled = validate_success(api_client.settle_dispatch(dispatch_id, manager_headers), 200)
    assert settled["status"] == "SETTLED"
    expected_actual = a.expected_reimbursement_from_model([3.4], world["cost_model"])
    assert settled["actual_reimbursement_cents"] == expected_actual == 361
    assert settled["reimbursement_variance_cents"] == 361 - 336

    lines = fx.list_route_lines(dispatch_id, manager_headers)
    assert sorted(line["line_type"] for line in lines) == ["ACTUAL_STOP", "PROVISIONAL_STOP"]
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 361


def test_a_late_remake_at_exactly_the_grace_boundary_is_refused():
    """A 30-minute promise handed over at 35 gross minutes is still inside the grace.

    PRD: "And when the `reason` given is `LATE`, the order's `order_to_door_gross_minutes` must be **strictly greater** than its `promise_minutes_snapshot` plus a 5-minute grace allowance, or the request is refused with `ERR_REMAKE_NOT_ELIGIBLE`; against a 30-minute promise, exactly 35 gross minutes is inside the grace and is refused, and only 36 or more qualifies."
    Design: Corner/validations/remake_at_the_grace_boundary_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:35:00Z")
    store_id = world["store"]["id"]
    order = world["orders"][0]

    assert order["promise_minutes_snapshot"] == 30
    assert order["order_to_door_gross_minutes"] == 35
    assert order["order_to_door_gross_minutes"] == (
        order["promise_minutes_snapshot"] + REMAKE_GRACE_MINUTES
    )
    assert order["order_to_door_net_minutes"] == 35

    validate_error(
        api_client.remake_order(
            order["id"], f.remake_payload("LATE"), make_manager_headers(store_id)
        ),
        ApiErrorId.ERR_REMAKE_NOT_ELIGIBLE.value,
    )

    after = fx.read_order(order["id"])
    assert after["version"] == order["version"]
    assert after["fulfillment_status"] == "DELIVERED"
    assert after["settlement_status"] == "CHARGED"
    assert after["remake_count"] == 0
    assert after["remake_credit_cents"] == 0
    assert after["remake_hold_minutes"] == 0
    assert after["door_arrival_at"] == order["door_arrival_at"]
    assert after["order_to_door_gross_minutes"] == 35
    assert fx.read_stop(world["stops"][0]["id"])["status"] == "DELIVERED"


def test_a_late_remake_one_minute_past_the_grace_boundary_is_accepted():
    """The same order handed over at 36 gross minutes qualifies for the remake.

    PRD: "And when the `reason` given is `LATE`, the order's `order_to_door_gross_minutes` must be **strictly greater** than its `promise_minutes_snapshot` plus a 5-minute grace allowance, or the request is refused with `ERR_REMAKE_NOT_ELIGIBLE`; against a 30-minute promise, exactly 35 gross minutes is inside the grace and is refused, and only 36 or more qualifies."
    Design: Corner/validations/remake_at_the_grace_boundary_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:36:00Z")
    store_id = world["store"]["id"]
    order = world["orders"][0]
    assert order["order_to_door_gross_minutes"] == 36

    remade = validate_success(
        api_client.remake_order(
            order["id"], f.remake_payload("LATE"), make_manager_headers(store_id)
        ),
        200,
    )
    assert remade["fulfillment_status"] == "REMAKE_QUEUED"
    assert remade["settlement_status"] == "ADJUSTED"
    assert remade["remake_count"] == 1
    assert remade["remake_credit_cents"] == 2200
    assert remade["door_arrival_at"] is None
    assert remade["order_to_door_gross_minutes"] is None
    assert remade["order_to_door_net_minutes"] is None
    assert remade["remake_hold_minutes"] == 0
    assert remade["version"] == order["version"] + 1
    assert fx.read_stop(world["stops"][0]["id"])["status"] == "REMADE"


INSURANCE_TO_DECEMBER = {"policy_number": "POL-9001", "coverage_to": "2026-12-01T00:00:00Z"}


def _driver_awaiting_a_decision(violation_points=0, result="CLEAR", mvr_headers=None):
    """Hire a driver and put a record pull and an active certificate on file, so that
    the qualification decision is the only step left."""
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    pull = fx.record_mvr_check(
        driver["id"],
        mvr_headers or COMPLIANCE_HEADERS,
        result=result,
        violation_points=violation_points,
        checked_on="2026-08-01T00:00:00Z",
    )
    fx.file_insurance(driver["id"], COMPLIANCE_HEADERS, **INSURANCE_TO_DECEMBER)
    return store, fx.read_driver(driver["id"]), pull


def test_qualifying_a_driver_carrying_six_violation_points_is_refused():
    """Six points on the newest record pull breaks the qualification ceiling.

    PRD: "The driver's `mvr_points_latest` must be at most 5 — exactly 5 passes, 6 is refused with `ERR_MVR_POINTS_EXCEEDED`."
    Design: Corner/validations/qualifying_a_driver_with_six_mvr_points_is_rejected
    """
    _store, driver, pull = _driver_awaiting_a_decision(
        violation_points=MVR_POINTS_MAX + 1, result="MINOR_VIOLATIONS"
    )
    assert pull["result"] == "MINOR_VIOLATIONS"
    assert driver["qualification_status"] == "PENDING_CHECKS"
    assert driver["mvr_points_latest"] == 6
    assert driver["insurance_status"] == "VERIFIED"

    validate_error(
        api_client.create_qualification_decision(
            driver["id"], f.qualification_decision_payload("QUALIFY"), SECOND_COMPLIANCE_HEADERS
        ),
        ApiErrorId.ERR_MVR_POINTS_EXCEEDED.value,
    )

    after = fx.read_driver(driver["id"])
    assert after["qualification_status"] == "PENDING_CHECKS"
    assert after["qualified_by_user_id"] is None
    assert after["version"] == driver["version"]
    assert after["insurance_status"] == "VERIFIED"
    assert after["mvr_points_latest"] == 6


def test_qualifying_a_driver_carrying_exactly_five_violation_points_is_accepted():
    """Exactly five points sits on the ceiling and still qualifies.

    PRD: "The driver's `mvr_points_latest` must be at most 5 — exactly 5 passes, 6 is refused with `ERR_MVR_POINTS_EXCEEDED`."
    Design: Corner/validations/qualifying_a_driver_with_six_mvr_points_is_rejected
    """
    _store, driver, _pull = _driver_awaiting_a_decision(
        violation_points=MVR_POINTS_MAX, result="MINOR_VIOLATIONS"
    )
    assert driver["mvr_points_latest"] == 5

    decided = validate_success(
        api_client.create_qualification_decision(
            driver["id"], f.qualification_decision_payload("QUALIFY"), SECOND_COMPLIANCE_HEADERS
        ),
        201,
    )
    assert decided["decision"] == "QUALIFY"

    after = fx.read_driver(driver["id"])
    assert after["qualification_status"] == "QUALIFIED"
    assert after["qualified_by_user_id"] == SECOND_COMPLIANCE_OFFICER_USER_ID
    assert after["version"] == driver["version"] + 1
    assert after["mvr_points_latest"] == 5


def test_the_officer_who_pulled_the_record_may_not_sign_the_qualification():
    """The signer is compared by caller identity, not by role, so the recorder is refused.

    PRD: "And the acting officer's `X-User-ID` must differ from the `recorded_by_user_id` on that newest pull: the officer who pulled the record may not sign the decision that relies on it, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/validations/the_officer_who_recorded_the_mvr_check_cannot_also_qualify_the_driver
    """
    _store, driver, pull = _driver_awaiting_a_decision()
    assert pull["recorded_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert pull["result"] == "CLEAR"
    assert driver["mvr_points_latest"] == 0
    assert driver["insurance_status"] == "VERIFIED"
    assert driver["qualification_status"] == "PENDING_CHECKS"

    validate_error(
        api_client.create_qualification_decision(
            driver["id"], f.qualification_decision_payload("QUALIFY"), COMPLIANCE_HEADERS
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    after = fx.read_driver(driver["id"])
    assert after["qualification_status"] == "PENDING_CHECKS"
    assert after["qualified_by_user_id"] is None
    assert after["version"] == driver["version"]


def test_a_second_officer_signs_the_same_qualification_successfully():
    """The identical decision from a different officer carries the driver to qualified.

    PRD: "On success `qualification_status` becomes `QUALIFIED`, `qualified_by_user_id` records the signing officer, and the driver's `version` increments by 1."
    Design: Corner/validations/the_officer_who_recorded_the_mvr_check_cannot_also_qualify_the_driver
    """
    _store, driver, pull = _driver_awaiting_a_decision()
    assert pull["recorded_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    decided = validate_success(
        api_client.create_qualification_decision(
            driver["id"], f.qualification_decision_payload("QUALIFY"), SECOND_COMPLIANCE_HEADERS
        ),
        201,
    )
    assert decided["decision"] == "QUALIFY"

    after = fx.read_driver(driver["id"])
    assert after["qualification_status"] == "QUALIFIED"
    assert after["qualified_by_user_id"] == SECOND_COMPLIANCE_OFFICER_USER_ID
    assert after["qualified_by_user_id"] != pull["recorded_by_user_id"]
    assert after["version"] == driver["version"] + 1


QUALIFIED_AT = "2026-07-15T12:00:00Z"
LAPSING_COVERAGE = {
    "policy_number": "POL-9001",
    "coverage_from": "2026-07-01T00:00:00Z",
    "coverage_to": "2026-08-01T00:00:00Z",
}


def _stacked_route_under_lapsing_coverage(planned_depart_at):
    """A qualified driver whose certificate runs out on 2026-08-01, with one ready
    order stacked on an uncommitted route leaving at the given instant."""
    world = fx.setup_operational_store(
        clock=QUALIFIED_AT,
        driver_overrides={
            "mvr_overrides": {"checked_on": "2026-07-10T08:00:00Z"},
            "insurance_overrides": LAPSING_COVERAGE,
        },
    )
    order = fx.add_ready_order(world["store"]["id"], world["addresses"]["A"]["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], planned_depart_at)
    world["stop"] = fx.stack_stop(dispatch["id"], order["id"], 1)
    world["order"] = order
    world["dispatch"] = fx.read_dispatch(dispatch["id"])
    return world


def test_committing_a_route_that_leaves_after_the_certificate_lapses_is_refused():
    """The coverage test at commitment reads the planned departure, not the clock.

    PRD: "The driver's newest `VERIFIED` insurance certificate must cover the route's `planned_depart_at` — at or after `coverage_from`, strictly before `coverage_to` — and not merely cover the present moment; a certificate that covers today but lapses before the planned departure is refused with `ERR_INSURANCE_NOT_ACTIVE`."
    Design: Corner/validations/locking_a_route_that_departs_after_the_insurance_lapses_is_rejected
    """
    world = _stacked_route_under_lapsing_coverage(PLANNED_DEPART_AT)
    dispatch = world["dispatch"]
    assert world["driver"]["qualification_status"] == "QUALIFIED"
    assert world["driver"]["insurance_status"] == "VERIFIED"
    assert dispatch["status"] == "STACKED"
    assert a.parse_instant(dispatch["planned_depart_at"]) == a.parse_instant(PLANNED_DEPART_AT)
    assert a.parse_instant(PLANNED_DEPART_AT) >= a.parse_instant(LAPSING_COVERAGE["coverage_to"])

    validate_error(
        api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_INSURANCE_NOT_ACTIVE.value,
    )

    after = fx.read_dispatch(dispatch["id"])
    assert after["status"] == "STACKED"
    assert after["version"] == dispatch["version"]
    assert after["resolved_cost_model_id"] is None
    assert after["route_minutes"] is None
    assert after["expected_return_at"] is None
    assert after["estimated_reimbursement_cents"] is None
    # PRD: "Insertion raises the route's `committed_hot_bag_slots` by the stop's
    # `hot_bag_slots`", so the one stacked slot is already committed before the
    # lock; the refused lock must leave that pre-lock total exactly as it was.
    assert after["committed_hot_bag_slots"] == dispatch["committed_hot_bag_slots"] == 1
    assert fx.read_driver(world["driver"]["id"])["qualification_status"] == "QUALIFIED"
    assert fx.read_stop(world["stop"]["id"])["status"] == "PENDING"
    assert fx.list_route_lines(dispatch["id"], world["manager_headers"]) == []


def test_committing_a_route_that_leaves_inside_the_coverage_window_is_accepted():
    """The same route commits once its planned departure sits inside the coverage.

    PRD: "The driver's newest `VERIFIED` insurance certificate must cover the route's `planned_depart_at` — at or after `coverage_from`, strictly before `coverage_to` — and not merely cover the present moment; a certificate that covers today but lapses before the planned departure is refused with `ERR_INSURANCE_NOT_ACTIVE`."
    Design: Corner/validations/locking_a_route_that_departs_after_the_insurance_lapses_is_rejected
    """
    depart_at = "2026-07-20T12:05:00Z"
    world = _stacked_route_under_lapsing_coverage(depart_at)
    dispatch = world["dispatch"]

    locked = validate_success(api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200)
    assert locked["status"] == "LOCKED"
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert locked["route_minutes"] == a.expected_route_minutes([3.00], 3, 6) == 24
    a.assert_iso_millis(locked["expected_return_at"], "expected_return_at")
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(depart_at, minutes=24)
    )
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], world["cost_model"]
    ) == 336
    assert locked["committed_hot_bag_slots"] == 1


def test_charging_a_remedy_back_to_a_driver_before_payroll_runs_is_refused():
    """A chargeable approval needs an actual-basis line, which only payroll writes.

    PRD: "Third, when `driver_chargeable` is true, the route that settled the complaint's order must have reached `SETTLED`, or the approval is refused with `ERR_CLAWBACK_NOT_SETTLED` — there is no actual-basis line to claw back until the route has settled."
    Design: Corner/validations/approving_a_driver_chargeable_remedy_before_the_route_settles_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:36:00Z")
    order = world["orders"][0]
    driver_id = world["driver"]["id"]
    manager_headers = world["manager_headers"]
    assert world["dispatch"]["status"] == "EN_ROUTE"

    complaint = fx.log_complaint(order["id"], "QUALITY")
    proposed = fx.propose_remedy(complaint["id"])
    assert (proposed["proposed_remedy_cents"], proposed["remedy_basis"]) == a.expected_remedy(
        order, "QUALITY"
    )
    assert proposed["proposed_remedy_cents"] == 1100
    assert proposed["status"] == "REMEDY_PROPOSED"

    validate_error(
        api_client.resolve_complaint(
            complaint["id"],
            f.resolve_complaint_payload("APPROVE", driver_chargeable=True),
            manager_headers,
        ),
        ApiErrorId.ERR_CLAWBACK_NOT_SETTLED.value,
    )

    after = validate_success(api_client.get_complaint(complaint["id"], CARE_HEADERS), 200)
    assert after["status"] == "REMEDY_PROPOSED"
    assert after["version"] == proposed["version"]
    assert after["clawback_cents"] == 0
    assert after["driver_chargeable"] is False
    assert after["resolved_at"] is None
    assert after["resolved_by_user_id"] is None

    order_after = fx.read_order(order["id"])
    assert order_after["remedy_issued_cents"] == 0
    assert order_after["settlement_status"] == "CHARGED"
    assert order_after["version"] == order["version"]
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 0
    lines = fx.list_route_lines(world["dispatch"]["id"], manager_headers)
    assert [line["line_type"] for line in lines] == ["PROVISIONAL_STOP"]


def test_approving_a_remedy_that_is_not_charged_back_writes_no_ledger_line():
    """Without the chargeable flag the same approval issues the credit and stops there.

    PRD: "When `driver_chargeable` is false or omitted, no ledger line is written and `clawback_cents` stays 0."
    Design: Corner/validations/approving_a_driver_chargeable_remedy_before_the_route_settles_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:36:00Z")
    order = world["orders"][0]
    driver_id = world["driver"]["id"]
    manager_headers = world["manager_headers"]

    complaint = fx.log_complaint(order["id"], "QUALITY")
    proposed = fx.propose_remedy(complaint["id"])
    assert proposed["proposed_remedy_cents"] == 1100

    resolved = validate_success(
        api_client.resolve_complaint(
            complaint["id"], f.resolve_complaint_payload("APPROVE"), manager_headers
        ),
        200,
    )
    assert resolved["status"] == "REMEDY_ISSUED"
    assert resolved["clawback_cents"] == 0
    assert resolved["driver_chargeable"] is False
    a.assert_iso_millis(resolved["resolved_at"], "resolved_at")

    order_after = fx.read_order(order["id"])
    assert order_after["remedy_issued_cents"] == 1100
    assert order_after["settlement_status"] == "ADJUSTED"
    assert fx.read_driver(driver_id)["reimbursement_accrued_cents"] == 0
    lines = fx.list_route_lines(world["dispatch"]["id"], manager_headers)
    assert [line["line_type"] for line in lines] == ["PROVISIONAL_STOP"]


def test_approving_a_remedy_beyond_the_remaining_refundable_balance_is_refused():
    """The second approval is capped on what the first one left of the ticket.

    PRD: "Second, `proposed_remedy_cents` must be no greater than the order's `total_charge_cents` minus its already-issued `remedy_issued_cents` — the **remaining** refundable balance at approval time — or the approval is refused with `ERR_REMEDY_EXCEEDS_TOTAL`."
    Design: Corner/validations/a_remedy_exceeding_the_remaining_refundable_balance_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:50:00Z")
    order = world["orders"][0]
    store_id = world["store"]["id"]
    manager_headers = world["manager_headers"]
    assert order["total_charge_cents"] == 2900
    assert order["order_to_door_gross_minutes"] == 50

    quality = fx.log_complaint(order["id"], "QUALITY")
    assert fx.propose_remedy(quality["id"])["proposed_remedy_cents"] == 1100
    assert fx.resolve_complaint(quality["id"], "APPROVE", store_id)["status"] == "REMEDY_ISSUED"
    order_mid = fx.read_order(order["id"])
    assert order_mid["remedy_issued_cents"] == 1100
    assert order_mid["settlement_status"] == "ADJUSTED"
    remaining = order_mid["total_charge_cents"] - order_mid["remedy_issued_cents"]
    assert remaining == 1800

    late = fx.log_complaint(order["id"], "LATE")
    proposed = fx.propose_remedy(late["id"])
    assert (proposed["proposed_remedy_cents"], proposed["remedy_basis"]) == a.expected_remedy(
        order, "LATE"
    )
    assert proposed["proposed_remedy_cents"] == 2400
    assert proposed["proposed_remedy_cents"] > remaining
    assert proposed["proposed_remedy_cents"] <= order_mid["total_charge_cents"]

    validate_error(
        api_client.resolve_complaint(
            late["id"], f.resolve_complaint_payload("APPROVE"), manager_headers
        ),
        ApiErrorId.ERR_REMEDY_EXCEEDS_TOTAL.value,
    )

    after = validate_success(api_client.get_complaint(late["id"], CARE_HEADERS), 200)
    assert after["status"] == "REMEDY_PROPOSED"
    assert after["version"] == proposed["version"]
    assert after["proposed_remedy_cents"] == 2400
    assert after["resolved_at"] is None
    assert after["resolved_by_user_id"] is None

    order_after = fx.read_order(order["id"])
    assert order_after["remedy_issued_cents"] == 1100
    assert order_after["settlement_status"] == "ADJUSTED"
    assert order_after["version"] == order_mid["version"]


def test_approving_a_second_remedy_inside_the_remaining_balance_is_accepted():
    """A second credit that fits the remaining balance re-adjusts the same ticket.

    PRD: "Re-entering `ADJUSTED` from `ADJUSTED` is a legal self-loop: a second approved complaint re-adjusts an already-adjusted ticket, drawing down the remaining refundable balance."
    Design: Corner/validations/a_remedy_exceeding_the_remaining_refundable_balance_is_rejected
    """
    world = _deliver_one_order("2026-08-05T12:50:00Z")
    order = world["orders"][0]
    store_id = world["store"]["id"]
    manager_headers = world["manager_headers"]

    first = fx.log_complaint(order["id"], "QUALITY")
    fx.propose_remedy(first["id"])
    fx.resolve_complaint(first["id"], "APPROVE", store_id)
    order_mid = fx.read_order(order["id"])
    assert order_mid["remedy_issued_cents"] == 1100

    second = fx.log_complaint(order["id"], "QUALITY")
    proposed = fx.propose_remedy(second["id"])
    assert proposed["proposed_remedy_cents"] == 1100
    assert proposed["proposed_remedy_cents"] <= (
        order_mid["total_charge_cents"] - order_mid["remedy_issued_cents"]
    )

    resolved = validate_success(
        api_client.resolve_complaint(
            second["id"], f.resolve_complaint_payload("APPROVE"), manager_headers
        ),
        200,
    )
    assert resolved["status"] == "REMEDY_ISSUED"
    assert resolved["clawback_cents"] == 0

    order_after = fx.read_order(order["id"])
    assert order_after["remedy_issued_cents"] == 2200
    assert order_after["settlement_status"] == "ADJUSTED"
    assert order_after["total_charge_cents"] - order_after["remedy_issued_cents"] == 700


def test_dropping_cash_the_driver_never_collected_is_refused():
    """An empty pouch cannot fund an envelope, so even a 100-cent drop is refused.

    PRD: "The drop may not exceed what the ledger says is in the pouch: an `amount_cents` greater than the driver's `cash_on_hand_cents` is refused with `ERR_SAFE_DROP_EXCEEDS_CASH`, because a drop must never break the conservation identity."
    Design: Corner/validations/a_safe_drop_larger_than_the_cash_on_hand_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    driver = fx.hire_driver(store_id)
    before = fx.read_driver(driver["id"])
    assert before["cash_on_hand_cents"] == 0
    assert before["cash_posture"] == "CLEAR"

    validate_error(
        api_client.create_safe_drop(
            driver["id"],
            f.create_safe_drop_payload(100, envelope_number="ENV-001"),
            make_driver_headers(driver["id"]),
        ),
        ApiErrorId.ERR_SAFE_DROP_EXCEEDS_CASH.value,
    )

    drops, meta = validate_paginated(
        api_client.list_safe_drops(make_manager_headers(store_id), {"driver_id": driver["id"]})
    )
    assert meta["total_count"] == 0
    assert drops == []

    after = fx.read_driver(driver["id"])
    assert after["cash_on_hand_cents"] == 0
    assert after["cash_posture"] == "CLEAR"
    assert after["version"] == before["version"]

    reconciliation = fx.read_cash_reconciliation(store_id)
    assert reconciliation["cash_collected_total_cents"] == 0
    assert reconciliation["safe_deposit_total_cents"] == 0
    assert reconciliation["driver_cash_on_hand_total_cents"] == 0
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)
    assert fx.read_store(store_id)["version"] == store["version"]


def test_dropping_exactly_the_cash_on_hand_is_accepted_but_one_cent_more_is_refused():
    """The pouch balance is the ceiling: equality passes, a single cent over does not.

    PRD: "The drop may not exceed what the ledger says is in the pouch: an `amount_cents` greater than the driver's `cash_on_hand_cents` is refused with `ERR_SAFE_DROP_EXCEEDS_CASH`, because a drop must never break the conservation identity."
    Design: Corner/validations/a_safe_drop_larger_than_the_cash_on_hand_is_rejected
    """
    world = _deliver_one_order(
        "2026-08-05T12:36:00Z", order_overrides={"payment_method": "CASH"}
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    holding = fx.read_driver(driver_id)
    assert holding["cash_on_hand_cents"] == 2900
    assert holding["cash_posture"] == "CLEAR"

    validate_error(
        api_client.create_safe_drop(
            driver_id,
            f.create_safe_drop_payload(2901, envelope_number="ENV-001"),
            make_driver_headers(driver_id),
        ),
        ApiErrorId.ERR_SAFE_DROP_EXCEEDS_CASH.value,
    )
    _drops, meta = validate_paginated(
        api_client.list_safe_drops(make_manager_headers(store_id), {"driver_id": driver_id})
    )
    assert meta["total_count"] == 0
    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == 2900

    drop = validate_success(
        api_client.create_safe_drop(
            driver_id,
            f.create_safe_drop_payload(2900, envelope_number="ENV-0002"),
            make_driver_headers(driver_id),
        ),
        201,
    )
    a.assert_safe_drop(drop)
    assert drop["status"] == "RECORDED"
    assert drop["amount_cents"] == 2900

    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == 0
    assert fx.read_store(store_id)["safe_deposit_total_cents"] == 2900
    reconciliation = fx.read_cash_reconciliation(store_id)
    assert reconciliation["cash_collected_total_cents"] == 2900
    assert reconciliation["safe_deposit_total_cents"] == 2900
    assert reconciliation["driver_cash_on_hand_total_cents"] == 0
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)


def _recorded_drop_of_the_days_takings():
    """One cash order handed over at 12:36 with its 2900-cent takings dropped into
    the safe at the same instant."""
    world = _deliver_one_order(
        "2026-08-05T12:36:00Z", order_overrides={"payment_method": "CASH"}
    )
    drop = validate_success(
        api_client.create_safe_drop(
            world["driver"]["id"],
            f.create_safe_drop_payload(2900, envelope_number="ENV-001"),
            make_driver_headers(world["driver"]["id"]),
        ),
        201,
    )
    assert drop["status"] == "RECORDED"
    assert drop["amount_cents"] == 2900
    assert drop["voided_at"] is None
    assert drop["voided_reason"] is None
    a.assert_iso_millis(drop["created_at"], "created_at")
    assert a.parse_instant(drop["created_at"]) == a.parse_instant("2026-08-05T12:36:00Z")
    return world, drop


def test_voiding_a_safe_drop_exactly_sixty_minutes_later_is_refused():
    """At exactly 3600 elapsed seconds the envelope is in the safe for good.

    PRD: "At exactly 3600 seconds the envelope is in the safe for good and the attempt is refused with `ERR_SAFE_DROP_NOT_VOIDABLE`."
    Design: Corner/validations/voiding_a_safe_drop_exactly_sixty_minutes_later_is_rejected
    """
    world, drop = _recorded_drop_of_the_days_takings()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    manager_headers = world["manager_headers"]

    on_the_edge = a.instant_plus(drop["created_at"], seconds=SAFE_DROP_VOID_WINDOW_SECONDS)
    fx.set_clock(on_the_edge)
    assert a.whole_minutes_between(drop["created_at"], on_the_edge) == 60

    validate_error(
        api_client.void_safe_drop(drop["id"], f.void_safe_drop_payload(), manager_headers),
        ApiErrorId.ERR_SAFE_DROP_NOT_VOIDABLE.value,
    )

    after = validate_success(api_client.get_safe_drop(drop["id"], manager_headers), 200)
    assert after["status"] == "RECORDED"
    assert after["voided_at"] is None
    assert after["voided_reason"] is None
    assert after["version"] == drop["version"]
    assert after["amount_cents"] == 2900

    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == 0
    assert fx.read_store(store_id)["safe_deposit_total_cents"] == 2900
    reconciliation = fx.read_cash_reconciliation(store_id)
    assert reconciliation["cash_collected_total_cents"] == 2900
    assert reconciliation["safe_deposit_total_cents"] == 2900
    assert reconciliation["driver_cash_on_hand_total_cents"] == 0
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)


def test_voiding_a_safe_drop_one_second_inside_the_window_is_accepted():
    """One second short of the hour the void still reverses the drop exactly.

    PRD: "The window is strict: the difference between the logical clock and the drop's `created_at`, measured in whole seconds, must be **less than** 60 minutes."
    Design: Corner/validations/voiding_a_safe_drop_exactly_sixty_minutes_later_is_rejected
    """
    world, drop = _recorded_drop_of_the_days_takings()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    manager_headers = world["manager_headers"]

    inside = a.instant_plus(drop["created_at"], seconds=SAFE_DROP_VOID_WINDOW_SECONDS - 1)
    fx.set_clock(inside)

    voided = validate_success(
        api_client.void_safe_drop(drop["id"], f.void_safe_drop_payload(), manager_headers), 200
    )
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "Mis-keyed envelope amount"
    a.assert_iso_millis(voided["voided_at"], "voided_at")
    assert a.parse_instant(voided["voided_at"]) == a.parse_instant(inside)
    assert voided["version"] == drop["version"] + 1

    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == 2900
    assert fx.read_store(store_id)["safe_deposit_total_cents"] == 0
    reconciliation = fx.read_cash_reconciliation(store_id)
    assert reconciliation["cash_collected_total_cents"] == 2900
    assert reconciliation["safe_deposit_total_cents"] == 0
    assert reconciliation["driver_cash_on_hand_total_cents"] == 2900
    assert reconciliation["reconciled"] is True
    a.assert_cash_conservation(reconciliation)


def test_publishing_a_delivery_area_window_that_overlaps_an_existing_one_is_refused():
    """Two candidate polygons may never cover the same instant for one store.

    PRD: "Before the version is stored, its window is tested against every existing version of the same store whose status is `DRAFT` or `ACTIVE`: if the two windows intersect on the half-open basis of §2.10, the publication is rejected with `ERR_ZONE_WINDOW_OVERLAP`."
    Design: Corner/validations/a_zone_version_overlapping_an_existing_window_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    existing = fx.publish_zone_version(store_id)
    assert existing["status"] == "DRAFT"
    assert existing["version_number"] == 1
    fresh = fx.read_store(store_id)

    overlapping = f.create_zone_version_payload(
        store_id,
        fresh["version"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    validate_error(
        api_client.create_zone_version(overlapping, manager_headers),
        ApiErrorId.ERR_ZONE_WINDOW_OVERLAP.value,
    )

    versions, meta = validate_paginated(
        api_client.list_zone_versions(manager_headers, {"store_id": store_id})
    )
    assert meta["total_count"] == 1
    assert [version["id"] for version in versions] == [existing["id"]]

    unchanged = validate_success(api_client.get_zone_version(existing["id"], manager_headers), 200)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == existing["version"]
    assert fx.read_store(store_id)["version"] == fresh["version"]


def test_publishing_a_delivery_area_window_that_merely_touches_an_existing_one_is_accepted():
    """Windows that meet at a boundary are adjacent rather than overlapping.

    PRD: "Overlap between two such windows is tested on the same half-open basis, so two versions that merely touch — where the earlier version's `effective_to` equals the later version's `effective_from` — are adjacent, not overlapping, and both may be stored."
    Design: Corner/validations/a_zone_version_overlapping_an_existing_window_is_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    existing = fx.publish_zone_version(store_id)
    assert existing["effective_to"] is not None
    fresh = fx.read_store(store_id)

    adjacent = f.create_zone_version_payload(
        store_id,
        fresh["version"],
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    assert a.parse_instant(existing["effective_to"]) == a.parse_instant(
        adjacent["effective_from"]
    )

    published = validate_success(api_client.create_zone_version(adjacent, manager_headers), 201)
    assert published["status"] == "DRAFT"
    assert published["version_number"] == 2
    assert published["supersedes_zone_version_id"] is None
    assert published["activated_at"] is None

    _versions, meta = validate_paginated(
        api_client.list_zone_versions(manager_headers, {"store_id": store_id})
    )
    assert meta["total_count"] == 2
    assert fx.read_store(store_id)["version"] == fresh["version"] + 1


def test_a_request_with_an_empty_caller_identity_is_refused_before_any_scope_check():
    """An empty caller identity fails to authenticate, ahead of every ownership test.

    PRD: "A request whose `X-User-ID` is absent or empty is rejected with `ERR_MISSING_USER_ID` (HTTP 401)."
    Design: Corner/validations/missing_and_unknown_identity_headers_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]

    validate_error(
        api_client.get_store(store_id, headers_for("StoreManager", "")),
        ApiErrorId.ERR_MISSING_USER_ID.value,
    )
    validate_error(
        api_client.get_store(UNKNOWN_STORE_ID, headers_for("StoreManager", "")),
        ApiErrorId.ERR_MISSING_USER_ID.value,
    )

    allowed = validate_success(api_client.get_store(store_id, make_manager_headers(store_id)), 200)
    assert allowed["id"] == store_id
    assert allowed["version"] == store["version"]


def test_a_request_naming_a_role_outside_the_declared_set_is_refused():
    """An unrecognised role is a failure to authenticate, not a failure to authorize.

    PRD: "A request whose `X-User-Role` is absent, empty, or is any string other than the five role names enumerated below is rejected with `ERR_INVALID_ROLE` (HTTP 401) — an unrecognised role is treated as a failure to authenticate, not as a failure to authorize."
    Design: Corner/validations/missing_and_unknown_identity_headers_are_rejected
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    store_id = store["id"]

    validate_error(
        api_client.get_store(store_id, headers_for("Franchisee", store_id)),
        ApiErrorId.ERR_INVALID_ROLE.value,
    )
    validate_error(
        api_client.get_store(UNKNOWN_STORE_ID, headers_for("Franchisee", store_id)),
        ApiErrorId.ERR_INVALID_ROLE.value,
    )
    validate_error(
        api_client.get_store(store_id, headers_for("", store_id)),
        ApiErrorId.ERR_INVALID_ROLE.value,
    )

    allowed = validate_success(api_client.get_store(store_id, make_manager_headers(store_id)), 200)
    assert allowed["id"] == store_id
    assert allowed["version"] == store["version"]
