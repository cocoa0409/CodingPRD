"""The pinned evaluation order of a load move's capacity arithmetic."""
import pytest

from test_helpers import (
    wide_primary_lane,
    wide_secondary_lane,
    assert_buildup_invariants,
    assert_load_move_invariants,
    assign_package_to_buildup,
    create_buildup,
    create_move,
    create_package,
    get_buildup,
    get_move,
    induct,
    offboard_package,
    onboard_package,
    plan_move,
    primary_sort,
    secondary_sort,
    set_clock,
    setup_night_with_second_aircraft,
)

CLOCK_1450 = "2026-09-02T00:40:00Z"


@pytest.fixture
def night():
    ctx = setup_night_with_second_aircraft()
    set_clock(CLOCK_1450)
    return ctx


def _sorted_package(night, tracking_number: str, grams: int,
                    move_id: str = None) -> dict:
    if "lane_wide_s_id" not in night:
        night["lane_wide_s_id"] = wide_secondary_lane(night)["id"]
    if "lane_wide_p_id" not in night:
        night["lane_wide_p_id"] = wide_primary_lane(night)["id"]
    wide = night["lane_wide_s_id"]
    wide_p = night["lane_wide_p_id"]
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                         planned_weight_grams=grams, dimension_weight_grams=grams)
    induct(pkg["id"])
    primary_sort(pkg["id"], wide_p)
    secondary_sort(pkg["id"], wide)
    return pkg


def test_mid_load_capacity_and_tier_track_the_row_set(night):
    """PRD §3.6: "Second compute the **raw forward capacity**: the move's
    `weight_limit_grams` minus that filled weight."
    PRD §3.6: "raw capacity strictly above zero reads `UNDER_CAPACITY`, exactly zero reads
    `AT_CAPACITY`, and below zero reads `RESERVE_TIER`."

    Design: Difficulty/combinatorial_formula/forward_capacity_tier_derives_from_raw_value_and_override_is_discarded
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    first = _sorted_package(night, "1Z-FC-0001", 50000)
    second = _sorted_package(night, "1Z-FC-0002", 55000)
    for pkg in (first, second):
        assign_package_to_buildup(move["id"], pkg["id"], buildup["id"])
        onboard_package(move["id"], pkg["id"])

    read = get_move(move["id"])
    assert read["forward_capacity_grams"] == 0
    assert read["load_plan_tier"] == "RESERVE_TIER"
    assert_load_move_invariants(read)


def test_an_overbooked_move_reads_a_floored_capacity_and_a_raw_tier(night):
    """PRD §3.6: "a move whose raw forward capacity is negative five thousand grams
    reads a displayed forward capacity of zero and a tier of `RESERVE_TIER` on the very
    same read."

    Design: Difficulty/combinatorial_formula/forward_capacity_tier_derives_from_raw_value_and_override_is_discarded
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    first = _sorted_package(night, "1Z-FC-0002", 50000)
    second = _sorted_package(night, "1Z-FC-0003", 55000)
    for pkg in (first, second):
        assign_package_to_buildup(move["id"], pkg["id"], buildup["id"])
        onboard_package(move["id"], pkg["id"])

    read = get_move(move["id"])
    assert read["forward_capacity_grams"] == 0, "the raw -5000 is floored to zero for display"
    assert read["load_plan_tier"] == "RESERVE_TIER", (
        "the label comes from the RAW value, not from the floored one"
    )
    assert_load_move_invariants(read)


def test_the_buildup_band_flips_to_the_breach_state(night):
    """PRD §3.6: "The breach state is entered automatically whenever the difference
    exceeds 25000 grams, its tier is recomputed to `RESERVE_TIER`, and it returns to
    `OPEN` automatically when unloading brings the rated weight back to within the
    tolerance."

    Design: Difficulty/combinatorial_formula/forward_capacity_tier_derives_from_raw_value_and_override_is_discarded
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    first = _sorted_package(night, "1Z-FC-0004", 50000)
    second = _sorted_package(night, "1Z-FC-0005", 55000)
    for pkg in (first, second):
        assign_package_to_buildup(move["id"], pkg["id"], buildup["id"])
        onboard_package(move["id"], pkg["id"])

    read = get_buildup(buildup["id"])
    assert read["rated_weight_grams"] == 105000
    assert read["status"] == "WEIGHT_BREACH", "105000 - 70000 == 35000 exceeds the tolerance"
    assert read["load_plan_tier"] == "RESERVE_TIER"
    assert_buildup_invariants(read)


def test_a_manual_tier_override_is_discarded_by_the_next_package_event(night):
    """PRD §3.15: "the override stands until the next package event on that object, at
    which point the ordinary derivation of §3.6 recomputes the tier and the manual value
    is gone."

    Design: Difficulty/combinatorial_formula/forward_capacity_tier_derives_from_raw_value_and_override_is_discarded
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    first = _sorted_package(night, "1Z-FC-0006", 50000)
    second = _sorted_package(night, "1Z-FC-0007", 55000)
    for pkg in (first, second):
        assign_package_to_buildup(move["id"], pkg["id"], buildup["id"])
        onboard_package(move["id"], pkg["id"])

    from test_helpers import api_client as api
    from test_helpers import TEST_USERS as H
    overridden = api.set_move_tier(move["id"], {"load_plan_tier": "AT_CAPACITY"},
                                   H["load_planner_headers"])
    assert overridden.status_code == 200
    assert overridden.json()["data"]["load_plan_tier"] == "AT_CAPACITY"

    offboard_package(move["id"], first["id"])
    read = get_move(move["id"])
    assert read["load_plan_tier"] == "UNDER_CAPACITY", (
        "the recompute discards the manual override"
    )
    assert read["forward_capacity_grams"] == 45000, (
        "the offboarded package leaves the move, so only the 55000-gram row remains"
    )
    assert read["load_plan_tier"] != "AT_CAPACITY"