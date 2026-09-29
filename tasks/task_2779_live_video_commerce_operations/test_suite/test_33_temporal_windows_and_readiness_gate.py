"""The go-live window, the flash-offer window, the readiness gate and slot versions."""

from test_helpers import (
    CLOCK_EPOCH,
    DEFAULT_PRODUCT,
    MERCHANDISER,
    PRODUCER,
    ApiErrorId,
    activate_offer,
    api_client,
    assert_flash_offer,
    assert_host_booking,
    assert_instant,
    assert_show,
    book_host,
    build_scenario,
    create_flash_offer_payload,
    create_host_booking_payload,
    create_offer,
    create_product,
    create_show,
    create_slot,
    go_live,
    prepared_draft_show,
    read_channel,
    read_offer,
    read_show,
    read_slot,
    ready_show_scenario,
    register_certified_host,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SASH = {
    "sku": "SKU-SASH",
    "title": "Silk Sash",
    "base_price_cents": 2500,
    "unit_cost_cents": 800,
    "on_hand_qty": 30,
    "evidence_ref": "LAB-89",
}


def test_going_live_one_minute_before_the_early_window_opens_is_refused():
    """A producer may open the stream half an hour early but not thirty-one minutes
    early, and the window opens exactly on the minute.

    PRD 3.4: "the logical instant must be at or after `scheduled_start_at` minus 30
    minutes, and strictly before `scheduled_end_at`. A producer trying to open the
    stream 31 minutes early, or one second after the planned end, is refused with
    `ERR_GO_LIVE_WINDOW_CLOSED`."

    Design: Corner/validations/go_live_one_minute_before_the_early_window_rejected
    """
    scenario = ready_show_scenario()

    set_clock("2026-08-10T17:29:00Z")
    too_early = api_client.go_live_show(scenario.show_id, PRODUCER)
    validate_error(too_early, ApiErrorId.ERR_GO_LIVE_WINDOW_CLOSED)

    still_ready = read_show(scenario.show_id)
    assert_show(still_ready)
    assert still_ready["status"] == "READY", "the refused attempt left the show ready"
    assert still_ready["went_live_at"] is None, "the stream was never opened"
    assert read_channel(scenario.channel_id)["status"] == "PROVISIONED", (
        "the destination is still waiting to carry the broadcast"
    )

    set_clock("2026-08-10T17:30:00Z")
    live = go_live(scenario.show_id)
    assert live["status"] == "LIVE", "thirty minutes early is inside the window"
    assert_instant(live["went_live_at"], "2026-08-10T17:30:00Z", "went_live_at")
    assert read_channel(scenario.channel_id)["status"] == "LIVE", (
        "the destination carries the broadcast"
    )


def test_activating_an_offer_on_the_window_end_is_accepted_and_one_second_later_is_not():
    """The flash-offer window is closed at both ends: activation at the very instant
    the window ends is accepted, and one second later it is refused.

    PRD 3.5: "the logical instant must lie inside the closed window — at or after
    `window_start_at` and at or before `window_end_at` — with anything outside
    refused as `ERR_OFFER_WINDOW_CLOSED`". PRD 3.5 calls the window closed: "both
    `window_start_at` and `window_end_at` are themselves inside validity."

    Design: Corner/validations/offer_activate_at_the_window_end_accepted_one_second_later_rejected
    """
    scenario = build_scenario(
        products=[dict(DEFAULT_PRODUCT), dict(SASH)],
        slots=[
            {
                "slot_sequence": 1,
                "planned_start_at": "2026-08-10T18:05:00Z",
                "planned_end_at": "2026-08-10T18:35:00Z",
                "planned_qty": 20,
            },
            {
                "product_index": 1,
                "slot_sequence": 2,
                "planned_start_at": "2026-08-10T18:40:00Z",
                "planned_end_at": "2026-08-10T19:00:00Z",
                "planned_qty": 10,
            },
        ],
        offers=[{"offer_price_cents": 3500}, {"slot_index": 1, "offer_price_cents": 2000}],
        take_live=True,
        clock_live="2026-08-10T19:00:00Z",
    )

    on_the_boundary = activate_offer(scenario.offers[1]["id"])
    assert_flash_offer(on_the_boundary)
    assert on_the_boundary["status"] == "ACTIVE", "the closing instant is inside the window"
    assert_instant(on_the_boundary["activated_at"], "2026-08-10T19:00:00Z", "activated_at")
    assert on_the_boundary["remaining_qty"] == 10, "activation recomputes the allotment"

    set_clock("2026-08-10T19:00:01Z")
    one_second_late = api_client.activate_flash_offer(scenario.offers[0]["id"], MERCHANDISER)
    validate_error(one_second_late, ApiErrorId.ERR_OFFER_WINDOW_CLOSED)

    unopened = read_offer(scenario.offers[0]["id"])
    assert unopened["status"] == "SCHEDULED", "the refused offer never opened"
    assert unopened["activated_at"] is None
    assert unopened["version"] == scenario.offers[0]["version"], (
        "a refused activation writes nothing"
    )


def test_the_readiness_gate_refuses_a_show_with_no_provisioned_destination():
    """A show whose only simulcast destination is still a draft cannot reach
    readiness, and its show-level index stays at zero.

    PRD 3.4: "At least one of the show's destinations must be `PROVISIONED`. If none
    is, the gate fails with `ERR_SIMULCAST_NOT_READY`." PRD 3.3 makes
    `Show.simulcast_readiness_index` the minimum readiness index "across the show's
    destinations whose status is `PROVISIONED` or `LIVE`; when that set is empty the
    show-level figure is 0."

    Design: Corner/errors/ready_without_a_provisioned_channel_returns_simulcast_not_ready
    """
    scenario = prepared_draft_show(
        channels=[
            {
                "platform": "FLAGSHIP_APP",
                "target_latency_ms": 1500,
                "is_primary": True,
                "provision": False,
            }
        ]
    )

    refused = api_client.ready_show(scenario.show_id, PRODUCER)
    validate_error(refused, ApiErrorId.ERR_SIMULCAST_NOT_READY)

    show = read_show(scenario.show_id)
    assert show["status"] == "DRAFT", "the show cannot leave draft without a destination"
    assert show["simulcast_readiness_index"] == 0, (
        "with no provisioned destination the show-level index is zero"
    )
    channel = read_channel(scenario.channel_id)
    assert channel["status"] == "DRAFT", "the destination was never provisioned"
    assert channel["readiness_index"] == 0
    assert channel["health_report_count"] == 0, "an unprovisioned destination files no health"
    assert channel["latency_ms"] is None


def test_the_readiness_gate_refuses_a_show_whose_primary_booking_is_unconfirmed():
    """A booked but unconfirmed lead presenter is not a confirmed primary, so the
    readiness gate reports a missing primary host.

    PRD 3.4: "Exactly one booking of this show must carry `role` equal to `PRIMARY`
    with status `CONFIRMED`; zero such bookings fails with
    `ERR_PRIMARY_HOST_MISSING`."

    Design: Corner/errors/ready_with_an_unconfirmed_primary_returns_primary_host_missing
    """
    scenario = prepared_draft_show(confirm=False, with_disclosure=False)

    refused = api_client.ready_show(scenario.show_id, PRODUCER)
    validate_error(refused, ApiErrorId.ERR_PRIMARY_HOST_MISSING)

    assert read_show(scenario.show_id)["status"] == "DRAFT", "the gate stayed shut"
    booking = validate_success(
        api_client.get_host_booking(scenario.booking["id"], PRODUCER)
    )
    assert_host_booking(booking)
    assert booking["role"] == "PRIMARY", "the show does have a primary booking"
    assert booking["status"] == "PENDING", "but the host has not accepted it"
    assert read_channel(scenario.channel_id)["readiness_index"] == 100, (
        "the simulcast side of the picture was never the problem"
    )


def test_a_second_lead_presenter_is_refused_while_a_supporting_one_is_welcome():
    """A show carries at most one lead presenter, so a second primary booking is
    refused; the same host is booked without objection as a guest.

    PRD 3.1: "A show has at most one lead presenter: if the show already carries a
    booking with `role` equal to `PRIMARY` whose status is `PENDING` or `CONFIRMED`,
    a second `PRIMARY` booking is refused with `ERR_PRIMARY_HOST_CONFLICT`. Any
    number of `GUEST` bookings is permitted."

    Design: Corner/validations/second_primary_booking_on_the_same_show_rejected_guest_role_accepted
    """
    scenario = prepared_draft_show()
    assert scenario.booking["role"] == "PRIMARY"
    assert scenario.booking["status"] == "CONFIRMED", "the show already has its lead"

    understudy = register_certified_host()
    clash = api_client.create_host_booking(
        create_host_booking_payload(scenario.show_id, understudy["id"], role="PRIMARY"),
        PRODUCER,
    )
    validate_error(clash, ApiErrorId.ERR_PRIMARY_HOST_CONFLICT)

    guest = book_host(scenario.show_id, understudy["id"], role="GUEST")
    assert_host_booking(guest)
    assert guest["role"] == "GUEST", "a supporting booking for the same host is permitted"
    assert guest["status"] == "PENDING", "a booking is not real until the talent accepts"
    assert guest["show_id"] == scenario.show_id

    confirmed, meta = validate_paginated(
        api_client.list_host_bookings(
            PRODUCER, {"show_id": scenario.show_id, "status": "CONFIRMED"}
        )
    )
    assert meta["total_count"] == 1, "exactly one booking of this show is confirmed"
    assert confirmed[0]["id"] == scenario.booking["id"], "and it is the lead presenter's"


def test_creating_an_offer_from_a_stale_view_of_the_slot_is_refused():
    """A merchandiser who creates a second offer against a slot without re-reading the
    slot is refused, because the first create advanced the slot's version.

    PRD 2.8: "Creating a flash offer — `POST /flash-offers` — requires
    `expected_lineup_slot_version` to equal the current `version` of the
    `LineupSlot` named by `lineup_slot_id`. If they differ, the create is rejected
    with `ERR_STALE_LINEUP_SLOT_VERSION` (HTTP 412) and nothing is written."
    PRD 3.5: "And the slot's own `version` is incremented, which means a client that
    creates two offers against the same slot must re-read the slot between them."

    Design: Corner/cross_cutting_complexity_layers/flash_offer_create_with_a_stale_lineup_slot_version_rejected
    """
    set_clock(CLOCK_EPOCH)
    product = create_product(
        **{k: v for k, v in DEFAULT_PRODUCT.items() if k != "evidence_ref"}
    )
    show = create_show()
    slot = create_slot(show["id"], product["id"])
    first_view = slot["version"]

    first_offer = create_offer(
        slot["id"],
        first_view,
        offer_price_cents=3500,
        window_start_at="2026-08-10T18:00:00Z",
        window_end_at="2026-08-10T18:30:00Z",
    )
    assert_flash_offer(first_offer)
    assert first_offer["status"] == "SCHEDULED"
    second_view = read_slot(slot["id"])["version"]
    assert second_view == first_view + 1, "the create advanced the slot the client last read"

    stale = api_client.create_flash_offer(
        create_flash_offer_payload(
            slot["id"],
            first_view,
            offer_price_cents=3000,
            window_start_at="2026-08-10T18:35:00Z",
            window_end_at="2026-08-10T19:00:00Z",
        ),
        MERCHANDISER,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LINEUP_SLOT_VERSION)

    offers, meta = validate_paginated(
        api_client.list_flash_offers(MERCHANDISER, {"lineup_slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1, "the refused create wrote no offer"
    assert offers[0]["id"] == first_offer["id"]
    assert read_slot(slot["id"])["version"] == second_view, "and it did not touch the slot"
    assert read_offer(first_offer["id"])["status"] == "SCHEDULED", (
        "the standing offer was not superseded by a refused create"
    )

    replacement = create_offer(
        slot["id"],
        second_view,
        offer_price_cents=3000,
        window_start_at="2026-08-10T18:35:00Z",
        window_end_at="2026-08-10T19:00:00Z",
    )
    assert replacement["status"] == "SCHEDULED", "a current view of the slot is accepted"
    retired = read_offer(first_offer["id"])
    assert retired["status"] == "SUPERSEDED", (
        "a new offer retires the scheduled offer standing on the same slot"
    )
    assert retired["superseded_by_offer_id"] == replacement["id"], (
        "the retired offer points at its replacement"
    )
