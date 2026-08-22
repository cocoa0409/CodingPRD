"""Registering cooperage, booking occupancy windows and committing wine."""
import pytest

from test_helpers import (
    LOAD_19T_CABERNET_OAKVILLE,
    LOAD_5T_CHARDONNAY_NAPA,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_lot,
    assert_vessel,
    assert_vessel_allocation,
    clean_vessel,
    commit_allocation,
    create_vessel_payload,
    house_lot,
    new_accepted_intake,
    new_lot,
    new_vessel,
    read_vessel_version,
    release_allocation,
    reserve_allocation,
    set_clock,
    setup_active_contract,
    setup_contract_with_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_vessel_rejects_a_type_outside_the_declared_enum(api, facility_admin_headers):
    """PRD 2.5: "The body must carry every required field for the endpoint; each
    field must have its declared type; every enum-valued field must carry a
    declared member; every numeric constraint must hold, including the "greater
    than zero", "at least zero", bounded-range and decimal-place constraints
    stated per field in §3; and the pagination `limit` must lie between 1 and
    100 with `offset` at least 0."
    PRD 3.2: "A `FacilityAdmin` records each one with a `vessel_code` asset tag
    — unique facility-wide, with a repeat refused as `ERR_DUPLICATE_VESSEL_CODE`
    — a `vessel_type` of either `TANK` or `BARREL`, a working `capacity_gallons`
    greater than zero, and a `facility_zone` of `ZONE_A`, `ZONE_B` or
    `BARREL_HALL`."

    Design: Corner/entities/corner_vessel_rejects_undeclared_enum_value_invalid_enum
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.create_vessel(
        create_vessel_payload(
            vessel_code="AMP-01", vessel_type="AMPHORA", capacity_gallons=250
        ),
        facility_admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(api.list_vessels(facility_admin_headers))
    assert rows == [], "a rejected registration must store nothing"
    assert meta["total_count"] == 0


def test_release_dirties_the_vessel_and_cleaning_returns_it_to_clean(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "It goes `CLEAN` to `DIRTY` automatically, never by direct
    request, whenever an allocation on that vessel moves from `COMMITTED` to
    `RELEASED`; that same event stamps `last_released_at` with the releasing
    allocation's `end_at`."
    PRD 3.2: "**Releasing** a `COMMITTED` allocation — a `CellarSupervisor`'s
    action — sets it to `RELEASED`, stamps `released_at` from the logical clock,
    and computes `occupied_days` as the whole days between `committed_at` and
    `released_at`."

    Design: Corner/state_machines/corner_vessel_condition_cleaning_loop_clean_dirty_clean
    """
    scenario = setup_contract_with_lot()
    vessel = new_vessel()
    allocation = house_lot(
        scenario["contract"]["id"], vessel["id"], scenario["lot"]["id"], 4000
    )

    released = validate_success(
        api.vessel_allocation_transition(
            allocation["id"], {"action": "RELEASE"}, cellar_supervisor_headers
        )
    )
    assert_vessel_allocation(released)
    assert released["status"] == "RELEASED"
    assert released["released_at"] == "2026-09-01T00:00:00.000Z"
    assert released["occupied_days"] == 0

    dirty = validate_success(api.get_vessel(vessel["id"], cellar_supervisor_headers))
    assert_vessel(dirty)
    assert dirty["condition"] == "DIRTY"
    assert dirty["last_released_at"] == "2026-11-01T00:00:00.000Z", (
        "last_released_at must take the releasing allocation's end_at"
    )

    lot = validate_success(api.get_lot(scenario["lot"]["id"], cellar_supervisor_headers))
    assert lot["current_vessel_id"] is None, "releasing unhouses the lot"

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01)

    cleaned = validate_success(
        api.vessel_condition(vessel["id"], {"action": "CLEAN"}, cellar_supervisor_headers)
    )
    assert cleaned["condition"] == "CLEAN"
    assert cleaned["last_released_at"] == "2026-11-01T00:00:00.000Z", (
        "cleaning does not move the last_released_at watermark"
    )


