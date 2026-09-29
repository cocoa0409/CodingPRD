"""Radio-site registration and the single-pass coverage recomputation.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_SITE_NOT_FOUND, ERR_STALE_VERSION
from test_helpers.assertions import (
    assert_common_fields,
    assert_coverage_result,
    assert_fields,
    assert_one_decimal_place,
    assert_site_capacity_counters,
)
from test_helpers.constants import (
    BACKUP_BATTERY_ONLY,
    BACKUP_GENERATOR,
    CAPACITY_NORMAL,
    COVERAGE_GENERAL,
    COVERAGE_MARGINAL,
    COVERAGE_MISSION_CRITICAL,
    COVERAGE_UNRATED,
    DERATE_A,
    DERATE_B,
    DERATE_C,
    DERATE_NONE,
    NONEXISTENT_ID,
    SITE_IN_SERVICE,
    STANDARD_P25_PHASE1,
)
from test_helpers.test_users import RF_ENGINEER, SYSTEM_ADMIN


def test_site_creation_applies_declared_field_defaults(api: ApiClient, clock_at_start: str):
    """A site registered with only its required inputs opens on every declared
    default, including a perfect grade of service.

    PRD 3.2: "Two ratings describe the backup plant: `battery_runtime_minutes`,
    the rated battery-only runtime, at least 0 and at most 2880 minutes and
    defaulting to 240; and `generator_fuel_hours`, the rated generator runtime
    on the installed fuel load, at least 0 and at most 96 hours with at most two
    decimal places, defaulting to 0."

    PRD 3.2: "A new site opens `IN_SERVICE` with its `capacity_mode` at
    `NORMAL`, its `coverage_class` at `UNRATED`, its `coverage_derate_tier` at
    `NONE`, its `coverage_reliability_pct` at 0, its `covered_test_points` and
    `total_test_points` at 0, its `busy_talkpaths`, `peak_talkpaths`,
    `granted_request_count`, and `busied_request_count` at 0, and its
    `grade_of_service_pct` at exactly 100.0."

    Design: Corner/entities/site_creation_applies_declared_field_defaults
    """
    site = validate_success(
        api.create_site(
            {
                "site_code": "DEF-1",
                "name": "Defaults One",
                "channel_capacity": 6,
                "backup_power_type": BACKUP_GENERATOR,
            },
            SYSTEM_ADMIN,
        ),
        201,
    )

    assert_common_fields(site, expected_version=1)
    assert_fields(
        site,
        site_code="DEF-1",
        name="Defaults One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
        battery_runtime_minutes=240,
        generator_fuel_hours=0,
        migration_standard=STANDARD_P25_PHASE1,
        status=SITE_IN_SERVICE,
        capacity_mode=CAPACITY_NORMAL,
        covered_test_points=0,
        total_test_points=0,
    )
    assert_coverage_result(site, 0.0, DERATE_NONE, COVERAGE_UNRATED)
    assert_site_capacity_counters(
        site,
        busy_talkpaths=0,
        peak_talkpaths=0,
        granted_request_count=0,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )


def test_site_not_found_for_unknown_site_id(api: ApiClient, clock_at_start: str):
    """A `site_id` that was never minted resolves to the site family's own 404.

    PRD 2.4: "The system's path identifiers are `agency_id`, `site_id`,
    `template_id`, `unit_id`, `keyset_id`, `campaign_id`, `talkgroup_id`,
    `patch_id`, `event_id`, `change_request_id`, and `request_id`; they map
    respectively to `ERR_AGENCY_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
    `ERR_TEMPLATE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_KEYSET_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_TALKGROUP_NOT_FOUND`, `ERR_PATCH_NOT_FOUND`,
    `ERR_SITE_EVENT_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, and
    `ERR_TALKPATH_REQUEST_NOT_FOUND`."

    Design: Corner/entities/site_not_found_for_unknown_site_id
    """
    response = api.get_site(NONEXISTENT_ID, SYSTEM_ADMIN)
    error = validate_error(response, ERR_SITE_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error", (
        f"error responses carry response_type 'error', got {body['response_type']!r}"
    )
    # PRD 2.2: "The `message` provides a human-readable explanation of what
    # went wrong."
    assert isinstance(error["message"], str) and error["message"].strip(), (
        f"error message must be a non-empty human-readable string, got {error.get('message')!r}"
    )


def test_coverage_reliability_floors_at_zero_for_zero_coverage(
    api: ApiClient, clock_at_start: str
):
    """Zero covered points out of a non-zero survey floors at 0.0 and still
    classifies MARGINAL rather than short-circuiting to UNRATED.

    PRD 3.2: "`coverage_reliability_pct` is then the raw percentage minus the
    tier derate minus the backup penalty, rounded half up to one decimal place,
    and floored at 0.0 so it can never go negative."

    PRD 3.2: "When `total_test_points` is 0, the pass short-circuits:
    `coverage_reliability_pct` becomes exactly 0.0, `coverage_derate_tier`
    becomes `NONE`, and `coverage_class` becomes `UNRATED`."

    Design: Corner/calculations/coverage_reliability_floors_at_zero_for_zero_coverage
    """
    site = fx.register_site(
        api,
        site_code="ZRO-1",
        name="Zero Coverage One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )

    surveyed = validate_success(
        api.submit_coverage(
            site["id"], f.coverage_payload(0, 500, site["version"]), RF_ENGINEER
        ),
        200,
    )

    # raw 0.00 - tier C 3.0pp - no backup penalty = -3.0, floored at 0.0.
    assert_coverage_result(surveyed, 0.0, DERATE_C, COVERAGE_MARGINAL)
    assert_fields(
        surveyed,
        covered_test_points=0,
        total_test_points=500,
        version=site["version"] + 1,
    )


def test_coverage_class_threshold_at_exactly_ninety_percent(
    api: ApiClient, clock_at_start: str
):
    """The `GENERAL` floor is inclusive and is tested against the derated value,
    so one extra covered point moves the class.

    PRD 3.2: "A `coverage_reliability_pct` of at least 97.0 makes the site
    `MISSION_CRITICAL`; at least 90.0 but below 97.0 makes it `GENERAL`;
    anything below 90.0 makes it `MARGINAL`."

    Design: Corner/calculations/coverage_class_threshold_at_exactly_ninety_percent
    """
    on_threshold = fx.register_site(
        api,
        site_code="THR-1",
        name="Threshold One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    below_threshold = fx.register_site(
        api,
        site_code="THR-2",
        name="Threshold Two",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )

    # 91.50 raw selects tier B (below 97.00, at least 90.00) and derates 1.5pp
    # to exactly 90.0.
    first = validate_success(
        api.submit_coverage(
            on_threshold["id"],
            f.coverage_payload(915, 1000, on_threshold["version"]),
            RF_ENGINEER,
        ),
        200,
    )
    assert_coverage_result(first, 90.0, DERATE_B, COVERAGE_GENERAL)
    assert_one_decimal_place(first["coverage_reliability_pct"], "coverage_reliability_pct")

    # 91.40 raw is still tier B but derates to 89.9, one tenth below the floor.
    second = validate_success(
        api.submit_coverage(
            below_threshold["id"],
            f.coverage_payload(914, 1000, below_threshold["version"]),
            RF_ENGINEER,
        ),
        200,
    )
    assert_coverage_result(second, 89.9, DERATE_B, COVERAGE_MARGINAL)

    assert first["coverage_class"] != COVERAGE_MISSION_CRITICAL, (
        "a derated 90.0 is GENERAL, not MISSION_CRITICAL"
    )
    assert second["coverage_class"] != COVERAGE_MISSION_CRITICAL, (
        "a derated 89.9 is MARGINAL, not MISSION_CRITICAL"
    )


def test_occ_site_coverage_resubmission_rejects_stale_expected_version(
    api: ApiClient, clock_at_start: str
):
    """A fresher worksheet may supersede an older one, but only when the client
    pinned the version it actually read.

    PRD 2.6: "Submitting drive-test results against a site requires
    `expected_site_version`, carrying the `version` of the target `Site` as the
    client last observed it. A mismatch against the site's current `version` is
    rejected with `ERR_STALE_VERSION` and HTTP 412, preventing an engineer from
    overwriting a newer survey with an older worksheet."

    Design: Corner/cross_cutting_complexity_layers/occ_site_coverage_resubmission_rejects_stale_expected_version
    """
    site = fx.register_site(
        api,
        site_code="OCC-1",
        name="Concurrency One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
    )
    v1 = site["version"]

    # First survey: raw 90.00 selects tier B and derates to 88.5.
    first = validate_success(
        api.submit_coverage(site["id"], f.coverage_payload(900, 1000, v1), RF_ENGINEER),
        200,
    )
    assert_coverage_result(first, 88.5, DERATE_B, COVERAGE_MARGINAL)
    v2 = first["version"]
    assert v2 == v1 + 1, f"a successful submission increments version, got {v2} from {v1}"

    # Replaying the newer worksheet against the stale pin must change nothing.
    stale = api.submit_coverage(
        site["id"], f.coverage_payload(980, 1000, v1), RF_ENGINEER
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    unchanged = fx.read_site(api, site["id"])
    assert_coverage_result(unchanged, 88.5, DERATE_B, COVERAGE_MARGINAL)
    assert_fields(unchanged, covered_test_points=900, total_test_points=1000, version=v2)

    # The identical body pinned to the current version is accepted.
    accepted = validate_success(
        api.submit_coverage(site["id"], f.coverage_payload(980, 1000, v2), RF_ENGINEER),
        200,
    )
    assert_coverage_result(accepted, 97.5, DERATE_A, COVERAGE_MISSION_CRITICAL)
    assert_fields(
        accepted, covered_test_points=980, total_test_points=1000, version=v2 + 1
    )


def test_coverage_derate_tier_selected_once_from_raw_pct_not_from_derated_value(
    api: ApiClient, clock_at_start: str
):
    """The tier comes from the raw percentage and is never re-selected once the
    derate has pushed the value into a lower band.

    PRD 3.2: "The raw percentage then selects a derate tier, and this is the
    subtle part: **the tier is selected once, from the raw percentage only, and
    is never re-selected from the derated result** — even when the derated result
    would have landed in a lower band."

    Design: Difficulty/combinatorial_formula/coverage_derate_tier_selected_once_from_raw_pct_mode_c
    """
    site = fx.register_site(
        api,
        site_code="COV-A",
        name="Ridge Alpha",
        channel_capacity=8,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=24,
    )
    v1 = site["version"]

    # raw = 100 * 970 / 1000 = 97.00, which is "at least 97.00" and so selects
    # tier A (0.5pp). 97.00 - 0.5 = 96.5.
    surveyed = validate_success(
        api.submit_coverage(site["id"], f.coverage_payload(970, 1000, v1), RF_ENGINEER),
        200,
    )
    assert_coverage_result(surveyed, 96.5, DERATE_A, COVERAGE_GENERAL)

    # Re-selecting the tier from the derated 96.5 would pick tier B (1.5pp) and
    # land on 95.5; the PRD forbids exactly that.
    assert surveyed["coverage_reliability_pct"] != 95.5, (
        "the tier must not be re-selected from the derated result"
    )
    assert_fields(surveyed, version=v1 + 1)


def test_coverage_derate_tier_selected_once_backup_penalty_stacks_on_the_tier(
    api: ApiClient, clock_at_start: str
):
    """Two sites with byte-identical drive tests diverge purely on backup plant:
    the `BATTERY_ONLY` penalty stacks on top of the tier derate.

    PRD 3.2: "On top of the tier derate, a site whose `backup_power_type` is
    `BATTERY_ONLY` suffers a further fixed penalty of two percentage points; a
    `GENERATOR` site suffers none."

    Design: Difficulty/combinatorial_formula/coverage_derate_tier_selected_once_from_raw_pct_mode_c
    """
    battery = fx.register_site(
        api,
        site_code="COV-B",
        name="Ridge Bravo",
        channel_capacity=8,
        backup_power_type=BACKUP_BATTERY_ONLY,
        battery_runtime_minutes=240,
    )
    generator = fx.register_site(
        api,
        site_code="COV-C",
        name="Ridge Charlie",
        channel_capacity=8,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=24,
    )

    # Both surveys are 985/1000, so raw is 98.50 and both select tier A.
    battery_result = validate_success(
        api.submit_coverage(
            battery["id"], f.coverage_payload(985, 1000, battery["version"]), RF_ENGINEER
        ),
        200,
    )
    generator_result = validate_success(
        api.submit_coverage(
            generator["id"],
            f.coverage_payload(985, 1000, generator["version"]),
            RF_ENGINEER,
        ),
        200,
    )

    # 98.50 - 0.5 - 2.0 = 96.0 versus 98.50 - 0.5 = 98.0.
    assert_coverage_result(battery_result, 96.0, DERATE_A, COVERAGE_GENERAL)
    assert_coverage_result(generator_result, 98.0, DERATE_A, COVERAGE_MISSION_CRITICAL)

    assert (
        battery_result["coverage_reliability_pct"]
        != generator_result["coverage_reliability_pct"]
    ), "identical drive tests must diverge on backup_power_type alone"
