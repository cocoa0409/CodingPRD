"""Which single defect is reported when a request breaches two different rules."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    OPERATOR,
    SERVICE_ENGINEER,
    create_settlement_line,
    get_ppa,
    get_site,
    setup_active_ppa,
    take_resource_hold,
)


def _create_plan(ppa_id, payload):
    return api_client.create_service_plan(ppa_id, SERVICE_ENGINEER, payload)


def _create_line(ppa_id, **overrides):
    payload = {
        "period_start": "2026-04-05T00:00:00Z",
        "period_end": "2026-04-04T00:00:00Z",
        "metered_kwh": 200000,
        "downtime_hours": 3.0,
        "customer_source_deadline_iso8601": "2026-04-02T00:00:00Z",
        "hourly_settlement": False,
        "expected_ppa_version": get_ppa(ppa_id)["version"],
    }
    payload.update(overrides)
    return api_client.create_settlement_line(ppa_id, ANALYST, payload)


def test_a_frozen_site_reports_the_posture_problem_not_the_capacity_shortfall():
    """PRD §2.4: "a request that would breach both a safety
    rule and a fiscal rule is reported against the safety rule".
    PRD §2.5: "A `SiteOperator` may lift a suspension only when the site's posture is
    `SITE_SUSPENDED`".

    Design: Difficulty/priority_pair_validation_conflict/frozen_site_wins_over_draw_position_shortfall
    """
    ctx = setup_active_ppa()
    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE")
    )
    frozen = get_site(ctx["site_id"])

    # The volume also exceeds the frozen site's pool, so two guards are breached.
    response = api_client.take_resource_hold(
        ctx["site_id"],
        OPERATOR,
        {
            "requested_therms": 250000,
            "window_start_iso8601": "2026-04-01T00:00:00Z",
            "window_end_iso8601": "2026-04-04T00:00:00Z",
        },
    )

    validate_error(response, ApiErrorId.ERR_SITE_FROZEN)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_INSUFFICIENT_DRAW_POSITION.value
    )
    assert get_site(ctx["site_id"])["draw_position_therms"] == frozen["draw_position_therms"], (
        "a refused hold leaves the pool untouched"
    )


def test_a_frozen_site_still_reports_the_posture_problem_when_the_pool_would_cover_the_hold():
    """PRD §2.5: "A facility may be suspended only while its posture is currently `SITE_ACTIVE` and only while
    at least one of its contracts is in `PPA_ACTIVE` — a site with no live contract has nothing
    to suspend."

    Design: Difficulty/priority_pair_validation_conflict/frozen_site_wins_over_draw_position_shortfall
    """
    ctx = setup_active_ppa()
    validate_success(
        api_client.freeze_site(ctx["site_id"], OPERATOR, "FUEL_SHORTAGE")
    )

    # A volume comfortably inside the pool: only the posture gate can fail.
    response = api_client.take_resource_hold(
        ctx["site_id"],
        OPERATOR,
        {
            "requested_therms": 1000,
            "window_start_iso8601": "2026-04-01T00:00:00Z",
            "window_end_iso8601": "2026-04-04T00:00:00Z",
        },
    )
    validate_error(response, ApiErrorId.ERR_SITE_FROZEN)


def test_a_window_too_close_to_an_open_window_is_refused_under_the_gap_rule():
    """PRD §3.7: "Maintenance windows at one
    site must be pairwise separated by at least `MAINTENANCE_GAP_DAYS`, and a new window that comes
    closer than that to an already open window at the same site is refused with
    `ERR_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/window_gap_wins_over_settlement_period_overlap
    """
    ctx = setup_active_ppa()
    validate_success(
        _create_plan(
            ctx["ppa_id"],
            {
                "remote_monitoring_status": "MONITORING_LINKED",
                "radius_buffer_m": 10.0,
                "window_start_iso8601": "2026-04-01T00:00:00Z",
                "window_end_iso8601": "2026-04-10T00:00:00Z",
            },
        ),
        expected_status=201,
    )

    response = _create_plan(
        ctx["ppa_id"],
        {
            "remote_monitoring_status": "MONITORING_LINKED",
            "radius_buffer_m": 10.0,
            "window_start_iso8601": "2026-03-20T00:00:00Z",
            "window_end_iso8601": "2026-04-11T00:00:00Z",
        },
    )

    validate_error(response, ApiErrorId.ERR_WINDOW_VIOLATION)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value
    )


def test_the_gap_rule_also_governs_a_window_that_starts_inside_an_open_window():
    """PRD §3.7: "The plan lifecycle has one entry edge and several exits."

    Design: Difficulty/priority_pair_validation_conflict/window_gap_wins_over_settlement_period_overlap
    """
    ctx = setup_active_ppa()
    validate_success(
        _create_plan(
            ctx["ppa_id"],
            {
                "remote_monitoring_status": "MONITORING_LINKED",
                "radius_buffer_m": 10.0,
                "window_start_iso8601": "2026-04-01T00:00:00Z",
                "window_end_iso8601": "2026-04-10T00:00:00Z",
            },
        ),
        expected_status=201,
    )
    stuck = _create_plan(
        ctx["ppa_id"],
        {
            "remote_monitoring_status": "MONITORING_LINKED",
            "radius_buffer_m": 5.0,
            "window_start_iso8601": "2026-04-05T00:00:00Z",
            "window_end_iso8601": "2026-04-06T00:00:00Z",
        },
    )
    assert stuck.status_code == 422, (
        f"a window nested inside an open one also violates the gap; got {stuck.status_code}"
    )


def test_an_inverted_settlement_period_is_refused_under_the_period_rule():
    """PRD §3.4: "Its `period_end` must be strictly after its `period_start`, or the request
    is refused with `ERR_SETTLEMENT_PERIOD_INVALID` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/window_gap_wins_over_settlement_period_overlap
    """
    ctx = setup_active_ppa()

    response = _create_line(
        ctx["ppa_id"],
        period_start="2026-04-05T00:00:00Z",
        period_end="2026-04-05T00:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_PERIOD_INVALID)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value
    )


def test_an_inverted_period_that_also_overlaps_an_existing_line_reports_one_error_only():
    """PRD §2.4: "Validation runs in a fixed order, and the order is observable because only the first failure is
    reported."

    Design: Difficulty/priority_pair_validation_conflict/window_gap_wins_over_settlement_period_overlap
    """
    ctx = setup_active_ppa()
    create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )

    # period_end is not after period_start, and the inverted span also lands
    # inside the existing line's interval.
    response = _create_line(
        ctx["ppa_id"],
        period_start="2026-02-15T00:00:00Z",
        period_end="2026-02-14T00:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_SETTLEMENT_PERIOD_INVALID)
    assert "error_id" not in response.json()["data"].get("secondary_error", {})
    rows = validate_success(
        api_client.list_settlement_lines(ctx["ppa_id"], ANALYST)
    )
    data = rows["data"] if isinstance(rows, dict) and "data" in rows else rows
    assert len(data) == 1, f"the refused line must not be persisted; found {len(data)} rows"