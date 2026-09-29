"""Consistency corners: every derived figure and ledger already correct in the
body of the write that caused it, and a screening cascade whose four aggregates are
all readable immediately afterwards with the logical clock frozen.
"""

from test_helpers import (
    assert_list_count,
    assert_same_instant,
    assert_settlement_row,
    assert_state_pair,
    make_guest_headers,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_CONSENT_VERSION
from test_helpers import factories as f
from test_helpers import fixtures as fx

FROZEN_CLOCK = "2026-08-09T09:00:00.000Z"
SERVICE_START_AT = "2026-08-09T11:00:00.000Z"
SERVICE_END_AT = "2026-08-09T12:00:00.000Z"
ARRIVAL_CLOCK = "2026-08-09T11:00:00.000Z"
SHIFT_BLOCK = {"start_at": SERVICE_START_AT, "end_at": "2026-08-09T18:00:00.000Z"}

DRY60_TYPE = {
    "code": "DRY60",
    "name": "Signature Dry Massage",
    "duration_minutes": 60,
    "room_class_required": "DRY",
    "required_skill_code": "SWEDISH",
    "required_scope_level": "BASIC",
    "base_price_cents": 18000,
    "retail_product_line": "BODY",
    "contraindication_codes": None,
    "high_demand": None,
}
DRY_ROOM = {"room_class": "DRY", "turnover_buffer_minutes": 15,
            "hourly_fixed_cost_cents": 2500}
SWEDISH_BASIC = {"skill_code": "SWEDISH", "scope_level": "BASIC"}

SCHEDULED_MINUTES = 60
ROOM_COMMITTED_MINUTES = 75              # 60 scheduled + 15 turnover
GOLD_QUOTE_CENTS = 16200                 # 18000 - round_half_up(18000 * 1000 / 10000)
GOLD_SERVICE_CHARGE_CENTS = 2916         # round_half_up(16200 * 1800 / 10000)
GOLD_FOLIO_TOTAL_CENTS = 19116           # 16200 + 0 + 2916 + 0

IMMEDIATE_FIELDS = ("end_at", "scheduled_duration_minutes", "high_demand_slot",
                    "assignment_mode", "schedule_status", "clearance_status",
                    "clearance_block_reason", "quoted_price_cents",
                    "realized_price_cents", "gratuity_cents",
                    "cancellation_charge_cents", "version")


def _frozen_world(guest_overrides, therapist_name="Consistency Therapist"):
    return fx.build_world(
        room_codes=("DRY-1",),
        therapist_names=(therapist_name,),
        clock=FROZEN_CLOCK,
        treatment_type_overrides=DRY60_TYPE,
        room_overrides=DRY_ROOM,
        certification_overrides=SWEDISH_BASIC,
        guest_overrides=guest_overrides,
        shift_block_overrides=SHIFT_BLOCK)


# ---------------------------------------------------------------------------
# computed_fields_and_ledgers_are_visible_in_the_writing_response
# ---------------------------------------------------------------------------

def test_the_booking_response_already_carries_every_derived_field_and_ledger():
    """The create response, an immediately following read and both minute ledgers
    agree with no clock movement in between.

    PRD §3.5: "Several fields are derived at that moment and never recomputed
    afterwards. `scheduled_duration_minutes` is a snapshot of the treatment type's
    `duration_minutes` taken at creation, so a later edit to the menu cannot move an
    existing booking. `end_at` is `start_at` advanced by
    `scheduled_duration_minutes`."

    PRD §3.5: "`high_demand_slot` is true when either the treatment type's
    `high_demand` flag is true or the UTC hour of `start_at` is at least 16 and less
    than 20 — the four-hour late-afternoon peak — and false otherwise."

    PRD §3.5: "Booking an appointment finally adds `scheduled_duration_minutes` plus
    the room's `turnover_buffer_minutes` to that room's `booked_minutes_total` and
    adds `scheduled_duration_minutes` to the therapist's `assigned_minutes_total`,
    each increment bumping that row's own `version` by 1."

    PRD §3.5: "The loyalty discount and the price floor close the quote. The raw
    discount is the subtotal multiplied by the loyalty rate and divided by ten
    thousand, rounded half up, where the loyalty rate is 0 basis points for `NONE`,
    500 for `SILVER`, 1,000 for `GOLD` and 1,500 for `PLATINUM`"

    Design: Corner/consistency_model/computed_fields_and_ledgers_are_visible_in_the_writing_response
    """
    world = _frozen_world({"full_name": "Immediate Consistency Guest",
                           "resort_room_number": "3201",
                           "loyalty_tier": "GOLD"})

    booked = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, SERVICE_START_AT,
                              world.therapist_id), fx.COORDINATOR), 201)

    assert_same_instant(booked["end_at"], SERVICE_END_AT, "end_at")
    assert booked["scheduled_duration_minutes"] == SCHEDULED_MINUTES
    assert booked["high_demand_slot"] is False, (
        "11:00 UTC is outside the 16:00-to-20:00 peak and `high_demand` is false")
    assert booked["assignment_mode"] == "EXPLICIT", (
        "therapist_id was supplied, so the assignment is not AUTO")
    assert_state_pair(booked, "REQUESTED", "PENDING")
    assert booked["quoted_price_cents"] == GOLD_QUOTE_CENTS, (
        "the GOLD rate of 1,000 basis points off an unsurcharged DRY quote")

    read_back = validate_success(
        api_client.get_appointment(booked["id"], fx.COORDINATOR))
    for field in IMMEDIATE_FIELDS:
        assert read_back[field] == booked[field], (
            f"{field} differs between the create response and the immediate read: "
            f"{booked[field]!r} then {read_back[field]!r}")

    assert world.fetch_room()["booked_minutes_total"] == ROOM_COMMITTED_MINUTES, (
        "the room ledger was committed by the create that just returned")
    assert world.fetch_therapist()["assigned_minutes_total"] == SCHEDULED_MINUTES, (
        "the therapist ledger excludes turnover and is already committed")


