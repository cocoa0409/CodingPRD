"""The derived thresholds: commitment cutoffs, labor posture, floored window thresholds,
the money-back tier composition and the composure of a package's reversal."""
import pytest

from test_helpers import (
    TEST_USERS as H,
    api_client as api,
    confirm,
    create_bank,
    create_lane,
    create_aircraft,
    create_extension_shift,
    create_hub,
    create_package,
    create_shift,
    depart_and_land,
    get_hub,
    get_shift,
    induct,
    primary_sort,
    secondary_sort,
    set_clock,
    setup_six_lane_night,
    setup_bare_hub,
)

CLOCK_1500 = "2026-09-02T01:00:00Z"
CLOCK_1450 = "2026-09-02T00:40:00Z"


def test_each_service_level_gets_its_own_cutoff_slip():
    """PRD §3.1: "`NEXT_DAY_AIR` is cut off exactly at the hub's `sort_window_close_minutes`,
    `SECOND_DAY_AIR` one full day later at that close plus 1440, and `GROUND` two days later
    at that close plus 2880."

    Design: Corner/calculations/commitment_cutoff_maps_each_service_level_to_its_own_slip
    """
    night = setup_six_lane_night()
    next_day = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CC-0001",
                              planned_weight_grams=20000, dimension_weight_grams=20000)
    second_day = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CC-0002",
                                service_level="SECOND_DAY_AIR", planned_weight_grams=20000,
                                dimension_weight_grams=20000)
    ground = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CC-0003",
                            service_level="GROUND", planned_weight_grams=20000,
                            dimension_weight_grams=20000)

    assert next_day["commitment_cutoff_minutes"] == 1560, "hub close plus zero"
    assert second_day["commitment_cutoff_minutes"] == 3000, "hub close plus 1440"
    assert ground["commitment_cutoff_minutes"] == 4440, "hub close plus 2880"


def test_the_posture_triggers_at_the_overrun_constant_and_red_dominates():
    """PRD §3.7: "Because the capacity rule is checked before the variance rules, a shift that
    is both over capacity and over variance reads `RED` and never `SATURATED` — a
    distinction that matters downstream, because the ground-feeder staging gate
    and the induction gate both test specifically for `SATURATED` and do not block
    on `RED`."

    Design: Corner/calculations/labor_posture_triggers_at_the_overrun_constant_and_red_dominates
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1500)
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LP-0001",
                   planned_weight_grams=436900, dimension_weight_grams=436900)

    shift = get_shift(night["shift_id"])
    assert shift["volume_variance_pct"] == pytest.approx(0.1497, abs=0.0001)
    assert shift["staffing_posture"] == "AMBER", (
        "a shortfall is not the same posture as a match, and 0.1497 is below the overrun band"
    )

    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LP-0002",
                   planned_weight_grams=100, dimension_weight_grams=100)
    shift = get_shift(night["shift_id"])
    assert shift["volume_variance_pct"] == pytest.approx(0.1500, abs=0.0001)
    assert shift["staffing_posture"] == "SATURATED", "the overrun constant is inclusive"

    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LP-0003",
                   planned_weight_grams=67100, dimension_weight_grams=67100)
    shift = get_shift(night["shift_id"])
    assert shift["volume_variance_pct"] == pytest.approx(0.3266, abs=0.0001)
    assert shift["staffing_posture"] == "RED", (
        "the capacity rule (live above 504000) is evaluated first"
    )


def test_a_green_shift_stays_green_while_the_variance_is_inside_ten_percent():
    """PRD §3.7: "Otherwise, if the absolute value of the variance is strictly less than
    0.10, the posture is `GREEN`."

    Design: Corner/calculations/labor_posture_triggers_at_the_overrun_constant_and_red_dominates
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1500)
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LP-0004",
                   planned_weight_grams=380000, dimension_weight_grams=380000)
    shift = get_shift(night["shift_id"])
    assert shift["volume_variance_pct"] == pytest.approx(0.0, abs=0.0001)
    assert shift["staffing_posture"] == "GREEN"


