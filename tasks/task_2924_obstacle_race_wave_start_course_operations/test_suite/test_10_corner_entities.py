"""Corner coverage: the `entities` section of the breadth index.

Every test in this module translates exactly one instance of
`SCAFFOLD_CORNER_DESIGN.yaml`'s `section: entities` block and names it on the
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
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_instant_equals,
    assert_no_version_fields,
    assert_obstacle_staffing,
    assert_rate_equals,
    assert_timestamp_millis,
    assert_version,
    assert_whole_cents,
    ids_of,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    CLEARANCE_CLEARED,
    COURSE_DRAFT,
    DEFAULT_CLOCK_UTC,
    DIVISION_COMPETITIVE,
    OUTCOME_COMPLETED,
    READINESS_RESTRICTED,
    ROLE_OBSTACLE_MARSHAL,
    SCORING_CHIP_TIME,
    SERVICE_OPEN,
    SERVICE_SPECTATOR_ZONE,
    SITE_POSTURE_OPEN,
    STAFFING_MARSHALED,
    STAFFING_UNSTAFFED,
    STAFF_PERSON_1,
    STAFF_PERSON_2,
    STAFF_PERSON_3,
    TERRAIN_FOREST,
    TERRAIN_QUARRY,
    USER_MARSHAL_7,
    WATER_ACCESS_NONE,
    WATER_ACCESS_POND,
    WATER_ACCESS_RIVER,
)

# ─── The canonical parcel, course and station set of the design index ────

#: The permit horizon sits well past every instant these tests use, so no
#: clock movement in this module ever expires the governing application.
_PERMIT_VALID_UNTIL_UTC = "2026-12-31T00:00:00.000Z"

#: The course of the index: a 12.00-per-minute corral feeding 200 at a time.
_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

#: Three dry primary stations whose design rates are 12.00, 7.50 and 12.00
#: (station 3's 9.00 lane rate plus 4.50 relief is capped by the corral), so
#: `design_capacity_pph` is 450 and the 15-minute heat ceiling is 112.
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
_ATTEMPT_UTC = "2026-09-12T08:03:00.000Z"


def _draft_course(api, **venue_overrides):
    """One parcel carrying one DRAFT course and no stations yet."""
    parcel = fx.venue(
        api,
        protected_acreage_sqm=2000,
        restoration_bond_cents=500000,
        **venue_overrides,
    )
    laid = fx.course(api, parcel["id"], **_COURSE_KWARGS)
    return parcel, laid


def _three_station_draft(api, **venue_overrides):
    """The canonical three-primary DRAFT course on a fresh parcel."""
    parcel = fx.venue(
        api,
        protected_acreage_sqm=2000,
        restoration_bond_cents=500000,
        **venue_overrides,
    )
    laid, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
    return parcel, laid, stations


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
    div = fx.division(api, min_age=16)
    heat = fx.wave(
        api,
        laid["id"],
        div["id"],
        wave_code="S1",
        scheduled_start_utc=_GUN_UTC,
        capacity=10,
    )
    human = fx.cleared_participant(api)
    ent = fx.entry(api, heat["id"], human["id"], 1)
    fx.check_in(api, ent["id"], chip_start_offset_seconds=20)
    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.set_clock(api, _GUN_UTC)
    fx.start(api, heat["id"])
    return laid, stations, heat, ent, human


# ─── Instance: venue_creation_returns_the_full_declared_field_set_with_zeroed_ledger


def test_venue_creation_returns_declared_fields_with_zeroed_ledger(api):
    """PRD §3.1: "A freshly registered parcel reads `site_posture` of `OPEN`, `disturbed_area_sqm` of 0, `bond_released_cents` and `bond_forfeited_cents` of 0, and `bond_held_cents` equal to the whole `restoration_bond_cents`."

    Design: Corner/entities/venue_creation_returns_the_full_declared_field_set_with_zeroed_ledger
    """
    response = api.create_venue(
        f.venue_payload(
            name="Ridgeline Quarry",
            terrain_type=TERRAIN_QUARRY,
            water_access=WATER_ACCESS_POND,
            land_use_zone="AG-2",
            protected_acreage_sqm=2000,
            restoration_bond_cents=1000000,
        ),
        users.OFFICER,
    )
    parcel = validate_success(response, expected_status=201)

    # The six posted input fields come back exactly as filed.
    assert parcel["name"] == "Ridgeline Quarry"
    assert parcel["terrain_type"] == TERRAIN_QUARRY
    assert parcel["water_access"] == WATER_ACCESS_POND
    assert parcel["land_use_zone"] == "AG-2"
    assert parcel["protected_acreage_sqm"] == 2000
    assert parcel["restoration_bond_cents"] == 1000000

    # The declared opening posture and the zeroed ledger.
    assert parcel["site_posture"] == SITE_POSTURE_OPEN
    assert parcel["disturbed_area_sqm"] == 0
    assert parcel["bond_released_cents"] == 0
    assert parcel["bond_forfeited_cents"] == 0
    assert parcel["bond_held_cents"] == 1000000
    assert_whole_cents(parcel["bond_held_cents"], "bond_held_cents")
    assert_bond_ledger_conserved(parcel)

    # The common properties of a living row.
    assert_version(parcel, 1, "venue")
    assert_timestamp_millis(parcel["created_at"], "created_at")
    assert_timestamp_millis(parcel["updated_at"], "updated_at")
    assert_instant_equals(parcel["created_at"], DEFAULT_CLOCK_UTC, "created_at")


# ─── Instance: get_one_obstacle_returns_the_stored_row_with_its_computed_rates


def test_obstacle_design_clearance_rate_is_capped_by_the_corral_rate(api):
    """PRD §3.2: "Add the design relief to the lane rate, take whichever is smaller of that sum and the parent course's `corral_release_rate_per_min`, and round the result half up to two decimal places."

    Design: Corner/entities/get_one_obstacle_returns_the_stored_row_with_its_computed_rates
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)
    placed = fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )

    station = validate_success(api.get_obstacle(placed["id"], users.MARSHAL))

    assert station["id"] == placed["id"]
    assert station["course_id"] == laid["id"]
    assert station["paired_obstacle_id"] is None
    # 4 lanes at 3.00 is a 12.00 lane rate; bypass_mode NONE adds no relief;
    # the 12.00 corral rate is the ceiling, so the design rate is 12.00.
    assert_rate_equals(
        station["design_clearance_rate_per_min"],
        12.00,
        "design_clearance_rate_per_min",
    )
    # The stored inputs are echoed back unchanged.
    assert station["lane_count"] == 4
    assert station["station_index"] == 1
    assert station["difficulty_rating"] == 3
    assert station["marshals_required"] == 2
    assert station["footprint_sqm"] == 1200
    assert station["water_contact"] is False
    assert station["bypass_mode"] == BYPASS_MODE_NONE
    assert station["penalty_seconds"] == 0


