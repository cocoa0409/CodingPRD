"""Corner-case coverage of the PRD's validation gates and their ordering.

Every test in this file translates exactly one live instance of the
`section: validations` slice of `SCAFFOLD_CORNER_DESIGN.yaml`, and names that
instance on the final `Design:` line of its docstring. Nothing else is probed
here: the design index is the only source of tests.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_entry_state,
    assert_obstacle_staffing,
    assert_rate_equals,
    assert_wave_state,
)

# ─── Private builders for the recipes' canonical parcel and course ───────
#
# The three stations below are the corner index's canonical dry course: design
# rates of 12.00, 7.50 and 12.00 against a corral rate of 12.00, so
# `design_capacity_pph` is 450 and a single heat may carry at most 112. Their
# footprints total 3700 sqm and their ratings 3, 5, 7 score 2.00.

_STATION_SPECS = (
    dict(
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=1,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_NONE,
        penalty_seconds=0,
    ),
    dict(
        name="Mud Trench",
        difficulty_rating=5,
        lane_count=3,
        service_rate_per_min=2.50,
        marshals_required=1,
        footprint_sqm=1500,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_MANDATORY,
        penalty_seconds=120,
    ),
    dict(
        name="Wall Climb",
        difficulty_rating=7,
        lane_count=3,
        service_rate_per_min=3.00,
        marshals_required=1,
        footprint_sqm=1000,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_TIMED_PENALTY,
        penalty_seconds=90,
    ),
)

_VENUE_KWARGS = dict(protected_acreage_sqm=2000, restoration_bond_cents=1000000)


def _unpermitted_parcel(api, **overrides):
    """A registered parcel carrying no land-use application at all."""
    return fx.venue(api, **dict(_VENUE_KWARGS, **overrides))


def _permitted_parcel(api, venue_overrides=None, **permit_overrides):
    """A parcel with exactly one governing permit. Returns (venue, permit)."""
    return fx.permitted_venue(
        api,
        dict(_VENUE_KWARGS, **(venue_overrides or {})),
        **dict(
            dict(
                water_use_allowed=False,
                max_disturbed_area_sqm=5000,
                quiet_hours_start_hour_utc=22,
                quiet_hours_end_hour_utc=6,
            ),
            **permit_overrides,
        ),
    )


def _canonical_course(api, venue_id, **overrides):
    return fx.course(
        api,
        venue_id,
        **dict(
            dict(
                name="Quarry Gauntlet",
                total_distance_m=10000,
                corral_release_rate_per_min=12.00,
                corral_throughput_capacity=200,
            ),
            **overrides,
        ),
    )


def _canonical_stations(api, course_id, overrides=None):
    """Place the three canonical stations, in ascending station order."""
    per_station = overrides or [{}, {}, {}]
    return [
        fx.obstacle(api, course_id, index + 1, **dict(spec, **extra))
        for index, (spec, extra) in enumerate(zip(_STATION_SPECS, per_station))
    ]


def _open_division(api, **overrides):
    return fx.division(
        api,
        **dict(
            dict(
                name="Open Wave",
                division_type=c.DIVISION_OPEN,
                bypass_policy=c.BYPASS_POLICY_ALLOWED_WITH_PENALTY,
                scoring_mode=c.SCORING_GUN_TIME,
                min_age=16,
                team_size_min=1,
                team_size_max=1,
            ),
            **overrides,
        ),
    )


def test_the_quiet_window_wraps_past_midnight_and_its_end_hour_is_free(api):
    """PRD §3.4: "When the start hour is numerically greater than the end hour, the window wraps past midnight and covers the hours from the start hour through 23 together with the hours from 0 up to but not including the end hour."

    Design: Corner/validations/the_quiet_window_wraps_past_midnight_and_its_end_hour_is_free
    """
    parcel, _permit = _permitted_parcel(
        api,
        {"water_access": c.WATER_ACCESS_NONE},
        quiet_hours_start_hour_utc=22,
        quiet_hours_end_hour_utc=6,
    )
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    heat_division = _open_division(api)

    # Hour 23 is on the far side of midnight from the start hour, yet still
    # inside the wrapped window.
    before_midnight = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="N1",
            scheduled_start_utc="2026-09-12T23:00:00.000Z", capacity=100,
        ),
        users.DIRECTOR,
    )
    validate_error(
        before_midnight,
        ApiErrorId.ERR_QUIET_HOURS_VIOLATION.value,
        expected_status=409,
    )

    # Hour 5 is the last hour the wrapped window covers.
    inside_tail = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="N2",
            scheduled_start_utc="2026-09-13T05:00:00.000Z", capacity=100,
        ),
        users.DIRECTOR,
    )
    validate_error(
        inside_tail, ApiErrorId.ERR_QUIET_HOURS_VIOLATION.value, expected_status=409
    )

    # Hour 6 is the end hour itself, which the half-open window excludes.
    at_the_end_hour = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="N3",
            scheduled_start_utc="2026-09-13T06:00:00.000Z", capacity=100,
        ),
        users.DIRECTOR,
    )
    heat = validate_success(at_the_end_hour, expected_status=201)
    assert heat["capacity"] == 100
    assert_wave_state(
        heat, release_status=c.RELEASE_SCHEDULED, roster_status=c.ROSTER_OPEN
    )

    assert_course_capacities(
        fx.read_course(api, laid["id"]), scheduled_capacity_total=100
    )
    _rows, meta = validate_paginated(
        api.list_waves(users.DIRECTOR, {"course_id": laid["id"]})
    )
    assert meta["total_count"] == 1


def test_an_unpermitted_venue_skips_the_quiet_window_entirely(api):
    """PRD §3.4: "When the parcel has no application reading `APPROVED`, this check is skipped entirely rather than treated as a failure."

    Design: Corner/validations/an_unpermitted_venue_skips_the_quiet_window_entirely
    """
    parcel = _unpermitted_parcel(api, water_access=c.WATER_ACCESS_NONE)
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    heat_division = _open_division(api)

    # 23:00 would sit deep inside a 22-to-6 quiet window, but with no permit on
    # the parcel there is no window to sit inside.
    scheduled = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="N1",
            scheduled_start_utc="2026-09-12T23:00:00.000Z", capacity=100,
        ),
        users.DIRECTOR,
    )
    heat = validate_success(scheduled, expected_status=201)
    assert_wave_state(
        heat, release_status=c.RELEASE_SCHEDULED, roster_status=c.ROSTER_OPEN
    )

    _rows, meta = validate_paginated(api.list_permits(parcel["id"], users.OFFICER))
    assert meta["total_count"] == 0

    ledger = fx.read_venue(api, parcel["id"])
    assert ledger["site_posture"] == c.SITE_POSTURE_OPEN
    assert ledger["disturbed_area_sqm"] == 3700
    assert_course_capacities(
        fx.read_course(api, laid["id"]),
        scheduled_capacity_total=100,
        readiness_posture=c.READINESS_FROZEN,
    )


def test_the_role_gate_rejects_the_call_before_the_body_is_ever_parsed(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Corner/validations/the_role_gate_rejects_the_call_before_the_body_is_ever_parsed
    """
    # This body is missing two required fields, so it violates the schema rung
    # as well as the role rung. Role authorisation sits above schema on the
    # ladder, so the wrong role is the answer and the body is never parsed.
    incomplete = f.venue_payload(
        water_access=c.WATER_ACCESS_NONE,
        protected_acreage_sqm=f.OMIT,
        restoration_bond_cents=f.OMIT,
    )

    wrong_role = api.create_venue(incomplete, users.MARSHAL)
    validate_error(
        wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403
    )

    # The same body from an authorised role reaches the schema rung and fails
    # there, which is what proves the first refusal was about the role.
    right_role = api.create_venue(incomplete, users.OFFICER)
    validate_error(
        right_role, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422
    )

    complete = api.create_venue(
        f.venue_payload(
            water_access=c.WATER_ACCESS_NONE,
            protected_acreage_sqm=2000,
            restoration_bond_cents=1000000,
        ),
        users.OFFICER,
    )
    parcel = validate_success(complete, expected_status=201)
    assert parcel["site_posture"] == c.SITE_POSTURE_OPEN
    assert parcel["bond_held_cents"] == 1000000
    assert_bond_ledger_conserved(parcel)

    _rows, meta = validate_paginated(api.list_venues(users.OFFICER))
    assert meta["total_count"] == 1


