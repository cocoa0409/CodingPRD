"""Ground feeder turnout windows and the departure ceiling that is tighter than staging."""
import pytest

from test_helpers import (
    TEST_USERS as H,
    api_client as api,
    begin_feeder_loading,
    begin_staging,
    confirm,
    create_feeder,
    create_package,
    get_feeder,
    set_clock,
    setup_night,
    stage_package,
)

CLOCK_1414 = "2026-09-01T23:34:00Z"
CLOCK_1425 = "2026-09-01T23:45:00Z"


@pytest.fixture
def night():
    ctx = setup_night()
    set_clock(CLOCK_1414)
    return ctx


def _ground_package(night, tracking_number: str, grams: int) -> dict:
    return create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                          destination_hub_code="LEX", service_level="GROUND",
                          planned_weight_grams=grams, dimension_weight_grams=grams)


def test_a_window_that_touches_exactly_is_refused(night):
    """PRD §3.8: "No other feeder on the hub may already be `STAGING` within one window
    length of this feeder's scheduled departure; a collision is refused with
    `ERR_FEEDER_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ground_feeder_turnout_point_touching_intervals_and_departure_ceiling
    """
    early = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1420,
                          stage_capacity_grams=100000, window_minutes=10)
    adjacent = create_feeder(night["hub_id"], feeder_code="F-2", scheduled_departure_minutes=1430,
                             stage_capacity_grams=100000, window_minutes=10)
    staged = begin_staging(early["id"])
    assert staged["status"] == "STAGING"

    attempt = api.begin_staging(adjacent["id"], H["feeder_coordinator_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_FEEDER_WINDOW_CONFLICT", (
        "1420 plus the ten-minute window is 1430, the first instant of the adjacent turnout"
    )


def test_a_full_staging_load_breaches_the_departure_ceiling(night):
    """PRD §3.8: "While the feeder is `STAGING`, the compliant ceiling is the full stage
    capacity;"
    PRD §3.8: "A feeder staged to exactly its full capacity is therefore perfectly compliant
    while staging and over its departure ceiling by five percent at the moment it
    leaves — refused with `ERR_FEEDER_OVER_CAPACITY` (HTTP 409), even though
    nothing about the load changed."

    Design: Difficulty/resource_temporal_overlap/ground_feeder_turnout_point_touching_intervals_and_departure_ceiling
    """
    feeder = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1420,
                           stage_capacity_grams=100000, window_minutes=10)
    package = _ground_package(night, "1Z-GF-0001", 100000)
    begin_staging(feeder["id"])
    staged = stage_package(feeder["id"], package["id"])
    assert staged["staged_weight_grams"] == 100000, (
        "the same load is compliant while staging"
    )

    begin_feeder_loading(feeder["id"])
    attempt = api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_FEEDER_OVER_CAPACITY", (
        "100000 exceeds floor(100000 * 0.95) == 95000"
    )


def test_a_load_under_the_tolerance_departs(night):
    """PRD §3.8: "at departure, the ceiling is ninety-five percent of the stage capacity,
    floored to a whole gram — the departure tolerance applied to the stage
    capacity, so the comparison is against exactly 0.95 of it."

    Design: Difficulty/resource_temporal_overlap/ground_feeder_turnout_point_touching_intervals_and_departure_ceiling
    """
    feeder = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1420,
                           stage_capacity_grams=100000, window_minutes=10)
    package = _ground_package(night, "1Z-GF-0002", 90000)
    begin_staging(feeder["id"])
    stage_package(feeder["id"], package["id"])
    begin_feeder_loading(feeder["id"])

    departed = confirm(api.depart_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert departed["status"] == "DEPARTED", "90000 is at or below the 95000 ceiling"


def test_a_window_separated_by_more_than_one_window_length_opens(night):
    """PRD §3.8: "The current hub minute must be at or after the scheduled departure
    minus the window length, and strictly before the scheduled departure."

    Design: Difficulty/resource_temporal_overlap/ground_feeder_turnout_point_touching_intervals_and_departure_ceiling
    """
    early = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1420,
                          stage_capacity_grams=100000, window_minutes=10)
    adjacent = create_feeder(night["hub_id"], feeder_code="F-2", scheduled_departure_minutes=1430,
                             stage_capacity_grams=100000, window_minutes=10)
    detached = create_feeder(night["hub_id"], feeder_code="F-3", scheduled_departure_minutes=1431,
                             stage_capacity_grams=100000, window_minutes=10)
    begin_staging(early["id"])

    set_clock(CLOCK_1425)
    confirm(api.cancel_feeder(early["id"], H["feeder_coordinator_headers"]))
    confirm(api.cancel_feeder(adjacent["id"], H["feeder_coordinator_headers"]))

    staged = begin_staging(detached["id"])
    assert staged["status"] == "STAGING", (
        "one minute of separation from the adjacent window means the conflict is gone"
    )


def test_cancelling_a_staging_feeder_returns_its_volume(night):
    """PRD §3.8: "A cancellation from either of the two later states releases every staged
    package back to the sort surface and clears its feeder reference, recomputing the
    staged weight to zero."

    Design: Difficulty/resource_temporal_overlap/ground_feeder_turnout_point_touching_intervals_and_departure_ceiling
    """
    feeder = create_feeder(night["hub_id"], feeder_code="F-1", scheduled_departure_minutes=1420,
                           stage_capacity_grams=100000, window_minutes=10)
    package = _ground_package(night, "1Z-GF-0003", 50000)
    begin_staging(feeder["id"])
    stage_package(feeder["id"], package["id"])
    assert get_feeder(feeder["id"])["staged_weight_grams"] == 50000

    cancelled = confirm(api.cancel_feeder(feeder["id"], H["feeder_coordinator_headers"]))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["staged_weight_grams"] == 0

    from test_helpers import get_package
    read = get_package(package["id"])
    assert read["staged_feeder_id"] is None, "the feeder reference is cleared"
    assert read["commitment_status"] == "COMMITTED", (
        "a cancellation returns the package rather than consuming it"
    )