def test_cancel_frees_the_counters_but_leaves_the_vessel_clean(
    api, facility_admin_headers
):
    """PRD 3.2: "**Cancelling** a `RESERVED` allocation — a `FacilityAdmin`'s
    action — sets it to `CANCELLED`, leaves `released_at` null, and leaves the
    vessel entirely untouched: its `condition` does not become `DIRTY` and its
    `last_released_at` does not move, because no wine was ever in it."
    PRD 2.8: "a contract's `gallons_allocated` and `barrel_slots_used` are
    always recomputed from that contract's surviving allocations in status
    `RESERVED` or `COMMITTED`"

    Design: Corner/state_machines/corner_allocation_cancel_leaves_vessel_clean_branch_divergence
    """
    scenario = setup_active_contract()
    vessel = new_vessel()
    allocation = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=2500
    )

    cancelled = validate_success(
        api.vessel_allocation_transition(
            allocation["id"], {"action": "CANCEL"}, facility_admin_headers
        )
    )
    assert_vessel_allocation(cancelled)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["released_at"] is None
    assert cancelled["lot_id"] is None
    assert cancelled["occupied_days"] == 0

    stored_vessel = validate_success(api.get_vessel(vessel["id"], facility_admin_headers))
    assert stored_vessel["condition"] == "CLEAN"
    assert stored_vessel["last_released_at"] is None

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01)
    assert contract["barrel_slots_used"] == 0


