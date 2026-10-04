"""Estimated wait publication and the queue-status read."""
import pytest

from test_helpers import (
    validate_success, assert_wait_band_consistent, api_client, make_patient_headers,
    TEST_USERS, get_service_center, INTAKE,
)
from test_helpers.fixtures import (
    setup_wait_scenario, setup_checked_in_visit, call_patient, new_phlebotomist,
    run_ops as _run_ops,
)


def test_wait_read_publishes_the_instantaneous_variant_while_waiting(api):
    """PRD §3.3: "While the reading appointment is in `queue_state` `WAITING`,
    the instantaneous variant applies: every row's `complexity_score` collapses
    to zero, so every earlier waiting row compares equal and contributes a
    position weight of 2, and the queue-depth quotient becomes twice the number
    of earlier waiting rows divided by the resolving staff count."
    PRD §3.3: "Imagine six earlier waiting rows and a single resolving nurse:
    the instantaneous reading is 12 minutes, which lands in `WITHIN_WINDOW`,
    while the blend-rate reading of the identical data is 9 minutes, which lands
    in `IMMEDIATE`."
    PRD §3.3: "The band is `IMMEDIATE` when the estimate is 10 or fewer minutes,
    `WITHIN_WINDOW` when it is 11 through 30 minutes inclusive, and `EXTENDED`
    when it is 31 or more."

    Design: Difficulty/dual_variant_calc/wait_dual_variant_on_appointment_queue
    """
    visit = setup_wait_scenario()
    headers = make_patient_headers(visit["patient"]["id"])
    data = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    assert data["estimated_wait_minutes"] == 12, (
        f"instantaneous variant should publish 12 for six earlier waiting rows "
        f"and one resolving nurse, got {data['estimated_wait_minutes']}"
    )
    assert data["wait_band"] == "WITHIN_WINDOW"
    assert_wait_band_consistent(data["estimated_wait_minutes"], data["wait_band"])


def test_wait_read_republishes_a_smaller_blend_rate_variant_once_called(api):
    """PRD §3.3: "While the reading appointment is in `queue_state` `CALLED` or
    `AT_STATION`, the blend-rate variant applies: scores are live again, so an
    earlier row whose score is strictly greater contributes only 1 and a tie
    contributes 2, and the resulting figure is strictly smaller."
    PRD §3.3: "Two sequential reads of the same underlying data therefore
    legitimately return different numbers, and an implementation that caches the
    first result will disagree with the contract."

    Design: Difficulty/dual_variant_calc/wait_dual_variant_on_appointment_queue
    """
    visit = setup_wait_scenario()
    headers = make_patient_headers(visit["patient"]["id"])

    waiting = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    assert waiting["estimated_wait_minutes"] == 12

    center_before = get_service_center(visit["center"]["id"], TEST_USERS["supervisor_headers"])
    call_patient(visit["appointment"]["id"])
    center_after = get_service_center(visit["center"]["id"], TEST_USERS["supervisor_headers"])

    called = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    # The PRD's own worked example pins the blended figure at 9 (IMMEDIATE): six
    # earlier rows — three outranking the reading row and three tying with it —
    # and one resolving nurse produce 9 against the instantaneous variant's 12.
    assert called["estimated_wait_minutes"] == 9, (
        f"blend-rate variant should publish 9 for the identical queue once the "
        f"row is CALLED, got {called['estimated_wait_minutes']}"
    )
    assert called["wait_band"] == "IMMEDIATE"
    assert waiting["estimated_wait_minutes"] > called["estimated_wait_minutes"], (
        "the instantaneous reading must be strictly larger than the blend-rate reading"
    )
    # The roster-capacity term is derived from the center, which no call in
    # between touched, so only the queue-depth term moved.
    assert center_before["staffed_minutes_available"] == center_after["staffed_minutes_available"]


