"""Under way, alongside and broken up: the departure cascade, the discharge
axis and the hulls that come back dirty."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_fleeting_assignment,
    create_fleeting_berth,
    make_contract_manager_headers,
    make_towboat_dispatcher_headers,
    read_assignment,
    read_barge,
    read_berth,
    read_contract,
    read_fleeting_assignment,
    read_tow,
    record_barge_arrival,
    seal_tow,
    setup_grain_movement,
    setup_grain_reference,
    start_unload,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCH = make_towboat_dispatcher_headers()
BILLER = make_contract_manager_headers()


def test_departure_cascade_is_fully_visible_in_the_same_request(api):
    """PRD §3.7: "Every fleeting reservation standing in `RESERVED` whose barge
    holds a `CONFIRMED` assignment on this tow is driven `RESERVED → RELEASED`
    with its `released_at` set to the tow's `departed_at`, which fixes that
    reservation's `billable_days` and `fee_cents` by the same arithmetic an
    ordinary release would use and decrements the berth's
    `occupied_barge_count` — departure automatically clears the harbor, because
    a barge cannot be both under way and sitting on a fleeting berth."
    PRD §3.7: "And every distinct freight contract named by those assignments
    whose `movement_status` stands in `ACTIVE` advances to `IN_TRANSIT`."
    PRD §2.10: "Cascades are immediate and complete. When an operation is
    specified to touch sibling or parent rows, those rows are updated within the
    same request, their `version` counters increment and their `updated_at`
    timestamps refresh, and the effects are visible to the very next read."

    Design: Corner/consistency_model/departure_cascade_is_fully_visible_in_the_same_request
    """
    reference = setup_grain_reference()
    berth = create_fleeting_berth(capacity_barges=4, daily_fee_cents_per_barge=15_000,
                                  switch_fee_cents=60_000)
    movement = setup_grain_movement(
        loads=(1700,), reference=reference, stage="BUILDING",
        tow_kwargs={"towboat_name": "M/V Whiskey"})
    hull = movement["barges"][0]
    reservation = create_fleeting_assignment(
        hull["id"], berth["id"], start_at="2026-08-12T12:00:00Z",
        end_at="2026-08-20T00:00:00Z", freight_contract_id=movement["contract_id"])
    seal_tow(movement["tow_id"])

    departed = validate_success(api.depart_tow(
        movement["tow_id"], {"departed_at": "2026-08-14T12:00:00Z"}, DISPATCH))
    assert departed["status"] == "UNDERWAY"
    assert_same_instant(departed["departed_at"], "2026-08-14T12:00:00Z")

    assert read_assignment(movement["assignments"][0]["id"])["status"] == "LOADED"
    contract = read_contract(movement["contract_id"])
    assert contract["movement_status"] == "IN_TRANSIT"
    assert contract["billing_status"] == "NOT_BILLED", "only the movement axis moved"

    released = read_fleeting_assignment(reservation["id"])
    assert released["status"] == "RELEASED"
    assert_same_instant(released["released_at"], "2026-08-14T12:00:00Z")
    assert released["billable_days"] == 2
    assert released["fee_cents"] == 90_000, (
        f"two billable days at 15000 plus the 60000 switch fee, "
        f"got {released['fee_cents']}")
    assert read_berth(berth["id"])["occupied_barge_count"] == 0

    hull = read_barge(hull["id"])
    assert hull["operational_status"] == "IN_TOW"
    assert hull["cleanliness_status"] == "WASHED", "the cleanliness axis is untouched"

    rows, meta = validate_paginated(api.list_fleeting_assignments(
        BILLER, params={"freight_contract_id": movement["contract_id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["fee_cents"] == 90_000


def test_break_up_returns_every_hull_dirty_with_its_last_cargo_recorded(api):
    """PRD §3.7: "Break-up moves the tow to the terminal `BROKEN_UP`, advances
    every `LOADED` assignment to the terminal `DISCHARGED`, and returns every
    hull named by those assignments from `operational_status` `IN_TOW` to
    `IDLE`."
    PRD §3.7: "Each of those hulls also has its `cleanliness_status` driven to
    `DIRTY` on the cleanliness axis, its `last_cargo_commodity_id` set to the
    `commodity_id` of the freight contract its assignment was moving, and its
    `last_cleaning_certificate_number` cleared — the certificate the hull held
    is void the moment it carries cargo, which is exactly what makes the next
    voyage's compatibility check meaningful."
    PRD §3.7: "That same completion carries a cross-entity consequence: when
    **every** non-`DROPPED` assignment of the named freight contract has reached
    `discharge_status` `COMPLETED`, that contract advances on its movement axis
    from `IN_TRANSIT` to `DISCHARGED`."

    Design: Corner/state_machines/tow_break_up_returns_every_hull_dirty_with_its_last_cargo_recorded
    """
    movement = setup_grain_movement(loads=(1700,), stage="DISCHARGED")
    assert read_contract(movement["contract_id"])["movement_status"] == "DISCHARGED", (
        "the bubble-up fired when the last cut finished unloading")

    broken = validate_success(api.break_up_tow(movement["tow_id"], DISPATCH))
    assert broken["status"] == "BROKEN_UP"

    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["status"] == "DISCHARGED"
    assert assignment["discharge_status"] == "COMPLETED"

    hull = read_barge(movement["barges"][0]["id"])
    assert hull["operational_status"] == "IDLE"
    assert hull["cleanliness_status"] == "DIRTY"
    assert hull["last_cargo_commodity_id"] == movement["commodity_id"]
    assert not hull.get("last_cleaning_certificate_number"), (
        "the certificate the hull held is void once it carried cargo")


def test_start_unload_before_the_barge_is_tendered_is_refused(api):
    """PRD §3.7: "Starting the unload supplies `unload_started_at`, which must
    be at or after the assignment's `arrived_at`, and moves `discharge_status`
    `ARRIVED → UNLOADING`."
    PRD §3.7: "Any of these three called out of sequence on the discharge axis
    is refused with `ERR_BARGE_ASSIGNMENT_INVALID_STATE`, while an out-of-order
    instant is refused with `ERR_UNLOAD_SEQUENCE_INVALID`."

    Design: Corner/state_machines/start_unload_before_the_barge_is_tendered_returns_assignment_invalid_state
    """
    movement = setup_grain_movement(loads=(1700,), stage="ARRIVED")
    assignment_id = movement["assignments"][0]["id"]

    validate_error(api.start_unload(
        assignment_id, {"unload_started_at": "2026-08-20T18:00:00Z"}, DISPATCH),
        ApiErrorId.ERR_BARGE_ASSIGNMENT_INVALID_STATE.value)

    stored = read_assignment(assignment_id)
    assert stored["discharge_status"] == "NOT_ARRIVED"
    assert stored.get("unload_started_at") is None
    assert read_contract(movement["contract_id"])["movement_status"] == "IN_TRANSIT"


def test_discharge_timestamps_must_follow_the_instant_they_succeed(api):
    """PRD §3.7: "Starting the unload supplies `unload_started_at`, which must
    be at or after the assignment's `arrived_at`, and moves `discharge_status`
    `ARRIVED → UNLOADING`."
    PRD §3.7: "Any of these three called out of sequence on the discharge axis
    is refused with `ERR_BARGE_ASSIGNMENT_INVALID_STATE`, while an out-of-order
    instant is refused with `ERR_UNLOAD_SEQUENCE_INVALID`."

    Design: Corner/validations/discharge_timestamp_sequence_guards_reject_out_of_order_instants
    """
    movement = setup_grain_movement(loads=(1700,), stage="ARRIVED")
    assignment_id = movement["assignments"][0]["id"]
    record_barge_arrival(assignment_id, "2026-08-20T06:00:00Z")

    validate_error(api.start_unload(
        assignment_id, {"unload_started_at": "2026-08-20T05:00:00Z"}, DISPATCH),
        ApiErrorId.ERR_UNLOAD_SEQUENCE_INVALID.value)
    stored = read_assignment(assignment_id)
    assert stored["discharge_status"] == "ARRIVED"
    assert stored.get("unload_started_at") is None

    started = start_unload(assignment_id, "2026-08-20T18:00:00Z")
    assert started["discharge_status"] == "UNLOADING"

    validate_error(api.finish_unload(
        assignment_id,
        {"unload_finished_at": "2026-08-20T17:00:00Z", "discharged_tons": 1687},
        DISPATCH),
        ApiErrorId.ERR_UNLOAD_SEQUENCE_INVALID.value)
    stored = read_assignment(assignment_id)
    assert stored["discharge_status"] == "UNLOADING"
    assert stored.get("unload_finished_at") is None
    assert stored["gross_laytime_hours"] == 0
    assert read_contract(movement["contract_id"])["movement_status"] == "IN_TRANSIT"


def test_cancelling_a_contract_voids_billing_and_drops_planned_cuts(api):
    """PRD §3.3: "Cancellation moves the billing axis from `NOT_BILLED` to
    `VOID`, drives every assignment of the contract that still stands in
    `PLANNED` to `DROPPED` — which releases that tonnage back out of its tow's
    rollup exactly as an ordinary drop would — and increments the contract's
    `version`."

    Design: Corner/state_machines/contract_cancel_voids_billing_and_drops_planned_assignments
    """
    movement = setup_grain_movement(loads=(1700,), stage="BUILDING")

    cancelled = validate_success(api.cancel_freight_contract(
        movement["contract_id"], {"reason": "Shipper withdrew the nomination."},
        BILLER))
    assert cancelled["movement_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "VOID"

    assert read_assignment(movement["assignments"][0]["id"])["status"] == "DROPPED"
    tow = read_tow(movement["tow_id"])
    assert tow["barge_count"] == 0
    assert tow["total_loaded_tons"] == 0
    assert float(tow["max_draft_feet"]) == 0
    assert read_barge(movement["barges"][0]["id"])["operational_status"] == "IDLE"


def test_list_barge_assignments_by_tow_contract_and_state_axis(api):
    """PRD §3.5: "Assignments may be listed narrowed by `tow_id`, by `barge_id`,
    by `freight_contract_id`, by `status` or by `discharge_status`, and that
    listing is the only channel through which cascade-created assignment state
    becomes discoverable."
    PRD §2.3: "Every filter parameter named in the endpoint table narrows the
    result set by exact match, and multiple filters combine conjunctively."

    Design: Corner/endpoints/list_barge_assignments_filtered_by_tow_and_by_discharge_status
    """
    movement = setup_grain_movement(
        loads=(1700, 1650), contracted_tons=3400, stage="BUILDING")
    expected = {a["id"] for a in movement["assignments"]}

    rows, meta = validate_paginated(api.list_barge_assignments(
        DISPATCH, params={"tow_id": movement["tow_id"]}))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == expected

    _rows, meta = validate_paginated(api.list_barge_assignments(
        DISPATCH, params={"tow_id": movement["tow_id"],
                          "discharge_status": "NOT_ARRIVED"}))
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(api.list_barge_assignments(
        DISPATCH, params={"tow_id": movement["tow_id"], "status": "DROPPED"}))
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert rows == []

    _rows, meta = validate_paginated(api.list_barge_assignments(
        BILLER, params={"freight_contract_id": movement["contract_id"]}))
    assert meta["total_count"] == 2
