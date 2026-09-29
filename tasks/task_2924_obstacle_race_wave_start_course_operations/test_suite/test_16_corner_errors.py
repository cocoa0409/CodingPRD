"""Corner index — `errors` section.

Every test in this module translates exactly one live instance of the
`section: errors` slice of SCAFFOLD_CORNER_DESIGN.yaml, and names that instance
on the final `Design:` line of its docstring.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_course_capacities,
    assert_entry_state,
    assert_instant_equals,
    assert_version,
    assert_wave_state,
)


def _drafted_course(api):
    """A permitted parcel carrying a DRAFT three-station course.

    Ratings 4/6/8 clear the design gate; the default station geometry gives
    every station a design rate of 4 lanes × 3.00 = 12.00 per minute, under the
    corral ceiling of 20.00, so `design_capacity_pph` is 720 and a heat of 50
    sits well inside the 15-minute grid ceiling of 180.
    """
    parcel, permit = fx.permitted_venue(api)
    course, stations = fx.three_station_course(api, parcel["id"])
    return parcel, permit, course, stations


def _open_heat(api, course_id, division_overrides=None, **wave_overrides):
    """A freshly scheduled heat with an OPEN roster. Returns (division, heat)."""
    division = fx.division(api, **(division_overrides or {}))
    heat = fx.wave(api, course_id, division["id"], **wave_overrides)
    return division, heat


def _staffed_published_course(api, station_kwargs=None):
    """A PUBLISHED course whose every station is fully marshaled.

    One paramedic covers the medic minimum for any scheduled capacity up to
    250, and no default station touches water, so the water-safety minimum is
    zero and `readiness_posture` settles on `OPEN`.
    """
    parcel, _permit = fx.permitted_venue(api)
    course, stations = fx.three_station_course(
        api, parcel["id"], station_kwargs=station_kwargs
    )
    for station in stations:
        fx.fully_marshal(api, course["id"], station)
    fx.medic_shift(api, course["id"])
    published = fx.published_course(api, course["id"])
    return parcel, published, stations


def _started_entry(api, station_kwargs=None):
    """One cleared human, checked in and started on a published course.

    Returns `(stations, heat, runner, entry)`.
    """
    _parcel, course, stations = _staffed_published_course(api, station_kwargs)
    _division, heat = _open_heat(api, course["id"])
    runner = fx.cleared_participant(api)
    entry = fx.entry(api, heat["id"], runner["id"], 1)
    fx.check_in(api, entry["id"])
    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.start(api, heat["id"])
    return stations, heat, runner, fx.read_entry(api, entry["id"])


# ─── errors / every path id route reports its own code ──────────────────


def test_each_path_id_route_reports_its_own_not_found_code(api):
    """PRD §2.6: "The applicable code is `ERR_VENUE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_OBSTACLE_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND` or `ERR_RESTORATION_TASK_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/every_path_id_route_returns_its_own_not_found_code
    """
    probes = [
        ("venue", api.get_venue(NON_EXISTENT_UUID, users.OFFICER),
         ApiErrorId.ERR_VENUE_NOT_FOUND.value),
        ("permit", api.get_permit(NON_EXISTENT_UUID, users.OFFICER),
         ApiErrorId.ERR_PERMIT_NOT_FOUND.value),
        ("course", api.get_course(NON_EXISTENT_UUID, users.DESIGNER),
         ApiErrorId.ERR_COURSE_NOT_FOUND.value),
        ("obstacle", api.get_obstacle(NON_EXISTENT_UUID, users.DESIGNER),
         ApiErrorId.ERR_OBSTACLE_NOT_FOUND.value),
        ("wave", api.get_wave(NON_EXISTENT_UUID, users.DIRECTOR),
         ApiErrorId.ERR_WAVE_NOT_FOUND.value),
        ("participant", api.get_participant(NON_EXISTENT_UUID, users.OPS),
         ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value),
        ("entry", api.get_entry(NON_EXISTENT_UUID, users.DIRECTOR),
         ApiErrorId.ERR_ENTRY_NOT_FOUND.value),
        ("staff assignment",
         api.get_staff_assignment(NON_EXISTENT_UUID, users.SAFETY),
         ApiErrorId.ERR_STAFF_ASSIGNMENT_NOT_FOUND.value),
        ("restoration task",
         api.get_restoration_task(NON_EXISTENT_UUID, users.OFFICER),
         ApiErrorId.ERR_RESTORATION_TASK_NOT_FOUND.value),
    ]
    for label, response, expected_error_id in probes:
        assert response.status_code == 404, (
            f"{label}: expected HTTP 404 for an unresolvable path id, "
            f"got {response.status_code}"
        )
        validate_error(response, expected_error_id, expected_status=404)


# ─── errors / unauthenticated and non-owner reads ───────────────────────


def test_an_unauthenticated_entry_read_is_rejected_before_anything_else(api):
    """PRD §2.1: "A request missing either header, carrying an empty value in either header, or naming a role outside that set of seven is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/an_unauthenticated_read_and_a_non_owner_read_are_both_rejected
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    _division, heat = _open_heat(api, course["id"])
    runner = fx.cleared_participant(api)
    entry = fx.entry(api, heat["id"], runner["id"], 1)

    for label, headers in (
        ("no operator id", users.headers_missing_user_id(constants.ROLE_RACE_DIRECTOR)),
        ("no role", users.headers_missing_role(constants.USER_DIRECTOR_1)),
        ("empty operator id", users.headers_blank_user_id(constants.ROLE_RACE_DIRECTOR)),
        ("empty role", users.headers_blank_role(constants.USER_DIRECTOR_1)),
        ("undeclared role",
         users.headers_for(constants.USER_DIRECTOR_1, constants.UNDECLARED_ROLE)),
    ):
        response = api.get_entry(entry["id"], headers)
        assert response.status_code == 401, (
            f"{label}: expected HTTP 401, got {response.status_code}"
        )
        validate_error(
            response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
        )

    # The same read succeeds once the headers are whole.
    assert fx.read_entry(api, entry["id"])["id"] == entry["id"]


