"""Appointments: the parallel state dimensions, check-in, holds, and attempt limits."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, make_patient_headers, make_phlebotomist_headers,
    assert_version_incremented,
)
from test_helpers.fixtures import (
    setup_checked_in_visit, setup_staff_pending_visit, setup_eligible_order,
    setup_collected_order_with_specimen, setup_windowed_visit, new_phlebotomist,
    new_patient, new_order, resolve_insurance, book, check_in, call_patient,
    get_order, get_appointment, set_clock, run_ops,
)


def test_a_pediatric_visit_without_a_resolving_credential_enters_staff_pending(api):
    """PRD §3.3: "If no phlebotomist at the center holds a credential sufficient
    for the mode — the pediatric set is `PBT_PEDIATRIC` and `RN`, and the
    difficult-draw set is `RN` alone — the visit does not silently stall at the
    desk. It moves automatically from `CHECKED_IN` to `STAFF_PENDING`."
    PRD §2.6: "Staff credential sufficiency runs fourth: if no phlebotomist on
    duty at the center holds a credential that covers the order's
    `collection_mode`, the operation is rejected with
    `ERR_STAFF_CREDENTIAL_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/appointment_runs_two_parallel_dimensions_with_hold_expiry
    """
    visit = setup_staff_pending_visit()
    response = api_client.call_appointment(visit["appointment"]["id"], INTAKE)
    validate_error(response, ApiErrorId.ERR_STAFF_CREDENTIAL_INSUFFICIENT.value)

    appointment = get_appointment(visit["appointment"]["id"])
    assert appointment["draw_state"] == "STAFF_PENDING"
    assert appointment["queue_state"] == "WAITING", (
        "the draw dimension moved while the queue dimension stayed put"
    )
    assert appointment["station_index"] == -1
    assert appointment["phlebotomist_id"] is None


def test_the_staff_pending_hold_expiry_is_a_derived_read_not_a_transition(api):
    """PRD §2.5: "a hold has expired exactly when the appointment is in
    `STAFF_PENDING` and the logical clock is strictly past the hold's expiry
    instant, and that expiry is a derived read that never by itself moves the
    appointment out of `STAFF_PENDING`."
    PRD §3.9: "an appointment in `STAFF_PENDING` whose hold expiry has passed has
    its derived `draw_hold_expired` flag reported as true, but the underlying
    `draw_state` is not auto-transitioned"

    Design: Corner/cross_cutting_complexity_layers/a_staff_pending_hold_expires_by_derived_read_and_never_auto_transitions
    """
    visit = setup_staff_pending_visit()
    api_client.call_appointment(visit["appointment"]["id"], INTAKE)
    appointment = get_appointment(visit["appointment"]["id"])
    assert appointment["draw_state"] == "STAFF_PENDING"
    assert appointment["draw_hold_expires_utc"] == "2026-09-01T14:00:00.000Z"
    assert appointment["draw_hold_expired"] is False

    set_clock("2026-09-01T14:01:00Z")
    run_ops(visit["center"]["id"])

    after = get_appointment(visit["appointment"]["id"])
    assert after["draw_hold_expired"] is True, "the clock alone must expire the hold"
    assert after["draw_state"] == "STAFF_PENDING", (
        "the expiry is a derived read and must not auto-transition the row"
    )
    assert after["draw_hold_expires_utc"] == "2026-09-01T14:00:00.000Z"


def test_check_in_accepts_the_exact_upper_edge_of_its_window(api):
    """PRD §3.3: "it is time-boxed: the logical clock must fall within the window
    that opens 30 minutes before `scheduled_start_utc` and closes 15 minutes
    after it. Those two bounds are `EARLY_CHECKIN_MINUTES` (30) and
    `GRACE_MINUTES` (15)."
    PRD §2.5: "When a rule says an instant falls inside a window, the lower edge
    is inclusive and the upper edge is not, unless the prose says otherwise for
    that specific rule."

    Design: Corner/validations/check_in_outside_the_window_returns_a_temporal_rejection
    """
    visit = setup_eligible_order(clock="2026-09-01T13:00:00Z")
    appointment = book(visit["center"]["id"], visit["order"]["id"], "2026-09-01T13:15:00Z")

    set_clock("2026-09-01T13:30:00Z")
    checked_in = validate_success(
        api_client.check_in(appointment["id"], make_patient_headers(visit["patient"]["id"])),
        200)
    assert checked_in["draw_state"] == "CHECKED_IN", (
        "the exact upper edge of the check-in window is still inside it"
    )
    assert checked_in["checkin_utc"] == "2026-09-01T13:30:00.000Z"


def test_check_in_past_the_window_is_rejected_and_leaves_the_visit_scheduled(api):
    """PRD §3.3: "Arriving earlier than the opening edge is rejected just as
    arriving past the closing edge is."
    PRD §2.11: "**Clinical safety.** The safety ladder of §2.6, evaluated in its
    fixed sub-order, with the first failing sub-check winning."

    Design: Corner/validations/check_in_outside_the_window_returns_a_temporal_rejection
    """
    visit = setup_eligible_order(clock="2026-09-01T13:30:00Z")
    appointment = book(visit["center"]["id"], visit["order"]["id"], "2026-09-01T14:00:00Z")

    set_clock("2026-09-01T14:16:00Z")
    response = api_client.check_in(
        appointment["id"], make_patient_headers(visit["patient"]["id"]))
    assert response.status_code >= 400, "one minute past the window must be refused"
    assert response.json()["response_type"] == "error"

    after = get_appointment(appointment["id"])
    assert after["draw_state"] == "SCHEDULED"
    assert after["checkin_utc"] is None


def test_check_in_is_not_idempotent_and_preserves_the_first_instant(api):
    """PRD §2.11: "A second, strictly sequential identical request observes the
    state written by the first and is rejected here."
    PRD §3.3: "A successful check-in moves `draw_state` from `SCHEDULED` to
    `CHECKED_IN`, moves `queue_state` from `NONE` to `WAITING`, and stamps
    `checkin_utc` with the logical clock."

    Design: Corner/state_machines/second_check_in_on_an_already_checked_in_appointment_is_rejected
    """
    visit = setup_eligible_order(clock="2026-09-01T13:30:00Z")
    appointment = book(visit["center"]["id"], visit["order"]["id"], "2026-09-01T14:00:00Z")
    headers = make_patient_headers(visit["patient"]["id"])
    first = validate_success(api_client.check_in(appointment["id"], headers), 200)
    checkin_at = first["checkin_utc"]

    response = api_client.check_in(appointment["id"], headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_appointment(appointment["id"])
    assert after["checkin_utc"] == checkin_at, "the second call must not restamp check-in"
    assert after["version"] == first["version"], "no second version bump survived"


def test_a_patient_can_check_in_their_own_appointment(api):
    """PRD §2.1: "When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the
    acting `Patient`, and the server enforces that a patient acts only on their
    own appointment by comparing `X-User-ID` to that appointment's linked
    `TestOrder.patient_id`."
    PRD §3.3: "Check-in is available to the `Patient` acting on their own visit
    and to an `IntakeCoordinator` acting at the desk."

    Design: Corner/rbac/a_patient_can_check_in_their_own_appointment
    """
    visit = setup_eligible_order(clock="2026-09-01T13:30:00Z")
    appointment = book(visit["center"]["id"], visit["order"]["id"], "2026-09-01T14:00:00Z")

    checked_in = validate_success(
        api_client.check_in(appointment["id"], make_patient_headers(visit["patient"]["id"])),
        200)
    assert checked_in["draw_state"] == "CHECKED_IN"
    assert checked_in["queue_state"] == "WAITING"
    assert checked_in["checkin_utc"] == "2026-09-01T13:30:00.000Z"


def test_finish_draw_from_a_waiting_queue_is_rejected(api):
    """PRD §3.4: "Finishing a draw is also the phlebotomist's operation, and it
    is accepted only while `queue_state` is still `AT_STATION`."
    PRD §2.11: "**State.** The target resource must be in a state that permits
    the operation."

    Design: Corner/state_machines/finish_draw_from_a_waiting_queue_returns_invalid_state
    """
    visit = setup_checked_in_visit(clock="2026-09-01T13:30:00Z")
    phleb = new_phlebotomist(visit["center"]["id"], credential="RN")

    response = api_client.finish_draw(visit["appointment"]["id"],
                                      make_phlebotomist_headers(phleb["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_appointment(visit["appointment"]["id"])
    assert after["draw_state"] == "CHECKED_IN"
    assert after["queue_state"] == "WAITING"


def test_booking_ignores_client_supplied_draw_state_and_version(api):
    """PRD §3.3: "Two request fields exist purely for shape compatibility and are
    always ignored. A client may send a `draw_state` and a `version` on creation,
    but both are server-owned, and the server discards whatever the client
    supplied."
    PRD §3.3: "A newly created booking lands in `draw_state` `SCHEDULED` and
    `queue_state` `NONE`."

    Design: Corner/entities/appointment_create_ignores_client_supplied_draw_state_and_version
    """
    visit = setup_eligible_order()
    appointment = validate_success(api_client.create_appointment({
        "service_center_id": visit["center"]["id"],
        "test_order_id": visit["order"]["id"],
        "scheduled_start_utc": "2026-09-01T14:00:00Z",
        "slot_span": 1,
        "source": "BOOKED",
        "expected_test_order_version": visit["order"]["version"],
        "draw_state": "DRAWN",
        "version": 99,
    }, INTAKE), 201)

    assert appointment["draw_state"] == "SCHEDULED"
    assert appointment["queue_state"] == "NONE"
    assert appointment["version"] == 1
    assert appointment["attempt_count"] == 0
    assert appointment["phlebotomist_id"] is None


def test_attempt_count_is_append_only_and_blocks_a_premature_reschedule(api):
    """PRD §3.4: "Every appointment carries an `attempt_count`, starting at 0,
    counting draw attempts consumed. The counter is append-only: no correction,
    reschedule, or recollection ever decrements it, and it is capped at
    `ATTEMPTS.max_total`, which is 2."
    PRD §3.4: "It requires `attempt_count` to be at least 2."

    Design: Corner/cross_cutting_complexity_layers/a_second_collection_attempt_accumulates_and_reaches_the_limit
    """
    visit = setup_checked_in_visit(clock="2026-09-01T13:30:00Z")
    before = get_appointment(visit["appointment"]["id"])
    assert before["attempt_count"] == 0

    response = api_client.reschedule_appointment(
        visit["appointment"]["id"], "2026-09-01T15:00:00Z", INTAKE)
    assert response.status_code >= 400, (
        "rescheduling requires the attempt limit to have been reached"
    )

    after = get_appointment(visit["appointment"]["id"])
    assert after["attempt_count"] == 0
    assert after["draw_state"] == "CHECKED_IN"
    assert after["version"] == before["version"]


def test_appointment_mutation_is_visible_in_its_own_response_and_on_reread(api):
    """PRD §3.3: "A successful check-in moves `draw_state` from `SCHEDULED` to
    `CHECKED_IN`, moves `queue_state` from `NONE` to `WAITING`, and stamps
    `checkin_utc` with the logical clock."
    PRD §2.4: "`version` is an integer that begins at 1 and increments by one on
    every mutation."

    Design: Corner/consistency_model/all_appointment_writes_are_visible_in_the_same_response_and_on_an_immediate_reread
    """
    visit = setup_eligible_order(clock="2026-09-01T13:30:00Z")
    appointment = book(visit["center"]["id"], visit["order"]["id"], "2026-09-01T14:00:00Z")
    assert appointment["version"] == 1

    checked_in = validate_success(
        api_client.check_in(appointment["id"], make_patient_headers(visit["patient"]["id"])),
        200)
    assert_version_incremented(checked_in["version"], appointment["version"])

    reread = get_appointment(appointment["id"])
    assert reread["draw_state"] == checked_in["draw_state"] == "CHECKED_IN"
    assert reread["queue_state"] == checked_in["queue_state"] == "WAITING"
    assert reread["checkin_utc"] == checked_in["checkin_utc"]