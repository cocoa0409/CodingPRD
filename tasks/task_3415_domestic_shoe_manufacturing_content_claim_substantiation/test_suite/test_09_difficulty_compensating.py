"""Depth probes: compensating invariants (shift pool-sum conservation;
lot reserve/release quantity conservation)."""
from test_helpers import (
    get_allocation, get_lot, get_run, lock_allocation, make_allocation,
    make_run, release_run, reserve_run, set_clock, shift_allocation_payload,
    standard_kit, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]


def _shift_kit():
    """MSHIFT standard kit; allocation total 100; STOCK run of 30 created
    before lock -> waterfall yields domestic 30 / import 70."""
    kit = standard_kit(with_run=False, model_overrides={"style_code": "MSHIFT"})
    run = make_run(kit["model"]["id"], kit["factory"]["id"], planned_units=30)
    allocation = lock_allocation(kit["allocation"]["id"])
    kit.update({"run": run, "allocation": allocation})
    return kit


def test_shift_forward_moves_units_and_conserves_total():
    """PRD §3.4: "A successful shift moves exactly `units` pairs between the
    pools in the requested direction, preserving the invariant that the two
    pools sum to `total_reserved_units`, and increments `version` by 1."
    PRD §3.4: "For a `DOMESTIC` factory, demand is summed over the runs of that
    factory and week currently in `PLANNED` or `MATERIAL_RESERVED`, bucketed by
    `run_type`: first the `GOVERNMENT` bucket, then `CUSTOM_BATCH`, then
    `STOCK`."

    Design: Difficulty/compensating_invariant/capacity_shift_conserves_total_reserved_units
    """
    kit = _shift_kit()
    allocation = kit["allocation"]
    assert allocation["domestic_reserved_units"] == 30
    assert allocation["import_reserved_units"] == 70
    assert allocation["domestic_reserved_units"] + allocation["import_reserved_units"] == 100

    shifted = validate_success(api.shift_allocation(
        allocation["id"],
        shift_allocation_payload("TO_DOMESTIC", 20, allocation["version"]), ADMIN))
    # 20 units moved import -> domestic: 50 / 50; the sum is still 100.
    assert shifted["domestic_reserved_units"] == 50
    assert shifted["import_reserved_units"] == 50
    assert shifted["domestic_reserved_units"] + shifted["import_reserved_units"] == 100


def test_shift_compensating_pair_restores_original_pools():
    """PRD §3.4: "A successful shift moves exactly `units` pairs between the
    pools in the requested direction, preserving the invariant that the two
    pools sum to `total_reserved_units`, and increments `version` by 1."

    Design: Difficulty/compensating_invariant/capacity_shift_conserves_total_reserved_units
    """
    kit = _shift_kit()
    allocation = kit["allocation"]
    shifted = validate_success(api.shift_allocation(
        allocation["id"],
        shift_allocation_payload("TO_DOMESTIC", 20, allocation["version"]), ADMIN))
    restored = validate_success(api.shift_allocation(
        allocation["id"],
        shift_allocation_payload("TO_IMPORT", 20, shifted["version"]), ADMIN))
    # The forward/compensating pair returns the pools to exactly (30, 70).
    assert restored["domestic_reserved_units"] == 30
    assert restored["import_reserved_units"] == 70
    assert restored["domestic_reserved_units"] + restored["import_reserved_units"] == 100


def _conservation_kit():
    """MCONS standard kit with a 500-unit thread lot; allocation total 500;
    STOCK run of 200 created before lock (domestic pool 200)."""
    kit = standard_kit(alloc_total=500, run_units=200, lot_qty=500,
                       model_overrides={"style_code": "MCONS"})
    lock_allocation(kit["allocation"]["id"])
    return kit


def test_reserve_draws_lot_down_exactly():
    """PRD §3.5: "On success, the system appends one entry per contributing lot
    to the run's `consumed_lots` — recording the `lot_id`, `component_id`,
    `units_consumed`, `unit_cost_cents`, and `is_domestic` of each draw —
    decrements each lot's `quantity_remaining` (bumping each lot's `version`
    by 1), and increments the run's `version` by 1."

    Design: Difficulty/compensating_invariant/lot_reserve_release_conserves_received_quantity
    """
    kit = _conservation_kit()
    run = reserve_run(kit["run"]["id"])
    lot = get_lot(kit["lot"]["id"])
    # Invariant: quantity_received 500 == quantity_remaining 300 + consumed 200.
    assert lot["quantity_remaining"] == 300
    assert run["consumed_lots"] == [{
        "lot_id": kit["lot"]["id"], "component_id": kit["component"]["id"],
        "units_consumed": 200, "unit_cost_cents": 100, "is_domestic": True,
    }]
    assert lot["quantity_received"] == lot["quantity_remaining"] + 200


def test_release_restores_lot_received_quantity_exactly():
    """PRD §3.5: "Reservation and release form a compensating pair that
    conserves each lot's `quantity_received`: what reservation draws down,
    release restores exactly."
    PRD §3.5: "Every lot in the run's `consumed_lots` is re-credited — each
    lot's `quantity_remaining` grows by the units that were consumed and its
    `version` increments — and the run's `consumed_lots` is cleared, with the
    run's `version` incrementing by 1."

    Design: Difficulty/compensating_invariant/lot_reserve_release_conserves_received_quantity
    """
    kit = _conservation_kit()
    reserve_run(kit["run"]["id"])
    released = release_run(kit["run"]["id"])
    lot = get_lot(kit["lot"]["id"])
    # Invariant restored: 500 == 500 + 0 with an empty consumption record.
    assert lot["quantity_remaining"] == 500 == lot["quantity_received"]
    assert released["consumed_lots"] == []
    assert released["status"] == "PLANNED"
