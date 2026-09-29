"""Two occupancy rules over the same planned windows, one pairwise, one aggregate.

The line's rule excludes overlapping neighbours one pair at a time and layers a
45-minute allergen buffer on top of it; the flume's rule instead counts every
overlapping occupant across all lines against a single capacity.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import LINE_OPERATOR_HEADERS

# The incumbent run occupies [07:00, 12:00) on L1.
OVERLAP_START_AT = "2026-08-03T11:00:00Z"
OVERLAP_END_AT = "2026-08-03T14:00:00Z"
TOUCHING_START_AT = "2026-08-03T12:00:00Z"
TOUCHING_END_AT = "2026-08-03T15:00:00Z"
ZERO_GAP_START_AT = "2026-08-03T15:00:00Z"
BUFFERED_START_AT = "2026-08-03T15:45:00Z"
CELERY_END_AT = "2026-08-03T18:00:00Z"
CELERY_CREW_SIZE = 4

# The celery specification: a lighter case and a calendar code date.
CELERY_MAX_SHELF_LIFE_DAYS = 12
CELERY_MIN_REMAINING_DAYS = 8
CELERY_CASE_NET_WEIGHT_LB = 25.0

# Two further lines, both entirely free of runs.
SECOND_LINE_CODE = "L2"
SECOND_LINE_COMPONENTS = 10
THIRD_LINE_CODE = "L3"
THIRD_LINE_COMPONENTS = 14
THIRD_LINE_MAX_ATP_RLU = 150
SHARED_CREW_SIZE = 5

# Windows on the shared flume W1, whose max_concurrent_runs is 2.
SECOND_OCCUPANT_START_AT = "2026-08-03T08:00:00Z"
SECOND_OCCUPANT_END_AT = "2026-08-03T13:00:00Z"
THIRD_OCCUPANT_START_AT = "2026-08-03T09:00:00Z"
THIRD_OCCUPANT_END_AT = "2026-08-03T10:00:00Z"
LATE_WINDOW_START_AT = "2026-08-03T13:00:00Z"
LATE_WINDOW_END_AT = "2026-08-03T14:00:00Z"


def _line_with_an_incumbent_and_a_celery_product(api):
    """The planned incumbent on L1, plus a CELERY product and its specification."""
    world = fx.build_world(api, stop_after=fx.STOP_RUN_PLANNED)
    assert world.run["run_status"] == c.RUN_SETUP

    celery = fx.create_product(api, **f.celery_product_payload())
    assert celery["allergen_group"] == c.ALLERGEN_CELERY
    celery_spec = fx.create_customer_spec(
        api,
        celery["id"],
        celery["version"],
        max_shelf_life_days_offered=CELERY_MAX_SHELF_LIFE_DAYS,
        min_remaining_shelf_life_days_at_ship=CELERY_MIN_REMAINING_DAYS,
        atmosphere_required=c.ATMOSPHERE_AIR,
        case_net_weight_lb=CELERY_CASE_NET_WEIGHT_LB,
        code_date_format=c.CODE_DATE_CALENDAR,
    )
    return world, celery, celery_spec


def test_an_overlapping_window_is_refused_and_a_touching_one_is_accepted(api):
    """Half-open windows make 11:00 a conflict and 12:00 a clean handover.

    PRD: The window must not overlap the window of any other run on the same line whose `run_status` is `SETUP` or `RUNNING`. Two windows that merely touch, where one ends at exactly the instant the next begins, do not overlap. A violation of either the ordering or the exclusion is refused with `ERR_LINE_INTERVAL_CONFLICT` (HTTP 409).
    PRD: The planned window is treated as half-open: `planned_start_at` is inclusive and `planned_end_at` is exclusive, and `planned_end_at` must be strictly after `planned_start_at`.

    Design: Difficulty/resource_temporal_overlap/line_run_interval_pairwise_exclusion_with_allergen_buffer
    """
    world, _celery, _celery_spec = _line_with_an_incumbent_and_a_celery_product(api)

    validate_error(
        api.create_process_run(
            f.process_run_payload(
                world.line_id,
                world.product_id,
                world.spec_id,
                world.wash_system_id,
                planned_start_at=OVERLAP_START_AT,
                planned_end_at=OVERLAP_END_AT,
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.LINE_INTERVAL_CONFLICT,
    )

    touching = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=TOUCHING_START_AT,
        planned_end_at=TOUCHING_END_AT,
    )
    assert touching["run_status"] == c.RUN_SETUP
    assert touching["line_id"] == world.line_id


def test_a_differing_allergen_group_needs_a_gap_of_forty_five_minutes(api):
    """Zero gap after an allergen-free run is refused; exactly 45 minutes passes.

    PRD: When that run packs a product whose `allergen_group` differs from the new run's product's `allergen_group`, the gap between that run's `planned_end_at` and the new `planned_start_at` must be at least 45 minutes; a gap of exactly 45 minutes passes. A shorter gap is refused with `ERR_CHANGEOVER_BUFFER_REQUIRED` (HTTP 409).
    PRD: Consider the immediately preceding non-terminal run on the same line — the run with the greatest `planned_end_at` that is at or before the new run's `planned_start_at`.

    Design: Difficulty/resource_temporal_overlap/line_run_interval_pairwise_exclusion_with_allergen_buffer
    """
    world, celery, celery_spec = _line_with_an_incumbent_and_a_celery_product(api)

    # The preceding non-terminal run ends at 15:00 and packs allergen group NONE.
    fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=TOUCHING_START_AT,
        planned_end_at=TOUCHING_END_AT,
    )
    assert world.product["allergen_group"] == c.ALLERGEN_NONE

    validate_error(
        api.create_process_run(
            f.process_run_payload(
                world.line_id,
                celery["id"],
                celery_spec["id"],
                world.wash_system_id,
                planned_start_at=ZERO_GAP_START_AT,
                planned_end_at=CELERY_END_AT,
                crew_size=CELERY_CREW_SIZE,
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.CHANGEOVER_BUFFER_REQUIRED,
    )

    buffered = fx.plan_run(
        api,
        world.line_id,
        celery["id"],
        celery_spec["id"],
        world.wash_system_id,
        planned_start_at=BUFFERED_START_AT,
        planned_end_at=CELERY_END_AT,
        crew_size=CELERY_CREW_SIZE,
    )
    assert buffered["run_status"] == c.RUN_SETUP
    assert buffered["product_id"] == celery["id"]
    assert buffered["crew_size"] == CELERY_CREW_SIZE


def _three_lines_sharing_one_flume(api):
    """The incumbent on L1 plus two lines that carry no runs at all."""
    world = fx.build_world(api, stop_after=fx.STOP_RUN_PLANNED)
    assert world.wash_system["max_concurrent_runs"] == c.WASH_MAX_CONCURRENT_RUNS

    second_line = fx.create_line(
        api,
        line_code=SECOND_LINE_CODE,
        required_disassembly_component_count=SECOND_LINE_COMPONENTS,
    )
    third_line = fx.create_line(
        api,
        line_code=THIRD_LINE_CODE,
        required_disassembly_component_count=THIRD_LINE_COMPONENTS,
        max_atp_rlu=THIRD_LINE_MAX_ATP_RLU,
    )
    return world, second_line, third_line


def test_a_third_overlapping_occupant_of_the_flume_is_refused(api):
    """The second occupant is accepted, the third exceeds the flume's capacity.

    PRD: Count the other runs on the same wash system whose `run_status` is `SETUP` or `RUNNING` and whose half-open planned window overlaps the new run's window; that count must be strictly less than the system's `max_concurrent_runs`, since the new run would be the next occupant after those already counted. Otherwise the request is refused with `ERR_WASH_SYSTEM_CAPACITY_EXCEEDED` (HTTP 409).
    PRD: The wash system has an aggregate occupancy limit rather than a pairwise exclusion, because runs on different lines legitimately share a flume.

    Design: Difficulty/resource_temporal_overlap/wash_system_aggregate_concurrency_capacity
    """
    world, second_line, third_line = _three_lines_sharing_one_flume(api)

    second = fx.plan_run(
        api,
        second_line["id"],
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=SECOND_OCCUPANT_START_AT,
        planned_end_at=SECOND_OCCUPANT_END_AT,
        crew_size=SHARED_CREW_SIZE,
    )
    assert second["run_status"] == c.RUN_SETUP
    assert second["wash_system_id"] == world.wash_system_id

    # L3 has no runs whatsoever, so no pairwise rule can be what refuses this.
    validate_error(
        api.create_process_run(
            f.process_run_payload(
                third_line["id"],
                world.product_id,
                world.spec_id,
                world.wash_system_id,
                planned_start_at=THIRD_OCCUPANT_START_AT,
                planned_end_at=THIRD_OCCUPANT_END_AT,
                crew_size=SHARED_CREW_SIZE,
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.WASH_SYSTEM_CAPACITY_EXCEEDED,
    )


def test_a_window_overlapping_no_other_occupant_is_accepted_on_the_same_line(api):
    """The refused line's own next window passes, because the count is zero.

    PRD: Two windows that merely touch, where one ends at exactly the instant the next begins, do not overlap.
    PRD: The wash system has an aggregate occupancy limit rather than a pairwise exclusion, because runs on different lines legitimately share a flume.

    Design: Difficulty/resource_temporal_overlap/wash_system_aggregate_concurrency_capacity
    """
    world, second_line, third_line = _three_lines_sharing_one_flume(api)

    fx.plan_run(
        api,
        second_line["id"],
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=SECOND_OCCUPANT_START_AT,
        planned_end_at=SECOND_OCCUPANT_END_AT,
        crew_size=SHARED_CREW_SIZE,
    )

    late = fx.plan_run(
        api,
        third_line["id"],
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=LATE_WINDOW_START_AT,
        planned_end_at=LATE_WINDOW_END_AT,
        crew_size=SHARED_CREW_SIZE,
    )
    assert late["run_status"] == c.RUN_SETUP
    assert late["line_id"] == third_line["id"]
    assert late["wash_system_id"] == world.wash_system_id
