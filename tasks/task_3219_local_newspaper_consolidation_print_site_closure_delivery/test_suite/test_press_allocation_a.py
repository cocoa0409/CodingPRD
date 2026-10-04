"""Difficulty queue A — rule dual_variant_calc, press-allocation variant.

The PRIORITY site serves a requesting market its whole request up to what
remains; the PROPORTIONAL site scales the same request by the shared
remaining-capacity ratio, so one request lands on two different allocated runs.
"""
import pytest

from test_helpers import (
    api,
    create_site,
    create_region,
    create_market,
    create_hub,
    get_print_site,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]

# A PRIORITY twin of CED: same 400000 installed capacity, same press line.
SITE_KOT_PRIORITY = {
    "code": "KOT",
    "press_units": 2,
    "shifts_per_night": 2,
    "copies_per_hour_per_press": 25000,
    "max_concurrent_departures": 2,
    "allocation_method": "PRIORITY",
    "distinct_shifts_per_night": 4,
    "loading_slot_minutes": 30,
}

# The PROPORTIONAL twin: 1 press * 2 shifts * 8h * 25000 cph = 400000 copies.
SITE_CED_PROPORTIONAL = {
    "code": "CED",
    "press_units": 1,
    "shifts_per_night": 2,
    "copies_per_hour_per_press": 25000,
    "max_concurrent_departures": 2,
    "allocation_method": "PROPORTIONAL",
    "distinct_shifts_per_night": 2,
    "loading_slot_minutes": 30,
}

# KOT installs 800000 copies and CED 400000, so the same request lands on two
# different allocated runs, which is the point of the dual-variant instance.
SITE_CAPACITY = 800000
CED_CAPACITY = 400000
# §3.5's PROPORTIONAL reading divides by the summed requested runs of the SITE's
# editions, so a site's edition count changes the scaled result. The third case
# therefore uses its own twins: a first run of 360000 leaves 440000 free and the
# two CED editions then sum to 400000 requested.
# Two independent twins of the 800000-copy site, one per reading of §3.5's
# PROPORTIONAL denominator (a site's own editions vs the two twins' editions).
PA_FIRST = 250000
PA_SECOND = 100000
PA_EXPECTED = 44444          # 100000 * 200000 // 450000, floored
TWO_SITE_FIRST = 360000
TWO_SITE_SECOND = 40000
TWO_SITE_EXPECTED = 44000    # 40000 * 440000 // 400000, floored


def _edition(site_id, market_id, slug, copies):
    return validate_success(
        api.create_edition(
            market_id,
            {
                "assigned_print_site_id": site_id,
                "slug": slug,
                "page_count": 12,
                "requested_print_run_copies": copies,
                "late_sports_engineering_flag": False,
                "legal_notice_count": 0,
            },
            PRINT_OPS,
        ),
        201,
    )


