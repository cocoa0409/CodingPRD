"""Corner-queue tests: immediate consistency of cascades and atomicity of
rejected writes."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_plan,
    create_crew_pool,
    create_locomotive,
    create_yard,
    get_locomotive,
    get_shipment,
    get_success_data,
    setup_operational_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

TS = TEST_USERS["terminal_superintendent_headers"]
ANY = TEST_USERS["any_headers"]


class TestImmediateConsistency:
    def test_cascade_visible_in_same_request_response(self, api):
        """PRD §3.5: "Cancellation of a `SCHEDULED` departure ... releases
        the locomotive back to `AVAILABLE` at the origin yard, and leaves the
        crew pool untouched ... Every `PLANNED` trip leg whose
        `planned_departure_utc` matches this departure's slot instead misses:
        each such leg moves to `MISSED` and the full missed-connection cascade
        of §3.7 fires per leg."
        PRD §3.7: "the shipment's `total_missed_connections` increments by
        one".

        Design: Corner/consistency_model/cascade_visible_in_same_request_response
        """
        sc = setup_operational_scenario(
            "IM", shipment_car_count=1, delivery_by="2026-09-04T00:00:00Z",
        )
        cancelled = validate_success(
            api.cancel_train_departure(sc["departure"]["id"], TS)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == sc["departure"]["version"] + 1
        loco = get_locomotive(sc["loco"]["id"])
        assert loco["status"] == "AVAILABLE", (
            "locomotive release visible on the very next read"
        )
        shipment = get_shipment(sc["shipment"]["id"])
        assert shipment["total_missed_connections"] == 1, (
            "miss cascade visible immediately"
        )

    def test_rejected_write_leaves_no_partial_state(self, api, any_headers):
        """PRD §3.5: "the locomotive must be `AVAILABLE` ... and positioned at
        the plan's origin yard, meaning the unit's `current_yard_id` equals
        the plan's `origin_yard_id` (otherwise `ERR_UNIT_WRONG_YARD`,
        HTTP 409)" and "no crew is consumed at scheduling time — the pool is
        committed only at finalization."

        Design: Corner/consistency_model/rejected_write_leaves_no_partial_state
        """
        yA = create_yard(yard_code="IM2-A")
        yB = create_yard(yard_code="IM2-B")
        yC = create_yard(yard_code="IM2-C")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="IM2-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        pool = create_crew_pool(yA["id"])
        loco = create_locomotive(yC["id"], unit_number="IM2-UP1")
        resp = api.create_train_departure(
            {
                "train_plan_id": plan["id"], "service_date": "2026-09-01",
                "crew_pool_id": pool["id"], "locomotive_id": loco["id"],
                "car_count_planned": 5, "crew_hours_estimated": 6,
            },
            TS,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_WRONG_YARD.value)
        _data, meta = validate_paginated(api.list_train_departures(any_headers))
        assert meta["total_count"] == 0
        loco_now = get_locomotive(loco["id"])
        assert loco_now["status"] == "AVAILABLE"
        assert loco_now["current_yard_id"] == yC["id"]
        pool_now = get_success_data(api.get_crew_pool(pool["id"], ANY))
        assert pool_now["crews_booked"] == 0
