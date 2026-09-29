"""Transitive cascades: the compliance sweep's five hops from an expired licence
down to a horizon-selective auto-cancellation, and the no-show cascade that
climbs to the guest aggregate and back down into a second appointment.
"""

from test_helpers import (
    ApiErrorId,
    assert_list_count,
    assert_same_instant,
    assert_state_pair,
    make_compliance_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import (
    CANON_QUOTED_PRICE_CENTS,
    CANON_RETAIL_AMOUNT_CENTS,
    CANON_START_AT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SWEEP_INSTANT = "2026-09-01T00:00:00.000Z"


def _sweep_world():
    """Two CONFIRMED appointments of one therapist whose licence lapses on
    2026-08-31: A on 2026-09-01T18:00Z (inside the 48-hour horizon at sweep time)
    and B on 2026-09-05T10:00Z (well beyond it). A carries one RECOMMENDED
    retail attachment."""
    world = fx.build_world(
        license_overrides={"expires_on": "2026-08-31"},
        shift_block_overrides={"start_at": "2026-09-01T08:00:00.000Z",
                               "end_at": "2026-09-01T22:00:00.000Z"})
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-09-05T08:00:00.000Z",
                       end_at="2026-09-05T22:00:00.000Z")
    for key, start_at in (("a", "2026-09-01T18:00:00.000Z"),
                          ("b", "2026-09-05T10:00:00.000Z")):
        appointment = fx.book_appointment(
            world.guest_id, world.treatment_type_id, world.room_id, start_at,
            world.therapist_id)
        world.appointments[key] = fx.confirm(appointment["id"])
    attachment = validate_success(api_client.create_retail_attachment(
        world.appointments["a"]["id"],
        f.retail_attachment_payload(amount_cents=CANON_RETAIL_AMOUNT_CENTS),
        world.therapist_headers), 201)
    fx.set_clock(SWEEP_INSTANT)
    return world, attachment


def test_compliance_sweep_reports_every_hop_of_the_licence_expiry_cascade():
    """One bodyless request expires the licence, suspends the therapist, blocks
    both appointments and expires the recommendation.

    PRD §3.10: "The first hop expires credentials: every licence whose
    `verification_status` is `VERIFIED` and whose `expires_on` falls strictly
    before the sweep instant's UTC date moves `VERIFIED → EXPIRED`."

    PRD §3.10: "The third hop blocks the work: because the therapist became
    suspended, every appointment of that therapist whose `schedule_status` is
    `REQUESTED`, `CONFIRMED` or `CHECKED_IN` has its `clearance_status` driven to
    `BLOCKED` with `clearance_block_reason` `LICENSE_INVALID`, processed in
    ascending `start_at` order with ties broken by ascending `created_at`."

    Design: Difficulty/transitive_cascade/compliance_sweep_license_expiry_five_hop_cascade
    """
    world, attachment = _sweep_world()
    appointment_a = world.appointments["a"]["id"]
    appointment_b = world.appointments["b"]["id"]

    room_before = world.fetch_room()
    therapist_before = world.fetch_therapist()
    assert room_before["booked_minutes_total"] == 240, (
        "two bookings of 90 scheduled plus 30 turnover minutes each")
    assert therapist_before["assigned_minutes_total"] == 180

    sweep = validate_success(api_client.run_compliance_sweep(
        {}, make_compliance_headers("co-5")))
    assert_same_instant(sweep["swept_at"], SWEEP_INSTANT, "swept_at")
    assert sweep["expired_license_ids"] == [world.license_id]
    assert sweep["suspended_therapist_ids"] == [world.therapist_id]
    assert sweep["blocked_appointment_ids"] == [appointment_a, appointment_b], (
        "blocked appointments are reported in ascending start_at order")
    assert sweep["expired_attachment_ids"] == [attachment["id"]]

    license_row = validate_success(api_client.get_license(
        world.license_id, make_compliance_headers("co-5")))
    assert license_row["verification_status"] == "EXPIRED"

    therapist = world.fetch_therapist()
    assert therapist["status"] == "SUSPENDED"
    assert therapist["suspension_reason"] == "LICENSE_EXPIRED"

    for appointment_id in (appointment_a, appointment_b):
        appointment = world.fetch_appointment(appointment_id)
        assert appointment["clearance_status"] == "BLOCKED"
        assert appointment["clearance_block_reason"] == "LICENSE_INVALID"

    expired = validate_success(api_client.list_retail_attachments(
        appointment_a, world.therapist_headers))
    assert expired[0]["status"] == "EXPIRED"
    assert expired[0]["resolved_by_user_id"] is None, (
        "no user resolved it, so resolved_by_user_id stays null")


def test_sweep_auto_cancels_only_inside_the_forty_eight_hour_horizon():
    """Hop five is horizon-selective, so the cascade stops partway for B.

    PRD §3.10: "The fifth hop protects the near-term schedule: among those newly
    blocked appointments, each one whose `schedule_status` is `CONFIRMED` and
    whose `start_at` is earlier than the sweep instant advanced by 48 hours moves
    `CONFIRMED → CANCELLED` as a system act, with `cancellation_charge_cents` 0
    and no folio posting — the spa, not the guest, caused this — and each such
    cancellation decrements that appointment's room `booked_minutes_total` and
    therapist `assigned_minutes_total` by the appointment's committed minutes."

    PRD §3.10: "Appointments in `REQUESTED` or `CHECKED_IN`, and confirmed
    appointments starting beyond the 48-hour horizon, stay blocked but are not
    cancelled."

    Design: Difficulty/transitive_cascade/compliance_sweep_license_expiry_five_hop_cascade
    """
    world, _attachment = _sweep_world()
    appointment_a = world.appointments["a"]["id"]
    appointment_b = world.appointments["b"]["id"]

    sweep = validate_success(api_client.run_compliance_sweep(
        {}, make_compliance_headers("co-5")))
    assert sweep["auto_cancelled_appointment_ids"] == [appointment_a], (
        "A starts 18 hours after the sweep while B starts four days out")

    cancelled = world.fetch_appointment(appointment_a)
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancellation_charge_cents"] == 0

    survivor = world.fetch_appointment(appointment_b)
    assert_state_pair(survivor, "CONFIRMED", "BLOCKED", "LICENSE_INVALID")

    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "only A's 120 committed minutes were released")
    assert world.fetch_therapist()["assigned_minutes_total"] == 90

    assert world.fetch_guest()["folio_balance_cents"] == 0
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings")


