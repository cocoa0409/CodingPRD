"""Cross-cutting layers: both optimistic-concurrency guards refusing a version
that was invalidated by writes the client never issued, and the cumulative
late-cancellation threshold that only bites on the second strike.
"""

from test_helpers import (
    ApiErrorId,
    assert_folio_contents,
    assert_ledgers,
    assert_list_count,
    assert_pool_conserved,
    assert_settlement_row,
    assert_state_pair,
    make_guest_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers import factories as f
from test_helpers import fixtures as fx

OCC_CLOCK = "2026-08-01T09:00:00.000Z"
SERVICE_CLOCK = "2026-08-09T09:00:00.000Z"
SERVICE_START_AT = "2026-08-09T11:00:00.000Z"
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
# loyalty_tier omitted entirely, so the guest sits on the NONE default and the
# DRY quote is exactly the list price.
NO_LOYALTY = {"loyalty_tier": None}
DRY_LIST_PRICE_CENTS = 18000


def _service_world(guest_name, resort_room_number, shift_block=None,
                   therapist_name="Service Therapist"):
    return fx.build_world(
        room_codes=("DRY-1",),
        therapist_names=(therapist_name,),
        clock=SERVICE_CLOCK,
        treatment_type_overrides=DRY60_TYPE,
        room_overrides=DRY_ROOM,
        certification_overrides=SWEDISH_BASIC,
        guest_overrides=dict(NO_LOYALTY, full_name=guest_name,
                             resort_room_number=resort_room_number),
        shift_block_overrides=shift_block or SHIFT_BLOCK)


# ---------------------------------------------------------------------------
# occ_stale_guest_version_rejects_intake_form_create
# ---------------------------------------------------------------------------

ACTIVE_INFECTION = "ACTIVE_INFECTION"


def test_the_guest_version_advanced_by_the_screening_refuses_the_replayed_write():
    """The version read at registration is two writes stale — the first form's
    creation and its screening — so replaying it is refused and writes nothing.

    PRD §2.9: "Creating an intake form for a guest requires `expected_guest_version`
    carrying the `version` of that `Guest` as the client last observed it. If the
    guest's current `version` differs, the request is rejected with
    `ERR_STALE_GUEST_VERSION` (HTTP 412)."

    PRD §3.4: "The new form lands in `status` `DRAFT`, and opening it increments the
    guest's `version` by 1."

    PRD §3.4: "Each screening increments the guest's `version` by 1."

    PRD §3.4: "A guest's **authoritative intake form** is the guest's form with the
    greatest `created_at` among those whose `status` is `SCREENED_CLEAR`,
    `SCREENED_FLAGGED` or `OVERRIDDEN`, with ties broken in favour of the greater
    `version`, and `authoritative_intake_form_id` on the guest is the computed
    pointer to that form's `id` — null when the guest has no screened form at all."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_guest_version_rejects_intake_form_create
    """
    fx.set_clock(OCC_CLOCK)
    guest = fx.create_guest(full_name="OCC Guest", resort_room_number="2901",
                            **NO_LOYALTY)
    version_at_create = guest["version"]
    first = fx.screened_intake(guest["id"], version_at_create)
    assert first["status"] == "SCREENED_CLEAR"
    guest_headers = make_guest_headers(guest["id"])

    replay = api_client.create_intake_form(
        guest["id"],
        f.intake_form_payload(version_at_create,
                             condition_codes=[ACTIVE_INFECTION]),
        guest_headers)
    validate_error(replay, ApiErrorId.ERR_STALE_GUEST_VERSION.value, 412)

    fresh = validate_success(api_client.get_guest(guest["id"], guest_headers))
    assert fresh["version"] == version_at_create + 2, (
        "the form's creation and its screening each bumped the guest, and the "
        f"refused write did not, so expected {version_at_create + 2}, got "
        f"{fresh['version']}")

    second = validate_success(api_client.create_intake_form(
        guest["id"],
        f.intake_form_payload(fresh["version"],
                              condition_codes=[ACTIVE_INFECTION]),
        guest_headers), 201)
    assert second["status"] == "DRAFT"

    after = validate_success(api_client.get_guest(guest["id"], guest_headers))
    assert after["version"] == version_at_create + 3, (
        "the accepted retry bumps the guest by exactly one more")
    assert after["authoritative_intake_form_id"] == first["id"], (
        "a DRAFT form is not screened, so it cannot become authoritative")
    assert after["screened_condition_codes"] == [], (
        "the screening decision survives the new DRAFT form untouched")
    assert validate_success(api_client.get_intake_form(
        first["id"], guest_headers))["status"] == "SCREENED_CLEAR"

    forms = assert_list_count(
        api_client.list_intake_forms(guest["id"], fx.COORDINATOR), 2,
        "both forms of this guest")
    assert [row["id"] for row in forms] == [second["id"], first["id"]], (
        "PRD §2.3: a guest's intake forms are returned newest first")


# ---------------------------------------------------------------------------
# occ_stale_appointment_version_rejects_final_settlement
# ---------------------------------------------------------------------------

SERVICE_DURATION_MINUTES = 60
FINAL_ROW = {
    "variant": "FINAL",
    "status": "FINALIZED",
    "basis_duration_minutes": 60,
    "realized_price_cents": 18000,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 3240,        # round_half_up(18000 * 1800 / 10000)
    "gratuity_cents": 0,
    "distributable_pool_cents": 3240,
    "therapist_share_cents": 1944,            # 3240 * 6000 / 10000
    "support_pool_cents": 810,                # 3240 * 2500 / 10000
    "house_share_cents": 486,                 # the residual, never a rate
    "therapist_commission_cents": 6840,       # SENIOR: 18000 * 3800 / 10000
    "retail_commission_cents": 0,
    "labor_cost_cents": 13984,                # 5200 + 6840 + 1944 + 0
    "room_fixed_cost_cents": 2500,            # 2500 * 60 / 60
    "folio_total_cents": 21240,               # 18000 + 0 + 3240 + 0
    "net_margin_cents": 1516,                 # 18000 - 13984 - 2500
}


def test_the_appointment_version_advanced_by_the_service_refuses_the_stale_cut():
    """Check-in, start and complete each bumped the appointment after confirm, so
    the version captured at confirm cannot cut the final row.

    PRD §2.9: "Cutting the final settlement for an appointment requires
    `expected_appointment_version` carrying the `version` of that `Appointment` as
    the client last observed it. If the appointment's current `version` differs, the
    request is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412)."

    PRD §3.9: "A successful cut does four things beyond creating the row. It writes
    the row's `realized_price_cents` onto the appointment's own
    `realized_price_cents` and increments the appointment's `version` by 1. It
    transitions the appointment's provisional row `PROVISIONAL → SUPERSEDED`."

    PRD §3.9: "It posts a folio charge of `kind` `SETTLEMENT_ADJUSTMENT` whose
    `amount_cents` is the final row's `folio_total_cents` less the sum of
    `amount_cents` over every folio posting already recorded against that
    appointment — a figure that is negative whenever the delivered service came in
    cheaper than the provisional estimate."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_appointment_version_rejects_final_settlement
    """
    world = _service_world("Settlement OCC Guest", "3001",
                           therapist_name="Settlement OCC Therapist")
    booked = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, SERVICE_START_AT,
                              world.therapist_id), fx.COORDINATOR), 201)
    appointment_id = booked["id"]
    assert booked["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
    version_at_confirm = fx.confirm(appointment_id)["version"]
    fx.set_clock(ARRIVAL_CLOCK)
    fx.check_in(appointment_id)
    fx.start_service(appointment_id, world.therapist_id)
    fx.complete_service(appointment_id, world.therapist_id,
                        SERVICE_DURATION_MINUTES, 0)

    stale = api_client.create_settlement(
        appointment_id, f.settlement_payload(version_at_confirm), fx.DIRECTOR)
    validate_error(stale, ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value, 412)

    held = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "settlement rows after the refused cut")
    assert held[0]["status"] == "PROVISIONAL", (
        "the refused cut neither created a row nor superseded the provisional one")
    current = validate_success(
        api_client.get_appointment(appointment_id, fx.DIRECTOR))
    assert current["realized_price_cents"] is None, (
        "the appointment's realised price is still unwritten")

    final = validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(current["version"]), fx.DIRECTOR),
        201)
    assert_settlement_row(final, FINAL_ROW, "final row")
    assert_pool_conserved(final)

    rows = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 2,
        "both settlement rows")
    assert [row["variant"] for row in rows] == ["PROVISIONAL", "FINAL"], (
        "the provisional row is returned first")
    assert rows[0]["status"] == "SUPERSEDED"
    assert rows[1]["status"] == "FINALIZED"

    settled = validate_success(
        api_client.get_appointment(appointment_id, fx.DIRECTOR))
    assert settled["realized_price_cents"] == FINAL_ROW["realized_price_cents"]
    assert settled["version"] == current["version"] + 1

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == FINAL_ROW["folio_total_cents"], (
        "the treatment charge posted at check-in already equalled the final "
        "folio total, so the adjustment is zero")
    # Both postings carry the same `posted_at`, because the clock has not moved
    # since check-in, so only the multiset is uniquely derived.
    assert_folio_contents(
        assert_list_count(
            api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
            2, "the appointment's postings"),
        [("TREATMENT", 21240), ("SETTLEMENT_ADJUSTMENT", 0)],
        "the appointment's postings")


