"""Shared scarce resources with windowed contention: an engineer's calendar, a reach."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    assert_acre_feet,
    assert_cfs,
    assert_instant,
    assert_storage_conservation,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DRAWDOWN_COORDINATED,
    DRAWDOWN_REQUESTED,
    INSPECTION_SCHEDULED,
)


# ---------------------------------------------------------------------------
# The engineer's 120-minute travel buffer
# ---------------------------------------------------------------------------
@pytest.fixture()
def two_classified_dams(program, base):
    """Two SIGNIFICANT dams on one reach, both certified by the same engineer."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    second = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Bitter Fork Dam",
        nid_code="ST00124",
        height_ft=48,
        gross_storage_acre_ft=900,
        crest_elevation_ft=1188.0,
        normal_pool_elevation_ft=1184.0,
        year_completed=1974,
        registered_at="2020-06-01T00:00:00Z",
    )
    program.classify_significant(
        second["id"],
        base.engineer_a_id,
        breach_peak_outflow_cfs=7400,
        inundation_map_ref="IM-2020-C",
    )
    first_visit = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    return {"second_dam": second, "first_visit": first_visit}


def test_a_window_one_minute_inside_the_buffer_is_a_calendar_conflict(
    api, program, base, two_classified_dams
):
    """A second visit beginning 119 minutes after the first one ends is refused.

    PRD 3.3: "Both comparisons are strict, so a new window beginning exactly 120 minutes after an existing window ends does not conflict, while one beginning 119 minutes after it does."

    Design: Difficulty/resource_temporal_overlap/engineer_visit_rejected_inside_the_travel_buffer_but_allowed_exactly_at_it
    """
    second_dam = two_classified_dams["second_dam"]
    response = api.create_inspection(
        f.inspection_payload(
            second_dam["id"],
            base.engineer_a_id,
            window_start="2026-08-05T13:59:00Z",
            window_end="2026-08-05T16:00:00Z",
        ),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_ENGINEER_WINDOW_CONFLICT.value, 409)

    rows, meta = validate_paginated(
        api.list_inspections(program.admin, {"engineer_id": base.engineer_a_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [two_classified_dams["first_visit"]["id"]]


def test_a_window_exactly_at_the_buffer_boundary_is_scheduled(
    api, program, base, two_classified_dams
):
    """One minute later, exactly 120 minutes after the first visit ends, it is allowed.

    PRD 3.3: "An engineer's calendar is protected by a **travel buffer of 120 minutes** — two hours between consecutive site visits."

    Design: Difficulty/resource_temporal_overlap/engineer_visit_rejected_inside_the_travel_buffer_but_allowed_exactly_at_it
    """
    second_dam = two_classified_dams["second_dam"]
    scheduled = program.schedule_inspection(
        second_dam["id"],
        base.engineer_a_id,
        window_start="2026-08-05T14:00:00Z",
        window_end="2026-08-05T16:00:00Z",
    )
    assert scheduled["status"] == INSPECTION_SCHEDULED
    assert scheduled["dam_id"] == second_dam["id"]
    assert_instant(scheduled["window_start"], "2026-08-05T14:00:00Z", "window_start")

    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 2

    first = two_classified_dams["first_visit"]
    rows, meta = validate_paginated(
        api.list_inspections(program.admin, {"engineer_id": base.engineer_a_id})
    )
    assert meta["total_count"] == 2
    untouched = next(row for row in rows if row["id"] == first["id"])
    assert untouched["status"] == INSPECTION_SCHEDULED
    assert_instant(untouched["window_end"], "2026-08-05T12:00:00Z", "window_end")
    assert untouched["performed_at"] is None


# ---------------------------------------------------------------------------
# Reach channel capacity across touching release windows
# ---------------------------------------------------------------------------
@pytest.fixture()
def cedar_notch_releases(program, base):
    """One coordinated 800-cfs release plus two competitors on a touching window."""
    dam = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Cedar Notch Dam",
        nid_code="ST00131",
        height_ft=88,
        gross_storage_acre_ft=5000,
        crest_elevation_ft=1310.0,
        normal_pool_elevation_ft=1305.0,
        year_completed=1962,
    )
    program.classify_significant(
        dam["id"],
        base.engineer_a_id,
        breach_peak_outflow_cfs=14000,
        inundation_map_ref="IM-2019-D",
    )
    event = program.declare_event(
        dam["id"],
        declared_at="2026-08-01T00:00:00Z",
        trigger_description="Snowmelt plus rain on a full reservoir.",
        declared_inflow_cfs=1400,
    )
    first = program.request_drawdown(
        dam["id"],
        event["id"],
        requested_release_cfs=800,
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T06:00:00Z",
    )
    program.coordinate_drawdown(first["id"], reach_id=base.reach_id)
    second = program.request_drawdown(
        dam["id"],
        event["id"],
        requested_release_cfs=500,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    third = program.request_drawdown(
        dam["id"],
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    return {"dam": dam, "first": first, "second": second, "third": third}


def test_touching_windows_overlap_so_the_aggregate_breaches_channel_capacity(
    api, program, base, cedar_notch_releases
):
    """A window starting exactly when another ends still competes for the channel.

    PRD 3.7: "The **channel-capacity check** treats release windows as closed intervals, so windows that merely touch at an endpoint do overlap: the set of competing orders is every order on the same reach whose status is `COORDINATED` or `ACTIVE` and whose `window_start` is at or before the new order's `window_end` while its `window_end` is at or after the new order's `window_start`."

    Design: Difficulty/resource_temporal_overlap/reach_capacity_rejected_when_touching_release_windows_aggregate_past_capacity
    """
    reach_version = program.reach_version(base.reach_id)
    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 800.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1

    # 800 already committed plus 500 requested exceeds the 1200-cfs channel.
    response = api.coordinate_drawdown(
        cedar_notch_releases["second"]["id"],
        f.coordinate_payload(reach_version),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_REACH_CAPACITY_EXCEEDED.value, 409)

    rejected = program.get_drawdown(cedar_notch_releases["second"]["id"])
    assert rejected["status"] == DRAWDOWN_REQUESTED
    assert rejected["coordinated_at"] is None

    after = program.get_reach(base.reach_id)
    assert_cfs(after["committed_release_cfs"], 800.000, "committed_release_cfs")
    assert after["active_drawdown_count"] == 1
    # The rejection took no version, so the same expected value is still current.
    assert after["version"] == reach_version


def test_an_aggregate_exactly_at_channel_capacity_is_allowed(
    program, base, cedar_notch_releases
):
    """800 plus 400 equals the channel capacity exactly, and equality passes.

    PRD 3.7: "Their `requested_release_cfs` values are summed, and if that sum plus the new order's requested rate is strictly greater than the reach's `channel_capacity_cfs`, coordination is rejected with `ERR_REACH_CAPACITY_EXCEEDED`; exact equality with the channel capacity is allowed."

    Design: Difficulty/resource_temporal_overlap/reach_capacity_rejected_when_touching_release_windows_aggregate_past_capacity
    """
    coordinated = program.coordinate_drawdown(
        cedar_notch_releases["third"]["id"], reach_id=base.reach_id
    )
    assert coordinated["status"] == DRAWDOWN_COORDINATED
    assert_instant(coordinated["coordinated_at"], "2026-08-01T00:00:00Z", "coordinated_at")
    # 400 cfs over six hours.
    assert_acre_feet(
        coordinated["planned_release_acre_ft"], 198.347, "planned_release_acre_ft"
    )

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 1200.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 2


def test_the_dam_storage_commitment_sums_both_coordinated_releases(
    program, cedar_notch_releases
):
    """Committed plus available always reconciles to the gross storage figure.

    PRD 3.7: "The storage split is maintained as a strict conservation law: a dam's `committed_drawdown_acre_ft` is the sum of `planned_release_acre_ft` over its orders in `COORDINATED` or `ACTIVE`, and its `available_conservation_storage_acre_ft` is `gross_storage_acre_ft` less that committed figure, rounded half up to three decimal places, so that committed plus available always equals gross storage — before and after every coordination, completion, cancellation and cascade cancellation."

    Design: Difficulty/resource_temporal_overlap/reach_capacity_rejected_when_touching_release_windows_aggregate_past_capacity
    """
    dam_id = cedar_notch_releases["dam"]["id"]
    program.coordinate_drawdown(
        cedar_notch_releases["third"]["id"],
        reach_id=cedar_notch_releases["dam"]["river_reach_id"],
    )

    dam = program.get_dam(dam_id)
    # 396.694 from the 800-cfs release plus 198.347 from the 400-cfs release.
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 595.041, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        4404.959,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)