def test_the_progression_gate_outranks_the_disturbed_area_gate_on_one_call(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Corner/validations/the_progression_gate_outranks_the_disturbed_area_gate_on_one_call
    """
    parcel, _permit = _permitted_parcel(
        api, {"water_access": c.WATER_ACCESS_NONE}, max_disturbed_area_sqm=5000
    )
    # Course A is flat but fits inside the permitted footprint: 3 x 1600 = 4800.
    flat = _canonical_course(api, parcel["id"], name="Flat Loop")
    for index in (1, 2, 3):
        fx.obstacle(
            api, flat["id"], index,
            name=f"Plateau {index}", difficulty_rating=5, lane_count=4,
            service_rate_per_min=3.00, marshals_required=1, footprint_sqm=1600,
            water_contact=False, bypass_mode=c.BYPASS_MODE_NONE, penalty_seconds=0,
        )
    only_flat = api.validate_course(flat["id"], users.DESIGNER)
    validate_error(
        only_flat, ApiErrorId.ERR_PROGRESSION_TOO_FLAT.value, expected_status=422
    )

    # Course B rises properly but pushes the parcel to 6300 sqm of disturbance.
    steep = _canonical_course(api, parcel["id"], name="Steep Loop")
    for index, rating in ((1, 3), (2, 5), (3, 7)):
        fx.obstacle(
            api, steep["id"], index,
            name=f"Rise {index}", difficulty_rating=rating, lane_count=4,
            service_rate_per_min=3.00, marshals_required=1, footprint_sqm=500,
            water_contact=False, bypass_mode=c.BYPASS_MODE_NONE, penalty_seconds=0,
        )
    only_over_area = api.validate_course(steep["id"], users.DESIGNER)
    validate_error(
        only_over_area,
        ApiErrorId.ERR_DISTURBED_AREA_EXCEEDED.value,
        expected_status=409,
    )

    # Course A now violates both gates at once. The design gate sits above the
    # disturbed-area cap on the ladder, so the flatness is still the answer.
    both_violated = api.validate_course(flat["id"], users.DESIGNER)
    validate_error(
        both_violated, ApiErrorId.ERR_PROGRESSION_TOO_FLAT.value, expected_status=422
    )

    flat_after = fx.read_course(api, flat["id"])
    assert_course_capacities(flat_after, status=c.COURSE_DRAFT)
    assert_rate_equals(
        flat_after["difficulty_progression_score"], 0.00,
        "difficulty_progression_score",
    )
    steep_after = fx.read_course(api, steep["id"])
    assert_course_capacities(steep_after, status=c.COURSE_DRAFT)
    assert_rate_equals(
        steep_after["difficulty_progression_score"], 2.00,
        "difficulty_progression_score",
    )
    assert fx.read_venue(api, parcel["id"])["disturbed_area_sqm"] == 6300


def _wet_and_dry_parcels(api):
    """Two POND parcels whose permits disagree about drawing water."""
    dry, _dry_permit = _permitted_parcel(
        api,
        {"name": "Dry Pond Quarry", "water_access": c.WATER_ACCESS_POND},
        water_use_allowed=False,
        max_disturbed_area_sqm=5000,
    )
    wet, _wet_permit = _permitted_parcel(
        api,
        {"name": "Wet Pond Quarry", "water_access": c.WATER_ACCESS_POND},
        water_use_allowed=True,
        max_disturbed_area_sqm=5000,
    )
    return dry, wet


def test_water_contact_is_judged_against_the_permit_not_the_venue_water_access(api):
    """PRD §3.2: "No obstacle on the course may have `water_contact` set to true unless the governing permit has `water_use_allowed` set to true, or the request is refused with `ERR_WATER_USE_NOT_PERMITTED`."

    Design: Corner/validations/water_contact_is_judged_against_the_permit_not_the_venue_water_access
    """
    dry, wet = _wet_and_dry_parcels(api)
    # Both parcels declare a POND, and on both the middle station wades into it.
    dry_course = _canonical_course(api, dry["id"], name="Dry Gauntlet")
    _canonical_stations(api, dry_course["id"], [{}, {"water_contact": True}, {}])
    wet_course = _canonical_course(api, wet["id"], name="Wet Gauntlet")
    _canonical_stations(api, wet_course["id"], [{}, {"water_contact": True}, {}])

    refused = api.validate_course(dry_course["id"], users.DESIGNER)
    validate_error(
        refused, ApiErrorId.ERR_WATER_USE_NOT_PERMITTED.value, expected_status=409
    )
    assert_course_capacities(
        fx.read_course(api, dry_course["id"]), status=c.COURSE_DRAFT
    )

    accepted = validate_success(api.validate_course(wet_course["id"], users.DESIGNER))
    assert accepted["status"] == c.COURSE_VALIDATED
    assert_rate_equals(
        accepted["difficulty_progression_score"], 2.00,
        "difficulty_progression_score",
    )


def test_a_rinse_station_draws_water_only_where_the_permit_allows_it(api):
    """PRD §3.9: "A positive `water_draw_lpm` brings the land authority into it: the parcel must have exactly one governing permit reading `APPROVED`, or the installation is refused with `ERR_PERMIT_NOT_APPROVED`, and that permit's `water_use_allowed` must be true, or it is refused with `ERR_WATER_USE_NOT_PERMITTED`."

    Design: Corner/validations/water_contact_is_judged_against_the_permit_not_the_venue_water_access
    """
    dry, wet = _wet_and_dry_parcels(api)
    rinse = f.festival_service_payload(
        service_type=c.SERVICE_RINSE_STATION,
        footprint_sqm=200,
        capacity=40,
        water_draw_lpm=120,
    )

    # The dry parcel has a pond and an approved permit, and still may not draw.
    refused = api.create_festival_service(dry["id"], dict(rinse), users.OPS)
    validate_error(
        refused, ApiErrorId.ERR_WATER_USE_NOT_PERMITTED.value, expected_status=409
    )
    _rows, meta = validate_paginated(
        api.list_festival_services(dry["id"], users.OPS)
    )
    assert meta["total_count"] == 0

    installed = validate_success(
        api.create_festival_service(wet["id"], dict(rinse), users.OPS),
        expected_status=201,
    )
    assert installed["status"] == c.SERVICE_OPEN
    assert installed["water_draw_lpm"] == 120


def test_restoration_areas_sum_to_the_disturbed_area_and_equality_passes(api):
    """PRD §3.9: "That area is also the weight the task carries in the bond split, so a task may not claim ground that was never disturbed: the sum of `area_sqm` over every remediation task on the parcel, the candidate included, must not exceed the parcel's `disturbed_area_sqm`, and a task that would push the total past it is refused with `ERR_RESTORATION_AREA_EXCEEDED`."

    Design: Corner/validations/restoration_areas_sum_to_the_disturbed_area_and_equality_passes
    """
    parcel, _permit = _permitted_parcel(api, {"water_access": c.WATER_ACCESS_NONE})
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    # 1200 + 1500 + 1000 of station footprint is 3700 sqm of disturbed ground.

    first = validate_success(
        api.create_restoration_task(
            parcel["id"],
            f.restoration_task_payload(2000, task_type=c.TASK_TYPE_DECOMPACT),
            users.OPS,
        ),
        expected_status=201,
    )
    assert first["area_sqm"] == 2000

    # 2000 + 1700 is exactly 3700: equality passes, only a strict excess fails.
    second = validate_success(
        api.create_restoration_task(
            parcel["id"],
            f.restoration_task_payload(1700, task_type=c.TASK_TYPE_RESEED),
            users.OPS,
        ),
        expected_status=201,
    )
    assert second["status"] == c.TASK_PENDING
    assert second["bond_release_cents"] == 0

    # One more square metre is one too many.
    refused = api.create_restoration_task(
        parcel["id"],
        f.restoration_task_payload(1, task_type=c.TASK_TYPE_DEBRIS_SWEEP),
        users.OPS,
    )
    validate_error(
        refused, ApiErrorId.ERR_RESTORATION_AREA_EXCEEDED.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api.list_restoration_tasks(parcel["id"], users.OFFICER)
    )
    assert meta["total_count"] == 2

    ledger = fx.read_venue(api, parcel["id"])
    assert ledger["disturbed_area_sqm"] == 3700
    assert ledger["bond_released_cents"] == 0
    assert_bond_ledger_conserved(ledger)


def test_team_code_is_mandatory_for_team_heats_and_forbidden_elsewhere(api):
    """PRD §3.5: "Division shape rules apply: `team_code` is required when the heat's division has `division_type` of `TEAM` and is forbidden when it has any other `division_type`, and a single `team_code` may not accumulate more than the division's `team_size_max` entries inside one heat; any of these is refused with `ERR_DIVISION_RULE_VIOLATION`."

    Design: Corner/validations/team_code_is_mandatory_for_team_heats_and_forbidden_elsewhere
    """
    parcel = _unpermitted_parcel(api, water_access=c.WATER_ACCESS_NONE)
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    squads = fx.division(
        api,
        name="Squad Wave",
        division_type=c.DIVISION_TEAM,
        bypass_policy=c.BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=c.SCORING_GUN_TIME,
        min_age=16,
        team_size_min=2,
        team_size_max=4,
    )
    solos = _open_division(api)
    team_heat = fx.wave(
        api, laid["id"], squads["id"], wave_code="T1",
        scheduled_start_utc="2026-09-12T08:00:00.000Z", capacity=20,
    )
    open_heat = fx.wave(
        api, laid["id"], solos["id"], wave_code="O1",
        scheduled_start_utc="2026-09-12T09:00:00.000Z", capacity=20,
    )
    one = fx.cleared_participant(api, birth_year=2000)
    two = fx.cleared_participant(api, birth_year=2000)

    missing_code = api.create_entry(
        team_heat["id"], f.entry_payload(one["id"], 1), users.OPS
    )
    validate_error(
        missing_code, ApiErrorId.ERR_DIVISION_RULE_VIOLATION.value, expected_status=409
    )
    on_a_team = validate_success(
        api.create_entry(
            team_heat["id"],
            f.entry_payload(one["id"], 1, team_code="T-RED"),
            users.OPS,
        ),
        expected_status=201,
    )
    assert on_a_team["team_code"] == "T-RED"
    assert_entry_state(on_a_team, progress_status=c.PROGRESS_REGISTERED)

    stray_code = api.create_entry(
        open_heat["id"], f.entry_payload(two["id"], 1, team_code="T-RED"), users.OPS
    )
    validate_error(
        stray_code, ApiErrorId.ERR_DIVISION_RULE_VIOLATION.value, expected_status=409
    )
    alone = validate_success(
        api.create_entry(open_heat["id"], f.entry_payload(two["id"], 1), users.OPS),
        expected_status=201,
    )
    assert_entry_state(alone, progress_status=c.PROGRESS_REGISTERED)

    assert fx.read_wave(api, team_heat["id"])["assigned_count"] == 1
    assert fx.read_wave(api, open_heat["id"])["assigned_count"] == 1


def test_the_permit_gate_runs_before_the_design_gates_on_validate(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Corner/validations/the_permit_gate_runs_before_the_design_gates_on_validate
    """
    parcel = _unpermitted_parcel(api, water_access=c.WATER_ACCESS_NONE)
    pending_permit = fx.submitted_permit(
        api, parcel["id"], water_use_allowed=False, max_disturbed_area_sqm=5000
    )
    assert pending_permit["status"] == c.PERMIT_SUBMITTED
    # Only two stations, so the course is too short as well as unpermitted.
    laid = _canonical_course(api, parcel["id"], name="Short Loop")
    fx.obstacle(api, laid["id"], 1, **_STATION_SPECS[0])
    fx.obstacle(api, laid["id"], 2, **_STATION_SPECS[2])

    undecided = api.validate_course(laid["id"], users.DESIGNER)
    validate_error(
        undecided, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value, expected_status=409
    )
    # The refused validate leaves the course untouched: PRD §3.2 lists the
    # `readiness_posture` recompute as an effect of a *successful* validation,
    # and §3.3 enumerates the recompute triggers (permit decided, course
    # validated or published, shift confirmed or vacated, heat scheduled) —
    # none of which a rejected request fires. The course therefore still
    # carries the `RESTRICTED` posture §3.2 mints it with.
    assert_course_capacities(
        fx.read_course(api, laid["id"]), status=c.COURSE_DRAFT
    )

    decided = validate_success(
        api.decide_permit(
            pending_permit["id"],
            f.decision_payload(c.DECISION_APPROVED, decision_note="Approved as filed"),
            users.OFFICER,
        )
    )
    assert decided["status"] == c.PERMIT_APPROVED
    assert_course_capacities(
        fx.read_course(api, laid["id"]), readiness_posture=c.READINESS_RESTRICTED
    )

    # With the permit rung satisfied the design rung finally gets to answer.
    still_short = api.validate_course(laid["id"], users.DESIGNER)
    validate_error(
        still_short, ApiErrorId.ERR_COURSE_TOO_SHORT.value, expected_status=422
    )

    unchanged = fx.read_course(api, laid["id"])
    assert_course_capacities(unchanged, status=c.COURSE_DRAFT)
    assert unchanged["obstacle_count"] == 2


def _heat_under_way_with_one_station_abandoned(api):
    """A STARTED heat whose middle station has just lost its only marshal.

    Returns (heat, entry, stations) with station 1 reading `MARSHALED` and
    station 2 reading `UNSTAFFED`.
    """
    parcel, _permit = _permitted_parcel(api, {"water_access": c.WATER_ACCESS_NONE})
    laid = _canonical_course(api, parcel["id"])
    stations = _canonical_stations(api, laid["id"])
    fx.published_course(api, laid["id"])
    shifts = [
        fx.marshal_shift(api, laid["id"], station["id"], staff_person_id=person)
        for person, station in zip(
            (c.STAFF_PERSON_1, c.STAFF_PERSON_2, c.STAFF_PERSON_3), stations
        )
    ]
    fx.medic_shift(api, laid["id"], staff_person_id=c.STAFF_MEDIC_1)
    heat = fx.wave(
        api, laid["id"], _open_division(api)["id"], wave_code="S1",
        scheduled_start_utc=f.GUN_UTC, capacity=50,
    )
    entry = fx.checked_in_entry(api, heat["id"], bib_number=1)
    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    started = fx.start(api, heat["id"])
    assert_wave_state(started, release_status=c.RELEASE_STARTED)

    fx.vacate(api, shifts[1]["id"], "Ran to the medical tent")
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[0]["id"]),
        staffing_state=c.STAFFING_MARSHALED,
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[1]["id"]),
        staffing_state=c.STAFFING_UNSTAFFED,
    )
    return heat, entry, stations