def test_a_shortfall_beyond_ten_percent_reads_amber():
    """PRD §3.7: "a shift whose live volume falls at least 0.10 below its forecast reads
    `AMBER`, and `GREEN` is reserved for a variance strictly inside plus or minus 0.10."

    Design: Corner/calculations/labor_posture_triggers_at_the_overrun_constant_and_red_dominates
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1500)
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LP-0005",
                   planned_weight_grams=300000, dimension_weight_grams=300000)
    shift = get_shift(night["shift_id"])
    assert shift["volume_variance_pct"] == pytest.approx(-0.2105, abs=0.0001)
    assert shift["staffing_posture"] == "AMBER", (
        "under-forecast is not the same posture as a matched forecast"
    )


def test_the_floor_is_applied_before_the_threshold_comparison():
    """PRD §2.5: "the congestion threshold is the window length in minutes multiplied by 2000
    grams per minute and floored to a whole gram, and the lockdown threshold is
    the same length multiplied by 5000 grams per minute and floored."

    Design: Corner/calculations/hub_thresholds_apply_the_declared_floor_to_a_non_round_window
    """
    set_clock("2026-09-01T23:00:00Z")
    hub = create_hub(sort_window_close_minutes=1561)
    create_lane(hub["id"], capacity_weight_grams=400000)
    create_shift(hub["id"], shift_code="N-1", end_minutes=1561)
    bank = create_bank(hub["id"])
    aircraft = create_aircraft(bank["id"], capacity_weight_grams=700000)
    set_clock("2026-09-01T23:20:00Z")
    depart_and_land(aircraft["id"], 60000)
    confirm(api.begin_bank_unload(bank["id"], H["sort_supervisor_headers"]))
    confirm(api.begin_aircraft_unload(aircraft["id"], H["sort_supervisor_headers"]))
    confirm(api.complete_aircraft_unload(aircraft["id"], {"unload_completed_minutes": 1401},
                                         H["sort_supervisor_headers"]))
    create_package(hub["id"], aircraft["id"], tracking_number="1Z-PR-0001",
                   planned_weight_grams=362000, dimension_weight_grams=362000)

    read = get_hub(hub["id"])
    assert read["sort_window_close_minutes"] == 1561
    assert read["live_planned_package_total"] == 362000
    assert read["posture"] == "OPEN", (
        "floor(181 * 2000) == 362000, and the open-to-congested comparison is strict"
    )

    create_package(hub["id"], aircraft["id"], tracking_number="1Z-PR-0002",
                   planned_weight_grams=100, dimension_weight_grams=100)
    read = get_hub(hub["id"])
    assert read["live_planned_package_total"] == 362100
    assert read["posture"] == "CONGESTED"


def test_four_packages_differing_only_in_level_and_commodity_collect_four_refunds():
    """PRD §3.11: "a package that is both perishable and next-day collects both, because
    the rate is keyed on the service level while the surcharge is keyed on the commodity
    class — two independent dimensions."

    Design: Corner/calculations/money_back_guarantee_tiers_and_perishable_surcharge_compose
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1500)
    cases = [
        ("1Z-MB-0001", "NEXT_DAY_AIR", "GENERAL", 38500),
        ("1Z-MB-0002", "SECOND_DAY_AIR", "GENERAL", 21000),
        ("1Z-MB-0003", "GROUND", "GENERAL", 9800),
        ("1Z-MB-0004", "NEXT_DAY_AIR", "PERISHABLE", 38675),
    ]
    for tracking, level, commodity, _ in cases:
        package = create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking,
                                 commodity_class=commodity, service_level=level,
                                 planned_weight_grams=100000, dimension_weight_grams=100000)
        failure = confirm(api.create_failure(
            {"hub_id": night["hub_id"], "package_id": package["id"],
             "cause_code": "SORT_MISS", "failure_minutes": 1500},
            H["refund_adjuster_headers"]), 201)
        expected = dict((c[0], c[3]) for c in cases)[tracking]
        assert failure["refund_amount_cents"] == expected, tracking
        assert failure["attributed_role"] == "CARRIER"
        assert failure["refund_eligible"] is True