def test_the_check_in_response_is_followed_by_an_already_consistent_folio():
    """The provisional row, the guest balance and both folio channels all agree the
    instant check-in returns, with the clock never moving afterwards.

    PRD §3.6: "It cuts a settlement row using the provisional variant of the
    distribution calculation, with `variant` `PROVISIONAL` and `status`
    `PROVISIONAL`, filling every computed money field on that row; the appointment
    must not already have a settlement row for this to happen."

    PRD §3.6: "It then posts a folio charge of `kind` `TREATMENT` whose
    `amount_cents` is that row's `folio_total_cents`, recomputes the guest's
    `folio_balance_cents` as the exact sum of the guest's postings and increments the
    guest's `version` by 1."

    PRD §3.9: "Under the provisional variant, `basis_duration_minutes` is the
    appointment's `scheduled_duration_minutes` and `realized_price_cents` is exactly
    the frozen `quoted_price_cents` — there is no overtime charge, no shortfall
    credit, and `gratuity_cents` on the row is 0 because a gratuity is only captured
    at completion."

    Design: Corner/consistency_model/computed_fields_and_ledgers_are_visible_in_the_writing_response
    """
    world = _frozen_world({"full_name": "Immediate Consistency Guest",
                           "resort_room_number": "3201",
                           "loyalty_tier": "GOLD"})
    booked = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, SERVICE_START_AT,
                              world.therapist_id), fx.COORDINATOR), 201)
    appointment_id = booked["id"]
    fx.confirm(appointment_id)
    fx.set_clock(ARRIVAL_CLOCK)
    checked_in = fx.check_in(appointment_id)
    assert_state_pair(checked_in, "CHECKED_IN", "CLEARED")

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == GOLD_FOLIO_TOTAL_CENTS, (
        "the balance is the recomputed sum of the postings, not a lazy total")

    rows = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "the provisional row cut at check-in")
    assert_settlement_row(rows[0], {
        "variant": "PROVISIONAL",
        "status": "PROVISIONAL",
        "basis_duration_minutes": SCHEDULED_MINUTES,
        "realized_price_cents": GOLD_QUOTE_CENTS,
        "gratuity_cents": 0,
        "service_charge_pool_cents": GOLD_SERVICE_CHARGE_CENTS,
        "folio_total_cents": GOLD_FOLIO_TOTAL_CENTS,
    }, "provisional row")

    for label, response in (
            ("the appointment-scoped channel",
             api_client.list_appointment_folio_charges(appointment_id,
                                                      fx.COORDINATOR)),
            ("the guest-scoped channel",
             api_client.list_guest_folio_charges(world.guest_id,
                                                fx.COORDINATOR))):
        postings = assert_list_count(response, 1, label)
        assert postings[0]["kind"] == "TREATMENT", label
        assert postings[0]["amount_cents"] == GOLD_FOLIO_TOTAL_CENTS, label
        assert_same_instant(postings[0]["posted_at"], ARRIVAL_CLOCK,
                            f"{label} posted_at")


# ---------------------------------------------------------------------------
# cascade_results_are_readable_immediately_with_no_lag
# ---------------------------------------------------------------------------