def test_a_skipped_unmarshaled_outcome_is_refused_at_a_marshaled_station(api):
    """PRD §3.7: "Conversely an outcome of `SKIPPED_UNMARSHALED` asserts the opposite, so the obstacle's `staffing_state` must be exactly `UNSTAFFED`; recording it at a station reading `PARTIAL` or `MARSHALED` is refused with `ERR_OBSTACLE_MARSHALED`."

    Design: Corner/validations/the_marshaling_truth_rule_refuses_both_the_wrong_outcome_and_its_mirror
    """
    heat, entry, stations = _heat_under_way_with_one_station_abandoned(api)

    mirror = api.create_attempt(
        entry["id"],
        f.attempt_payload(stations[0]["id"], c.OUTCOME_SKIPPED_UNMARSHALED),
        users.MARSHAL,
    )
    validate_error(
        mirror, ApiErrorId.ERR_OBSTACLE_MARSHALED.value, expected_status=409
    )

    # The same outcome at the abandoned station is the honest reading.
    honest = validate_success(
        api.create_attempt(
            entry["id"],
            f.attempt_payload(stations[1]["id"], c.OUTCOME_SKIPPED_UNMARSHALED),
            users.MARSHAL,
        ),
        expected_status=201,
    )
    assert honest["outcome"] == c.OUTCOME_SKIPPED_UNMARSHALED
    assert honest["recorded_by_user_id"] == c.USER_MARSHAL_1

    _rows, meta = validate_paginated(
        api.list_entry_attempts(entry["id"], users.DIRECTOR)
    )
    assert meta["total_count"] == 1
    assert_wave_state(
        fx.read_wave(api, heat["id"]), release_status=c.RELEASE_STARTED
    )


def test_a_completed_outcome_is_refused_at_an_unstaffed_station(api):
    """PRD §3.7: "An outcome of `COMPLETED`, `BYPASSED` or `FAILED_PENALTY` asserts that somebody was standing there to observe it, so the obstacle's `staffing_state` must be anything other than `UNSTAFFED`; recording one of those three at a station with zero confirmed marshals is refused with `ERR_OBSTACLE_UNMARSHALED`."

    Design: Corner/validations/the_marshaling_truth_rule_refuses_both_the_wrong_outcome_and_its_mirror
    """
    _heat, entry, stations = _heat_under_way_with_one_station_abandoned(api)

    unwitnessed = api.create_attempt(
        entry["id"],
        f.attempt_payload(stations[1]["id"], c.OUTCOME_COMPLETED),
        users.MARSHAL,
    )
    validate_error(
        unwitnessed, ApiErrorId.ERR_OBSTACLE_UNMARSHALED.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api.list_entry_attempts(entry["id"], users.DIRECTOR)
    )
    assert meta["total_count"] == 0