def test_a_participant_may_not_read_or_sign_for_another_human(api):
    """PRD §2.1: "Concretely, a `Participant` may read only an `Entry` whose `participant_id` equals the acting `X-User-ID`, may file a protest only on such an entry, and may sign a waiver only on the `Participant` row whose own `id` equals the acting `X-User-ID`; any other target yields `ERR_NOT_ENTRY_OWNER` (HTTP 403)."

    Design: Corner/errors/an_unauthenticated_read_and_a_non_owner_read_are_both_rejected
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    _division, heat = _open_heat(api, course["id"])
    owner = fx.cleared_participant(api, full_name="Owner Runner")
    stranger = fx.participant(api, full_name="Stranger Runner")
    entry = fx.entry(api, heat["id"], owner["id"], 1)

    # A stranger reading somebody else's entry card.
    validate_error(
        api.get_entry(entry["id"], users.participant_headers(stranger["id"])),
        ApiErrorId.ERR_NOT_ENTRY_OWNER.value,
        expected_status=403,
    )
    # A stranger signing somebody else's waiver.
    validate_error(
        api.sign_waiver(
            owner["id"],
            f.waiver_payload(),
            users.participant_headers(stranger["id"]),
        ),
        ApiErrorId.ERR_NOT_ENTRY_OWNER.value,
        expected_status=403,
    )
    assert fx.read_participant(api, stranger["id"])["waiver_signed"] is False

    # The owner reads their own card, and an operator reads anybody's.
    own_read = validate_success(
        api.get_entry(entry["id"], users.participant_headers(owner["id"]))
    )
    assert own_read["id"] == entry["id"]
    assert fx.read_entry(api, entry["id"])["participant_id"] == owner["id"]


# ─── errors / segregation of duties ─────────────────────────────────────


def test_the_submitter_may_not_decide_their_own_application(api):
    """PRD §2.7: "The land authority's decision on a permit application may not be recorded by the operator identifier stored in that permit's `submitted_by_user_id`; a `PermitOfficer` whose `X-User-ID` matches the submitter is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), which is what prevents one human wearing both the `CourseDesigner` and `PermitOfficer` hats from rubber-stamping their own application."

    Design: Corner/errors/the_same_operator_cannot_file_and_then_decide_one_application
    """
    parcel = fx.venue(api)
    drafted = validate_success(
        api.create_permit(
            parcel["id"], f.permit_payload(), users.DUAL_HAT_DESIGNER
        ),
        expected_status=201,
    )
    submitted = validate_success(
        api.submit_permit(drafted["id"], users.DUAL_HAT_DESIGNER)
    )
    assert submitted["status"] == constants.PERMIT_SUBMITTED
    assert submitted["submitted_by_user_id"] == constants.USER_DUAL_HAT

    # The same human, now wearing the PermitOfficer hat.
    refused = api.decide_permit(
        submitted["id"],
        f.decision_payload(constants.DECISION_APPROVED),
        users.DUAL_HAT_OFFICER,
    )
    validate_error(
        refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )
    still_open = fx.read_permit(api, submitted["id"])
    assert still_open["status"] == constants.PERMIT_SUBMITTED
    assert still_open["decided_by_user_id"] is None
    assert_version(still_open, submitted["version"], "permit")

    # A different officer may rule on it.
    decided = validate_success(
        api.decide_permit(
            submitted["id"],
            f.decision_payload(constants.DECISION_APPROVED),
            users.OFFICER,
        )
    )
    assert decided["status"] == constants.PERMIT_APPROVED
    assert decided["decided_by_user_id"] == constants.USER_OFFICER_1


# ─── errors / the three uniqueness codes ────────────────────────────────


def test_a_reused_station_index_reports_the_station_index_code(api):
    """PRD §3.2: "`station_index` is unique per course: reusing one is refused with `ERR_STATION_INDEX_CONFLICT`."

    Design: Corner/errors/the_uniqueness_family_reports_three_distinct_conflict_codes
    """
    parcel = fx.venue(api)
    course = fx.course(api, parcel["id"])
    fx.obstacle(api, course["id"], 1, name="Cargo Net", difficulty_rating=3)

    refused = api.create_obstacle(
        course["id"],
        f.obstacle_payload(1, name="Second Net", difficulty_rating=4),
        users.DESIGNER,
    )
    validate_error(
        refused, ApiErrorId.ERR_STATION_INDEX_CONFLICT.value, expected_status=409
    )
    assert fx.read_course(api, course["id"])["obstacle_count"] == 1

    # The next free index is accepted, so only the collision was refused.
    second = fx.obstacle(api, course["id"], 2, name="Mud Trench", difficulty_rating=5)
    assert second["station_index"] == 2
    assert fx.read_course(api, course["id"])["obstacle_count"] == 2


def test_a_reused_bib_number_reports_the_bib_code(api):
    """PRD §3.5: "Registering a participant into a heat is done by a `SiteOpsLead` or a `RaceDirector` and carries the `participant_id`, the printed `bib_number` (an integer of at least 1, unique among the entries of that heat — a reuse is refused with `ERR_BIB_NUMBER_TAKEN`), and optionally a `team_code`."

    Design: Corner/errors/the_uniqueness_family_reports_three_distinct_conflict_codes
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    _division, heat = _open_heat(api, course["id"], capacity=20)
    first = fx.cleared_participant(api, full_name="Runner One")
    second = fx.cleared_participant(api, full_name="Runner Two")
    fx.entry(api, heat["id"], first["id"], 1)

    refused = api.create_entry(
        heat["id"], f.entry_payload(second["id"], 1), users.OPS
    )
    validate_error(
        refused, ApiErrorId.ERR_BIB_NUMBER_TAKEN.value, expected_status=409
    )
    assert fx.read_wave(api, heat["id"])["assigned_count"] == 1

    # A free bib for the same human is accepted.
    accepted = fx.entry(api, heat["id"], second["id"], 2)
    assert accepted["bib_number"] == 2
    assert fx.read_wave(api, heat["id"])["assigned_count"] == 2


