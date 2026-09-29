"""Compensating invariants: the checked-in abort that returns the folio to zero
through a new negative row rather than an edit, and the book-cancel-rebook-cancel
cycle that must leave both minute ledgers at exactly zero.
"""

from test_helpers import (
    assert_balance_equals_posting_sum,
    assert_folio_rows,
    assert_list_count,
    assert_percent_2dp,
    assert_same_instant,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_START_AT
from test_helpers import factories as f
from test_helpers import fixtures as fx

PROVISIONAL_FOLIO_TOTAL_CENTS = 50504


def _armed_abort_world():
    """A CHECKED_IN appointment whose room has since been taken out of service, so
    its clearance dimension is BLOCKED and the abort path is armed."""
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    fx.set_room_status(world.room_id, "MAINTENANCE")
    return world


def test_checked_in_abort_reverses_the_folio_with_a_new_negative_row():
    """The reversal is an immutable compensating posting, not an edit.

    PRD §3.8: "It unwinds the check-in in full: the appointment's settlement row in
    `status` `PROVISIONAL` moves `PROVISIONAL → REVERSED` with its computed money
    fields frozen where they stood, and a compensating folio posting of `kind`
    `REVERSAL` is written whose `amount_cents` is the negative of that row's
    `folio_total_cents`, returning the guest's recomputed `folio_balance_cents` to
    its exact pre-check-in value."

    PRD §2.5: "The second is the folio posting: postings are never edited or
    deleted, and a correction is expressed as an additional posting whose amount
    may be negative."

    Design: Difficulty/compensating_invariant/checked_in_abort_returns_folio_balance_to_zero
    """
    world = _armed_abort_world()
    appointment_id = world.appointments["a"]["id"]

    assert world.fetch_guest()["folio_balance_cents"] == \
        PROVISIONAL_FOLIO_TOTAL_CENTS
    before = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
        1, "appointment folio postings before the abort")
    assert_folio_rows(before, [("TREATMENT", PROVISIONAL_FOLIO_TOTAL_CENTS)],
                      "appointment folio before the abort")
    blocked = world.fetch_appointment(appointment_id)
    assert blocked["clearance_status"] == "BLOCKED"
    assert blocked["clearance_block_reason"] == "ROOM_UNAVAILABLE", (
        "this is what makes the CHECKED_IN abort legal under the clearance rung")

    aborted = validate_success(api_client.cancel_appointment(
        appointment_id, f.cancel_payload("hydro circulator failure"),
        fx.COORDINATOR))
    assert aborted["schedule_status"] == "CANCELLED"
    assert aborted["cancellation_charge_cents"] == 0

    row = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "settlement rows")[0]
    assert row["status"] == "REVERSED"
    assert row["folio_total_cents"] == PROVISIONAL_FOLIO_TOTAL_CENTS, (
        "the computed money fields freeze where they stood; nothing is edited "
        "in place")

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
        2, "appointment folio postings after the abort")
    assert_folio_rows(postings, [
        ("TREATMENT", PROVISIONAL_FOLIO_TOTAL_CENTS),
        ("REVERSAL", -PROVISIONAL_FOLIO_TOTAL_CENTS),
    ], "appointment folio after the abort")

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == 0, (
        "50504 + -50504 conserves the money exactly")
    assert_balance_equals_posting_sum(guest, postings)


def test_the_facility_caused_abort_is_not_held_against_the_guest():
    """No charge, no strike and no restriction follow a spa-caused abort.

    PRD §3.8: "No penalty attaches to the guest for an abort the spa caused:
    `cancellation_charge_cents` stays 0 and `late_cancel_count` is **not**
    incremented."

    PRD §3.8: "The room and therapist minute ledgers are released as on any other
    cancellation."

    Design: Difficulty/compensating_invariant/checked_in_abort_returns_folio_balance_to_zero
    """
    world = _armed_abort_world()
    appointment_id = world.appointments["a"]["id"]

    validate_success(api_client.cancel_appointment(
        appointment_id, f.cancel_payload("hydro circulator failure"),
        fx.COORDINATOR))

    guest = world.fetch_guest()
    assert guest["late_cancel_count"] == 0
    assert guest["no_show_strikes"] == 0
    assert guest["booking_privilege"] == "OPEN"

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 2,
        "guest folio postings")
    kinds = [posting["kind"] for posting in postings]
    assert "LATE_CANCEL" not in kinds, (
        "an abort is not a policy charge, so no LATE_CANCEL row is written")
    assert kinds.count("TREATMENT") == 1, (
        "the original TREATMENT row is still present and unmodified")

    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