# ---------------------------------------------------------------------------
# rate_threshold_second_late_cancel_flips_booking_privilege
# ---------------------------------------------------------------------------

BOOKING_CLOCK = "2026-08-01T09:00:00.000Z"
WIDE_SHIFT_BLOCK = {"start_at": "2026-08-10T08:00:00.000Z",
                    "end_at": "2026-08-14T22:00:00.000Z"}
FIRST_SLOT = "2026-08-10T10:00:00.000Z"
SECOND_SLOT = "2026-08-11T10:00:00.000Z"
THIRD_SLOT = "2026-08-12T10:00:00.000Z"
FOURTH_SLOT = "2026-08-13T10:00:00.000Z"
FIFTH_SLOT = "2026-08-14T10:00:00.000Z"
# Fourteen hours before each cancelled slot: inside 24 hours, so the charge band
# applies, and at or beyond 4 hours, so it is the 5,000-basis-point band.
FIRST_CANCEL_CLOCK = "2026-08-09T20:00:00.000Z"
SECOND_CANCEL_CLOCK = "2026-08-10T20:00:00.000Z"
LATE_CANCEL_CHARGE_CENTS = 9000           # round_half_up(18000 * 5000 / 10000)
ROOM_MINUTES_PER_BOOKING = 75             # 60 scheduled + 15 turnover
THERAPIST_MINUTES_PER_BOOKING = 60


