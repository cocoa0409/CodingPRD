"""Round trips that must leave money and crew capacity exactly where they started."""

from test_helpers import (
    COORDINATOR,
    api_client,
    assert_cents,
    assert_crew_load,
    assert_deposit_stream_balances,
    assert_instant_equals,
    assert_pct,
    install_appointment_payload,
    list_ledger_for_account,
    list_ledger_for_preorder,
    make_subscriber_headers,
    read_account,
    read_appointment,
    read_crew,
    read_crew_version,
    read_preorder,
    read_zone,
    record_outcome,
    setup_scheduled_bury_appointment,
    setup_zone_with_preorders,
    validate_success,
)

WINDOW_START = "2026-10-05T09:00:00Z"
WINDOW_END = "2026-10-05T11:00:00Z"


def test_a_pending_sign_up_holds_exactly_one_deposit_and_lifts_the_live_rate():
    """The opening leg of the round trip: 1,000 cents held and the rate at 10.00.

    PRD 3.3: "The deposit is recorded, not merely asserted: one ledger entry of `entry_type`
    `DEPOSIT_HELD` is appended for the amount of `deposit_amount_cents` as a positive
    `amount_cents`, referencing this preorder, and the account's `deposit_held_cents` is
    recomputed from its stream."

    Design: Difficulty/compensating_invariant/deposit_cents_conserved_across_preorder_create_then_cancel
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    account = base["accounts"][0]

    assert_cents(
        read_account(account["id"])["deposit_held_cents"], 1000, "deposit_held_cents"
    )
    zone = read_zone(base["zone"]["id"])
    assert_pct(zone["prereg_rate_pct"], 10.00, "prereg_rate_pct")
    assert zone["provisional_qualifying_count"] == 1, zone["provisional_qualifying_count"]

    entries, _ = list_ledger_for_preorder(base["preorders"][0]["id"])
    assert len(entries) == 1, entries
    assert entries[0]["entry_type"] == "DEPOSIT_HELD", entries[0]["entry_type"]
    assert_cents(entries[0]["amount_cents"], 1000, "DEPOSIT_HELD amount_cents")


def test_cancelling_a_pending_sign_up_returns_every_cent_it_held():
    """The closing leg: a refund entry cancels the hold and the balance is back at zero.

    PRD 3.3: "From `PENDING` the transition is `PENDING → CANCELLED`: `cancelled_at` is
    stamped with the logical clock and the money dimension moves `HELD → REFUNDED`, appending
    one `DEPOSIT_REFUNDED` entry whose `amount_cents` is the negative of `deposit_amount_cents`
    and recomputing the account's `deposit_held_cents`."

    Design: Difficulty/compensating_invariant/deposit_cents_conserved_across_preorder_create_then_cancel
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    account = base["accounts"][0]
    preorder_id = base["preorders"][0]["id"]

    validate_success(
        api_client.cancel_preorder(preorder_id, make_subscriber_headers(account["id"]))
    )

    preorder = read_preorder(preorder_id)
    assert preorder["preorder_status"] == "CANCELLED", preorder["preorder_status"]
    assert preorder["deposit_status"] == "REFUNDED", preorder["deposit_status"]
    assert preorder["cancelled_at"] is not None
    assert_cents(read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents")

    entries, _ = list_ledger_for_account(account["id"])
    assert_deposit_stream_balances(entries, 0)


def test_the_original_hold_entry_is_never_rewritten_by_the_refund():
    """The append-only stream keeps the positive hold intact beside the negative refund.

    PRD 2.8: "Entries are never filtered by date and never pruned, so each recomputation is a
    full replay of the account's stream and is independent of the order in which the entries are
    visited."

    Design: Difficulty/compensating_invariant/deposit_cents_conserved_across_preorder_create_then_cancel
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    account = base["accounts"][0]
    preorder_id = base["preorders"][0]["id"]
    before, _ = list_ledger_for_preorder(preorder_id)
    original_hold = before[0]

    validate_success(
        api_client.cancel_preorder(preorder_id, make_subscriber_headers(account["id"]))
    )

    after, _ = list_ledger_for_preorder(preorder_id)
    assert len(after) == 2, after
    holds = [entry for entry in after if entry["entry_type"] == "DEPOSIT_HELD"]
    assert len(holds) == 1, after
    assert holds[0]["id"] == original_hold["id"], (original_hold["id"], holds[0]["id"])
    assert_cents(holds[0]["amount_cents"], 1000, "DEPOSIT_HELD amount_cents")
    assert_instant_equals(
        holds[0]["occurred_at"], original_hold["occurred_at"], "occurred_at"
    )
    refunds = [entry for entry in after if entry["entry_type"] == "DEPOSIT_REFUNDED"]
    assert len(refunds) == 1, after
    assert_cents(refunds[0]["amount_cents"], -1000, "DEPOSIT_REFUNDED amount_cents")


def test_cancellation_recomputes_the_live_rate_downward_to_zero():
    """Withdrawing the only sign-up empties the numerator without touching the denominator.

    PRD 3.3: "Either way the zone's `provisional_qualifying_count` and `prereg_rate_pct` are
    recomputed downward and the zone's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/deposit_cents_conserved_across_preorder_create_then_cancel
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    account = base["accounts"][0]

    validate_success(
        api_client.cancel_preorder(
            base["preorders"][0]["id"], make_subscriber_headers(account["id"])
        )
    )

    zone = read_zone(base["zone"]["id"])
    assert zone["provisional_qualifying_count"] == 0, zone["provisional_qualifying_count"]
    assert_pct(zone["prereg_rate_pct"], 0.00, "prereg_rate_pct")
    assert zone["household_count"] == 10, zone["household_count"]


def test_booking_a_two_hour_window_loads_the_crew_with_its_buffered_minutes():
    """The opening leg: 120 window minutes plus a 30-minute buffer is 150 occupied minutes.

    PRD 3.8: "A successfully booked appointment opens in status `SCHEDULED` with
    `restoration_required` false and `restoration_due_by`, `restoration_satisfied_at`,
    `completed_at` and `cancellation_reason` all null, and the holding crew's
    `booked_minutes_total` and `scheduled_appointment_count` are recomputed upward while the
    crew's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_across_appointment_schedule_then_cancel
    """
    base = setup_scheduled_bury_appointment(
        window_start_at=WINDOW_START, window_end_at=WINDOW_END
    )

    appointment = read_appointment(base["appointment"]["id"])
    assert appointment["status"] == "SCHEDULED", appointment["status"]
    assert appointment["occupied_minutes"] == 150, appointment["occupied_minutes"]
    assert_crew_load(read_crew(base["crew"]["id"]), 150, 1)


def test_cancelling_the_visit_releases_exactly_the_minutes_it_took():
    """The closing leg: the crew returns to zero booked minutes and zero appointments.

    PRD 3.8: "All three share one consequence: the crew's `booked_minutes_total` and
    `scheduled_appointment_count` are recomputed downward by this row's `occupied_minutes`,
    restoring both to their pre-booking values, and the crew's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_across_appointment_schedule_then_cancel
    """
    base = setup_scheduled_bury_appointment(
        window_start_at=WINDOW_START, window_end_at=WINDOW_END
    )
    version_before = read_crew_version(base["crew"]["id"])

    cancelled = record_outcome(
        base["appointment"]["id"], "CANCELLED", cancellation_reason="SUBSCRIBER_REQUEST"
    )

    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert cancelled["cancellation_reason"] == "SUBSCRIBER_REQUEST", (
        cancelled["cancellation_reason"]
    )
    crew = read_crew(base["crew"]["id"])
    assert_crew_load(crew, 0, 0)
    assert crew["version"] > version_before, (version_before, crew["version"])


def test_the_freed_window_can_be_rebooked_at_exactly_the_same_instants():
    """A cancelled row occupies no interval, so the identical window is available again.

    PRD 3.8: "Only `SCHEDULED` appointments occupy anything at all - `COMPLETED`, `NO_SHOW` and
    `CANCELLED` rows occupy neither minutes nor interval - so ending an appointment frees
    both."

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_across_appointment_schedule_then_cancel
    """
    base = setup_scheduled_bury_appointment(
        window_start_at=WINDOW_START, window_end_at=WINDOW_END
    )
    record_outcome(
        base["appointment"]["id"], "CANCELLED", cancellation_reason="SUBSCRIBER_REQUEST"
    )
    crew_id = base["crew"]["id"]

    response = api_client.create_install_appointment(
        install_appointment_payload(
            base["converted"]["id"],
            crew_id,
            WINDOW_START,
            WINDOW_END,
            read_crew_version(crew_id),
        ),
        COORDINATOR,
    )

    rebooked = validate_success(response, 201)
    assert rebooked["status"] == "SCHEDULED", rebooked["status"]
    assert rebooked["occupied_minutes"] == 150, rebooked["occupied_minutes"]
    assert rebooked["id"] != base["appointment"]["id"]
    assert_crew_load(read_crew(crew_id), 150, 1)