@pytest.fixture
def two_site_scenario():
    """Hub + PRIORITY site KOT + PROPORTIONAL site CED, both at 800000 capacity.

    Regions North and South each carry one market with no guaranteed floor, so
    nothing but the allocation method decides the second edition's run size.
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    kot = create_site(hub["id"], **SITE_KOT_PRIORITY)
    ced = create_site(hub["id"], **SITE_CED_PROPORTIONAL)
    north = create_region(hub["id"])
    south = create_region(hub["id"], name="South", daily_headcount_floor=3,
                          daily_headcount_cap=8, allocation_priority=2)
    riverton = create_market(north["id"], publication_deadline_utc="05:30",
                             on_time_margin_minutes=30, guaranteed_floor_copies=0,
                             single_copy_market_rule="carrier")
    fallow = create_market(south["id"], name="Fallow", weighted_demand_units=12000,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=0,
                           single_copy_market_rule="carrier")
    return hub, kot, ced, riverton, fallow


def test_priority_site_gives_the_market_its_whole_requested_run(two_site_scenario):
    """PRD §3.5: "Under the `PRIORITY` method the contested pool is the site's
    `capacity_remaining_copies` and the competing editions are the site's other
    editions ordered by `slug` ascending and then by `print_market_id` ascending;
    each market is served its whole request up to what remains, so an early market
    can consume the pool before a later one is reached."

    PRD §3.1: "From these the system derives `capacity_copies` as the number of
    presses multiplied by the number of shifts per night, multiplied by eight
    hours, multiplied by the per-press hourly throughput".

    Design: Difficulty/dual_variant_calc/press_allocation_priority_vs_proportional
    """
    hub, kot, ced, riverton, fallow = two_site_scenario

    first = _edition(kot["id"], riverton["id"], "2026-09-21", TWO_SITE_FIRST)
    assert first["allocated_print_run_copies"] == TWO_SITE_FIRST

    site_kot = get_print_site(kot["id"])
    assert site_kot["allocation_method"] == "PRIORITY"
    assert site_kot["capacity_copies"] == SITE_CAPACITY
    assert site_kot["capacity_remaining_copies"] == SITE_CAPACITY - TWO_SITE_FIRST

    second = _edition(kot["id"], fallow["id"], "2026-09-21", TWO_SITE_SECOND)

    assert second["allocated_print_run_copies"] == TWO_SITE_SECOND, (
        f"PRIORITY must serve the whole request up to what remains, got "
        f"{second['allocated_print_run_copies']}"
    )


def test_proportional_site_scales_the_run_by_the_shared_ratio(two_site_scenario):
    """PRD §3.5: "Under the `PROPORTIONAL` method the same floor is applied, but
    the run is first scaled: the `allocated_print_run_copies` is the requested run
    multiplied by the site's remaining capacity and divided by the summed requested
    runs of the site's editions, floored to a whole number of copies".

    Design: Difficulty/dual_variant_calc/press_allocation_priority_vs_proportional
    """
    hub, kot, ced, riverton, fallow = two_site_scenario

    first = _edition(ced["id"], riverton["id"], "2026-09-21", PA_FIRST)
    site_ced = get_print_site(ced["id"])
    assert site_ced["allocation_method"] == "PROPORTIONAL"
    assert site_ced["capacity_copies"] == CED_CAPACITY
    assert site_ced["capacity_remaining_copies"] == (
        CED_CAPACITY - first["allocated_print_run_copies"]
    )

    second = _edition(ced["id"], fallow["id"], "2026-09-21", PA_SECOND)

    # §3.5 scales the run by the site's remaining capacity over the summed requested
    # runs of its editions, so the result is strictly below the request (the exact
    # scaled figure for this pair is pinned by the dual-variant test below).
    assert 0 < second["allocated_print_run_copies"] < PA_SECOND, (
        f"PROPORTIONAL must scale the shared ratio, got "
        f"{second['allocated_print_run_copies']}"
    )
    assert get_print_site(ced["id"])["capacity_remaining_copies"] == (
        CED_CAPACITY - first["allocated_print_run_copies"]
        - second["allocated_print_run_copies"]
    )


def test_the_two_allocation_methods_disagree_on_the_identical_request(two_site_scenario):
    """PRD §3.1: "Its `allocation_method` is either `PRIORITY` or `PROPORTIONAL`,
    and that single choice governs how every edition printed at the site is sized."

    PRD §3.5: "In either method the market's `guaranteed_floor_copies` is applied
    first: the run actually requested becomes the larger of
    `requested_print_run_copies` and `guaranteed_floor_copies`, and the
    `allocated_print_run_copies` is the smaller of that and the site's remaining
    capacity."

    Design: Difficulty/dual_variant_calc/press_allocation_priority_vs_proportional
    """
    hub, kot, ced, riverton, fallow = two_site_scenario

    # A slug is unique within its market, so each twin's first edition takes its own
    # slug; otherwise the two sites would be measured on different markets.
    _edition(kot["id"], riverton["id"], "2026-09-21", PA_FIRST)
    _edition(ced["id"], riverton["id"], "2026-09-22", PA_FIRST)

    priority_edition = _edition(kot["id"], fallow["id"], "2026-09-21", PA_SECOND)
    proportional_edition = _edition(ced["id"], fallow["id"], "2026-09-22", PA_SECOND)

    assert priority_edition["allocated_print_run_copies"] == PA_SECOND
    # 100000 * 200000 // 450000 floored is 44444, not the whole request.
    assert proportional_edition["allocated_print_run_copies"] == PA_EXPECTED, (
        f"PROPORTIONAL must scale the run, got "
        f"{proportional_edition['allocated_print_run_copies']}"
    )
    assert proportional_edition["allocated_print_run_copies"] != PA_SECOND
    assert (
        priority_edition["allocated_print_run_copies"]
        != proportional_edition["allocated_print_run_copies"]
    ), "the same request must land on two different allocated runs"
    assert get_print_site(kot["id"])["allocation_method"] == "PRIORITY"
    assert get_print_site(ced["id"])["allocation_method"] == "PROPORTIONAL"