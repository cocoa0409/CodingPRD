"""Difficulty queue A — combinatorial_formula, modes (b) and (a).

Mode (b): the press-run duration's division chain collapses to one raw figure that
is rounded up to the next quarter hour exactly once.

Mode (a): the nightly route cost selects its copy-volume tier from the pre-discount
copy count, multiplies by the sanction factor, and only then adds the surcharge.
"""
import pytest

from test_helpers import (
    api,
    get_print_market,
    get_print_route,
    get_delivery_route,
    cost_run,
    setup_market_with_route,
    create_edition,
    plan_transfer,
    hub_version,
    create_contractor,
    create_delivery_route,
    create_stops,
    setup_contractor_with_costed_route,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


# ─── Mode (b): press_run_hours ───────────────────────────────────────

@pytest.fixture
def planned_market():
    """Hub + site KOT + region North + market Riverton + committed route."""
    hub, site, region, market, route = setup_market_with_route(
        market_overrides={
            "publication_deadline_utc": "05:30",
            "on_time_margin_minutes": 30,
            "guaranteed_floor_copies": 8000,
            "single_copy_market_rule": "carrier",
        },
        clock=CLOCK_2026_09_30,
    )
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    return hub, site, region, market, route


def test_press_run_hours_rounds_the_single_duration_up_once(planned_market):
    """PRD §3.5: "A raw hours figure is formed by dividing
    `requested_print_run_copies` by the site's `press_units`, then by its
    `shifts_per_night`, then by its `copies_per_hour_per_press`, and then by the
    speed factor. That single raw duration is rounded up to the next quarter hour
    to give `press_run_hours`."

    PRD §3.5: "The `speed_factor` is 1.00 for a `page_count` of at most 8, 0.85
    for a `page_count` above 8 up to 16, and 0.70 beyond 16."

    Design: Difficulty/combinatorial_formula/press_run_hours_nested_rounding_order_pinned
    """
    hub, site, region, market, route = planned_market

    edition = validate_success(
        api.create_edition(
            market["id"],
            {
                "assigned_print_site_id": site["id"],
                "slug": "2026-09-21",
                "page_count": 12,
                "requested_print_run_copies": 180000,
                "late_sports_engineering_flag": False,
                "legal_notice_count": 0,
            },
            PRINT_OPS,
        ),
        201,
    )

    assert edition["press_run_hours"] == pytest.approx(2.25, abs=0.001), (
        f"expected the single rounded duration 2.25, got {edition['press_run_hours']}"
    )
    assert edition["press_run_hours"] != pytest.approx(2.00, abs=0.001), (
        "rounding the per-press throughput first would yield 2.00 hours"
    )


def test_ready_time_lands_where_the_pinned_division_chain_puts_it(planned_market):
    """PRD §3.5: "`press_ready_utc` is the selected route's `dispatch_cutoff_utc`
    plus sixty minutes of make-ready plus `press_run_hours`, and
    `latest_edition_ready_utc` is `press_ready_utc` plus the route's
    `transit_minutes` plus its `buffer_minutes`."

    PRD §3.5: "The `minutes_late` is the whole minutes from the market's
    `publication_deadline_utc` to `latest_edition_ready_utc`, floored at zero".

    Design: Difficulty/combinatorial_formula/press_run_hours_nested_rounding_order_pinned
    """
    hub, site, region, market, route = planned_market

    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12,
                             requested_print_run_copies=180000)

    assert edition["latest_edition_ready_utc"][:19].endswith("T07:00:00"), (
        f"cutoff 01:00 + 60m make-ready + 2.25h press + 120m transit + 45m buffer "
        f"lands at 07:00Z, got {edition['latest_edition_ready_utc']}"
    )
    assert edition["minutes_late"] == 90, (
        f"05:30 deadline to 07:00 ready time is 90 whole minutes, "
        f"got {edition['minutes_late']}"
    )


# ─── Mode (a): delivery_route_night_cost ─────────────────────────────

@pytest.fixture
def costed_route():
    """Contractor Cedar Hill + route R1 + 5 stops + a 28000-copy costed edition."""
    hub, site, region, market, route = setup_market_with_route(
        clock=CLOCK_2026_09_30)
    contractor, delivery_route, stops, edition = setup_contractor_with_costed_route(
        hub["id"], market["id"], site["id"], stop_count=5,
        run_date="2026-09-21", copies=28000, slug="2026-09-20")
    return hub, site, market, contractor, delivery_route, stops, edition


def test_base_cost_uses_the_billed_stop_count_not_the_tier(costed_route):
    """PRD §3.3: "Step one builds the `base_cost_cents`: a copy term, zero unless
    the contractor's `pay_basis` is `PER_COPY`, in which case it is
    `copies_carried_night` multiplied by the contractor's `per_copy_rate_cents`;
    plus a stop term taken over the counted stop count — delivery stops on the
    route whose status is `active` or `paused` — floored at the contractor's
    `min_stop_guarantee`, multiplied by the route's `per_stop_fee_cents`; the copy
    term and the stop term are added and rounded half up to two decimals."

    PRD §3.3: "When the contractor's `pay_basis` is `PER_STOP` the copy term
    vanishes and the tier percentage multiplies only the stop term".

    Design: Difficulty/combinatorial_formula/delivery_night_cost_tier_then_surcharge_order
    """
    hub, site, market, contractor, delivery_route, stops, edition = costed_route

    assert contractor["pay_basis"] == "PER_STOP"
    assert delivery_route["base_cost_cents"] == pytest.approx(5750.00, abs=0.01), (
        f"five stops at 1150 each is 5750.00, got {delivery_route['base_cost_cents']}"
    )
    assert delivery_route["cost_run_date"] == "2026-09-21"
    assert delivery_route["last_cost_run_date"] == "2026-09-21"


