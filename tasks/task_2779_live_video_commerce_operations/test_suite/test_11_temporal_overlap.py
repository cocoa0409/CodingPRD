"""Two overlap rules on two different resources, with opposite interval semantics."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant,
    build_scenario,
    cancel_booking,
    create_flash_offer_payload,
    create_host_booking_payload,
    create_show,
    create_slot,
    create_substantiated_product,
    make_merchandising_manager_headers,
    make_show_producer_headers,
    read_offer,
    read_slot,
    validate_error,
    validate_success,
)

PRODUCER_HEADERS = make_show_producer_headers()
MERCHANDISER_HEADERS = make_merchandising_manager_headers()

TOUCHING_BOOKING = {
    "call_time_at": "2026-08-10T20:30:00Z",
    "release_time_at": "2026-08-10T22:00:00Z",
    "fee_cents": 30000,
}


def _host_with_one_pending_booking_and_two_spare_shows():
    """b1 runs 17:00-20:30Z; a late show and a morning show wait for competitors."""
    scenario = build_scenario(
        confirm=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )
    late_show = create_show(
        title="Late Silk",
        scheduled_start_at="2026-08-10T21:30:00Z",
        scheduled_end_at="2026-08-10T23:00:00Z",
    )
    morning_show = create_show(
        title="Morning Silk",
        scheduled_start_at="2026-08-10T14:30:00Z",
        scheduled_end_at="2026-08-10T16:00:00Z",
    )
    return scenario, late_show, morning_show


def test_a_booking_starting_exactly_when_another_releases_still_collides():
    """The buffer, not raw intersection, decides: 20:30Z is inside 20:30Z plus 45 minutes.

    The PRD: "each booked interval is expanded by a turnaround buffer of three
    quarters of an hour on both sides before it is compared against the host's
    other bookings", over "the existing bookings of the same host_id whose status
    is PENDING or CONFIRMED".

    Design: Difficulty/resource_temporal_overlap/host_booking_half_open_interval_with_buffer
    """
    scenario, late_show, _morning = _host_with_one_pending_booking_and_two_spare_shows()

    response = api_client.create_host_booking(
        create_host_booking_payload(late_show["id"], scenario.host_id, **TOUCHING_BOOKING),
        PRODUCER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_HOST_BOOKING_OVERLAP.value)


def test_a_booking_releasing_exactly_45_minutes_earlier_is_accepted():
    """16:15Z advanced by 45 minutes is 17:00Z, which is not earlier than 17:00Z.

    The PRD: "the new booking is rejected when the new call_time_at is earlier than
    the existing release_time_at advanced by 45 minutes and the existing
    call_time_at is earlier than the new release_time_at advanced by 45 minutes.
    Both conditions must hold for a collision."

    Design: Difficulty/resource_temporal_overlap/host_booking_half_open_interval_with_buffer
    """
    scenario, _late, morning_show = _host_with_one_pending_booking_and_two_spare_shows()

    accepted = validate_success(
        api_client.create_host_booking(
            create_host_booking_payload(
                morning_show["id"],
                scenario.host_id,
                call_time_at="2026-08-10T14:00:00Z",
                release_time_at="2026-08-10T16:15:00Z",
                fee_cents=20000,
            ),
            PRODUCER_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "PENDING"
    assert_instant(accepted["release_time_at"], "2026-08-10T16:15:00Z", "release_time_at")


def test_cancelling_the_incumbent_records_the_reason():
    """A PENDING booking can be cancelled and keeps the reason it was cancelled for.

    The PRD: cancellation "requires a cancel_reason, and works from either PENDING
    or CONFIRMED, in both cases while the show is still in DRAFT or READY. Both
    branches record cancel_reason, increment the booking's version".

    Design: Difficulty/resource_temporal_overlap/host_booking_half_open_interval_with_buffer
    """
    scenario, _late, _morning = _host_with_one_pending_booking_and_two_spare_shows()

    cancel_booking(scenario.booking["id"], cancel_reason="HOST_ILLNESS")

    booking = validate_success(
        api_client.get_host_booking(scenario.booking["id"], PRODUCER_HEADERS)
    )
    assert booking["status"] == "CANCELLED"
    assert booking["cancel_reason"] == "HOST_ILLNESS"


def test_the_touching_booking_is_accepted_once_the_incumbent_is_cancelled():
    """Cancelling removes the incumbent from the candidate set, so the collision vanishes.

    The PRD: "Cancelled and completed bookings are invisible to this check."

    Design: Difficulty/resource_temporal_overlap/host_booking_half_open_interval_with_buffer
    """
    scenario, late_show, _morning = _host_with_one_pending_booking_and_two_spare_shows()

    api_client.create_host_booking(
        create_host_booking_payload(late_show["id"], scenario.host_id, **TOUCHING_BOOKING),
        PRODUCER_HEADERS,
    )
    cancel_booking(scenario.booking["id"], cancel_reason="HOST_ILLNESS")

    replayed = validate_success(
        api_client.create_host_booking(
            create_host_booking_payload(late_show["id"], scenario.host_id, **TOUCHING_BOOKING),
            PRODUCER_HEADERS,
        ),
        201,
    )
    assert replayed["status"] == "PENDING"
    assert replayed["show_id"] == late_show["id"]


def _same_product_on_a_second_show():
    """Show 1 holds an 18:00-19:00Z offer on the robe; show 4 has slots for robe and sash."""
    scenario = build_scenario(
        with_booking=False,
        with_disclosure=False,
        num_viewers=0,
        channels=[],
    )
    encore = create_show(
        title="Silk Encore",
        scheduled_start_at="2026-08-10T19:00:00Z",
        scheduled_end_at="2026-08-10T21:00:00Z",
    )
    robe_slot = create_slot(
        encore["id"],
        scenario.product_id,
        slot_sequence=1,
        planned_start_at="2026-08-10T19:05:00Z",
        planned_end_at="2026-08-10T19:35:00Z",
        planned_qty=10,
    )
    sash = create_substantiated_product(
        evidence_ref="LAB-89",
        sku="SKU-SASH",
        title="Silk Sash",
        base_price_cents=2500,
        unit_cost_cents=900,
        on_hand_qty=40,
        claim_text="Hand rolled hem",
    )
    sash_slot = create_slot(
        encore["id"],
        sash["id"],
        slot_sequence=2,
        planned_start_at="2026-08-10T19:40:00Z",
        planned_end_at="2026-08-10T20:00:00Z",
        planned_qty=10,
    )
    return scenario, robe_slot, sash_slot


def test_a_window_starting_the_instant_another_ends_collides_on_the_same_product():
    """The window interval is closed with no buffer, so touching windows collide.

    The PRD: "the create is rejected when the new window_start_at is at or before
    the existing window_end_at and the existing window_start_at is at or before the
    new window_end_at". Because no buffer is applied, "touching windows collide: an
    offer starting at the exact instant an existing offer ends is rejected with
    ERR_OFFER_WINDOW_OVERLAP".

    Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_per_product
    """
    _scenario, robe_slot, _sash_slot = _same_product_on_a_second_show()

    response = api_client.create_flash_offer(
        create_flash_offer_payload(
            robe_slot["id"],
            read_slot(robe_slot["id"])["version"],
            offer_price_cents=3400,
            window_start_at="2026-08-10T19:00:00Z",
            window_end_at="2026-08-10T19:30:00Z",
            max_qty=5,
        ),
        MERCHANDISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP.value)


def test_a_window_starting_one_minute_after_the_incumbent_ends_is_accepted():
    """19:01Z is not at or before 19:00Z, so the first condition fails and the create stands.

    The PRD: "A successful create enters SCHEDULED with held_qty and sold_qty at
    zero and remaining_qty equal to max_qty".

    Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_per_product
    """
    _scenario, robe_slot, _sash_slot = _same_product_on_a_second_show()

    api_client.create_flash_offer(
        create_flash_offer_payload(
            robe_slot["id"],
            read_slot(robe_slot["id"])["version"],
            offer_price_cents=3400,
            window_start_at="2026-08-10T19:00:00Z",
            window_end_at="2026-08-10T19:30:00Z",
            max_qty=5,
        ),
        MERCHANDISER_HEADERS,
    )
    accepted = validate_success(
        api_client.create_flash_offer(
            create_flash_offer_payload(
                robe_slot["id"],
                read_slot(robe_slot["id"])["version"],
                offer_price_cents=3400,
                window_start_at="2026-08-10T19:01:00Z",
                window_end_at="2026-08-10T19:30:00Z",
                max_qty=5,
            ),
            MERCHANDISER_HEADERS,
        ),
        201,
    )

    offer = read_offer(accepted["id"])
    assert offer["status"] == "SCHEDULED"
    assert_instant(offer["window_start_at"], "2026-08-10T19:01:00Z", "window_start_at")
    assert offer["remaining_qty"] == 5


def test_an_offer_on_another_slot_never_supersedes_the_incumbent():
    """Supersession is scoped to one lineup slot, while the overlap check spans shows.

    The PRD: "Any offer already standing on the same lineup slot in status
    SCHEDULED transitions SCHEDULED -> SUPERSEDED, has its
    superseded_by_offer_id set to the new offer's id".

    Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_per_product
    """
    scenario, robe_slot, _sash_slot = _same_product_on_a_second_show()

    api_client.create_flash_offer(
        create_flash_offer_payload(
            robe_slot["id"],
            read_slot(robe_slot["id"])["version"],
            offer_price_cents=3400,
            window_start_at="2026-08-10T19:01:00Z",
            window_end_at="2026-08-10T19:30:00Z",
            max_qty=5,
        ),
        MERCHANDISER_HEADERS,
    )

    incumbent = read_offer(scenario.offer_id)
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["superseded_by_offer_id"] is None


def test_a_different_product_may_reuse_the_window_verbatim():
    """The collision set is scoped through the slot's product, so the sash is free.

    The PRD: "offer windows are checked for collision per product across every
    show, not merely within one show or one slot. Over all existing offers whose
    status is SCHEDULED, ACTIVE or EXHAUSTED and whose lineup slot points at the
    same product_id as the new offer's slot".

    Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_per_product
    """
    _scenario, _robe_slot, sash_slot = _same_product_on_a_second_show()

    accepted = validate_success(
        api_client.create_flash_offer(
            create_flash_offer_payload(
                sash_slot["id"],
                read_slot(sash_slot["id"])["version"],
                offer_price_cents=2000,
                window_start_at="2026-08-10T18:00:00Z",
                window_end_at="2026-08-10T19:00:00Z",
                max_qty=5,
            ),
            MERCHANDISER_HEADERS,
        ),
        201,
    )
    assert read_offer(accepted["id"])["status"] == "SCHEDULED"
