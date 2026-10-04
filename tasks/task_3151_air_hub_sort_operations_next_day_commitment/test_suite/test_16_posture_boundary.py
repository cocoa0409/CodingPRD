"""The asymmetric hub-posture boundary: strict above the congestion threshold,
inclusive at the lockdown threshold."""
import pytest

from test_helpers import (
    CONGESTION_THRESHOLD_GRAMS,
    create_lane,
    create_package,
    get_hub,
    set_clock,
    setup_night,
)

CLOCK_1414 = "2026-09-01T23:34:00Z"


@pytest.fixture
def night():
    ctx = setup_night()
    set_clock(CLOCK_1414)
    return ctx


def test_a_live_total_exactly_at_the_congestion_threshold_stays_open(night):
    """PRD §2.5: "the open-to-congested comparison is strict, so a live volume of exactly the
    floored congestion threshold reads `OPEN` and not `CONGESTED`, while the
    congested-to-lockdown comparison is inclusive, so a live volume of exactly the
    floored lockdown threshold reads `LOCKDOWN` and not `CONGESTED`."

    Design: Difficulty/boundary_precision_check/hub_posture_strict_greater_than_at_the_congestion_threshold
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-BP-0001",
                   planned_weight_grams=CONGESTION_THRESHOLD_GRAMS,
                   dimension_weight_grams=CONGESTION_THRESHOLD_GRAMS)
    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 360000
    assert hub["posture"] == "OPEN", (
        "360000 against the floored threshold of 360000 is not greater than it"
    )


def test_one_hundred_grams_later_the_hub_reads_congested(night):
    """PRD §2.5: "Above the congestion threshold but at or below the lockdown threshold, the
    hub reads `CONGESTED`;"

    Design: Difficulty/boundary_precision_check/hub_posture_strict_greater_than_at_the_congestion_threshold
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-BP-0002",
                   planned_weight_grams=CONGESTION_THRESHOLD_GRAMS,
                   dimension_weight_grams=CONGESTION_THRESHOLD_GRAMS)
    assert get_hub(night["hub_id"])["posture"] == "OPEN"

    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-BP-0003",
                   planned_weight_grams=100, dimension_weight_grams=100)
    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 360100
    assert hub["posture"] == "CONGESTED"


def test_a_total_that_should_have_been_congested_would_be_an_off_by_one(night):
    """PRD §2.5: "    "The boundaries are deliberate and asymmetric: the open-to-congested
    comparison is strict, so a live volume of exactly the floored congestion
    threshold reads `OPEN` and not `CONGESTED`, while the congested-to-lockdown
    comparison is inclusive, so a live volume of exactly the floored lockdown
    threshold reads `LOCKDOWN` and not `CONGESTED`.""

    Design: Difficulty/boundary_precision_check/hub_posture_strict_greater_than_at_the_congestion_threshold
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-BP-0004",
                   planned_weight_grams=360000, dimension_weight_grams=360000)
    hub = get_hub(night["hub_id"])
    assert hub["posture"] != "CONGESTED", (
        "a total of 360000 that should have been CONGESTED would be an off-by-one error"
    )
    assert hub["live_planned_package_total"] == CONGESTION_THRESHOLD_GRAMS


def test_the_lockdown_side_of_the_boundary_is_inclusive(night):
    """PRD §2.5: "the congested-to-lockdown comparison is inclusive, so a live volume of
    exactly the floored lockdown threshold reads `LOCKDOWN` and not `CONGESTED`."

    Design: Difficulty/boundary_precision_check/hub_posture_strict_greater_than_at_the_congestion_threshold
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-BP-0005",
                   planned_weight_grams=900000, dimension_weight_grams=900000)
    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 900000
    assert hub["posture"] == "LOCKDOWN", (
        "900000 against the floored lockdown threshold is at or above it"
    )


def test_a_totally_empty_hub_reads_open(night):
    """PRD §2.5: "at or below the congestion threshold it reads `OPEN`."

    Design: Difficulty/boundary_precision_check/hub_posture_strict_greater_than_at_the_congestion_threshold
    """
    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 0
    assert hub["posture"] == "OPEN"