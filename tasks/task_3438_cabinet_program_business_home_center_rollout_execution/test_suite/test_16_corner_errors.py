"""Error-catalog coverage: missing CURRENT batch at production, late cancel (PRD §3.4, §3.6)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    PLATFORM_ADMIN_HEADERS,
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_NEXT,
    factories,
    order_line,
)
from test_helpers import fixtures


def test_in_production_without_current_batch_rejected(api):
    """Production start pins each line's finish batch; with none CURRENT the
    transition is refused, and registering a batch unblocks it.

    PRD §3.4: "Production start, moving `SCHEDULED` → `IN_PRODUCTION` under a `PlantScheduler`, requires for every order line a `CURRENT` finish batch for that line's `finish_code` (`ERR_NO_CURRENT_BATCH`), and pins each line's `finish_batch_id` to that batch."
    PRD §3.4: "Between a retirement and the registration of a successor, a finish code has no `CURRENT` batch at all — and every rule that needs one, from production pinning to replacement color checks, then fails with `ERR_NO_CURRENT_BATCH`."
    Design: Corner/errors/in_production_without_current_batch_rejected
    """
    world = fixtures.setup_active_program(api)
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=10)
    order = fixtures.place_order(
        api, world["account"], world["program"],
        lines=[order_line(finish_code="MAPLE", quantity=1)],
    )
    fixtures.acknowledge_order(api, order["id"])
    fixtures.schedule_order(api, order["id"])

    blocked = api.transition_order(
        order["id"], {"to_status": "IN_PRODUCTION"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_NO_CURRENT_BATCH")
    assert fixtures.get_order(api, order["id"])["status"] == "SCHEDULED"

    batch_resp = api.create_finish_batch(
        factories.finish_batch_payload(
            finish_code="MAPLE", batch_code="M1", lab_l=60, lab_a=10, lab_b=10,
            effective_from="2026-09-01T00:00:00Z",
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_success(batch_resp, 201)

    started = fixtures.start_production(api, order["id"])
    assert started["status"] == "IN_PRODUCTION"
    assert started["lines"][0]["finish_batch_id"] is not None


def test_order_cancel_too_late_rejected(api):
    """Cancellation closes after SCHEDULED; from IN_PRODUCTION it is refused
    and the slot commitment stands.

    PRD §3.6: "It is available to a `ProgramManager`, or to the `DealerRep` who owns the order's account (`ERR_FORBIDDEN` for anyone else), and only from `SUBMITTED`, `ACKNOWLEDGED`, or `SCHEDULED`; from `IN_PRODUCTION`, `MFG_COMPLETE`, `SHIPPED`, `DELIVERED`, or `CANCELLED` the request is rejected with `ERR_ORDER_NOT_CANCELLABLE`."
    Design: Corner/errors/order_cancel_too_late_rejected
    """
    world = fixtures.setup_scheduled_order(
        api, slot_overrides={"week": WEEK_NEXT, "capacity_units": 10}
    )
    fixtures.start_production(api, world["order"]["id"])

    blocked = api.cancel_order(world["order"]["id"], PROGRAM_MANAGER_HEADERS)
    validate_error(blocked, "ERR_ORDER_NOT_CANCELLABLE")

    after = fixtures.get_order(api, world["order"]["id"])
    assert after["status"] == "IN_PRODUCTION"

    slots, meta = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert meta["total_count"] == 1
    assert slots[0]["committed_units"] == 1
