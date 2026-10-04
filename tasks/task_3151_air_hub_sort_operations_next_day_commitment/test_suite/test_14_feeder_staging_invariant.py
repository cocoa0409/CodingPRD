"""The conserved quantity of a feeder's staging lane: cancelling returns it to zero."""
import pytest

from test_helpers import (
    confirm_list,
    TEST_USERS as H,
    api_client as api,
    begin_staging,
    confirm,
    create_feeder,
    create_package,
    get_feeder,
    get_package,
    set_clock,
    setup_night,
    stage_package,
)

CLOCK_1414 = "2026-09-01T23:34:00Z"


@pytest.fixture
def night():
    ctx = setup_night()
    set_clock(CLOCK_1414)
    return ctx


def _ground_package(night, tracking_number: str, grams: int) -> dict:
    return create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                          destination_hub_code="LEX", service_level="GROUND",
                          planned_weight_grams=grams, dimension_weight_grams=grams)


def _staged_feeder(night):
    feeder = create_feeder(night["hub_id"], feeder_code="F-1",
                           scheduled_departure_minutes=1420,
                           stage_capacity_grams=100000, window_minutes=10)
    begin_staging(feeder["id"])
    return feeder


def test_the_lane_rises_to_the_staged_weight_and_falls_back_to_zero(night):
    """PRD §3.8: "Staging a package onto the feeder's turnout lane records the feeder on the
    package's `staged_feeder_id` and accumulates the feeder's
    `staged_weight_grams`, which is the sum of `planned_weight_grams` over every
    package staged on it whose commitment is not voided."
    PRD §3.8: "A cancellation from either of the two later states releases every staged
    package back to the sort surface and clears its feeder reference, recomputing the
    staged weight to zero."

    Design: Difficulty/compensating_invariant/ground_feeder_depart_cancel_restores_staging_lane_invariant
    """
    feeder = _staged_feeder(night)
    assert get_feeder(feeder["id"])["staged_weight_grams"] == 0

    first = _ground_package(night, "1Z-FI-0001", 50000)
    second = _ground_package(night, "1Z-FI-0002", 50000)
    stage_package(feeder["id"], first["id"])
    loaded = stage_package(feeder["id"], second["id"])
    assert loaded["staged_weight_grams"] == 100000

    cancelled = confirm(api.cancel_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["staged_weight_grams"] == 0
    assert cancelled["staged_weight_grams"] == 0


def test_the_cancelled_lane_returns_both_packages_rather_than_consuming_them(night):
    """PRD §3.8: "A cancellation from either of the two later states releases every staged
    package back to the sort surface and clears its feeder reference, recomputing
    the staged weight to zero."

    Design: Difficulty/compensating_invariant/ground_feeder_depart_cancel_restores_staging_lane_invariant
    """
    feeder = _staged_feeder(night)
    first = _ground_package(night, "1Z-FI-0003", 50000)
    second = _ground_package(night, "1Z-FI-0004", 50000)
    stage_package(feeder["id"], first["id"])
    stage_package(feeder["id"], second["id"])

    confirm(api.cancel_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    read = get_package(first["id"])
    assert read["commitment_status"] == "COMMITTED"
    assert read["commitment_status"] != "VOIDED", "the packages were returned, not consumed"


def test_no_package_remains_on_the_cancelled_feeder(night):
    """PRD §3.8: "A cancellation from either of the two later states releases every staged
    package back to the sort surface and clears its feeder reference, recomputing
    the staged weight to zero."

    Design: Difficulty/compensating_invariant/ground_feeder_depart_cancel_restores_staging_lane_invariant
    """
    feeder = _staged_feeder(night)
    first = _ground_package(night, "1Z-FI-0005", 50000)
    second = _ground_package(night, "1Z-FI-0006", 50000)
    stage_package(feeder["id"], first["id"])
    stage_package(feeder["id"], second["id"])
    confirm(api.cancel_feeder(feeder["id"], H["feeder_coordinator_headers"]))

    remaining, _ = confirm_list(api.list_packages(H["feeder_coordinator_headers"],
                                             {"staged_feeder_id": feeder["id"]}))
    assert remaining == [], "both packages left the lane"


def test_the_same_volume_taken_through_departure_is_voided_instead(night):
    """PRD §3.8: "every staged package has its commitment voided, its handling moved to
    `DIVERTED`, and its final commitment minute cleared, each emits exactly one
    failure with a `REVENUE_PRORATE` cause attributed to the customer, in `OPEN`
    status and not refund-eligible, and the hub's live volume recomputes."

    Design: Difficulty/compensating_invariant/ground_feeder_depart_cancel_restores_staging_lane_invariant
    """
    feeder = _staged_feeder(night)
    first = _ground_package(night, "1Z-FI-0007", 50000)
    second = _ground_package(night, "1Z-FI-0008", 40000)
    stage_package(feeder["id"], first["id"])
    stage_package(feeder["id"], second["id"])
    confirm(api.begin_feeder_loading(feeder["id"], H["feeder_coordinator_headers"]))
    departed = confirm(api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert departed["status"] == "DEPARTED"
    assert departed["staged_weight_grams"] == 0

    read = get_package(first["id"])
    assert read["commitment_status"] == "VOIDED", (
        "the lane also reads zero, but the packages were consumed rather than restored"
    )
    assert read["handling_status"] == "DIVERTED"
    assert read["final_commitment_minutes"] is None