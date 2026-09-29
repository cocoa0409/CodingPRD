"""Standing up the mountain inventory and reading it back.

A season configuration, the lifts that turn, the terrain areas they serve, the
stake readings that measure them and the patrollers rostered onto them all
enter the system through a create call and leave it through a read call. The
behaviours grouped here are the shapes of those two calls: which fields a
freshly created row carries, which of them the server owns outright and
refuses to take from the caller, which optional policy knobs fall back to a
declared default, how a collection is paged and filtered, and which rejection
a caller earns for an unknown identifier, an out-of-domain enum, a missing
required field or a reference that points into another season.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CROSS_SEASON_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_TERRAIN_AREA_NOT_FOUND,
)
from test_helpers.assertions import (
    LIFT_FIELDS,
    SEASON_FIELDS,
    SNOW_DEPTH_READING_FIELDS,
    TERRAIN_AREA_FIELDS,
    assert_created_at_ascending,
    assert_fields_present,
    assert_immutable_observation,
    assert_integer,
    assert_number_equals,
    assert_one_decimal,
    assert_pagination_meta,
    assert_versioned_row,
    assert_water_af,
    canonical_instant,
    ids_of,
)
from test_helpers.constants import (
    DEFAULT_BASE_DEPTH_POLICY,
    DEFAULT_GROOM_FRESHNESS_HOURS,
    DEFAULT_LIMIT,
    DEFAULT_MIN_PATROLLERS_PER_OPEN_AREA,
    DEFAULT_OFFSET,
    DEFAULT_REQUIRED_OPERATOR_COUNT,
)
from test_helpers.factories import (
    lift_payload,
    patroller_payload,
    season_payload,
    session_payload,
    snow_depth_reading_payload,
    terrain_area_payload,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
)

# ─── The canonical season under test ──────────────────
SEASON_LABEL = "2026-27"
WATER_RIGHT_AF = 250.000
PLANT_MAX_GPM = 6000
KWH_PER_AF = 620.0
ENERGY_WINDOW_CODES = ["OFF_1", "MID_1", "ON_1", "MID_2"]

# ─── The minimally specified season ───────────────────
MINIMAL_SEASON_LABEL = "2026-27-minimal"
MINIMAL_WATER_RIGHT_AF = 120.000
MINIMAL_PLANT_MAX_GPM = 4000
MINIMAL_KWH_PER_AF = 600.0

# ─── The lift and terrain area under test ─────────────
LIFT_CODE = "L1"
LIFT_NAME = "Summit Express"
LIFT_TYPE = "DETACHABLE"
WIND_HOLD_THRESHOLD_MPH = 40.0
HOURLY_CAPACITY_PPH = 1800
AREA_ACRES = 18.0
AREA_MIN_OPEN_BASE_DEPTH_IN = 30

# ─── The forged system fields a caller may not seed ───
FORGED_ID = "00000000-0000-4000-8000-000000000000"
FORGED_VERSION = 99
FORGED_CREATED_AT = "2000-01-01T00:00:00Z"
FORGED_STAFFED_OPERATOR_COUNT = 5

# ─── The three-area collection walked by the page ─────
AREA_COUNT = 3
PAGE_LIMIT = 2

# ─── The appended stake reading ───────────────────────
FIRST_DEPTH_IN = 40.0
SECOND_DEPTH_IN = 31.0
SURVIVING_STAKE_COUNT = 1

# ─── The session flow the schema check is about ───────
SESSION_GPM = 1200


def test_a_new_season_returns_every_declared_field_with_its_ledgers_at_zero(api):
    """A freshly created season echoes its declared configuration and opens its water and snow ledgers at zero in PRESEASON.

    A newly created season starts in `season_state` `PRESEASON`, with `water_reserved_af`, `water_used_af` and `snow_produced_swe_af` all at 0.0 and `open_area_count` at 0.

    Design: Corner/entities/season_creation_returns_every_declared_field_and_zeroed_ledgers
    """
    payload = season_payload(
        season_label=SEASON_LABEL,
        water_right_seasonal_af=WATER_RIGHT_AF,
        plant_max_gpm=PLANT_MAX_GPM,
        snowmaking_kwh_per_af=KWH_PER_AF,
        base_depth_policy=DEFAULT_BASE_DEPTH_POLICY,
        min_patrollers_per_open_area=DEFAULT_MIN_PATROLLERS_PER_OPEN_AREA,
        groom_freshness_hours=DEFAULT_GROOM_FRESHNESS_HOURS,
    )

    data = validate_success(api.create_season(payload, DIRECTOR_HEADERS), 201)

    assert_fields_present(data, SEASON_FIELDS)
    assert_versioned_row(data, expected_version=1)

    # The declared configuration comes back exactly as it was submitted.
    assert data["season_label"] == SEASON_LABEL
    assert_water_af(data["water_right_seasonal_af"], WATER_RIGHT_AF)
    assert_integer(data["plant_max_gpm"], PLANT_MAX_GPM)
    assert_number_equals(data["snowmaking_kwh_per_af"], KWH_PER_AF)
    assert data["base_depth_policy"] == DEFAULT_BASE_DEPTH_POLICY
    assert_integer(
        data["min_patrollers_per_open_area"], DEFAULT_MIN_PATROLLERS_PER_OPEN_AREA
    )
    assert_integer(data["groom_freshness_hours"], DEFAULT_GROOM_FRESHNESS_HOURS)
    assert [window["code"] for window in data["energy_windows"]] == ENERGY_WINDOW_CODES

    # The season has done no work yet, so every ledger reads zero.
    assert data["season_state"] == "PRESEASON"
    assert_water_af(data["water_reserved_af"], 0.000)
    assert_water_af(data["water_used_af"], 0.000)
    assert_water_af(data["snow_produced_swe_af"], 0.000)
    assert_integer(data["open_area_count"], 0)


def test_the_three_optional_readiness_policies_fall_back_to_their_declared_defaults(api):
    """A season created without the three readiness knobs receives the mean-of-stakes policy, two patrollers per open area and an eighteen-hour groom freshness.

    Three readiness policies are optional and carry defaults: `base_depth_policy` selects which stake statistic defines an area's base depth and is either `MEAN_OF_STAKES` (the default) or `MIN_OF_STAKES`; `min_patrollers_per_open_area` is the number of available patrollers an area must carry to stay open and defaults to 2 with a minimum of 1; and `groom_freshness_hours` is how long a completed groom keeps an area current and defaults to 18 hours with a minimum of 1.

    Design: Corner/entities/season_defaults_apply_when_the_three_optional_knobs_are_omitted
    """
    payload = season_payload(
        season_label=MINIMAL_SEASON_LABEL,
        water_right_seasonal_af=MINIMAL_WATER_RIGHT_AF,
        plant_max_gpm=MINIMAL_PLANT_MAX_GPM,
        snowmaking_kwh_per_af=MINIMAL_KWH_PER_AF,
    )
    # Nothing about readiness is declared: the three knobs are simply absent.
    assert "base_depth_policy" not in payload
    assert "min_patrollers_per_open_area" not in payload
    assert "groom_freshness_hours" not in payload

    data = validate_success(api.create_season(payload, DIRECTOR_HEADERS), 201)

    assert data["base_depth_policy"] == DEFAULT_BASE_DEPTH_POLICY
    assert_integer(
        data["min_patrollers_per_open_area"], DEFAULT_MIN_PATROLLERS_PER_OPEN_AREA
    )
    assert_integer(data["groom_freshness_hours"], DEFAULT_GROOM_FRESHNESS_HOURS)

    # The declared numbers of this leaner season are still echoed faithfully.
    assert data["season_label"] == MINIMAL_SEASON_LABEL
    assert_water_af(data["water_right_seasonal_af"], MINIMAL_WATER_RIGHT_AF)
    assert_integer(data["plant_max_gpm"], MINIMAL_PLANT_MAX_GPM)
    assert_number_equals(data["snowmaking_kwh_per_af"], MINIMAL_KWH_PER_AF)


def test_a_new_lift_lands_closed_with_its_inspection_still_due(api, mountain):
    """A freshly registered lift echoes its declared mechanics and is seeded on both of its state dimensions at once: out of service and not yet inspected.

    A fresh lift lands with `service_status` `CLOSED`, `mechanical_status` `INSPECTION_DUE`, `staffed_operator_count` 0, and `last_inspection_at`, `last_inspection_result`, `inspection_valid_until` and `wind_hold_since` all null.

    Design: Corner/entities/lift_creation_echoes_input_and_seeds_both_state_dimensions
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    payload = lift_payload(
        season_row["id"],
        lift_code=LIFT_CODE,
        name=LIFT_NAME,
        lift_type=LIFT_TYPE,
        wind_hold_threshold_mph=WIND_HOLD_THRESHOLD_MPH,
        hourly_capacity_pph=HOURLY_CAPACITY_PPH,
        required_operator_count=DEFAULT_REQUIRED_OPERATOR_COUNT,
    )

    data = validate_success(api.create_lift(payload, LIFT_OPS_HEADERS), 201)

    assert_fields_present(data, LIFT_FIELDS)
    assert_versioned_row(data, expected_version=1)

    assert data["season_id"] == season_row["id"]
    assert data["lift_code"] == LIFT_CODE
    assert data["name"] == LIFT_NAME
    assert data["lift_type"] == LIFT_TYPE
    assert_one_decimal(data["wind_hold_threshold_mph"], WIND_HOLD_THRESHOLD_MPH)
    assert_integer(data["hourly_capacity_pph"], HOURLY_CAPACITY_PPH)
    assert_integer(data["required_operator_count"], DEFAULT_REQUIRED_OPERATOR_COUNT)

    # Service posture and mechanical posture are seeded independently.
    assert data["service_status"] == "CLOSED"
    assert data["mechanical_status"] == "INSPECTION_DUE"
    assert_integer(data["staffed_operator_count"], 0)
    assert data["last_inspection_at"] is None
    assert data["last_inspection_result"] is None
    assert data["inspection_valid_until"] is None
    assert data["wind_hold_since"] is None


