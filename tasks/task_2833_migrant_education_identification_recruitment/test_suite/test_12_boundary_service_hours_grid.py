"""Delivered hours must sit on the quarter-hour grid inside an inclusive 0.00-to-8.00 band."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_row_count,
)
from test_helpers.test_users import make_coordinator_headers


def _active_plan(client):
    """A certified child holding one ACTIVE summer plan ready to receive sessions."""
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    bundle.plan = fixtures.active_plan(client, bundle.student["id"])
    return bundle


def _post(client, plan_id, delivered_on, hours):
    return client.create_delivery(
        factories.delivery_payload(plan_id, delivered_on=delivered_on, hours=hours),
        make_coordinator_headers(),
    )


def test_the_grid_accepts_the_two_inclusive_edges_and_refuses_everything_off_it(client):
    """0.25 and 8.00 are accepted while 0.00, 8.25 and 0.30 are all refused.

    "`hours` must be strictly greater than 0.00, no more than 8.00, and an exact multiple
    of a quarter hour; `credits_awarded`, when present, must be no more than 2.00 and
    likewise an exact multiple of 0.25."

    Design: Difficulty/boundary_precision_check/service_delivery_hours_must_sit_on_the_quarter_hour_grid_and_rejects_off_grid_values
    """
    bundle = _active_plan(client)
    plan_id = bundle.plan["id"]

    validate_error(
        _post(client, plan_id, "2026-07-20", 0.00),
        api_errors.ERR_INVALID_SERVICE_HOURS,
        422,
    )

    low_edge = validate_success(_post(client, plan_id, "2026-07-21", 0.25), 201)
    assert_decimal_equals(low_edge["hours"], "0.25", "delivery.hours")

    high_edge = validate_success(_post(client, plan_id, "2026-07-22", 8.00), 201)
    assert_decimal_equals(high_edge["hours"], "8.00", "delivery.hours")

    validate_error(
        _post(client, plan_id, "2026-07-23", 8.25),
        api_errors.ERR_INVALID_SERVICE_HOURS,
        422,
    )
    validate_error(
        _post(client, plan_id, "2026-07-24", 0.30),
        api_errors.ERR_INVALID_SERVICE_HOURS,
        422,
    )


def test_only_the_accepted_sessions_reach_the_ledger(client):
    """The refused posts leave no row and no hour behind on either aggregate.

    "A value off that grid - 0.00 hours, 8.25 hours, 1.10 hours - is refused with
    `ERR_INVALID_SERVICE_HOURS`."

    Design: Difficulty/boundary_precision_check/service_delivery_hours_must_sit_on_the_quarter_hour_grid_and_rejects_off_grid_values
    """
    bundle = _active_plan(client)
    plan_id = bundle.plan["id"]

    _post(client, plan_id, "2026-07-20", 0.00)
    _post(client, plan_id, "2026-07-21", 0.25)
    _post(client, plan_id, "2026-07-22", 8.00)
    _post(client, plan_id, "2026-07-23", 8.25)
    _post(client, plan_id, "2026-07-24", 0.30)

    student = fixtures.read_student(client, bundle.student["id"])
    assert_decimal_equals(
        student["total_service_hours_ledger"],
        "8.25",
        "student.total_service_hours_ledger",
    )

    plan = fixtures.read_plan(client, plan_id)
    assert_decimal_equals(plan["delivered_hours"], "8.25", "plan.delivered_hours")

    rows, _meta = fixtures.list_rows(
        client.list_deliveries(make_coordinator_headers(), {"plan_id": plan_id})
    )
    assert_row_count(rows, 2, "delivered sessions on the plan")