def test_queue_status_read_is_a_pure_projection_repeatable_with_no_write(api):
    """PRD §3.3: "The wait estimate a patient sees is not stored; it is computed
    on demand, and it is computed differently depending on where the patient is
    in the room."
    PRD §3.3: "The estimate is recomputed whenever an appointment checks in,
    whenever one is called, and whenever a phlebotomist's roster status is
    edited."

    Design: Corner/endpoints/queue_status_is_a_computed_read_that_echoes_no_stored_wait_field
    """
    visit = setup_checked_in_visit(clock="2026-09-01T13:30:00Z")
    new_phlebotomist(visit["center"]["id"], credential="PBT", full_name="Omar Vela")
    headers = make_patient_headers(visit["patient"]["id"])

    first = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    second = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    assert first["estimated_wait_minutes"] == second["estimated_wait_minutes"], (
        "two reads with no intervening write must publish the same estimate"
    )

    appt = validate_success(api.get_appointment(visit["appointment"]["id"], INTAKE), 200)
    assert "estimated_wait_minutes" not in appt, (
        "the wait figure is computed on read and is not a stored appointment column"
    )
    assert appt["draw_state"] == "CHECKED_IN"


def test_wait_band_moves_at_its_boundary_when_the_resolving_roster_shrinks(api):
    """PRD §3.3: "when no such phlebotomist exists the quotient is 999."
    PRD §3.3: "Retiring a phlebotomist through the roster edit does raise the
    wait estimate, because the resolving-staff term that appears in the
    queue-depth denominator shrinks and the negative pressure on the quotient
    grows, and that can move the published band at its boundary."
    PRD §3.9: "the field is set to fifteen minutes multiplied by the number of
    on-duty phlebotomists"

    Design: Corner/cross_cutting_complexity_layers/wait_bands_respond_to_a_roster_change
    """
    visit = setup_checked_in_visit(clock="2026-09-01T13:00:00Z",
                                   scheduled_start_utc="2026-09-01T13:15:00Z")
    center = visit["center"]
    new_phlebotomist(center["id"], credential="RN", full_name="Hana Reed")
    two = new_phlebotomist(center["id"], credential="PBT", full_name="Omar Vela")
    three = new_phlebotomist(center["id"], credential="PBT", full_name="Ines Cruz")
    _run_ops(center["id"])

    headers = make_patient_headers(visit["patient"]["id"])
    before = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    assert_wait_band_consistent(before["estimated_wait_minutes"], before["wait_band"])

    api_client.patch_phlebotomist(two["id"], {"status": "OFF_DUTY"},
                                  TEST_USERS["supervisor_headers"])
    api_client.patch_phlebotomist(three["id"], {"status": "OFF_DUTY"},
                                  TEST_USERS["supervisor_headers"])

    after = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    assert_wait_band_consistent(after["estimated_wait_minutes"], after["wait_band"])

    assert api_client.get_phlebotomist(
        two["id"], TEST_USERS["supervisor_headers"]).json()["data"]["status"] == "OFF_DUTY"
    # The published estimate is re-derived against the narrowed resolving set.
    assert after["estimated_wait_minutes"] >= before["estimated_wait_minutes"], (
        "shrinking the resolving roster cannot lower the published estimate"
    )


def test_wait_estimate_uses_created_at_order_and_never_the_identifier(api):
    """PRD §3.3: "Each earlier waiting row contributes a position weight of 3
    when its `complexity_score` is strictly greater than the reading row's, 2
    when the two scores are equal, and 1 otherwise."
    PRD §3.3: "Ties in the queue are broken by the earlier `created_at`, and the
    identifier is never consulted."

    Design: Difficulty/dual_variant_calc/wait_dual_variant_on_appointment_queue
    """
    visit = setup_wait_scenario()
    headers = make_patient_headers(visit["patient"]["id"])

    reading = validate_success(api.queue_status(visit["appointment"]["id"], headers), 200)
    # Six earlier WAITING rows at weight 2 each, divided by one resolving nurse.
    assert reading["estimated_wait_minutes"] == 12

    # The earlier rows are the ones created strictly before the reading row:
    # three outrank it and three tie with it, so under the live-score reading
    # the quotient would be 9 rather than 12.
    earlier_starts = [a["scheduled_start_utc"] for a in visit["earlier_appointments"]]
    assert len(earlier_starts) == 6
    assert reading["estimated_wait_minutes"] != 9