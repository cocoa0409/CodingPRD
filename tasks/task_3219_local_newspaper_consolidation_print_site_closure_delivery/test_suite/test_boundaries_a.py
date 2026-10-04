"""Difficulty queue A — boundary_precision_check on two different metrics.

One boundary sits at ratio equality (nine of ten markets on time against a floor of
90); the other sits at exact adjacency on the dock calendar, where a window opening
exactly at the previous window's close does not overlap under half-open intervals.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_edition,
    get_compliance,
    validate_error,
    validate_success,
    setup_ratio_at_floor_with_sites,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── Ratio equality boundary ─────────────────────────────────────────

@pytest.fixture
def ratio_at_the_floor():
    """Ten counted markets, exactly nine of them on time, against a floor of 90."""
    hub, site, region, markets, editions, routes = setup_ratio_at_floor_with_sites(
        clock=CLOCK_2026_09_30, on_time_count=9, late_count=1)
    return hub, site, region, markets, editions


def test_nine_of_ten_on_time_satisfies_the_floor(ratio_at_the_floor):
    """PRD §2.9: "With ten counted markets and `min_on_time_ratio_pct` of 90, nine
    on-time markets pass: 900 is at or above 900."
    PRD §2.9: "The gate is satisfied when the number of on-time markets multiplied
    by 100 is at or above `min_on_time_ratio_pct` multiplied by the number of
    counted markets".

    Design: Difficulty/boundary_precision_check/on_time_ratio_equality_satisfies_the_floor
    """
    hub, site, region, markets, editions = ratio_at_the_floor

    compliance = get_compliance(hub["id"])

    assert compliance["counted_market_count"] == 10, (
        f"got {compliance['counted_market_count']}"
    )
    assert compliance["on_time_market_count"] == 9, (
        f"got {compliance['on_time_market_count']}"
    )
    assert compliance["min_on_time_ratio_pct"] == 90
    assert compliance["is_legal_notice_ratio_compliant"] is True, (
        "equality satisfies the rule: 9 * 100 >= 90 * 10"
    )


def test_ratio_equality_leaves_the_block_cleared(ratio_at_the_floor):
    """PRD §2.9: "A failed gate sets the hub's `legal_notice_block` to true."
    PRD §2.9: "With ten counted markets and `min_on_time_ratio_pct` of 90, nine
    on-time markets pass: 900 is at or above 900."

    Design: Difficulty/boundary_precision_check/on_time_ratio_equality_satisfies_the_floor
    """
    hub, site, region, markets, editions = ratio_at_the_floor

    compliance = get_compliance(hub["id"])
    refreshed = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)

    assert compliance["is_legal_notice_ratio_compliant"] is True
    assert compliance["legal_notice_block"] is False, (
        "a passing gate leaves the block false"
    )
    assert refreshed["legal_notice_block"] is False


def test_dropping_one_more_market_off_time_breaks_the_floor(ratio_at_the_floor):
    """PRD §2.9: "The gate is satisfied when the number of on-time markets
    multiplied by 100 is at or above `min_on_time_ratio_pct` multiplied by the
    number of counted markets — an exact integer comparison with no floating point,
    and equality satisfies it."
    PRD §2.9: "Because the block is derived rather than stored by hand, every event
    that can change a market's on-time status or remove a market from the count
    re-examines the ratio and refreshes the flag".

    Design: Difficulty/boundary_precision_check/on_time_ratio_equality_satisfies_the_floor
    """
    hub, site, region, markets, editions = ratio_at_the_floor

    assert get_compliance(hub["id"])["is_legal_notice_ratio_compliant"] is True

    # A correction on one still-on-time market pulls it off time, taking the
    # count from 9 of 10 down to 8 of 10 and breaking the equality.
    on_time_edition = editions[0]
    validate_success(api.dispatch_edition(on_time_edition["id"], PRINT_OPS), 200)
    validate_success(api.deliver_edition(on_time_edition["id"], PRINT_OPS), 200)

    doctored = create_edition(
        markets[0]["id"], site["id"], slug="2026-09-22", page_count=20,
        requested_print_run_copies=200000)
    assert doctored["minutes_late"] > 0, (
        "the injected edition must be late for the boundary to move"
    )
    validate_success(api.dispatch_edition(doctored["id"], PRINT_OPS), 200)

    compliance = get_compliance(hub["id"])
    assert compliance["is_legal_notice_ratio_compliant"] is False, (
        f"8 of 10 against a floor of 90 must fail, got "
        f"{compliance['on_time_market_count']} of {compliance['counted_market_count']}"
    )
    assert validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["legal_notice_block"] is True


# ─── Dock adjacency boundary ─────────────────────────────────────────

@pytest.fixture
def dock_with_one_departure():
    """Site KOT with loading_slot_minutes 30 and max_concurrent_departures 1.

    One route dispatches at 01:00, occupying the half-open window [01:00, 01:30).
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"], max_concurrent_departures=1,
                       loading_slot_minutes=30)
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    # The second market must carry no guaranteed floor and a deadline far enough
    # out that a shady-but-legal, non-adjacent window can still be built.
    other = create_market(region["id"], name="Fallow", weighted_demand_units=6000,
                          publication_deadline_utc="12:00",
                          on_time_margin_minutes=30, guaranteed_floor_copies=0,
                          single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    return hub, site, region, market, other


def test_a_window_opening_at_the_previous_close_does_not_overlap(
        dock_with_one_departure):
    """PRD §2.10: "Windows are half-open — the interval
    `[dispatch_cutoff_utc, dispatch_cutoff_utc + loading_slot_minutes)` — so two
    departures that abut exactly do not collide, while one that starts inside
    another's window does."

    Design: Difficulty/boundary_precision_check/contractor_reinstatement_never_undoes_a_zero_stop_capacity_edge
    """
    hub, site, region, market, dock_other_market = dock_with_one_departure

    adjacent = validate_success(
        api.create_print_route(
            site["id"],
            {
                "destination_market_id": market["id"],
                "transit_minutes": 130,
                "dispatch_cutoff_utc": "01:30",
                "is_direct_hop": True,
                "buffer_minutes": 45,
            },
            PRINT_OPS),
        201,
    )

    assert adjacent["dispatch_cutoff_utc"] == "01:30"
    assert adjacent["status"] == "eligible"


def test_a_window_opening_one_minute_inside_collides(dock_with_one_departure):
    """PRD §2.10: "A new route whose window overlaps an existing departure at the
    same site is refused with `ERR_DOCK_SLOT_CONFLICT` (HTTP 409), unless the
    site's `max_concurrent_departures` still has room for one further overlapping
    departure."

    Design: Difficulty/boundary_precision_check/contractor_reinstatement_never_undoes_a_zero_stop_capacity_edge
    """
    hub, site, region, market, dock_other_market = dock_with_one_departure

    response = api.create_print_route(
        site["id"],
        {
            "destination_market_id": dock_other_market["id"],
            "transit_minutes": 140,
            "dispatch_cutoff_utc": "01:29",
            "is_direct_hop": True,
            "buffer_minutes": 45,
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_DOCK_SLOT_CONFLICT")
    assert response.status_code == 409, (
        f"the dock refusal carries HTTP 409, got {response.status_code}"
    )
    assert error["error_id"] == "ERR_DOCK_SLOT_CONFLICT"


def test_a_saturated_site_refuses_every_further_overlapping_window(
        dock_with_one_departure):
    """PRD §2.10: "Each site declares how many route dispatch windows may overlap
    through `max_concurrent_departures`, and each route occupies a loading window
    of `loading_slot_minutes` starting at its `dispatch_cutoff_utc`."
    PRD §2.10: "A new route whose window overlaps an existing departure at the same
    site is refused with `ERR_DOCK_SLOT_CONFLICT` (HTTP 409), unless the site's
    `max_concurrent_departures` still has room for one further overlapping
    departure."

    Design: Difficulty/boundary_precision_check/contractor_reinstatement_never_undoes_a_zero_stop_capacity_edge
    """
    hub, site, region, market, dock_other_market = dock_with_one_departure

    site_row = validate_success(api.get_print_site(site["id"], PRINT_OPS), 200)
    assert site_row["max_concurrent_departures"] == 1
    assert site_row["loading_slot_minutes"] == 30

    # The only departure occupies [01:00, 01:30) and the cap is one, so every
    # window that overlaps it is refused -- there is no room for one further
    # overlapping departure.
    for cutoff in ("01:15", "01:29"):
        inside = api.create_print_route(
            site["id"],
            {
                "destination_market_id": dock_other_market["id"],
                "transit_minutes": 140,
                "dispatch_cutoff_utc": cutoff,
                "is_direct_hop": True,
                "buffer_minutes": 45,
            },
            PRINT_OPS,
        )
        assert inside.status_code == 409, (
            f"a window opening at {cutoff} overlaps [01:00, 01:30), got "
            f"{inside.status_code}"
        )
        assert inside.json()["data"]["error_id"] == "ERR_DOCK_SLOT_CONFLICT"