def test_reading_back_a_new_terrain_area_shows_every_derived_field_at_its_zero_baseline(
    api, mountain
):
    """A terrain area fetched straight after creation returns the stored declaration together with a completely unearned derived state.

    New areas begin with `opening_state` `CLOSED` and `park_state` `NO_PARK`, `base_depth_in` 0.0 and `base_depth_stake_count` 0, `groom_coverage_pct` 0.0 and `groom_ready` false, `last_groomed_at` and `mitigation_clearance_expires_at` null, `assigned_patroller_count` 0, `machine_swe_af` 0.0, `park_feature_count` 0, `park_risk_score` 0.0, and both `park_built_by_user_id` and `park_inspected_by_user_id` null.

    Design: Corner/entities/terrain_area_retrieval_returns_the_stored_row_with_all_derived_fields_zeroed
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    area_row = mountain.create_terrain_area(
        season_row["id"],
        lift_row["id"],
        trail_code="T1",
        name="Sunbowl",
        terrain_class="BLUE",
        acres=AREA_ACRES,
        min_open_base_depth_in=AREA_MIN_OPEN_BASE_DEPTH_IN,
    )

    data = validate_success(api.get_terrain_area(area_row["id"], GROOMING_HEADERS))

    assert_fields_present(data, TERRAIN_AREA_FIELDS)
    assert_versioned_row(data, expected_version=1)

    # The stored declaration.
    assert data["id"] == area_row["id"]
    assert data["season_id"] == season_row["id"]
    assert data["serving_lift_id"] == lift_row["id"]
    assert data["trail_code"] == "T1"
    assert data["name"] == "Sunbowl"
    assert data["terrain_class"] == "BLUE"
    assert_one_decimal(data["acres"], AREA_ACRES)
    assert_integer(data["min_open_base_depth_in"], AREA_MIN_OPEN_BASE_DEPTH_IN)
    assert data["avalanche_terrain"] is False

    # Nothing has been measured, groomed, patrolled, blown or built yet.
    assert data["opening_state"] == "CLOSED"
    assert data["park_state"] == "NO_PARK"
    assert_one_decimal(data["base_depth_in"], 0.0)
    assert_integer(data["base_depth_stake_count"], 0)
    assert_one_decimal(data["groom_coverage_pct"], 0.0)
    assert data["groom_ready"] is False
    assert data["last_groomed_at"] is None
    assert data["mitigation_clearance_expires_at"] is None
    assert_integer(data["assigned_patroller_count"], 0)
    assert_water_af(data["machine_swe_af"], 0.000)
    assert_integer(data["park_feature_count"], 0)
    assert_one_decimal(data["park_risk_score"], 0.0)
    assert data["park_built_by_user_id"] is None
    assert data["park_inspected_by_user_id"] is None


def test_the_terrain_listing_pages_the_collection_and_counts_the_filtered_set(api, mountain):
    """A page of terrain areas carries the size of the whole filtered set, not the size of the page, and a class filter narrows that set before the window is applied.

    List responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the size of the filtered set before the page window is applied and `has_more` indicates whether any rows remain beyond the current page.

    Lifts may be listed filtered by `season_id`, by `service_status` and by `mechanical_status`; terrain areas by `season_id`, `serving_lift_id`, `opening_state` and `terrain_class`; pump houses by `season_id` and `status`.

    Design: Corner/entities/terrain_area_listing_paginates_filters_and_reports_total_count
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    areas = [
        mountain.create_terrain_area(
            season_row["id"],
            lift_row["id"],
            trail_code=trail_code,
            name=name,
            terrain_class=terrain_class,
            acres=acres,
        )
        for trail_code, name, terrain_class, acres in (
            ("T1", "Sunbowl", "BLUE", 18.0),
            ("T2", "Devil's Chute", "BLACK", 12.0),
            ("T3", "Meadow Lane", "GREEN", 8.0),
        )
    ]

    # The first page of two, with a third row still waiting behind it.
    data, meta = validate_paginated(
        api.list_terrain_areas(
            GUEST_SERVICES_HEADERS,
            season_id=season_row["id"],
            limit=PAGE_LIMIT,
            offset=0,
        )
    )
    assert len(data) == PAGE_LIMIT
    assert_pagination_meta(meta, PAGE_LIMIT, 0, AREA_COUNT, True)
    assert_created_at_ascending(data)
    assert ids_of(data) == [areas[0]["id"], areas[1]["id"]]

    # The window moved past the first two rows: one row left, nothing behind it.
    data, meta = validate_paginated(
        api.list_terrain_areas(
            GUEST_SERVICES_HEADERS,
            season_id=season_row["id"],
            limit=PAGE_LIMIT,
            offset=PAGE_LIMIT,
        )
    )
    assert len(data) == 1
    assert_pagination_meta(meta, PAGE_LIMIT, PAGE_LIMIT, AREA_COUNT, False)
    assert ids_of(data) == [areas[2]["id"]]

    # Every area is still CLOSED, so that filter selects the whole collection.
    data, meta = validate_paginated(
        api.list_terrain_areas(
            GUEST_SERVICES_HEADERS, season_id=season_row["id"], opening_state="CLOSED"
        )
    )
    assert len(data) == AREA_COUNT
    assert_integer(meta["total_count"], AREA_COUNT)

    # A class filter shrinks the counted set, not merely the returned page.
    data, meta = validate_paginated(
        api.list_terrain_areas(
            GUEST_SERVICES_HEADERS, season_id=season_row["id"], terrain_class="BLACK"
        )
    )
    assert len(data) == 1
    assert_integer(meta["total_count"], 1)
    assert data[0]["trail_code"] == "T2"


