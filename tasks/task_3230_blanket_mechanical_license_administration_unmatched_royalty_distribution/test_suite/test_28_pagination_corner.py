"""Queue B (corner) — pagination with status filter on usage reports."""
from test_helpers import (
    TEST_USERS, validate_paginated,
    set_clock, create_active_schedule, setup_active_dsp,
    create_report_with_lines, submit_report,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def test_pagination_with_status_filter(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100. The `offset` parameter sets how many items to
    skip and defaults to 0. Unless otherwise specified, every list endpoint
    returns its resources sorted by `created_at` in ascending order."

    Design: Corner/cross_cutting/pagination_with_status_filter
    """
    set_clock("2026-09-10T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    r_jun, _ = create_report_with_lines(dsp, dsp_headers, "2026-06", [])
    r_jul, _ = create_report_with_lines(dsp, dsp_headers, "2026-07", [])
    r_aug, _ = create_report_with_lines(dsp, dsp_headers, "2026-08", [
        {"track_title": "Sora", "plays_count": 10, "duration_seconds": 100,
         "isrc": "USAA19900051"},
    ])
    submit_report(dsp, dsp_headers, ack, r_aug)
    data, meta = validate_paginated(api_client.list_usage_reports(
        dsp["id"], dsp_headers,
        params={"status": "DRAFT", "limit": 1, "offset": 1}))
    assert meta["total_count"] == 2, f"two DRAFT reports; got {meta['total_count']}"
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == r_jul["id"], (
        f"offset 1 over created_at ASC skips the first DRAFT (June) and "
        f"returns July; got {data[0]['id']}")
