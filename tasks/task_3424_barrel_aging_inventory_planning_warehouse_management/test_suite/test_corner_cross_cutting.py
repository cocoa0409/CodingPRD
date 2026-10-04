"""Corner-design translations: optimistic concurrency control on parent
versions (PRD §2.7) and the lazy, clock-driven reservation expiry (PRD §3.6).

Version assertions are relative (observed version + 1) because PRD §2.5 pins
"an integer that increments by one on every mutation of the resource" without
pinning the initial value.
"""
from test_helpers import (
    ApiErrorId,
    add_blend_component_payload,
    create_blend_batch,
    create_commissioned_rickhouse,
    create_label_payload,
    create_program,
    create_reservation,
    create_reservation_payload,
    fill_mature_barrel,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    get_program_fresh,
    get_success_data,
    rotate_barrel_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_occ_blend_component_stale_version_rejected(api, master_blender_headers):
    """PRD §2.7: "Adding a component to a blend batch — `POST
    /barrel-aging/blend-batches/{id}/components` — requires
    `expected_blend_batch_version` carrying the batch `version` the client last
    observed. If the batch's current `version` differs, the request is rejected
    with `ERR_STALE_BLEND_BATCH_VERSION` (HTTP 412)."
    PRD §3.5: "Every add increments the batch's `version`, which is precisely
    why the expectation field exists."

    Design: Corner/cross_cutting_complexity_layers/occ_blend_component_stale_version_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-X1",
    )
    barrel_1 = fill_mature_barrel(ctx["slots"][0]["id"])
    barrel_2 = fill_mature_barrel(ctx["slots"][1]["id"])
    label = get_success_data(
        api.create_label(
            create_label_payload(name="OCC Batch", age_statement_years=1, spirit_type="BOURBON"),
            master_blender_headers,
        )
    )
    batch = create_blend_batch(label["id"], "2030-09-01T00:00:00Z")
    observed_version = batch["version"]

    # First add with the observed version succeeds and bumps the batch version.
    validate_success(
        api.add_blend_component(
            batch["id"],
            add_blend_component_payload(barrel_1["id"], 10.0, observed_version),
            master_blender_headers,
        ),
        expected_status=201,
    )

    # Second add still carrying the pre-add version is stale.
    resp = api.add_blend_component(
        batch["id"],
        add_blend_component_payload(barrel_2["id"], 10.0, observed_version),
        master_blender_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_BLEND_BATCH_VERSION)

    after = get_blend_batch_fresh(batch["id"])
    assert after["version"] == observed_version + 1, (
        "only the first add mutated the batch (one increment, PRD §2.5)"
    )
    components, _meta = validate_paginated(
        api.list_blend_components(batch["id"], master_blender_headers)
    )
    assert len(components) == 1 and components[0]["barrel_id"] == barrel_1["id"], (
        "the rejected second add persisted no component"
    )


def test_occ_reservation_stale_program_version_rejected(api, program_director_headers):
    """PRD §2.7: "Creating a reservation under a program — `POST
    /barrel-aging/private-selection-programs/{id}/reservations` — requires
    `expected_program_version` carrying the program `version` the client last
    observed; a mismatch is rejected with `ERR_STALE_PROGRAM_VERSION`
    (HTTP 412)."
    PRD §3.6: "A successful reservation is created `ACTIVE`, recording its
    `program_id`, with `expires_at` set to its creation time plus the program's
    `reservation_window_days`; the new `ACTIVE` reservation drops
    `available_slots` by one, and the program's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/occ_reservation_stale_program_version_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-X2",
    )
    barrel_1 = fill_mature_barrel(ctx["slots"][0]["id"])
    barrel_2 = fill_mature_barrel(ctx["slots"][1]["id"])
    # required_barrel_count 2: quota remains for both barrels, so the stale
    # version is the only losing condition on the second reservation.
    program = create_program(
        name="OCC Program", min_quality_score=0,
        required_barrel_count=2, reservation_window_days=45,
    )
    observed_version = program["version"]

    validate_success(
        api.create_reservation(
            program["id"],
            create_reservation_payload(barrel_1["id"], observed_version),
            program_director_headers,
        ),
        expected_status=201,
    )

    resp = api.create_reservation(
        program["id"],
        create_reservation_payload(barrel_2["id"], observed_version),
        program_director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

    program_after = get_program_fresh(program["id"])
    assert program_after["available_slots"] == 1, (
        "2 required minus 1 ACTIVE reservation; the stale request counted nothing"
    )


def test_occ_rotation_stale_barrel_version_rejected(api, warehouse_manager_headers):
    """PRD §2.7: "Rotating a barrel — `POST /barrel-aging/barrels/{id}/rotations`
    — requires `expected_barrel_version` carrying the barrel `version` the
    client last observed; a mismatch is rejected with `ERR_STALE_BARREL_VERSION`
    (HTTP 412)."
    PRD §3.2: "Rotation closes the barrel's currently `OPEN` occupancy (its
    `end_at` is stamped with the current clock and its `status` becomes
    `CLOSED`) and opens a successor occupancy on the destination slot with
    `move_reason` `ROTATION`; the barrel's `version` increments, and posture
    recomputes on both the source and destination rickhouses."
    PRD §3.2: "Its `current_slot_id` is computed — the `slot_id` of its `OPEN`
    occupancy, or null when no occupancy is open — and the occupancy records,
    keyed by `barrel_id` and `slot_id`, are the source of truth."

    Design: Corner/cross_cutting_complexity_layers/occ_rotation_stale_barrel_version_rejected
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=3, name="RH-X3",
    )
    slot_1, slot_2, slot_3 = (s["id"] for s in ctx["slots"])
    barrel = fill_placed_barrel(slot_1)  # AGING, version observed at creation
    observed_version = barrel["version"]

    moved = validate_success(
        api.rotate_barrel(
            barrel["id"],
            rotate_barrel_payload(slot_2, observed_version),
            warehouse_manager_headers,
        )
    )
    assert moved["current_slot_id"] == slot_2

    resp = api.rotate_barrel(
        barrel["id"],
        rotate_barrel_payload(slot_3, observed_version),
        warehouse_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_BARREL_VERSION)

    after = get_barrel_fresh(barrel["id"])
    assert after["version"] == observed_version + 1, (
        "only the first rotation mutated the barrel (one increment, PRD §2.5)"
    )
    assert after["current_slot_id"] == slot_2, "the rejected rotation moved nothing"


def test_scheduled_reservation_expiry_restores_quota(api, program_director_headers):
    """PRD §3.6: "Expiry is the lazy exit. When the current logical clock moves
    strictly past a reservation's `expires_at` — a clock exactly equal to
    `expires_at` does not expire it — the reservation transitions `ACTIVE` →
    `EXPIRED` on the next clock-set or read, `available_slots` increases by
    exactly one, and the program's `version` increments."
    PRD §3.6: "Only an `ACTIVE` reservation can be consumed — and because
    expiry is lazy, a reservation whose `expires_at` has passed has already
    become `EXPIRED` by the time it is read, so consuming a lapsed reservation
    fails the from-state check with `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD §2.3: "`state` on the barrel-reservation, blend-batch,
    program-reservation, and bonded-report lists".

    Design: Corner/cross_cutting_complexity_layers/scheduled_reservation_expiry_restores_quota
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-X4",
    )
    barrel = fill_mature_barrel(ctx["slots"][0]["id"])  # filled 2028-09-01
    program = create_program(
        name="Expiry Check", min_quality_score=0,
        required_barrel_count=1, reservation_window_days=45,
    )
    assert program["available_slots"] == 1

    reservation = create_reservation(program["id"], barrel["id"])
    assert reservation["state"] == "ACTIVE"
    assert get_program_fresh(program["id"])["available_slots"] == 0

    # Creation at 2028-09-01 plus a 45-day window puts expires_at at
    # 2028-10-16; the clock at 2028-10-17 is strictly past it.
    set_clock("2028-10-17T00:00:00Z")

    program_after = get_program_fresh(program["id"])
    assert program_after["available_slots"] == 1, (
        "the lazy expiry restored the consumed quota slot"
    )

    expired, _meta = validate_paginated(
        api.list_program_reservations(
            program["id"], program_director_headers, params={"state": "EXPIRED"},
        )
    )
    assert [r["id"] for r in expired] == [reservation["id"]], (
        "the state=EXPIRED filter returns exactly the lapsed reservation"
    )

    resp = api.consume_reservation(reservation["id"], program_director_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
