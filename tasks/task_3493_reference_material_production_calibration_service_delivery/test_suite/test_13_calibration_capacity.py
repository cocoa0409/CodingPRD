"""Difficulty queue: aggregate daily capacity and validation-cascade order."""
from test_helpers import (
    ApiErrorId, make_calibration_coordinator_headers, make_calibration_order,
    make_customer, make_program, make_service, make_traceability_link,
    schedule_calibration_order, validate_error, validate_success,
)

_COORD = make_calibration_coordinator_headers()


def _setup_two_services():
    """One program (capacity 480) with two ACTIVE services, each with its own
    valid traceability link, one customer, and one RECEIVED order per service."""
    program = make_program(program_code="NIST-RM-16")
    svc_a = make_service(service_code="DCV-4A", measurand="DC voltage")
    svc_b = make_service(service_code="RES-4B", measurand="resistance",
                         base_fee_cents=10000, per_point_fee_cents=800)
    make_traceability_link(svc_a["id"], standard_description="Std-16A")
    make_traceability_link(svc_b["id"], standard_description="Std-16B")
    customer = make_customer(name="C16")
    order_a = make_calibration_order(svc_a["id"], customer["id"],
                                     artifact_description="artifact A", measurement_points=1)
    order_b = make_calibration_order(svc_b["id"], customer["id"],
                                     artifact_description="artifact B", measurement_points=1)
    return {"program": program, "svc_a": svc_a, "svc_b": svc_b,
            "customer": customer, "order_a": order_a, "order_b": order_b}


def test_full_day_capacity_allowed(api):
    """PRD §3.6: "the sum of `duration_minutes` over all orders in those same
    three active states whose `scheduled_start` falls on the new start's UTC
    calendar day, plus the new order's duration, must not exceed the program's
    `daily_lab_capacity_minutes` (`ERR_CAPACITY_EXCEEDED`)" — 480 == 480 does
    not exceed.

    Design: Difficulty/resource_temporal_overlap/program_daily_capacity_aggregate
    """
    st = _setup_two_services()
    scheduled = schedule_calibration_order(st["order_a"]["id"],
                                           "2026-10-05T09:00:00Z",
                                           "2026-10-05T17:00:00Z")
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["duration_minutes"] == 480


def test_capacity_overflow_rejected_across_distinct_links(api):
    """PRD §3.6: "the sum of `duration_minutes` over all orders in those same
    three active states whose `scheduled_start` falls on the new start's UTC
    calendar day, plus the new order's duration, must not exceed the program's
    `daily_lab_capacity_minutes` (`ERR_CAPACITY_EXCEEDED`)".

    Design: Difficulty/resource_temporal_overlap/program_daily_capacity_aggregate
    """
    st = _setup_two_services()
    schedule_calibration_order(st["order_a"]["id"], "2026-10-05T09:00:00Z",
                               "2026-10-05T17:00:00Z")
    resp = api.transition_calibration_order(
        st["order_b"]["id"], {"to": "SCHEDULED",
                              "scheduled_start": "2026-10-05T17:00:00Z",
                              "scheduled_end": "2026-10-05T17:30:00Z"}, _COORD)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def _setup_capacity_cancel():
    """Program capacity 480; one service+link; order A scheduled 09:00-17:00;
    order B (RECEIVED) wanting 17:00-17:30 the same day."""
    program = make_program(program_code="NIST-RM-18")
    service = make_service(service_code="DCV-5")
    make_traceability_link(service["id"], standard_description="Std-18")
    customer = make_customer(name="C18")
    order_a = make_calibration_order(service["id"], customer["id"],
                                     artifact_description="artifact A", measurement_points=1)
    schedule_calibration_order(order_a["id"], "2026-10-05T09:00:00Z",
                               "2026-10-05T17:00:00Z")
    order_b = make_calibration_order(service["id"], customer["id"],
                                     artifact_description="artifact B", measurement_points=1)
    return {"program": program, "order_a": order_a, "order_b": order_b}