def test_a_duplicate_email_or_chip_reports_the_generic_conflict_code(api):
    """PRD §3.5: "Humans are enrolled once and then registered into heats. Enrolment is performed by a `SiteOpsLead` or a `RaceDirector` and records the participant's `full_name` (1 to 120 characters), their four-digit `birth_year` between 1900 and 2026 inclusive, a contact `email` that must be unique across every enrolled human, and the `chip_id` serial of the timing chip bonded to them, likewise unique across every enrolled human; a duplicate on either is refused with `ERR_UNIQUENESS_CONFLICT`."

    Design: Corner/errors/the_uniqueness_family_reports_three_distinct_conflict_codes
    """
    fx.participant(
        api, full_name="Runner One", email="one@example.com", chip_id="CHIP-501"
    )

    duplicate_email = api.create_participant(
        f.participant_payload(
            full_name="Runner Three", email="one@example.com", chip_id="CHIP-503"
        ),
        users.OPS,
    )
    validate_error(
        duplicate_email, ApiErrorId.ERR_UNIQUENESS_CONFLICT.value, expected_status=409
    )

    duplicate_chip = api.create_participant(
        f.participant_payload(
            full_name="Runner Four", email="four@example.com", chip_id="CHIP-501"
        ),
        users.OPS,
    )
    validate_error(
        duplicate_chip, ApiErrorId.ERR_UNIQUENESS_CONFLICT.value, expected_status=409
    )

    _rows, meta = validate_paginated(api.list_participants(users.OPS))
    assert meta["total_count"] == 1


