"""Difficulty-design translations: resource temporal-overlap rules (half-open
occupancy intervals, the thirty-day sampling buffer) and compensating
invariants (rotation round-trip, reservation create/release).
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    create_assessment_payload,
    create_barrel_payload,
    create_commissioned_rickhouse,
    create_reservation,
    fill_placed_barrel,
    get_barrel_fresh,
    get_program_fresh,
    get_success_data,
    record_quality_sample,
    release_reservation,
    rotate_barrel,
    set_clock,
    setup_program_with_mature_barrel,
    validate_error,
    validate_success,
)


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant (fractional seconds optional)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_slot_occupancy_half_open_overlap_and_adjacency(api, warehouse_manager_headers):
    """PRD §3.2: "if an existing `OPEN` occupancy on that slot overlaps the new
    interval, the request fails with `ERR_SLOT_OCCUPANCY_OVERLAP` (HTTP 409) —
    because intervals are half-open, adjacency is allowed, so a new occupancy
    starting exactly when the old one ends is not an overlap."
    PRD §3.2: "Rotation closes the barrel's currently `OPEN` occupancy (its
    `end_at` is stamped with the current clock and its `status` becomes
    `CLOSED`) and opens a successor occupancy on the destination slot with
    `move_reason` `ROTATION`"

    Design: Difficulty/resource_temporal_overlap/slot_occupancy_half_open_overlap_and_adjacency
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=2, name="RH-OV",
    )
    slot_1, slot_2 = ctx["slots"][0], ctx["slots"][1]
    barrel_1 = fill_placed_barrel(slot_1["id"], fill_volume_liters=100.0, min_maturation_months=12)

    # A second fill into the occupied slot overlaps the open interval.
    validate_error(
        api.create_barrel(
            create_barrel_payload(
                slot_1["id"], spirit_type="RYE", fill_proof=110.0,
                fill_volume_liters=90.0, min_maturation_months=12,
            ),
            warehouse_manager_headers,
        ),
        ApiErrorId.ERR_SLOT_OCCUPANCY_OVERLAP,
    )

    # Rotating barrel_1 out closes its occupancy at 2028-10-01.
    set_clock("2028-10-01T00:00:00Z")
    rotate_barrel(barrel_1["id"], slot_2["id"])

    # Adjacency: a new occupancy starting exactly when the old one ended is not
    # an overlap and must be accepted.
    barrel_2 = validate_success(
        api.create_barrel(
            create_barrel_payload(
                slot_1["id"], spirit_type="RYE", fill_proof=110.0,
                fill_volume_liters=90.0, min_maturation_months=12,
            ),
            warehouse_manager_headers,
        ),
        expected_status=201,
    )
    assert barrel_2["maturation_status"] == "AGING"

    occupancies = get_success_data(
        api.list_slot_occupancies(slot_1["id"], warehouse_manager_headers)
    )
    assert len(occupancies) == 2
    closed = [o for o in occupancies if o["status"] == "CLOSED"]
    opened = [o for o in occupancies if o["status"] == "OPEN"]
    assert len(closed) == 1 and len(opened) == 1
    assert closed[0]["barrel_id"] == barrel_1["id"]
    assert _instant(closed[0]["end_at"]) == _instant("2028-10-01T00:00:00Z")
    assert opened[0]["barrel_id"] == barrel_2["id"]
    assert _instant(opened[0]["start_at"]) == _instant("2028-10-01T00:00:00Z")


