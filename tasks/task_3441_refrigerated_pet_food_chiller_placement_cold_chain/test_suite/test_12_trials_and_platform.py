"""Trial campaigns and platform-level concerns (PRD §2.1, §2.4, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_trial_campaign_payload,
    set_clock,
    setup_active_placement,
    validate_error,
    validate_success,
)


def test_trial_closed_interval_shared_date_is_overlap(api, placement_manager_headers):
    """PRD §3.8: "Two campaigns at the same store must keep clear of each other
    under two rules evaluated in a fixed intra-tier order. First, their
    closed-interval windows must not intersect at all — sharing even a single
    start or end date counts as overlap and is rejected with 409
    `ERR_TRIAL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/trial_calendar_closed_interval_with_gap
    """
    ctx = setup_active_placement()
    sid = ctx["store"]["id"]
    first = validate_success(
        api.create_trial_campaign(sid, create_trial_campaign_payload(
            name="Launch Demo", start_date="2026-09-10T00:00:00Z", end_date="2026-09-20T00:00:00Z"),
            placement_manager_headers),
        expected_status=201,
    )
    assert first["status"] == "ACTIVE"

    resp = api.create_trial_campaign(sid, create_trial_campaign_payload(
        name="Shared Date", start_date="2026-09-20T00:00:00Z", end_date="2026-09-25T00:00:00Z"),
        placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_OVERLAP)
    assert resp.status_code == 409, "closed intervals sharing an end/start date intersect"


def test_trial_gap_14_days_inclusive_boundary(api, placement_manager_headers):
    """PRD §3.8: "Second, a 14-day gap must separate one campaign's `end_date`
    from the next campaign's `start_date`; the boundary is inclusive, so a
    start exactly 14 days after a prior `end_date` is allowed, while fewer than
    14 days in either direction yields 422 `ERR_TRIAL_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/trial_calendar_closed_interval_with_gap
    """
    ctx = setup_active_placement()
    sid = ctx["store"]["id"]
    validate_success(
        api.create_trial_campaign(sid, create_trial_campaign_payload(
            name="Launch Demo", start_date="2026-09-10T00:00:00Z", end_date="2026-09-20T00:00:00Z"),
            placement_manager_headers),
        expected_status=201,
    )

    resp = api.create_trial_campaign(sid, create_trial_campaign_payload(
        name="One Day Gap", start_date="2026-09-21T00:00:00Z", end_date="2026-09-30T00:00:00Z"),
        placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_TRIAL_GAP_VIOLATION)
    assert resp.status_code == 422, "1-day gap < 14"

    exact = validate_success(
        api.create_trial_campaign(sid, create_trial_campaign_payload(
            name="Exact Gap", start_date="2026-10-04T00:00:00Z", end_date="2026-10-10T00:00:00Z"),
            placement_manager_headers),
        expected_status=201,
    )
    assert exact["status"] == "ACTIVE", "start exactly 14 days after the prior end_date is allowed"


def test_trial_campaign_auto_completes_after_window(api, placement_manager_headers):
    """PRD §2.4: "an `ACTIVE` trial campaign reads as `COMPLETED` once the
    logical now is later than one day after its `end_date`."
    PRD §3.8: "A campaign is `ACTIVE` on creation, materializes `COMPLETED`
    lazily once the logical now passes one day beyond its `end_date`, and
    campaigns are listed in `start_date` ascending order."

    Design: Corner/state_machines/trial_campaign_auto_completes_after_window
    """
    ctx = setup_active_placement()
    sid = ctx["store"]["id"]
    created = validate_success(
        api.create_trial_campaign(sid, create_trial_campaign_payload(
            name="Launch Demo", start_date="2026-09-10T00:00:00Z", end_date="2026-09-20T00:00:00Z"),
            placement_manager_headers),
        expected_status=201,
    )
    assert created["status"] == "ACTIVE"

    set_clock("2026-09-21T00:00:01Z")  # one second past end_date + 1 day
    listed = validate_success(api.list_trial_campaigns(sid, placement_manager_headers))
    assert listed[0]["id"] == created["id"]
    assert listed[0]["status"] == "COMPLETED", "lazy materialization on read, no write required"


def test_clock_regression_returns_400(api, platform_admin_headers):
    """PRD §2.4: "The clock is forward-only: `to_iso8601` must be strictly
    greater than the current logical time, and a value equal to or earlier than
    the current logical time is rejected with 400 `ERR_CLOCK_REGRESSION`."

    Design: Corner/errors/clock_regression_returns_400
    """
    set_clock("2026-09-05T00:00:00Z")
    resp = api.set_clock({"to_iso8601": "2026-09-04T00:00:00Z"}, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    assert resp.status_code == 400

    # The clock is unchanged: re-setting the exact current value is still a regression.
    resp = api.set_clock({"to_iso8601": "2026-09-05T00:00:00Z"}, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    assert resp.status_code == 400, "equal is not strictly greater; clock kept its prior value"


def test_unauthenticated_missing_headers_returns_401(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming their operational
    capacity. If either header is missing or blank, or if the supplied role is
    not one of the declared roles, the request is rejected with 401
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_missing_headers_returns_401
    """
    resp = api.list_chillers(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401
