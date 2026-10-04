"""Telemetry, excursion accumulator, and the repair cascade (PRD §2.10, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_lot_conservation,
    assert_temperature_reading,
    create_delivered_inventory,
    create_dispatch_payload,
    create_reading_payload,
    create_released_lot,
    create_resolve_payload,
    evaluate_performance,
    get_chiller,
    get_placement,
    get_product_lot,
    list_service_tickets,
    make_store_operator_headers,
    post_reading,
    set_clock,
    setup_activated_placement,
    setup_active_placement,
    setup_suspended_placement,
    trigger_severe_excursion,
    validate_success,
)


def test_temperature_upper_bound_inclusive_activates(api, platform_admin_headers):
    """PRD §2.10: "The safe cabinet band is 0.0 to 4.0 degrees Celsius,
    inclusive at both ends. A posted temperature reading is an excursion when
    its `temp_c` is below 0.0 or above 4.0; exactly 0.0 and exactly 4.0 are in
    range."
    PRD §3.5: "The first in-range reading posted to an `INSTALLED` chiller
    activates it: `INSTALLED` becomes `ACTIVE`, and the chiller's `version`
    increments."

    Design: Difficulty/boundary_precision_check/temperature_upper_bound_inclusive
    """
    ctx = setup_active_placement()
    cid = ctx["chiller"]["id"]
    set_clock("2026-09-02T09:00:00Z")
    resp = api.post_temperature_reading(
        cid, create_reading_payload(recorded_at="2026-09-02T08:30:00Z", temp_c=4.0, duration_minutes=130),
        platform_admin_headers,
    )
    reading = validate_success(resp, expected_status=201)
    assert reading["is_excursion"] is False, "4.0 C is the inclusive upper bound of the safe band"

    chiller = get_chiller(cid)
    assert chiller["status"] == "ACTIVE", "first in-range reading activates the chiller"
    assert chiller["excursion_minutes_24h"] == 0
    tickets = list_service_tickets(cid)
    assert tickets == [], "no ticket minted by an in-range reading"


def test_temperature_just_over_bound_trips_cascade(api, platform_admin_headers):
    """PRD §2.10: "When a newly posted reading pushes the recomputed
    accumulator to 120 minutes or more, the chiller is deemed severely
    excursioned and the breach cascade of §3.5 fires: the placement is
    suspended, its store's sellable inventory is quarantined, and a service
    ticket is minted automatically."

    Design: Difficulty/boundary_precision_check/temperature_upper_bound_inclusive
    """
    ctx = setup_active_placement()
    cid = ctx["chiller"]["id"]
    set_clock("2026-09-02T09:00:00Z")
    post_reading(cid, "2026-09-02T08:30:00Z", 4.0, 130)  # in-range: activates
    resp = api.post_temperature_reading(
        cid, create_reading_payload(recorded_at="2026-09-02T08:45:00Z", temp_c=4.1, duration_minutes=130),
        platform_admin_headers,
    )
    reading = validate_success(resp, expected_status=201)
    assert reading["is_excursion"] is True, "4.1 C is above the inclusive band"

    chiller = get_chiller(cid)
    assert chiller["status"] == "NEEDS_REPAIR", "130 >= 120 severe threshold (boundary inclusive)"
    tickets = list_service_tickets(cid)
    assert len(tickets) == 1 and tickets[0]["origin"] == "AUTO_EXCURSION"


def test_chiller_repair_cycle_completes_once(api, field_technician_headers, service_dispatcher_headers):
    """PRD §2.10: "A completed repair stamps `last_repair_at` with the logical
    now, which recomputes the accumulator to 0 because the window excludes
    readings at or before that instant."
    PRD §3.5: "When the resolved ticket's chiller is `NEEDS_REPAIR`, the
    resolution doubles as the repair: the chiller returns to `ACTIVE`,
    `last_repair_at` is stamped with the logical now (which recomputes
    `excursion_minutes_24h` to 0, since the window excludes readings at or
    before `last_repair_at`), and the placement's `operational_status` lifts
    from `SUSPENDED` back to `OK` with its `version` incrementing."

    Design: Difficulty/non_linear_state_machine/chiller_cyclic_repair_loop
    """
    ctx = setup_activated_placement()
    cid = ctx["chiller"]["id"]
    set_clock("2026-09-02T11:05:00Z")
    post_reading(cid, "2026-09-02T10:00:00Z", 5.0, 70)
    post_reading(cid, "2026-09-02T11:00:00Z", 6.0, 60)

    chiller = get_chiller(cid)
    assert chiller["status"] == "NEEDS_REPAIR", "70 + 60 = 130 >= 120"
    assert chiller["excursion_minutes_24h"] == 130
    tickets = list_service_tickets(cid)
    assert len(tickets) == 1
    assert tickets[0]["origin"] == "AUTO_EXCURSION" and tickets[0]["status"] == "OPEN"

    resp = api.dispatch_service_ticket(
        tickets[0]["id"],
        create_dispatch_payload(window_start="2026-09-02T12:00:00Z", window_end="2026-09-02T13:00:00Z"),
        service_dispatcher_headers,
    )
    validate_success(resp, expected_status=200)
    resp = api.resolve_service_ticket(tickets[0]["id"], create_resolve_payload(
        resolution_note="replaced compressor relay"), field_technician_headers)
    validate_success(resp, expected_status=200)

    chiller = get_chiller(cid)
    assert chiller["status"] == "ACTIVE", "resolve on the ticket repairs the NEEDS_REPAIR chiller"
    assert chiller["excursion_minutes_24h"] == 0, "last_repair_at cutoff resets the accumulator"
    assert chiller["last_repair_at"] is not None


def test_chiller_repair_cycle_repeats(api, field_technician_headers):
    """PRD §3.5: "Conversely, when a posted reading pushes the recomputed
    `excursion_minutes_24h` to 120 minutes or more — the severe threshold,
    boundary inclusive — a chiller in `INSTALLED` or `ACTIVE` degrades to
    `NEEDS_REPAIR` and a three-hop cascade fires: ... and a service ticket is
    minted against the chiller with `origin` `AUTO_EXCURSION`, `status` `OPEN`,
    and the `issue_summary` text \"AUTO: severe temperature excursion\"."

    Design: Difficulty/non_linear_state_machine/chiller_cyclic_repair_loop
    """
    ctx = setup_suspended_placement()  # first cycle already completed: NEEDS_REPAIR
    cid = ctx["chiller"]["id"]
    resp = api.resolve_service_ticket(ctx["auto_ticket"]["id"],
                                      create_resolve_payload(resolution_note="cleared condenser"),
                                      field_technician_headers)
    validate_success(resp, expected_status=200)
    assert get_chiller(cid)["status"] == "ACTIVE"

    # Round 2: a fresh 130-minute excursion recorded after last_repair_at.
    set_clock("2026-09-03T09:00:00Z")
    post_reading(cid, "2026-09-03T08:00:00Z", 5.5, 130)
    chiller = get_chiller(cid)
    assert chiller["status"] == "NEEDS_REPAIR", "cycle completed twice (ACTIVE -> NEEDS_REPAIR again)"

    tickets = list_service_tickets(cid)
    autos = [t for t in tickets if t["origin"] == "AUTO_EXCURSION"]
    assert len(autos) == 2, "a second AUTO_EXCURSION ticket is minted for the second breach"
    assert autos[1]["issue_summary"] == "AUTO: severe temperature excursion"


def test_excursion_cascade_depth3_hops(api, placement_manager_headers):
    """PRD §3.5: "when a posted reading pushes the recomputed
    `excursion_minutes_24h` to 120 minutes or more — the severe threshold,
    boundary inclusive — a chiller in `INSTALLED` or `ACTIVE` degrades to
    `NEEDS_REPAIR` and a three-hop cascade fires: the placement using this
    chiller, if `ACTIVE`, has its `operational_status` driven to `SUSPENDED`
    (placement `version` increments); every `SELLABLE` inventory position at
    that placement's store becomes `QUARANTINED` (each position's `version`
    increments); and a service ticket is minted against the chiller with
    `origin` `AUTO_EXCURSION`, `status` `OPEN`, and the `issue_summary` text
    \"AUTO: severe temperature excursion\"."

    Design: Difficulty/transitive_cascade/excursion_cascade_depth3
    """
    ctx = setup_activated_placement()
    lot = create_released_lot(quantity_units=500)
    create_delivered_inventory(ctx, lot, 120)  # SELLABLE position of 120 at the store

    chiller = trigger_severe_excursion(ctx, duration_minutes=120)  # exactly the inclusive threshold
    assert chiller["status"] == "NEEDS_REPAIR", "hop 1: exactly 120 excursion minutes degrades the chiller"

    placement = get_placement(ctx["placement"]["id"])
    assert placement["operational_status"] == "SUSPENDED", "hop 2, caused by hop 1"

    positions = validate_success(
        api.list_inventory_positions(placement_manager_headers, params={"store_id": ctx["store"]["id"]})
    )
    assert positions[0]["status"] == "QUARANTINED", "hop 3, caused by hop 2"


def test_excursion_cascade_mints_ticket_and_preserves_buckets(api, placement_manager_headers,
                                                              service_dispatcher_headers):
    """PRD §2.11: "Shipment creation moves units from `unshipped_qty` to
    `in_transit_qty`; dock delivery moves the shipped units out of
    `in_transit_qty` into `in_store_qty` (accepted units) and `spoiled_qty`
    (rejected units); spoiling a shipment in transit moves all of its units
    from `in_transit_qty` to `spoiled_qty`; and a date-check sweep removal
    moves units from `in_store_qty` to `removed_qty`."
    PRD §3.5: "and a service ticket is minted against the chiller with `origin`
    `AUTO_EXCURSION`, `status` `OPEN`, and the `issue_summary` text \"AUTO:
    severe temperature excursion\"."

    Design: Difficulty/transitive_cascade/excursion_cascade_depth3
    """
    ctx = setup_activated_placement()
    lot = create_released_lot(quantity_units=500)
    create_delivered_inventory(ctx, lot, 120)

    trigger_severe_excursion(ctx, duration_minutes=120)

    tickets = list_service_tickets(ctx["chiller"]["id"])
    assert len(tickets) == 1, "sibling hop of hop 1: exactly one ticket minted"
    assert tickets[0]["origin"] == "AUTO_EXCURSION"
    assert tickets[0]["status"] == "OPEN"
    assert tickets[0]["issue_summary"] == "AUTO: severe temperature excursion"

    lot_after = get_product_lot(lot["id"])
    assert lot_after["in_store_qty"] == 120, "quarantine does not move buckets; only the sweep does"
    assert lot_after["unshipped_qty"] == 380
    assert_lot_conservation(lot_after)


def test_parallel_dimensions_excursion_preserves_performance(api, placement_manager_headers):
    """PRD §3.4: "Three parallel state dimensions govern the placement from
    then on — lifecycle `status`, velocity-driven `performance_status`, and
    chiller-health-driven `operational_status`; the performance and operational
    dimensions evolve independently and never gate each other, and only the
    lifecycle `status` gates them."

    Design: Difficulty/non_linear_state_machine/placement_parallel_dimensions_independent
    """
    ctx = setup_activated_placement()
    pid = ctx["placement"]["id"]
    under = evaluate_performance(pid, 30)
    assert under["performance_status"] == "UNDERPERFORMING"
    assert under["underperforming_streak"] == 1
    assert under["operational_status"] == "OK"

    trigger_severe_excursion(ctx, clock_to="2026-09-02T10:00:00Z",
                             recorded_at="2026-09-02T09:30:00Z", temp_c=6.0, duration_minutes=120)
    placement = get_placement(pid)
    assert placement["operational_status"] == "SUSPENDED", "chiller-health axis moved"
    assert placement["performance_status"] == "UNDERPERFORMING", "velocity axis untouched by the excursion"
    assert placement["underperforming_streak"] == 1


def test_parallel_dimensions_repair_and_evaluation_independent(api, placement_manager_headers,
                                                               field_technician_headers):
    """PRD §3.4: "the performance and operational dimensions evolve
    independently and never gate each other, and only the lifecycle `status`
    gates them."
    PRD §3.5: "the placement's `operational_status` lifts from `SUSPENDED` back
    to `OK` with its `version` incrementing."

    Design: Difficulty/non_linear_state_machine/placement_parallel_dimensions_independent
    """
    ctx = setup_suspended_placement()
    pid = ctx["placement"]["id"]
    evaluate_performance(pid, 30)  # UNDERPERFORMING while SUSPENDED: axes do not gate each other

    resp = api.resolve_service_ticket(ctx["auto_ticket"]["id"],
                                      create_resolve_payload(resolution_note="fixed thermostat"),
                                      field_technician_headers)
    validate_success(resp, expected_status=200)
    placement = get_placement(pid)
    assert placement["operational_status"] == "OK", "repair lifts the suspension"
    assert placement["performance_status"] == "UNDERPERFORMING", "repair does not touch the velocity axis"

    performing = evaluate_performance(pid, 50)
    assert performing["performance_status"] == "PERFORMING", "50 >= 40 velocity floor"
    assert performing["underperforming_streak"] == 0
    assert performing["operational_status"] == "OK"


def test_excursion_accumulator_late_reading_backfill(api, platform_admin_headers):
    """PRD §2.10: "Late-arriving readings — readings posted after readings with
    a later `recorded_at` — are accepted and count by their `recorded_at`,
    regardless of posting order."
    PRD §2.10: "Each chiller maintains `excursion_minutes_24h`, a rolling
    accumulator computed from its own readings only: the sum of
    `duration_minutes` over excursion readings whose `recorded_at` falls within
    the inclusive window from 24 hours before the current logical time up to
    the current logical time..."

    Design: Corner/calculations/excursion_accumulator_late_reading_backfill
    """
    ctx = setup_activated_placement(clock_to="2026-09-02T12:00:00Z",
                                    reading_recorded_at="2026-09-02T08:00:00Z")
    cid = ctx["chiller"]["id"]

    post_reading(cid, "2026-09-02T11:00:00Z", 5.0, 60)
    chiller = get_chiller(cid)
    assert chiller["status"] == "ACTIVE", "60 < 120: below the severe threshold"
    assert chiller["excursion_minutes_24h"] == 60

    # Late-arriving: recorded_at 10:00 predates the already-posted 11:00 reading.
    post_reading(cid, "2026-09-02T10:00:00Z", 5.5, 70)
    chiller = get_chiller(cid)
    assert chiller["excursion_minutes_24h"] == 130, "recorded_at, not arrival order, drives the accumulator"
    assert chiller["status"] == "NEEDS_REPAIR", "backfill tips the accumulator over 120"


def test_temperature_reading_immutable_shape_no_version(api, platform_admin_headers):
    """PRD §2.5: "`TemperatureReading` is the one exception: it is an
    append-only telemetry record and carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from temperature readings."
    PRD §2.10: "A posted temperature reading is an excursion when its `temp_c`
    is below 0.0 or above 4.0; exactly 0.0 and exactly 4.0 are in range."

    Design: Corner/entities/temperature_reading_immutable_shape_no_version
    """
    ctx = setup_active_placement()
    set_clock("2026-09-02T09:00:00Z")  # clock must reach past recorded_at (future readings are rejected)
    resp = api.post_temperature_reading(
        ctx["chiller"]["id"],
        create_reading_payload(recorded_at="2026-09-01T00:30:00Z", temp_c=2.5, duration_minutes=10),
        platform_admin_headers,
    )
    reading = validate_success(resp, expected_status=201)
    assert_temperature_reading(reading)  # asserts absence of version/updated_at
    assert reading["is_excursion"] is False, "2.5 C sits inside the inclusive band"
    for field in ("id", "created_at", "chiller_id", "recorded_at", "temp_c", "duration_minutes", "is_excursion"):
        assert field in reading, f"reading must carry {field}"


def test_store_operator_posts_reading_for_own_store_chiller(api):
    """PRD §3.5: "Either a `PlatformAdmin` or the `StoreOperator` of the store
    hosting the chiller's `ACTIVE` placement may post; a `StoreOperator` whose
    `X-User-ID` names any other store is rejected with 403
    `ERR_STORE_OWNERSHIP_MISMATCH`."
    PRD §2.1: "When `X-User-Role` is `StoreOperator`, `X-User-ID` is the `id`
    of the acting `Store`; ownership checks on any resource that references a
    `Store` compare the resource's store foreign key to `X-User-ID`, and a
    mismatch is rejected with 403 `ERR_STORE_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/store_operator_posts_reading_for_own_store_chiller
    """
    ctx = setup_active_placement()
    set_clock("2026-09-02T09:00:00Z")
    resp = api.post_temperature_reading(
        ctx["chiller"]["id"],
        create_reading_payload(recorded_at="2026-09-01T01:00:00Z", temp_c=3.1, duration_minutes=10),
        make_store_operator_headers(ctx["store"]["id"]),
    )
    reading = validate_success(resp, expected_status=201)
    assert reading["is_excursion"] is False
    assert get_chiller(ctx["chiller"]["id"])["status"] == "ACTIVE", (
        "first in-range reading activates the chiller"
    )