def test_a_listing_without_a_window_uses_the_declared_page_defaults(api, mountain):
    """A list call that names no window is served with the declared default limit and offset rather than an unbounded page.

    `limit` defaults to 10, has a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has a minimum of 0.

    Design: Corner/entities/listing_applies_the_declared_pagination_defaults_when_limit_is_omitted
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    for trail_code in ("T1", "T2", "T3"):
        mountain.create_terrain_area(
            season_row["id"], lift_row["id"], trail_code=trail_code, name=f"Run {trail_code}"
        )

    data, meta = validate_paginated(
        api.list_terrain_areas(GUEST_SERVICES_HEADERS, season_id=season_row["id"])
    )

    assert_pagination_meta(meta, DEFAULT_LIMIT, DEFAULT_OFFSET, AREA_COUNT, False)
    # Three rows fit comfortably inside the default window of ten.
    assert len(data) == AREA_COUNT


def test_an_unknown_terrain_area_id_is_refused_with_the_terrain_family_code(api):
    """An identifier that resolves to no terrain area is refused with the terrain area's own not-found code, both when it is fetched and when a reading is filed against it.

    Each resource family has its own not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_TERRAIN_AREA_NOT_FOUND`, `ERR_LIFT_NOT_FOUND`, `ERR_PUMP_HOUSE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_GROOMING_TASK_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_PATROLLER_NOT_FOUND`, `ERR_MISSION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_DAY_PLAN_NOT_FOUND` and `ERR_RESERVATION_NOT_FOUND` — all HTTP 404.

    Design: Corner/entities/terrain_area_fetch_with_unknown_id_returns_terrain_area_not_found
    """
    validate_error(
        api.get_terrain_area(NON_EXISTENT_UUID, GROOMING_HEADERS),
        ERR_TERRAIN_AREA_NOT_FOUND,
    )

    # The same unresolvable segment decides the error on the nested reading route.
    validate_error(
        api.record_snow_depth_reading(
            NON_EXISTENT_UUID, snow_depth_reading_payload(), GROOMING_HEADERS
        ),
        ERR_TERRAIN_AREA_NOT_FOUND,
    )


def test_a_snowmaking_session_without_a_flow_figure_is_a_schema_violation(
    api, mountain, open_mountain_with_plant
):
    """Scheduling a session without the required flow figure is rejected as a malformed request and creates nothing, while the identical body carrying the flow is accepted.

    Request-body schema conformance — required fields present, types correct, enum values inside their declared domains, numbers inside their declared ranges, arrays inside their declared cardinality — `ERR_INVALID_REQUEST` (400), on every endpoint.

    Design: Corner/entities/snowmaking_session_create_missing_gpm_returns_invalid_request
    """
    area_id = open_mountain_with_plant["area_id"]
    pump_house_id = open_mountain_with_plant["pump_house_id"]

    payload = session_payload(area_id, pump_house_id, mountain.area_version(area_id))
    del payload["gpm"]

    validate_error(api.create_session(payload, SNOWMAKING_HEADERS), ERR_INVALID_REQUEST)

    # A rejected schedule leaves no session behind on the area.
    _, meta = validate_paginated(
        api.list_sessions(SNOWMAKING_HEADERS, terrain_area_id=area_id)
    )
    assert_integer(meta["total_count"], 0)

    # The same request, now naming its flow, is admissible.
    payload["gpm"] = SESSION_GPM
    payload["expected_terrain_area_version"] = mountain.area_version(area_id)
    data = validate_success(api.create_session(payload, SNOWMAKING_HEADERS), 201)
    assert_integer(data["gpm"], SESSION_GPM)
    assert data["terrain_area_id"] == area_id
    assert data["pump_house_id"] == pump_house_id


def test_derived_terrain_state_submitted_on_creation_does_not_seed_the_new_area(
    api, mountain
):
    """A caller who types an opened state, a measured base depth, a groom verdict and a patroller headcount into a terrain area creation still gets the untouched baseline.

    New areas begin with `opening_state` `CLOSED` and `park_state` `NO_PARK`, `base_depth_in` 0.0 and `base_depth_stake_count` 0, `groom_coverage_pct` 0.0 and `groom_ready` false, `last_groomed_at` and `mitigation_clearance_expires_at` null, `assigned_patroller_count` 0, `machine_swe_af` 0.0, `park_feature_count` 0, `park_risk_score` 0.0, and both `park_built_by_user_id` and `park_inspected_by_user_id` null.

    Design: Corner/entities/terrain_area_computed_fields_extra_field_input_ignored
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    payload = terrain_area_payload(
        season_row["id"],
        lift_row["id"],
        trail_code="T9",
        name="Sunbowl",
        terrain_class="BLUE",
        acres=AREA_ACRES,
        opening_state="OPEN",
        base_depth_in=99.0,
        groom_ready=True,
        assigned_patroller_count=7,
    )

    data = validate_success(api.create_terrain_area(payload, DIRECTOR_HEADERS), 201)

    # The declaration the caller is allowed to make survives.
    assert data["trail_code"] == "T9"
    assert_one_decimal(data["acres"], AREA_ACRES)

    # Everything the mountain has to earn is still at zero.
    assert data["opening_state"] == "CLOSED"
    assert_one_decimal(data["base_depth_in"], 0.0)
    assert_integer(data["base_depth_stake_count"], 0)
    assert data["groom_ready"] is False
    assert_one_decimal(data["groom_coverage_pct"], 0.0)
    assert_integer(data["assigned_patroller_count"], 0)


def test_lift_identity_and_staffing_are_minted_by_the_server_not_by_the_caller(
    api, mountain
):
    """A lift registration that tries to dictate its own identity, version, creation stamp and staffed headcount is minted afresh by the server instead.

    Every resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits.

    A fresh lift lands with `service_status` `CLOSED`, `mechanical_status` `INSPECTION_DUE`, `staffed_operator_count` 0, and `last_inspection_at`, `last_inspection_result`, `inspection_valid_until` and `wind_hold_since` all null.

    Design: Corner/entities/lift_system_fields_are_server_owned_and_input_ignored
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    payload = lift_payload(
        season_row["id"],
        lift_code="L9",
        name=LIFT_NAME,
        id=FORGED_ID,
        version=FORGED_VERSION,
        created_at=FORGED_CREATED_AT,
        staffed_operator_count=FORGED_STAFFED_OPERATOR_COUNT,
    )

    data = validate_success(api.create_lift(payload, LIFT_OPS_HEADERS), 201)

    assert_versioned_row(data, expected_version=1)
    assert data["id"] != FORGED_ID, "the caller must not be able to choose a row id"
    assert canonical_instant(data["created_at"]) != canonical_instant(FORGED_CREATED_AT), (
        "created_at must be stamped by the server, not carried in the payload"
    )
    assert_integer(data["staffed_operator_count"], 0)
    assert data["lift_code"] == "L9"


def test_a_terrain_class_outside_its_domain_and_a_negative_acreage_are_both_refused(
    api, mountain
):
    """A terrain class that is not one of the declared classes, and an acreage below zero, are each rejected as malformed requests and neither leaves a row behind.

    Request-body schema conformance — required fields present, types correct, enum values inside their declared domains, numbers inside their declared ranges, arrays inside their declared cardinality — `ERR_INVALID_REQUEST` (400), on every endpoint.

    Design: Corner/entities/terrain_area_invalid_enum_terrain_class_is_rejected
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)

    # A plausible-sounding class that the contract never declares.
    validate_error(
        api.create_terrain_area(
            terrain_area_payload(
                season_row["id"],
                lift_row["id"],
                trail_code="T1",
                terrain_class="DOUBLE_BLACK",
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    # An acreage outside its declared range.
    validate_error(
        api.create_terrain_area(
            terrain_area_payload(
                season_row["id"], lift_row["id"], trail_code="T2", acres=-4.0
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(
        api.list_terrain_areas(DIRECTOR_HEADERS, season_id=season_row["id"])
    )
    assert_integer(meta["total_count"], 0)


def test_a_second_reading_on_one_stake_is_appended_and_carries_no_version(
    api, mountain, initial_clock
):
    """A stake read twice yields two immutable rows that carry neither a version nor an update stamp, while the area's base depth follows only the later of the two.

    The one exception is the snow stake reading: a `SnowDepthReading` is an immutable observation and carries only `id` and `created_at`.

    Within that window the readings are collapsed to one per stake: for each distinct `stake_code`, the reading with the greatest `measured_at` wins, and where two readings share that instant the one with the later `created_at` wins.

    Design: Corner/entities/snow_depth_reading_rows_are_append_only_and_carry_no_version
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    area_row = mountain.create_terrain_area(
        season_row["id"], lift_row["id"], trail_code="T1", name="Sunbowl"
    )
    first = mountain.record_reading(
        area_row["id"], stake_code="S1", depth_in=FIRST_DEPTH_IN, measured_at=initial_clock
    )

    # The same stake, the same instant, a thinner measurement.
    data = validate_success(
        api.record_snow_depth_reading(
            area_row["id"],
            snow_depth_reading_payload(
                stake_code="S1", depth_in=SECOND_DEPTH_IN, measured_at=initial_clock
            ),
            GROOMING_HEADERS,
        ),
        201,
    )

    assert_fields_present(data, SNOW_DEPTH_READING_FIELDS)
    assert_immutable_observation(data)
    assert data["id"] != first["id"], "a second reading is a new row, not an edit"
    assert_one_decimal(data["depth_in"], SECOND_DEPTH_IN)

    # Both observations survive: the stake's history is appended to, never rewritten.
    rows, meta = validate_paginated(
        api.list_snow_depth_readings(area_row["id"], GROOMING_HEADERS, stake_code="S1")
    )
    assert_integer(meta["total_count"], 2)
    assert len(rows) == 2

    # One stake still, and the later-created row is the one that counts.
    area_after = mountain.area(area_row["id"])
    assert_integer(area_after["base_depth_stake_count"], SURVIVING_STAKE_COUNT)
    assert_one_decimal(area_after["base_depth_in"], SECOND_DEPTH_IN)


def test_a_serving_lift_from_another_season_cannot_carry_a_terrain_area(api, mountain):
    """A terrain area declared under one season may not name a serving lift that belongs to a different season, while the same declaration with a lift of its own season is accepted.

    A serving lift that belongs to a different season than the declared one is refused with `ERR_CROSS_SEASON_REFERENCE`.

    Design: Corner/entities/terrain_area_with_a_serving_lift_from_another_season_returns_cross_season_reference
    """
    season_a = mountain.create_season(season_label=SEASON_LABEL)
    season_b = mountain.create_season(season_label="2027-28")
    lift_b = mountain.create_lift(season_b["id"], lift_code="LB", name="Backside Quad")

    validate_error(
        api.create_terrain_area(
            terrain_area_payload(
                season_a["id"], lift_b["id"], trail_code="T1", name="Sunbowl"
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_CROSS_SEASON_REFERENCE,
    )

    # The refusal is total: neither season gained a terrain area.
    for season_row in (season_a, season_b):
        _, meta = validate_paginated(
            api.list_terrain_areas(DIRECTOR_HEADERS, season_id=season_row["id"])
        )
        assert_integer(meta["total_count"], 0)

    # The identical declaration, served by a lift of its own season, is fine.
    lift_a = mountain.create_lift(season_a["id"], lift_code="LA", name="Frontside Quad")
    data = validate_success(
        api.create_terrain_area(
            terrain_area_payload(
                season_a["id"], lift_a["id"], trail_code="T1", name="Sunbowl"
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert data["season_id"] == season_a["id"]
    assert data["serving_lift_id"] == lift_a["id"]


def test_rostering_a_patroller_onto_an_unknown_area_is_refused_by_that_family(api, mountain):
    """A patroller rostered onto an area that does not exist is refused with the terrain family's not-found code, whereas one rostered with no area at all is created unassigned and on duty.

    Each unresolvable reference raises its own family's not-found code.

    A patroller created with `on_duty` true therefore lands directly in `AVAILABLE`, and one created off duty lands in `OFF_DUTY`.

    Design: Corner/entities/patroller_with_an_unknown_assigned_terrain_area_returns_not_found
    """
    season_row = mountain.create_season(season_label=SEASON_LABEL)
    lift_row = mountain.create_lift(season_row["id"], lift_code=LIFT_CODE, name=LIFT_NAME)
    area_row = mountain.create_terrain_area(
        season_row["id"], lift_row["id"], trail_code="T1", name="Sunbowl"
    )

    validate_error(
        api.create_patroller(
            patroller_payload(
                season_row["id"],
                patroller_code="P9",
                assigned_terrain_area_id=NON_EXISTENT_UUID,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_TERRAIN_AREA_NOT_FOUND,
    )

    # Leaving the assignment out is legitimate: the patroller simply covers nothing.
    data = validate_success(
        api.create_patroller(
            patroller_payload(season_row["id"], patroller_code="P9", on_duty=True),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert data["assigned_terrain_area_id"] is None
    assert data["status"] == "AVAILABLE"

    # No area was credited with the new patroller.
    assert_integer(mountain.area(area_row["id"])["assigned_patroller_count"], 0)
