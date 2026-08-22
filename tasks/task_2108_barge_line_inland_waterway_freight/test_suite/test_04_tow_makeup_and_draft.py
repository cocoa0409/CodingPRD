"""Building a tow: makeup gates, the draft profile, light-loading and sealing."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_assignment,
    adjust_load,
    assert_tow_rollup,
    create_active_contract,
    create_barge,
    create_barge_assignment_payload,
    create_commodity,
    create_compatibility_rule,
    create_contract,
    create_effective_tariff,
    create_fuel_posting,
    create_river_reading,
    create_shipper,
    create_tow,
    book_contract,
    activate_contract,
    drop_assignment,
    make_towboat_dispatcher_headers,
    read_assignment,
    read_barge,
    read_tow,
    seal_tow,
    set_clock,
    setup_grain_movement,
    setup_grain_reference,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCH = make_towboat_dispatcher_headers()


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / the band's lower edge
# ---------------------------------------------------------------------------
def _two_gauges_at_the_band_edge():
    reference = setup_grain_reference(gauge_station="MEMPHIS", stage_feet=15.0,
                                      reading_at="2026-08-02T06:00:00Z")
    create_river_reading(gauge_station="VICKSBURG",
                         reading_at="2026-08-02T06:00:00Z", stage_feet=14.9)
    return reference


def test_stage_of_exactly_fifteen_feet_is_normal_and_seals_the_makeup(api):
    """PRD §3.2: "The `draft_restriction_band` is resolved from `stage_feet`
    with lower-edge-inclusive boundaries: a stage of 25.0 feet or higher is
    `HIGH_WATER`; a stage of at least 15.0 feet but below 25.0 is `NORMAL`; a
    stage of at least 8.0 feet but below 15.0 is `LOW`; anything below 8.0 feet
    is `CRITICAL`."
    PRD §3.2: "The band then fixes the other two: `max_draft_feet` is 12.0 feet
    in `HIGH_WATER`, 12.0 feet in `NORMAL`, 10.5 feet in `LOW` and 9.0 feet in
    `CRITICAL`, while `tow_size_cap_barges` is 20 barges in `HIGH_WATER`, 40 in
    `NORMAL`, 30 in `LOW` and just 6 in `CRITICAL`."

    Design: Difficulty/boundary_precision_check/river_stage_band_lower_bound_is_inclusive_at_fifteen_feet
    """
    reference = _two_gauges_at_the_band_edge()
    movement = setup_grain_movement(
        loads=(1900,), capacities=(2200,), reference=reference,
        tow_kwargs={"towboat_name": "M/V Memphis",
                    "controlling_gauge_station": "MEMPHIS"})

    tow = seal_tow(movement["tow_id"])
    assert tow["draft_restriction_band"] == "NORMAL", (
        "15.0 feet sits on the inclusive lower edge of NORMAL")
    assert float(tow["allowed_draft_feet"]) == 12.0
    assert float(tow["max_draft_feet"]) == 10.81, (
        f"1900 tons on a 17.0 t/in hull draws 10.81 feet, got {tow['max_draft_feet']}")
    assert tow["status"] == "SEALED"
    assert read_assignment(movement["assignments"][0]["id"])["status"] == "CONFIRMED"


def test_stage_one_tenth_below_fifteen_feet_is_low_and_refuses_the_seal(api):
    """PRD §3.2: "The `draft_restriction_band` is resolved from `stage_feet`
    with lower-edge-inclusive boundaries: a stage of 25.0 feet or higher is
    `HIGH_WATER`; a stage of at least 15.0 feet but below 25.0 is `NORMAL`; a
    stage of at least 8.0 feet but below 15.0 is `LOW`; anything below 8.0 feet
    is `CRITICAL`."
    PRD §3.5: "The tow's `max_draft_feet` must be at or below the controlling
    band's permitted `max_draft_feet`, failing which the seal is refused with
    `ERR_DRAFT_EXCEEDS_RESTRICTION`; and the tow's `barge_count` must be at or
    below that band's `tow_size_cap_barges`, failing which the seal is refused
    with `ERR_TOW_SIZE_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/river_stage_band_lower_bound_is_inclusive_at_fifteen_feet
    """
    reference = _two_gauges_at_the_band_edge()
    movement = setup_grain_movement(
        loads=(1900,), capacities=(2200,), reference=reference,
        tow_kwargs={"towboat_name": "M/V Vicksburg",
                    "controlling_gauge_station": "VICKSBURG"})

    validate_error(api.seal_tow(movement["tow_id"], DISPATCH),
                   ApiErrorId.ERR_DRAFT_EXCEEDS_RESTRICTION.value)

    tow = read_tow(movement["tow_id"])
    assert tow["draft_restriction_band"] == "LOW", (
        "14.9 feet falls one tenth below the NORMAL edge")
    assert float(tow["allowed_draft_feet"]) == 10.5
    assert tow["status"] == "BUILDING", "the refused seal leaves the tow BUILDING"
    assert read_assignment(movement["assignments"][0]["id"])["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / tonnage and draft conserved by a drop
# ---------------------------------------------------------------------------
def _tow_with_two_cuts():
    movement = setup_grain_movement(
        loads=(1700, 1650), contracted_tons=5100, stage="BUILDING")
    third_hull = create_barge(hull_number="BL-1003")
    return movement, third_hull


def test_adding_a_third_cut_lifts_the_tow_rollup(api):
    """PRD §3.5: "Over that active set, `barge_count` is the number of
    assignments, `total_loaded_tons` is the sum of their `loaded_tons`, and
    `max_draft_feet` is the greatest `barge_draft_feet` among them, taken as 0
    when the active set is empty."
    PRD §3.5: "For a single assignment, `barge_draft_feet` is the hull's
    `light_draft_feet` plus the quotient of `loaded_tons` divided by the product
    of the hull's `tons_per_inch_immersion` and the twelve inches in a foot,
    with the result rounded half up to two decimal places."

    Design: Difficulty/compensating_invariant/tow_tonnage_and_draft_profile_conserved_by_assignment_drop
    """
    movement, third_hull = _tow_with_two_cuts()
    before = read_tow(movement["tow_id"])
    assert before["total_loaded_tons"] == 3350
    assert float(before["max_draft_feet"]) == 9.83

    third = add_assignment(movement["tow_id"], third_hull["id"],
                           movement["contract_id"], loaded_tons=1740, cut_position=3)
    assert float(third["barge_draft_feet"]) == 10.03, (
        f"1740 tons draws 10.03 feet, got {third['barge_draft_feet']}")

    tow = read_tow(movement["tow_id"])
    assert tow["barge_count"] == 3
    assert tow["total_loaded_tons"] == 5090
    assert float(tow["max_draft_feet"]) == 10.03, (
        "the rollup takes the greatest rounded barge draft")


def test_dropping_the_third_cut_restores_the_tow_rollup_exactly(api):
    """PRD §3.5: "The drop removes that assignment's `loaded_tons` from the
    tow's `total_loaded_tons`, decrements the tow's `barge_count` by one, and
    recomputes `max_draft_feet` across the remaining active assignments —
    yielding 0 when none remain."
    PRD §3.5: "The hull returns to `operational_status` `IDLE` if it had already
    been taken `IN_TOW`, and because no cargo ever moved, the hull's
    `cleanliness_status` and `last_cargo_commodity_id` are deliberately left
    untouched."

    Design: Difficulty/compensating_invariant/tow_tonnage_and_draft_profile_conserved_by_assignment_drop
    """
    movement, third_hull = _tow_with_two_cuts()
    third = add_assignment(movement["tow_id"], third_hull["id"],
                           movement["contract_id"], loaded_tons=1740, cut_position=3)

    dropped = drop_assignment(third["id"])
    assert dropped["status"] == "DROPPED"

    tow = read_tow(movement["tow_id"])
    assert tow["total_loaded_tons"] == 3350, (
        f"tonnage returns to exactly its pre-add value, got {tow['total_loaded_tons']}")
    assert tow["barge_count"] == 2
    assert float(tow["max_draft_feet"]) == 9.83, (
        f"the draft profile returns to exactly its pre-add value, "
        f"got {tow['max_draft_feet']}")
    assert read_barge(third_hull["id"])["operational_status"] == "IDLE"

    first = read_assignment(movement["assignments"][0]["id"])
    second = read_assignment(movement["assignments"][1]["id"])
    assert first["loaded_tons"] == 1700 and second["loaded_tons"] == 1650, (
        "the surviving cuts are untouched by the round trip")
    assert_tow_rollup(tow, [first, second, read_assignment(third["id"])])


# ---------------------------------------------------------------------------
# Queue A — priority_pair / state outranks the draft safety gate
# ---------------------------------------------------------------------------
def _sealed_tow_then_falling_river():
    reference = setup_grain_reference(stage_feet=18.0)
    movement = setup_grain_movement(
        loads=(1900,), capacities=(2200,), stage="SEALED", reference=reference,
        tow_kwargs={"towboat_name": "M/V Helena"})
    create_river_reading(gauge_station="MEMPHIS",
                         reading_at="2026-08-05T00:00:00Z", stage_feet=7.5)
    return reference, movement


def test_resealing_a_sealed_tow_reports_the_state_error_not_the_draft_error(api):
    """PRD §2.7: "When a request violates more than one rule, exactly one error
    is returned, and which one is fully determined: the checks below are
    evaluated in strictly ascending order and **the first failing check decides
    the response**."
    PRD §2.7: "**State precondition.** The target resource stands in a state
    from which the requested transition is declared, including the hull's
    `operational_status` when it is being fleeted, assigned or washed —
    otherwise the entity's invalid-state code (409), or `ERR_BARGE_NOT_AVAILABLE`
    (409) where the obstruction is the hull's operational posture. Applies to
    every transition endpoint."
    PRD §2.7: "**Draft restriction.** The tow's `max_draft_feet` is at or below
    the controlling band's permitted `max_draft_feet` — otherwise
    `ERR_DRAFT_EXCEEDS_RESTRICTION` (422). Guards sealing a tow."

    Design: Difficulty/priority_pair_validation_conflict/tow_state_precondition_outranks_draft_safety_gate_on_seal
    """
    _reference, movement = _sealed_tow_then_falling_river()

    validate_error(api.seal_tow(movement["tow_id"], DISPATCH),
                   ApiErrorId.ERR_TOW_INVALID_STATE.value)

    tow = read_tow(movement["tow_id"])
    assert tow["status"] == "SEALED", "the refused call changed nothing"
    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["status"] == "CONFIRMED"
    assert float(assignment["barge_draft_feet"]) == 10.81


def test_the_same_makeup_on_a_building_tow_hits_the_draft_gate(api):
    """PRD §3.5: "The tow's `max_draft_feet` must be at or below the controlling
    band's permitted `max_draft_feet`, failing which the seal is refused with
    `ERR_DRAFT_EXCEEDS_RESTRICTION`; and the tow's `barge_count` must be at or
    below that band's `tow_size_cap_barges`, failing which the seal is refused
    with `ERR_TOW_SIZE_CAP_EXCEEDED`."
    PRD §3.2: "The band then fixes the other two: `max_draft_feet` is 12.0 feet
    in `HIGH_WATER`, 12.0 feet in `NORMAL`, 10.5 feet in `LOW` and 9.0 feet in
    `CRITICAL`, while `tow_size_cap_barges` is 20 barges in `HIGH_WATER`, 40 in
    `NORMAL`, 30 in `LOW` and just 6 in `CRITICAL`."

    Design: Difficulty/priority_pair_validation_conflict/tow_state_precondition_outranks_draft_safety_gate_on_seal
    """
    reference, _movement = _sealed_tow_then_falling_river()
    second = setup_grain_movement(
        loads=(1900,), capacities=(2200,), reference=reference,
        tow_kwargs={"towboat_name": "M/V Greenville"})

    validate_error(api.seal_tow(second["tow_id"], DISPATCH),
                   ApiErrorId.ERR_DRAFT_EXCEEDS_RESTRICTION.value)
    tow = read_tow(second["tow_id"])
    assert tow["draft_restriction_band"] == "CRITICAL", (
        "the 7.5-foot reading now controls")
    assert float(tow["allowed_draft_feet"]) == 9.0
    assert tow["status"] == "BUILDING"


# ---------------------------------------------------------------------------
# Queue A — priority_pair / cleanliness outranks the reused-hull constraint
# ---------------------------------------------------------------------------
def _hull_dirty_for_grain_and_already_assigned():
    """A WASHED hull whose last cargo was fertilizer, already carrying a PLANNED
    fertilizer assignment, plus an ACTIVE grain contract and an empty tow."""
    set_clock("2026-08-02T00:00:00Z")
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    uan = create_commodity(code="UAN32", commodity_group="FERTILIZER",
                           residue_class="TOXIC", hazard_flag=True, stowage_factor=0.85)
    create_compatibility_rule("FERTILIZER", "FERTILIZER",
                              required_cleaning_level="SWEEP", prohibited=False)
    create_compatibility_rule("FERTILIZER", "GRAIN",
                              required_cleaning_level="STEAM_CERT", prohibited=False)
    create_effective_tariff(commodity_group="GRAIN", tariff_code="T-GRAIN-2026")
    create_effective_tariff(commodity_group="FERTILIZER", tariff_code="T-FERT-2026",
                            base_rate_cents_per_ton_mile=1.5,
                            demurrage_rate_cents_per_hour=40_000)
    create_fuel_posting()
    create_river_reading()
    shipper = create_shipper()
    hull = create_barge(hull_number="BL-4001", cleanliness_status="WASHED",
                        last_cargo_commodity_id=uan["id"])
    set_clock("2026-08-05T00:00:00Z")

    fert_contract = create_active_contract(shipper["id"], uan["id"], contracted_tons=1000)
    grain_contract = create_active_contract(shipper["id"], corn["id"], contracted_tons=1700)
    first_tow = create_tow(towboat_name="M/V Natchez", horsepower=4200)
    fert_assignment = add_assignment(first_tow["id"], hull["id"], fert_contract["id"],
                                     loaded_tons=1000, cut_position=1)
    second_tow = create_tow(towboat_name="M/V Greenville", horsepower=4200)
    return hull, grain_contract, fert_assignment, second_tow


def test_cleanliness_gate_outranks_the_already_assigned_constraint(api):
    """PRD §2.7: "**Cleanliness sufficiency.** The hull's cleanliness rank is at
    least the rank of the cleaning level the matrix requires for the target
    commodity — otherwise `ERR_BARGE_CLEANLINESS_INSUFFICIENT` (422). Guards the
    same two operations: adding a barge assignment, and sealing a tow."
    PRD §2.7: "**Single active assignment per hull.** The hull does not already
    hold an assignment in status `PLANNED`, `CONFIRMED` or `LOADED` on any tow —
    otherwise `ERR_BARGE_ALREADY_ASSIGNED` (409). Guards adding a barge
    assignment to a tow."

    Design: Difficulty/priority_pair_validation_conflict/cleanliness_safety_outranks_barge_already_assigned_constraint
    """
    hull, grain_contract, _fert_assignment, second_tow = \
        _hull_dirty_for_grain_and_already_assigned()

    validate_error(api.create_barge_assignment(
        second_tow["id"],
        create_barge_assignment_payload(hull["id"], grain_contract["id"],
                                        loaded_tons=1500, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_BARGE_CLEANLINESS_INSUFFICIENT.value)

    tow = read_tow(second_tow["id"])
    assert tow["barge_count"] == 0, "the refused addition must not join the makeup"
    assert tow["total_loaded_tons"] == 0


def test_the_refused_grain_assignment_leaves_the_fertilizer_cut_standing(api):
    """PRD §3.1: "The hull passes only when its cleanliness rank is greater than
    or equal to the rank of the required level; a hull that falls below is
    refused with `ERR_BARGE_CLEANLINESS_INSUFFICIENT`."
    PRD §3.5: "The prior-cargo prohibition is then tested and, if the pair is
    prohibited, the request is refused with `ERR_CARGO_INCOMPATIBLE`; the hull's
    cleanliness rank is tested next against the required level and, if it falls
    short, the request is refused with `ERR_BARGE_CLEANLINESS_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/cleanliness_safety_outranks_barge_already_assigned_constraint
    """
    hull, grain_contract, fert_assignment, second_tow = \
        _hull_dirty_for_grain_and_already_assigned()

    validate_error(api.create_barge_assignment(
        second_tow["id"],
        create_barge_assignment_payload(hull["id"], grain_contract["id"],
                                        loaded_tons=1500, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_BARGE_CLEANLINESS_INSUFFICIENT.value)

    standing = read_assignment(fert_assignment["id"])
    assert standing["status"] == "PLANNED", (
        "the fertilizer assignment the hull already holds is untouched")
    assert standing["loaded_tons"] == 1000
    _rows, meta = validate_paginated(api.list_barge_assignments(
        DISPATCH, params={"tow_id": second_tow["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Queue A — priority_pair / foreign-key existence outranks tow state
# ---------------------------------------------------------------------------
def test_unknown_barge_on_a_sealed_tow_reports_the_not_found_code(api):
    """PRD §2.7: "**Foreign-key existence.** Every foreign key supplied in the
    body resolves to an existing row, validated in the order the fields are
    declared in the endpoint's input list — otherwise the matching not-found
    code (404). Applies to every write endpoint carrying foreign keys."
    PRD §2.6: "Foreign keys arriving in a request body are resolved after every
    path segment has resolved, and they are resolved **in the order the fields
    are declared in that endpoint's input list**, not in alphabetical order and
    not in the order the client happened to serialize them."

    Design: Difficulty/priority_pair_validation_conflict/body_foreign_key_existence_outranks_tow_state_on_assignment_create
    """
    movement = setup_grain_movement(loads=(1700,), stage="SEALED")

    validate_error(api.create_barge_assignment(
        movement["tow_id"],
        create_barge_assignment_payload(NON_EXISTENT_UUID, movement["contract_id"],
                                        loaded_tons=100, cut_position=9),
        DISPATCH),
        ApiErrorId.ERR_BARGE_NOT_FOUND.value)

    tow = read_tow(movement["tow_id"])
    assert tow["barge_count"] == 1, "the refused call changed no makeup"
    assert tow["total_loaded_tons"] == 1700


def test_unknown_contract_on_a_sealed_tow_reports_the_contract_not_found_code(api):
    """PRD §2.7: "**Foreign-key existence.** Every foreign key supplied in the
    body resolves to an existing row, validated in the order the fields are
    declared in the endpoint's input list — otherwise the matching not-found
    code (404). Applies to every write endpoint carrying foreign keys."
    PRD §2.6: "A create call that names both a missing barge and a missing
    contract reports whichever of the two is declared first for that endpoint."

    Design: Difficulty/priority_pair_validation_conflict/body_foreign_key_existence_outranks_tow_state_on_assignment_create
    """
    movement = setup_grain_movement(loads=(1700,), stage="SEALED")
    spare_hull = create_barge(hull_number="BL-4409")

    validate_error(api.create_barge_assignment(
        movement["tow_id"],
        create_barge_assignment_payload(spare_hull["id"], NON_EXISTENT_UUID,
                                        loaded_tons=100, cut_position=9),
        DISPATCH),
        ApiErrorId.ERR_FREIGHT_CONTRACT_NOT_FOUND.value)

    assert read_tow(movement["tow_id"])["barge_count"] == 1
    assert read_barge(spare_hull["id"])["operational_status"] == "IDLE"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / the contract's movement axis
# ---------------------------------------------------------------------------
def _booked_contract_and_empty_tow():
    reference = setup_grain_reference()
    hull = create_barge(hull_number="BL-1001")
    contract = create_contract(reference["shipper_id"], reference["commodity_id"],
                               contracted_tons=1700)
    book_contract(contract["id"])
    tow = create_tow(controlling_gauge_station=reference["gauge_station"])
    return hull, contract, tow


def test_barge_may_not_join_a_tow_against_a_merely_booked_contract(api):
    """PRD §3.5: "The named contract must stand in `movement_status` `ACTIVE` or
    `IN_TRANSIT`; a contract in any other movement state is refused with
    `ERR_CONTRACT_MOVEMENT_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/barge_assignment_requires_contract_active_not_merely_booked
    """
    hull, contract, tow = _booked_contract_and_empty_tow()

    validate_error(api.create_barge_assignment(
        tow["id"],
        create_barge_assignment_payload(hull["id"], contract["id"],
                                        loaded_tons=1700, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_CONTRACT_MOVEMENT_INVALID_STATE.value)

    assert read_tow(tow["id"])["barge_count"] == 0
    assert read_barge(hull["id"])["operational_status"] == "IDLE"


def test_the_identical_addition_succeeds_once_the_contract_is_active(api):
    """PRD §3.5: "The named contract must stand in `movement_status` `ACTIVE` or
    `IN_TRANSIT`; a contract in any other movement state is refused with
    `ERR_CONTRACT_MOVEMENT_INVALID_STATE`."
    PRD §3.5: "The assignment is created with `status` `PLANNED` on the makeup
    axis and `discharge_status` `NOT_ARRIVED` on the unload axis."

    Design: Difficulty/cross_entity_state_dependency/barge_assignment_requires_contract_active_not_merely_booked
    """
    hull, contract, tow = _booked_contract_and_empty_tow()
    validate_error(api.create_barge_assignment(
        tow["id"],
        create_barge_assignment_payload(hull["id"], contract["id"],
                                        loaded_tons=1700, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_CONTRACT_MOVEMENT_INVALID_STATE.value)

    activated = activate_contract(contract["id"])
    assert activated["movement_status"] == "ACTIVE"
    assert float(activated["pinned_fuel_surcharge_pct"]) == 0.045

    created = validate_success(api.create_barge_assignment(
        tow["id"],
        create_barge_assignment_payload(hull["id"], contract["id"],
                                        loaded_tons=1700, cut_position=1),
        DISPATCH), 201)
    assert created["status"] == "PLANNED"
    assert created["discharge_status"] == "NOT_ARRIVED"

    refreshed = read_tow(tow["id"])
    assert refreshed["barge_count"] == 1
    assert refreshed["total_loaded_tons"] == 1700
    assert float(refreshed["max_draft_feet"]) == 9.83


# ---------------------------------------------------------------------------
# Queue B — makeup and seal validations
# ---------------------------------------------------------------------------
def test_assignment_guards_reject_capacity_then_cut_position_then_reused_hull(api):
    """PRD §3.5: "Only then is `loaded_tons` compared against the hull's
    `capacity_tons`, exceeding it being refused with
    `ERR_BARGE_CAPACITY_EXCEEDED`. Below that come the two structural gates: a
    `cut_position` already occupied by a non-`DROPPED` assignment of the same
    tow is refused with `ERR_DUPLICATE_CUT_POSITION`, and a hull that already
    holds an assignment in `PLANNED`, `CONFIRMED` or `LOADED` status on any tow
    anywhere is refused with `ERR_BARGE_ALREADY_ASSIGNED`."

    Design: Corner/validations/assignment_creation_guards_reject_capacity_then_cut_position_then_reused_hull
    """
    reference = setup_grain_reference()
    first_hull = create_barge(hull_number="BL-1001")
    second_hull = create_barge(hull_number="BL-1002")
    contract = create_active_contract(reference["shipper_id"],
                                      reference["commodity_id"], contracted_tons=3400)
    first_tow = create_tow(towboat_name="M/V Juliet")
    second_tow = create_tow(towboat_name="M/V Kilo")

    validate_error(api.create_barge_assignment(
        first_tow["id"],
        create_barge_assignment_payload(first_hull["id"], contract["id"],
                                        loaded_tons=2000, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_BARGE_CAPACITY_EXCEEDED.value)

    created = validate_success(api.create_barge_assignment(
        first_tow["id"],
        create_barge_assignment_payload(first_hull["id"], contract["id"],
                                        loaded_tons=1700, cut_position=1),
        DISPATCH), 201)
    assert created["cut_position"] == 1

    validate_error(api.create_barge_assignment(
        first_tow["id"],
        create_barge_assignment_payload(second_hull["id"], contract["id"],
                                        loaded_tons=1650, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_DUPLICATE_CUT_POSITION.value)

    validate_error(api.create_barge_assignment(
        second_tow["id"],
        create_barge_assignment_payload(first_hull["id"], contract["id"],
                                        loaded_tons=1200, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_BARGE_ALREADY_ASSIGNED.value)

    assert read_tow(first_tow["id"])["barge_count"] == 1
    assert read_tow(first_tow["id"])["total_loaded_tons"] == 1700
    assert read_tow(second_tow["id"])["barge_count"] == 0


def test_prohibited_prior_cargo_pair_is_refused(api):
    """PRD §3.1: "Each rule covers one ordered pair — a `prior_commodity_group`
    that was last carried in a hull and a `next_commodity_group` about to be
    loaded into it — and declares the `required_cleaning_level` that the hull
    must hold before the next cargo may load, one of `NONE`, `SWEEP`, `WASH` or
    `STEAM_CERT`, plus a `prohibited` flag that defaults to false and, when
    true, forbids the sequence outright no matter how thoroughly the hull is
    cleaned."
    PRD §3.1: "A prohibited pair is refused with `ERR_CARGO_INCOMPATIBLE`."

    Design: Corner/validations/prohibited_prior_cargo_pair_returns_cargo_incompatible
    """
    set_clock("2026-08-02T00:00:00Z")
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    ulsd = create_commodity(code="ULSD", commodity_group="PETROLEUM",
                            residue_class="OILY", hazard_flag=True, stowage_factor=1.1)
    create_compatibility_rule("PETROLEUM", "GRAIN",
                              required_cleaning_level="STEAM_CERT", prohibited=True)
    create_effective_tariff()
    create_fuel_posting()
    create_river_reading()
    shipper = create_shipper()
    hull = create_barge(hull_number="BL-8001", cleanliness_status="STEAM_CERTIFIED",
                        last_cargo_commodity_id=ulsd["id"])
    set_clock("2026-08-05T00:00:00Z")
    contract = create_active_contract(shipper["id"], corn["id"], contracted_tons=1700)
    tow = create_tow(towboat_name="M/V Lima")

    validate_error(api.create_barge_assignment(
        tow["id"],
        create_barge_assignment_payload(hull["id"], contract["id"],
                                        loaded_tons=1700, cut_position=1),
        DISPATCH),
        ApiErrorId.ERR_CARGO_INCOMPATIBLE.value)

    assert read_tow(tow["id"])["barge_count"] == 0
    assert read_barge(hull["id"])["operational_status"] == "IDLE"
    _rows, meta = validate_paginated(api.list_barge_assignments(
        DISPATCH, params={"tow_id": tow["id"]}))
    assert meta["total_count"] == 0


def test_tow_size_cap_stops_a_seventh_barge_under_the_critical_band(api):
    """PRD §3.5: "A `CRITICAL` river therefore stops a seventh barge outright,
    while a `NORMAL` river tolerates forty."
    PRD §2.7: "**Tow size cap.** The tow's `barge_count` is at or below the
    controlling band's `tow_size_cap_barges` — otherwise
    `ERR_TOW_SIZE_CAP_EXCEEDED` (422). Guards sealing a tow."

    Design: Corner/validations/tow_size_cap_exceeded_under_the_critical_band
    """
    movement = setup_grain_movement(
        loads=(1000,) * 7, contracted_tons=7000, stage="BUILDING",
        ref_kwargs={"stage_feet": 7.5}, tow_kwargs={"towboat_name": "M/V Mike",
                                                    "horsepower": 8000})
    tow = read_tow(movement["tow_id"])
    assert tow["barge_count"] == 7
    assert tow["total_loaded_tons"] == 7000
    assert float(tow["max_draft_feet"]) == 6.4, (
        "the seven-barge makeup clears the 9.0-foot CRITICAL draft limit")

    validate_error(api.seal_tow(movement["tow_id"], DISPATCH),
                   ApiErrorId.ERR_TOW_SIZE_CAP_EXCEEDED.value)
    tow = read_tow(movement["tow_id"])
    assert tow["draft_restriction_band"] == "CRITICAL"
    assert float(tow["allowed_draft_feet"]) == 9.0

    drop_assignment(movement["assignments"][6]["id"])
    tow = read_tow(movement["tow_id"])
    assert tow["barge_count"] == 6
    assert tow["total_loaded_tons"] == 6000

    sealed = seal_tow(movement["tow_id"])
    assert sealed["status"] == "SEALED", "six is the inclusive CRITICAL cap"


def test_seal_without_a_gauge_reading_is_refused(api):
    """PRD §3.5: "A controlling gauge reading must exist for the tow's
    `controlling_gauge_station` at or before the logical clock, absent which the
    seal is refused with `ERR_NO_RIVER_STAGE_READING`."
    PRD §2.7: "**Stage reading availability.** A river stage reading exists for
    the tow's `controlling_gauge_station` whose `reading_at` is at or before the
    logical clock — otherwise `ERR_NO_RIVER_STAGE_READING` (422). Guards two
    operations: sealing a tow, and adjusting a tow's load."

    Design: Corner/validations/seal_without_a_gauge_reading_returns_no_river_stage_reading
    """
    movement = setup_grain_movement(
        loads=(1700,), stage="BUILDING",
        tow_kwargs={"towboat_name": "M/V Helena",
                    "controlling_gauge_station": "HELENA"})

    validate_error(api.seal_tow(movement["tow_id"], DISPATCH),
                   ApiErrorId.ERR_NO_RIVER_STAGE_READING.value)
    assert read_tow(movement["tow_id"])["status"] == "BUILDING"
    assert read_assignment(movement["assignments"][0]["id"])["status"] == "PLANNED"


def test_sealing_a_tow_with_no_barges_is_refused(api):
    """PRD §3.5: "The tow must stand in `BUILDING`, and it must carry at least
    one active assignment — sealing a tow whose `barge_count` is 0 is refused
    with `ERR_TOW_INVALID_STATE`."
    PRD §3.5: "A new tow stands in status `BUILDING` with `barge_count` 0,
    `total_loaded_tons` 0 and `max_draft_feet` 0."

    Design: Corner/state_machines/seal_a_tow_with_no_barges_returns_tow_invalid_state
    """
    set_clock("2026-08-05T00:00:00Z")
    create_river_reading()
    tow = create_tow(towboat_name="M/V Hotel", horsepower=4000)

    validate_error(api.seal_tow(tow["id"], DISPATCH),
                   ApiErrorId.ERR_TOW_INVALID_STATE.value)
    stored = read_tow(tow["id"])
    assert stored["status"] == "BUILDING"
    assert stored["barge_count"] == 0
    assert float(stored["max_draft_feet"]) == 0


# ---------------------------------------------------------------------------
# Queue B — light-loading
# ---------------------------------------------------------------------------
def test_adjust_load_clamps_the_cut_to_the_critical_band_allowance(api):
    """PRD §3.5: "For each active assignment whose `barge_draft_feet` exceeds
    the controlling band's permitted draft, the hull's allowance is computed as
    the tow's `allowed_draft_feet` minus that hull's `light_draft_feet`,
    multiplied by twelve inches per foot, multiplied by that hull's
    `tons_per_inch_immersion`, then truncated downward to a whole ton."
    PRD §3.5: "The assignment's `loaded_tons` is then set to the smaller of its
    current value and that allowance — light-loading only ever removes tonnage,
    never adds it."

    Design: Corner/calculations/adjust_load_light_loads_the_tow_to_the_critical_band_allowance
    """
    movement = setup_grain_movement(
        loads=(1700,), stage="BUILDING", ref_kwargs={"stage_feet": 7.5},
        tow_kwargs={"towboat_name": "M/V Tango"})
    before = read_tow(movement["tow_id"])
    assert float(before["max_draft_feet"]) == 9.83
    assert before["draft_restriction_band"] == "CRITICAL"
    assert float(before["allowed_draft_feet"]) == 9.0

    adjust_load(movement["tow_id"])

    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["loaded_tons"] == 1530, (
        f"the CRITICAL allowance is floor(7.5 * 12 * 17.0) = 1530 tons, "
        f"got {assignment['loaded_tons']}")
    assert float(assignment["barge_draft_feet"]) == 9.0
    tow = read_tow(movement["tow_id"])
    assert tow["total_loaded_tons"] == 1530
    assert float(tow["max_draft_feet"]) == 9.0
    assert tow["status"] == "BUILDING", "light-loading is a self-loop on BUILDING"

    sealed = seal_tow(movement["tow_id"])
    assert sealed["status"] == "SEALED", "9.00 <= 9.0 passes on the inclusive edge"


def test_repeat_adjust_load_with_a_stale_tow_version_is_refused(api):
    """PRD §2.8: "**Adjusting a tow's load** likewise requires
    `expected_tow_version`. Light-loading rewrites `loaded_tons` on every
    over-draft assignment of the tow, so the request carries the `version` the
    dispatcher based the decision on; if the makeup has advanced since then, the
    adjustment is rejected with `ERR_STALE_TOW_VERSION` (HTTP 412) rather than
    applied to a composition the caller never saw."

    Design: Corner/cross_cutting_layers/repeat_adjust_load_with_stale_expected_tow_version_returns_412
    """
    movement = setup_grain_movement(
        loads=(1700,), stage="BUILDING", ref_kwargs={"stage_feet": 7.5},
        tow_kwargs={"towboat_name": "M/V Tango"})
    observed_version = read_tow(movement["tow_id"])["version"]
    adjust_load(movement["tow_id"], expected_tow_version=observed_version)

    validate_error(api.adjust_tow_load(
        movement["tow_id"], {"expected_tow_version": observed_version}, DISPATCH),
        ApiErrorId.ERR_STALE_TOW_VERSION.value)

    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["loaded_tons"] == 1530, (
        "the clamp written by the first pass is left exactly as it was")
    assert float(assignment["barge_draft_feet"]) == 9.0
    tow = read_tow(movement["tow_id"])
    assert tow["total_loaded_tons"] == 1530
    assert float(tow["max_draft_feet"]) == 9.0
    assert tow["status"] == "BUILDING"