def test_a_duplicate_wave_code_reports_the_generic_conflict_code(api):
    """PRD §3.4: "Each heat names the `division_id` of the single division it carries, a `wave_code` label such as `A1` that must be unique among the heats of that course (a duplicate is refused with `ERR_UNIQUENESS_CONFLICT`), the planned gun instant `scheduled_start_utc`, and a `capacity` of at least 1 giving how many entries may be assigned to it."

    Design: Corner/errors/the_uniqueness_family_reports_three_distinct_conflict_codes
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    division, first = _open_heat(api, course["id"], wave_code="S1", capacity=20)
    assert first["wave_code"] == "S1"

    # A disjoint corral window, so only the label collides.
    refused = api.create_wave(
        course["id"],
        f.wave_payload(
            division["id"],
            wave_code="S1",
            scheduled_start_utc="2026-09-12T10:00:00.000Z",
            capacity=20,
        ),
        users.DIRECTOR,
    )
    validate_error(
        refused, ApiErrorId.ERR_UNIQUENESS_CONFLICT.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api.list_waves(users.DIRECTOR, params={"course_id": course["id"]})
    )
    assert meta["total_count"] == 1

    # A distinct label in the same disjoint window is accepted.
    second = fx.wave(
        api,
        course["id"],
        division["id"],
        wave_code="S2",
        scheduled_start_utc="2026-09-12T10:00:00.000Z",
        capacity=20,
    )
    assert second["wave_code"] == "S2"


# ─── errors / the state family, one code per write ───────────────────────


def test_registering_into_a_locked_roster_reports_the_roster_code(api):
    """PRD §3.5: "Registration is only accepted while the heat's `roster_status` is `OPEN`; a heat already `LOCKED` or `SEALED` refuses it with `ERR_ROSTER_CLOSED`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    _division, heat = _open_heat(api, course["id"])
    first = fx.cleared_participant(api, full_name="Runner One")
    latecomer = fx.cleared_participant(api, full_name="Runner Two")
    fx.entry(api, heat["id"], first["id"], 1)

    locked = fx.lock_roster(api, heat["id"])
    assert_wave_state(
        locked,
        release_status=constants.RELEASE_SCHEDULED,
        roster_status=constants.ROSTER_LOCKED,
    )

    refused = api.create_entry(
        heat["id"], f.entry_payload(latecomer["id"], 2), users.OPS
    )
    validate_error(refused, ApiErrorId.ERR_ROSTER_CLOSED.value, expected_status=409)
    assert fx.read_wave(api, heat["id"])["assigned_count"] == 1


def test_validating_a_published_course_reports_the_course_state_code(api):
    """PRD §3.2: "The course must be `DRAFT`, or the request is refused with `ERR_COURSE_STATE_INVALID`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    published = fx.published_course(api, course["id"])
    assert_course_capacities(published, status=constants.COURSE_PUBLISHED)

    refused = api.validate_course(course["id"], users.DESIGNER)
    validate_error(
        refused, ApiErrorId.ERR_COURSE_STATE_INVALID.value, expected_status=409
    )
    after = fx.read_course(api, course["id"])
    assert_course_capacities(after, status=constants.COURSE_PUBLISHED)
    assert_version(after, published["version"], "course")


def test_placing_a_station_after_validation_reports_the_frozen_set_code(api):
    """PRD §3.2: "Once the course leaves `DRAFT`, the station set is frozen and any further placement is refused with `ERR_OBSTACLE_SET_FROZEN`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    parcel, _permit, course, _stations = _drafted_course(api)
    fx.validated_course(api, course["id"])
    disturbed_before = fx.read_venue(api, parcel["id"])["disturbed_area_sqm"]

    refused = api.create_obstacle(
        course["id"],
        f.obstacle_payload(4, name="Late Addition", difficulty_rating=8),
        users.DESIGNER,
    )
    validate_error(
        refused, ApiErrorId.ERR_OBSTACLE_SET_FROZEN.value, expected_status=409
    )
    assert fx.read_course(api, course["id"])["obstacle_count"] == 3
    assert fx.read_venue(api, parcel["id"])["disturbed_area_sqm"] == disturbed_before


