"""Lane occupancy, the capacity boundary, and the concourse width geometry."""
import pytest

from test_helpers import (
    assign_package_to_buildup,
    create_buildup,
    create_move,
    create_package,
    get_concourse_width,
    get_lane,
    get_package,
    induct,
    onboard_package,
    plan_move,
    primary_sort,
    reclaim_package,
    secondary_sort,
    setup_six_lane_night,
)


@pytest.fixture
def night():
    return setup_six_lane_night()


def _induct_rated(night, tracking_number: str, grams: int) -> dict:
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                         planned_weight_grams=grams, dimension_weight_grams=grams)
    induct(pkg["id"])
    return pkg


def test_exact_capacity_saturates_the_lane(night):
    """PRD §3.3: "A lane starts `AVAILABLE` and moves to `SATURATED` automatically once its
    load reaches its capacity, back to `AVAILABLE` when the load falls below
    capacity, and to `CLOSED` or back by explicit supervisor action."

    Design: Difficulty/combinatorial_formula/sort_lane_load_three_input_branch_at_exact_capacity
    """
    packages = [_induct_rated(night, f"1Z-LL-{n}", 20000) for n in ("0001", "0002", "0003")]
    for pkg in packages:
        primary_sort(pkg["id"], night["lane_p1_id"])

    lane = get_lane(night["lane_p1_id"])
    assert lane["lane_load_grams"] == 60000
    assert lane["status"] == "SATURATED", (
        "60000 against capacity 60000 saturates, so the boundary is inclusive"
    )


def test_reclaiming_vacates_the_lane_and_clears_saturation(night):
    """PRD §3.3: "a package that is `UNSORTED` after a reclaim, or that has been loaded
    and vacated the lane, contributes nothing."

    Design: Difficulty/combinatorial_formula/sort_lane_load_three_input_branch_at_exact_capacity
    """
    packages = [_induct_rated(night, f"1Z-LL-{n}", 20000) for n in ("0004", "0005", "0006")]
    for pkg in packages:
        primary_sort(pkg["id"], night["lane_p1_id"])
    assert get_lane(night["lane_p1_id"])["status"] == "SATURATED"

    reclaim_package(packages[2]["id"])
    lane = get_lane(night["lane_p1_id"])
    assert lane["lane_load_grams"] == 40000
    assert lane["status"] == "AVAILABLE", "the lane falls back below capacity"


def test_loading_a_package_drops_it_out_of_the_lane_sum(night):
    """PRD §3.3: "The lane's `lane_load_grams` is the sum of rated handling weights over every
    package assigned to it whose sort status is `PRIMARY_SORTED` or
    `SECONDARY_SORTED`;"
    PRD §3.3: "a package that is `UNSORTED` after a reclaim, or that has been loaded and
    vacated the lane, contributes nothing."

    Design: Difficulty/combinatorial_formula/sort_lane_load_three_input_branch_at_exact_capacity
    """
    package = _induct_rated(night, "1Z-LL-0007", 40000)
    primary_sort(package["id"], night["lane_p1_id"])
    secondary_sort(package["id"], night["lane_s1_id"])
    assert get_lane(night["lane_s1_id"])["lane_load_grams"] == 40000

    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=200000)
    plan_move(move["id"])
    assign_package_to_buildup(move["id"], package["id"], buildup["id"])
    onboard_package(move["id"], package["id"])

    assert get_lane(night["lane_s1_id"])["lane_load_grams"] == 0, (
        "a package that has been loaded vacates its lane"
    )
    read = get_package(package["id"])
    assert read["sort_status"] == "LOADED"
    assert read["assigned_lane_id"] is None


def test_point_touching_turnouts_merge_but_a_one_minute_gap_does_not(night):
    """PRD §3.13: "two same-kind lanes whose intervals touch exactly at a point — the second
    beginning exactly where the first ends — merge and credit four units per
    merged minute, while two lanes that miss by exactly one minute do not merge at
    all and contribute zero, so one minute of gap disables an entire merge."

    Design: Difficulty/combinatorial_formula/sort_lane_load_three_input_branch_at_exact_capacity
    """
    read = get_concourse_width({"hub_id": night["hub_id"], "lane_kind": "PRIMARY"})
    assert read["merged_minutes"] == 100, (
        "P-01 closes at 1500 exactly where P-02 opens, so the pair merges over 100 minutes; "
        "P-03 opens at 1601, one minute after P-02 closes, so it does not merge"
    )
    assert read["concourse_width_rating"] == 400, "100 merged minutes times the merge credit of four"


def test_the_concourse_read_ignores_a_second_lane_kind(night):
    """PRD §3.13: "Take every non-closed lane on the hub whose kind matches the kind being asked
    about, and sort their turnout intervals — each a start minute and an end
    minute — by start minute and then by end minute."

    Design: Difficulty/combinatorial_formula/sort_lane_load_three_input_branch_at_exact_capacity
    """
    primary = get_concourse_width({"hub_id": night["hub_id"], "lane_kind": "PRIMARY"})
    secondary = get_concourse_width({"hub_id": night["hub_id"], "lane_kind": "SECONDARY"})
    assert primary["merged_minutes"] == 100, "only the three PRIMARY lanes of that kind participate"
    assert secondary["concourse_width_rating"] == 0