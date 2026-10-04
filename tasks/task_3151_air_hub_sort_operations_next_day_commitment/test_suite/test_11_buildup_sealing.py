"""Sealing a buildup: an exact meeting at the container limit is admitted, an overshoot
inside the breach band is not."""
import pytest

from test_helpers import (
    get_move,
    wide_primary_lane,
    wide_secondary_lane,
    TEST_USERS as H,
    api_client as api,
    assign_package_to_buildup,
    confirm,
    create_buildup,
    create_move,
    create_package,
    get_buildup,
    induct,
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


def test_an_exact_meeting_at_the_container_limit_seals(night):
    """PRD §3.6: "sealing requires that its rated weight is at or below its container limit,
    and separately requires that its rated weight does not exceed that limit by
    more than nothing and by at most 25000 grams — the same exclusion of the
    tolerance band — and, when the owning move's declared `requires_container` map
    says true for this buildup's destination gateway, requires it be filled to at
    least its container limit minus a fill tolerance of 5000 grams."
    PRD §3.6: "A buildup may also be sealed or unsealed directly: sealing requires that its
    rated weight is at or below its container limit, and separately requires that
    its rated weight does not exceed that limit by more than nothing and by at
    most 25000 grams — the same exclusion of the tolerance band — and, when the
    owning move's declared `requires_container` map says true for this buildup's
    destination gateway, requires it be filled to at least its container limit
    minus a fill tolerance of 5000 grams."

    Design: Difficulty/resource_temporal_overlap/buildup_occupancy_interval_admits_an_exact_meeting_at_the_limit
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=100000,
                             requires_container=True)
    plan_move(move["id"])

    package = _sorted(night, "1Z-BS-0001", 100000)
    assign_package_to_buildup(move["id"], package["id"], buildup["id"])
    onboard_package(move["id"], package["id"])

    read = get_buildup(buildup["id"])
    assert read["rated_weight_grams"] == 100000
    assert read["container_limit_grams"] == 100000

    sealed = confirm(api.seal_buildup(buildup["id"],
                                      {"expected_buildup_version": read["version"]},
                                      H["load_planner_headers"]))
    assert sealed["status"] == "SEALED", (
        "the zero-tolerance meeting is admitted: 100000 >= 100000 - 5000 satisfies the fill gate"
    )


def test_the_same_buildup_refuses_an_overshoot_inside_the_band(night):
    """PRD §3.6: "sealing requires that its rated weight is at or below its container limit,
    and separately requires that its rated weight does not exceed that limit by
    more than nothing and by at most 25000 grams — the same exclusion of the
    tolerance band — and, when the owning move's declared `requires_container` map
    says true for this buildup's destination gateway, requires it be filled to at
    least its container limit minus a fill tolerance of 5000 grams."

    Design: Difficulty/resource_temporal_overlap/buildup_occupancy_interval_admits_an_exact_meeting_at_the_limit
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=100000,
                             requires_container=True)
    plan_move(move["id"])

    big = _sorted(night, "1Z-BS-0002", 100000)
    overshoot = _sorted(night, "1Z-BS-0003", 100100)
    # The delta must jump straight past the band: 100000 against the 100000
    # container sits exactly at zero (legal), so the one package that carries the
    # buildup into WEIGHT_BREACH is the 100100-gram row on top of it.
    assign_package_to_buildup(move["id"], big["id"], buildup["id"])
    onboard_package(move["id"], big["id"])
    assign_package_to_buildup(move["id"], overshoot["id"], buildup["id"])
    onboard_package(move["id"], overshoot["id"])

    read = get_buildup(buildup["id"])
    assert read["status"] == "WEIGHT_BREACH", (
        "200100 - 100000 == 100100, which exceeds the 25000-gram band"
    )

    attempt = api.seal_buildup(buildup["id"],
                               {"expected_buildup_version": read["version"]},
                               H["load_planner_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_BUILDUP_UNDER_CAPACITY"


def test_the_fill_tolerance_is_satisfied_by_the_exact_load(night):
    """PRD §3.6: "when the owning move's declared `requires_container` map says true for
    this buildup's destination gateway, requires it be filled to at least its container
    limit minus a fill tolerance of 5000 grams."

    Design: Difficulty/resource_temporal_overlap/buildup_occupancy_interval_admits_an_exact_meeting_at_the_limit
    """
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=100000,
                             requires_container=False)
    plan_move(move["id"])
    package = _sorted(night, "1Z-BS-0004", 100000)
    assign_package_to_buildup(move["id"], package["id"], buildup["id"])
    onboard_package(move["id"], package["id"])

    read = get_buildup(buildup["id"])
    assert read["requires_container"] is False
    sealed = confirm(api.seal_buildup(buildup["id"],
                                      {"expected_buildup_version": read["version"]},
                                      H["load_planner_headers"]))
    assert sealed["status"] == "SEALED"

    # Declaring the gateway requirement now excludes a partially filled container.
    # The package's destination is read as a gateway code, so the declaration
    # names that code (a hub destination is not a gateway).
    import test_helpers.constants as C
    gateway = getattr(C, "TRACKED_GATEWAY", "LAX")
    confirm(api.set_gateway_requirements(
        move["id"], {"destination_gateway_code": gateway, "requires_container": True},
        H["load_planner_headers"]))
    confirm(api.unseal_buildup(buildup["id"], H["load_planner_headers"]))

    # Offboarding takes the package back off the move, so the move's planned
    # weight -- the subject of the requires_container gate -- reads zero again.
    from test_helpers import offboard_package
    offboard_package(move["id"], package["id"])
    light = get_buildup(buildup["id"])
    light_m = get_move(move["id"])
    assert light_m["planned_weight_grams"] == 0
    refusal = api.seal_buildup(buildup["id"],
                               {"expected_buildup_version": light["version"]},
                               H["load_planner_headers"])
    assert refusal.status_code == 409, refusal.text