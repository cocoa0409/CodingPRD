"""Corner coverage: the `rbac` section of the breadth index.

Every test in this module translates exactly one instance of
`SCAFFOLD_CORNER_DESIGN.yaml`'s `section: rbac` block and names it on the
`Design:` line of its docstring. Nothing here is invented from the PRD
directly: the design index is the only test source.

Each test starts against an empty store whose logical clock reads
`2026-08-01T00:00:00Z`, so every world a test needs is built inside that test
or by one of the private module-level helpers below.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_entry_state,
    assert_timing,
    assert_version,
    assert_wave_state,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    CERT_BASIC,
    CERT_PARAMEDIC,
    CLEARANCE_CLEARED,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    DECISION_APPROVED,
    DIVISION_OPEN,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED_PENALTY,
    PROGRESS_FINISHED,
    READINESS_OPEN,
    RELEASE_SCHEDULED,
    RELEASE_STARTED,
    RESULT_OFFICIAL,
    RESULT_PROVISIONAL,
    RESULT_UNDER_PROTEST,
    ROSTER_SEALED,
    RULING_DENIED_OFFICIAL,
    SCORING_GUN_TIME,
    SERVICE_BAG_CHECK,
    SERVICE_OPEN,
    STAFF_MEDIC_1,
    STAFF_PERSON_1,
    STAFF_PERSON_2,
    STAFF_PERSON_3,
    STAFF_ROLE_MARSHAL,
    STAFF_ROLE_MEDIC,
    TERRAIN_FOREST,
    TERRAIN_QUARRY,
    USER_MARSHAL_7,
    WATER_ACCESS_NONE,
)

# ─── The canonical parcel, course and station set of the design index ────

#: The permit horizon sits well past every instant these tests use, so no
#: clock movement in this module ever expires the governing application.
_PERMIT_VALID_UNTIL_UTC = "2026-12-31T00:00:00.000Z"
_RESTORATION_DEADLINE_UTC = "2026-10-01T00:00:00.000Z"

#: The course of the index: a 12.00-per-minute corral feeding 200 at a time.
_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

#: Three dry primary stations, each needing exactly one marshal, whose design
#: rates are 12.00, 7.50 and 12.00 — so `design_capacity_pph` is 450 and, once
#: every station is marshaled, `bottleneck_capacity_pph` is 450 as well.
_STATION_KWARGS = [
    {
        "name": "Cargo Net",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1200,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 0,
    },
    {
        "name": "Mud Trench",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 1,
        "footprint_sqm": 1500,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_MANDATORY,
        "penalty_seconds": 120,
    },
    {
        "name": "Wall Climb",
        "difficulty_rating": 7,
        "lane_count": 3,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 90,
    },
]

_STATION_PEOPLE = [STAFF_PERSON_1, STAFF_PERSON_2, STAFF_PERSON_3]

_GUN_UTC = "2026-09-12T08:00:00.000Z"
_FINISH_UTC = "2026-09-12T08:15:00.000Z"

#: The three marshals of the design index, each recording at one station.
_RECORDERS = [users.MARSHAL, users.MARSHAL_7, users.MARSHAL_2]


def _unpermitted_world(api):
    """A parcel with no permit at all, a DRAFT one-station course, an OPEN heat
    at 08:00 for 20 runners, and one waivered runner on bib 1.

    Returns `(venue, course, station, division, wave, entry, participant)`.
    """
    parcel = fx.venue(
        api,
        water_access=WATER_ACCESS_NONE,
        protected_acreage_sqm=2000,
        restoration_bond_cents=1000000,
    )
    laid = fx.course(api, parcel["id"], **_COURSE_KWARGS)
    station = fx.obstacle(api, laid["id"], 1, **_STATION_KWARGS[0])
    div = fx.division(
        api,
        name="Open Wave",
        division_type=DIVISION_OPEN,
        bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=SCORING_GUN_TIME,
        min_age=16,
    )
    heat = fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S1",
        scheduled_start_utc=_GUN_UTC,
        capacity=20,
    )
    human = fx.cleared_participant(api, birth_year=2000)
    ent = fx.entry(api, heat["id"], human["id"], 1)
    return parcel, laid, station, div, heat, ent, human


def _started_heat_with_one_runner(api):
    """The canonical published, fully staffed course with heat S1 STARTED.

    Returns `(course, stations, wave, entry, participant)`. The clock is left
    at the gun instant `2026-09-12T08:00:00Z`.
    """
    parcel = fx.venue(
        api,
        water_access=WATER_ACCESS_NONE,
        protected_acreage_sqm=2000,
        restoration_bond_cents=1000000,
    )
    fx.approved_permit(
        api,
        parcel["id"],
        water_use_allowed=False,
        max_disturbed_area_sqm=5000,
        quiet_hours_start_hour_utc=22,
        quiet_hours_end_hour_utc=6,
        valid_until_utc=_PERMIT_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    laid, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
    fx.published_course(api, laid["id"])
    for station, person in zip(stations, _STATION_PEOPLE):
        fx.marshal_shift(api, laid["id"], station["id"], staff_person_id=person)
    fx.medic_shift(api, laid["id"])
    div = fx.division(
        api,
        name="Open Wave",
        division_type=DIVISION_OPEN,
        bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=SCORING_GUN_TIME,
        min_age=16,
    )
    heat = fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S1",
        scheduled_start_utc=_GUN_UTC,
        capacity=50,
    )
    human = fx.cleared_participant(api, birth_year=2000)
    ent = fx.entry(api, heat["id"], human["id"], 1)
    fx.check_in(api, ent["id"])
    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.set_clock(api, _GUN_UTC)
    fx.start(api, heat["id"])
    return laid, stations, heat, ent, human


def _protested_entry(api):
    """A finished runner carrying a 120-second penalty, protesting the station-2
    attempt that `marshal-7` recorded.

    Returns `(entry, disputed_attempt)` with the entry `UNDER_PROTEST`.
    """
    _, stations, _, ent, human = _started_heat_with_one_runner(api)
    outcomes = [OUTCOME_COMPLETED, OUTCOME_FAILED_PENALTY, OUTCOME_COMPLETED]
    cards = [
        fx.attempt(api, ent["id"], station["id"], outcome, headers=recorder)
        for station, outcome, recorder in zip(stations, outcomes, _RECORDERS)
    ]
    disputed = cards[1]
    assert disputed["recorded_by_user_id"] == USER_MARSHAL_7

    fx.set_clock(api, _FINISH_UTC)
    fx.finish(api, ent["id"], headers=users.MARSHAL)
    fx.protest(api, ent["id"], human["id"], disputed["id"])
    return fx.read_entry(api, ent["id"]), disputed


# ─── Instance: roles_cannot_reach_each_others_exclusive_operations


def test_eight_cross_role_attempts_are_all_refused(api):
    """PRD §2.1: "A request whose headers are well formed but whose role is not among the roles authorised for the operation being invoked is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_operations
    """
    parcel, laid, station, _, heat, ent, _ = _unpermitted_world(api)
    parcel_version = fx.read_venue(api, parcel["id"])["version"]

    forbidden = 403
    code = ApiErrorId.ERR_FORBIDDEN_ROLE.value

    # Registering a parcel belongs to the PermitOfficer alone.
    validate_error(
        api.create_venue(
            f.venue_payload(
                name="Second Parcel",
                terrain_type=TERRAIN_FOREST,
                water_access=WATER_ACCESS_NONE,
                protected_acreage_sqm=1000,
                restoration_bond_cents=500000,
            ),
            users.DESIGNER,
        ),
        code,
        expected_status=forbidden,
    )

    # Filing the application is the CourseDesigner's move, even though it is
    # the PermitOfficer who ultimately rules on it.
    validate_error(
        api.create_permit(
            parcel["id"],
            f.permit_payload(
                permit_number="C-2924-47",
                water_use_allowed=False,
                max_disturbed_area_sqm=5000,
                valid_until_utc=_PERMIT_VALID_UNTIL_UTC,
                restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
            ),
            users.OFFICER,
        ),
        code,
        expected_status=forbidden,
    )

    # Divisions are the RaceDirector's configuration.
    validate_error(
        api.create_division(
            f.division_payload(name="Rogue Division", min_age=16), users.DESIGNER
        ),
        code,
        expected_status=forbidden,
    )

    # The designer validates; only the director publishes.
    validate_error(
        api.publish_course(laid["id"], users.DESIGNER),
        code,
        expected_status=forbidden,
    )

    # Rostering is exclusive to the SafetyOfficer, broad as the director is.
    validate_error(
        api.create_staff_assignment(
            laid["id"],
            f.staff_payload(
                STAFF_ROLE_MARSHAL,
                station["id"],
                staff_person_id=STAFF_PERSON_1,
                certification_level=CERT_BASIC,
            ),
            users.DIRECTOR,
        ),
        code,
        expected_status=forbidden,
    )

    # The SafetyOfficer may hold a heat, but never release one.
    validate_error(
        api.release_wave(heat["id"], users.SAFETY),
        code,
        expected_status=forbidden,
    )

    # A protest is the Participant's own instrument.
    validate_error(
        api.create_protest(
            ent["id"],
            f.protest_payload(NON_EXISTENT_UUID, reason="Filed by the wrong role"),
            users.OPS,
        ),
        code,
        expected_status=forbidden,
    )

    # Settling the bond stays with the PermitOfficer who posted it.
    validate_error(
        api.create_bond_release(
            parcel["id"], f.bond_release_payload(parcel_version), users.OPS
        ),
        code,
        expected_status=forbidden,
    )

    # Not one of the eight left a trace.
    _, venue_meta = validate_paginated(
        api.list_venues(users.OFFICER, params={"limit": 10, "offset": 0})
    )
    assert venue_meta["total_count"] == 1

    _, division_meta = validate_paginated(
        api.list_divisions(users.DIRECTOR, params={"limit": 10, "offset": 0})
    )
    assert division_meta["total_count"] == 1

    _, permit_meta = validate_paginated(
        api.list_permits(parcel["id"], users.OFFICER, params={"limit": 10, "offset": 0})
    )
    assert permit_meta["total_count"] == 0

    _, shift_meta = validate_paginated(
        api.list_staff_assignments(users.SAFETY, params={"limit": 10, "offset": 0})
    )
    assert shift_meta["total_count"] == 0

    assert fx.read_course(api, laid["id"])["status"] == COURSE_DRAFT
    assert_wave_state(fx.read_wave(api, heat["id"]), release_status=RELEASE_SCHEDULED)
    assert_version(fx.read_venue(api, parcel["id"]), parcel_version, "venue")


def test_role_gate_precedes_state_and_body_reference_gates(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Corner/rbac/roles_cannot_reach_each_others_exclusive_operations
    """
    _, laid, _, _, _, ent, _ = _unpermitted_world(api)

    # The course is only DRAFT, so publication would also fail the course-state
    # rung — but role authorisation sits above it in the ladder.
    validate_error(
        api.publish_course(laid["id"], users.DESIGNER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    assert fx.read_course(api, laid["id"])["status"] == COURSE_DRAFT

    # The disputed attempt does not exist and the entry is not protestable, yet
    # the wrong role is still what decides the response.
    validate_error(
        api.create_protest(
            ent["id"],
            f.protest_payload(NON_EXISTENT_UUID, reason="Filed by the wrong role"),
            users.OPS,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        expected_status=403,
    )
    assert fx.read_entry(api, ent["id"])["disputed_attempt_id"] is None


# ─── Instance: all_seven_roles_perform_their_own_operations_end_to_end


def test_all_seven_roles_perform_their_own_operations(api):
    """PRD §2.1: "The authorised roles for each operation are listed in the endpoint table of §4."

    Design: Corner/rbac/all_seven_roles_perform_their_own_operations_end_to_end
    """
    # PermitOfficer: register the parcel.
    parcel = validate_success(
        api.create_venue(
            f.venue_payload(
                terrain_type=TERRAIN_QUARRY,
                water_access=WATER_ACCESS_NONE,
                protected_acreage_sqm=2000,
                restoration_bond_cents=1000000,
            ),
            users.OFFICER,
        ),
        expected_status=201,
    )

    # CourseDesigner: file and submit the land-use application.
    permit = validate_success(
        api.create_permit(
            parcel["id"],
            f.permit_payload(
                permit_number="C-2924-48",
                water_use_allowed=False,
                max_disturbed_area_sqm=5000,
                quiet_hours_start_hour_utc=22,
                quiet_hours_end_hour_utc=6,
                valid_until_utc=_PERMIT_VALID_UNTIL_UTC,
                restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
            ),
            users.DESIGNER,
        ),
        expected_status=201,
    )
    validate_success(api.submit_permit(permit["id"], users.DESIGNER))

    # PermitOfficer: rule on the application filed by a different operator.
    validate_success(
        api.decide_permit(
            permit["id"], f.decision_payload(DECISION_APPROVED), users.OFFICER
        )
    )

    # CourseDesigner: lay the course, place the stations, run the design gate.
    laid = validate_success(
        api.create_course(parcel["id"], f.course_payload(**_COURSE_KWARGS), users.DESIGNER),
        expected_status=201,
    )
    stations = [
        validate_success(
            api.create_obstacle(
                laid["id"], f.obstacle_payload(index + 1, **kwargs), users.DESIGNER
            ),
            expected_status=201,
        )
        for index, kwargs in enumerate(_STATION_KWARGS)
    ]
    validate_success(api.validate_course(laid["id"], users.DESIGNER))

    # RaceDirector: publish, define the division, schedule the heat.
    validate_success(api.publish_course(laid["id"], users.DIRECTOR))
    div = validate_success(
        api.create_division(
            f.division_payload(
                name="Open Wave",
                division_type=DIVISION_OPEN,
                bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
                scoring_mode=SCORING_GUN_TIME,
                min_age=16,
            ),
            users.DIRECTOR,
        ),
        expected_status=201,
    )
    heat = validate_success(
        api.create_wave(
            laid["id"],
            f.wave_payload(
                div["id"], wave_code="S1", scheduled_start_utc=_GUN_UTC, capacity=50
            ),
            users.DIRECTOR,
        ),
        expected_status=201,
    )

    # SafetyOfficer: roster three marshals and the medic.
    for station, person in zip(stations, _STATION_PEOPLE):
        validate_success(
            api.create_staff_assignment(
                laid["id"],
                f.staff_payload(
                    STAFF_ROLE_MARSHAL,
                    station["id"],
                    staff_person_id=person,
                    certification_level=CERT_BASIC,
                ),
                users.SAFETY,
            ),
            expected_status=201,
        )
    validate_success(
        api.create_staff_assignment(
            laid["id"],
            f.staff_payload(
                STAFF_ROLE_MEDIC,
                None,
                staff_person_id=STAFF_MEDIC_1,
                certification_level=CERT_PARAMEDIC,
            ),
            users.SAFETY,
        ),
        expected_status=201,
    )

    # SiteOpsLead: the festival area, the human, the entry and bag check.
    bag_check = validate_success(
        api.create_festival_service(
            parcel["id"],
            f.festival_service_payload(
                service_type=SERVICE_BAG_CHECK,
                footprint_sqm=150,
                capacity=500,
                water_draw_lpm=0,
            ),
            users.OPS,
        ),
        expected_status=201,
    )
    human = validate_success(
        api.create_participant(f.participant_payload(birth_year=2000), users.OPS),
        expected_status=201,
    )

    # Participant: sign their own waiver.
    signed = validate_success(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(),
            users.participant_headers(human["id"]),
        )
    )
    assert signed["clearance_status"] == CLEARANCE_CLEARED

    ent = validate_success(
        api.create_entry(heat["id"], f.entry_payload(human["id"], 1), users.OPS),
        expected_status=201,
    )
    validate_success(
        api.check_in_entry(ent["id"], f.check_in_payload(0), users.OPS)
    )

    # RaceDirector: seal the roster, release the heat and fire the gun.
    validate_success(api.lock_roster(heat["id"], users.DIRECTOR))
    validate_success(api.release_wave(heat["id"], users.DIRECTOR))
    validate_success(api.set_clock(_GUN_UTC, users.DIRECTOR))
    started = validate_success(api.start_wave(heat["id"], users.DIRECTOR))
    assert_wave_state(
        started, release_status=RELEASE_STARTED, roster_status=ROSTER_SEALED
    )

    # ObstacleMarshal: three attempt cards and the finish.
    outcomes = [OUTCOME_COMPLETED, OUTCOME_FAILED_PENALTY, OUTCOME_COMPLETED]
    for station, outcome, recorder in zip(stations, outcomes, _RECORDERS):
        validate_success(
            api.create_attempt(
                ent["id"], f.attempt_payload(station["id"], outcome), recorder
            ),
            expected_status=201,
        )
    validate_success(api.set_clock(_FINISH_UTC, users.DIRECTOR))
    finished = validate_success(api.finish_entry(ent["id"], users.MARSHAL))
    assert_entry_state(
        finished,
        progress_status=PROGRESS_FINISHED,
        result_status=RESULT_PROVISIONAL,
    )
    assert_timing(
        finished,
        provisional_penalty_seconds=120,
        provisional_elapsed_seconds=1020,
    )

    # Participant: read their own entry.
    own = validate_success(
        api.get_entry(ent["id"], users.participant_headers(human["id"]))
    )
    assert own["id"] == ent["id"]

    # The race really ran: the course is open and the installation is serving.
    course_row = fx.read_course(api, laid["id"])
    assert course_row["status"] == COURSE_PUBLISHED
    assert course_row["readiness_posture"] == READINESS_OPEN
    rows, meta = validate_paginated(
        api.list_festival_services(
            parcel["id"], users.OPS, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == bag_check["id"]
    assert rows[0]["status"] == SERVICE_OPEN


# ─── Instance: the_marshal_who_recorded_the_attempt_cannot_adjudicate_the_protest


def test_recording_marshal_cannot_adjudicate_the_protest(api):
    """PRD §2.7: "Likewise, an adjudication of a protest may not be recorded by the operator identifier stored in `recorded_by_user_id` on the disputed attempt; the marshal who wrote down the disputed outcome cannot also rule on the complaint about it, and an attempt to do so is refused with the same `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_marshal_who_recorded_the_attempt_cannot_adjudicate_the_protest
    """
    ent, disputed = _protested_entry(api)
    assert_entry_state(ent, result_status=RESULT_UNDER_PROTEST)
    assert ent["disputed_attempt_id"] == disputed["id"]
    opened_at_version = ent["version"]

    # `marshal-7` wrote the disputed card; the RaceDirector hat does not help.
    validate_error(
        api.create_adjudication(
            ent["id"],
            f.adjudication_payload(
                RULING_DENIED_OFFICIAL,
                opened_at_version,
                note="Reviewed by the recording marshal",
            ),
            users.DUAL_HAT_MARSHAL_AS_DIRECTOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )

    # The protest is still open and nothing on the card moved.
    after = fx.read_entry(api, ent["id"])
    assert_entry_state(after, result_status=RESULT_UNDER_PROTEST)
    assert after["protest_rounds"] == 0
    assert_version(after, opened_at_version, "entry")


def test_a_different_operator_with_the_same_role_may_adjudicate(api):
    """PRD §2.7: "Neither check inspects `X-User-Role`: it is the identifier, not the hat, that is disqualified."

    Design: Corner/rbac/the_marshal_who_recorded_the_attempt_cannot_adjudicate_the_protest
    """
    ent, _ = _protested_entry(api)
    opened_at_version = ent["version"]

    # Same RaceDirector role, same OCC token, different operator identifier.
    validate_error(
        api.create_adjudication(
            ent["id"],
            f.adjudication_payload(RULING_DENIED_OFFICIAL, opened_at_version),
            users.DUAL_HAT_MARSHAL_AS_DIRECTOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    ruled = validate_success(
        api.create_adjudication(
            ent["id"],
            f.adjudication_payload(
                RULING_DENIED_OFFICIAL, opened_at_version, note="Penalty stands"
            ),
            users.DIRECTOR,
        )
    )

    assert_entry_state(ruled, result_status=RESULT_OFFICIAL)
    assert ruled["protest_rounds"] == 1
    assert_version(ruled, opened_at_version + 1, "entry")
    assert ruled["voided_attempt_ids"] == []
    assert_timing(ruled, official_penalty_seconds=120)
