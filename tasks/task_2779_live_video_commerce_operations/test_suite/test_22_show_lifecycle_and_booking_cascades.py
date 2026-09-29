"""The readiness gate, booking cancellation cascades and terminal settlement."""

from test_helpers import (
    CLOCK_EPOCH,
    PRODUCER,
    SIGNOFF_OFFICER,
    SIGNOFF_OFFICER_ID,
    ApiErrorId,
    add_cart_item_payload,
    assert_instant,
    build_scenario,
    cancel_booking_payload,
    make_host_headers,
    read_cart,
    read_channel,
    read_line,
    read_offer,
    read_show,
    set_clock,
    signoff_payload,
    validate_error,
    validate_success,
)


def test_clearing_the_readiness_gate_stamps_the_grade_and_the_logical_instant(api):
    """When a producer asserts a show is fit to air, the platform records both the
    instant it checked and the simulcast grade it found: one destination reporting
    exactly the reference latency with no frame loss grades a perfect 100.

    PRD 3.4: "A show that clears all six recomputes `simulcast_readiness_index`
    from the current destination health, stamps `readiness_checked_at` with the
    logical instant, and increments its `version`."
    PRD 3.3: "take the destination's reported `latency_ms`, subtract 1,500
    milliseconds, divide by 50 milliseconds, and floor the result at zero" and
    "The second penalty is **frame loss**: the reported `dropped_frame_pct`
    multiplied by 400" and "Subtract a drift tolerance of 800 milliseconds from
    the spread, divide by 100 milliseconds, and floor at zero."
    PRD 2.5: "That clock starts at exactly `2026-08-01T00:00:00Z`, and until an
    administrator moves it, every temporal comparison in the system is evaluated
    against that instant."

    Design: Corner/state_machines/show_ready_transition_stamps_readiness_index_and_timestamp
    """
    scenario = build_scenario(
        with_disclosure=False,
        offers=[],
        channels=[
            {
                "platform": "FLAGSHIP_APP",
                "target_latency_ms": 1500,
                "is_primary": True,
                "latency_ms": 1500,
                "dropped_frame_pct": 0.0,
            }
        ],
    )
    show_before = read_show(scenario.show_id)
    assert show_before["status"] == "DRAFT"

    show = validate_success(api.ready_show(scenario.show_id, PRODUCER))

    assert show["status"] == "READY"
    assert_instant(show["readiness_checked_at"], CLOCK_EPOCH, "readiness_checked_at")
    assert show["simulcast_readiness_index"] == 100, (
        "no latency penalty, no frame-loss penalty and a single-destination spread "
        "of zero leave the grade at 100"
    )
    assert show["version"] == show_before["version"] + 1

    channel = read_channel(scenario.channel_id)
    assert channel["readiness_index"] == 100
    assert channel["status"] == "PROVISIONED", "the gate does not move destinations"


def test_a_show_with_nothing_to_sell_cannot_be_declared_ready(api):
    """A broadcast with a confirmed host and a provisioned destination but no
    lineup has nothing to sell, so the gate refuses it and it stays a draft.

    PRD 3.4: "**Non-empty lineup.** The show must have at least one lineup slot; a
    show with none fails with `ERR_LINEUP_EMPTY`."
    PRD 3.4: "Running the gate moves the show `DRAFT → READY` and is refused
    unless the show is currently `DRAFT`"

    Design: Corner/state_machines/ready_without_lineup_slots_returns_lineup_empty
    """
    scenario = build_scenario(
        products=[],
        with_disclosure=False,
        slots=[],
        offers=[],
    )

    validate_error(api.ready_show(scenario.show_id, PRODUCER), ApiErrorId.ERR_LINEUP_EMPTY)

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT", "the refused gate leaves the show a draft"


def test_a_host_cannot_accept_the_same_booking_twice(api):
    """Acceptance is a one-time act: replaying it on a booking already accepted is
    refused and does not rewrite the moment of acceptance.

    PRD 3.1: "Acceptance is refused unless the booking is still `PENDING`
    (`ERR_INVALID_BOOKING_STATE`)"
    PRD 2.4: "`version` is an integer that starts at `1` when the row is created
    and increments by exactly `1` on every mutation of that row"

    Design: Corner/state_machines/second_confirm_on_confirmed_booking_returns_invalid_booking_state
    """
    scenario = build_scenario(
        products=[],
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )
    booking_id = scenario.bookings[0]["id"]
    before = validate_success(api.get_host_booking(booking_id, PRODUCER))
    assert before["status"] == "CONFIRMED"

    validate_error(
        api.confirm_host_booking(booking_id, make_host_headers(scenario.host_id)),
        ApiErrorId.ERR_INVALID_BOOKING_STATE,
    )

    after = validate_success(api.get_host_booking(booking_id, PRODUCER))
    assert after["status"] == "CONFIRMED"
    assert_instant(after["confirmed_at"], before["confirmed_at"], "confirmed_at")
    assert after["version"] == before["version"], "a refused write bumps nothing"