FLAGGED_CODE = "ACUTE_HYPERTENSION"
DECLARED_MEDICATION = "LISINOPRIL"


def test_the_screening_cascade_is_visible_in_all_four_aggregates_with_no_lag():
    """One screening call moves the new form, the old form, the guest's computed
    pointer and the appointment's clearance dimension, and every one of them is
    already visible while the clock stands still.

    PRD §3.4: "Both screening outcomes rewrite `authoritative_intake_form_id` to the
    freshly screened form and copy that form's full `condition_codes` — not merely
    the flagged subset — into the guest's `screened_condition_codes`, which is the
    input set every contraindication check reads. The guest's previous authoritative
    form, when there was one, transitions to `SUPERSEDED`, a terminal state with no
    way out."

    PRD §3.4: "A `SCREENED_FLAGGED` result runs the block cascade: because the
    guest's authoritative form is now flagged, every appointment of that guest whose
    `schedule_status` is `REQUESTED`, `CONFIRMED` or `CHECKED_IN` has its
    `clearance_status` driven to `BLOCKED` with `clearance_block_reason`
    `INTAKE_FLAGGED`, processed in ascending `start_at` order with ties broken by
    ascending `created_at`, and because those appointments became blocked, every
    retail attachment on them still in `RECOMMENDED` becomes `EXPIRED`."

    PRD §2.10: "They advance independently: an appointment may legitimately sit at
    `CONFIRMED` with `BLOCKED` clearance, at `CONFIRMED` with `CLEARED` clearance, or
    at `CHECKED_IN` with `BLOCKED` clearance, and it is the **pair** that decides
    which transitions are legal."

    Design: Corner/consistency_model/cascade_results_are_readable_immediately_with_no_lag
    """
    world = _frozen_world({"full_name": "Cascade Read Guest",
                           "resort_room_number": "3301"},
                          therapist_name="Cascade Read Therapist")
    first_form = world.intake
    booked = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                 world.room_id, SERVICE_START_AT,
                                 world.therapist_id)
    appointment_id = fx.confirm(booked["id"])["id"]
    guest_headers = make_guest_headers(world.guest_id)
    version_before = validate_success(
        api_client.get_guest(world.guest_id, fx.COORDINATOR))["version"]

    second_form = validate_success(api_client.create_intake_form(
        world.guest_id,
        f.intake_form_payload(version_before, condition_codes=[FLAGGED_CODE],
                              medications=[DECLARED_MEDICATION]),
        guest_headers), 201)
    validate_success(api_client.sign_consent(
        second_form["id"], f.consent_payload(CANON_CONSENT_VERSION),
        guest_headers))
    validate_success(api_client.submit_intake_form(
        second_form["id"], {}, guest_headers))

    screened = validate_success(api_client.screen_intake_form(
        second_form["id"], {}, fx.COMPLIANCE))
    assert screened["status"] == "SCREENED_FLAGGED"
    assert screened["flagged_condition_codes"] == [FLAGGED_CODE]
    assert screened["screened_by_user_id"] == fx.CO_SUBMIT
    assert_same_instant(screened["screened_at"], FROZEN_CLOCK, "screened_at")

    guest = validate_success(api_client.get_guest(world.guest_id, fx.COORDINATOR))
    assert guest["authoritative_intake_form_id"] == second_form["id"], (
        "the freshly screened form is authoritative on the very next read")
    assert guest["screened_condition_codes"] == [FLAGGED_CODE]
    assert guest["version"] == version_before + 2, (
        "the second form's creation and its screening each bumped the guest")

    assert validate_success(api_client.get_intake_form(
        first_form["id"], fx.COORDINATOR))["status"] == "SUPERSEDED", (
        "the displacement of the previous authoritative form is not deferred")

    blocked = validate_success(
        api_client.get_appointment(appointment_id, fx.COORDINATOR))
    assert_state_pair(blocked, "CONFIRMED", "BLOCKED", "INTAKE_FLAGGED")

    listed = assert_list_count(api_client.list_appointments(
        fx.COORDINATOR, {"guest_id": world.guest_id,
                         "clearance_status": "BLOCKED"}), 1,
        "the blocked appointments of this guest")
    assert [row["id"] for row in listed] == [appointment_id], (
        "the list channel sees the cascade with no lag")

    superseded = assert_list_count(api_client.list_intake_forms(
        world.guest_id, fx.COMPLIANCE, {"status": "SUPERSEDED"}), 1,
        "the superseded forms of this guest")
    assert [row["id"] for row in superseded] == [first_form["id"]]
