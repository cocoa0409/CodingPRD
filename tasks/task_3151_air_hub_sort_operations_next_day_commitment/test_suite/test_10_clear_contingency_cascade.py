"""The four-hop clear-contingency chain: Hub to Package, Package to Hub,
Hub to LaborShift, LaborShift to the triage read."""
import pytest

from test_helpers import (
    TEST_USERS as H,
    api_client as api,
    clear_contingency,
    confirm,
    create_extension_shift,
    create_package,
    declare_contingency,
    diverge_package,
    get_triage,
    land_second_aircraft,
    set_clock,
    setup_six_lane_night,
)

CLOCK_1601_INSTANT = "2026-09-02T02:21:00Z"  # minute 1581, inside the extension shift


def _cascade_seed():
    """Seven baseline packages plus one diverted package parked out of the live set."""
    night = setup_six_lane_night()
    extension = create_extension_shift(night["hub_id"])
    night["shift_id"] = extension["id"]
    night["shift"] = extension

    set_clock(CLOCK_1601_INSTANT)
    for index in range(1, 8):
        create_package(night["hub_id"], night["ac1_id"],
                       tracking_number=f"1Z-CS-{index:04d}",
                       planned_weight_grams=50000, dimension_weight_grams=50000)
    land_second_aircraft(night, inbound_weight_grams=100000, unload_minutes=1601, complete=True)
    parked = create_package(night["hub_id"], night["ac2_id"], tracking_number="1Z-CS-0008",
                            planned_weight_grams=100000, dimension_weight_grams=100000)
    declare_contingency(night["hub_id"])
    diverge_package(parked["id"])
    return night, parked


def test_clearing_restores_the_diverted_package_first():
    """PRD §3.4: "Every package that is `DIVERTED` in handling and `REROUTED` in commitment has
    its commitment returned to `COMMITTED`, its `final_commitment_minutes` cleared
    to null, and its service level restored to the level it originally committed
    to;"

    Design: Difficulty/transitive_cascade/clear_contingency_four_hop_stranding_cascade
    """
    night, parked = _cascade_seed()
    before = confirm(api.get_package(parked["id"], H["commitment_controller_headers"]))
    assert before["commitment_status"] == "REROUTED"
    assert before["handling_status"] == "DIVERTED"

    clear_contingency(night["hub_id"])
    after = confirm(api.get_package(parked["id"], H["commitment_controller_headers"]))
    assert after["commitment_status"] == "COMMITTED"
    assert after["handling_status"] == "NORMAL"
    assert after["final_commitment_minutes"] is None


def test_the_restored_package_lifts_the_live_total_back_across_the_threshold():
    """PRD §2.6: "a package leaves the live total the instant it is diverted or parked
    at the hub, and it returns the instant it is cleared back."
    PRD §2.5: "Above the congestion threshold but at or below the lockdown threshold, the
    hub reads `CONGESTED`;"

    Design: Difficulty/transitive_cascade/clear_contingency_four_hop_stranding_cascade
    """
    night, parked = _cascade_seed()
    diverted_total = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert diverted_total["live_planned_package_total"] == 350000, (
        "the diverted 100000-gram package has left the live set"
    )

    clear_contingency(night["hub_id"])
    hub = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert hub["live_planned_package_total"] == 450000, (
        "the restored package lifted the live total back across the 360000 congestion threshold"
    )
    assert hub["posture"] == "CONGESTED"


def test_the_posture_change_moves_the_containing_shift_off_green():
    """PRD §3.7: "Otherwise, if the shift's variance is at least 0.15, the posture is
    `SATURATED`."
    PRD §3.7: "The variance itself is the live volume minus the shift's forecast volume,
    divided by the forecast volume, rounded half up to four decimal places,
    expressed as a signed fraction."

    Design: Difficulty/transitive_cascade/clear_contingency_four_hop_stranding_cascade
    """
    night, parked = _cascade_seed()
    green_shift = confirm(api.get_shift(night["shift_id"], H["sort_supervisor_headers"]))
    assert green_shift["staffing_posture"] == "GREEN", (
        "with the package still diverted the live total is 350000, well inside the GREEN band"
    )

    clear_contingency(night["hub_id"])
    shift = confirm(api.get_shift(night["shift_id"], H["sort_supervisor_headers"]))
    assert shift["staffing_posture"] == "SATURATED"
    assert shift["volume_variance_pct"] == pytest.approx(0.1842, abs=0.0001), (
        "the 450000 live total against the forecast of 380000"
    )


def test_the_saturated_shift_throttles_the_triage_read():
    """PRD §3.7: "If it is `SATURATED`, the triage is `THROTTLE_INDUCTION`."

    Design: Difficulty/transitive_cascade/clear_contingency_four_hop_stranding_cascade
    """
    night, parked = _cascade_seed()
    accept = get_triage(night["hub_id"])
    assert accept["triage"] == "ACCEPT", "the pre-cascade baseline reads ACCEPT"

    clear_contingency(night["hub_id"])
    triage = get_triage(night["hub_id"])
    assert triage["triage"] == "THROTTLE_INDUCTION"
    assert triage["staffing_posture"] == "SATURATED"