def test_commit_writes_the_housing_link_in_both_directions(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "On success the allocation moves `RESERVED` to `COMMITTED`,
    takes the supplied `lot_id`, stamps `committed_at` from the logical clock,
    and writes the allocation's `vessel_id` onto the lot as its
    `current_vessel_id`, incrementing the lot's `version`."

    Design: Corner/endpoints/corner_vessel_allocation_commit_links_lot_and_vessel
    """
    scenario = setup_contract_with_lot(
        load=LOAD_5T_CHARDONNAY_NAPA, lot_code="CH-NAP-26-01"
    )
    vessel = new_vessel()
    allocation = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=1000
    )

    committed = validate_success(
        api.commit_vessel_allocation(
            allocation["id"], {"lot_id": scenario["lot"]["id"]}, cellar_supervisor_headers
        )
    )
    assert_vessel_allocation(committed)
    assert committed["status"] == "COMMITTED"
    assert committed["lot_id"] == scenario["lot"]["id"]
    assert committed["committed_at"] == "2026-09-01T00:00:00.000Z"

    lot = validate_success(api.get_lot(scenario["lot"]["id"], cellar_supervisor_headers))
    assert lot["current_vessel_id"] == vessel["id"]

    rows, _ = validate_paginated(
        api.list_vessel_allocations(
            facility_admin_headers, params={"lot_id": scenario["lot"]["id"]}
        )
    )
    assert [row["id"] for row in rows] == [allocation["id"]]

    lots, _ = validate_paginated(
        api.list_lots(facility_admin_headers, params={"current_vessel_id": vessel["id"]})
    )
    assert [row["id"] for row in lots] == [scenario["lot"]["id"]]

    stored_vessel = validate_success(api.get_vessel(vessel["id"], facility_admin_headers))
    assert stored_vessel["condition"] == "CLEAN", "committing does not dirty a vessel"


def test_commit_into_a_dirty_vessel_is_refused_until_it_is_cleaned(
    api, cellar_supervisor_headers
):
    """PRD 3.2: "The allocation must be in `RESERVED`, the governing contract
    must be `ACTIVE`, and the vessel's `condition` must be `CLEAN` — a `DIRTY`
    or `OUT_OF_SERVICE` vessel is refused with `ERR_VESSEL_NOT_CLEAN`."

    Design: Corner/errors/corner_commit_into_dirty_vessel_rejected
    """
    scenario = setup_contract_with_lot(
        load=LOAD_5T_CHARDONNAY_NAPA, delivery_ticket="DT-V1", lot_code="CH-NAP-26-01"
    )
    contract_id = scenario["contract"]["id"]
    second_intake = new_accepted_intake(
        contract_id,
        "DT-V2",
        load=LOAD_5T_CHARDONNAY_NAPA,
        block_code="C02",
    )
    second_lot = new_lot(contract_id, [second_intake["id"]], lot_code="CH-NAP-26-02")

    vessel = new_vessel()
    first_allocation = house_lot(
        contract_id, vessel["id"], scenario["lot"]["id"], allocated_gallons=1000
    )
    release_allocation(first_allocation["id"])

    dirty = validate_success(api.get_vessel(vessel["id"], cellar_supervisor_headers))
    assert dirty["condition"] == "DIRTY"

    second_allocation = reserve_allocation(
        contract_id,
        vessel["id"],
        allocated_gallons=1000,
        start_at="2026-11-05T00:00:00Z",
        end_at="2026-12-01T00:00:00Z",
    )

    response = api.commit_vessel_allocation(
        second_allocation["id"], {"lot_id": second_lot["id"]}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_NOT_CLEAN.value, 409)

    unchanged = validate_success(
        api.get_vessel_allocation(second_allocation["id"], cellar_supervisor_headers)
    )
    assert unchanged["status"] == "RESERVED"
    assert unchanged["lot_id"] is None

    clean_vessel(vessel["id"])
    committed = validate_success(
        api.commit_vessel_allocation(
            second_allocation["id"], {"lot_id": second_lot["id"]}, cellar_supervisor_headers
        )
    )
    assert committed["status"] == "COMMITTED"
    housed = validate_success(api.get_lot(second_lot["id"], cellar_supervisor_headers))
    assert housed["current_vessel_id"] == vessel["id"]


def test_commit_of_a_lot_larger_than_the_allocation_exceeds_vessel_capacity(
    api, cellar_supervisor_headers
):
    """PRD 3.2: "Finally the lot's `volume_gallons` may not exceed the
    allocation's `allocated_gallons`, which is the second reading of
    `ERR_VESSEL_CAPACITY_EXCEEDED`."

    Design: Corner/errors/corner_commit_lot_larger_than_allocation_rejected
    """
    scenario = setup_contract_with_lot()
    vessel = new_vessel()
    allocation = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=1000
    )

    response = api.commit_vessel_allocation(
        allocation["id"], {"lot_id": scenario["lot"]["id"]}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_CAPACITY_EXCEEDED.value, 422)

    stored = validate_success(
        api.get_vessel_allocation(allocation["id"], cellar_supervisor_headers)
    )
    assert stored["status"] == "RESERVED"
    assert stored["lot_id"] is None
    assert stored["committed_at"] is None

    lot = validate_success(api.get_lot(scenario["lot"]["id"], cellar_supervisor_headers))
    assert lot["current_vessel_id"] is None
    assert lot["production_status"] == "JUICE"


def test_tank_entitlement_ceiling_is_aggregate_across_allocations(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "Three ceilings then apply: `allocated_gallons` may not exceed
    the vessel's `capacity_gallons` (`ERR_VESSEL_CAPACITY_EXCEEDED`); for a
    `TANK` vessel, the contract's current `gallons_allocated` plus the newly
    requested `allocated_gallons` may not exceed `tank_gallons_entitled`
    (`ERR_TANK_ENTITLEMENT_EXCEEDED`); and for a `BARREL` vessel, the contract's
    current `barrel_slots_used` plus one may not exceed `barrel_slots_entitled`
    (`ERR_BARREL_SLOTS_EXHAUSTED`)."

    Design: Corner/validations/corner_tank_entitlement_exceeded_on_second_allocation
    """
    scenario = setup_active_contract(tank_gallons_entitled=5000)
    contract_id = scenario["contract"]["id"]
    tank_one = new_vessel(vessel_code="T-101")
    tank_two = new_vessel(vessel_code="T-102")
    reserve_allocation(contract_id, tank_one["id"], allocated_gallons=4000)

    response = api.create_vessel_allocation(
        {
            "contract_id": contract_id,
            "vessel_id": tank_two["id"],
            "start_at": "2026-09-01T00:00:00Z",
            "end_at": "2026-11-01T00:00:00Z",
            "allocated_gallons": 2000,
            "expected_vessel_version": read_vessel_version(tank_two["id"]),
        },
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_TANK_ENTITLEMENT_EXCEEDED.value, 422)

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["gallons_allocated"] == pytest.approx(4000.00, abs=0.01)

    untouched = validate_success(api.get_vessel(tank_two["id"], facility_admin_headers))
    assert untouched["version"] == 1, "a rejected reserve never bumps the vessel"

    reserve_allocation(contract_id, tank_two["id"], allocated_gallons=1000)
    filled = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert filled["gallons_allocated"] == pytest.approx(5000.00, abs=0.01)


def test_barrel_entitlement_counts_slots_rather_than_gallons(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "Three ceilings then apply: `allocated_gallons` may not exceed
    the vessel's `capacity_gallons` (`ERR_VESSEL_CAPACITY_EXCEEDED`); for a
    `TANK` vessel, the contract's current `gallons_allocated` plus the newly
    requested `allocated_gallons` may not exceed `tank_gallons_entitled`
    (`ERR_TANK_ENTITLEMENT_EXCEEDED`); and for a `BARREL` vessel, the contract's
    current `barrel_slots_used` plus one may not exceed `barrel_slots_entitled`
    (`ERR_BARREL_SLOTS_EXHAUSTED`)."
    PRD 3.2: "It recomputes the contract's `gallons_allocated` (the total
    `allocated_gallons` over that contract's `RESERVED` and `COMMITTED`
    allocations pointing at `TANK` vessels) and `barrel_slots_used` (the count
    of that contract's `RESERVED` and `COMMITTED` allocations pointing at
    `BARREL` vessels), incrementing the contract's `version`, and it increments
    the vessel's `version` as well."

    Design: Corner/validations/corner_barrel_slots_exhausted_at_entitlement_boundary
    """
    scenario = setup_active_contract(barrel_slots_entitled=1)
    contract_id = scenario["contract"]["id"]
    barrel_one = new_vessel(
        vessel_code="BBL-0001",
        vessel_type="BARREL",
        capacity_gallons=60,
        facility_zone="BARREL_HALL",
    )
    barrel_two = new_vessel(
        vessel_code="BBL-0002",
        vessel_type="BARREL",
        capacity_gallons=60,
        facility_zone="BARREL_HALL",
    )
    reserve_allocation(
        contract_id,
        barrel_one["id"],
        allocated_gallons=60,
        end_at="2027-03-01T00:00:00Z",
    )

    response = api.create_vessel_allocation(
        {
            "contract_id": contract_id,
            "vessel_id": barrel_two["id"],
            "start_at": "2026-09-01T00:00:00Z",
            "end_at": "2027-03-01T00:00:00Z",
            "allocated_gallons": 60,
            "expected_vessel_version": read_vessel_version(barrel_two["id"]),
        },
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_BARREL_SLOTS_EXHAUSTED.value, 422)

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["barrel_slots_used"] == 1
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01), (
        "barrel gallons never count against the tank entitlement"
    )


def test_allocation_with_a_zero_length_window_is_an_invalid_interval(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "The interval must be sane — `end_at` strictly after
    `start_at`, otherwise `ERR_INVALID_INTERVAL` — and must lie inside the
    contract's effective window, otherwise `ERR_OUTSIDE_CONTRACT_WINDOW`."

    Design: Corner/validations/corner_allocation_zero_length_interval_rejected
    """
    scenario = setup_active_contract()
    vessel = new_vessel()

    response = api.create_vessel_allocation(
        {
            "contract_id": scenario["contract"]["id"],
            "vessel_id": vessel["id"],
            "start_at": "2026-09-01T00:00:00Z",
            "end_at": "2026-09-01T00:00:00Z",
            "allocated_gallons": 1000,
            "expected_vessel_version": vessel["version"],
        },
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INTERVAL.value, 422)

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01)
    stored_vessel = validate_success(api.get_vessel(vessel["id"], facility_admin_headers))
    assert stored_vessel["version"] == 1


