"""Harvest windows: half-open overlap semantics and listing filters."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_harvest_window_payload,
    set_clock, create_released_variety, create_harvest_window,
    get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _window_payload(variety_id, start, end, region="CA-SALINAS", target=10000):
    return create_harvest_window_payload(
        variety_id, region_code=region, week_start=start, week_end=end,
        target_volume_kg=target)


def test_harvest_window_pure_adjacency_accepted(api):
    """PRD section 3.5: "Two windows for the same `region_code` and `variety_id`
    may not overlap; because the intervals are half-open, pure adjacency — one
    window's `week_end` equal to the other's `week_start` — is allowed, while
    any true overlap is rejected with `ERR_HARVEST_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/harvest_window_half_open_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    create_harvest_window(variety)  # WA [2026-09-28, 2026-10-05)
    resp = api.create_harvest_window(
        _window_payload(variety["id"], "2026-10-05T00:00:00Z",
                        "2026-10-12T00:00:00Z"),
        ADMIN)
    data = validate_success(resp, 201)
    assert data["week_start"].startswith("2026-10-05")
    assert data["booked_volume_kg"] == 0


def test_harvest_window_true_overlap_rejected(api):
    """PRD section 3.5: "any true overlap is rejected with
    `ERR_HARVEST_WINDOW_OVERLAP`."
    PRD section 3.5: "a `week_start` and a `week_end` delimiting a half-open
    interval — the window covers `week_start` up to but not including
    `week_end`".

    Design: Difficulty/resource_temporal_overlap/harvest_window_half_open_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    create_harvest_window(variety)  # WA [2026-09-28, 2026-10-05)
    create_harvest_window(variety, week_start="2026-10-05T00:00:00Z",
                          week_end="2026-10-12T00:00:00Z")  # WB adjacent
    resp = api.create_harvest_window(
        _window_payload(variety["id"], "2026-10-04T00:00:00Z",
                        "2026-10-11T00:00:00Z", target=5000),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_HARVEST_WINDOW_OVERLAP)


def test_harvest_windows_list_filters_by_region_and_variety(api):
    """PRD section 3.5: "Windows can be listed with filters on `variety_id` or
    `region_code`, and retrieved individually."

    Design: Corner/entities/harvest_windows_list_filters_by_region_and_variety
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    create_harvest_window(variety)  # CA-SALINAS [09-28, 10-05)
    create_harvest_window(variety, week_start="2026-10-05T00:00:00Z",
                          week_end="2026-10-12T00:00:00Z")  # CA-SALINAS
    create_harvest_window(variety, region_code="WA-SKAGIT",
                          target_volume_kg=4000)
    rows, meta = validate_paginated(api.list_harvest_windows(
        ADMIN, params={"variety_id": variety["id"]}))
    assert len(rows) == 3 and meta["total_count"] == 3
    rows, meta = validate_paginated(api.list_harvest_windows(
        ADMIN, params={"variety_id": variety["id"],
                       "region_code": "CA-SALINAS"}))
    assert len(rows) == 2 and meta["total_count"] == 2
    assert all(r["region_code"] == "CA-SALINAS" for r in rows)
    rows, meta = validate_paginated(api.list_harvest_windows(
        ADMIN, params={"region_code": "OR-WILLAMETTE"}))
    assert rows == [] and meta["total_count"] == 0 and meta["has_more"] is False
