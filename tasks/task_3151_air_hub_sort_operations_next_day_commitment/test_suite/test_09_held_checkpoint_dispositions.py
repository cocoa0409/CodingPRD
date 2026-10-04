"""The two held-checkpoint dispositions, which differ in preconditions and in effect."""
import pytest

from test_helpers import (
    confirm_list,
    TEST_USERS as H,
    api_client as api,
    assert_version_incremented,
    clear_contingency,
    confirm,
    create_package,
    declare_contingency,
    get_aircraft,
    get_ops_run,
    ground_downgrade_package,
    land_second_aircraft,
    run_ops_checkpoint,
    set_clock,
    setup_six_lane_night,
    cancel_aircraft,
    depart_and_land,
    begin_aircraft_unload,
)

CLOCK_1540 = "2026-09-02T01:40:00Z"
CLOCK_1600 = "2026-09-02T02:40:00Z"


def _advance_seed(move_instant_minutes: int = 1600):
    """Two downgraded packages plus a held checkpoint, ready for a disposition."""
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    time_downgraded = create_package(night["hub_id"], night["ac1_id"],
                                     tracking_number="1Z-OP-0001",
                                     planned_weight_grams=30000,
                                     dimension_weight_grams=30000)
    confirm(api.downgrade_commitment(
        time_downgraded["id"], {"expected_package_version": time_downgraded["version"]},
        H["commitment_controller_headers"]))

    # Both packages ride N701UP so they stay DOWNGRADED through the seed; the
    # aircraft hop is exercised on the empty N702UP, which the PRD's cancel path
    # parks with a maintenance hold and the advance reinstates.
    ground = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-OP-0002",
                            destination_hub_code="ORD", planned_weight_grams=20000,
                            dimension_weight_grams=20000)
    set_clock(CLOCK_1600)
    declare_contingency(night["hub_id"])
    ground_downgrade_package(ground["id"])
    depart_and_land(night["ac2_id"], 40000)
    begin_aircraft_unload(night["ac2_id"])
    cancel_aircraft(night["ac2_id"], "MECHANICAL")
    ops_run = run_ops_checkpoint(night["hub_id"], move_instant_minutes, "MAJOR")
    return night, time_downgraded, ground, ops_run


def test_advancing_reroutes_every_downgraded_package():
    """PRD §3.10: "every package on the hub in `DOWNGRADED` commitment moves to `REROUTED` with
    its final commitment minute set to its cutoff plus 240, and every aircraft on
    the hub that is `CANCELLED` with a maintenance hold is returned to `IN_FLIGHT`
    with its actual arrival minute cleared."

    Design: Difficulty/transitive_cascade/ops_advance_three_hop_reroute_and_aircraft_reinstatement_cascade
    """
    night, first, second, ops_run = _advance_seed()
    result = confirm(api.advance_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))
    assert result["verdict"] == "ADVANCED"

    first_read = confirm(api.get_package(first["id"], H["commitment_controller_headers"]))
    second_read = confirm(api.get_package(second["id"], H["commitment_controller_headers"]))
    assert first_read["commitment_status"] == "REROUTED"
    assert first_read["final_commitment_minutes"] == 1800
    assert second_read["commitment_status"] == "REROUTED"
    assert second_read["final_commitment_minutes"] == 1800


def test_advancing_reinstates_the_grounded_aircraft():
    """PRD §3.10: "every aircraft on the hub that is `CANCELLED` with a maintenance hold
    is returned to `IN_FLIGHT` with its actual arrival minute cleared."

    Design: Difficulty/transitive_cascade/ops_advance_three_hop_reroute_and_aircraft_reinstatement_cascade
    """
    night, first, second, ops_run = _advance_seed()
    before = get_aircraft(night["ac2_id"])
    assert before["status"] == "CANCELLED"
    assert before["maintenance_hold"] is True

    confirm(api.advance_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))

    after = get_aircraft(night["ac2_id"])
    assert after["status"] == "IN_FLIGHT"
    assert after["actual_arrival_minutes"] is None, (
        "the arrival stamp is a consequence of the aircraft hop itself"
    )
    assert after["maintenance_hold"] is True, (
        "the reinstated aircraft stays blocked from unload work until the same advance clears maintenance"
    )


def test_advancing_emits_no_failure_and_counts_the_checkpoint():
    """PRD §3.10: "Note that no failure is emitted by this disposition, and no package is
    parked."

    Design: Difficulty/transitive_cascade/ops_advance_three_hop_reroute_and_aircraft_reinstatement_cascade
    """
    night, first, second, ops_run = _advance_seed()
    read = get_ops_run(ops_run["id"])
    assert read["run_index"] == 1
    assert read["level"] == "MAJOR"
    assert read["verdict"] == "HELD"

    result = confirm(api.advance_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))
    assert result["verdict"] == "ADVANCED"

    hub = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert hub["ops_run_index"] == 2, (
        "creating the checkpoint took the index to 1 and the advance took it to 2"
    )
    for pkg_id in (first["id"], second["id"]):
        failures, _ = confirm_list(api.list_package_failures(pkg_id, H["refund_adjuster_headers"]))
        assert len(failures) == 1, "the advance emits no new failure beyond the seeding ones"


def test_releasing_parks_every_downgraded_package_and_leaves_aircraft_alone():
    """PRD §3.10: "every package on the hub in `DOWNGRADED` commitment moves to `REROUTED` with
    its final commitment minute set to its cutoff plus 240, and every aircraft on
    the hub that is `CANCELLED` with a maintenance hold is returned to `IN_FLIGHT`
    with its actual arrival minute cleared."
    PRD §3.10: "No aircraft changes status at all under this disposition — the aircraft-level
    compensation belongs exclusively to the advance path."

    Design: Difficulty/transitive_cascade/ops_advance_three_hop_reroute_and_aircraft_reinstatement_cascade
    """
    night, first, second, ops_run = _advance_seed()
    before = get_aircraft(night["ac2_id"])

    # Releasing requires the contingency to be clear.
    clear_contingency(night["hub_id"])
    released = confirm(api.release_ops_run(ops_run["id"], H["hub_ops_manager_headers"]))
    assert released["verdict"] == "RELEASED"

    first_read = confirm(api.get_package(first["id"], H["commitment_controller_headers"]))
    assert first_read["commitment_status"] == "UPGRADED_HELD"
    assert first_read["final_commitment_minutes"] == 1920, "the cutoff plus 360"

    after = get_aircraft(night["ac2_id"])
    assert after["status"] == before["status"], (
        "the aircraft-level compensation belongs exclusively to the advance path"
    )
    hub = confirm(api.get_hub(night["hub_id"], H["hub_ops_manager_headers"]))
    assert hub["ops_run_index"] == 2, (
        "creating the checkpoint took the index to 1 and the release took it to 2"
    )