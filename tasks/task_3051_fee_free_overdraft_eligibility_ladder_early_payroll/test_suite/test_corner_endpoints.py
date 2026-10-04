"""Breadth tests for envelope shape, pagination, and the logical clock."""

import test_helpers as th
from test_helpers import fixtures


def test_members_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items before returning results and defaults to
    0. Unless a list endpoint states a different ordering in §3, results are
    sorted by `created_at` in ascending order."
    PRD §2.3: "Paginated list responses carry four fields in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/members_list_pagination_envelope
    """
    for i, ref in enumerate(["pg1", "pg2", "pg3"], start=1):
        fixtures.create_member(
            api, external_ref=ref, full_name=f"P {i}", enrolled_at="2025-09-01T00:00:00Z"
        )

    resp = api.list_members(th.TEST_USERS["program_ops"], params={"limit": 2, "offset": 0})
    data, meta = th.validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    body = resp.json()
    assert body["response_type"] == "array"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_clock_default_and_set(api):
    """PRD §2.10: "All time-derived behavior in this document — tenure windows,
    scoring windows, notice periods, aging thresholds, dispute deadlines,
    reconciliation windows — reads from a single server-side logical clock,
    never from wall-clock time. When the server starts and the clock has never
    been set, the clock reads 2026-09-01T00:00:00Z."
    PRD §3.1: "From `enrolled_at`, the system derives `tenure_days`: the whole
    number of days (fractional days discarded) between enrollment and the
    current logical clock."

    Design: Corner/endpoints/clock_default_and_set
    """
    member = fixtures.create_member(
        api, external_ref="clk1", full_name="Clock One", enrolled_at="2026-08-01T00:00:00Z"
    )
    # Default clock reads 2026-09-01, so a member enrolled 2026-08-01 shows
    # 31 whole days of tenure.
    assert member["tenure_days"] == 31, f"tenure_days: {member.get('tenure_days')}"

    resp = api.set_clock(
        th.factories.clock_payload("2026-09-16T00:00:00Z"), th.TEST_USERS["program_ops"]
    )
    data = th.validate_success(resp, expected_status=200)
    assert data["current_utc"].startswith("2026-09-16T00:00:00")