def test_capacity_rejected_before_compensating_cancel(api):
    """PRD §3.6: "the sum of `duration_minutes` ... plus the new order's
    duration, must not exceed the program's `daily_lab_capacity_minutes`
    (`ERR_CAPACITY_EXCEEDED`)".

    Design: Difficulty/compensating_invariant/daily_capacity_conserved_schedule_cancel
    """
    st = _setup_capacity_cancel()
    resp = api.transition_calibration_order(
        st["order_b"]["id"], {"to": "SCHEDULED",
                              "scheduled_start": "2026-10-05T17:00:00Z",
                              "scheduled_end": "2026-10-05T17:30:00Z"}, _COORD)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_cancel_restores_daily_capacity(api):
    """PRD §3.6: "it frees the order's daily-capacity contribution — cancelled
    orders are excluded from the aggregate".

    Design: Difficulty/compensating_invariant/daily_capacity_conserved_schedule_cancel
    """
    st = _setup_capacity_cancel()
    validate_success(
        api.transition_calibration_order(st["order_a"]["id"], {"to": "CANCELLED"}, _COORD))
    scheduled = validate_success(
        api.transition_calibration_order(
            st["order_b"]["id"], {"to": "SCHEDULED",
                                  "scheduled_start": "2026-10-05T17:00:00Z",
                                  "scheduled_end": "2026-10-05T17:30:00Z"}, _COORD))
    assert scheduled["status"] == "SCHEDULED"


def _setup_safety_vs_window():
    """Service whose only link has calibration_due_date 2026-10-06T00:00:00Z;
    order A scheduled 2026-10-05 09:00-11:00; orders B and C unscheduled."""
    program = make_program(program_code="NIST-RM-10")
    service = make_service(service_code="DCV-2")
    make_traceability_link(service["id"], standard_description="Std-10",
                           calibration_due_date="2026-10-06T00:00:00Z")
    customer = make_customer(name="C10-cal")
    order_a = make_calibration_order(service["id"], customer["id"],
                                     artifact_description="artifact A", measurement_points=1)
    schedule_calibration_order(order_a["id"], "2026-10-05T09:00:00Z",
                               "2026-10-05T11:00:00Z")
    order_b = make_calibration_order(service["id"], customer["id"],
                                     artifact_description="artifact B", measurement_points=1)
    order_c = make_calibration_order(service["id"], customer["id"],
                                     artifact_description="artifact C", measurement_points=1)
    return {"order_b": order_b, "order_c": order_c}


def test_traceability_safety_precedes_window_conflict(api):
    """PRD §2.8: "A request that fails an earlier stage is rejected immediately
    with that stage's error and never reaches later stages; where several stages
    apply to the same request, the relative order below is authoritative." —
    traceability chain (stage 12) precedes booking overlap (stage 20).
    PRD §3.6: "requires the selected link's `calibration_due_date` to fall on or
    after `scheduled_end` — otherwise the chain does not cover the window and
    the request fails with `ERR_TRACEABILITY_CHAIN_BROKEN`".

    Design: Difficulty/priority_pair_validation_conflict/traceability_safety_precedes_window_temporal
    """
    st = _setup_safety_vs_window()
    resp = api.transition_calibration_order(
        st["order_b"]["id"], {"to": "SCHEDULED",
                              "scheduled_start": "2026-10-05T10:30:00Z",
                              "scheduled_end": "2026-10-08T12:00:00Z"}, _COORD)
    validate_error(resp, ApiErrorId.ERR_TRACEABILITY_CHAIN_BROKEN)


def test_window_conflict_fires_when_chain_intact(api):
    """PRD §3.6: overlap with an existing booking on the selected link "is a
    conflict answered by `ERR_RESOURCE_WINDOW_CONFLICT`".

    Design: Difficulty/priority_pair_validation_conflict/traceability_safety_precedes_window_temporal
    """
    st = _setup_safety_vs_window()
    resp = api.transition_calibration_order(
        st["order_c"]["id"], {"to": "SCHEDULED",
                              "scheduled_start": "2026-10-05T10:30:00Z",
                              "scheduled_end": "2026-10-05T11:30:00Z"}, _COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_WINDOW_CONFLICT)