def test_unstaffed_obstacle_reads_zero_effective_rate(api):
    """PRD §3.2: "Placing an obstacle also computes that obstacle's `effective_clearance_rate_per_min` by the live rule of §3.3 — which, for a station that has just been placed and therefore has a `confirmed_marshal_count` of 0 and a `staffing_state` of `UNSTAFFED`, evaluates to 0.00 — and it recomputes the parent course's `obstacle_count`, `difficulty_progression_score`, `design_capacity_pph` and `bottleneck_capacity_pph` along with the parcel's `disturbed_area_sqm`."

    Design: Corner/entities/get_one_obstacle_returns_the_stored_row_with_its_computed_rates
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)
    placed = fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )

    station = validate_success(api.get_obstacle(placed["id"], users.MARSHAL))

    assert_obstacle_staffing(
        station,
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
        effective_rate=0.00,
    )


# ─── Instance: list_venues_paginates_with_total_count_and_has_more


def _three_parcels(api):
    """Two QUARRY parcels and one FOREST parcel, registered in that order."""
    quarry_a = fx.venue(
        api,
        name="Ridgeline Quarry",
        terrain_type=TERRAIN_QUARRY,
        water_access=WATER_ACCESS_POND,
        land_use_zone="AG-2",
        protected_acreage_sqm=2000,
        restoration_bond_cents=500000,
    )
    quarry_b = fx.venue(
        api,
        name="Southpit Quarry",
        terrain_type=TERRAIN_QUARRY,
        water_access=WATER_ACCESS_RIVER,
        land_use_zone="AG-3",
        protected_acreage_sqm=500,
        restoration_bond_cents=400000,
    )
    woods = fx.venue(
        api,
        name="Hollow Woods",
        terrain_type=TERRAIN_FOREST,
        water_access=WATER_ACCESS_NONE,
        land_use_zone="RU-1",
        protected_acreage_sqm=9000,
        restoration_bond_cents=300000,
    )
    return quarry_a, quarry_b, woods


def test_list_venues_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List responses populate four pagination fields inside `meta`: `limit` and `offset` echo the effective values actually applied, `total_count` reports the number of rows matching the filter before the limit and offset window is taken, and `has_more` is true when rows matching the filter remain beyond the returned window."

    Design: Corner/entities/list_venues_paginates_with_total_count_and_has_more
    """
    quarry_a, quarry_b, woods = _three_parcels(api)

    first_page, first_meta = validate_paginated(
        api.list_venues(users.OFFICER, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_venues(users.OFFICER, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2

    # The two windows together cover the whole collection exactly once.
    seen = ids_of(first_page) + ids_of(second_page)
    assert len(seen) == len(set(seen)), f"a parcel was paged twice: {seen}"
    assert set(seen) == {quarry_a["id"], quarry_b["id"], woods["id"]}


def test_list_venues_filters_by_terrain_type(api):
    """PRD §3.1: "Parcels can be listed with an optional filter on `terrain_type` and an optional filter on `site_posture`, and each parcel can be read individually with its live disturbed-area total and all three bond ledger columns."

    Design: Corner/entities/list_venues_paginates_with_total_count_and_has_more
    """
    _, _, woods = _three_parcels(api)

    rows, meta = validate_paginated(
        api.list_venues(
            users.OFFICER,
            params={"terrain_type": TERRAIN_FOREST, "limit": 10, "offset": 0},
        )
    )
    assert ids_of(rows) == [woods["id"]]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ─── Instance: get_unknown_venue_id_returns_venue_not_found


def test_get_unknown_venue_id_returns_venue_not_found(api):
    """PRD §2.6: "The applicable code is `ERR_VENUE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_OBSTACLE_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND` or `ERR_RESTORATION_TASK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_unknown_venue_id_returns_venue_not_found
    """
    parcel = fx.venue(api, protected_acreage_sqm=2000, restoration_bond_cents=500000)

    validate_error(
        api.get_venue(NON_EXISTENT_UUID, users.OFFICER),
        ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        expected_status=404,
    )

    # The collection itself is intact: the real parcel still reads back.
    stored = validate_success(api.get_venue(parcel["id"], users.OFFICER))
    assert stored["id"] == parcel["id"]


# ─── Instance: create_obstacle_without_lane_count_returns_invalid_request


def test_create_obstacle_without_lane_count_returns_invalid_request(api):
    """PRD §2.6: "Required fields present, types correct, enum members drawn from the declared sets, and numeric bounds respected — `limit` between 1 and 100 inclusive, `offset` at least 0, `difficulty_rating` between 1 and 10 inclusive, `lane_count` at least 1, a wave's `capacity` at least 1, `area_sqm` strictly greater than 0, and each quiet-hour field between 0 and 23 inclusive."

    Design: Corner/entities/create_obstacle_without_lane_count_returns_invalid_request
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)

    validate_error(
        api.create_obstacle(
            laid["id"],
            f.obstacle_payload(
                1,
                name="Cargo Net",
                difficulty_rating=3,
                lane_count=f.OMIT,
                service_rate_per_min=3.00,
                marshals_required=2,
                footprint_sqm=1200,
                water_contact=False,
                bypass_mode=BYPASS_MODE_NONE,
                penalty_seconds=0,
            ),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=422,
    )

    # Nothing was persisted by the refused placement.
    stored = fx.read_course(api, laid["id"])
    assert stored["obstacle_count"] == 0
    assert stored["design_capacity_pph"] == 0

    rows, meta = validate_paginated(
        api.list_obstacles(
            users.DESIGNER,
            params={"course_id": laid["id"], "limit": 10, "offset": 0},
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


# ─── Instance: omitted_optional_fields_take_their_declared_defaults


def test_waiver_without_medical_flags_clears_the_participant(api):
    """PRD §3.5: "When none of the three blocking conditions `CARDIAC`, `PREGNANCY` or `RECENT_SURGERY` appears in `medical_flags`, the participant advances `PENDING → CLEARED`."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    human = fx.participant(
        api,
        full_name="Ada Rock",
        birth_year=2000,
        email="ada@example.com",
        chip_id="CHIP-001",
    )

    # The waiver carries a signature and no medical_flags array at all.
    signed = validate_success(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(signature_name="Ada Rock"),
            users.participant_headers(human["id"]),
        )
    )

    assert signed["medical_flags"] == []
    assert signed["waiver_signed"] is True
    assert signed["clearance_status"] == CLEARANCE_CLEARED


def test_festival_service_without_water_draw_defaults_to_zero(api):
    """PRD §3.9: "A `SiteOpsLead` or a `RaceDirector` installs a festival service on the parcel by naming its `service_type` — one of `BAG_CHECK`, `RINSE_STATION` or `SPECTATOR_ZONE` — its `footprint_sqm` of ground disturbance strictly greater than 0, the `capacity` of people it serves at once (at least 1), and optionally its `water_draw_lpm`, the litres per minute it draws from the parcel's water source, which defaults to 0 and must be at least 0."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    parcel = fx.venue(
        api,
        water_access=WATER_ACCESS_POND,
        protected_acreage_sqm=2000,
        restoration_bond_cents=500000,
    )

    installed = validate_success(
        api.create_festival_service(
            parcel["id"],
            f.festival_service_payload(
                service_type=SERVICE_SPECTATOR_ZONE,
                footprint_sqm=600,
                capacity=900,
                water_draw_lpm=f.OMIT,
            ),
            users.OPS,
        ),
        expected_status=201,
    )

    assert installed["water_draw_lpm"] == 0
    assert installed["status"] == SERVICE_OPEN


def test_obstacle_without_paired_obstacle_id_is_primary(api):
    """PRD §3.2: "An obstacle whose `paired_obstacle_id` is null is a **primary** obstacle — a real station on the course."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)

    # The placement supplies every required field and no paired_obstacle_id.
    placed = validate_success(
        api.create_obstacle(
            laid["id"],
            f.obstacle_payload(
                1,
                name="Cargo Net",
                difficulty_rating=3,
                lane_count=4,
                service_rate_per_min=3.00,
                marshals_required=2,
                footprint_sqm=1200,
                water_contact=False,
                bypass_mode=BYPASS_MODE_NONE,
                penalty_seconds=0,
            ),
            users.DESIGNER,
        ),
        expected_status=201,
    )
    assert placed["paired_obstacle_id"] is None

    # As the course's only primary station it drives design_capacity_pph.
    stored = fx.read_course(api, laid["id"])
    assert_course_capacities(stored, design_capacity_pph=720)


def test_disturbed_area_sums_obstacle_and_installation_footprints(api):
    """PRD §3.1: "It is the sum of `footprint_sqm` over every `Obstacle` standing on any `Course` of that parcel — regardless of whether that course reads `DRAFT`, `VALIDATED`, `PUBLISHED`, `SUSPENDED` or `COMPLETED` — plus the sum of `footprint_sqm` over every `FestivalService` installed on the parcel, with no status filter at all."

    Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
    """
    parcel, laid = _draft_course(api, water_access=WATER_ACCESS_POND)
    fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )
    fx.festival_service(
        api,
        parcel["id"],
        service_type=SERVICE_SPECTATOR_ZONE,
        footprint_sqm=600,
        capacity=900,
        water_draw_lpm=f.OMIT,
    )

    stored = fx.read_venue(api, parcel["id"])
    assert stored["disturbed_area_sqm"] == 1800


