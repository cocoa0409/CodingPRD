"""Depopulation orders: targeting rules, downtime computation with the
regional surcharge, completion cascades, event clearance, and the conserved
hen-inventory invariant.
"""

from test_helpers import (
    ADMIN,
    HEALTH,
    PLANNER,
    api_client,
    assert_instant_equal,
    complete_depopulation_order,
    confirm_disease_event,
    create_and_place_flock,
    create_complex,
    create_depopulation_order,
    create_disease_event,
    create_house,
    create_planned_flock,
    read_complex,
    read_flock,
    read_house,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_depop_order_house_not_in_scope(api):
    """The order's house must be a member of the event's scope_house_ids.

    PRD §3.3: "the target house must be a member of the event's
    `scope_house_ids` (else `ERR_HOUSE_NOT_IN_SCOPE`)".

    Design: Corner/validations/depop_order_house_not_in_scope
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house1 = create_house(complex_["id"], house_code="H1", capacity_hens=50_000)
    house2 = create_house(complex_["id"], house_code="H2", capacity_hens=50_000)
    create_and_place_flock(
        house1["id"], flock_code="F1",
        placement_date="2026-04-28T00:00:00Z", placed_hen_count=10_000,
    )
    create_and_place_flock(
        house2["id"], flock_code="F2",
        placement_date="2026-04-28T00:00:00Z", placed_hen_count=10_000,
    )
    event = create_disease_event(complex_["id"], [house1["id"]])
    confirm_disease_event(event["id"])

    response = api.create_depopulation_order(
        event["id"],
        {"house_id": house2["id"], "disposal_method": "BURIAL"},
        HEALTH,
    )
    validate_error(response, ERR.ERR_HOUSE_NOT_IN_SCOPE)
    rows, meta = validate_paginated(
        api.list_depopulation_orders(event["id"], HEALTH)
    )
    assert rows == [] and meta["total_count"] == 0


def test_depop_order_requires_active_flock(api):
    """A house whose only flock was CANCELLED by the confirmation cascade has
    nothing to depopulate.

    PRD §3.3: "the house must currently hold at least one flock in
    `GROWING`, `LAYING`, or `MOLT` (else `ERR_NO_ACTIVE_FLOCK_IN_HOUSE`)".
    PRD §3.3: "Link two: every `PLANNED` flock of the complex is cancelled to
    `CANCELLED`".

    Design: Corner/validations/depop_order_requires_active_flock
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], placement_date="2026-12-01T00:00:00Z",
        placed_hen_count=40_000,
    )
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    assert read_flock(flock["id"])["status"] == "CANCELLED"

    response = api.create_depopulation_order(
        event["id"],
        {"house_id": house["id"], "disposal_method": "BURIAL"},
        HEALTH,
    )
    validate_error(response, ERR.ERR_NO_ACTIVE_FLOCK_IN_HOUSE)


def test_duplicate_depop_order_returns_409(api):
    """One ISSUED order per (event, house); the second create is a conflict.

    PRD §3.3: "no other `ISSUED` order may already exist for the same event
    and house (else `ERR_DEPOPULATION_ORDER_EXISTS`)".

    Design: Corner/validations/duplicate_depop_order_returns_409
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    create_depopulation_order(event["id"], house["id"], "BURIAL")

    response = api.create_depopulation_order(
        event["id"],
        {"house_id": house["id"], "disposal_method": "INCINERATION"},
        HEALTH,
    )
    validate_error(response, ERR.ERR_DEPOPULATION_ORDER_EXISTS)
    rows, meta = validate_paginated(
        api.list_depopulation_orders(event["id"], HEALTH)
    )
    assert meta["total_count"] == 1 and len(rows) == 1


def _setup_biosecure_unit(api):
    """NORTHEAST complex; LAYING-track flock of 10000 placed at age 0."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Biosecure Unit", region_code="NORTHEAST")
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_planned_flock(
        house["id"], placement_date="2026-09-01T00:00:00Z",
        placed_hen_count=10_000,
    )
    return complex_, house, flock