def test_cancelling_a_pending_booking_voids_its_pending_paperwork(api):
    """When a booking falls through before the host ever accepted it, the
    disclosure obligation attached to that booking is voided rather than left
    outstanding, and the show itself is untouched because it was never ready.

    PRD 3.1: "Both branches record `cancel_reason`, increment the booking's
    `version`, and void the paperwork: every disclosure record naming this booking
    through `host_booking_id` whose status is still `PENDING` moves `PENDING →
    VOIDED`, with its own `version` incremented."
    PRD 3.4: "A show falls `READY → DRAFT` in exactly two circumstances: when the
    `CONFIRMED` `PRIMARY` booking is cancelled, and when a health report leaves
    the show with no destination in `PROVISIONED` or `LIVE`."

    Design: Corner/state_machines/booking_cancel_voids_pending_disclosure
    """
    scenario = build_scenario(
        products=[],
        slots=[],
        offers=[],
        channels=[],
        confirm=False,
        acknowledge=False,
    )
    booking_id = scenario.bookings[0]["id"]
    record_id = scenario.disclosure["id"]
    assert scenario.disclosure["status"] == "PENDING"

    booking = validate_success(
        api.cancel_host_booking(
            booking_id, cancel_booking_payload(cancel_reason="HOST_ILLNESS"), PRODUCER
        )
    )

    assert booking["status"] == "CANCELLED"
    assert booking["cancel_reason"] == "HOST_ILLNESS"

    record = validate_success(api.get_disclosure_record(record_id, PRODUCER))
    assert record["status"] == "VOIDED"
    assert record["acknowledged_at"] is None
    assert record["acknowledged_late"] is False

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT", "a show that was never ready cannot revert"


def test_losing_the_primary_host_retires_the_pricing_planned_for_the_show(api):
    """When the accepted primary host withdraws from a ready show, the show drops
    back to draft and the flash pricing planned for it is retired; paperwork the
    host already acknowledged stands.

    PRD 3.4: "A show falls `READY → DRAFT` in exactly two circumstances: when the
    `CONFIRMED` `PRIMARY` booking is cancelled, and when a health report leaves
    the show with no destination in `PROVISIONED` or `LIVE`."
    PRD 3.4: "Second, every flash offer still in `SCHEDULED` whose lineup slot
    belongs to this show transitions `SCHEDULED → CANCELLED`, each bumping its own
    `version` — pricing planned for a show that can no longer air is retired
    rather than left standing."
    PRD 3.1: "every disclosure record naming this booking through
    `host_booking_id` whose status is still `PENDING` moves `PENDING → VOIDED`"

    Design: Corner/state_machines/primary_booking_cancel_reverts_ready_show_and_cancels_scheduled_offer
    """
    scenario = build_scenario(run_ready=True)
    booking_id = scenario.bookings[0]["id"]
    assert scenario.disclosure["status"] == "ACKNOWLEDGED"
    assert read_show(scenario.show_id)["status"] == "READY"

    booking = validate_success(
        api.cancel_host_booking(
            booking_id, cancel_booking_payload(cancel_reason="HOST_ILLNESS"), PRODUCER
        )
    )
    assert booking["status"] == "CANCELLED"

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT", "the show loses its readiness"
    assert show["simulcast_readiness_index"] == 100, (
        "destination health is untouched by a booking cancellation"
    )

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "CANCELLED"
    assert offer["activated_at"] is None

    record = validate_success(api.get_disclosure_record(scenario.disclosure["id"], PRODUCER))
    assert record["status"] == "ACKNOWLEDGED", (
        "the void cascade only reaches records still pending"
    )