def test_checking_in_an_already_checked_in_entry_reports_the_entry_state_code(api):
    """PRD §3.5: "The entry must still read `REGISTERED`, or it is refused with `ERR_ENTRY_STATE_INVALID`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    _parcel, _permit, course, _stations = _drafted_course(api)
    _division, heat = _open_heat(api, course["id"])
    runner = fx.cleared_participant(api)
    entry = fx.entry(api, heat["id"], runner["id"], 1)
    checked_in = fx.check_in(api, entry["id"])
    assert_entry_state(checked_in, progress_status=constants.PROGRESS_CHECKED_IN)

    # The roster is still OPEN and the heat still SCHEDULED, so the entry's own
    # state is the only condition this second bag-check call can fail.
    refused = api.check_in_entry(
        entry["id"], f.check_in_payload(0), users.OPS
    )
    validate_error(
        refused, ApiErrorId.ERR_ENTRY_STATE_INVALID.value, expected_status=409
    )
    after = fx.read_entry(api, entry["id"])
    assert_entry_state(after, progress_status=constants.PROGRESS_CHECKED_IN)
    assert after["bag_tag_code"] == checked_in["bag_tag_code"]
    assert_version(after, checked_in["version"], "entry")


def test_bypassing_a_mandatory_station_reports_the_bypass_code(api):
    """PRD §3.7: "An outcome of `BYPASSED` is refused with `ERR_BYPASS_NOT_ALLOWED` when the obstacle's own `bypass_mode` reads `MANDATORY`, and it is refused with the same code when the heat's division has a `bypass_policy` of `MANDATORY_COMPLETION`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    stations, _heat, _runner, entry = _started_entry(
        api,
        station_kwargs=[
            {"difficulty_rating": 4},
            {
                "difficulty_rating": 6,
                "bypass_mode": constants.BYPASS_MODE_MANDATORY,
                "penalty_seconds": 120,
            },
            {"difficulty_rating": 8},
        ],
    )
    mandatory_station = stations[1]
    assert mandatory_station["bypass_mode"] == constants.BYPASS_MODE_MANDATORY

    refused = api.create_attempt(
        entry["id"],
        f.attempt_payload(mandatory_station["id"], constants.OUTCOME_BYPASSED),
        users.MARSHAL,
    )
    validate_error(
        refused, ApiErrorId.ERR_BYPASS_NOT_ALLOWED.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api.list_entry_attempts(entry["id"], users.DIRECTOR)
    )
    assert meta["total_count"] == 0

    # The same station accepts an honest failure at its stated penalty.
    honoured = fx.attempt(
        api, entry["id"], mandatory_station["id"], constants.OUTCOME_FAILED_PENALTY
    )
    assert honoured["provisional_penalty_seconds"] == 120