# ─── Instance: computed_course_fields_ignore_client_supplied_values


def test_new_course_reads_draft_restricted_with_zeroed_aggregates(api):
    """PRD §3.2: "A new course reads `status` of `DRAFT` and `readiness_posture` of `RESTRICTED`, with `obstacle_count`, `difficulty_progression_score`, `design_capacity_pph`, `bottleneck_capacity_pph`, `medic_headcount`, `water_safety_headcount` and `scheduled_capacity_total` all at 0."

    Design: Corner/entities/computed_course_fields_ignore_client_supplied_values
    """
    parcel = fx.venue(
        api,
        water_access=WATER_ACCESS_POND,
        protected_acreage_sqm=2000,
        restoration_bond_cents=500000,
    )

    laid = validate_success(
        api.create_course(parcel["id"], f.course_payload(**_COURSE_KWARGS), users.DESIGNER),
        expected_status=201,
    )

    assert_course_capacities(
        laid,
        design_capacity_pph=0,
        bottleneck_capacity_pph=0,
        scheduled_capacity_total=0,
        readiness_posture=READINESS_RESTRICTED,
        status=COURSE_DRAFT,
    )
    assert laid["obstacle_count"] == 0
    assert laid["medic_headcount"] == 0
    assert laid["water_safety_headcount"] == 0
    assert_rate_equals(
        laid["difficulty_progression_score"], 0.00, "difficulty_progression_score"
    )


