"""Conserved quantities: disposition units and slot commitments (PRD §3.6, §3.7)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_NEXT,
    assert_disposition_invariant,
    factories,
    family_spec,
    order_line,
)
from test_helpers import fixtures


def _append_action(api, line_id, action_type, qty):
    return api.append_disposition_action(
        line_id, factories.disposition_action_payload(action_type, qty),
        PROGRAM_MANAGER_HEADERS,
    )


def test_disposition_actions_conserve_units_and_auto_retire(api):
    """Every action keeps logged + remaining == original; an overage is refused;
    the final action reconciles to zero and the line retires itself.

    PRD §3.7: "Each action's `qty` must be strictly positive and no greater than the line's `remaining_disposition_qty` (`ERR_DISPOSITION_OVERAGE`), the remainder decreases by the action's quantity, and the invariant that the logged quantities plus the remainder equal `original_disposition_qty` holds at all times."
    PRD §3.7: "A `SUNSETTING` line moves to `RETIRED` automatically at the moment its `remaining_disposition_qty` reaches zero and every display reset of that line stands in `COMPLETE` or `WAIVED` — whether the last condition falls into place through a disposition action, a completion, or a waiver."
    PRD §3.7: "When the retiring line was the program's last `SUNSETTING` line, the program itself completes the cycle: it returns `TRANSITIONING` → `ACTIVE`, with `transition_started_at`, `display_reset_deadline`, and `disposition_deadline` cleared to null, ready for the next generation of the line."
    Design: Difficulty/compensating_invariant/disposition_actions_conserve_physical_units
    """
    world = fixtures.setup_transitioning_program(
        api,
        store_codes=["ST-1"],
        disposition_qty=100,
        new_line_overrides={
            "families": [family_spec(standard_price_cents=11000, base_lead_weeks=2)],
        },
    )
    line1 = world["line1"]
    assert line1["status"] == "SUNSETTING"
    assert line1["remaining_disposition_qty"] == 100

    reset = world["resets"][0]
    fixtures.transition_display_reset(
        api, reset["id"], "SCHEDULED", scheduled_date="2026-09-10T09:00:00Z"
    )
    fixtures.transition_display_reset(api, reset["id"], "COMPLETE")

    after_rtv = validate_success(_append_action(api, line1["id"], "RTV", 40), 201)
    assert after_rtv["remaining_disposition_qty"] == 60
    assert_disposition_invariant(fixtures.get_line(api, line1["id"]))

    after_liquidate = validate_success(_append_action(api, line1["id"], "LIQUIDATE", 25), 201)
    assert after_liquidate["remaining_disposition_qty"] == 35

    overage = _append_action(api, line1["id"], "TRANSFER", 36)
    validate_error(overage, "ERR_DISPOSITION_OVERAGE")
    assert fixtures.get_line(api, line1["id"])["remaining_disposition_qty"] == 35

    after_transfer = validate_success(_append_action(api, line1["id"], "TRANSFER", 20), 201)
    assert after_transfer["remaining_disposition_qty"] == 15

    after_destroy = validate_success(_append_action(api, line1["id"], "DESTROY", 15), 201)
    assert after_destroy["remaining_disposition_qty"] == 0
    assert_disposition_invariant(after_destroy)

    retired = fixtures.get_line(api, line1["id"])
    assert retired["status"] == "RETIRED"
    program = fixtures.get_program(api, world["program"]["id"])
    assert program["status"] == "ACTIVE"
    assert program["transition_started_at"] is None
    assert program["display_reset_deadline"] is None
    assert program["disposition_deadline"] is None


def test_zero_quantity_rejected_and_destroy_reconciles(api):
    """A non-positive action violates the same invariant gate; completing the
    reset first lets the final DESTROY retire the line.

    PRD §3.7: "Each action's `qty` must be strictly positive and no greater than the line's `remaining_disposition_qty` (`ERR_DISPOSITION_OVERAGE`), the remainder decreases by the action's quantity, and the invariant that the logged quantities plus the remainder equal `original_disposition_qty` holds at all times."
    PRD §3.7: "A `SUNSETTING` line moves to `RETIRED` automatically at the moment its `remaining_disposition_qty` reaches zero and every display reset of that line stands in `COMPLETE` or `WAIVED` — whether the last condition falls into place through a disposition action, a completion, or a waiver."
    Design: Difficulty/compensating_invariant/disposition_actions_conserve_physical_units
    """
    world = fixtures.setup_transitioning_program(
        api, store_codes=["ST-1"], disposition_qty=50
    )
    line1 = world["line1"]

    reset = world["resets"][0]
    # COMPLETE is reachable directly from PLANNED.
    fixtures.transition_display_reset(api, reset["id"], "COMPLETE")

    zero = _append_action(api, line1["id"], "DESTROY", 0)
    validate_error(zero, "ERR_DISPOSITION_OVERAGE")
    assert fixtures.get_line(api, line1["id"])["remaining_disposition_qty"] == 50

    final = validate_success(_append_action(api, line1["id"], "DESTROY", 50), 201)
    assert final["remaining_disposition_qty"] == 0
    assert_disposition_invariant(final)

    assert fixtures.get_line(api, line1["id"])["status"] == "RETIRED"
    assert fixtures.get_program(api, world["program"]["id"])["status"] == "ACTIVE"


def test_cancel_from_scheduled_restores_slot_units(api):
    """Cancelling a scheduled order returns exactly its units and re-opens the
    auto-locked slot; the sibling commitment is untouched.

    PRD §3.6: "Cancelling a `SCHEDULED` order returns its committed units to each picked slot — re-opening a full slot automatically — and every cancellation, from any of the three states, recomputes the account's credit exposure and re-evaluates its held orders per §2.8."
    PRD §3.4: "A slot starts `OPEN` with `committed_units` at zero, locks automatically when commitments reach exactly its capacity, and re-opens automatically whenever a release drops commitments back below capacity."
    Design: Difficulty/compensating_invariant/slot_commit_then_cancel_restores_capacity_units
    """
    world = fixtures.setup_active_program(
        api, families=[family_spec(standard_price_cents=1000, base_lead_weeks=3)]
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=30)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=20)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=10)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    fixtures.acknowledge_order(api, o2["id"])
    fixtures.schedule_order(api, o1["id"])
    fixtures.schedule_order(api, o2["id"])

    def slot_state():
        slots, meta = validate_paginated(
            api.list_production_slots(
                PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
            )
        )
        assert meta["total_count"] == 1
        return slots[0]

    before = slot_state()
    assert before["committed_units"] == 30
    assert before["status"] == "LOCKED"

    cancelled = fixtures.cancel_order(api, o1["id"])
    assert cancelled["status"] == "CANCELLED"

    after = slot_state()
    assert after["committed_units"] == 10
    assert after["status"] == "OPEN"
    assert fixtures.get_order(api, o2["id"])["status"] == "SCHEDULED"


def test_cancel_acknowledged_leaves_slot_untouched(api):
    """An acknowledged order holds no slot units, so its cancellation changes
    no commitment; cancelling the scheduled one drains the slot to zero.

    PRD §3.6: "Cancelling a `SCHEDULED` order returns its committed units to each picked slot — re-opening a full slot automatically — and every cancellation, from any of the three states, recomputes the account's credit exposure and re-evaluates its held orders per §2.8."
    Design: Difficulty/compensating_invariant/slot_commit_then_cancel_restores_capacity_units
    """
    world = fixtures.setup_active_program(
        api, families=[family_spec(standard_price_cents=1000, base_lead_weeks=3)]
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=30)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=20)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=5)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    fixtures.acknowledge_order(api, o2["id"])
    fixtures.schedule_order(api, o1["id"])

    def committed():
        slots, _ = validate_paginated(
            api.list_production_slots(
                PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
            )
        )
        return slots[0]["committed_units"], slots[0]["status"]

    assert committed() == (20, "OPEN")

    fixtures.cancel_order(api, o2["id"])
    assert committed() == (20, "OPEN")

    fixtures.cancel_order(api, o1["id"])
    assert committed() == (0, "OPEN")