def test_place_then_depopulate_restores_house_hen_inventory(api):
    """The forward action (+10000) paired with its compensating depopulation
    (-10000) returns the house inventory to its pre-placement baseline.

    PRD §3.1: "The house's `hen_inventory` begins at zero and is always the
    sum of `current_hen_count` over the house's flocks in `GROWING`,
    `LAYING`, or `MOLT`".
    PRD §3.3: "Completing an order (legal only from `ISSUED`, else
    `ERR_INVALID_STATE`) stamps `completed_at`, increments the order's
    `version`, depopulates every flock of the target house in `GROWING`,
    `LAYING`, or `MOLT` to `DEPOPULATED` with `current_hen_count` zeroed,
    recomputes the house's `hen_inventory` downward, and sets the house's
    `downtime_until` to the clock plus the order's `downtime_days`".

    Design: Difficulty/compensating_invariant/place_then_depopulate_restores_house_hen_inventory
    """
    complex_, house, flock = _setup_biosecure_unit(api)
    assert read_house(house["id"])["hen_inventory"] == 0

    placed = validate_success(api.place_flock(flock["id"], PLANNER))
    assert placed["status"] == "GROWING"
    assert read_house(house["id"])["hen_inventory"] == 10_000

    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    order = create_depopulation_order(event["id"], house["id"], "BURIAL")
    complete_depopulation_order(order["id"])

    flock_after = read_flock(flock["id"])
    assert flock_after["status"] == "DEPOPULATED"
    assert flock_after["current_hen_count"] == 0
    # The forward/compensating pair conserved the invariant.
    assert read_house(house["id"])["hen_inventory"] == 0


def test_depopulation_downtime_stamped_from_disposal_method(api):
    """BURIAL contributes a base of 28 days with no regional surcharge when
    no region-mate carries a freshly CONFIRMED event.

    PRD §3.3: "Creation computes the order's `downtime_days`: the disposal
    method contributes a base of 42 days for composting, 28 for burial, 21
    for incineration, or 35 for landfill, and if another complex in the same
    region carries an event still in `CONFIRMED` status whose confirmation
    instant falls within the thirty days before this order's creation clock,
    a regional surcharge of 14 days is added."
    PRD §3.3: "sets the house's `downtime_until` to the clock plus the
    order's `downtime_days` — repopulation is blocked until that instant".

    Design: Difficulty/compensating_invariant/place_then_depopulate_restores_house_hen_inventory
    """
    complex_, house, flock = _setup_biosecure_unit(api)
    validate_success(api.place_flock(flock["id"], PLANNER))
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    order = create_depopulation_order(event["id"], house["id"], "BURIAL")
    assert order["downtime_days"] == 28
    complete_depopulation_order(order["id"])

    house_after = read_house(house["id"])
    assert_instant_equal(
        house_after["downtime_until"], "2026-09-29T00:00:00Z",
        "downtime_until",
    )


def test_depopulation_downtime_adds_regional_bonus(api):
    """A region-mate's CONFIRMED event 15 days inside the 30-day lookback
    adds 14 days: COMPOSTING 42 + 14 = 56.

    PRD §3.3: "Creation computes the order's `downtime_days`: the disposal
    method contributes a base of 42 days for composting, 28 for burial, 21
    for incineration, or 35 for landfill, and if another complex in the same
    region carries an event still in `CONFIRMED` status whose confirmation
    instant falls within the thirty days before this order's creation clock,
    a regional surcharge of 14 days is added."

    Design: Corner/calculations/depopulation_downtime_adds_regional_bonus
    """
    set_clock("2026-09-01T00:00:00Z")
    region_a = create_complex(name="Region A", region_code="SOUTHEAST")
    region_b = create_complex(name="Region B", region_code="SOUTHEAST")
    house_a = create_house(region_a["id"], house_code="HA", capacity_hens=50_000)
    house_b = create_house(region_b["id"], house_code="HB", capacity_hens=50_000)
    create_and_place_flock(
        house_a["id"], flock_code="FA",
        placement_date="2026-04-28T00:00:00Z", placed_hen_count=10_000,
    )
    create_and_place_flock(
        house_b["id"], flock_code="FB",
        placement_date="2026-04-28T00:00:00Z", placed_hen_count=10_000,
    )

    set_clock("2026-09-05T00:00:00Z")
    event_a = create_disease_event(
        region_a["id"], [house_a["id"]], detection_date="2026-09-05T00:00:00Z"
    )
    confirm_disease_event(event_a["id"])

    set_clock("2026-09-20T00:00:00Z")
    event_b = create_disease_event(
        region_b["id"], [house_b["id"]], detection_date="2026-09-20T00:00:00Z"
    )
    confirm_disease_event(event_b["id"])

    order_b = create_depopulation_order(
        event_b["id"], house_b["id"], "COMPOSTING"
    )
    # A's event was confirmed 2026-09-05 — 15 days before the creation clock.
    assert order_b["downtime_days"] == 56
    assert read_complex(region_a["id"])["biosecurity_posture"] == "QUARANTINE"
    assert read_complex(region_b["id"])["biosecurity_posture"] == "QUARANTINE"

    complete_depopulation_order(order_b["id"])
    assert_instant_equal(
        read_house(house_b["id"])["downtime_until"], "2026-11-15T00:00:00Z",
        "downtime_until",
    )


