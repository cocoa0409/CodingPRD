"""Closed-interval occupancy versus half-open accounting periods, and the
scope each overlap rule is measured against."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    APPROVER,
    OPERATOR,
    SERVICE_ENGINEER,
    create_customer,
    create_ppa,
    create_settlement_line,
    get_site,
    set_clock,
    setup_active_ppa,
    take_resource_hold,
)


def test_two_holds_that_merely_touch_are_treated_as_overlapping():
    """PRD §2.6: "two such windows at the same site may never overlap — not even by touching, since a
    window whose end equals another's start is treated as overlapping rather than adjacent."

    Design: Difficulty/resource_temporal_overlap/touching_resource_hold_windows_conflict_under_closed_interval_semantics
    """
    set_clock()
    site = api_create_site()
    first = take_resource_hold(
        site["id"],
        requested_therms=30000,
        window_start_iso8601="2026-04-01T00:00:00Z",
        window_end_iso8601="2026-04-02T00:00:00Z",
    )
    assert first["lifecycle_state"] == "DELIVERY_SCHEDULED"

    response = api_client.take_resource_hold(
        site["id"],
        OPERATOR,
        {
            "requested_therms": 30000,
            "window_start_iso8601": "2026-04-02T00:00:00Z",
            "window_end_iso8601": "2026-04-03T00:00:00Z",
        },
    )

    validate_error(response, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)
    after = get_site(site["id"])
    assert after["draw_position_therms"] == after["initial_fuel_inventory_therms"] - 30000, (
        f"the refused hold must not draw the pool; got {after['draw_position_therms']}"
    )


def test_the_refused_touching_hold_creates_no_second_row():
    """PRD §3.3: "a hold that would breach any
    of them is refused with the corresponding code rather than being partially created."

    Design: Difficulty/resource_temporal_overlap/touching_resource_hold_windows_conflict_under_closed_interval_semantics
    """
    set_clock()
    site = api_create_site()
    take_resource_hold(
        site["id"],
        requested_therms=30000,
        window_start_iso8601="2026-04-01T00:00:00Z",
        window_end_iso8601="2026-04-02T00:00:00Z",
    )
    api_client.take_resource_hold(
        site["id"],
        OPERATOR,
        {
            "requested_therms": 30000,
            "window_start_iso8601": "2026-04-02T00:00:00Z",
            "window_end_iso8601": "2026-04-03T00:00:00Z",
        },
    )

    rows = validate_success(
        api_client.list_site_fuel_deliveries(site["id"], OPERATOR)
    )
    data = rows["data"] if isinstance(rows, dict) and "data" in rows else rows
    assert len(data) == 1, f"the site still carries exactly one hold row; found {len(data)}"


def test_a_hold_window_that_merely_touches_a_settlement_period_is_still_refused():
    """PRD §2.6: "A request that would create such an overlap is refused with `ERR_DELIVERY_WINDOW_OVERLAP`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/touching_resource_hold_windows_conflict_under_closed_interval_semantics
    """
    set_clock()
    site = api_create_site()
    take_resource_hold(
        site["id"],
        requested_therms=10000,
        window_start_iso8601="2026-04-01T00:00:00Z",
        window_end_iso8601="2026-04-05T00:00:00Z",
    )

    response = api_client.take_resource_hold(
        site["id"],
        OPERATOR,
        {
            "requested_therms": 10000,
            "window_start_iso8601": "2026-03-28T00:00:00Z",
            "window_end_iso8601": "2026-04-01T00:00:00Z",
        },
    )
    validate_error(response, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)


def test_settlement_periods_that_merely_touch_are_admitted():
    """PRD §3.4: "A line whose interval ends exactly where
    its successor's interval begins does not double-count that instant, because the period is
    half-open at the end."

    Design: Difficulty/resource_temporal_overlap/adjacent_settlement_periods_are_admitted_under_half_open_semantics
    """
    ctx = setup_active_ppa()
    prior = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )

    successor = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-04-11T00:00:00Z",
        period_end="2026-04-25T00:00:00Z",
        metered_kwh=100000,
    )

    assert successor["status"] == "SETTLEMENT_DRAFT", (
        "an adjacent period is admitted under half-open semantics; got "
        f"{successor['status']}"
    )
    assert successor["period_start"] == "2026-04-11T00:00:00Z"
    assert prior["status"] == "SETTLEMENT_DRAFT"


def test_a_genuinely_overlapping_settlement_period_is_refused():
    """PRD §3.4: "Its half-open interval from
    `period_start` to `period_end` must not overlap any existing line on the same contract other
    than lines that have been reversed, or the request is refused with
    `ERR_SETTLEMENT_PERIOD_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/adjacent_settlement_periods_are_admitted_under_half_open_semantics
    """
    ctx = setup_active_ppa()
    create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-03-11T00:00:00Z",
        period_end="2026-04-11T00:00:00Z",
    )
    ppa = validate_success(api_client.get_ppa(ctx["ppa_id"], ANALYST))

    response = api_client.create_settlement_line(
        ctx["ppa_id"],
        ANALYST,
        {
            "period_start": "2026-03-20T00:00:00Z",
            "period_end": "2026-04-20T00:00:00Z",
            "metered_kwh": 100000,
            "downtime_hours": 1.0,
            "customer_source_deadline_iso8601": "2026-04-01T00:00:00Z",
            "hourly_settlement": False,
            "expected_ppa_version": ppa["version"],
        },
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP)


def test_identical_maintenance_windows_at_two_sites_do_not_conflict():
    """PRD §3.7: "the summed clearance radius across the site's active and
    window-open plans must not exceed the site's `clearance_zone_capacity`".

    Design: Difficulty/resource_temporal_overlap/same_day_maintenance_windows_at_two_sites_do_not_conflict
    """
    ctx = setup_two_sites_with_live_contracts()

    plan_north = validate_success(
        api_client.create_service_plan(
            ctx["ppa_north_id"],
            SERVICE_ENGINEER,
            {
                "remote_monitoring_status": "MONITORING_LINKED",
                "radius_buffer_m": 10.0,
                "window_start_iso8601": "2026-04-01T00:00:00Z",
                "window_end_iso8601": "2026-04-08T00:00:00Z",
            },
        ),
        expected_status=201,
    )
    plan_south = validate_success(
        api_client.create_service_plan(
            ctx["ppa_south_id"],
            SERVICE_ENGINEER,
            {
                "remote_monitoring_status": "MONITORING_LINKED",
                "radius_buffer_m": 10.0,
                "window_start_iso8601": "2026-04-01T00:00:00Z",
                "window_end_iso8601": "2026-04-08T00:00:00Z",
            },
        ),
        expected_status=201,
    )

    assert plan_south["lifecycle_state"] == "SERVICE_PLAN_DRAFT"
    assert plan_south["window_start_iso8601"] == plan_north["window_start_iso8601"]
    # PRD §3.7: "the plan's contribution to the site's clearance total is its
    # `radius_buffer_m` counted only while the plan is in `SERVICE_ACTIVE` or
    # `SERVICE_MAINTENANCE_WINDOW_OPEN`". Both hand-created plans are drafts, so
    # neither site's clearance total moves — and because the gap rule is scoped
    # per site, the identical windows at two sites do not conflict.
    assert get_site(ctx["site_north_id"])["clearance_zone_used"] == 0.0
    assert get_site(ctx["site_south_id"])["clearance_zone_used"] == 0.0


# --- local plumbing ----------------------------------------------------------
def api_create_site():
    from test_helpers.fixtures import create_site

    return create_site()


def setup_two_sites_with_live_contracts():
    set_clock()
    from test_helpers.fixtures import create_site

    north = create_site(name="Vineyard North")
    south = create_site(name="Vineyard South")
    customer = create_customer(name="Vineyard Group")
    ppa_north = create_ppa(north["id"], customer["id"], contracted_kw=300)
    ppa_south = create_ppa(south["id"], customer["id"], contracted_kw=300)
    validate_success(api_client.activate_ppa(ppa_north["id"], OPERATOR))
    validate_success(api_client.activate_ppa(ppa_south["id"], OPERATOR))
    return {
        "site_north_id": north["id"],
        "site_south_id": south["id"],
        "ppa_north_id": ppa_north["id"],
        "ppa_south_id": ppa_south["id"],
        "customer_id": customer["id"],
    }