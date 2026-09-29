"""Resource temporal overlap: the chair's padded block and the clinician's cap.

Source: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rule `resource_temporal_overlap`.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_infusion_appointment,
    assert_instant_equals,
    assert_unit_ledger,
    assert_visit,
    validate_list,
)
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.factories import create_appointment_payload, create_visit_payload
from test_helpers.fixtures import (
    ADMIN,
    bootstrap_reference,
    book_visit,
    register_patient,
    scheduled_dose,
    set_clock,
)


def _chair_practice():
    """Infliximab (IV, 150 minutes) on Meridian PPO, chair AIC-1 with a
    30-minute turnover buffer, an `ACTIVE` episode with six approved units and
    one appointment already occupying 2026-08-12T09:00:00Z."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = scheduled_dose(instant(2026, 8, 12, 9, 0, 0), requested_units=6)
    return scenario, scenario.appointment


def _schedule(scenario, scheduled_start):
    return api_client.create_infusion_appointment(
        create_appointment_payload(
            scenario.episode_id, scenario.chair_id, scheduled_start=scheduled_start
        ),
        scenario.nurse_headers,
    )


# ---------------------------------------------------------------------------
# resource_temporal_overlap /
# infusion_chair_occupancy_plus_turnover_buffer_rejects_only_inside_the_block
# ---------------------------------------------------------------------------
def test_chair_start_inside_the_turnover_block_is_refused():
    """A 150-minute dose from 09:00 blocks the chair through 12:00.

    PRD §3.7: "Each of the chair's existing appointments in `SCHEDULED` or
    `ADMINISTERED` blocks an interval that is its own occupancy padded by the
    chair's `turnover_buffer_minutes` on **both** sides — from its
    `scheduled_start` less the buffer up to, but not including, its
    `scheduled_end` plus the buffer."

    Design: Difficulty/resource_temporal_overlap/infusion_chair_occupancy_plus_turnover_buffer_rejects_only_inside_the_block
    """
    scenario, first = _chair_practice()
    assert_infusion_appointment(first)
    assert_instant_equals(first["scheduled_start"], instant(2026, 8, 12, 9, 0, 0))
    assert_instant_equals(first["scheduled_end"], instant(2026, 8, 12, 11, 30, 0))

    response = _schedule(scenario, instant(2026, 8, 12, 11, 45, 0))

    validate_error(response, ApiErrorId.ERR_CHAIR_TIME_CONFLICT.value, 409)
    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)


def test_chair_start_exactly_at_the_end_of_the_block_is_accepted():
    """A start at the exact instant the padded block ends does not conflict.

    PRD §3.7: "A dose that starts at the exact instant an existing dose's
    `scheduled_end` plus buffer falls does not conflict, and neither does one
    that ends exactly at an existing dose's `scheduled_start` less the buffer."

    Design: Difficulty/resource_temporal_overlap/infusion_chair_occupancy_plus_turnover_buffer_rejects_only_inside_the_block
    """
    scenario, _first = _chair_practice()

    second = get_success_data(_schedule(scenario, instant(2026, 8, 12, 12, 0, 0)), 201)

    assert_infusion_appointment(second)
    assert_instant_equals(second["scheduled_start"], instant(2026, 8, 12, 12, 0, 0))
    assert_instant_equals(second["scheduled_end"], instant(2026, 8, 12, 14, 30, 0))
    assert second["dose_sequence"] == 2
    assert second["status"] == "SCHEDULED"


def test_only_the_start_inside_the_block_is_rejected_and_it_reserves_nothing():
    """The rejected request leaves the chair's calendar and the unit ledger alone.

    PRD §3.7: "If those two half-open intervals overlap at any instant, the
    request is refused with `ERR_CHAIR_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/infusion_chair_occupancy_plus_turnover_buffer_rejects_only_inside_the_block
    """
    scenario, _first = _chair_practice()

    refused = _schedule(scenario, instant(2026, 8, 12, 11, 45, 0))
    validate_error(refused, ApiErrorId.ERR_CHAIR_TIME_CONFLICT.value, 409)

    accepted = get_success_data(_schedule(scenario, instant(2026, 8, 12, 12, 0, 0)), 201)
    assert accepted["dose_sequence"] == 2

    rows, meta = validate_list(
        api_client.list_infusion_appointments(ADMIN, {"chair_id": scenario.chair_id})
    )
    assert meta["total_count"] == 2, (
        f"the chair must hold exactly the two accepted doses, got {meta['total_count']}"
    )
    assert len(rows) == 2

    assert_unit_ledger(scenario.refresh_authorization(), reserved=2, consumed=0, remaining=4)


