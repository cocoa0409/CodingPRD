"""Which of the six mountain roles may issue which operation.

Every request to the mountain operations service carries a declared role, and
the service decides on the role header alone — before any readiness gate, any
workflow gate and any version guard — whether the caller may perform the act at
all. The behaviours grouped here walk the permission map one endpoint family at
a time: the opening decision that only the mountain operations director may
issue, the pump house that two roles may build but only the snowmaking
supervisor may run, the incident that four roles may report but only the
director may dispatch, the terrain park that a grooming lead may build and only
a patroller other than its builder may sign off, the weather observation two
roles share while publication and the close of day stay with the director, and
the guest admission whose writes belong to the guest services desk while its
reads are open to everybody.

Each behaviour is built so the disputed request is sound in every respect other
than the role that sends it: the same payload from the permitted role succeeds
immediately afterwards, which is what makes each refusal attributable to
authorisation rather than to the state of the mountain.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_SOD_VIOLATION, ERR_UNAUTHORIZED
from test_helpers.assertions import (
    assert_instant_equals,
    assert_integer,
    assert_one_decimal,
    assert_version_unchanged,
    assert_water_af,
    ids_of,
)
from test_helpers.constants import (
    ALL_ROLES,
    INITIAL_CLOCK,
    ROLE_DIRECTOR,
    ROLE_GROOMING,
    ROLE_GUEST_SERVICES,
    ROLE_LIFT_OPS,
    ROLE_PATROLLER,
    ROLE_SNOWMAKING,
)
from test_helpers.factories import (
    close_day_payload,
    incident_dispatch_payload,
    incident_payload,
    opening_decision_payload,
    park_build_payload,
    park_feature,
    park_inspection_payload,
    pump_house_payload,
    pump_house_status_payload,
    reservation_payload,
    session_payload,
    weather_payload,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
    headers_for_role,
    make_patroller_headers,
)

# ─── The opening decision under dispute ───────────────
OPENING_NOTE = "first tracks"

# ─── The pump house the director provisions ───────────
PUMP_HOUSE_CODE = "PH1"
PUMP_HOUSE_NAME = "Base Pumphouse"
ROGUE_PUMP_HOUSE_CODE = "PH9"
ROGUE_PUMP_HOUSE_NAME = "Rogue Pumphouse"
SESSION_WINDOW_START = "2026-08-01T05:00:00Z"
SESSION_WINDOW_END = "2026-08-01T12:00:00Z"
SESSION_GUN_COUNT = 30
SESSION_GPM = 1200
SESSION_WATER_AF_RESERVED = 1.547

# ─── The incident every role tries to touch ───────────
REPORTER_CODE = "LIFTIE-3"
LOCATION_NOTE = "skier left of tower 7"
REPORTING_ROLES = (
    ROLE_PATROLLER,
    ROLE_GUEST_SERVICES,
    ROLE_LIFT_OPS,
    ROLE_DIRECTOR,
)
REPORTED_SEVERITIES = ("MINOR", "MODERATE", "SERIOUS", "MINOR")
SHARED_REPORT_COUNT = 4

# ─── The terrain park and its sign-off ────────────────
PARK_TRAIL_CODE = "TP"
PARK_NAME = "Main Park"
PARK_FEATURES = (
    park_feature("JUMP", "L"),
    park_feature("JUMP", "M"),
    park_feature("RAIL", "M"),
    park_feature("RAIL", "S"),
    park_feature("JIB", "S"),
)
PARK_FEATURE_COUNT = 5
PARK_RISK_SCORE = 34.0
INSPECTION_NOTE = "features walked, takeoffs firm"

# ─── The weather the two roles post ───────────────────
LIFT_OPS_WIND_MPH = 18.0
LIFT_OPS_WET_BULB_F = 21.0
DIRECTOR_WIND_MPH = 12.0
DIRECTOR_WET_BULB_F = 20.0
REFUSED_WIND_MPH = 30.0
REFUSED_WET_BULB_F = 30.0

# ─── The party the guest services desk admits ─────────
PARTY_CODE = "G1"
PARTY_PASS_TYPE = "DAY_TICKET"
PARTY_SIZE = 10
PARTY_VEHICLE_COUNT = 3
PARTY_ALLOCATED_STALLS = 3
CONFIRMED_ROW_COUNT = 1


def headers_of(role: str, patroller_id: str):
    """The ready-made header set for one role, resolving the patrol role onto a
    real patroller row so a refusal can only be about the role itself."""
    return headers_for_role(role, patroller_id if role == ROLE_PATROLLER else None)


def test_only_the_mountain_ops_director_may_decide_that_a_terrain_area_opens(api, mountain):
    """The opening decision on a fully ready area is refused to all five other roles and granted to the director alone.

    The daily open/close decision is the `MountainOpsDirector`'s exclusive act on one terrain area, carrying a `decision` of `OPEN` or `CLOSE` and an optional `note`.

    If the headers are well formed but the declared role is not permitted to invoke the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/the_terrain_opening_decision_is_exclusive_to_the_mountain_ops_director
    """
    # A published operating day over an area that has cleared every gate, so the
    # only thing that can stand between a caller and an open trail is the role.
    state = mountain.operating_season()
    area_id = state["area_id"]
    on_duty_patroller_id = state["patroller_ids"][0]
    assert state["area"]["opening_state"] == "READY"
    day_plan_before = mountain.day_plan(state["day_plan_id"])

    payload = opening_decision_payload("OPEN", note=OPENING_NOTE)
    for role in ALL_ROLES:
        if role == ROLE_DIRECTOR:
            continue
        # Never 404, 409 or 422: the refusal happens before readiness is read.
        validate_error(
            api.decide_opening(area_id, payload, headers_of(role, on_duty_patroller_id)),
            ERR_UNAUTHORIZED,
            403,
        )

    # None of the five refusals ran a partial cascade.
    area_after_refusals = validate_success(api.get_terrain_area(area_id, GROOMING_HEADERS))
    assert area_after_refusals["opening_state"] == "READY"
    assert_version_unchanged(day_plan_before, mountain.day_plan(state["day_plan_id"]))

    # The identical payload from the one permitted role opens the trail.
    opened = validate_success(api.decide_opening(area_id, payload, DIRECTOR_HEADERS))
    assert opened["opening_state"] == "OPEN"


def test_the_director_may_build_a_pump_house_but_only_the_supervisor_may_run_it(api, mountain):
    """Provisioning a pump house is open to the director as well as the supervisor, while changing its status and committing water against it are the supervisor's alone.

    Pump houses complete the inventory and may be registered by the `SnowmakingSupervisor` or the `MountainOpsDirector`.

    Its `status` is either `ONLINE` (the default) or `MAINTENANCE`, and the `SnowmakingSupervisor` may toggle it later: moving a pump house to `MAINTENANCE` blocks new sessions on it and blocks any attempt to start or resume an existing one, both rejected with `ERR_PUMP_HOUSE_OFFLINE`, while sessions already running are left untouched and may still be paused or completed.

    Scheduling a snowmaking session is the `SnowmakingSupervisor`'s exclusive act and the single most heavily gated create in the system, because it simultaneously commits a scarce water right, a scarce pumping capacity, and a terrain area whose readiness the supervisor read a moment ago.

    Design: Corner/rbac/pump_houses_are_created_by_two_roles_but_only_the_supervisor_may_run_them
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"], name="Sunbowl")

    # The director provisions plant successfully and it comes up online.
    provisioned = validate_success(
        api.create_pump_house(
            pump_house_payload(
                season["id"],
                pump_house_code=PUMP_HOUSE_CODE,
                name=PUMP_HOUSE_NAME,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert provisioned["status"] == "ONLINE"
    pump_house_id = provisioned["id"]

    # The grooming lead is in neither permitted set.
    validate_error(
        api.create_pump_house(
            pump_house_payload(
                season["id"],
                pump_house_code=ROGUE_PUMP_HOUSE_CODE,
                name=ROGUE_PUMP_HOUSE_NAME,
            ),
            GROOMING_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    # The very director who built this pump house may not take it offline.
    for headers in (DIRECTOR_HEADERS, LIFT_OPS_HEADERS):
        validate_error(
            api.set_pump_house_status(
                pump_house_id, pump_house_status_payload("MAINTENANCE"), headers
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    # The two refused status writes changed nothing at all.
    untouched = validate_success(api.get_pump_house(pump_house_id, DIRECTOR_HEADERS))
    assert untouched["status"] == "ONLINE"
    assert_integer(untouched["active_session_count"], 0)

    # One payload, sound in every respect except the role that sends it.
    session_request = session_payload(
        area["id"],
        pump_house_id,
        mountain.area_version(area["id"]),
        window_start=SESSION_WINDOW_START,
        window_end=SESSION_WINDOW_END,
        gun_count=SESSION_GUN_COUNT,
        gpm=SESSION_GPM,
    )
    for headers in (DIRECTOR_HEADERS, GROOMING_HEADERS, GUEST_SERVICES_HEADERS):
        validate_error(
            api.create_session(session_request, headers), ERR_UNAUTHORIZED, 403
        )

    scheduled = validate_success(
        api.create_session(session_request, SNOWMAKING_HEADERS), 201
    )
    assert_water_af(scheduled["water_af_reserved"], SESSION_WATER_AF_RESERVED)

    # The permitted role can do what the director could not.
    toggled = validate_success(
        api.set_pump_house_status(
            pump_house_id, pump_house_status_payload("MAINTENANCE"), SNOWMAKING_HEADERS
        )
    )
    assert toggled["status"] == "MAINTENANCE"


def test_four_roles_may_report_an_incident_while_only_the_director_may_dispatch_a_responder(
    api, mountain
):
    """Anyone on the hill except the grooming and snowmaking crews may open an injury record, and committing a patroller to it belongs to the director alone.

    Incidents may be reported by a `Patroller`, a `GuestServicesAgent`, the `MountainOpsDirector` or a `LiftOpsManager` — the guest services desk and the lift crew see as much as patrol does.

    Dispatching a responder is the `MountainOpsDirector`'s exclusive act and nominates a `patroller_id` in the body.

    Design: Corner/rbac/incident_reporting_is_shared_by_four_roles_while_dispatch_is_exclusive_to_one
    """
    state = mountain.open_mountain()
    area_id = state["area_id"]
    first_patroller_id = state["patroller_ids"][0]
    assert state["area"]["opening_state"] == "OPEN"

    # Four roles, four accepted reports, four records opened on the clock.
    reported_incident_ids = []
    for role, severity in zip(REPORTING_ROLES, REPORTED_SEVERITIES):
        reported = validate_success(
            api.create_incident(
                incident_payload(
                    area_id,
                    reporter_code=REPORTER_CODE,
                    severity=severity,
                    location_note=LOCATION_NOTE,
                ),
                headers_of(role, first_patroller_id),
            ),
            201,
        )
        assert reported["state"] == "REPORTED"
        assert_instant_equals(reported["reported_at"], INITIAL_CLOCK)
        assert reported["responder_patroller_id"] is None
        reported_incident_ids.append(reported["id"])

    # The two roles outside the shared set are refused the identical report.
    for role in (ROLE_GROOMING, ROLE_SNOWMAKING):
        validate_error(
            api.create_incident(
                incident_payload(
                    area_id,
                    reporter_code=REPORTER_CODE,
                    severity="MINOR",
                    location_note=LOCATION_NOTE,
                ),
                headers_of(role, first_patroller_id),
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    # A role that may not open an incident may still read the day's incidents.
    rows, meta = validate_paginated(
        api.list_incidents(GROOMING_HEADERS, terrain_area_id=area_id)
    )
    assert_integer(meta["total_count"], SHARED_REPORT_COUNT)
    assert len(rows) == SHARED_REPORT_COUNT

    # No role inherits dispatch from its ability to report, and the patroller is
    # refused even when he nominates himself.
    first_incident_id = reported_incident_ids[0]
    dispatch_request = incident_dispatch_payload(first_patroller_id)
    for role in (ROLE_PATROLLER, ROLE_LIFT_OPS, ROLE_GUEST_SERVICES, ROLE_GROOMING):
        validate_error(
            api.dispatch_incident(
                first_incident_id, dispatch_request, headers_of(role, first_patroller_id)
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    # The nominated patroller was never consumed by the four refusals, so the
    # director's dispatch still finds him available.
    dispatched = validate_success(
        api.dispatch_incident(first_incident_id, dispatch_request, DIRECTOR_HEADERS)
    )
    assert dispatched["state"] == "DISPATCHED"
    assert dispatched["responder_patroller_id"] == first_patroller_id
    assert_integer(dispatched["response_minutes"], 0)

    # The responder leaving the roster drops the area below its patrol minimum.
    held_area = validate_success(api.get_terrain_area(area_id, GROOMING_HEADERS))
    assert held_area["opening_state"] == "PATROL_HOLD"


def test_only_a_patroller_may_sign_off_a_park_and_never_the_one_who_built_it(api, mountain):
    """A grooming lead may shape a park but may not certify it, and the patroller who shaped it is stopped by the segregation-of-duties rule rather than by the role check.

    A build is recorded by a `GroomingLead` or a `Patroller` and submits the park's `features` as an array, each entry declaring a `feature_type` of `JUMP`, `RAIL`, `JIB` or `HALFPIPE` and a `size_class` of `S`, `M` or `L`.

    Inspection is a `Patroller`-only sign-off, optionally carrying an `inspection_note`.

    It requires `park_state` to be `PARK_BUILT`, requires the acting patroller to be on duty, and requires `X-User-ID` to differ from `park_built_by_user_id` — the same user may not both build and sign off a park, and doing so is refused with `ERR_SOD_VIOLATION`.

    Design: Corner/rbac/park_inspection_is_patroller_only_and_the_builder_may_never_inspect_his_own_build
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"],
        lift["id"],
        trail_code=PARK_TRAIL_CODE,
        name=PARK_NAME,
        terrain_class="PARK",
    )
    patrollers = mountain.staff_patrol(season["id"], area["id"], 2)
    builder_id, inspector_id = patrollers[0]["id"], patrollers[1]["id"]

    build_request = park_build_payload(list(PARK_FEATURES))

    # The guest services desk is outside the build set entirely.
    validate_error(
        api.build_park(area["id"], build_request, GUEST_SERVICES_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )

    # Building as a patroller is what makes the sign-off rule observable.
    built = validate_success(
        api.build_park(area["id"], build_request, make_patroller_headers(builder_id))
    )
    assert built["park_state"] == "PARK_BUILT"
    assert_integer(built["park_feature_count"], PARK_FEATURE_COUNT)
    assert_one_decimal(built["park_risk_score"], PARK_RISK_SCORE)

    observed = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert observed["park_built_by_user_id"] == builder_id
    assert observed["park_inspected_by_user_id"] is None

    # The grooming lead who could legally build may not sign off, and neither
    # may the director or the lift manager.
    inspection_request = park_inspection_payload(inspection_note=INSPECTION_NOTE)
    for headers in (GROOMING_HEADERS, DIRECTOR_HEADERS, LIFT_OPS_HEADERS):
        validate_error(
            api.inspect_park(area["id"], inspection_request, headers),
            ERR_UNAUTHORIZED,
            403,
        )

    # The builder holds the one permitted role, so the role check passes and the
    # segregation-of-duties rule is what stops him: a conflict, not a refusal.
    validate_error(
        api.inspect_park(
            area["id"], inspection_request, make_patroller_headers(builder_id)
        ),
        ERR_SOD_VIOLATION,
        409,
    )

    signed_off = validate_success(
        api.inspect_park(
            area["id"], inspection_request, make_patroller_headers(inspector_id)
        )
    )
    assert signed_off["park_state"] == "PARK_INSPECTED"
    assert signed_off["park_inspected_by_user_id"] == inspector_id
    assert signed_off["park_built_by_user_id"] == builder_id

    # Building and certifying a park is not an opening decision.
    assert signed_off["opening_state"] == "CLOSED"


def test_the_lift_manager_shares_the_weather_post_but_may_neither_publish_nor_close_the_day(
    api, mountain
):
    """Two roles may post the mountain observation onto one day plan, while opening that plan for business and putting it to bed stay with the director.

    Publishing takes no payload and is the director's act.

    Posting the mountain weather observation is shared between the `MountainOpsDirector` and the `LiftOpsManager`, and it is the head of the deepest cascade in the system.

    Closing the operating day is the `MountainOpsDirector`'s act and carries an optional `season_final` flag.

    Design: Corner/rbac/weather_is_shared_by_two_roles_while_publish_and_close_day_stay_with_the_director
    """
    state = mountain.ready_area()
    day_plan_id = mountain.create_day_plan(state["season_id"])["id"]

    # The plan satisfies every publication precondition, so only the role stands
    # in the way.
    for headers in (LIFT_OPS_HEADERS, GUEST_SERVICES_HEADERS):
        validate_error(api.publish_day_plan(day_plan_id, headers), ERR_UNAUTHORIZED, 403)
    assert mountain.day_plan(day_plan_id)["posture"] == "DRAFT"
    assert mountain.season(state["season_id"])["season_state"] == "PRESEASON"

    published = validate_success(api.publish_day_plan(day_plan_id, DIRECTOR_HEADERS))
    assert published["posture"] == "PUBLISHED_PARTIAL"
    assert published["published_at"] is not None
    assert mountain.season(state["season_id"])["season_state"] == "OPERATING"

    # The lift manager posts a reading on the same plan he could not publish.
    from_lift_ops = validate_success(
        api.post_weather(
            day_plan_id,
            weather_payload(LIFT_OPS_WIND_MPH, LIFT_OPS_WET_BULB_F, new_snow_in=0.0),
            LIFT_OPS_HEADERS,
        )
    )
    assert_one_decimal(from_lift_ops["wind_speed_mph"], LIFT_OPS_WIND_MPH)
    assert_one_decimal(from_lift_ops["wet_bulb_f"], LIFT_OPS_WET_BULB_F)
    assert from_lift_ops["posture"] == "PUBLISHED_PARTIAL"

    # The director posts over it.
    from_director = validate_success(
        api.post_weather(
            day_plan_id,
            weather_payload(DIRECTOR_WIND_MPH, DIRECTOR_WET_BULB_F, new_snow_in=0.0),
            DIRECTOR_HEADERS,
        )
    )
    assert_one_decimal(from_director["wind_speed_mph"], DIRECTOR_WIND_MPH)
    assert_one_decimal(from_director["wet_bulb_f"], DIRECTOR_WET_BULB_F)

    for headers in (GROOMING_HEADERS, SNOWMAKING_HEADERS):
        validate_error(
            api.post_weather(
                day_plan_id,
                weather_payload(REFUSED_WIND_MPH, REFUSED_WET_BULB_F, new_snow_in=0.0),
                headers,
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    # The two refused posts left no trace, so the refusal precedes the write.
    observed = validate_success(api.get_day_plan(day_plan_id, GROOMING_HEADERS))
    assert_one_decimal(observed["wind_speed_mph"], DIRECTOR_WIND_MPH)
    assert_one_decimal(observed["wet_bulb_f"], DIRECTOR_WET_BULB_F)

    # The lift manager who may post weather to this exact plan cannot close it.
    for headers in (GUEST_SERVICES_HEADERS, LIFT_OPS_HEADERS):
        validate_error(
            api.close_day(day_plan_id, headers, close_day_payload(False)),
            ERR_UNAUTHORIZED,
            403,
        )

    closed = validate_success(
        api.close_day(day_plan_id, DIRECTOR_HEADERS, close_day_payload(False))
    )
    assert closed["posture"] == "DAY_CLOSED"
    # The mountain is put to bed: the standby lift shuts down, while the merely
    # ready area is untouched because only open and held areas are swept.
    assert mountain.lift(state["lift_id"])["service_status"] == "CLOSED"
    assert mountain.area(state["area_id"])["opening_state"] == "READY"


def test_only_the_guest_services_desk_may_write_an_admission_that_every_role_may_read(
    api, mountain
):
    """Creating, checking in and releasing a reservation belong to the guest services agent alone, while the roles refused those writes read the very same reservation in full.

    Admission is the `GuestServicesAgent`'s work.

    If the headers are well formed but the declared role is not permitted to invoke the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

    Design: Corner/rbac/admission_writes_are_guest_services_only_while_admission_reads_are_open_to_all_six_roles
    """
    state = mountain.open_mountain()
    day_plan_id = state["day_plan_id"]
    on_duty_patroller_id = state["patroller_ids"][0]

    # The version is read immediately before the writes, so no refusal below can
    # be a stale-version rejection in disguise.
    observed_version = validate_success(
        api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS)
    )["version"]
    admission_request = reservation_payload(
        day_plan_id,
        observed_version,
        party_code=PARTY_CODE,
        pass_type=PARTY_PASS_TYPE,
        party_size=PARTY_SIZE,
        vehicle_count=PARTY_VEHICLE_COUNT,
    )

    for role in (ROLE_DIRECTOR, ROLE_LIFT_OPS, ROLE_PATROLLER):
        validate_error(
            api.create_reservation(
                admission_request, headers_of(role, on_duty_patroller_id)
            ),
            ERR_UNAUTHORIZED,
            403,
        )

    # The same party code the three refusals used is still free, so none of them
    # persisted a row.
    admitted = validate_success(
        api.create_reservation(admission_request, GUEST_SERVICES_HEADERS), 201
    )
    assert admitted["party_code"] == PARTY_CODE
    assert admitted["state"] == "CONFIRMED"
    assert_integer(admitted["allocated_stalls"], PARTY_ALLOCATED_STALLS)
    reservation_id = admitted["id"]

    validate_error(
        api.check_in_reservation(reservation_id, DIRECTOR_HEADERS), ERR_UNAUTHORIZED, 403
    )
    validate_error(
        api.release_reservation(
            reservation_id, headers_of(ROLE_PATROLLER, on_duty_patroller_id)
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    # The director who was refused the check-in reads the whole row.
    read_by_director = validate_success(
        api.get_reservation(reservation_id, DIRECTOR_HEADERS)
    )
    assert read_by_director["state"] == "CONFIRMED"
    assert_integer(read_by_director["party_size"], PARTY_SIZE)
    assert_integer(read_by_director["allocated_stalls"], PARTY_ALLOCATED_STALLS)

    # The grooming lead lists the day's admissions although no admission write is
    # open to that role.
    rows, meta = validate_paginated(
        api.list_day_plan_reservations(day_plan_id, GROOMING_HEADERS, state="CONFIRMED")
    )
    assert_integer(meta["total_count"], CONFIRMED_ROW_COUNT)
    assert ids_of(rows) == [reservation_id]

    checked_in = validate_success(
        api.check_in_reservation(reservation_id, GUEST_SERVICES_HEADERS)
    )
    assert checked_in["state"] == "CHECKED_IN"

    released = validate_success(
        api.release_reservation(reservation_id, GUEST_SERVICES_HEADERS)
    )
    assert released["state"] == "RELEASED"
    assert_integer(released["allocated_stalls"], 0)

    # The seats and the stalls the party held come back to the day.
    day_plan_after = mountain.day_plan(day_plan_id)
    assert_integer(day_plan_after["admitted_guest_count"], 0)
    assert_integer(day_plan_after["parking_stalls_used"], 0)
