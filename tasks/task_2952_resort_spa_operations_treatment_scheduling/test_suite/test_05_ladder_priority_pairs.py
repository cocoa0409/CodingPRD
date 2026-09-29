"""Priority pairs on the thirty-four-rung ladder: three doubly-invalid requests
whose reported error must be the higher rung's, each paired with a control call
that proves the lower rung was armed the whole time.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_list_count,
    assert_state_pair,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_START_AT
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _world_without_intake():
    """The canonical menu, room and therapist plus a guest who has never filed an
    intake form, so `authoritative_intake_form_id` is null."""
    world = fx.build_world(with_guest=False)
    world.guest = fx.create_guest()
    return world


def test_unresolvable_body_room_id_outranks_the_missing_intake_clearance():
    """Rung 5 fires before rung 12 on a request that violates both.

    PRD §2.7 rung 5: "**Body reference existence** — every identifier supplied in
    a request body resolves, checked in the body-field order `guest_id`, then
    `treatment_type_id`, then `room_id`, then `therapist_id`."

    PRD §2.7: "The server walks the ladder from the top and returns the error of
    the **first** rung the request violates; lower rungs are not evaluated once a
    rung has failed."

    Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_p5_beats_intake_safety_p12
    """
    world = _world_without_intake()

    response = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              NON_EXISTENT_UUID, CANON_START_AT,
                              world.therapist_id),
        fx.COORDINATOR)
    error = validate_error(response, ApiErrorId.ERR_ROOM_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_INTAKE_NOT_CLEARED.value, (
        "the guest has no screened intake, but rung 5 is reported first")

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the refused booking")
    assert world.fetch_room()["booked_minutes_total"] == 0


def test_resolving_the_room_id_reveals_the_armed_intake_clearance_rung():
    """The identical booking with a real room falls through to rung 12.

    PRD §2.7 rung 12: "**Intake cleared** — the guest has an authoritative intake
    form whose `status` is `SCREENED_CLEAR` or `OVERRIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_p5_beats_intake_safety_p12
    """
    world = _world_without_intake()

    response = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT,
                              world.therapist_id),
        fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_INTAKE_NOT_CLEARED.value, 409)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the refused booking")
    assert world.fetch_room()["booked_minutes_total"] == 0


# ---------------------------------------------------------------------------
# Rung 12 over rung 25
# ---------------------------------------------------------------------------

def _two_therapist_world():
    """Two credentialled therapists, guest 1 holding a REQUESTED 17:00 booking in
    HYDRO-1 (occupancy [17:00, 19:30)), and guest 2 with no intake form."""
    world = fx.build_world(therapist_names=("Leilani Akana", "Malia Cortez"))
    world.appointments["a"] = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_of("Leilani Akana"))
    second_guest = fx.create_guest(full_name="Rory Vance", resort_room_number="0908",
                                   loyalty_tier="GOLD")
    return world, second_guest


def test_missing_intake_clearance_outranks_the_room_turnover_conflict():
    """Rung 12 beats rung 25 across a thirteen-rung gap.

    PRD §2.7: "First, on a booking a clinical rejection always wins over a
    scheduling rejection: a guest with an unscreened intake form receives
    `ERR_INTAKE_NOT_CLEARED` even when the requested slot is also outside the
    therapist's shift window and the lead time is also too short."

    PRD §2.7 rung 25: "**Room turnover** — the room's occupancy interval does not
    overlap the occupancy interval of any other appointment in that room."

    Design: Difficulty/priority_pair_validation_conflict/intake_safety_p12_beats_room_turnover_p25
    """
    world, second_guest = _two_therapist_world()

    response = api_client.create_appointment(
        f.appointment_payload(second_guest["id"], world.treatment_type_id,
                              world.room_id, "2026-08-10T18:00:00.000Z",
                              world.therapist_of("Malia Cortez")),
        fx.COORDINATOR)
    error = validate_error(response, ApiErrorId.ERR_INTAKE_NOT_CLEARED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ROOM_TURNOVER_CONFLICT.value, (
        "[18:00, 20:00) overlaps the existing occupancy [17:00, 19:30) in the "
        "same room, yet the clinical rung is reported")

    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "only guest 1's booking ever committed minutes")
    assert_list_count(
        api_client.list_appointments(fx.COORDINATOR,
                                     params={"room_id": world.room_id}),
        1, "appointments in HYDRO-1")


def test_clearing_the_second_guest_reveals_the_armed_turnover_rung():
    """With the safety rung satisfied the same slot fails on room turnover.

    PRD §3.5: "The room has its own, deliberately different geometry: a room's
    occupancy interval begins at the appointment's `start_at` and runs up to but
    not including its `end_at` advanced by that room's `turnover_buffer_minutes`,
    and the new occupancy may not overlap the occupancy interval of any
    appointment in that room that is non-terminal or `COMPLETED`."

    PRD §2.7 rung 25: "**Room turnover** — the room's occupancy interval does not
    overlap the occupancy interval of any other appointment in that room."

    Design: Difficulty/priority_pair_validation_conflict/intake_safety_p12_beats_room_turnover_p25
    """
    world, second_guest = _two_therapist_world()
    screened = fx.screened_intake(second_guest["id"], second_guest["version"])
    assert screened["status"] == "SCREENED_CLEAR"

    response = api_client.create_appointment(
        f.appointment_payload(second_guest["id"], world.treatment_type_id,
                              world.room_id, "2026-08-10T18:00:00.000Z",
                              world.therapist_of("Malia Cortez")),
        fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_ROOM_TURNOVER_CONFLICT.value, 409)

    assert world.fetch_room()["booked_minutes_total"] == 120
    assert_list_count(
        api_client.list_appointments(fx.COORDINATOR,
                                     params={"room_id": world.room_id}),
        1, "appointments in HYDRO-1")


# ---------------------------------------------------------------------------
# Rung 10 over rung 30
# ---------------------------------------------------------------------------

def _thin_folio_world():
    """A CONFIRMED appointment whose guest's folio limit (40000) cannot absorb the
    50504c treatment charge, with the room taken out of service so the clearance
    dimension is BLOCKED for ROOM_UNAVAILABLE."""
    world = fx.world_with_confirmed_appointment(
        guest_overrides={"folio_limit_cents": 40000})
    fx.set_room_status(world.room_id, "MAINTENANCE")
    fx.set_clock(CANON_START_AT)
    return world


def test_blocked_clearance_outranks_the_exhausted_folio_limit():
    """Rung 10 fires on check-in before the fiscal rung is reached.

    PRD §2.7 rung 10: "**Clearance state** — the appointment's `clearance_status`
    is `CLEARED` for check-in and for service start, and is `BLOCKED` for the
    checked-in abort path of cancellation."

    PRD §2.10: "When one or more fail, clearance is `BLOCKED` and
    `clearance_block_reason` is set from the **first** failing clause in that
    order — `INTAKE_FLAGGED`, then `LICENSE_INVALID`, then `THERAPIST_SUSPENDED`,
    then `ROOM_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/clearance_state_p10_beats_folio_fiscal_p30
    """
    world = _thin_folio_world()
    appointment_id = world.appointments["a"]["id"]
    assert_state_pair(world.fetch_appointment(appointment_id),
                      "CONFIRMED", "BLOCKED", "ROOM_UNAVAILABLE")

    response = api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR)
    error = validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_CLEARED.value,
                           409)
    assert error["error_id"] != ApiErrorId.ERR_FOLIO_LIMIT_EXCEEDED.value, (
        "0 + 50504 exceeds the 40000c folio limit, yet the clearance rung wins")

    assert world.fetch_appointment(appointment_id)["schedule_status"] == "CONFIRMED"
    assert_list_count(api_client.list_settlements(appointment_id, fx.DIRECTOR), 0,
                      "settlement rows")
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings")
    assert world.fetch_guest()["folio_balance_cents"] == 0


def test_reactivating_the_room_reveals_the_armed_folio_capacity_rung():
    """Reclearing the appointment exposes rung 30 with a 402.

    PRD §2.7 rung 30: "**Folio capacity** — the guest's `folio_balance_cents` plus
    the amount about to post does not exceed the guest's `folio_limit_cents`."

    PRD §2.10: "Four kinds of event can drive it back to `CLEARED`: a director
    override of the flagged form, a fresh screening that comes back clear, a
    therapist reinstatement, and a room moved back to `ACTIVE` — in each case only
    when all four clauses hold again."

    Design: Difficulty/priority_pair_validation_conflict/clearance_state_p10_beats_folio_fiscal_p30
    """
    world = _thin_folio_world()
    appointment_id = world.appointments["a"]["id"]
    validate_error(
        api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR),
        ApiErrorId.ERR_APPOINTMENT_NOT_CLEARED.value, 409)

    room = validate_success(api_client.patch_treatment_room(
        world.room_id, f.room_status_payload("ACTIVE"), fx.DIRECTOR))
    assert room["status"] == "ACTIVE"
    assert_state_pair(world.fetch_appointment(appointment_id),
                      "CONFIRMED", "CLEARED", None)

    response = api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_FOLIO_LIMIT_EXCEEDED.value, 402)

    assert world.fetch_appointment(appointment_id)["schedule_status"] == "CONFIRMED"
    assert_list_count(api_client.list_settlements(appointment_id, fx.DIRECTOR), 0,
                      "settlement rows")
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings")
    assert world.fetch_guest()["folio_balance_cents"] == 0