def test_placing_one_station_recomputes_design_capacity_pph(api):
    """PRD §3.2: "`design_capacity_pph` is the staffing-independent throughput of the course in participants per hour: consider only the primary obstacles, take the smallest `design_clearance_rate_per_min` among them, multiply by 60 to convert per-minute into per-hour, and discard any fractional part; when the course has no primary obstacle at all the value is 0."

    Design: Corner/entities/computed_course_fields_ignore_client_supplied_values
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)
    fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )

    stored = validate_success(api.get_course(laid["id"], users.DESIGNER))

    assert stored["obstacle_count"] == 1
    # The lone primary clears 12.00 per minute, so 12.00 * 60 == 720; the
    # live twin is still 0 because nobody is rostered at the station yet.
    assert_course_capacities(
        stored,
        design_capacity_pph=720,
        bottleneck_capacity_pph=0,
        status=COURSE_DRAFT,
        readiness_posture=READINESS_RESTRICTED,
    )


def test_single_station_course_scores_zero_progression(api):
    """PRD §3.2: "When the course has fewer than two primary stations the score is 0.00."

    Design: Corner/entities/computed_course_fields_ignore_client_supplied_values
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)
    fx.obstacle(
        api,
        laid["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=2,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )

    stored = fx.read_course(api, laid["id"])
    assert_rate_equals(
        stored["difficulty_progression_score"], 0.00, "difficulty_progression_score"
    )


# ─── Instance: attempt_recorded_at_and_recorder_identity_are_stamped_by_the_server


def test_attempt_stamps_recorded_at_and_recorder_identity(api):
    """PRD §3.7: "Recording an attempt stamps `recorded_at` from the logical clock — this instant, not the insertion order, is the chronological key for penalty accumulation — together with `recorded_by_user_id` and `recorded_by_role` taken from the acting `X-User-ID` and `X-User-Role` headers."

    Design: Corner/entities/attempt_recorded_at_and_recorder_identity_are_stamped_by_the_server
    """
    _, stations, _, ent, _ = _started_heat_with_one_runner(api)
    fx.set_clock(api, _ATTEMPT_UTC)

    # The card carries only the station and the outcome: no instant, no
    # identity and no staffing snapshot is a client input.
    card = validate_success(
        api.create_attempt(
            ent["id"],
            f.attempt_payload(stations[0]["id"], OUTCOME_COMPLETED),
            users.MARSHAL_7,
        ),
        expected_status=201,
    )

    assert_instant_equals(card["recorded_at"], _ATTEMPT_UTC, "recorded_at")
    assert card["recorded_by_user_id"] == USER_MARSHAL_7
    assert card["recorded_by_role"] == ROLE_OBSTACLE_MARSHAL
    assert card["entry_id"] == ent["id"]
    assert card["provisional_penalty_seconds"] == 0


def test_attempt_snapshots_the_station_staffing_state(api):
    """PRD §3.7: "Because a station can lose its last marshal mid-heat, each attempt also snapshots the station's staffing at the moment of recording into `obstacle_staffing_state_at_record`, which holds `UNSTAFFED`, `PARTIAL` or `MARSHALED` and is never revised afterwards."

    Design: Corner/entities/attempt_recorded_at_and_recorder_identity_are_stamped_by_the_server
    """
    _, stations, _, ent, _ = _started_heat_with_one_runner(api)
    fx.set_clock(api, _ATTEMPT_UTC)

    card = validate_success(
        api.create_attempt(
            ent["id"],
            f.attempt_payload(stations[0]["id"], OUTCOME_COMPLETED),
            users.MARSHAL_7,
        ),
        expected_status=201,
    )

    # Station 1 needs one marshal and has one confirmed, so it reads MARSHALED
    # at the instant the card is written.
    assert card["obstacle_staffing_state_at_record"] == STAFFING_MARSHALED
    assert card["obstacle_id"] == stations[0]["id"]


# ─── Instance: unknown_enum_member_on_obstacle_creation_returns_invalid_request


def test_unknown_bypass_mode_returns_invalid_request(api):
    """PRD §2.6: "Required fields present, types correct, enum members drawn from the declared sets, and numeric bounds respected — `limit` between 1 and 100 inclusive, `offset` at least 0, `difficulty_rating` between 1 and 10 inclusive, `lane_count` at least 1, a wave's `capacity` at least 1, `area_sqm` strictly greater than 0, and each quiet-hour field between 0 and 23 inclusive."

    Design: Corner/entities/unknown_enum_member_on_obstacle_creation_returns_invalid_request
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)

    # PENALTY_ALLOWED is not one of the four declared bypass modes.
    validate_error(
        api.create_obstacle(
            laid["id"],
            f.obstacle_payload(
                1,
                name="Cargo Net",
                difficulty_rating=3,
                lane_count=4,
                service_rate_per_min=3.00,
                marshals_required=2,
                footprint_sqm=1200,
                water_contact=False,
                bypass_mode="PENALTY_ALLOWED",
                penalty_seconds=0,
            ),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=422,
    )

    assert fx.read_course(api, laid["id"])["obstacle_count"] == 0


def test_station_index_below_one_returns_invalid_request(api):
    """PRD §2.6: "Required fields present, types correct, enum members drawn from the declared sets, and numeric bounds respected — `limit` between 1 and 100 inclusive, `offset` at least 0, `difficulty_rating` between 1 and 10 inclusive, `lane_count` at least 1, a wave's `capacity` at least 1, `area_sqm` strictly greater than 0, and each quiet-hour field between 0 and 23 inclusive."

    Design: Corner/entities/unknown_enum_member_on_obstacle_creation_returns_invalid_request
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)

    # station_index is 1-based, so 0 is out of bounds.
    validate_error(
        api.create_obstacle(
            laid["id"],
            f.obstacle_payload(
                0,
                name="Cargo Net",
                difficulty_rating=3,
                lane_count=4,
                service_rate_per_min=3.00,
                marshals_required=2,
                footprint_sqm=1200,
                water_contact=False,
                bypass_mode=BYPASS_MODE_NONE,
                penalty_seconds=0,
            ),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=422,
    )

    assert fx.read_course(api, laid["id"])["obstacle_count"] == 0


def test_difficulty_rating_above_ten_returns_invalid_request(api):
    """PRD §2.6: "Required fields present, types correct, enum members drawn from the declared sets, and numeric bounds respected — `limit` between 1 and 100 inclusive, `offset` at least 0, `difficulty_rating` between 1 and 10 inclusive, `lane_count` at least 1, a wave's `capacity` at least 1, `area_sqm` strictly greater than 0, and each quiet-hour field between 0 and 23 inclusive."

    Design: Corner/entities/unknown_enum_member_on_obstacle_creation_returns_invalid_request
    """
    _, laid = _draft_course(api, water_access=WATER_ACCESS_POND)

    # The producer's scale runs 1 to 10 inclusive, so 11 is out of bounds.
    validate_error(
        api.create_obstacle(
            laid["id"],
            f.obstacle_payload(
                1,
                name="Cargo Net",
                difficulty_rating=11,
                lane_count=4,
                service_rate_per_min=3.00,
                marshals_required=2,
                footprint_sqm=1200,
                water_contact=False,
                bypass_mode=BYPASS_MODE_NONE,
                penalty_seconds=0,
            ),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        expected_status=422,
    )

    assert fx.read_course(api, laid["id"])["obstacle_count"] == 0


# ─── Instance: division_and_attempt_are_immutable_rows_without_version_or_update_endpoint


def test_division_carries_no_version_or_updated_at(api):
    """PRD §2.4: "For those two entity types, `updated_at` and `version` are absent from the response body entirely; only `id` and `created_at` are present."

    Design: Corner/entities/division_and_attempt_are_immutable_rows_without_version_or_update_endpoint
    """
    div = fx.division(
        api,
        name="Elite",
        division_type=DIVISION_COMPETITIVE,
        bypass_policy=BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )

    stored = validate_success(api.get_division(div["id"], users.DIRECTOR))

    assert stored["id"] == div["id"]
    assert_no_version_fields(stored, "division")
    assert stored["division_type"] == DIVISION_COMPETITIVE
    assert stored["bypass_policy"] == BYPASS_POLICY_DQ_ON_BYPASS
    assert stored["scoring_mode"] == SCORING_CHIP_TIME
    assert stored["min_age"] == 18


def test_obstacle_attempt_carries_no_version_or_updated_at(api):
    """PRD §2.4: "For those two entity types, `updated_at` and `version` are absent from the response body entirely; only `id` and `created_at` are present."

    Design: Corner/entities/division_and_attempt_are_immutable_rows_without_version_or_update_endpoint
    """
    _, stations, _, ent, _ = _started_heat_with_one_runner(api)

    card = validate_success(
        api.create_attempt(
            ent["id"],
            f.attempt_payload(stations[0]["id"], OUTCOME_COMPLETED),
            users.MARSHAL_7,
        ),
        expected_status=201,
    )
    assert_no_version_fields(card, "obstacle attempt")

    # The same shape comes back when the card is read from the entry's roll.
    rows, meta = validate_paginated(
        api.list_entry_attempts(ent["id"], users.MARSHAL, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert_no_version_fields(rows[0], "listed obstacle attempt")


# ─── Instance: creating_a_course_under_an_unknown_venue_returns_venue_not_found


def test_creating_a_course_under_unknown_venue_returns_venue_not_found(api):
    """PRD §2.6: "The applicable code is `ERR_VENUE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_OBSTACLE_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND` or `ERR_RESTORATION_TASK_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/creating_a_course_under_an_unknown_venue_returns_venue_not_found
    """
    parcel = fx.venue(api, protected_acreage_sqm=2000, restoration_bond_cents=500000)

    validate_error(
        api.create_course(
            NON_EXISTENT_UUID,
            f.course_payload(name="Ghost Course", **{
                "total_distance_m": 10000,
                "corral_release_rate_per_min": 12.00,
                "corral_throughput_capacity": 200,
            }),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        expected_status=404,
    )

    rows, meta = validate_paginated(
        api.list_courses(parcel["id"], users.DESIGNER, params={"limit": 10, "offset": 0})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_path_resolution_precedes_body_schema_on_course_creation(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Corner/entities/creating_a_course_under_an_unknown_venue_returns_venue_not_found
    """
    fx.venue(api, protected_acreage_sqm=2000, restoration_bond_cents=500000)

    # The venue id does not resolve (rung 3) *and* a required body field is
    # missing (rung 4); the higher rung decides the response.
    validate_error(
        api.create_course(
            NON_EXISTENT_UUID,
            f.course_payload(name="Ghost Course", total_distance_m=f.OMIT),
            users.DESIGNER,
        ),
        ApiErrorId.ERR_VENUE_NOT_FOUND.value,
        expected_status=404,
    )


# ─── Instance: self_referential_bypass_lane_resolves_and_is_excluded_from_primary_aggregates


def _lane_relieving(api, course_id, primary_id):
    """A bypass lane whose own design rate (1.00) is the slowest row on the course."""
    return fx.obstacle(
        api,
        course_id,
        4,
        name="Wall Bypass Loop",
        difficulty_rating=2,
        lane_count=1,
        service_rate_per_min=1.00,
        marshals_required=1,
        footprint_sqm=200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
        paired_obstacle_id=primary_id,
    )


def test_bypass_lane_is_excluded_from_design_capacity(api):
    """PRD §3.2: "`design_capacity_pph` is the staffing-independent throughput of the course in participants per hour: consider only the primary obstacles, take the smallest `design_clearance_rate_per_min` among them, multiply by 60 to convert per-minute into per-hour, and discard any fractional part; when the course has no primary obstacle at all the value is 0."

    Design: Corner/entities/self_referential_bypass_lane_resolves_and_is_excluded_from_primary_aggregates
    """
    _, laid, stations = _three_station_draft(api)
    assert_course_capacities(
        fx.read_course(api, laid["id"]), design_capacity_pph=450
    )

    lane = _lane_relieving(api, laid["id"], stations[2]["id"])

    # One lane, one lane-worth of service: the slowest row on the course by far.
    assert_rate_equals(
        lane["design_clearance_rate_per_min"], 1.00, "bypass lane design rate"
    )

    # The minimum is taken over the primaries only, so 7.50 still governs.
    assert_course_capacities(
        fx.read_course(api, laid["id"]), design_capacity_pph=450
    )


def test_obstacle_count_includes_the_bypass_lane(api):
    """PRD §3.2: "`obstacle_count` is simply how many obstacle rows stand on the course, bypass lanes included."

    Design: Corner/entities/self_referential_bypass_lane_resolves_and_is_excluded_from_primary_aggregates
    """
    _, laid, stations = _three_station_draft(api)
    assert fx.read_course(api, laid["id"])["obstacle_count"] == 3

    _lane_relieving(api, laid["id"], stations[2]["id"])

    assert fx.read_course(api, laid["id"])["obstacle_count"] == 4


def test_bypass_lane_is_found_by_filtering_on_its_primary(api):
    """PRD §3.2: "Obstacles may be listed with optional filters on `course_id`, on `paired_obstacle_id` (to find the lanes relieving a given primary) and on `staffing_state`, and a single obstacle may be read to see its live marshal count, staffing state and both clearance rates."

    Design: Corner/entities/self_referential_bypass_lane_resolves_and_is_excluded_from_primary_aggregates
    """
    _, laid, stations = _three_station_draft(api)
    primary = stations[2]
    lane = _lane_relieving(api, laid["id"], primary["id"])

    # The stored row names its primary, and reads back the same way.
    assert lane["paired_obstacle_id"] == primary["id"]
    assert fx.read_obstacle(api, lane["id"])["paired_obstacle_id"] == primary["id"]

    rows, meta = validate_paginated(
        api.list_obstacles(
            users.DESIGNER,
            params={"paired_obstacle_id": primary["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [lane["id"]]

    # The three primaries relieve nobody, so the same filter never names them.
    for station in stations:
        untouched, untouched_meta = validate_paginated(
            api.list_obstacles(
                users.DESIGNER,
                params={
                    "paired_obstacle_id": station["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        expected = [lane["id"]] if station["id"] == primary["id"] else []
        assert ids_of(untouched) == expected
        assert untouched_meta["total_count"] == len(expected)
