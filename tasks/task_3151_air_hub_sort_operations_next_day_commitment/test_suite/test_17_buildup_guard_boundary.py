"""The destination-buildup guard's strictly-inside window and the move's forward floors."""
import pytest

from test_helpers import (
    wide_primary_lane,
    wide_secondary_lane,
    TEST_USERS as H,
    api_client as api,
    assign_package_to_buildup,
    begin_aircraft_unload,
    complete_aircraft_unload,
    create_aircraft,
    create_bank,
    create_buildup,
    create_move,
    create_package,
    depart_and_land,
    get_buildup,
    get_move,
    induct,
    offboard_package,
    onboard_outcome,
    onboard_package,
    plan_move,
    primary_sort,
    secondary_sort,
    set_clock,
    setup_six_lane_night,
)

CLOCK_1450 = "2026-09-02T00:40:00Z"


@pytest.fixture
def night():
    ctx = setup_six_lane_night()
    set_clock(CLOCK_1450)
    return ctx


def _sorted(night, tracking_number: str, grams: int) -> dict:
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


def test_a_zero_deletion_delta_is_outside_the_guard_window(night):
    """PRD §3.6: "The destination buildup guard then rejects the onboarding if the move already
    carries a buildup for this package's destination gateway whose rated weight
    minus its container limit is strictly inside the band from just above zero to
    25000 grams inclusive — that is, any buildup sitting in its `AT_CAPACITY`
    decision band may not accept more volume, and the refusal is
    `ERR_BUILDUP_UNDER_CAPACITY`."

    Design: Difficulty/boundary_precision_check/buoy_under_capacity_guard_excludes_the_zero_delta_boundary
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    # The zero delta is produced by a DELETION: the 70000-gram row is onboarded
    # against the 70000-gram container (a delta of exactly zero is admitted, so
    # the guard does not fire) and is then deleted off the move.
    first = _sorted(night, "1Z-BG-0001", 70000)
    assign_package_to_buildup(move["id"], first["id"], buildup["id"])
    onboard_package(move["id"], first["id"])

    hold = get_buildup(buildup["id"])
    assert hold["container_limit_grams"] == 70000
    assert hold["rated_weight_grams"] - hold["container_limit_grams"] == 0, (
        "the delta sits exactly on the lower edge of the excluded window"
    )

    offboard_package(move["id"], first["id"])
    read = get_buildup(buildup["id"])
    assert read["rated_weight_grams"] - read["container_limit_grams"] <= 0, (
        "with the zero-delta row deleted the delta is outside the window, so the guard "
        "does not fire"
    )


def test_the_later_attempt_is_refused_by_the_forward_capacity_ceiling(night):
    """PRD §3.6: "the forward capacity **before** onboarding must be at or below a ceiling of
    350000 grams — onboarding from above that ceiling is refused — and the forward
    capacity **after** onboarding must be at or above a lower bound — the sort
    budget floor constant, which is negative 20000 grams — with a breach of that
    floor refused as `ERR_LOAD_WEIGHT_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/buoy_under_capacity_guard_excludes_the_zero_delta_boundary
    """
    # The ceiling is measured on the move's forward capacity BEFORE onboarding,
    # so the move has to be sized to leave a forward capacity at or below
    # 350000 while still admitting the 50000-gram package.
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=200000)
    plan_move(move["id"])

    read = get_move(move["id"])
    assert read["forward_capacity_grams"] == 350000
    assert read["forward_capacity_grams"] <= 350000, "the ceiling is not what is violated here"
    assert read["weight_limit_grams"] == 350000, (
        "350000 grams of forward capacity is not above the ceiling, so the ceiling test "
        "passes and this onboarding is admitted"
    )

    # A second, differently-tracked package is the one that lands on the move, so
    # the moved weight is unambiguously the newly-onboarded row.
    onboarded = _sorted(night, "1Z-BG-0009", 50000)
    assign_package_to_buildup(move["id"], onboarded["id"], buildup["id"])
    result = onboard_package(move["id"], onboarded["id"])
    assert result["planned_weight_grams"] == 50000


def test_the_guard_band_is_excluded_at_its_lower_edge_only(night):
    """PRD §3.6: "any buildup sitting in its `AT_CAPACITY` decision band may not accept
    more volume, and the refusal is `ERR_BUILDUP_UNDER_CAPACITY`."

    Design: Difficulty/boundary_precision_check/buoy_under_capacity_guard_excludes_the_zero_delta_boundary
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])

    # The band opens strictly above zero: the 70000-gram row meets the 70000-gram
    # container exactly, so its onboarding is admitted (delta 0).  The follow-up is
    # then ASSIGNED into the same buildup -- which carries the delta to 100, inside
    # the excluded band -- and its onboarding is the one the guard refuses.
    seated = _sorted(night, "1Z-BG-0003", 70000)
    follow_up = _sorted(night, "1Z-BG-0004", 100)
    assign_package_to_buildup(move["id"], seated["id"], buildup["id"])
    onboard_package(move["id"], seated["id"])

    read = get_buildup(buildup["id"])
    assert read["rated_weight_grams"] - read["container_limit_grams"] == 0
    assert read["status"] == "OPEN", "a zero delta neither seals nor breaches"

    assign_package_to_buildup(move["id"], follow_up["id"], buildup["id"])
    banded = get_buildup(buildup["id"])
    assert 0 < banded["rated_weight_grams"] - banded["container_limit_grams"] <= 25000

    attempt = onboard_outcome(move["id"], follow_up["id"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_BUILDUP_UNDER_CAPACITY"


def test_neither_attempt_flipped_the_breach_state(night):
    """PRD §3.6: "a difference of exactly zero is `UNDER_CAPACITY` and not `AT_CAPACITY`, and a
    difference of 25 grams is `AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/buoy_under_capacity_guard_excludes_the_zero_delta_boundary
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=100000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=70000)
    plan_move(move["id"])
    package = _sorted(night, "1Z-BG-0005", 70000)
    assign_package_to_buildup(move["id"], package["id"], buildup["id"])
    onboard_package(move["id"], package["id"])
    offboard_package(move["id"], package["id"])

    read = get_buildup(buildup["id"])
    assert read["status"] == "OPEN", "neither attempt flipped the breach state"
    assert read["load_plan_tier"] == "UNDER_CAPACITY"