def _threshold_world():
    """Three CONFIRMED appointments on three consecutive days, all with the same
    therapist in the same room, booked while the clock sits well before them."""
    world = fx.build_world(
        room_codes=("DRY-1",),
        therapist_names=("Threshold Therapist",),
        clock=BOOKING_CLOCK,
        treatment_type_overrides=DRY60_TYPE,
        room_overrides=DRY_ROOM,
        certification_overrides=SWEDISH_BASIC,
        guest_overrides=dict(NO_LOYALTY, full_name="Repeat Late Canceller",
                             resort_room_number="3101"),
        shift_block_overrides=WIDE_SHIFT_BLOCK)
    for key, slot in (("a1", FIRST_SLOT), ("a2", SECOND_SLOT),
                      ("a3", THIRD_SLOT)):
        booked = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                     world.room_id, slot, world.therapist_id)
        world.appointments[key] = fx.confirm(booked["id"])
    return world


def _book_slot(world, slot):
    return api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, slot, world.therapist_id),
        fx.COORDINATOR)


def test_one_late_cancellation_charges_the_band_but_leaves_the_privilege_open():
    """One strike short of the threshold of 2 is not a restriction: the guest is
    charged and may still book.

    PRD §3.8: "Otherwise the appointment moves to `LATE_CANCELLED` and a charge is
    assessed. The band rate is 5,000 basis points when the figure is 4 hours or more
    (again inclusive) and 10,000 basis points when it is under 4 hours, which
    includes every negative figure."

    PRD §3.8: "A guest below the threshold simply keeps `booking_privilege` at
    `OPEN` and none of the last three hops run."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_second_late_cancel_flips_booking_privilege
    """
    world = _threshold_world()
    fx.set_clock(FIRST_CANCEL_CLOCK)

    cancelled = validate_success(api_client.cancel_appointment(
        world.appointments["a1"]["id"], f.cancel_payload("first late cancel"),
        make_guest_headers(world.guest_id)))
    assert cancelled["schedule_status"] == "LATE_CANCELLED", (
        f"14 hours out is inside 24 hours, got {cancelled['schedule_status']}")
    assert cancelled["cancellation_charge_cents"] == LATE_CANCEL_CHARGE_CENTS

    guest = world.fetch_guest()
    assert guest["late_cancel_count"] == 1
    assert guest["no_show_strikes"] == 0, "a cancellation is not a no-show"
    assert guest["booking_privilege"] == "OPEN", (
        "one short of the restriction threshold of 2 is still OPEN")
    assert guest["folio_balance_cents"] == LATE_CANCEL_CHARGE_CENTS

    accepted = validate_success(_book_slot(world, FOURTH_SLOT), 201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert_state_pair(world.fetch_appointment(world.appointments["a2"]["id"]),
                      "CONFIRMED", "CLEARED")
    assert_state_pair(world.fetch_appointment(world.appointments["a3"]["id"]),
                      "CONFIRMED", "CLEARED")


def test_the_second_late_cancellation_restricts_and_cancels_the_requested_survivor():
    """Crossing the cumulative threshold flips the privilege, cancels every other
    `REQUESTED` appointment for free, spares the `CONFIRMED` one and closes booking.

    PRD §3.8: "Because `late_cancel_count` has now reached the restriction threshold
    of 2, the guest's `booking_privilege` flips from `OPEN` to `RESTRICTED`. Because
    the guest became restricted, every **other** appointment of that guest whose
    `schedule_status` is `REQUESTED` is cancelled by the system, processed in
    ascending `created_at` order, each landing in `CANCELLED` with
    `cancellation_charge_cents` 0 and no folio posting of its own."

    PRD §3.5: "Finally the slot must be far enough out — `start_at` must be at least
    two hours, that is 120 minutes, after the logical clock
    (`ERR_BOOKING_LEAD_TIME`) — and the guest's `booking_privilege` must be `OPEN`
    (`ERR_GUEST_BOOKING_RESTRICTED`)."

    PRD §3.8: "Both cancellation outcomes release capacity: the room's
    `booked_minutes_total` is reduced by `scheduled_duration_minutes` plus that
    room's `turnover_buffer_minutes`, and the therapist's `assigned_minutes_total`
    is reduced by `scheduled_duration_minutes`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_second_late_cancel_flips_booking_privilege
    """
    world = _threshold_world()
    guest_headers = make_guest_headers(world.guest_id)
    fx.set_clock(FIRST_CANCEL_CLOCK)
    validate_success(api_client.cancel_appointment(
        world.appointments["a1"]["id"], f.cancel_payload("first late cancel"),
        guest_headers))
    survivor = validate_success(_book_slot(world, FOURTH_SLOT), 201)

    fx.set_clock(SECOND_CANCEL_CLOCK)
    second = validate_success(api_client.cancel_appointment(
        world.appointments["a2"]["id"], f.cancel_payload("second late cancel"),
        guest_headers))
    assert second["schedule_status"] == "LATE_CANCELLED"
    assert second["cancellation_charge_cents"] == LATE_CANCEL_CHARGE_CENTS

    guest = world.fetch_guest()
    assert guest["late_cancel_count"] == 2
    assert guest["booking_privilege"] == "RESTRICTED", (
        "the second strike reaches the restriction threshold of 2")
    assert guest["folio_balance_cents"] == 2 * LATE_CANCEL_CHARGE_CENTS

    # The restriction cascade reaches every OTHER appointment still REQUESTED.
    swept = world.fetch_appointment(survivor["id"])
    assert swept["schedule_status"] == "CANCELLED", (
        f"the REQUESTED survivor is cancelled by the system, got "
        f"{swept['schedule_status']}")
    assert swept["cancellation_charge_cents"] == 0, (
        "a system cancellation carries no charge")
    assert_state_pair(world.fetch_appointment(world.appointments["a3"]["id"]),
                      "CONFIRMED", "CLEARED")

    refused = _book_slot(world, FIFTH_SLOT)
    validate_error(refused, ApiErrorId.ERR_GUEST_BOOKING_RESTRICTED.value, 409)

    rows = assert_list_count(
        api_client.list_appointments(fx.COORDINATOR,
                                     {"guest_id": world.guest_id}), 4,
        "every appointment of this guest")
    assert sorted(row["schedule_status"] for row in rows) == [
        "CANCELLED", "CONFIRMED", "LATE_CANCELLED", "LATE_CANCELLED"], (
        "the refused attempt created no fifth row")

    charges = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, guest_headers), 2,
        "the guest's postings")
    assert [(row["kind"], row["amount_cents"]) for row in charges] == [
        ("LATE_CANCEL", LATE_CANCEL_CHARGE_CENTS),
        ("LATE_CANCEL", LATE_CANCEL_CHARGE_CENTS)], (
        "only the two charged cancellations posted; the free ones posted nothing")
    assert_ledgers(world.fetch_room(), world.fetch_therapist(),
                   ROOM_MINUTES_PER_BOOKING, THERAPIST_MINUTES_PER_BOOKING)
