"""The departure safety ladder, its boundaries and its precedence over safety rungs."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_service_day,
    board_trip,
    create_trip,
    depart_trip,
    file_inspection,
    patch_service_day,
    set_clock,
    setup_harbor_world,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_master_with_a_lapsed_licence_may_not_sail(api):
    """PRD §3.7: "The master's `status` must be `ACTIVE` and both `cert_expires_on`
    and `medical_expires_on` must be no earlier than today's date, else
    `ERR_CREW_CERT_EXPIRED`."

    Design: Corner/validations/expired_crew_certificate_blocks_departure
    """
    world = setup_harbor_world(crew={"cert_expires_on": "2026-09-11"})
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_CREW_CERT_EXPIRED.value, 422)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["settlement_status"] == "UNSETTLED"


def test_master_below_the_required_endorsement_may_not_sail(api):
    """PRD §3.7: "The master's `endorsement_class` must rank at least as high as the
    vessel's `required_endorsement`, so a `MASTER_25T` holder asked to take out a hull
    requiring `MASTER_100T` is refused with `ERR_CREW_ENDORSEMENT_INSUFFICIENT`."
    PRD §3.3: "The **crew ceiling** is the full `seat_capacity` when the master's
    `endorsement_class` is `MASTER_100T`, and a flat 24 seats when it is
    `MASTER_25T`."

    Design: Corner/validations/master_holding_only_a_25_ton_endorsement_cannot_take_a_100_ton_vessel
    """
    world = setup_harbor_world(vessel={"required_endorsement": "MASTER_100T"},
                               crew={"endorsement_class": "MASTER_25T"})
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_CREW_ENDORSEMENT_INSUFFICIENT.value, 422)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["effective_capacity"] == 24, (
        f"A MASTER_25T master caps the sailing at 24 seats, got "
        f"{refreshed['effective_capacity']}"
    )


def test_harbor_class_hull_may_not_sail_under_restricted_posture(api):
    """PRD §2.8: "**Hull class.** Under `RESTRICTED` posture only an `OFFSHORE` hull
    may sail — otherwise `ERR_HULL_CLASS_RESTRICTED` (422)."
    PRD §3.7: "Under `RESTRICTED` posture only an `OFFSHORE` `hull_class` may sail, a
    `HARBOR` hull being turned back with `ERR_HULL_CLASS_RESTRICTED`."

    Design: Corner/validations/harbor_class_hull_may_not_sail_under_restricted_posture
    """
    world = setup_harbor_world(
        vessel={"hull_class": "HARBOR"},
        service_day={"service_date": "2026-09-12", "wind_knots": 24.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
    )
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_HULL_CLASS_RESTRICTED.value, 422)

    assert world["day"]["posture"] == "RESTRICTED"
    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["effective_capacity"] == 28, (
        f"70 percent of 40 seats is 28, got {refreshed['effective_capacity']}"
    )


def test_three_open_deficiencies_block_a_restricted_day_departure(api):
    """PRD §3.7: "The vessel must have a latest `ANNUAL` inspection whose `result` is
    `PASS` or `PASS_WITH_DEFICIENCIES` and whose `expires_on` is not earlier than the
    logical clock's calendar date — an `expires_on` falling exactly on today is still
    valid — and when the day's posture is `RESTRICTED` that inspection must
    additionally carry a `deficiency_count` of no more than 2; any failure here is
    `ERR_VESSEL_INSPECTION_INVALID`."

    Design: Corner/validations/three_open_deficiencies_block_departure_only_while_posture_is_restricted
    """
    world = setup_harbor_world(
        inspection={"result": "PASS_WITH_DEFICIENCIES", "deficiency_count": 3},
        service_day={"service_date": "2026-09-12", "wind_knots": 24.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
    )
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_VESSEL_INSPECTION_INVALID.value, 422)

    assert world["day"]["posture"] == "RESTRICTED"
    vessel = validate_success(api.get_vessel(world["vessel_id"], DISPATCHER))
    assert vessel["service_state"] == "IN_SERVICE", (
        f"Deficiencies do not change service_state, got {vessel['service_state']}"
    )
    assert validate_success(
        api.get_trip(trip["id"], DISPATCHER)
    )["operational_status"] == "BOARDING"


def test_hull_inside_its_winter_layup_window_may_not_sail(api):
    """PRD §3.1: "The layup edges are driven by the clock rather than by any
    inspection: advancing the logical clock into the inclusive window moves the vessel
    `IN_SERVICE → LAID_UP` (provided the latest annual inspection is not a `FAIL`),
    from which point departure attempts are rejected with `ERR_VESSEL_IN_LAYUP`;
    advancing the clock past `layup_end_date`, or back before `layup_start_date`,
    moves it `LAID_UP → IN_SERVICE` and the vessel becomes departable again."
    PRD §3.7: "The vessel's derived `service_state` must be `IN_SERVICE`: a `LAID_UP`
    hull is rejected with `ERR_VESSEL_IN_LAYUP` and an `OUT_OF_SERVICE` hull with
    `ERR_VESSEL_OUT_OF_SERVICE`."

    Design: Corner/validations/departure_while_the_clock_sits_inside_the_winter_layup_window_is_rejected
    """
    world = setup_harbor_world(vessel={"layup_start_date": "2026-09-20",
                                       "layup_end_date": "2027-03-31"})
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    set_clock("2026-09-21T10:00:00Z")

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_VESSEL_IN_LAYUP.value, 409)

    vessel = validate_success(api.get_vessel(world["vessel_id"], DISPATCHER))
    assert vessel["service_state"] == "LAID_UP", (
        f"The clock sits inside the inclusive layup window, got "
        f"{vessel['service_state']}"
    )
    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["actual_departure_utc"] is None


def _clearance_boundary_world():
    """Two operating days a centimetre apart: one at exactly 0.30 m of clearance and
    one just below it, each carrying a boarded sailing."""
    world = setup_harbor_world(
        vessel={"name": "Harrier", "draft_m": 1.25},
        service_day={"service_date": "2026-09-15", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 1.55},
        clock=None,
    )
    shallow_day = add_service_day(service_date="2026-09-16", wind_knots=10.0,
                                  wave_height_m=0.30, low_water_m=1.54)
    set_clock("2026-09-15T09:00:00Z")
    ok_trip = create_trip(world, scheduled_departure_utc="2026-09-15T10:00:00Z",
                          scheduled_arrival_utc="2026-09-15T10:25:00Z")
    bad_trip = create_trip(world, service_day_id=shallow_day["id"],
                           scheduled_departure_utc="2026-09-16T10:00:00Z",
                           scheduled_arrival_utc="2026-09-16T10:25:00Z")
    board_trip(world, ok_trip["id"], [])
    board_trip(world, bad_trip["id"], [])
    return world, ok_trip, bad_trip


def test_clearance_of_exactly_thirty_centimetres_may_sail(api):
    """PRD §3.7: "Finally the under-keel clearance — the day's `low_water_m` less the
    vessel's `draft_m`, rounded half up to two decimals — must be at least 0.30
    metres, else `ERR_UNDER_KEEL_CLEARANCE`."
    PRD §3.3: "The **tide ceiling** depends on the under-keel clearance, which is the
    day's `low_water_m` minus the vessel's `draft_m`, rounded half up to two decimals;
    when that clearance is strictly below 0.60 metres the ceiling is `seat_capacity`
    divided by two and rounded down to a whole seat, and otherwise it is the full
    `seat_capacity`."

    Design: Difficulty/boundary_precision_check/under_keel_clearance_of_exactly_030_departs_while_029_is_rejected
    """
    world, ok_trip, _bad_trip = _clearance_boundary_world()

    departed = depart_trip(world, ok_trip["id"])

    assert departed["operational_status"] == "DEPARTED", (
        "A clearance of exactly 0.30 m satisfies the at-least rule"
    )
    assert departed["settlement_status"] == "PROVISIONAL"
    assert departed["effective_capacity"] == 20, (
        f"A 0.30 m clearance derates the 40-seat hull to 20, got "
        f"{departed['effective_capacity']}"
    )


def test_clearance_one_centimetre_short_is_rejected(api):
    """PRD §3.7: "Finally the under-keel clearance — the day's `low_water_m` less the
    vessel's `draft_m`, rounded half up to two decimals — must be at least 0.30
    metres, else `ERR_UNDER_KEEL_CLEARANCE`."
    PRD §2.8: "**Under-keel clearance.** The clearance is at least the safety minimum
    — otherwise `ERR_UNDER_KEEL_CLEARANCE` (422)."

    Design: Difficulty/boundary_precision_check/under_keel_clearance_of_exactly_030_departs_while_029_is_rejected
    """
    world, _ok_trip, bad_trip = _clearance_boundary_world()

    validate_error(api.depart_trip(bad_trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_UNDER_KEEL_CLEARANCE.value, 422)

    refreshed = validate_success(api.get_trip(bad_trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["settlement_status"] == "UNSETTLED"


def _failed_annual_world():
    """A boarded sailing whose hull has just failed its annual survey."""
    world = setup_harbor_world()
    trip = create_trip(world)
    board_trip(world, trip["id"], [])
    file_inspection(world["vessel_id"], inspection_type="ANNUAL", result="FAIL",
                    deficiency_count=7, performed_on="2026-09-12")
    set_clock("2026-09-12T13:50:00Z")
    return world, trip


def test_failed_annual_survey_puts_the_hull_out_of_service(api):
    """PRD §3.1: "Filing an `ANNUAL` inspection with `result` `FAIL` that becomes the
    latest annual row moves the vessel `IN_SERVICE → OUT_OF_SERVICE`, and every
    subsequent departure attempt on that hull is rejected with
    `ERR_VESSEL_OUT_OF_SERVICE`; the vessel's `version` increments by 1."
    PRD §3.1: "If that latest annual inspection exists and its `result` is `FAIL`, the
    vessel reads `OUT_OF_SERVICE`."

    Design: Difficulty/cross_entity_state_dependency/trip_departure_blocked_by_vessel_out_of_service_from_failed_annual_inspection
    """
    world, trip = _failed_annual_world()

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_VESSEL_OUT_OF_SERVICE.value, 409)

    vessel = validate_success(api.get_vessel(world["vessel_id"], DISPATCHER))
    assert vessel["service_state"] == "OUT_OF_SERVICE", (
        f"The newest ANNUAL row is a FAIL, got {vessel['service_state']}"
    )


def test_the_blocked_departure_leaves_both_trip_axes_untouched(api):
    """PRD §3.7: "The vessel's derived `service_state` must be `IN_SERVICE`: a
    `LAID_UP` hull is rejected with `ERR_VESSEL_IN_LAYUP` and an `OUT_OF_SERVICE` hull
    with `ERR_VESSEL_OUT_OF_SERVICE`."
    PRD §3.7: "A successful departure stamps `actual_departure_utc` from the logical
    clock, snapshots `booked_pax` from the trip's current `seats_committed` — this
    snapshot is the provisional passenger basis — and posts a provisional landing fee
    on every berth slot of the trip that is still `RESERVED`."

    Design: Difficulty/cross_entity_state_dependency/trip_departure_blocked_by_vessel_out_of_service_from_failed_annual_inspection
    """
    world, trip = _failed_annual_world()

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_VESSEL_OUT_OF_SERVICE.value, 409)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING"
    assert refreshed["settlement_status"] == "UNSETTLED"
    assert refreshed["actual_departure_utc"] is None


def _already_departed_on_a_shoaling_day():
    """A sailing that has already left, on a day since patched below the clearance
    minimum."""
    world = setup_harbor_world(
        vessel={"name": "Harrier", "draft_m": 1.25},
        service_day={"service_date": "2026-09-14", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-14T09:00:00Z",
    )
    trip = create_trip(world, scheduled_departure_utc="2026-09-14T10:00:00Z",
                       scheduled_arrival_utc="2026-09-14T10:25:00Z")
    board_trip(world, trip["id"], [])
    set_clock("2026-09-14T10:05:00Z")
    depart_trip(world, trip["id"])
    patch_service_day(world["day_id"], low_water_m=1.50)
    return world, trip


def test_state_rung_answers_before_the_clearance_rung(api):
    """PRD §2.8: "A trip that has already departed and is asked to depart again on a
    day whose under-keel clearance is below the safety minimum is rejected with
    `ERR_TRIP_NOT_BOARDING`, not `ERR_UNDER_KEEL_CLEARANCE`, because the state rung
    sits above the safety rungs."
    PRD §2.8: "When more than one rule would reject a request, exactly one error is
    returned, and it is always the one belonging to the lowest-numbered rung of the
    following ladder."

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_under_keel_safety_on_second_depart
    """
    world, trip = _already_departed_on_a_shoaling_day()

    error = validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                           ApiErrorId.ERR_TRIP_NOT_BOARDING.value, 409)

    assert error["error_id"] != ApiErrorId.ERR_UNDER_KEEL_CLEARANCE.value


def test_the_rejected_second_departure_changes_nothing(api):
    """PRD §2.8: "A trip that has already departed and is asked to depart again on a
    day whose under-keel clearance is below the safety minimum is rejected with
    `ERR_TRIP_NOT_BOARDING`, not `ERR_UNDER_KEEL_CLEARANCE`, because the state rung
    sits above the safety rungs."
    PRD §3.2: "Otherwise, if `low_water_m` is strictly below 1.80 metres, the day is
    `RESTRICTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_under_keel_safety_on_second_depart
    """
    world, trip = _already_departed_on_a_shoaling_day()

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_TRIP_NOT_BOARDING.value, 409)

    day = validate_success(api.get_service_day(world["day_id"], DISPATCHER))
    assert day["posture"] == "RESTRICTED"
    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "DEPARTED"
    assert refreshed["settlement_status"] == "PROVISIONAL"
