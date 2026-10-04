"""The commitment axis is a cycle: downgrade, compensating void, reroute, clear."""
import pytest

from test_helpers import (
    CLOCK_1540,
    CLOCK_1600,
    api_client as api,
    TEST_USERS as H,
    clear_contingency,
    confirm,
    create_package,
    declare_contingency,
    get_package,
    package_failures,
    set_clock,
    setup_night,
    run_ops_checkpoint,
    advance_ops_run,
)


def _rerouted_by_advance(night, pkg):
    """Produce a REROUTED package that survives a cleared contingency.

    PRD 3.4 sweeps every package that is DIVERTED in handling **and** REROUTED in
    commitment back to COMMITTED the moment the contingency clears, so the only
    REROUTED state §3.9's clear-reroute can act on is the one §3.10's advance
    disposition creates: DOWNGRADED -> REROUTED with the handling dimension left
    alone.
    """
    current = get_package(pkg["id"])
    if current["commitment_status"] == "COMMITTED":
        downgraded = confirm(api.downgrade_commitment(
            pkg["id"], {"expected_package_version": current["version"]},
            H["commitment_controller_headers"]))
        assert downgraded["commitment_status"] == "DOWNGRADED"
    checkpoint = run_ops_checkpoint(night["hub_id"], 1540, "MAJOR")
    advance_ops_run(checkpoint["id"])
    return get_package(pkg["id"])


@pytest.fixture
def night():
    return setup_night()


def test_the_commitment_axis_returns_to_committed_twice(night):
    """PRD §3.9: "five states: `COMMITTED`, `DOWNGRADED`, `REROUTED`, `VOIDED` and
    `UPGRADED_HELD`."
    PRD §3.12: "voiding a carrier refund restores the package's commitment."

    Design: Difficulty/non_linear_state_machine/package_commitment_cyclic_decision_loop_down_up_down
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CY-0001",
                         planned_weight_grams=20000, dimension_weight_grams=20000)
    version = pkg["version"]
    set_clock(CLOCK_1540)

    downgraded = confirm(api.downgrade_commitment(
        pkg["id"], {"expected_package_version": version}, H["commitment_controller_headers"]))
    assert downgraded["commitment_status"] == "DOWNGRADED"
    assert downgraded["final_commitment_minutes"] == 1920, "the cutoff 1560 plus 360"

    failures = package_failures(pkg["id"])
    assert len(failures) == 1
    confirm(api.void_failure(failures[0]["id"], H["refund_adjuster_headers"]))

    restored = get_package(pkg["id"])
    assert restored["commitment_status"] == "COMMITTED", "the first revisit of COMMITTED"
    assert restored["final_commitment_minutes"] is None
    return restored


def test_the_reroute_leg_sets_the_shorter_buffer_and_clears_back(night):
    """PRD §3.9: "sets the final commitment minute to the cutoff plus 240, emits exactly one
    failure with a `LATE_INBOUND` cause attributed to the carrier, in `OPEN`
    status and refund-eligible, and recomputes the hub's live volume and posture."
    PRD §3.9: "returning it to `COMMITTED` handling `NORMAL` with any open reroute failure
    voided and the live volume recomputed."

    Design: Difficulty/non_linear_state_machine/package_commitment_cyclic_decision_loop_down_up_down
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CY-0002",
                         planned_weight_grams=20000, dimension_weight_grams=20000)

    set_clock(CLOCK_1540)
    declare_contingency(night["hub_id"])
    rerouted = _rerouted_by_advance(night, pkg)
    assert rerouted["commitment_status"] == "REROUTED"
    assert rerouted["final_commitment_minutes"] == 1800, "the cutoff 1560 plus 240"

    clear_contingency(night["hub_id"])
    cleared = confirm(api.clear_reroute(pkg["id"], H["commitment_controller_headers"]))
    assert cleared["commitment_status"] == "COMMITTED", "the second revisit of COMMITTED"
    assert cleared["final_commitment_minutes"] is None
    return cleared


def test_each_decision_overwrites_the_final_commitment_minute(night):
    """PRD §3.9: "the decisions below move the package relative to that cutoff."
    PRD §3.11: "    "moving only when the failure's own status moves or when its history is re-
    derived.""

    Design: Difficulty/non_linear_state_machine/package_commitment_cyclic_decision_loop_down_up_down
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CY-0003",
                         planned_weight_grams=20000, dimension_weight_grams=20000)
    set_clock(CLOCK_1540)
    first = confirm(api.downgrade_commitment(
        pkg["id"], {"expected_package_version": pkg["version"]},
        H["commitment_controller_headers"]))
    assert first["final_commitment_minutes"] == 1920

    declare_contingency(night["hub_id"])
    second = _rerouted_by_advance(night, pkg)
    assert second["final_commitment_minutes"] == 1800, (
        "the later decision overwrites the earlier final commitment minute"
    )
    assert second["commitment_status"] == "REROUTED"


def test_the_cycle_closes_with_no_drift(night):
    """PRD §3.9: "Every commitment decision in this subsection also requires that the package
    has not already been loaded — a commitment action on a loaded package is
    refused with `ERR_SORT_PENDING` — and the two decisions that would strand a
    package at the hub require that it is not already `HOLD_AT_HUB`."

    Design: Difficulty/non_linear_state_machine/package_commitment_cyclic_decision_loop_down_up_down
    """
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CY-0004",
                         planned_weight_grams=20000, dimension_weight_grams=20000)
    assert pkg["commitment_status"] == "COMMITTED"
    set_clock(CLOCK_1540)
    declare_contingency(night["hub_id"])
    _rerouted_by_advance(night, pkg)
    clear_contingency(night["hub_id"])
    final = confirm(api.clear_reroute(pkg["id"], H["commitment_controller_headers"]))

    assert final["commitment_status"] == "COMMITTED"
    assert final["handling_status"] == "NORMAL"
    assert final["commitment_posture"] == "COMMITTED_OK", (
        "the derived commitment posture follows the restored status"
    )