def test_a_settled_show_accepts_no_further_lifecycle_request(api):
    """Settlement closes the book: ending again, declaring readiness again and
    signing off again are all refused, and the settlement instant is not rewritten.

    PRD 3.9: "Three conditions are checked, in ladder order: the show must be
    `ENDED` (`ERR_INVALID_SHOW_STATE`)"
    PRD 3.4: "Running the gate moves the show `DRAFT → READY` and is refused
    unless the show is currently `DRAFT` (`ERR_INVALID_SHOW_STATE`)."
    PRD 3.9: "The show must be `LIVE` (`ERR_INVALID_SHOW_STATE`)."
    PRD 3.9: "every simulcast destination of the show still in `LIVE` transitions
    `LIVE → ENDED`, and every booking of the show still in `CONFIRMED` transitions
    `CONFIRMED → COMPLETED`"

    Design: Corner/state_machines/settled_show_rejects_every_further_transition
    """
    scenario = build_scenario(take_live=True, clock_live=None)
    set_clock("2026-08-10T19:00:00Z")
    validate_success(api.end_show(scenario.show_id, PRODUCER))
    settled = validate_success(
        api.compliance_signoff_show(
            scenario.show_id,
            SIGNOFF_OFFICER,
            signoff_payload(attestation_note="All claims reviewed"),
        )
    )
    assert settled["status"] == "SETTLED"
    settled_at = settled["settled_at"]

    validate_error(
        api.end_show(scenario.show_id, PRODUCER), ApiErrorId.ERR_INVALID_SHOW_STATE
    )
    validate_error(
        api.ready_show(scenario.show_id, PRODUCER), ApiErrorId.ERR_INVALID_SHOW_STATE
    )
    validate_error(
        api.compliance_signoff_show(scenario.show_id, SIGNOFF_OFFICER, signoff_payload()),
        ApiErrorId.ERR_INVALID_SHOW_STATE,
    )

    show = read_show(scenario.show_id)
    assert show["status"] == "SETTLED"
    assert_instant(show["settled_at"], settled_at, "settled_at")
    assert show["compliance_signoff_by_user_id"] == SIGNOFF_OFFICER_ID

    booking = validate_success(api.get_host_booking(scenario.bookings[0]["id"], PRODUCER))
    assert booking["status"] == "COMPLETED"
    assert read_channel(scenario.channel_id)["status"] == "ENDED"


def test_sign_off_expires_a_basket_whose_recovery_window_has_run_out(api):
    """A basket abandoned mid-broadcast keeps a twenty-minute recovery window; once
    the show settles past that deadline the basket is written off, and with no
    money ever taken the show closes on a zero final margin.

    PRD 3.6: "The cart stamps `abandoned_at` with the logical instant and sets
    `recovery_deadline_at` to that instant plus a **recovery window of a third of
    an hour**, meaning 20 minutes."
    PRD 3.9: "transitions every cart of the show that is `ABANDONED` and whose
    `recovery_deadline_at` is at or before the logical instant `ABANDONED →
    EXPIRED` (each with `version` incremented), recomputes `abandoned_cart_count`
    and `abandonment_rate_bp`"
    PRD 3.7: "It is 10,000 multiplied by `abandoned_cart_count`, divided by the
    total number of carts ever opened on the show, rounded half up to a whole basis
    point"
    PRD 3.9: "`merchandise_revenue_cents` counts only orders whose `payment_state`
    is `CAPTURED` and whose `fulfillment_state` is not `CANCELLED`" and
    "`margin_cents` is `net_of_returns_cents` less `cogs_cents` less
    `host_commission_cents`."

    Design: Corner/state_machines/abandoned_cart_past_its_deadline_expires_at_compliance_signoff
    """
    scenario = build_scenario(take_live=True, activate=True, num_carts=1)
    line = validate_success(
        api.add_cart_item(
            scenario.cart_id,
            add_cart_item_payload(scenario.offer_id, qty=2),
            scenario.viewer_headers,
        ),
        201,
    )
    abandoned = validate_success(
        api.abandon_cart(scenario.cart_id, scenario.viewer_headers)
    )
    assert abandoned["status"] == "ABANDONED"
    assert_instant(abandoned["abandoned_at"], "2026-08-10T18:10:00Z", "abandoned_at")
    assert_instant(
        abandoned["recovery_deadline_at"],
        "2026-08-10T18:30:00Z",
        "recovery_deadline_at",
    )

    set_clock("2026-08-10T18:35:00Z")
    validate_success(api.end_show(scenario.show_id, PRODUCER))

    show = validate_success(
        api.compliance_signoff_show(
            scenario.show_id,
            SIGNOFF_OFFICER,
            signoff_payload(attestation_note="Settled with one lost cart"),
        )
    )
    assert show["status"] == "SETTLED"

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "EXPIRED", "the recovery window had already run out"
    assert_instant(
        cart["recovery_deadline_at"], "2026-08-10T18:30:00Z", "recovery_deadline_at"
    )

    assert read_line(line["id"])["state"] == "RELEASED"

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "EXPIRED"
    assert offer["held_qty"] == 0
    assert offer["sold_qty"] == 0

    assert show["abandoned_cart_count"] == 1
    assert show["abandonment_rate_bp"] == 10000, "the show's only cart was lost"
    assert show["margin_final_cents"] == 0, "no order was ever captured"