# ---------------------------------------------------------------------------
# resource_temporal_overlap /
# clinician_concurrent_visit_cap_uses_half_open_zero_buffer_intervals
# ---------------------------------------------------------------------------
def _clinician_book():
    """One rheumatologist, four patients, and two 30-minute `FOLLOW_UP` visits
    already booked on 2026-08-03 at 14:00 and 14:10."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = bootstrap_reference()
    patients = [register_patient(scenario) for _ in range(4)]
    first = book_visit(
        scenario, instant(2026, 8, 3, 14, 0, 0), patient_id=patients[0]["id"]
    )
    second = book_visit(
        scenario, instant(2026, 8, 3, 14, 10, 0), patient_id=patients[1]["id"]
    )
    return scenario, patients, first, second


def _book(scenario, patient_id, visit_datetime):
    return api_client.create_visit(
        create_visit_payload(
            patient_id, scenario.rheumatologist_id, visit_datetime=visit_datetime
        ),
        scenario.rheum_headers,
    )


def test_a_third_visit_overlapping_both_bookings_exceeds_the_clinician_cap():
    """Two overlapping visits are the cap; a third overlapping one is refused.

    PRD §3.2: "A clinician may hold at most two mutually overlapping visits; if
    the requested interval would overlap two visits the clinician already has,
    the third booking is refused with `ERR_CLINICIAN_CAPACITY_EXCEEDED` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/clinician_concurrent_visit_cap_uses_half_open_zero_buffer_intervals
    """
    scenario, patients, first, second = _clinician_book()
    assert_instant_equals(first["visit_end_datetime"], instant(2026, 8, 3, 14, 30, 0))
    assert_instant_equals(second["visit_end_datetime"], instant(2026, 8, 3, 14, 40, 0))

    response = _book(scenario, patients[2]["id"], instant(2026, 8, 3, 14, 20, 0))

    validate_error(response, ApiErrorId.ERR_CLINICIAN_CAPACITY_EXCEEDED.value, 409)

    _rows, meta = validate_list(
        api_client.list_visits(ADMIN, {"patient_id": patients[2]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused booking must not persist a visit, got {meta['total_count']}"
    )


def test_a_visit_starting_exactly_when_another_ends_does_not_overlap_it():
    """The visit interval is half-open and no buffer pads it.

    PRD §3.2: "The interval a visit occupies runs from its `visit_datetime` up to
    but not including its `visit_end_datetime`, and no buffer of any kind pads
    it, so a visit that begins at the exact instant another one ends does not
    overlap it."

    Design: Difficulty/resource_temporal_overlap/clinician_concurrent_visit_cap_uses_half_open_zero_buffer_intervals
    """
    scenario, patients, _first, _second = _clinician_book()

    booked = get_success_data(
        _book(scenario, patients[3]["id"], instant(2026, 8, 3, 14, 40, 0)), 201
    )

    assert_visit(booked)
    assert_instant_equals(booked["visit_datetime"], instant(2026, 8, 3, 14, 40, 0))
    assert_instant_equals(booked["visit_end_datetime"], instant(2026, 8, 3, 15, 10, 0))
    assert booked["status"] == "SCHEDULED"

    _rows, meta = validate_list(
        api_client.list_visits(ADMIN, {"clinician_id": scenario.rheumatologist_id})
    )
    assert meta["total_count"] == 3, (
        f"the clinician must hold the two seed visits plus this one, got {meta['total_count']}"
    )


def test_the_cap_counts_only_visits_the_interval_actually_overlaps():
    """14:20 is refused while 14:40 is accepted against the same two bookings.

    PRD §3.2: "Every persisted visit of that clinician counts toward the check
    regardless of its own `status` — scheduled, checked in and scored visits are
    all real bookings."

    Design: Difficulty/resource_temporal_overlap/clinician_concurrent_visit_cap_uses_half_open_zero_buffer_intervals
    """
    scenario, patients, _first, _second = _clinician_book()

    refused = _book(scenario, patients[2]["id"], instant(2026, 8, 3, 14, 20, 0))
    validate_error(refused, ApiErrorId.ERR_CLINICIAN_CAPACITY_EXCEEDED.value, 409)

    accepted = get_success_data(
        _book(scenario, patients[3]["id"], instant(2026, 8, 3, 14, 40, 0)), 201
    )
    assert accepted["status"] == "SCHEDULED"

    _rows, meta = validate_list(
        api_client.list_visits(ADMIN, {"clinician_id": scenario.rheumatologist_id})
    )
    assert meta["total_count"] == 3