def test_reserving_twice_on_one_vessel_needs_a_re_read_version(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.6: "A `POST /vessel-allocations` request must carry
    `expected_vessel_version` equal to the target `Vessel`'s current `version`."
    PRD 2.6: "Note that a successful reservation itself increments the vessel's
    `version`, so a caller booking two windows back to back must re-read the
    vessel between them."

    Design: Corner/errors/corner_stale_vessel_version_on_allocation_reserve_rejected
    """
    scenario = setup_active_contract()
    contract_id = scenario["contract"]["id"]
    vessel = new_vessel()
    stale_version = vessel["version"]
    first = reserve_allocation(
        contract_id, vessel["id"], allocated_gallons=2000,
        expected_vessel_version=stale_version,
    )

    response = api.create_vessel_allocation(
        {
            "contract_id": contract_id,
            "vessel_id": vessel["id"],
            "start_at": "2027-01-05T00:00:00Z",
            "end_at": "2027-03-01T00:00:00Z",
            "allocated_gallons": 1500,
            "expected_vessel_version": stale_version,
        },
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VESSEL_VERSION.value, 412)

    fresh = validate_success(api.get_vessel(vessel["id"], cellar_supervisor_headers))
    assert fresh["version"] == 2, "the first reserve advanced the vessel"

    second = validate_success(
        api.create_vessel_allocation(
            {
                "contract_id": contract_id,
                "vessel_id": vessel["id"],
                "start_at": "2027-01-05T00:00:00Z",
                "end_at": "2027-03-01T00:00:00Z",
                "allocated_gallons": 1500,
                "expected_vessel_version": fresh["version"],
            },
            cellar_supervisor_headers,
        ),
        201,
    )
    assert second["status"] == "RESERVED"

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["gallons_allocated"] == pytest.approx(3500.00, abs=0.01)

    rows, _ = validate_paginated(
        api.list_vessel_allocations(
            facility_admin_headers, params={"vessel_id": vessel["id"]}
        )
    )
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])


def test_start_fermentation_needs_the_lot_to_be_housed(api, cellar_supervisor_headers):
    """PRD 3.4: "On the production axis, a `CellarSupervisor` starts
    fermentation, moving `JUICE` to `FERMENTING`; the lot must be housed at that
    moment, meaning its `current_vessel_id` is not null, and an unhoused lot is
    refused with `ERR_LOT_NOT_HOUSED`."

    Design: Corner/errors/corner_start_fermentation_on_unhoused_lot_rejected
    """
    scenario = setup_contract_with_lot(
        load=LOAD_5T_CHARDONNAY_NAPA, delivery_ticket="DT-X1", lot_code="CH-NAP-26-01"
    )
    vessel = new_vessel()
    allocation = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=1000
    )

    response = api.lot_transition(
        scenario["lot"]["id"], {"action": "START_FERMENTATION"}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_LOT_NOT_HOUSED.value, 409)

    unmoved = validate_success(
        api.get_lot(scenario["lot"]["id"], cellar_supervisor_headers)
    )
    assert unmoved["production_status"] == "JUICE"

    commit_allocation(allocation["id"], scenario["lot"]["id"])
    fermenting = validate_success(
        api.lot_transition(
            scenario["lot"]["id"], {"action": "START_FERMENTATION"}, cellar_supervisor_headers
        )
    )
    assert_lot(fermenting)
    assert fermenting["production_status"] == "FERMENTING"


def test_unknown_body_lot_id_outranks_the_allocation_state_check(
    api, cellar_supervisor_headers
):
    """PRD 2.5: "Requests are validated in a strictly ordered ladder, and the
    **first** rung that fails decides the response."
    PRD 2.5: "Every reference supplied in a request body must resolve:
    `client_id`, `contract_id`, `vessel_id`, `lot_id`, `line_id`, each entry of
    `intake_ids`, and each `source_lot_id` inside `components`. The rejection is
    the matching not-found code above, with status 404."

    Design: Corner/validations/corner_body_fk_existence_outranks_state_on_commit_not_found
    """
    scenario = setup_contract_with_lot(
        load=LOAD_5T_CHARDONNAY_NAPA, delivery_ticket="DT-M1", lot_code="CH-NAP-26-01"
    )
    vessel = new_vessel()
    allocation = house_lot(
        scenario["contract"]["id"], vessel["id"], scenario["lot"]["id"], 1000
    )
    release_allocation(allocation["id"])
    clean_vessel(vessel["id"])

    response = api.commit_vessel_allocation(
        allocation["id"], {"lot_id": NON_EXISTENT_UUID}, cellar_supervisor_headers
    )

    validate_error(response, ApiErrorId.ERR_LOT_NOT_FOUND.value, 404)

    stored = validate_success(
        api.get_vessel_allocation(allocation["id"], cellar_supervisor_headers)
    )
    assert stored["status"] == "RELEASED"
    assert stored["lot_id"] == scenario["lot"]["id"]


# ── The trailing cleaning buffer on vessel occupancy ─────────────────


def _setup_tank_with_autumn_reservation():
    """One ACTIVE contract and a 4000-gallon tank booked 2026-09-01 .. 2026-11-01,
    whose trailing cleaning buffer therefore runs to 2026-11-03."""
    scenario = setup_active_contract()
    vessel = new_vessel()
    scenario["vessel"] = vessel
    scenario["allocation"] = reserve_allocation(
        scenario["contract"]["id"], vessel["id"], allocated_gallons=4000
    )
    return scenario


def test_window_opening_inside_the_two_day_cleaning_buffer_is_an_overlap(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "The requested interval, treated as half-open from `start_at` up
    to but not including `end_at`, must not intersect any other live
    allocation's interval on the same vessel **extended by a two-day cleaning
    buffer** — that is, the other allocation is treated as occupying from its
    `start_at` up to its `end_at` plus 48 hours."
    PRD 3.2: "An intersection is refused with `ERR_VESSEL_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/vessel_allocation_blocked_inside_trailing_cleaning_buffer
    """
    scenario = _setup_tank_with_autumn_reservation()
    vessel_id = scenario["vessel"]["id"]

    response = api.create_vessel_allocation(
        {
            "contract_id": scenario["contract"]["id"],
            "vessel_id": vessel_id,
            "start_at": "2026-11-02T00:00:00Z",
            "end_at": "2026-12-01T00:00:00Z",
            "allocated_gallons": 3000,
            "expected_vessel_version": read_vessel_version(vessel_id),
        },
        cellar_supervisor_headers,
    )

    validate_error(response, ApiErrorId.ERR_VESSEL_OVERLAP.value, 409)

    vessel = validate_success(api.get_vessel(vessel_id, facility_admin_headers))
    assert vessel["condition"] == "CLEAN", (
        "an overlap rejection never dirties cooperage"
    )
    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(4000.00, abs=0.01)


def test_window_opening_exactly_at_the_end_of_the_buffer_is_bookable(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.2: "The requested interval, treated as half-open from `start_at` up
    to but not including `end_at`, must not intersect any other live
    allocation's interval on the same vessel **extended by a two-day cleaning
    buffer** — that is, the other allocation is treated as occupying from its
    `start_at` up to its `end_at` plus 48 hours."
    PRD 3.2: "A successful reservation is stored in `status` `RESERVED` with
    `lot_id`, `committed_at` and `released_at` all null and `occupied_days` at
    0."

    Design: Difficulty/resource_temporal_overlap/vessel_allocation_blocked_inside_trailing_cleaning_buffer
    """
    scenario = _setup_tank_with_autumn_reservation()
    vessel_id = scenario["vessel"]["id"]

    data = validate_success(
        api.create_vessel_allocation(
            {
                "contract_id": scenario["contract"]["id"],
                "vessel_id": vessel_id,
                "start_at": "2026-11-03T00:00:00Z",
                "end_at": "2026-12-01T00:00:00Z",
                "allocated_gallons": 3000,
                "expected_vessel_version": read_vessel_version(vessel_id),
            },
            cellar_supervisor_headers,
        ),
        201,
    )

    assert_vessel_allocation(data)
    assert data["status"] == "RESERVED"
    assert data["start_at"] == "2026-11-03T00:00:00.000Z"
    assert data["end_at"] == "2026-12-01T00:00:00.000Z"
    assert data["lot_id"] is None
    assert data["committed_at"] is None
    assert data["occupied_days"] == 0

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(7000.00, abs=0.01)


# ── Ladder order: the state rung outranks the entitlement rung ───────


def _setup_released_allocation_and_oversized_lot():
    """A RELEASED 1000-gallon allocation on a re-cleaned tank, plus an unhoused
    3135.00-gallon lot on the same contract."""
    scenario = setup_contract_with_lot(
        load=LOAD_5T_CHARDONNAY_NAPA, delivery_ticket="DT-7001", lot_code="CH-NAP-26-01"
    )
    contract_id = scenario["contract"]["id"]
    big_intake = new_accepted_intake(
        contract_id, "DT-7002", load=LOAD_19T_CABERNET_OAKVILLE
    )
    big_lot = new_lot(contract_id, [big_intake["id"]], lot_code="CS-OAK-26-01")

    vessel = new_vessel()
    allocation = house_lot(contract_id, vessel["id"], scenario["lot"]["id"], 1000)
    release_allocation(allocation["id"])
    clean_vessel(vessel["id"])

    scenario["vessel"] = vessel
    scenario["allocation"] = allocation
    scenario["big_lot"] = big_lot
    return scenario


def test_committing_into_a_released_allocation_reports_invalid_state(
    api, cellar_supervisor_headers
):
    """PRD 2.5: "Requests are validated in a strictly ordered ladder, and the
    **first** rung that fails decides the response."
    PRD 2.5: "The requested action must be a transition declared out of the
    target's current state. Repeating a trigger that has already fired, and any
    action attempted out of a terminal state, both fail here with
    `ERR_INVALID_STATE` (409)."
    PRD 3.2: "Both `RELEASED` and `CANCELLED` are terminal."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_when_committing_a_released_allocation
    """
    scenario = _setup_released_allocation_and_oversized_lot()

    response = api.commit_vessel_allocation(
        scenario["allocation"]["id"],
        {"lot_id": scenario["big_lot"]["id"]},
        cellar_supervisor_headers,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_VESSEL_CAPACITY_EXCEEDED.value, (
        "the state rung sits above the entitlement rung, so the capacity breach "
        "must not be the reported failure"
    )


def test_rejected_commit_into_a_released_allocation_mutates_nothing(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.5: "Two rungs are never both reported: if a caller sends an
    unauthorized role together with a malformed body and a non-existent path id,
    the role rejection wins, because it sits higher on the ladder."
    PRD 3.2: "Finally the lot's `volume_gallons` may not exceed the allocation's
    `allocated_gallons`, which is the second reading of
    `ERR_VESSEL_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_when_committing_a_released_allocation
    """
    scenario = _setup_released_allocation_and_oversized_lot()

    api.commit_vessel_allocation(
        scenario["allocation"]["id"],
        {"lot_id": scenario["big_lot"]["id"]},
        cellar_supervisor_headers,
    )

    allocation = validate_success(
        api.get_vessel_allocation(scenario["allocation"]["id"], facility_admin_headers)
    )
    assert allocation["status"] == "RELEASED"
    assert allocation["lot_id"] == scenario["lot"]["id"], (
        "the rejected call must not repoint the released allocation"
    )

    big_lot = validate_success(
        api.get_lot(scenario["big_lot"]["id"], facility_admin_headers)
    )
    assert big_lot["current_vessel_id"] is None
    assert big_lot["volume_gallons"] == pytest.approx(3135.00, abs=0.01)

    vessel = validate_success(api.get_vessel(scenario["vessel"]["id"], facility_admin_headers))
    assert vessel["condition"] == "CLEAN"
