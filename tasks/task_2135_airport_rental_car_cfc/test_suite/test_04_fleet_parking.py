"""Fleet parking allocation over closed intervals and the shared overflow lot."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_fleet_allocation,
    assert_overflow_stall_identity,
    assert_zone_stall_identity,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_touching_day_collides_on_the_closed_interval(api):
    """PRD §3.4: "Every allocation on the same `zone_id` that is still in `ALLOCATED` status
    and whose interval overlaps the requested one is gathered, where overlap on these closed
    intervals holds when the new start date is no later than the existing end date and the
    existing start date is no later than the new end date — so intervals that merely touch on
    one calendar day do collide."
    PRD §3.4: "When it is positive, the spill is only permitted if `allow_overflow` was
    supplied as true; otherwise the request is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/fleet_zone_closed_interval_touching_day_collides_and_aggregates_capacity
    """
    scenario = fx.setup_active_agreement(api)
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=100)
    operator = scenario["operator"]
    fx.create_fleet_allocation(
        api, scenario["agreement"]["id"], zone["id"], operator,
        start_date="2026-03-01", end_date="2026-03-10", stalls_requested=60,
    )

    version = fx.read_zone_version(api, zone["id"], operator)
    response = api.create_fleet_allocation(
        f.fleet_allocation_payload(
            scenario["agreement"]["id"], zone["id"], version,
            start_date="2026-03-10", end_date="2026-03-20", stalls_requested=50,
            allow_overflow=False,
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED.value, 409)
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 60, (
        "the refused request must leave only the incumbent 60 stalls in use"
    )


def test_disjoint_fleet_interval_is_granted_in_full(api):
    """PRD §3.4: "The `zone_stalls_granted` of every gathered row is summed to give the stalls
    already in use, the zone's free stalls are its `stall_capacity` minus that sum but never
    below zero, and `zone_stalls_granted` for the new allocation is the smaller of
    `stalls_requested` and those free stalls."
    PRD §3.4: "`inclusive_days` is the difference between `end_date` and `start_date` in days,
    plus one, because the interval is closed — a one-day allocation has `inclusive_days` of 1.
    `overflow_surcharge_cents` is `overflow_stalls_granted` multiplied by the facility's
    `overflow_daily_surcharge_cents` and then by `inclusive_days`, which is 0 for any
    allocation that stayed entirely inside its zone."
    PRD §3.1: "from then on `stalls_allocated` is the total of `zone_stalls_granted` over the
    zone's allocations still in `ALLOCATED` status, and `stalls_available` is always
    `stall_capacity` minus `stalls_allocated`."

    Design: Difficulty/resource_temporal_overlap/fleet_zone_closed_interval_touching_day_collides_and_aggregates_capacity
    """
    scenario = fx.setup_active_agreement(api)
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=100)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    fx.create_fleet_allocation(
        api, agreement_id, zone["id"], operator,
        start_date="2026-03-01", end_date="2026-03-10", stalls_requested=60,
    )

    version = fx.read_zone_version(api, zone["id"], operator)
    granted = validate_success(
        api.create_fleet_allocation(
            f.fleet_allocation_payload(
                agreement_id, zone["id"], version,
                start_date="2026-03-11", end_date="2026-03-20", stalls_requested=40,
                allow_overflow=False,
            ),
            operator,
        ),
        201,
    )

    assert_fleet_allocation(granted)
    assert granted["zone_stalls_granted"] == 40, "a disjoint window sees the whole zone free"
    assert granted["overflow_stalls_granted"] == 0
    assert granted["overflow_surcharge_cents"] == 0
    assert granted["inclusive_days"] == 10, (
        "2026-03-11 through 2026-03-20 inclusive spans 10 days"
    )
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 100
    assert stored_zone["stalls_available"] == 0
    assert_zone_stall_identity(stored_zone)
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["fleet_stalls_allocated"] == 100
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["overflow_stalls_allocated"] == 0


def test_overflow_grant_splits_across_zone_and_lot(api):
    """PRD §3.4: "If spill is permitted, the facility's shared overflow lot is drawn down the
    same way but across every zone of the facility: all allocations of the facility still in
    `ALLOCATED` status whose intervals overlap the requested one under the same closed-interval
    test are gathered, their `overflow_stalls_granted` are summed, and the free overflow stalls
    are the facility's `overflow_lot_stalls` minus that sum but never below zero."
    PRD §3.4: "`overflow_surcharge_cents` is `overflow_stalls_granted` multiplied by the
    facility's `overflow_daily_surcharge_cents` and then by `inclusive_days`, which is 0 for
    any allocation that stayed entirely inside its zone."
    PRD §3.4: "A granted allocation is created in `ALLOCATED` status; it raises the zone's
    `stalls_allocated` by `zone_stalls_granted` and recomputes the zone's `stalls_available`,
    raises the facility's `overflow_stalls_allocated` by `overflow_stalls_granted` and
    recomputes `overflow_stalls_available`, and raises the agreement's `fleet_stalls_allocated`
    by the sum of `zone_stalls_granted` and `overflow_stalls_granted`."

    Design: Difficulty/compensating_invariant/fleet_stall_conservation_across_overflow_grant_then_release
    """
    scenario = fx.setup_active_agreement(
        api,
        facility_overrides={"overflow_lot_stalls": 100, "overflow_daily_surcharge_cents": 400},
    )
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=200)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]

    allocation = fx.create_fleet_allocation(
        api, agreement_id, zone["id"], operator,
        start_date="2026-03-01", end_date="2026-03-10",
        stalls_requested=250, allow_overflow=True,
    )

    assert allocation["zone_stalls_granted"] == 200, "the 200-stall zone is drawn down first"
    assert allocation["overflow_stalls_granted"] == 50, "the unmet 50 spill into the lot"
    assert allocation["inclusive_days"] == 10
    assert allocation["overflow_surcharge_cents"] == 200_000, (
        "50 overflow stalls at 400 cents per stall per day over 10 days is 200,000 cents"
    )
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 200
    assert stored_zone["stalls_available"] == 0
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["overflow_stalls_allocated"] == 50
    assert facility["overflow_stalls_available"] == 50
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["fleet_stalls_allocated"] == 250


def test_releasing_an_overflow_grant_restores_both_stall_identities(api):
    """PRD §3.4: "Releasing a fleet allocation is the exact compensating action. From
    `ALLOCATED` the row moves to the terminal `RELEASED`, the zone's `stalls_allocated` falls
    by `zone_stalls_granted` with `stalls_available` recomputed, the facility's
    `overflow_stalls_allocated` falls by `overflow_stalls_granted` with
    `overflow_stalls_available` recomputed, and the agreement's `fleet_stalls_allocated` falls
    by the sum of the two grants."
    PRD §3.4: "Both conserved stall totals return to exactly their pre-grant values, and the
    allocation's `version`, the zone's `version` and the facility's `version` each advance by
    1."

    Design: Difficulty/compensating_invariant/fleet_stall_conservation_across_overflow_grant_then_release
    """
    scenario = fx.setup_active_agreement(
        api,
        facility_overrides={"overflow_lot_stalls": 100, "overflow_daily_surcharge_cents": 400},
    )
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=200)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    allocation = fx.create_fleet_allocation(
        api, agreement_id, zone["id"], operator,
        start_date="2026-03-01", end_date="2026-03-10",
        stalls_requested=250, allow_overflow=True,
    )

    released = validate_success(api.release_fleet_allocation(allocation["id"], operator))

    assert released["status"] == "RELEASED"
    assert released["zone_stalls_granted"] == 200, (
        "the grant split stays on the row for billing after release"
    )
    assert released["overflow_stalls_granted"] == 50
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 0
    assert stored_zone["stalls_available"] == 200
    assert_zone_stall_identity(stored_zone)
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["overflow_stalls_allocated"] == 0
    assert facility["overflow_stalls_available"] == 100
    assert_overflow_stall_identity(facility)
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["fleet_stalls_allocated"] == 0


def test_overflow_demand_beyond_the_lot_is_rejected(api):
    """PRD §3.4: "If the unmet demand exceeds those free overflow stalls, the request is
    rejected with `ERR_OVERFLOW_EXHAUSTED` (HTTP 409); otherwise `overflow_stalls_granted` is
    set to exactly the unmet demand."
    PRD §3.1: "Thereafter `overflow_stalls_available` is always the facility's
    `overflow_lot_stalls` minus its `overflow_stalls_allocated`, and `overflow_stalls_allocated`
    is always the total of `overflow_stalls_granted` across the facility's fleet allocations
    that are still in `ALLOCATED` status."

    Design: Corner/validations/overflow_demand_beyond_the_lot_is_rejected
    """
    scenario = fx.setup_active_agreement(
        api,
        facility_overrides={"overflow_lot_stalls": 10, "overflow_daily_surcharge_cents": 400},
    )
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=50)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    version = fx.read_zone_version(api, zone["id"], operator)

    response = api.create_fleet_allocation(
        f.fleet_allocation_payload(
            agreement_id, zone["id"], version,
            start_date="2026-03-01", end_date="2026-03-10",
            stalls_requested=100, allow_overflow=True,
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_OVERFLOW_EXHAUSTED.value, 409)
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 0, "the partial zone grant must not be persisted"
    assert stored_zone["stalls_available"] == 50
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["overflow_stalls_allocated"] == 0
    assert facility["overflow_stalls_available"] == 10
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["fleet_stalls_allocated"] == 0
    _rows, meta = validate_paginated(
        api.list_fleet_allocations(ADMIN, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 0


def test_stale_zone_version_blocks_fleet_allocation(api):
    """PRD §2.9: "A request creating a fleet allocation must carry `expected_zone_version`,
    holding the `version` of the `FleetParkingZone` named by `zone_id` as the client last
    observed it. A mismatch against the zone's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing a client from sizing a stall request against a
    zone occupancy reading that has since moved."

    Design: Corner/cross_cutting_complexity_layers/stale_zone_version_on_fleet_allocation_create_returns_conflict
    """
    scenario = fx.setup_active_agreement(api)
    zone = fx.create_fleet_zone(api, scenario["facility"]["id"], stall_capacity=200)
    agreement_id, operator = scenario["agreement"]["id"], scenario["operator"]
    stale_version = zone["version"]
    fx.create_fleet_allocation(
        api, agreement_id, zone["id"], operator,
        start_date="2026-03-01", end_date="2026-03-05", stalls_requested=20,
    )

    response = api.create_fleet_allocation(
        f.fleet_allocation_payload(
            agreement_id, zone["id"], stale_version,
            start_date="2026-06-01", end_date="2026-06-05",
            stalls_requested=20, allow_overflow=False,
        ),
        operator,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    stored_zone = validate_success(api.get_fleet_zone(zone["id"], ADMIN))
    assert stored_zone["stalls_allocated"] == 20, (
        "the stale create must be refused before the capacity arithmetic runs"
    )
    assert stored_zone["stalls_available"] == 180
    agreement = validate_success(api.get_agreement(agreement_id, ADMIN))
    assert agreement["fleet_stalls_allocated"] == 20
    _rows, meta = validate_paginated(
        api.list_fleet_allocations(ADMIN, params={"zone_id": zone["id"]})
    )
    assert meta["total_count"] == 1
