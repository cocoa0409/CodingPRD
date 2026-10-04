"""Difficulty-design translations: boundary precision checks.

Two inclusive equality boundaries: a component whose age at bottling is
exactly the label's age statement passes validation (PRD §3.5), and a
rickhouse flips to FULL exactly when occupied_slots reaches total_slots
(PRD §3.2).
"""
from test_helpers import (
    create_active_label,
    create_batch_with_component,
    create_commissioned_rickhouse,
    fill_barrels_on_slots,
    fill_placed_barrel,
    set_clock,
    validate_success,
)


def test_age_statement_exact_anniversary_passes(api, master_blender_headers):
    """PRD §3.5: "the barrel's age at the `scheduled_bottling_date` — the days
    between `fill_date` and that date, divided by 365, rounded down to whole
    years — must be at least the label's `age_statement_years`; a component
    whose age is exactly the statement satisfies the obligation, and any
    younger component fails validation with `ERR_AGE_STATEMENT_VIOLATION`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/age_statement_exact_anniversary_passes
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-AB",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])  # filled 2028-09-01
    label = create_active_label(name="Four Year", age_statement_years=4, spirit_type="BOURBON")

    set_clock("2032-08-15T00:00:00Z")
    # The scheduled bottling date 2032-08-31 is exactly 1460 days = 4 x 365-day
    # years after the 2028-09-01 fill: the component's age at bottling equals
    # the statement exactly, and the >= obligation is inclusive.
    batch, _component = create_batch_with_component(
        label["id"], barrel["id"], 10.0, scheduled_bottling_date="2032-08-31T00:00:00Z"
    )
    validated = validate_success(api.validate_blend_batch(batch["id"], master_blender_headers))
    assert validated["state"] == "VALIDATED"
    assert validated["validated_at"] is not None


def test_rickhouse_full_at_exact_capacity(api, warehouse_manager_headers):
    """PRD §3.2: "Once commissioned, the posture is `FULL` the moment
    `occupied_slots` reaches `total_slots` — equality is the trigger, so a
    house one slot short of capacity remains `OPERATING` — and it returns to
    `OPERATING` whenever occupancy drops back below capacity."

    Design: Difficulty/boundary_precision_check/rickhouse_full_at_exact_capacity
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=2, positions_per_row=2, name="RH-FC",
    )
    slots = ctx["slots"]
    fill_barrels_on_slots(
        [s["id"] for s in slots[:3]],
        fill_volume_liters=100.0,
        min_maturation_months=12,
    )

    rickhouse_id = ctx["rickhouse"]["id"]
    before = validate_success(api.get_rickhouse(rickhouse_id, warehouse_manager_headers))
    assert before["occupied_slots"] == 3
    assert before["occupied_slots"] == before["total_slots"] - 1
    assert before["posture"] == "OPERATING", "one slot short of capacity stays OPERATING"

    fill_placed_barrel(slots[3]["id"], fill_volume_liters=100.0, min_maturation_months=12)

    after = validate_success(api.get_rickhouse(rickhouse_id, warehouse_manager_headers))
    assert after["occupied_slots"] == 4
    assert after["occupied_slots"] == after["total_slots"]
    assert after["posture"] == "FULL", "equality with total_slots triggers FULL"
