"""Corner queue B — section: calculations.

The newsroom allocation waterfall, the severance tiers and the late-edition penalty
scale.
"""
import pytest

from test_helpers import (
    api,
    create_hub_with_clock,
    create_region,
    create_market,
    create_position,
    create_newsroom_change,
    approve_newsroom_change,
    apply_newsroom_change,
    get_newsroom_change,
    hub_version,
    set_clock,
    create_hub,
    create_site,
    create_route,
    create_edition,
    plan_transfer,
    validate_success,
    TEST_USERS,
    NEWSROOM_MANAGER,
    NEWSROOM_MANAGER_ALT,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]


def test_hub_newsroom_allocation_waterfall_leaves_documented_unassigned():
    """PRD §3.8: "Each region's `guaranteed_headcount` is the smaller of its
    `region_need_score` floored to a whole number of heads and its
    `daily_headcount_floor`, so the floor is the binding value whenever the need
    score would allow more."
    PRD §3.8: "Whatever the waterfall cannot place is the hub's
    `unassigned_headcount`, the difference between the hub's `total_newsroom_headcount`
    and the sum of `allocated_newsroom_headcount` over its regions".

    Design: Corner/calculations/hub_newsroom_allocation_waterfall_leaves_documented_unassigned
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    north = create_region(hub["id"])
    south = create_region(hub["id"], name="South", daily_headcount_floor=3,
                          daily_headcount_cap=8, allocation_priority=2)
    create_market(north["id"], name="Riverton", weighted_demand_units=7000)
    create_market(south["id"], name="Fallow", weighted_demand_units=12000)

    regions = validate_success(api.list_regions(hub["id"], PRINT_OPS), 200)
    refreshed = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)

    by_name = {r["name"]: r for r in regions}
    assert by_name["North"]["region_need_score"] == 7.00, (
        f"7000 demand units over one thousand is 7.00, got "
        f"{by_name['North']['region_need_score']}"
    )
    assert by_name["South"]["region_need_score"] == 12.00
    assert by_name["North"]["guaranteed_headcount"] == 4
    assert by_name["South"]["guaranteed_headcount"] == 3
    assert by_name["North"]["allocated_newsroom_headcount"] == 10, (
        "North's cap binds at 10"
    )
    assert by_name["South"]["allocated_newsroom_headcount"] == 8, (
        "South's cap binds at 8"
    )
    assert refreshed["unassigned_headcount"] == 12, (
        f"10 + 8 + 12 must balance to 30, got {refreshed['unassigned_headcount']}"
    )


def test_severance_cost_uses_the_mitigation_factor_only_at_scale():
    """PRD §3.8: "When three or four or more heads are severed, the same
    multiplication applies but a mitigation factor of 0.25 is inserted — the severed
    count, times 2.15, times 0.25, times `monthly_cost_cents`, times 1.65 — and the
    result is rounded half up to two decimals."
    PRD §3.8: "When one or two heads are severed, the cost is the severed count
    multiplied by 2.15 months of severance, multiplied by a salary-load multiplier
    of 1.65, multiplied by the position's `monthly_cost_cents`, rounded half up to
    two decimals, and no mitigation factor applies."

    Design: Corner/calculations/severance_cost_uses_the_mitigation_factor_only_at_scale
    """
    set_clock(CLOCK_2026_09_01)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"], monthly_cost_cents=520000)

    big = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-11", layoff_order_index=1, requested_slots=40)
    small = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-13", layoff_order_index=2, requested_slots=2)

    # The two-head movement is rejected while still proposed, and the big change is
    # approved before the clock moves past its effective date.
    validate_success(api.reject_newsroom_change(small["id"], NEWSROOM_MANAGER), 200)
    rejected = get_newsroom_change(small["id"])
    assert rejected["status"] == "rejected"
    approve_newsroom_change(big["id"], headers=NEWSROOM_MANAGER_ALT)
    set_clock("2026-09-12T00:00:00Z")
    applied = apply_newsroom_change(big["id"])

    assert applied["status"] == "applied"
    # §3.8: the waterfall serves the earlier-created sibling first, so the heads it
    # can place are its own -- the rejected two-slot movement no longer ranks.
    assert applied["allocated_slots"] == 20, (
        f"got {applied['allocated_slots']}"
    )
    assert applied["severance_cost_cents"] == pytest.approx(9223500.00, abs=0.01), (
        f"15 severed heads at scale cost 15 * 2.15 * 0.25 * 520000 * 1.65, got "
        f"{applied['severance_cost_cents']}"
    )


def test_the_two_severance_branches_are_distinguished_by_the_mitigation():
    """PRD §3.8: "The severed headcount is `requested_slots` minus
    `allocated_slots`, so a movement whose slots are all placed carries no severance
    at all."
    PRD §3.8: "The mitigation applies from the four-head boundary upward."

    Design: Corner/calculations/severance_cost_uses_the_mitigation_factor_only_at_scale
    """
    set_clock(CLOCK_2026_09_01)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"], monthly_cost_cents=520000)

    big = create_newsroom_change(
        position["id"], region["id"], region["id"], hub_version(hub["id"]),
        effective_date="2026-09-11", layoff_order_index=1, requested_slots=40)
    approve_newsroom_change(big["id"], headers=NEWSROOM_MANAGER_ALT)
    set_clock("2026-09-12T00:00:00Z")
    applied = apply_newsroom_change(big["id"])

    severed = applied["requested_slots"] - applied["allocated_slots"]
    assert severed == 20
    expected_at_scale = round(severed * 2.15 * 0.25 * 520000 * 1.65, 2)
    assert applied["severance_cost_cents"] == pytest.approx(expected_at_scale, abs=0.01)

    # The same count without mitigation would be strictly larger.
    without_mitigation = round(severed * 2.15 * 1.65 * 520000, 2)
    assert applied["severance_cost_cents"] < without_mitigation, (
        "the 0.25 mitigation factor must be applied at scale"
    )


def test_late_edition_penalty_is_zero_at_the_boundary_and_scales_above_it():
    """PRD §3.5: "A penalty of exactly zero is booked when `minutes_late` is zero."
    PRD §3.5: "Otherwise the multiplier is 3 when the edition has an open correction,
    2 when it carries the `late_sports_engineering_flag`, and 1 otherwise — in that
    precedence".
    PRD §3.5: "The penalty is `minutes_late` multiplied by 45 cents per minute,
    multiplied by that multiplier, truncated toward zero."

    Design: Corner/calculations/late_edition_penalty_is_zero_at_the_boundary_and_scales_above_it
    """
    hub = create_hub_with_clock(CLOCK_2026_09_01)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=8000,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    validate_success(
        api.plan_market_transfer(
            market["id"],
            {"receiving_print_site_id": site["id"], "expected_hub_version": version},
            PRINT_OPS),
        200,
    )

    on_time = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12, requested_print_run_copies=40000)
    assert on_time["minutes_late"] == 0, (
        f"a 40000-copy 12-page run on this route still clears 05:30, got "
        f"{on_time['minutes_late']}"
    )
    assert on_time["late_edition_penalty_cents"] == 0, (
        "a zero-minutes-late edition books exactly zero"
    )

    late = create_edition(market["id"], site["id"], slug="2026-09-22",
                          page_count=12, requested_print_run_copies=180000,
                          late_sports_engineering_flag=True)
    assert late["minutes_late"] == 90
    assert late["late_edition_penalty_cents"] == 90 * 45 * 2, (
        f"the late-sports flag doubles the per-minute rate, got "
        f"{late['late_edition_penalty_cents']}"
    )

    # An edition carrying both the flag and an open correction takes multiplier 3.
    corrected = create_edition(market["id"], site["id"], slug="2026-09-23",
                               page_count=12, requested_print_run_copies=180000,
                               late_sports_engineering_flag=True,
                               legal_notice_count=1)
    validate_success(api.dispatch_edition(corrected["id"], PRINT_OPS), 200)
    validate_success(api.deliver_edition(corrected["id"], PRINT_OPS), 200)
    validate_success(api.correct_edition(corrected["id"], PRINT_OPS), 200)
    reopened = create_edition(market["id"], site["id"], slug="2026-09-24",
                              page_count=12, requested_print_run_copies=180000,
                              late_sports_engineering_flag=True)
    validate_success(api.dispatch_edition(reopened["id"], PRINT_OPS), 200)
    assert reopened["minutes_late"] == 90, (
        f"got {reopened['minutes_late']}"
    )