def test_protesting_a_pending_result_reports_the_not_protestable_code(api):
    """PRD §3.8: "The entry's `result_status` must read `PROVISIONAL`, or the protest is refused with `ERR_ENTRY_NOT_PROTESTABLE`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    stations, _heat, runner, entry = _started_entry(api)
    recorded = fx.attempt(
        api, entry["id"], stations[0]["id"], constants.OUTCOME_COMPLETED
    )
    assert_entry_state(
        fx.read_entry(api, entry["id"]), result_status=constants.RESULT_PENDING
    )

    refused = api.create_protest(
        entry["id"],
        f.protest_payload(recorded["id"]),
        users.participant_headers(runner["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_ENTRY_NOT_PROTESTABLE.value, expected_status=409
    )
    after = fx.read_entry(api, entry["id"])
    assert_entry_state(after, result_status=constants.RESULT_PENDING)
    assert after["protest_rounds"] == 0
    assert after["disputed_attempt_id"] is None


def test_an_unresolvable_disputed_attempt_answers_before_the_state_check(api):
    """PRD §3.8: "And `disputed_attempt_id` must name an attempt whose `entry_id` is this very entry; an id that does not resolve, or resolves to an attempt on somebody else's card, is refused with `ERR_ATTEMPT_NOT_FOUND`."

    Design: Corner/errors/the_state_family_refuses_each_write_with_its_own_code
    """
    stations, _heat, runner, entry = _started_entry(api)
    fx.attempt(api, entry["id"], stations[0]["id"], constants.OUTCOME_COMPLETED)
    # The entry is PENDING, so the state rung would also refuse this call — the
    # body-reference rung sits above it and must answer first.
    assert_entry_state(
        fx.read_entry(api, entry["id"]), result_status=constants.RESULT_PENDING
    )

    refused = api.create_protest(
        entry["id"],
        f.protest_payload(NON_EXISTENT_UUID),
        users.participant_headers(runner["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_ATTEMPT_NOT_FOUND.value, expected_status=404
    )
    after = fx.read_entry(api, entry["id"])
    assert after["protest_rounds"] == 0
    _rows, meta = validate_paginated(
        api.list_entry_attempts(entry["id"], users.DIRECTOR)
    )
    assert meta["total_count"] == 1


# ─── errors / the team roster minimum at the gun ─────────────────────────


def _team_heat_with_one_checked_in(api):
    """A RELEASED team heat whose only T-RED squad is half at bag check.

    Returns `(heat, entry_checked_in, entry_registered)`.
    """
    _parcel, course, _stations = _staffed_published_course(api)
    division = fx.division(
        api,
        name="Team Relay",
        division_type=constants.DIVISION_TEAM,
        team_size_min=2,
        team_size_max=4,
    )
    heat = fx.wave(
        api, course["id"], division["id"], wave_code="T1", capacity=40
    )
    first = fx.cleared_participant(api, full_name="Runner One")
    second = fx.cleared_participant(api, full_name="Runner Two")
    entry_one = fx.entry(api, heat["id"], first["id"], 1, team_code="T-RED")
    entry_two = fx.entry(api, heat["id"], second["id"], 2, team_code="T-RED")
    fx.check_in(api, entry_one["id"])
    fx.lock_roster(api, heat["id"])
    released = fx.release(api, heat["id"])
    assert_wave_state(
        released,
        release_status=constants.RELEASE_RELEASED,
        roster_status=constants.ROSTER_LOCKED,
    )
    return heat, entry_one, entry_two


def test_a_short_team_blocks_the_gun_and_seals_nothing(api):
    """PRD §3.6: "When the heat's division has `division_type` of `TEAM`, every distinct `team_code` present among the heat's entries must have at least `team_size_min` entries whose `progress_status` reads `CHECKED_IN`; a short team refuses the start with `ERR_TEAM_INCOMPLETE`."

    Design: Corner/errors/a_team_heat_cannot_start_with_half_a_team_checked_in
    """
    heat, entry_one, entry_two = _team_heat_with_one_checked_in(api)

    refused = api.start_wave(heat["id"], users.DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_TEAM_INCOMPLETE.value, expected_status=409)

    # Nothing was sealed and nobody was started by the refused gun.
    after = fx.read_wave(api, heat["id"])
    assert_wave_state(
        after,
        release_status=constants.RELEASE_RELEASED,
        roster_status=constants.ROSTER_LOCKED,
    )
    assert after["actual_start_utc"] is None
    assert_entry_state(
        fx.read_entry(api, entry_one["id"]),
        progress_status=constants.PROGRESS_CHECKED_IN,
    )
    assert_entry_state(
        fx.read_entry(api, entry_two["id"]),
        progress_status=constants.PROGRESS_REGISTERED,
    )


def test_checking_the_second_runner_in_clears_the_team_minimum(api):
    """PRD §3.5: "The heat's `roster_status` must be `OPEN` or `LOCKED`; once it is `SEALED`, check-in is refused with `ERR_ROSTER_CLOSED`."

    Design: Corner/errors/a_team_heat_cannot_start_with_half_a_team_checked_in
    """
    heat, entry_one, entry_two = _team_heat_with_one_checked_in(api)
    validate_error(
        api.start_wave(heat["id"], users.DIRECTOR),
        ApiErrorId.ERR_TEAM_INCOMPLETE.value,
        expected_status=409,
    )

    # A LOCKED roster still takes a bag-check; only a SEALED one refuses it.
    late = fx.check_in(api, entry_two["id"])
    assert_entry_state(late, progress_status=constants.PROGRESS_CHECKED_IN)

    started = fx.start(api, heat["id"])
    assert_wave_state(
        started,
        release_status=constants.RELEASE_STARTED,
        roster_status=constants.ROSTER_SEALED,
    )
    assert_instant_equals(
        started["actual_start_utc"], constants.DEFAULT_CLOCK_UTC, "actual_start_utc"
    )
    for entry_id in (entry_one["id"], entry_two["id"]):
        assert_entry_state(
            fx.read_entry(api, entry_id),
            progress_status=constants.PROGRESS_STARTED,
        )


# ─── errors / a frozen parcel refuses every downstream class ─────────────


def _frozen_parcel_with_a_drafted_course(api):
    """A parcel frozen by a denied application, with one course already laid.

    Returns `(parcel, course)`.
    """
    parcel = fx.venue(api)
    course = fx.course(api, parcel["id"])
    submitted = fx.submitted_permit(api, parcel["id"])
    denied = validate_success(
        api.decide_permit(
            submitted["id"],
            f.decision_payload(constants.DECISION_DENIED),
            users.OFFICER,
        )
    )
    assert denied["status"] == constants.PERMIT_DENIED
    return parcel, course


def test_a_frozen_parcel_refuses_a_new_course_and_suspends_the_old_one(api):
    """PRD §2.10: "Any design, scheduling, permit-submission, festival-installation or inspection operation attempted against a parcel that is `FROZEN` or `CLOSED_OUT` is rejected with `ERR_VENUE_FROZEN` (HTTP 409)."

    Design: Corner/errors/a_frozen_parcel_refuses_new_design_and_festival_work
    """
    parcel, course = _frozen_parcel_with_a_drafted_course(api)

    refused = api.create_course(
        parcel["id"],
        f.course_payload(
            name="Replacement Loop",
            total_distance_m=8000,
            corral_release_rate_per_min=10.00,
            corral_throughput_capacity=150,
        ),
        users.DESIGNER,
    )
    validate_error(refused, ApiErrorId.ERR_VENUE_FROZEN.value, expected_status=409)

    frozen = fx.read_venue(api, parcel["id"])
    assert frozen["site_posture"] == constants.SITE_POSTURE_FROZEN
    assert frozen["disturbed_area_sqm"] == 0

    # The course already on the parcel is suspended, not removed.
    suspended = fx.read_course(api, course["id"])
    assert_course_capacities(
        suspended,
        status=constants.COURSE_SUSPENDED,
        readiness_posture=constants.READINESS_FROZEN,
    )
    _rows, meta = validate_paginated(api.list_courses(parcel["id"], users.DESIGNER))
    assert meta["total_count"] == 1


def test_a_frozen_parcel_refuses_a_new_festival_installation(api):
    """PRD §2.10: "Any design, scheduling, permit-submission, festival-installation or inspection operation attempted against a parcel that is `FROZEN` or `CLOSED_OUT` is rejected with `ERR_VENUE_FROZEN` (HTTP 409)."

    Design: Corner/errors/a_frozen_parcel_refuses_new_design_and_festival_work
    """
    parcel, _course = _frozen_parcel_with_a_drafted_course(api)

    refused = api.create_festival_service(
        parcel["id"],
        f.festival_service_payload(footprint_sqm=150, capacity=500, water_draw_lpm=0),
        users.OPS,
    )
    validate_error(refused, ApiErrorId.ERR_VENUE_FROZEN.value, expected_status=409)

    _rows, meta = validate_paginated(
        api.list_festival_services(parcel["id"], users.OPS)
    )
    assert meta["total_count"] == 0
    frozen = fx.read_venue(api, parcel["id"])
    assert frozen["site_posture"] == constants.SITE_POSTURE_FROZEN
    assert frozen["disturbed_area_sqm"] == 0