# ---------------------------------------------------------------------------
# The no-show restriction cascade
# ---------------------------------------------------------------------------

def _no_show_world():
    """One CONFIRMED appointment at 17:00Z and one still-REQUESTED appointment the
    next morning, with the clock 16 minutes past the confirmed slot's start."""
    world = fx.build_world()
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-08-11T08:00:00.000Z",
                       end_at="2026-08-11T20:00:00.000Z")
    confirmed = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    world.appointments["a"] = fx.confirm(confirmed["id"])
    world.appointments["b"] = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id,
        "2026-08-11T09:00:00.000Z", world.therapist_id)
    fx.set_clock("2026-08-10T17:16:00.000Z")
    return world


def test_no_show_charges_the_capped_full_quote_and_restricts_the_guest():
    """The no-show band plus the high-demand uplift is clamped at the whole quote.

    PRD §3.8: "The charge uses the same calculation with the no-show band of
    10,000 basis points, again taking the 2,000-basis-point high-demand uplift and
    again capped at 10,000 basis points, which makes a no-show cost the full
    quoted price whether or not the slot was in demand."

    PRD §3.8: "the posting carries `kind` `NO_SHOW`, and the counter that moves is
    `no_show_strikes`, whose restriction threshold is 1."

    Design: Difficulty/transitive_cascade/no_show_guest_restriction_five_hop_cascade
    """
    world = _no_show_world()
    assert world.fetch_room()["booked_minutes_total"] == 240
    assert world.fetch_therapist()["assigned_minutes_total"] == 180
    assert world.fetch_guest()["booking_privilege"] == "OPEN"

    no_show = validate_success(api_client.no_show_appointment(
        world.appointments["a"]["id"], {}, fx.COORDINATOR))
    assert no_show["schedule_status"] == "NO_SHOW"
    assert no_show["cancellation_charge_cents"] == CANON_QUOTED_PRICE_CENTS, (
        "10,000 bp plus the 2,000 bp uplift clamped to 10,000 bp of 42800")

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings")
    assert postings[0]["kind"] == "NO_SHOW"
    assert postings[0]["amount_cents"] == CANON_QUOTED_PRICE_CENTS

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == CANON_QUOTED_PRICE_CENTS
    assert guest["no_show_strikes"] == 1
    assert guest["booking_privilege"] == "RESTRICTED", (
        "a single strike reaches the threshold of 1")


def test_restriction_cascade_cancels_the_other_requested_appointment_for_free():
    """The cascade descends into a different appointment of the same guest.

    PRD §3.8: "A single no-show therefore restricts the guest immediately,
    cancelling every other `REQUESTED` appointment of theirs in ascending
    `created_at` order and releasing each one's minutes."

    PRD §3.8: "Once `booking_privilege` is `RESTRICTED`, further booking attempts
    for that guest fail with `ERR_GUEST_BOOKING_RESTRICTED`."

    Design: Difficulty/transitive_cascade/no_show_guest_restriction_five_hop_cascade
    """
    world = _no_show_world()
    validate_success(api_client.no_show_appointment(
        world.appointments["a"]["id"], {}, fx.COORDINATOR))

    other = world.fetch_appointment(world.appointments["b"]["id"])
    assert other["schedule_status"] == "CANCELLED"
    assert other["cancellation_charge_cents"] == 0, (
        "the restriction cascade never charges")

    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings after the cascade")

    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0

    fx.set_clock("2026-08-11T00:00:00.000Z")
    refused = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, "2026-08-11T09:00:00.000Z",
                              world.therapist_id),
        fx.COORDINATOR)
    validate_error(refused, ApiErrorId.ERR_GUEST_BOOKING_RESTRICTED.value, 409)