def test_quality_sample_thirty_day_buffer(api, warehouse_manager_headers):
    """PRD §3.3: "Sampling is rate-limited per barrel: a `QUALITY_SAMPLE`
    recorded fewer than thirty days after the same barrel's previous
    `QUALITY_SAMPLE` is rejected with `ERR_SAMPLE_BUFFER_VIOLATION`
    (HTTP 409); exactly thirty days is allowed."
    PRD §3.3: "a `QUALITY_SAMPLE` subtracts its `sample_draw_liters`"

    Design: Difficulty/resource_temporal_overlap/quality_sample_thirty_day_buffer
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-SB",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"])

    set_clock("2029-03-01T00:00:00Z")
    record_quality_sample(barrel["id"], sample_draw_liters=1.0, quality_score=90)

    # 20 days later: inside the thirty-day buffer.
    set_clock("2029-03-21T00:00:00Z")
    validate_error(
        api.create_barrel_assessment(
            barrel["id"],
            create_assessment_payload("QUALITY_SAMPLE", sample_draw_liters=1.0, quality_score=91),
            warehouse_manager_headers,
        ),
        ApiErrorId.ERR_SAMPLE_BUFFER_VIOLATION,
    )

    # Exactly thirty days after the first sample: the boundary is allowed.
    set_clock("2029-03-31T00:00:00Z")
    validate_success(
        api.create_barrel_assessment(
            barrel["id"],
            create_assessment_payload("QUALITY_SAMPLE", sample_draw_liters=1.0, quality_score=92),
            warehouse_manager_headers,
        ),
        expected_status=201,
    )

    after = get_barrel_fresh(barrel["id"])
    assert after["current_volume_ledger_liters"] == 198.00, (
        "two successful 1.0 L draws: 200.00 - 1.00 - 1.00"
    )


def test_rotation_round_trip_conserves_bonded_volume(api, warehouse_manager_headers):
    """PRD §3.2: "Rotation closes the barrel's currently `OPEN` occupancy (its
    `end_at` is stamped with the current clock and its `status` becomes
    `CLOSED`) and opens a successor occupancy on the destination slot with
    `move_reason` `ROTATION`; the barrel's `version` increments, and posture
    recomputes on both the source and destination rickhouses."
    PRD §3.3: "It starts at the barrel's `fill_volume_liters` and replays, in
    chronological order, every recorded event touching the barrel" — rotation
    records no ledger event, so the rotate/rotate-back pair moves no liquid.

    Design: Difficulty/compensating_invariant/rotation_round_trip_conserves_bonded_volume
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=3, name="RH-RC",
    )
    slot_1, slot_2, slot_3 = ctx["slots"]
    barrel_a = fill_placed_barrel(slot_1["id"], fill_volume_liters=200.0, min_maturation_months=48)
    barrel_b = fill_placed_barrel(slot_2["id"], fill_volume_liters=150.0, min_maturation_months=48)

    def bonded_ledger_total() -> float:
        # Both barrels remain custody BONDED throughout; sum their ledgers.
        return (
            get_barrel_fresh(barrel_a["id"])["current_volume_ledger_liters"]
            + get_barrel_fresh(barrel_b["id"])["current_volume_ledger_liters"]
        )

    assert bonded_ledger_total() == 350.00

    set_clock("2028-10-01T00:00:00Z")
    rotate_barrel(barrel_a["id"], slot_3["id"])
    set_clock("2028-11-01T00:00:00Z")
    rotate_barrel(barrel_a["id"], slot_1["id"])

    after_a = get_barrel_fresh(barrel_a["id"])
    after_b = get_barrel_fresh(barrel_b["id"])
    assert after_a["current_volume_ledger_liters"] == 200.00
    assert after_b["current_volume_ledger_liters"] == 150.00
    assert after_a["custody_status"] == "BONDED"
    assert after_b["custody_status"] == "BONDED"
    assert bonded_ledger_total() == 350.00, (
        "invariant: the rotate/rotate-back pair conserves total bonded ledger volume"
    )

    occupancies = get_success_data(
        api.list_barrel_occupancies(barrel_a["id"], warehouse_manager_headers)
    )
    assert len(occupancies) == 3
    # start_at ascending (PRD §3.2): slot1 CLOSED, slot3 CLOSED, slot1 OPEN.
    assert occupancies[0]["slot_id"] == slot_1["id"]
    assert occupancies[0]["status"] == "CLOSED"
    assert _instant(occupancies[0]["start_at"]) == _instant("2028-09-01T00:00:00Z")
    assert _instant(occupancies[0]["end_at"]) == _instant("2028-10-01T00:00:00Z")
    assert occupancies[1]["slot_id"] == slot_3["id"]
    assert occupancies[1]["status"] == "CLOSED"
    assert _instant(occupancies[1]["start_at"]) == _instant("2028-10-01T00:00:00Z")
    assert _instant(occupancies[1]["end_at"]) == _instant("2028-11-01T00:00:00Z")
    assert occupancies[2]["slot_id"] == slot_1["id"]
    assert occupancies[2]["status"] == "OPEN"
    assert occupancies[2]["end_at"] is None
    assert _instant(occupancies[2]["start_at"]) == _instant("2028-11-01T00:00:00Z")

    rickhouse = validate_success(api.get_rickhouse(ctx["rickhouse"]["id"], warehouse_manager_headers))
    assert rickhouse["occupied_slots"] == 2
    assert rickhouse["posture"] == "OPERATING"


def test_reservation_create_release_conserves_available_slots(api, program_director_headers):
    """PRD §3.6: "The program's `available_slots` is derived:
    `required_barrel_count` minus its reservations in `ACTIVE`, minus its
    reservations in `CONSUMED`."
    PRD §3.6: "Releasing an `ACTIVE` reservation moves it to `RELEASED` and
    compensates the program: `available_slots` increases by exactly one, with
    the invariant that create-then-release leaves `available_slots` unchanged."

    Design: Difficulty/compensating_invariant/reservation_create_release_conserves_available_slots
    """
    ctx = setup_program_with_mature_barrel(
        program_overrides={
            "name": "Quota Check",
            "min_quality_score": 0,
            "required_barrel_count": 2,
            "reservation_window_days": 45,
        }
    )
    program = ctx["program"]
    barrel = ctx["barrel"]

    initial = get_program_fresh(program["id"])
    assert initial["available_slots"] == 2

    reservation = create_reservation(program["id"], barrel["id"])
    assert reservation["state"] == "ACTIVE"
    after_create = get_program_fresh(program["id"])
    assert after_create["available_slots"] == 1, "2 required - 1 ACTIVE - 0 CONSUMED"

    released = release_reservation(reservation["id"])
    assert released["state"] == "RELEASED"

    after_release = get_program_fresh(program["id"])
    assert after_release["available_slots"] == 2, (
        "compensation restores the pre-create value exactly"
    )

    consumed = get_success_data(
        api.list_program_reservations(
            program["id"], program_director_headers, params={"state": "CONSUMED"}
        )
    )
    assert consumed == [], "release is not a consume"