def test_disease_event_cleared_via_run_ops_after_downtime(api):
    """Once the order is COMPLETED and the scope house's downtime has fully
    elapsed, the next checkpoint clears the event and relaxes posture.

    PRD §3.3: "An event is cleared automatically at any complex's operations
    checkpoint once every one of its depopulation orders is `COMPLETED` and
    every scope house's downtime has elapsed; clearance stamps `cleared_at`
    and recomputes posture region-wide, returning the complex to `NORMAL` or
    `ELEVATED` as §2.7 dictates."

    Design: Corner/state_machines/disease_event_cleared_via_run_ops_after_downtime
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )

    set_clock("2026-09-10T00:00:00Z")
    event = create_disease_event(
        complex_["id"], [house["id"]], detection_date="2026-09-10T00:00:00Z"
    )
    confirm_disease_event(event["id"])
    order = create_depopulation_order(event["id"], house["id"], "INCINERATION")
    assert order["downtime_days"] == 21
    complete_depopulation_order(order["id"])
    assert_instant_equal(
        read_house(house["id"])["downtime_until"], "2026-10-01T00:00:00Z",
        "downtime_until",
    )
    assert read_complex(complex_["id"])["biosecurity_posture"] == "QUARANTINE"

    # At exactly downtime_until the downtime has elapsed; the checkpoint
    # clears the event and the region relaxes to NORMAL.
    set_clock("2026-10-01T00:00:00Z")
    run_ops(complex_["id"])

    cleared = validate_success(api.get_disease_event(event["id"], HEALTH))
    assert cleared["status"] == "CLEARED"
    assert_instant_equal(
        cleared["cleared_at"], "2026-10-01T00:00:00Z", "cleared_at"
    )
    assert read_complex(complex_["id"])["biosecurity_posture"] == "NORMAL"


def test_cascaded_mutation_bumps_house_version(api):
    """The depopulation completion's hen-inventory recompute is a mutation of
    the house: its version increments and updated_at refreshes.

    PRD §2.8: "Every resource touched by a cascade — not just the resource
    the request targeted — refreshes its `updated_at` and increments its
    `version`."
    PRD §3.3: "Completing an order ... recomputes the house's
    `hen_inventory` downward, and sets the house's `downtime_until` to the
    clock plus the order's `downtime_days`".

    Design: Corner/complexity_layers/cascaded_mutation_bumps_house_version
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    event = create_disease_event(complex_["id"], [house["id"]])
    confirm_disease_event(event["id"])
    order = create_depopulation_order(event["id"], house["id"], "LANDFILL")
    house_pre = read_house(house["id"])

    complete_depopulation_order(order["id"])

    house_post = read_house(house["id"])
    assert house_post["version"] == house_pre["version"] + 1
    assert house_post["hen_inventory"] == 0
    # LANDFILL base 35 days from the 2026-09-01 completion clock.
    assert_instant_equal(
        house_post["downtime_until"], "2026-10-06T00:00:00Z", "downtime_until"
    )
    assert_instant_equal(
        house_post["updated_at"], "2026-09-01T00:00:00Z", "updated_at"
    )