def test_the_lane_sum_ignores_a_loaded_package():
    """PRD §3.3: "a package that is `UNSORTED` after a reclaim, or that has been loaded and
    vacated the lane, contributes nothing."

    Design: Corner/calculations/lane_load_excludes_loaded_packages_from_the_sum
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    wide_primary = create_lane(night["hub_id"], lane_code="P-W", lane_kind="PRIMARY",
                               commodity_capability="GENERAL", capacity_weight_grams=400000,
                               certified_until_minutes=1700,
                               turnout_start_minutes=1400, turnout_end_minutes=1500)
    wide_secondary = create_lane(night["hub_id"], lane_code="S-W", lane_kind="SECONDARY",
                                 commodity_capability="GENERAL", capacity_weight_grams=400000,
                                 certified_until_minutes=1700,
                                 turnout_start_minutes=1400, turnout_end_minutes=1600)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-LS-0009",
                             planned_weight_grams=40000, dimension_weight_grams=40000)
    induct(package["id"])
    primary_sort(package["id"], wide_primary["id"])
    secondary_sort(package["id"], wide_secondary["id"])

    from test_helpers import create_move, create_buildup, plan_move, assign_package_to_buildup, onboard_package, get_lane, get_package, get_move
    # 20000 grams of forward capacity is nowhere near the 350000 onboarding
    # ceiling, so the limit has to sit at or below it.
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=20000)
    buildup = create_buildup(night["hub_id"], move["id"], container_limit_grams=200000)
    plan_move(move["id"])

    before = confirm(api.get_lane(wide_secondary["id"], H["sort_operator_headers"]))
    assert before["lane_load_grams"] == 40000

    assign_package_to_buildup(move["id"], package["id"], buildup["id"])
    onboard_package(move["id"], package["id"])

    after = confirm(api.get_lane(wide_secondary["id"], H["sort_operator_headers"]))
    assert after["lane_load_grams"] == 0
    read = get_package(package["id"])
    assert read["sort_status"] == "LOADED"
    assert read["assigned_lane_id"] is None
    assert confirm(api.get_move(move["id"], H["load_planner_headers"]))["planned_weight_grams"] == 40000


def test_the_three_move_fields_reconcile_after_a_load_then_unload():
    """PRD §3.6: "a move read after a package was loaded and then unloaded returns to
    exactly its pre-load tier and capacity, because the row set is identical and nothing
    drifts."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_computed_fields_survive_a_mutation_reversal
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    from test_helpers import create_move, plan_move, onboard_package, offboard_package, get_move
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    plan_move(move["id"])
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-DR-0001",
                             planned_weight_grams=30000, dimension_weight_grams=30000)
    induct(package["id"])
    primary_sort(package["id"], night["lane_p1_id"])
    secondary_sort(package["id"], night["lane_s1_id"])

    before = get_move(move["id"])
    assert (before["planned_weight_grams"], before["loaded_weight_grams"],
            before["forward_capacity_grams"]) == (0, 0, 350000)

    onboard_package(move["id"], package["id"])
    loaded = get_move(move["id"])
    assert (loaded["planned_weight_grams"], loaded["loaded_weight_grams"],
            loaded["forward_capacity_grams"]) == (30000, 30000, 320000)

    offboard_package(move["id"], package["id"])
    after = get_move(move["id"])
    assert after["planned_weight_grams"] == before["planned_weight_grams"]
    assert after["loaded_weight_grams"] == before["loaded_weight_grams"]
    assert after["forward_capacity_grams"] == before["forward_capacity_grams"]
    assert after["version"] > loaded["version"], (
        "the reversal updated the row rather than skipping it"
    )


def test_the_parent_version_advances_by_exactly_one_per_onboarding():
    """PRD §2.9: "Onboarding a package onto a load move must likewise carry
    `expected_load_move_version`, the client's last observed `version` of the target move,
    and a mismatch is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_version_increments_on_every_mutation
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    from test_helpers import create_move, plan_move, get_move
    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=30000)
    created_version = move["version"]
    planned = plan_move(move["id"])
    assert planned["version"] > created_version

    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-OV-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    induct(package["id"])
    primary_sort(package["id"], night["lane_p1_id"])
    secondary_sort(package["id"], night["lane_s1_id"])
    pkg_read = confirm(api.get_package(package["id"], H["sort_operator_headers"]))

    stale = api.load_package(move["id"], {
        "package_id": package["id"],
        "expected_load_move_version": created_version,
        "expected_package_version": pkg_read["version"]},
        H["load_planner_headers"])
    assert stale.status_code == 412
    assert stale.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    success = confirm(api.load_package(move["id"], {
        "package_id": package["id"],
        "expected_load_move_version": planned["version"],
        "expected_package_version": pkg_read["version"]},
        H["load_planner_headers"]))
    assert success["version"] == planned["version"] + 1
    assert success["loaded_weight_grams"] == 20000