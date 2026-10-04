"""The compensating invariant: a downgrade paired with its void leaves the hub's live
volume exactly where it started."""
import pytest

from test_helpers import (
    TEST_USERS as H,
    api_client as api,
    confirm,
    create_move,
    get_hub,
    get_package,
    package_failures,
    plan_move,
    set_clock,
    setup_six_lane_night,
    onboard_package,
    create_package,
    induct,
    primary_sort,
    secondary_sort,
)

CLOCK_1540 = "2026-09-02T01:40:00Z"


def test_the_forward_step_leaves_the_invariant_untouched():
    """PRD §2.6: "The inclusion set is pinned by enumeration rather than by any adjective: a
    package leaves the live total the instant it is diverted or parked at the hub,
    and it returns the instant it is cleared back."
    PRD §3.12: "The package the failure names, if it is in `DOWNGRADED` commitment, returns
    to `COMMITTED` with its final commitment minute cleared to null and its
    service level restored to the level it originally committed to;"

    Design: Difficulty/compensating_invariant/money_back_refund_void_restores_hub_live_volume_invariant
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CI-0001",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    before = get_hub(night["hub_id"])["live_planned_package_total"]
    assert before == 20000

    downgraded = confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    assert downgraded["commitment_status"] == "DOWNGRADED"
    after_down = get_hub(night["hub_id"])["live_planned_package_total"]
    assert after_down == before


def test_the_compensating_void_restores_the_exact_pre_sequence_volume():
    """PRD §3.12: "The hub's live volume recomputes as a result, and the hub's refund
    batch total recomputes because the voided failure leaves the carrier sum."

    Design: Difficulty/compensating_invariant/money_back_refund_void_restores_hub_live_volume_invariant
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CI-0002",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    before = get_hub(night["hub_id"])["live_planned_package_total"]

    confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    failures = package_failures(package["id"])
    assert len(failures) == 1
    assert failures[0]["attributed_role"] == "CARRIER"
    confirm(api.void_failure(failures[0]["id"], H["refund_adjuster_headers"]))

    after_void = get_hub(night["hub_id"])["live_planned_package_total"]
    assert after_void == before
    assert after_void == 20000
    read = get_package(package["id"])
    assert read["commitment_status"] == "COMMITTED"
    assert read["final_commitment_minutes"] is None, "no drift in the commitment decision either"


def test_the_invariant_is_broken_by_carrying_the_package_onto_the_move_first():
    """PRD §3.9: "Every commitment decision in this subsection also requires that the package
    has not already been loaded — a commitment action on a loaded package is
    refused with `ERR_SORT_PENDING` — and the two decisions that would strand a
    package at the hub require that it is not already `HOLD_AT_HUB`."

    Design: Difficulty/compensating_invariant/money_back_refund_void_restores_hub_live_volume_invariant
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CI-0003",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    induct(package["id"])
    primary_sort(package["id"], night["lane_p1_id"])
    secondary_sort(package["id"], night["lane_s1_id"])

    move = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    plan_move(move["id"])
    onboard_package(move["id"], package["id"])

    # The loaded package is not loadable again, and its commitment decision is closed off.
    loaded = get_package(package["id"])
    assert loaded["sort_status"] == "LOADED"
    attempt = api.downgrade_commitment(
        package["id"], {"expected_package_version": loaded["version"]},
        H["commitment_controller_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_SORT_PENDING"


def test_the_live_volume_is_unchanged_across_the_whole_forward_plus_compensating_sequence():
    """PRD §3.12: "voiding a carrier refund restores the package's commitment."

    Design: Difficulty/compensating_invariant/money_back_refund_void_restores_hub_live_volume_invariant
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1540)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-CI-0004",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    before = get_hub(night["hub_id"])["live_planned_package_total"]

    confirm(api.downgrade_commitment(
        package["id"], {"expected_package_version": package["version"]},
        H["commitment_controller_headers"]))
    failures = package_failures(package["id"])
    confirm(api.void_failure(failures[0]["id"], H["refund_adjuster_headers"]))

    assert get_hub(night["hub_id"])["live_planned_package_total"] == before
    assert before == 20000