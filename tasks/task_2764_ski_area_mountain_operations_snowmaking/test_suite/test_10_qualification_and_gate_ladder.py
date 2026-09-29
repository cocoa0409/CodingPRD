"""Who is qualified to act, and which refusal the mountain reports when several
gates are violated at once.

Two families of rule live in this file. The first asks whether the person named
by a request carries the qualification the work demands: a lift may not spin
below its required operator count, a role slot on a lift is exclusive unless it
is the float, an explosive shot needs a blaster and a ski cut needs a partner,
and the medical certification floor guards mission sign-off and the dispatch of
a serious incident. The second family watches the opening decision refuse a
terrain area that violates three rules simultaneously, and confirms that each
cured gate hands the report to the next surviving violation.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BLASTER_CERT_REQUIRED,
    ERR_DAY_PLAN_NOT_PUBLISHED,
    ERR_LIFT_OPERATORS_INSUFFICIENT,
    ERR_LIFT_ROLE_SLOT_CONFLICT,
    ERR_OPERATOR_DOUBLE_BOOKED,
    ERR_PARK_NOT_INSPECTED,
    ERR_PARK_RISK_TOO_HIGH,
    ERR_PATROLLER_BUSY,
    ERR_PATROLLER_CERT_INSUFFICIENT,
    ERR_PATROLLER_NOT_ON_DUTY,
    ERR_SEASON_NOT_OPERATING,
    ERR_SERVING_LIFT_NOT_OPEN,
    ERR_SKI_CUT_PARTNER_REQUIRED,
    ERR_SOD_VIOLATION,
    ERR_TRANSPORT_MODE_NOT_ALLOWED,
    wins,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_integer,
    assert_one_decimal,
)
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    LIFT_OPS_HEADERS,
    make_patroller_headers,
)

# ─── The season, lift and area shape every recipe here reuses ─────────────────

SEASON_OVERRIDES: Dict[str, Any] = {
    "season_label": "2026-27",
    "base_depth_policy": "MEAN_OF_STAKES",
    "water_right_seasonal_af": 250.000,
    "plant_max_gpm": 6000,
    "snowmaking_kwh_per_af": 620.0,
    "min_patrollers_per_open_area": 2,
    "groom_freshness_hours": 18,
}

LIFT_OVERRIDES: Dict[str, Any] = {
    "lift_code": "L1",
    "name": "Summit Express",
    "lift_type": "DETACHABLE",
    "wind_hold_threshold_mph": 40.0,
    "hourly_capacity_pph": 1800,
    "required_operator_count": 2,
}

AREA_OVERRIDES: Dict[str, Any] = {
    "trail_code": "T1",
    "name": "Sunbowl",
    "terrain_class": "BLUE",
    "acres": 18.0,
    "min_open_base_depth_in": 30,
    "avalanche_terrain": False,
}

SHIFT_START = "2026-08-01T00:00:00Z"
SHIFT_END = "2026-08-01T16:00:00Z"

# A five-feature park scoring 34.0, and the same park with two halfpipes added
# so that the raw score reaches 70.0 and the exposure factor 1.2.
PARK_FEATURES_MODEST: List[Dict[str, str]] = [
    f.park_feature("JUMP", "L"),
    f.park_feature("JUMP", "M"),
    f.park_feature("RAIL", "M"),
    f.park_feature("RAIL", "S"),
    f.park_feature("JIB", "S"),
]

PARK_FEATURES_OVER_THE_CEILING: List[Dict[str, str]] = PARK_FEATURES_MODEST + [
    f.park_feature("HALFPIPE", "S"),
    f.park_feature("HALFPIPE", "L"),
]


def _season_with_inspected_lift(mountain) -> Dict[str, Any]:
    """A season and one registered lift carrying a passing inspection, with no
    operators assigned and the lift still CLOSED."""
    season = mountain.create_season(**SEASON_OVERRIDES)
    lift = mountain.create_lift(season["id"], **LIFT_OVERRIDES)
    mountain.inspect_lift(lift["id"], "PASS")
    return {"season_id": season["id"], "lift_id": lift["id"]}


def _avalanche_area_with_three_patrollers(mountain) -> Dict[str, Any]:
    """A season whose one avalanche-terrain area carries three on-duty
    patrollers: P1 (EMT, blaster), P2 (PARAMEDIC, blaster) and P3 (EMT, not a
    blaster). The area is left CLOSED, which is where mitigation belongs."""
    state = _season_with_inspected_lift(mountain)
    area = mountain.create_terrain_area(
        state["season_id"],
        state["lift_id"],
        **dict(AREA_OVERRIDES, avalanche_terrain=True),
    )
    roster = [
        ("P1", "EMT", True),
        ("P2", "PARAMEDIC", True),
        ("P3", "EMT", False),
    ]
    patrollers = [
        mountain.create_patroller(
            state["season_id"],
            patroller_code=code,
            cert_level=cert,
            blaster_certified=blaster,
            on_duty=True,
            assigned_terrain_area_id=area["id"],
        )
        for code, cert, blaster in roster
    ]
    state["area_id"] = area["id"]
    state["p1_id"] = patrollers[0]["id"]
    state["p2_id"] = patrollers[1]["id"]
    state["p3_id"] = patrollers[2]["id"]
    return state


def _published_day_over_a_standby_lift(mountain) -> Dict[str, Any]:
    """A published operating day whose single READY area is served by a lift on
    STANDBY carrying two named operator assignments, the first of which the
    caller can release by id."""
    state = _season_with_inspected_lift(mountain)
    top_op = mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-1",
        role_on_lift="TOP_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-2",
        role_on_lift="BOTTOM_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.set_lift_status(state["lift_id"], "STANDBY")
    area = mountain.create_terrain_area(
        state["season_id"], state["lift_id"], **AREA_OVERRIDES
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(area["id"], passes_completed=20)
    patrollers = mountain.staff_patrol(state["season_id"], area["id"], count=2)
    day_plan = mountain.create_day_plan(
        state["season_id"], operating_date="2026-08-01", parking_stalls_total=500
    )
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], wind_speed_mph=10.0, wet_bulb_f=22.0)
    state.update(
        {
            "area_id": area["id"],
            "day_plan_id": day_plan["id"],
            "top_op_assignment_id": top_op["id"],
            "patroller_ids": [row["id"] for row in patrollers],
        }
    )
    return state


def test_a_lift_whose_released_operator_leaves_it_short_handed_is_refused_open(
    api, mountain
):
    """Releasing one of two operators drops staffed_operator_count below the
    lift's required_operator_count, and the STANDBY to OPEN request is then
    refused for the staffing shortfall rather than for the transition itself.

    `STANDBY → OPEN` requires the same current inspection, requires `staffed_operator_count` to be at least `required_operator_count` — otherwise `ERR_LIFT_OPERATORS_INSUFFICIENT` — and requires that, where the season has an active day plan at all, that plan's `posture` is not `WEATHER_HOLD`.

    Design: Corner/validations/a_lift_cannot_open_below_its_required_operator_count
    """
    state = _published_day_over_a_standby_lift(mountain)
    lift_id = state["lift_id"]

    staffed = validate_success(api.get_lift(lift_id, LIFT_OPS_HEADERS))
    assert_integer(staffed["staffed_operator_count"], 2)
    assert staffed["service_status"] == "STANDBY"
    assert_integer(staffed["required_operator_count"], 2)

    released = validate_success(
        api.release_lift_staff_assignment(
            state["top_op_assignment_id"], LIFT_OPS_HEADERS
        )
    )
    assert released["state"] == "RELEASED"
    assert_instant_equals(released["released_at"], INITIAL_CLOCK)

    short_handed = validate_success(api.get_lift(lift_id, LIFT_OPS_HEADERS))
    assert_integer(short_handed["staffed_operator_count"], 1)
    assert short_handed["service_status"] == "STANDBY", (
        "the release only recomputes coverage; a STANDBY lift does not move"
    )

    refused = api.set_lift_service_status(
        lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
    )
    validate_error(refused, ERR_LIFT_OPERATORS_INSUFFICIENT, expected_status=422)

    restaffed = validate_success(
        api.create_lift_staff_assignment(
            f.staff_assignment_payload(
                lift_id,
                operator_code="OP-3",
                role_on_lift="TOP_OP",
                shift_start=SHIFT_START,
                shift_end=SHIFT_END,
            ),
            LIFT_OPS_HEADERS,
        ),
        expected_status=201,
    )
    assert restaffed["role_on_lift"] == "TOP_OP", (
        "the released row freed the slot, so the vacated role can be filled again"
    )

    opened = validate_success(
        api.set_lift_service_status(
            lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert opened["service_status"] == "OPEN"
    assert_integer(opened["staffed_operator_count"], 2)

    rows, meta = validate_paginated(
        api.list_lift_staff_assignments(lift_id, LIFT_OPS_HEADERS, state="ASSIGNED")
    )
    assert len(rows) == 2, (
        f"Expected two covering assignments after the swap, got {len(rows)}"
    )
    assert_integer(meta["total_count"], 2)
    assert sorted(row["operator_code"] for row in rows) == ["OP-2", "OP-3"]


def test_a_lift_role_slot_is_exclusive_unless_the_role_is_the_liftie_float(
    api, mountain
):
    """A second assignment into an occupied TOP_OP or MID_LOAD slot is refused,
    while a second LIFTIE_FLOAT on the same lift over the same shift window is
    accepted, and only the accepted rows count towards coverage.

    One lift may hold at most one `ASSIGNED` assignment per `role_on_lift`, with the deliberate exception of `LIFTIE_FLOAT`, which may repeat freely; a second assignment for an already-filled non-float slot is refused with `ERR_LIFT_ROLE_SLOT_CONFLICT`.

    Design: Corner/validations/role_slots_are_exclusive_for_every_role_except_liftie_float
    """
    state = _season_with_inspected_lift(mountain)
    lift_id = state["lift_id"]
    mountain.assign_operator(
        lift_id,
        operator_code="OP-1",
        role_on_lift="TOP_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.assign_operator(
        lift_id,
        operator_code="OP-2",
        role_on_lift="BOTTOM_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )

    def attempt(operator_code: str, role_on_lift: str):
        return api.create_lift_staff_assignment(
            f.staff_assignment_payload(
                lift_id,
                operator_code=operator_code,
                role_on_lift=role_on_lift,
                shift_start=SHIFT_START,
                shift_end=SHIFT_END,
            ),
            LIFT_OPS_HEADERS,
        )

    # Every operator code below is fresh, so the turnaround rule cannot stand in
    # for the slot rule.
    assert wins(ERR_LIFT_ROLE_SLOT_CONFLICT, ERR_OPERATOR_DOUBLE_BOOKED)

    validate_error(
        attempt("OP-9", "TOP_OP"), ERR_LIFT_ROLE_SLOT_CONFLICT, expected_status=409
    )

    first_float = validate_success(attempt("OP-9", "LIFTIE_FLOAT"), expected_status=201)
    assert first_float["role_on_lift"] == "LIFTIE_FLOAT"
    assert first_float["state"] == "ASSIGNED"
    assert first_float["released_at"] is None

    second_float = validate_success(
        attempt("OP-10", "LIFTIE_FLOAT"), expected_status=201
    )
    assert second_float["role_on_lift"] == "LIFTIE_FLOAT", (
        "the float role repeats freely on one lift"
    )

    first_mid = validate_success(attempt("OP-11", "MID_LOAD"), expected_status=201)
    assert first_mid["role_on_lift"] == "MID_LOAD"

    validate_error(
        attempt("OP-12", "MID_LOAD"), ERR_LIFT_ROLE_SLOT_CONFLICT, expected_status=409
    )

    lift = validate_success(api.get_lift(lift_id, LIFT_OPS_HEADERS))
    assert_integer(lift["staffed_operator_count"], 5)


def test_an_explosive_mission_may_only_be_thrown_by_a_blaster_certified_patroller(
    api, mountain
):
    """An acting patroller who is on duty but not blaster certified is refused
    an explosive shot, while a blaster executes the same mission and closes the
    access road for twenty minutes per charge used.

    The method dictates the qualification: an `EXPLOSIVE` or `GAS_EXPLODER` mission demands that the acting patroller carry `blaster_certified` true, refused otherwise with `ERR_BLASTER_CERT_REQUIRED`; a `SKI_CUT` mission demands a partner, meaning at least one *other* patroller of the same season who is on duty and whose `status` is `AVAILABLE` at the moment of execution, refused otherwise with `ERR_SKI_CUT_PARTNER_REQUIRED`.

    Design: Corner/validations/explosive_missions_need_a_blaster_and_ski_cuts_need_an_available_partner
    """
    state = _avalanche_area_with_three_patrollers(mountain)
    mission = mountain.plan_mission(
        state["area_id"],
        route_code="AV-1",
        method="EXPLOSIVE",
        hazard_rating_pre="CONSIDERABLE",
        planned_charges=2,
    )

    not_a_blaster = validate_success(
        api.get_patroller(state["p3_id"], DIRECTOR_HEADERS)
    )
    assert not_a_blaster["on_duty"] is True, (
        "the duty gate must pass so the qualification gate is what reports"
    )
    assert not_a_blaster["blaster_certified"] is False
    assert wins(ERR_PATROLLER_NOT_ON_DUTY, ERR_BLASTER_CERT_REQUIRED)

    refused = api.execute_mission(
        mission["id"],
        f.mission_execute_payload(2),
        make_patroller_headers(state["p3_id"]),
    )
    validate_error(refused, ERR_BLASTER_CERT_REQUIRED, expected_status=422)

    executed = validate_success(
        api.execute_mission(
            mission["id"],
            f.mission_execute_payload(2),
            make_patroller_headers(state["p1_id"]),
        )
    )
    assert executed["state"] == "EXECUTED"
    assert executed["executed_by_patroller_id"] == state["p1_id"]
    assert_integer(executed["charges_used"], 2)
    assert_integer(executed["road_closure_minutes"], 40)
    assert_integer(executed["clearance_valid_hours"], 24)
    assert_instant_equals(executed["executed_at"], INITIAL_CLOCK)


def test_a_ski_cut_needs_another_available_patroller_and_the_actor_is_not_his_own_partner(
    api, mountain
):
    """With both peers off duty the only on-duty patroller cannot ski cut alone,
    and restoring exactly one peer to duty is enough to let the same request
    through.

    The method dictates the qualification: an `EXPLOSIVE` or `GAS_EXPLODER` mission demands that the acting patroller carry `blaster_certified` true, refused otherwise with `ERR_BLASTER_CERT_REQUIRED`; a `SKI_CUT` mission demands a partner, meaning at least one *other* patroller of the same season who is on duty and whose `status` is `AVAILABLE` at the moment of execution, refused otherwise with `ERR_SKI_CUT_PARTNER_REQUIRED`.

    Design: Corner/validations/explosive_missions_need_a_blaster_and_ski_cuts_need_an_available_partner
    """
    state = _avalanche_area_with_three_patrollers(mountain)
    mission = mountain.plan_mission(
        state["area_id"],
        route_code="AV-2",
        method="SKI_CUT",
        hazard_rating_pre="CONSIDERABLE",
        planned_charges=0,
    )
    mountain.set_duty(state["p2_id"], False)
    mountain.set_duty(state["p3_id"], False)

    actor = validate_success(api.get_patroller(state["p1_id"], DIRECTOR_HEADERS))
    assert actor["on_duty"] is True
    assert actor["status"] == "AVAILABLE", (
        "the acting patroller is available, and still may not partner himself"
    )

    refused = api.execute_mission(
        mission["id"],
        f.mission_execute_payload(0),
        make_patroller_headers(state["p1_id"]),
    )
    validate_error(refused, ERR_SKI_CUT_PARTNER_REQUIRED, expected_status=422)

    untouched = validate_success(api.get_mission(mission["id"], DIRECTOR_HEADERS))
    assert untouched["state"] == "PLANNED"
    assert untouched["executed_at"] is None
    assert untouched["executed_by_patroller_id"] is None

    mountain.set_duty(state["p2_id"], True)
    executed = validate_success(
        api.execute_mission(
            mission["id"],
            f.mission_execute_payload(0),
            make_patroller_headers(state["p1_id"]),
        )
    )
    assert executed["state"] == "EXECUTED"
    assert executed["executed_by_patroller_id"] == state["p1_id"]


def _avalanche_area_with_a_basic_patroller(mountain) -> Dict[str, Any]:
    """A season whose one avalanche-terrain area carries three on-duty
    patrollers: P1 (EMT), P2 (PARAMEDIC) and P4 (BASIC), the last of whom sits
    below the medical certification floor."""
    state = _season_with_inspected_lift(mountain)
    area = mountain.create_terrain_area(
        state["season_id"],
        state["lift_id"],
        **dict(AREA_OVERRIDES, avalanche_terrain=True),
    )
    roster = [("P1", "EMT"), ("P2", "PARAMEDIC"), ("P4", "BASIC")]
    patrollers = [
        mountain.create_patroller(
            state["season_id"],
            patroller_code=code,
            cert_level=cert,
            blaster_certified=True,
            on_duty=True,
            assigned_terrain_area_id=area["id"],
        )
        for code, cert in roster
    ]
    state["area_id"] = area["id"]
    state["p1_id"] = patrollers[0]["id"]
    state["p2_id"] = patrollers[1]["id"]
    state["p4_id"] = patrollers[2]["id"]
    return state


def test_signing_off_a_mitigation_mission_always_demands_the_medical_floor(
    api, mountain
):
    """A BASIC patroller who did not execute the mission is still refused the
    sign-off, and a PARAMEDIC clears the same mission.

    The clearing `Patroller` must not be the patroller who executed it — a matching `X-User-ID` is refused with `ERR_SOD_VIOLATION` — must be on duty, and must carry a `cert_level` of `EMT` or `PARAMEDIC`, with `BASIC` and `OEC` refused as `ERR_PATROLLER_CERT_INSUFFICIENT`.

    Design: Corner/validations/the_certification_floor_guards_both_mission_clearance_and_serious_incident_dispatch
    """
    state = _avalanche_area_with_a_basic_patroller(mountain)
    mission = mountain.plan_mission(
        state["area_id"],
        route_code="AV-1",
        method="SKI_CUT",
        hazard_rating_pre="CONSIDERABLE",
        planned_charges=0,
    )
    executed = mountain.execute_mission(mission["id"], state["p1_id"], charges_used=0)
    assert executed["executed_by_patroller_id"] == state["p1_id"], (
        "P4 is not the executor, so segregation of duties cannot be what reports"
    )
    assert wins(ERR_SOD_VIOLATION, ERR_PATROLLER_CERT_INSUFFICIENT)

    refused = api.clear_mission(
        mission["id"],
        f.mission_clear_payload("LOW"),
        make_patroller_headers(state["p4_id"]),
    )
    validate_error(refused, ERR_PATROLLER_CERT_INSUFFICIENT, expected_status=422)

    cleared = validate_success(
        api.clear_mission(
            mission["id"],
            f.mission_clear_payload("LOW"),
            make_patroller_headers(state["p2_id"]),
        )
    )
    assert cleared["state"] == "CLEARED"
    assert cleared["cleared_by_patroller_id"] == state["p2_id"]


def test_the_medical_floor_guards_a_serious_dispatch_but_not_a_minor_one(api, mountain):
    """A BASIC patroller is refused as the responder to a SERIOUS incident and
    accepted as the responder to a MINOR one, so the certification floor is
    conditional on the triage severity rather than absolute.

    Three conditions guard it, and their relative order matters when a nomination fails more than one: the nominated patroller must be on duty (`ERR_PATROLLER_NOT_ON_DUTY`), then a `SERIOUS` or `CRITICAL` incident additionally requires that patroller's `cert_level` to be `EMT` or `PARAMEDIC` (`ERR_PATROLLER_CERT_INSUFFICIENT`), and only then is the patroller's availability tested — a patroller already `ON_INCIDENT` cannot be dispatched again and the request is refused with `ERR_PATROLLER_BUSY`.

    Design: Corner/validations/the_certification_floor_guards_both_mission_clearance_and_serious_incident_dispatch
    """
    state = _avalanche_area_with_a_basic_patroller(mountain)
    serious = mountain.report_incident(
        state["area_id"],
        reporter_code="LIFTIE-3",
        severity="SERIOUS",
        location_note="skier left of tower 7",
    )

    refused = api.dispatch_incident(
        serious["id"], f.incident_dispatch_payload(state["p4_id"]), DIRECTOR_HEADERS
    )
    validate_error(refused, ERR_PATROLLER_CERT_INSUFFICIENT, expected_status=422)

    still_free = validate_success(api.get_patroller(state["p4_id"], DIRECTOR_HEADERS))
    assert still_free["status"] == "AVAILABLE", (
        "the refused nomination must not consume the patroller"
    )
    assert wins(ERR_PATROLLER_CERT_INSUFFICIENT, ERR_PATROLLER_BUSY)

    dispatched = validate_success(
        api.dispatch_incident(
            serious["id"], f.incident_dispatch_payload(state["p1_id"]), DIRECTOR_HEADERS
        )
    )
    assert dispatched["state"] == "DISPATCHED"
    assert dispatched["responder_patroller_id"] == state["p1_id"]
    assert_integer(dispatched["response_minutes"], 0)
    responder = validate_success(api.get_patroller(state["p1_id"], DIRECTOR_HEADERS))
    assert responder["status"] == "ON_INCIDENT"

    minor = mountain.report_incident(
        state["area_id"],
        reporter_code="LIFTIE-3",
        severity="MINOR",
        location_note="skier left of tower 7",
    )
    accepted = validate_success(
        api.dispatch_incident(
            minor["id"], f.incident_dispatch_payload(state["p4_id"]), DIRECTOR_HEADERS
        )
    )
    assert accepted["state"] == "DISPATCHED"
    assert accepted["responder_patroller_id"] == state["p4_id"]


def _open_mountain_with_a_dispatched_incident(
    mountain, severity: str, responder_index: int
) -> Dict[str, Any]:
    """An open mountain carrying one incident of the given severity with a
    patroller already dispatched to it."""
    state = mountain.open_mountain(
        season_overrides=dict(SEASON_OVERRIDES),
        lift_overrides=dict(LIFT_OVERRIDES),
        area_overrides=dict(AREA_OVERRIDES),
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        passes_completed=20,
        patroller_count=2,
    )
    assert state["area"]["opening_state"] == "OPEN", (
        f"Setup expected an open area, got {state['area']['opening_state']}"
    )
    incident = mountain.report_incident(
        state["area_id"],
        reporter_code="LIFTIE-3",
        severity=severity,
        location_note="skier left of tower 7",
    )
    responder_id = state["patroller_ids"][responder_index]
    mountain.dispatch_incident(incident["id"], responder_id)
    state["incident_id"] = incident["id"]
    state["responder_id"] = responder_id
    return state


def test_a_serious_incident_may_be_taken_by_ambulance_but_not_by_helicopter(
    api, mountain
):
    """The helicopter is reserved for a CRITICAL triage, so a SERIOUS incident
    is refused it while the ambulance the same incident does qualify for is
    ordered.

    The order names a `transport_mode` of `TOBOGGAN`, `SNOWMOBILE`, `AMBULANCE` or `HELICOPTER`, and the mode is gated by triage severity — `HELICOPTER` is permitted only when `severity` is `CRITICAL`, and `AMBULANCE` only when `severity` is `SERIOUS` or `CRITICAL`, with any other combination refused as `ERR_TRANSPORT_MODE_NOT_ALLOWED`.

    Design: Corner/validations/transport_modes_are_gated_by_incident_severity_in_two_tiers
    """
    state = _open_mountain_with_a_dispatched_incident(mountain, "SERIOUS", 0)
    responder_headers = make_patroller_headers(state["responder_id"])

    refused = api.order_incident_transport(
        state["incident_id"],
        f.incident_transport_payload("HELICOPTER"),
        responder_headers,
    )
    validate_error(refused, ERR_TRANSPORT_MODE_NOT_ALLOWED, expected_status=422)

    untouched = validate_success(
        api.get_incident(state["incident_id"], DIRECTOR_HEADERS)
    )
    assert untouched["state"] == "DISPATCHED"
    assert untouched["transport_mode"] is None
    assert untouched["transport_ordered_at"] is None

    ordered = validate_success(
        api.order_incident_transport(
            state["incident_id"],
            f.incident_transport_payload("AMBULANCE"),
            responder_headers,
        )
    )
    assert ordered["state"] == "TRANSPORT_ORDERED"
    assert ordered["transport_mode"] == "AMBULANCE"
    assert_instant_equals(ordered["transport_ordered_at"], INITIAL_CLOCK)


def test_a_minor_incident_is_refused_an_ambulance_and_rides_the_toboggan(api, mountain):
    """The ambulance needs a SERIOUS or CRITICAL triage, so a MINOR incident is
    refused it, while the unrestricted toboggan is available at any severity.

    The order names a `transport_mode` of `TOBOGGAN`, `SNOWMOBILE`, `AMBULANCE` or `HELICOPTER`, and the mode is gated by triage severity — `HELICOPTER` is permitted only when `severity` is `CRITICAL`, and `AMBULANCE` only when `severity` is `SERIOUS` or `CRITICAL`, with any other combination refused as `ERR_TRANSPORT_MODE_NOT_ALLOWED`.

    Design: Corner/validations/transport_modes_are_gated_by_incident_severity_in_two_tiers
    """
    state = _open_mountain_with_a_dispatched_incident(mountain, "MINOR", 1)
    responder_headers = make_patroller_headers(state["responder_id"])

    refused = api.order_incident_transport(
        state["incident_id"],
        f.incident_transport_payload("AMBULANCE"),
        responder_headers,
    )
    validate_error(refused, ERR_TRANSPORT_MODE_NOT_ALLOWED, expected_status=422)

    ordered = validate_success(
        api.order_incident_transport(
            state["incident_id"],
            f.incident_transport_payload("TOBOGGAN"),
            responder_headers,
        )
    )
    assert ordered["state"] == "TRANSPORT_ORDERED"
    assert ordered["transport_mode"] == "TOBOGGAN"


def _draft_day_over_a_standby_lift(mountain) -> Dict[str, Any]:
    """A PRESEASON season whose day plan is still DRAFT, whose single area has
    cleared every readiness gate on itself, and whose serving lift sits on
    STANDBY with a current inspection and two covering operators."""
    state = _season_with_inspected_lift(mountain)
    mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-1",
        role_on_lift="TOP_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-2",
        role_on_lift="BOTTOM_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.set_lift_status(state["lift_id"], "STANDBY")
    area = mountain.create_terrain_area(
        state["season_id"], state["lift_id"], **AREA_OVERRIDES
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(area["id"], passes_completed=20)
    mountain.staff_patrol(state["season_id"], area["id"], count=2)
    day_plan = mountain.create_day_plan(
        state["season_id"], operating_date="2026-08-01", parking_stalls_total=500
    )
    state["area_id"] = area["id"]
    state["day_plan_id"] = day_plan["id"]
    return state


def test_the_opening_decision_reports_the_season_gate_before_the_lift_gate(
    api, mountain
):
    """An opening decision that violates the season state, the publication state
    and the serving lift state at once reports only the season state, and each
    cured gate hands the report to the next surviving violation.

    Because a single request can violate several rules at once, the order in which checks run is part of the contract: the **first** failing check decides the response, and later checks are never reported.

    Design: Corner/validations/the_gate_ladder_reports_the_season_state_before_the_publish_state_and_the_lift_state
    """
    state = _draft_day_over_a_standby_lift(mountain)
    assert wins(ERR_SEASON_NOT_OPERATING, ERR_DAY_PLAN_NOT_PUBLISHED)
    assert wins(ERR_DAY_PLAN_NOT_PUBLISHED, ERR_SERVING_LIFT_NOT_OPEN)

    refused = api.decide_opening(
        state["area_id"], f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(refused, ERR_SEASON_NOT_OPERATING, expected_status=409)

    preseason = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    assert preseason["season_state"] == "PRESEASON"
    assert_integer(preseason["open_area_count"], 0)

    published = validate_success(
        api.publish_day_plan(state["day_plan_id"], DIRECTOR_HEADERS)
    )
    assert published["posture"] == "PUBLISHED_PARTIAL"
    promoted = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    assert promoted["season_state"] == "OPERATING", (
        "the first publish is what promotes the season, curing two gates at once"
    )

    lift_refusal = api.decide_opening(
        state["area_id"], f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(lift_refusal, ERR_SERVING_LIFT_NOT_OPEN, expected_status=422)

    spinning = validate_success(
        api.set_lift_service_status(
            state["lift_id"], f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert spinning["service_status"] == "OPEN"

    opened = validate_success(
        api.decide_opening(
            state["area_id"], f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert opened["opening_state"] == "OPEN"
    full = validate_success(api.get_day_plan(state["day_plan_id"], DIRECTOR_HEADERS))
    assert full["posture"] == "PUBLISHED_FULL", (
        "the season's only area is open, so everything that could be open is open"
    )


def _open_park_area(mountain) -> Dict[str, Any]:
    """A PARK class area standing OPEN on a published day: a five-feature park
    scoring 34.0, built by the grooming lead and inspected by P1, served by a
    lift that is OPEN with two operators and a current inspection."""
    state = _season_with_inspected_lift(mountain)
    mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-1",
        role_on_lift="TOP_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.assign_operator(
        state["lift_id"],
        operator_code="OP-2",
        role_on_lift="BOTTOM_OP",
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
    )
    mountain.set_lift_status(state["lift_id"], "STANDBY")
    area = mountain.create_terrain_area(
        state["season_id"],
        state["lift_id"],
        **dict(
            AREA_OVERRIDES,
            trail_code="TP",
            name="Main Park",
            terrain_class="PARK",
        ),
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(area["id"], passes_completed=20)
    patrollers = mountain.staff_patrol(state["season_id"], area["id"], count=2)
    mountain.build_park(area["id"], features=PARK_FEATURES_MODEST)
    mountain.inspect_park(area["id"], patrollers[0]["id"])
    day_plan = mountain.create_day_plan(
        state["season_id"], operating_date="2026-08-01", parking_stalls_total=500
    )
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], wind_speed_mph=10.0, wet_bulb_f=22.0)
    mountain.set_lift_status(state["lift_id"], "OPEN")
    opened = mountain.decide_opening(area["id"], "OPEN")
    assert opened["opening_state"] == "OPEN", (
        f"Setup expected an open park, got {opened['opening_state']}"
    )
    state["area_id"] = area["id"]
    state["day_plan_id"] = day_plan["id"]
    state["inspector_id"] = patrollers[0]["id"]
    return state


def test_tearing_down_a_park_holds_the_terrain_and_re_arms_the_inspection_gate(
    api, mountain
):
    """An empty feature list submitted against an inspected park closes it,
    drops the open park area onto a patrol hold, clears the inspector, and the
    area can no longer be reopened until it is walked again.

    Submitting an **empty** `features` array from `PARK_INSPECTED` is how a park is torn down: `park_state` moves `PARK_INSPECTED → PARK_CLOSED`, `park_feature_count` returns to 0, `park_risk_score` returns to 0.0, `park_inspected_by_user_id` is nulled, and if the area was `OPEN` with `terrain_class` `PARK` it is pushed onto `PATROL_HOLD`.

    Design: Corner/validations/the_park_gates_are_re_armed_by_every_rebuild_and_evaluated_in_priority_order
    """
    state = _open_park_area(mountain)

    torn_down = validate_success(
        api.build_park(state["area_id"], f.park_build_payload([]), GROOMING_HEADERS)
    )
    assert torn_down["park_state"] == "PARK_CLOSED"
    assert_integer(torn_down["park_feature_count"], 0)
    assert_one_decimal(torn_down["park_risk_score"], 0.0)
    assert torn_down["park_inspected_by_user_id"] is None

    held = validate_success(api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS))
    assert held["opening_state"] == "PATROL_HOLD"

    refused = api.decide_opening(
        state["area_id"], f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(refused, ERR_PARK_NOT_INSPECTED, expected_status=422)

    after = validate_success(api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS))
    assert after["opening_state"] == "PATROL_HOLD", (
        "the refused decision ran no part of the opening cascade"
    )


def test_a_rebuilt_park_reports_the_inspection_gate_before_the_risk_ceiling(
    api, mountain
):
    """A park rebuilt over the risk ceiling violates both park gates at once and
    reports the inspection first; once walked it reports the ceiling, and only a
    park back under the ceiling reopens the terrain.

    Only an inspected park whose `park_risk_score` is at or below 60.0 may be opened; a park-class area opened before inspection is refused with `ERR_PARK_NOT_INSPECTED`, and one whose score exceeds the ceiling with `ERR_PARK_RISK_TOO_HIGH`.

    Design: Corner/validations/the_park_gates_are_re_armed_by_every_rebuild_and_evaluated_in_priority_order
    """
    state = _open_park_area(mountain)
    area_id = state["area_id"]
    mountain.build_park(area_id, features=[])
    assert wins(ERR_PARK_NOT_INSPECTED, ERR_PARK_RISK_TOO_HIGH)

    rebuilt = validate_success(
        api.build_park(
            area_id,
            f.park_build_payload(PARK_FEATURES_OVER_THE_CEILING),
            GROOMING_HEADERS,
        )
    )
    assert rebuilt["park_state"] == "PARK_BUILT"
    assert_integer(rebuilt["park_feature_count"], 7)
    assert_one_decimal(rebuilt["park_risk_score"], 84.0)
    assert rebuilt["park_inspected_by_user_id"] is None

    both_violated = api.decide_opening(
        area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(both_violated, ERR_PARK_NOT_INSPECTED, expected_status=422)

    walked = validate_success(
        api.inspect_park(
            area_id,
            f.park_inspection_payload(),
            make_patroller_headers(state["inspector_id"]),
        )
    )
    assert walked["park_state"] == "PARK_INSPECTED"
    assert walked["opening_state"] == "PATROL_HOLD", (
        "signing off a park never reopens terrain by itself"
    )

    too_risky = api.decide_opening(
        area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(too_risky, ERR_PARK_RISK_TOO_HIGH, expected_status=422)

    mountain.build_park(area_id, features=[])
    mountain.build_park(area_id, features=PARK_FEATURES_MODEST)
    back_under = mountain.inspect_park(area_id, state["inspector_id"])
    assert_one_decimal(back_under["park_risk_score"], 34.0)
    assert back_under["park_state"] == "PARK_INSPECTED"

    opened = validate_success(
        api.decide_opening(area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS)
    )
    assert opened["opening_state"] == "OPEN"