# ---------------------------------------------------------------------------
# Minute-ledger conservation across two up/down cycles
# ---------------------------------------------------------------------------

def test_book_cancel_rebook_cancel_returns_both_minute_ledgers_to_zero():
    """Two up/down cycles must leave no drift on either ledger.

    PRD §2.12: "Booking an appointment adds those minutes to the room; any
    transition that releases the slot — an ordinary cancellation, a late
    cancellation, a no-show, the checked-in abort, a sweep-driven automatic
    cancellation or a restriction-driven cancellation — subtracts exactly the same
    quantity."

    PRD §2.12: "Two running counters give the spa a live picture of committed
    capacity, and both are maintained as strict double-entry-style increments and
    decrements rather than being recomputed from scratch."

    Design: Difficulty/compensating_invariant/book_cancel_rebook_cancel_returns_minute_ledgers_to_zero
    """
    world = fx.build_world()
    first = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "90 scheduled plus 30 turnover minutes")
    assert world.fetch_therapist()["assigned_minutes_total"] == 90, (
        "the turnover buffer belongs to the room, not the practitioner")

    cancelled = validate_success(api_client.cancel_appointment(
        first["id"], f.cancel_payload("itinerary change"), fx.COORDINATOR))
    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["cancellation_charge_cents"] == 0
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0

    second = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    assert second["id"] != first["id"], (
        "the identical slot is bookable again, which proves the decrement really "
        "happened rather than being masked")
    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "the ledger reads 120 again, not 240")
    assert world.fetch_therapist()["assigned_minutes_total"] == 90

    fx.set_clock("2026-08-09T17:00:00.000Z")
    validate_success(api_client.cancel_appointment(
        second["id"], f.cancel_payload("itinerary change again"),
        fx.COORDINATOR))
    assert world.fetch_room()["booked_minutes_total"] == 0, (
        "neither ledger is negative and neither retains drift after two cycles")
    assert world.fetch_therapist()["assigned_minutes_total"] == 0

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == 0
    assert guest["late_cancel_count"] == 0
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings")


def test_the_utilization_report_cross_checks_the_reconciled_ledgers():
    """A day with no completed appointments still reports its room at 0.00.

    PRD §3.10: "Every room appears in that array whether or not it saw any
    business, each element carrying `room_id`, `room_code`, `occupied_minutes`,
    `utilization_pct`, `revenue_cents`, `labor_cost_cents`, `room_fixed_cost_cents`,
    `net_margin_cents` and `revenue_per_room_hour_cents`."

    PRD §3.10: "A room with no completed appointments in the window reports
    `occupied_minutes` 0, `utilization_pct` exactly `0.00` and every money field 0
    rather than being omitted."

    Design: Difficulty/compensating_invariant/book_cancel_rebook_cancel_returns_minute_ledgers_to_zero
    """
    world = fx.build_world()
    first = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    validate_success(api_client.cancel_appointment(
        first["id"], f.cancel_payload("itinerary change"), fx.COORDINATOR))
    second = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    fx.set_clock("2026-08-09T17:00:00.000Z")
    validate_success(api_client.cancel_appointment(
        second["id"], f.cancel_payload("itinerary change again"),
        fx.COORDINATOR))

    report = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR,
        params=f.report_window("2026-08-10T00:00:00.000Z",
                               "2026-08-11T00:00:00.000Z",
                               room_id=world.room_id)))
    assert_same_instant(report["from_at"], "2026-08-10T00:00:00.000Z", "from_at")
    assert_same_instant(report["to_at"], "2026-08-11T00:00:00.000Z", "to_at")
    assert report["window_minutes"] == 1440

    assert len(report["rooms"]) == 1, (
        f"the room still appears with zero business, got {report['rooms']}")
    element = report["rooms"][0]
    assert element["room_id"] == world.room_id
    assert element["room_code"] == "HYDRO-1"
    assert element["occupied_minutes"] == 0
    assert_percent_2dp(element["utilization_pct"], "utilization_pct")
    assert float(element["utilization_pct"]) == 0.00
    for field in ("revenue_cents", "labor_cost_cents", "room_fixed_cost_cents",
                  "net_margin_cents", "revenue_per_room_hour_cents"):
        assert element[field] == 0, (
            f"{field} must be 0 rather than omitted, got {element.get(field)!r}")
