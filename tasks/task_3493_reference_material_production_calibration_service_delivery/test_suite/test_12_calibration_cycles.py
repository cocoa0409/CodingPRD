"""Difficulty queue: calibration hold/resume cycle and half-open overlap."""
from test_helpers import (
    ApiErrorId, make_calibration_coordinator_headers, make_calibration_order,
    make_metrologist_headers, schedule_calibration_order,
    setup_calibration_scenario, validate_error, validate_success,
)

_COORD = make_calibration_coordinator_headers()
_MET = make_metrologist_headers("met-op")


def _drive_hold_cycle(api, order_id):
    """SCHEDULED -> IN_MEASUREMENT -> MEASUREMENT_HOLD -> IN_MEASUREMENT ->
    COMPLETED."""
    scheduled = schedule_calibration_order(order_id, "2026-10-05T09:00:00Z",
                                           "2026-10-05T11:00:00Z")
    validate_success(api.transition_calibration_order(order_id, {"to": "IN_MEASUREMENT"}, _MET))
    validate_success(api.transition_calibration_order(order_id, {"to": "MEASUREMENT_HOLD"}, _MET))
    validate_success(api.transition_calibration_order(order_id, {"to": "IN_MEASUREMENT"}, _MET))
    completed = validate_success(
        api.transition_calibration_order(
            order_id, {"to": "COMPLETED", "result": "IN_TOLERANCE",
                       "measured_correction": 0.003}, _MET))
    return scheduled, completed


def test_hold_resume_cycle_completes_with_standard_fee(api):
    """PRD §3.6: "an order in `SCHEDULED` or `MEASUREMENT_HOLD` may be moved to
    `IN_MEASUREMENT`, and an order `IN_MEASUREMENT` may be parked back into
    `MEASUREMENT_HOLD`".
    PRD §3.6: "fixes `final_fee_cents` — equal to `quoted_fee_cents`, or, when
    `expedite_requested` is true, the quoted fee multiplied by the program's
    `expedite_multiplier_pct` and divided by 100".

    Design: Difficulty/non_linear_state_machine/calibration_measurement_hold_cycle
    """
    sc = setup_calibration_scenario(expedite=False, measurement_points=4,
                                    service_overrides={"service_code": "DCV-1"})
    order = sc["order"]
    assert order["quoted_fee_cents"] == 26000
    scheduled, completed = _drive_hold_cycle(api, order["id"])
    assert scheduled["final_fee_cents"] == 26000
    assert completed["status"] == "COMPLETED"


def test_hold_cycle_records_result_and_window_fields(api):
    """PRD §3.6: "A successful scheduling stores `resolved_traceability_link_id`,
    derives `duration_minutes` as the whole minutes between window end and
    start".
    PRD §3.6: completion "records a `result` of `IN_TOLERANCE` or
    `OUT_OF_TOLERANCE` ... together with the `measured_correction`".

    Design: Difficulty/non_linear_state_machine/calibration_measurement_hold_cycle
    """
    sc = setup_calibration_scenario(expedite=False, measurement_points=4,
                                    service_overrides={"service_code": "DCV-1B"})
    scheduled, completed = _drive_hold_cycle(api, sc["order"]["id"])
    assert scheduled["duration_minutes"] == 120
    assert scheduled["resolved_traceability_link_id"] == sc["link"]["id"]
    assert completed["result"] == "IN_TOLERANCE"
    assert completed["measured_correction"] == 0.003


def _setup_three_orders(service_code):
    sc = setup_calibration_scenario(measurement_points=1,
                                    service_overrides={"service_code": service_code})
    order_b = make_calibration_order(sc["service"]["id"], sc["customer"]["id"],
                                     artifact_description="artifact B",
                                     measurement_points=1)
    order_c = make_calibration_order(sc["service"]["id"], sc["customer"]["id"],
                                     artifact_description="artifact C",
                                     measurement_points=1)
    return sc, order_b, order_c


def test_adjacent_windows_allowed(api):
    """PRD §3.6: "mere adjacency, one window's end touching the other's start,
    is allowed."

    Design: Difficulty/resource_temporal_overlap/traceability_link_booking_half_open_overlap
    """
    sc, order_b, _c = _setup_three_orders("DCV-3")
    a = validate_success(api.transition_calibration_order(
        sc["order"]["id"], {"to": "SCHEDULED", "scheduled_start": "2026-10-05T09:00:00Z",
                            "scheduled_end": "2026-10-05T11:00:00Z"}, _COORD))
    b = validate_success(api.transition_calibration_order(
        order_b["id"], {"to": "SCHEDULED", "scheduled_start": "2026-10-05T11:00:00Z",
                        "scheduled_end": "2026-10-05T12:00:00Z"}, _COORD))
    assert a["status"] == "SCHEDULED"
    assert b["status"] == "SCHEDULED"


def test_overlapping_window_rejected(api):
    """PRD §3.6: "any other order booked on that same link and currently
    `SCHEDULED`, `IN_MEASUREMENT`, or `MEASUREMENT_HOLD` whose window overlaps
    the new one — the existing start lying strictly before the new end while the
    new start lies strictly before the existing end — is a conflict answered by
    `ERR_RESOURCE_WINDOW_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/traceability_link_booking_half_open_overlap
    """
    sc, order_b, order_c = _setup_three_orders("DCV-3C")
    schedule_calibration_order(sc["order"]["id"], "2026-10-05T09:00:00Z",
                               "2026-10-05T11:00:00Z")
    schedule_calibration_order(order_b["id"], "2026-10-05T11:00:00Z",
                               "2026-10-05T12:00:00Z")
    resp = api.transition_calibration_order(
        order_c["id"], {"to": "SCHEDULED", "scheduled_start": "2026-10-05T10:30:00Z",
                        "scheduled_end": "2026-10-05T11:30:00Z"}, _COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_WINDOW_CONFLICT)
