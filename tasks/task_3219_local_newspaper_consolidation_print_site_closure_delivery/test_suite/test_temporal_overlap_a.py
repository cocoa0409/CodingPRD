"""Difficulty queue A — resource_temporal_overlap on two interval semantics.

The dock calendar uses half-open intervals with a per-departure loading buffer
counted against `max_concurrent_departures`; the stop pause window is closed-inclusive
on both ends and counts paused stops against the route's aggregate stop capacity.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_stop_response,
    terminate_stop,
    get_stop,
    get_print_site,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


# ─── Dock occupancy boundary ─────────────────────────────────────────

@pytest.fixture
def dock_with_room_for_two():
    """Site KOT with loading_slot_minutes 30, max_concurrent_departures 2, route at 01:00."""
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"], max_concurrent_departures=2,
                       loading_slot_minutes=30)
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    return hub, site, region, market


def test_one_further_overlap_is_accepted_inside_the_declared_concurrency(
        dock_with_room_for_two):
    """PRD §2.10: "Each site declares how many route dispatch windows may overlap
    through `max_concurrent_departures`, and each route occupies a loading window
    of `loading_slot_minutes` starting at its `dispatch_cutoff_utc`."
    PRD §2.10: "A new route whose window overlaps an existing departure at the same
    site is refused with `ERR_DOCK_SLOT_CONFLICT` (HTTP 409), unless the site's
    `max_concurrent_departures` still has room for one further overlapping
    departure."

    Design: Difficulty/resource_temporal_overlap/dock_loading_window_half_open_adjacency
    """
    hub, site, region, market = dock_with_room_for_two

    site_row = get_print_site(site["id"])
    assert site_row["max_concurrent_departures"] == 2
    assert site_row["loading_slot_minutes"] == 30

    second = validate_success(
        api.create_print_route(
            site["id"],
            {
                "destination_market_id": market["id"],
                "transit_minutes": 130,
                "dispatch_cutoff_utc": "01:15",
                "is_direct_hop": True,
                "buffer_minutes": 45,
            },
            PRINT_OPS),
        201,
    )

    assert second["dispatch_cutoff_utc"] == "01:15"
    assert second["status"] == "eligible"


def test_a_third_overlap_is_refused_once_the_concurrency_is_spent(
        dock_with_room_for_two):
    """PRD §2.10: "Windows are half-open — the interval
    `[dispatch_cutoff_utc, dispatch_cutoff_utc + loading_slot_minutes)` — so two
    departures that abut exactly do not collide, while one that starts inside
    another's window does."

    Design: Difficulty/resource_temporal_overlap/dock_loading_window_half_open_adjacency
    """
    hub, site, region, market = dock_with_room_for_two

    validate_success(
        api.create_print_route(
            site["id"],
            {
                "destination_market_id": market["id"],
                "transit_minutes": 130,
                "dispatch_cutoff_utc": "01:15",
                "is_direct_hop": True,
                "buffer_minutes": 45,
            },
            PRINT_OPS),
        201,
    )

    response = api.create_print_route(
        site["id"],
        {
            "destination_market_id": market["id"],
            "transit_minutes": 140,
            "dispatch_cutoff_utc": "01:20",
            "is_direct_hop": True,
            "buffer_minutes": 45,
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_DOCK_SLOT_CONFLICT")
    assert response.status_code == 409, (
        f"the refusal carries HTTP 409, got {response.status_code}"
    )
    assert error["error_id"] == "ERR_DOCK_SLOT_CONFLICT"


# ─── Pause-window and aggregate capacity semantics ───────────────────

@pytest.fixture
def route_with_full_stop_capacity():
    """Contractor Cedar Hill with a route of stop_capacity 3 carrying S1..S3."""
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"],
                                           stop_capacity=3)
    stops = [
        create_stop(delivery_route["id"], market["id"], stop_code=f"S{i}")
        for i in range(1, 4)
    ]
    return hub, market, contractor, delivery_route, stops


def test_the_pause_window_is_counted_inclusively_on_both_ends(
        route_with_full_stop_capacity):
    """PRD §3.3: "The `pause_window_days` is computed as the end date minus the
    start date plus one when both dates are supplied, and zero otherwise".

    Design: Difficulty/resource_temporal_overlap/delivery_stop_pause_window_inclusive_aggregate_capacity
    """
    hub, market, contractor, delivery_route, stops = route_with_full_stop_capacity

    s1 = get_stop(stops[0]["id"])

    assert s1["pause_start_date"] == "2026-10-05"
    assert s1["pause_end_date"] == "2026-10-09"
    assert s1["pause_window_days"] == 5, (
        f"2026-10-05..2026-10-09 inclusive is five days, got "
        f"{s1['pause_window_days']}"
    )
    assert s1["status"] == "active"


def test_paused_stops_occupy_aggregate_capacity_until_they_terminate(
        route_with_full_stop_capacity):
    """PRD §3.3: "Adding a stop that would push the route's non-terminated stop
    count above its `stop_capacity` is refused with `ERR_STOP_CAPACITY_EXCEEDED`
    (HTTP 422)".

    PRD §3.3: "each with a `print_market_id`, a `stop_code` unique within the
    route, the `contracted_daily_copies` it takes per night".

    Design: Difficulty/resource_temporal_overlap/delivery_stop_pause_window_inclusive_aggregate_capacity
    """
    hub, market, contractor, delivery_route, stops = route_with_full_stop_capacity

    refused = create_stop_response(delivery_route["id"], market["id"], stop_code="S4")
    error = validate_error(refused, "ERR_STOP_CAPACITY_EXCEEDED")
    assert refused.status_code == 422, (
        f"the capacity refusal carries HTTP 422, got {refused.status_code}"
    )
    assert error["error_id"] == "ERR_STOP_CAPACITY_EXCEEDED"

    terminated = terminate_stop(stops[2]["id"])
    assert terminated["status"] == "terminated"

    accepted = create_stop_response(delivery_route["id"], market["id"], stop_code="S4")
    assert accepted.status_code == 201, (
        "a terminated stop leaves the aggregate capacity, so the next stop must fit: "
        f"{accepted.status_code} {accepted.text}"
    )
    assert accepted.json()["data"]["status"] == "active"