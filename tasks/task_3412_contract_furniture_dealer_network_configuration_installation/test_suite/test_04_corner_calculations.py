"""Calculation corners: BOM merge/sort, queue-day tier boundary, fabric
upcharge rounding precision, and lazy agreement expiry (PRD §2.6, §3.2-§3.5).
"""

from test_helpers import (
    ApiErrorId,
    bom_expand,
    create_and_lock_configuration,
    create_configuration,
    create_end_user,
    create_order,
    create_product_family,
    create_volume_agreement,
    activate_agreement,
    get_agreement,
    lock_configuration,
    make_dealer_headers,
    make_module_entry,
    set_logical_clock,
    setup_dealer_world,
    setup_locked_world,
    submit_order,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _line_part(line):
    """Part identifier of a BOM line; the PRD pins the merge/sort semantics,
    not the per-line JSON key spelling, so accept common spellings."""
    for key in ("part_number", "part", "partNumber", "part_no"):
        if isinstance(line.get(key), str):
            return line[key]
    raise AssertionError(
        f"BOM line carries no recognizable part-number key: {sorted(line)}"
    )


def _line_qty(line):
    for key in ("total_qty", "qty", "quantity"):
        if isinstance(line.get(key), int) and not isinstance(line.get(key), bool):
            return line[key]
    raise AssertionError(
        f"BOM line carries no recognizable quantity key: {sorted(line)}"
    )


def test_bom_merges_shared_parts_and_sorts(api):
    """PRD §3.4: "Parts are then merged by part number across all module
    entries — a part shared by two module types appears once with its
    quantities summed — and the merged lines are sorted by part number in
    ascending lexicographic order." For 2 x WORKSTATION_6X6 (A) + 1 x
    PRIVATE_OFFICE (A): 7 distinct part numbers, PN-PNL-FAB merges to quantity
    8 (2x2 + 4x1), first line PN-DOOR, parts_total_cents 352411, total_units 3.

    Design: Corner/calculations/calc_bom_merges_shared_parts_and_sorts
    """
    ctx = setup_dealer_world(
        api, family_specs=(("SYS-7500", "SYSTEMS", 42),)
    )
    modules = [
        make_module_entry("WORKSTATION_6X6", "A", 2),
        make_module_entry("PRIVATE_OFFICE", "A", 1),
    ]
    spec = create_configuration(api, ctx["dealer"]["id"], modules=modules)

    bom = validate_success(
        api.get_configuration_bom(
            spec["id"], make_dealer_headers(ctx["dealer"]["id"])
        ),
        200,
    )
    expected = bom_expand(modules)
    assert bom["parts_total_cents"] == 352411
    assert bom["parts_total_cents"] == expected["parts_total_cents"]
    assert bom["total_units"] == 3

    lines = bom["lines"]
    part_sequence = [_line_part(line) for line in lines]
    # Merged: 5 workstation parts + PN-FRM-PO + PN-DOOR = 7 distinct lines.
    assert len(lines) == 7
    assert part_sequence == sorted(part_sequence), "lines sorted ascending"
    assert part_sequence[0] == "PN-DOOR"
    fab_lines = [l for l in lines if _line_part(l) == "PN-PNL-FAB"]
    assert len(fab_lines) == 1, "shared part appears exactly once"
    assert _line_qty(fab_lines[0]) == 8, "quantities summed across entries"


def test_queue_tier_boundary_49_vs_50_units(api):
    """PRD §3.4: "Queue days key off the whole configuration's `total_units`:
    3 queue days when `total_units` is at most 49, 7 when it is at least 50
    and at most 199, and 12 when it is 200 or more — so exactly 49 units
    still earns 3 queue days, exactly 50 earns 7, exactly 199 earns 7, and
    exactly 200 earns 12." On a base-28 SEATING family: 49 -> 31, 50 -> 35.

    Design: Corner/calculations/calc_queue_tier_boundary_49_vs_50_units
    """
    ctx = setup_dealer_world(
        api, family_specs=(("SEAT-2200", "SEATING", 28),)
    )
    spec49 = create_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("TASK_CHAIR_SET", "A", 49)],
    )
    spec50 = create_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("TASK_CHAIR_SET", "A", 50)],
    )
    locked49 = lock_configuration(api, spec49, ctx["dealer"]["id"])
    locked50 = lock_configuration(api, spec50, ctx["dealer"]["id"])
    assert locked49["max_lead_time_days"] == 31
    assert locked50["max_lead_time_days"] == 35


def test_fabric_upcharge_grade_c_precision(api):
    """PRD §2.6: "Order pricing applies rounding exactly twice: once per
    module line, where each line's exact extended amount is rounded to whole
    cents before any summation, and once on the discounted order total."
    1 x WORKSTATION_6X6 grade C: unit exact 85837 x 1.12 = 96137.44, line
    rounds half-up to 96137; provisional at tier 1 is
    round_half_up(96137 x 0.90) = 86523.

    Design: Corner/calculations/calc_fabric_upcharge_grade_c_precision
    """
    ctx = setup_locked_world(
        api,
        family_specs=(("SYS-7500", "SYSTEMS", 42),),
        modules=[make_module_entry("WORKSTATION_6X6", "C", 1)],
    )
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
    )
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    assert submitted["pre_discount_total_cents"] == 96137
    assert submitted["provisional_tier"] == 1
    assert submitted["provisional_total_cents"] == 86523


def test_agreement_lazy_expiry_on_read(api):
    """PRD §3.2: "Expiry is lazy and system-driven: on any read or write of
    an agreement, the server first checks whether the agreement is `ACTIVE`
    and the logical clock date is strictly after `effective_end`; if so, the
    agreement moves `ACTIVE → EXPIRED` — its terminal state — before the read
    or write proceeds against the new state."

    Design: Corner/calculations/calc_agreement_lazy_expiry_on_read
    """
    end_user = create_end_user(api, name="MegaCorp")
    agreement = create_volume_agreement(
        api, end_user["id"],
        effective_start="2026-01-01", effective_end="2026-10-01",
    )
    activate_agreement(api, agreement["id"])
    assert get_agreement(api, agreement["id"])["status"] == "ACTIVE"

    set_logical_clock(api, "2026-10-02T00:00:00Z")
    expired = get_agreement(api, agreement["id"])
    assert expired["status"] == "EXPIRED"
