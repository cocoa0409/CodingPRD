"""Calibration corner cases: expedite fee, window gates, retired service."""
from test_helpers import (
    ApiErrorId, create_service_payload, make_calibration_coordinator_headers,
    make_metrologist_headers, make_program_admin_headers, make_service,
    setup_calibration_scenario, validate_error, validate_success,
)


def test_expedite_fee_branch_multiplier(api):
    """PRD §3.6: "fixes `final_fee_cents` — equal to `quoted_fee_cents`, or,
    when `expedite_requested` is true, the quoted fee multiplied by the
    program's `expedite_multiplier_pct` and divided by 100, rounded half up to
    whole cents".

    Design: Corner/calculations/expedite_fee_branch_multiplier
    """
    sc = setup_calibration_scenario(expedite=True, measurement_points=4,
                                    service_overrides={"service_code": "SVC-C24"})
    order = sc["order"]
    assert order["quoted_fee_cents"] == 26000
    scheduled = validate_success(
        api.transition_calibration_order(
            order["id"], {"to": "SCHEDULED", "scheduled_start": "2026-10-05T09:00:00Z",
                          "scheduled_end": "2026-10-05T10:00:00Z"},
            make_calibration_coordinator_headers()))
    assert scheduled["final_fee_cents"] == 39000


def test_calibration_complete_requires_in_measurement_rejected(api):
    """PRD §3.6: "Completion, also the `Metrologist`'s, moves the order from
    `IN_MEASUREMENT` to terminal `COMPLETED` — lawful only from
    `IN_MEASUREMENT`", with any other source state refused by
    `ERR_INVALID_CALIBRATION_STATE`.

    Design: Corner/state_machines/calibration_complete_requires_in_measurement_rejected
    """
    sc = setup_calibration_scenario(measurement_points=2,
                                    service_overrides={"service_code": "SVC-C17"})
    resp = api.transition_calibration_order(
        sc["order"]["id"], {"to": "COMPLETED", "result": "IN_TOLERANCE",
                            "measured_correction": 0.001},
        make_metrologist_headers("met-op"))
    validate_error(resp, ApiErrorId.ERR_INVALID_CALIBRATION_STATE)


def test_schedule_window_in_past_rejected(api):
    """PRD §3.6: "its start must not lie earlier than the current logical clock
    (`ERR_WINDOW_IN_PAST`)".
    PRD §2.4: "Before any explicit adjustment, the logical clock starts at
    exactly `2026-09-01T00:00:00Z`".

    Design: Corner/validations/schedule_window_in_past_rejected
    """
    sc = setup_calibration_scenario(measurement_points=1,
                                    service_overrides={"service_code": "SVC-C30"})
    resp = api.transition_calibration_order(
        sc["order"]["id"], {"to": "SCHEDULED", "scheduled_start": "2026-08-01T09:00:00Z",
                            "scheduled_end": "2026-08-01T10:00:00Z"},
        make_calibration_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


def test_retired_service_rejects_scheduling_rejected(api):
    """PRD §3.6: "Retiring a service (`RETIRED`) stops new scheduling without
    touching history" and "the service itself must still be `ACTIVE`
    (`ERR_SERVICE_NOT_ACTIVE`)".

    Design: Corner/validations/retired_service_rejects_scheduling_rejected
    """
    sc = setup_calibration_scenario(
        measurement_points=1,
        service_overrides={"service_code": "SVC-C31", "status": "RETIRED"})
    resp = api.transition_calibration_order(
        sc["order"]["id"], {"to": "SCHEDULED", "scheduled_start": "2026-10-05T09:00:00Z",
                            "scheduled_end": "2026-10-05T10:00:00Z"},
        make_calibration_coordinator_headers())
    validate_error(resp, ApiErrorId.ERR_SERVICE_NOT_ACTIVE)


def test_duplicate_service_code_rejected(api):
    """PRD §3.6: "each **CalibrationServiceOffering** carries a unique
    `service_code` — duplicates refused with `ERR_DUPLICATE_SERVICE_CODE`".

    Design: Corner/errors/duplicate_service_code_rejected
    """
    make_service(service_code="SVC-C40")
    resp = api.create_calibration_service(
        create_service_payload(service_code="SVC-C40", measurand="resistance",
                               base_fee_cents=10000, per_point_fee_cents=800,
                               standard_turnaround_days=3),
        make_program_admin_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERVICE_CODE)
