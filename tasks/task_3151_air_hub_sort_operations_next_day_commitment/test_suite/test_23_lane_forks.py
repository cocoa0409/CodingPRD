"""The operator axis and the capacity axis of a sort lane, independent of each other."""
import pytest

from test_helpers import (
    api_client as api,
    TEST_USERS as H,
    confirm,
    create_lane,
    create_package,
    failed_error_id,
    get_lane,
    induct,
    primary_sort,
    reclaim_package,
    set_clock,
    setup_six_lane_night,
)

CLOCK_1414 = "2026-09-01T23:34:00Z"


@pytest.fixture
def night():
    ctx = setup_six_lane_night()
    set_clock(CLOCK_1414)
    return ctx


def _induct_rated(night, tracking_number: str, grams: int) -> dict:
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                         planned_weight_grams=grams, dimension_weight_grams=grams)
    induct(pkg["id"])
    return pkg


def test_the_first_visit_to_available_reads_the_partial_load(night):
    """PRD §3.3: "The lane's `lane_load_grams` is the sum of rated handling weights over every
    package assigned to it whose sort status is `PRIMARY_SORTED` or
    `SECONDARY_SORTED`;"

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    big = _induct_rated(night, "1Z-FK-0001", 40000)
    primary_sort(big["id"], night["lane_p1_id"])

    lane = get_lane(night["lane_p1_id"])
    assert lane["status"] == "AVAILABLE"
    assert lane["lane_load_grams"] == 40000


def test_the_capacity_branch_off_available_saturates_the_lane(night):
    """PRD §3.3: "A lane starts `AVAILABLE` and moves to `SATURATED` automatically once its
    load reaches its capacity, back to `AVAILABLE` when the load falls below
    capacity, and to `CLOSED` or back by explicit supervisor action."

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    big = _induct_rated(night, "1Z-FK-0002", 40000)
    extra = _induct_rated(night, "1Z-FK-0003", 20000)
    primary_sort(big["id"], night["lane_p1_id"])
    primary_sort(extra["id"], night["lane_p1_id"])

    lane = get_lane(night["lane_p1_id"])
    assert lane["status"] == "SATURATED"
    assert lane["lane_load_grams"] == 60000


def test_the_operator_branch_off_the_same_available_state_closes_the_lane(night):
    """PRD §3.3: "and to `CLOSED` or back by explicit supervisor action."

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    lane_id = night["lane_p1_id"]
    assert get_lane(lane_id)["status"] == "AVAILABLE"

    closed = confirm(api.close_lane(lane_id, H["sort_supervisor_headers"]))
    assert closed["status"] == "CLOSED"
    assert get_lane(lane_id)["lane_load_grams"] == 0, "the load is unchanged by closing"


def test_the_second_visit_to_available_reads_the_reclaimed_load(night):
    """PRD §3.3: "a package that is `UNSORTED` after a reclaim, or that has been loaded and
    vacated the lane, contributes nothing."

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    big = _induct_rated(night, "1Z-FK-0004", 40000)
    extra = _induct_rated(night, "1Z-FK-0005", 20000)
    lane_id = night["lane_p1_id"]
    primary_sort(big["id"], lane_id)
    primary_sort(extra["id"], lane_id)
    assert get_lane(lane_id)["status"] == "SATURATED"

    confirm(api.close_lane(lane_id, H["sort_supervisor_headers"]))
    reclaim_package(extra["id"])
    reopened = confirm(api.reopen_lane(lane_id, H["sort_supervisor_headers"]))
    assert reopened["status"] == "AVAILABLE", "the second visit to AVAILABLE"
    assert reopened["lane_load_grams"] == 40000
    assert get_lane(lane_id)["status"] == "AVAILABLE"


def test_the_lane_specific_fork_did_not_leak_across_lanes(night):
    """PRD §3.3: "A lane starts `AVAILABLE` and moves to `SATURATED` automatically once its
    load reaches its capacity, back to `AVAILABLE` when the load falls below
    capacity, and to `CLOSED` or back by explicit supervisor action."
    PRD §3.3: "Sorting happens in two passes over physical lanes, and the lane a package
    occupies is a first-class resource with its own certification, capability and
    capacity."

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    lane_c = create_lane(night["hub_id"], lane_code="P-CL", lane_kind="PRIMARY",
                         commodity_capability="GENERAL", capacity_weight_grams=60000,
                         certified_until_minutes=1700,
                         turnout_start_minutes=1400, turnout_end_minutes=1500)
    closed = confirm(api.close_lane(lane_c["id"], H["sort_supervisor_headers"]))
    assert closed["status"] == "CLOSED"
    assert get_lane(night["lane_p1_id"])["status"] == "AVAILABLE", (
        "the lane-specific fork did not leak across lanes"
    )

    package = _induct_rated(night, "1Z-FK-0006", 20000)
    sorted_package = primary_sort(package["id"], night["lane_p1_id"])
    assert sorted_package["sort_status"] == "PRIMARY_SORTED"


def test_a_reopened_detached_lane_is_still_subject_to_the_capacity_branch(night):
    """PRD §3.3: "back to `AVAILABLE` when the load falls below capacity, and to `CLOSED` or
    back by explicit supervisor action."

    Design: Difficulty/non_linear_state_machine/sort_lane_branching_reopen_saturation_fork_join
    """
    lane_c = create_lane(night["hub_id"], lane_code="P-CL2", lane_kind="PRIMARY",
                         commodity_capability="GENERAL", capacity_weight_grams=60000,
                         certified_until_minutes=1700,
                         turnout_start_minutes=1601, turnout_end_minutes=1700)
    confirm(api.close_lane(lane_c["id"], H["sort_supervisor_headers"]))
    reopened = confirm(api.reopen_lane(lane_c["id"], H["sort_supervisor_headers"]))
    assert reopened["status"] == "AVAILABLE"

    fresh = _induct_rated(night, "1Z-FK-0007", 60000)
    primary_sort(fresh["id"], lane_c["id"])
    saturated = get_lane(lane_c["id"])
    assert saturated["status"] == "SATURATED"
    assert saturated["lane_load_grams"] == 60000