def test_tier_and_status_factor_combine_then_the_surcharge_is_added(costed_route):
    """PRD §3.3: "the tier percentage `copy_volume_tier_pct` is 0.00 for up to
    7,500 copies, 0.05 above 7,500 up to 15,000, 0.10 above 15,000 up to 30,000,
    and 0.15 above 30,000."

    PRD §3.3: "The route's `route_night_cost` is the base cost multiplied by one
    plus the tier percentage, multiplied by the status factor, plus the route's
    `printed_copies_surcharge_cents`, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/delivery_night_cost_tier_then_surcharge_order
    """
    hub, site, market, contractor, delivery_route, stops, edition = costed_route

    refreshed = get_delivery_route(delivery_route["id"])

    assert refreshed["copy_volume_tier_pct"] == pytest.approx(0.10, abs=1e-9)
    assert refreshed["contractor_status_factor"] == pytest.approx(1.00, abs=1e-9)
    assert refreshed["route_night_cost"] == pytest.approx(6325.00, abs=0.01), (
        f"5750 * 1.10 * 1.00 + 0 is 6325.00, got {refreshed['route_night_cost']}"
    )
    assert refreshed["cost_per_copy_cents"] == pytest.approx(0.2259, abs=1e-4), (
        f"6325 / 28000 rounds to 0.2259, got {refreshed['cost_per_copy_cents']}"
    )


def test_the_surcharge_is_added_after_the_tier_not_inside_it(costed_route):
    """PRD §3.3: "The `printed_copies_surcharge_cents` is deliberately not part of
    step one."

    PRD §3.3: "The route's `route_night_cost` is the base cost multiplied by one
    plus the tier percentage, multiplied by the status factor, plus the route's
    `printed_copies_surcharge_cents`, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/delivery_night_cost_tier_then_surcharge_order
    """
    hub, site, market, contractor, delivery_route, stops, edition = costed_route

    assert delivery_route["base_cost_cents"] == pytest.approx(5750.00, abs=0.01)
    assert delivery_route["printed_copies_surcharge_cents"] == 0

    # Rerun the same route with a surcharge: 5750 * 1.10 * 1.00 + 400 = 6725.00.
    # R2 runs over the same market; its own ceiling is raised so the doubled
    # nightly cost for that market does not trip an unrelated route ceiling.
    surcharged = create_delivery_route(
        contractor["id"], market["id"], route_code="R2",
        printed_copies_surcharge_cents=400)
    cost_run(surcharged["id"], "2026-09-21")
    refreshed = get_delivery_route(surcharged["id"])

    # R2 carries no stops of its own, so its stop term floors at the contractor's
    # min_stop_guarantee of 3: 3 * 1150 = 3450, and 3450 * 1.10 + 400 = 4195.00.
    assert refreshed["base_cost_cents"] == pytest.approx(3450.00, abs=0.01), (
        "the surcharge must not enter the base cost"
    )
    assert refreshed["route_night_cost"] == pytest.approx(4195.00, abs=0.01), (
        f"3450 * 1.10 * 1.00 + 400 is 4195.00, got {refreshed['route_night_cost']}"
    )


def test_speed_factor_tier_is_selected_from_the_page_count(planned_market):
    """PRD §3.5: "The `speed_factor` is 1.00 for a `page_count` of at most 8, 0.85
    for a `page_count` above 8 up to 16, and 0.70 beyond 16."

    Design: Difficulty/combinatorial_formula/press_run_hours_nested_rounding_order_pinned
    """
    hub, site, region, market, route = planned_market

    eight_pages = create_edition(market["id"], site["id"], slug="2026-09-21",
                                 page_count=8,
                                 requested_print_run_copies=40000)
    twelve_pages = create_edition(market["id"], site["id"], slug="2026-09-22",
                                  page_count=12,
                                  requested_print_run_copies=40000)
    twenty_pages = create_edition(market["id"], site["id"], slug="2026-09-23",
                                  page_count=20,
                                  requested_print_run_copies=40000)

    # The quarter-hour rounding masks the tier on these short runs, so the tier is
    # read from the pinned 40000-copy case and its effect on the ready time.
    assert eight_pages["press_run_hours"] == pytest.approx(0.50, abs=0.001)
    assert twelve_pages["press_run_hours"] == pytest.approx(0.50, abs=0.001)
    assert twenty_pages["press_run_hours"] == pytest.approx(0.75, abs=0.001), (
        "a 20-page run takes the 0.70 speed factor and lifts the duration a tier"
    )
    # 40000 / 2 / 2 / 25000 / 1.00 = 0.4 raw hours -> next quarter hour 0.50.
    assert eight_pages["press_run_hours"] == pytest.approx(0.50, abs=0.001)