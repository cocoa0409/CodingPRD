"""Creation-time initialisation, server-assigned fields and request-shape refusals.

Every test builds its own world from an empty database through the public API.
"""

from test_helpers import (
    CLOCK_EPOCH,
    MERCHANDISER,
    NON_EXISTENT_UUID,
    PRODUCER,
    ApiErrorId,
    assert_flash_offer,
    assert_inventory_pool_conserved,
    assert_product,
    build_scenario,
    create_cart_payload,
    create_flash_offer_payload,
    create_host_booking_payload,
    create_lineup_slot_payload,
    create_product_payload,
    create_stream_channel_payload,
    make_viewer_headers,
    read_show,
    read_slot,
    register_viewer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_product_initialises_the_three_way_inventory_pool(api):
    """A brand-new catalogue product opens with every unit free and no claim yet
    signed off by anybody.

    PRD 3.2: "At creation, `reserved_qty` and `committed_qty` are zero,
    `available_qty` equals `on_hand_qty`, and `claim_substantiation_status`
    initialises to `UNSUBSTANTIATED` with `substantiated_by_user_id` and
    `substantiated_at` both null."

    Design: Corner/entities/product_creation_initialises_inventory_pool
    """
    set_clock(CLOCK_EPOCH)

    payload = create_product_payload(
        sku="SKU-ROBE",
        title="Silk Wrap Robe",
        base_price_cents=4000,
        unit_cost_cents=1500,
        on_hand_qty=50,
        claim_text="Machine washable mulberry silk",
    )
    product = validate_success(api.create_product(payload, MERCHANDISER), 201)

    assert_product(product)
    assert product["on_hand_qty"] == 50, "on_hand_qty is the supplied count"
    assert product["reserved_qty"] == 0, "reserved_qty starts at zero"
    assert product["committed_qty"] == 0, "committed_qty starts at zero"
    assert product["available_qty"] == 50, "available_qty equals on_hand_qty at creation"
    assert product["claim_substantiation_status"] == "UNSUBSTANTIATED"
    assert product["substantiated_by_user_id"] is None
    assert product["substantiated_at"] is None
    assert product["base_price_cents"] == 4000
    assert product["unit_cost_cents"] == 1500
    assert product["claim_text"] == "Machine washable mulberry silk"
    assert_inventory_pool_conserved(product)


def test_new_flash_offer_derives_its_allotment_ledger_and_bumps_the_slot(api):
    """The merchandiser only states the allotment ceiling; the offer's held, sold
    and remaining counters are derived by the server, and the parent lineup slot
    is versioned by the create.

    PRD 3.5: "A successful create enters `SCHEDULED` with `held_qty` and
    `sold_qty` at zero and `remaining_qty` equal to `max_qty`, and `activated_at`
    null."
    PRD 3.5: "And the slot's own `version` is incremented, which means a client
    that creates two offers against the same slot must re-read the slot between
    them."

    Design: Corner/entities/flash_offer_allotment_ledger_computed_at_creation
    """
    scenario = build_scenario(
        with_booking=False,
        with_disclosure=False,
        offers=[],
        channels=[],
    )
    slot_before = read_slot(scenario.slot_id)

    payload = create_flash_offer_payload(
        scenario.slot_id,
        slot_before["version"],
        offer_price_cents=3500,
        window_start_at="2026-08-10T18:00:00Z",
        window_end_at="2026-08-10T19:00:00Z",
        max_qty=10,
    )
    offer = validate_success(api.create_flash_offer(payload, MERCHANDISER), 201)

    assert_flash_offer(offer)
    assert offer["status"] == "SCHEDULED"
    assert offer["activated_at"] is None
    assert offer["superseded_by_offer_id"] is None
    assert offer["max_qty"] == 10
    assert offer["held_qty"] == 0
    assert offer["sold_qty"] == 0
    assert offer["remaining_qty"] == 10, "remaining_qty equals max_qty on a fresh offer"

    slot_after = read_slot(scenario.slot_id)
    assert slot_after["version"] == slot_before["version"] + 1, (
        f"slot version must advance from {slot_before['version']} to "
        f"{slot_before['version'] + 1} after an offer is created against it"
    )


def test_simulcast_destination_is_not_primary_unless_the_flag_is_supplied(api):
    """A destination attached without the reference-clock flag is a secondary
    surface, and it starts unmeasured: no latency sample, no dropped frames, no
    readiness grade.

    PRD 3.3: "The optional `is_primary` flag, false by default, marks the
    destination whose latency serves as the reference clock when the team
    discusses drift."
    PRD 3.3: "A new destination enters `DRAFT` with `readiness_index` at 0,
    `latency_ms` null, `dropped_frame_pct` at `0.0` and `health_report_count` at
    0."
    PRD 3.3: "`Show.simulcast_readiness_index` is the *minimum* `readiness_index`
    across the show's destinations whose status is `PROVISIONED` or `LIVE`; when
    that set is empty the show-level figure is 0."

    Design: Corner/entities/stream_channel_is_primary_defaults_to_false
    """
    scenario = build_scenario(
        products=[],
        with_booking=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )

    payload = create_stream_channel_payload(
        scenario.show_id, platform="SOCIAL_A", target_latency_ms=2000
    )
    assert "is_primary" not in payload, "the optional flag is deliberately omitted"
    channel = validate_success(api.create_stream_channel(payload, PRODUCER), 201)

    assert channel["is_primary"] is False, "is_primary defaults to false"
    assert channel["status"] == "DRAFT"
    assert channel["latency_ms"] is None
    assert channel["dropped_frame_pct"] == 0.0
    assert channel["readiness_index"] == 0
    assert channel["health_report_count"] == 0

    show = read_show(scenario.show_id)
    assert show["simulcast_readiness_index"] == 0, (
        "a DRAFT destination is outside the PROVISIONED/LIVE set, so the "
        "show-level figure stays 0"
    )


def test_cart_ownership_comes_from_the_header_not_from_the_body(api):
    """A shopper cannot open a cart in somebody else's name: the acting viewer's
    header identity is the cart's owner even when the body names another viewer.

    PRD 2.1: "A viewer's own identity is also the *source* of ownership on
    creation: the `viewer_id` of a new cart and the `viewer_id` of a new chat or
    question are taken from `X-User-ID` and never from the request body, even if
    the body supplies one."
    PRD 3.6: "A `Viewer` opens a cart against one show by supplying the
    `show_id`; the server sets `viewer_id` from `X-User-ID` — never from the body
    — and the cart enters `OPEN` with `recovered_count` at 0, `held_item_count`
    at 0, `pre_discount_subtotal_cents` at 0 and `bundle_discount_pct` at `0.0`."

    Design: Corner/entities/cart_viewer_id_input_ignored_system_assigns_from_header
    """
    scenario = build_scenario(
        products=[],
        with_booking=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )
    acting_viewer = register_viewer()
    other_viewer = register_viewer()

    payload = create_cart_payload(scenario.show_id, viewer_id=other_viewer["id"])
    cart = validate_success(
        api.create_cart(payload, make_viewer_headers(acting_viewer["id"])), 201
    )

    assert cart["viewer_id"] == acting_viewer["id"], (
        "the cart belongs to the header identity, not to the body's viewer_id"
    )
    assert cart["viewer_id"] != other_viewer["id"]
    assert cart["status"] == "OPEN"
    assert cart["recovered_count"] == 0
    assert cart["held_item_count"] == 0
    assert cart["pre_discount_subtotal_cents"] == 0
    assert cart["bundle_discount_pct"] == 0.0

    rows, meta = validate_paginated(
        api.list_carts(MERCHANDISER, params={"viewer_id": other_viewer["id"]})
    )
    assert meta["total_count"] == 0, "the named-but-not-acting viewer owns no cart"
    assert rows == []


def test_target_latency_below_the_contracted_floor_is_rejected(api):
    """A destination contracted at 400 milliseconds glass-to-glass is outside the
    range the platform supports, so no destination row is created at all.

    PRD 3.3: "The producer attaches a **simulcast destination** for each place
    the broadcast appears, naming the `show_id`, the `platform` — one of
    `FLAGSHIP_APP`, `SOCIAL_A`, `SOCIAL_B` or `PARTNER_APP` — and the contracted
    glass-to-glass `target_latency_ms` for that destination, which must be
    between 500 and 8,000 inclusive."
    PRD 2.7: "required fields present, enum values inside their declared sets,
    numbers inside their declared ranges, timestamps well formed, and every
    declared ordering constraint satisfied"

    Design: Corner/entities/stream_channel_target_latency_below_range_rejected
    """
    scenario = build_scenario(
        products=[],
        with_booking=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )

    resp = api.create_stream_channel(
        create_stream_channel_payload(
            scenario.show_id, platform="SOCIAL_B", target_latency_ms=400
        ),
        PRODUCER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api.list_stream_channels(PRODUCER, params={"show_id": scenario.show_id})
    )
    assert meta["total_count"] == 0, "a rejected create writes no destination row"
    assert rows == []


def test_booking_without_a_call_time_is_rejected(api):
    """The occupied interval is not optional: a booking that names no call time
    has no interval to protect, so the platform refuses it rather than inventing
    one.

    PRD 3.1: "Booking a host onto a show is again the producer's act, and the
    payload names the `show_id` and the `host_id` alongside a `role` of either
    `PRIMARY` or `GUEST`, the occupied interval as `call_time_at` and
    `release_time_at`, and a flat appearance `fee_cents` of zero or more."
    PRD 2.7: "required fields present, enum values inside their declared sets,
    numbers inside their declared ranges, timestamps well formed, and every
    declared ordering constraint satisfied"

    Design: Corner/entities/host_booking_missing_call_time_returns_invalid_request
    """
    scenario = build_scenario(
        products=[],
        certify=False,
        with_booking=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )

    payload = create_host_booking_payload(
        scenario.show_id,
        scenario.host_id,
        role="PRIMARY",
        release_time_at="2026-08-10T20:30:00Z",
        fee_cents=50000,
    )
    payload.pop("call_time_at")

    validate_error(
        api.create_host_booking(payload, PRODUCER), ApiErrorId.ERR_INVALID_REQUEST
    )

    rows, meta = validate_paginated(
        api.list_host_bookings(PRODUCER, params={"show_id": scenario.show_id})
    )
    assert meta["total_count"] == 0, "a rejected create books nobody"
    assert rows == []


def test_lineup_slot_naming_an_unknown_product_is_not_found(api):
    """A lineup segment must point at a product that exists in the catalogue; a
    body foreign key that resolves to nothing is a not-found on the product, not
    a malformed request.

    PRD 2.6: "Foreign keys supplied in a request body resolve to the same code
    family: an unknown `show_id`, `host_id`, `product_id`, `lineup_slot_id`,
    `flash_offer_id`, `host_booking_id` or `viewer_id` in a body yields that
    entity's not-found error."
    PRD 2.7: "**Body foreign-key existence** — the same 404 family. This applies
    to creating a host booking, a lineup slot, a flash offer, a stream channel, a
    disclosure record, a cart, a cart line, an interaction, and a replay
    conversion."

    Design: Corner/entities/lineup_slot_unknown_product_returns_not_found
    """
    scenario = build_scenario(
        products=[],
        with_booking=False,
        with_disclosure=False,
        slots=[],
        offers=[],
        channels=[],
    )

    payload = create_lineup_slot_payload(
        scenario.show_id,
        NON_EXISTENT_UUID,
        slot_sequence=1,
        planned_start_at="2026-08-10T18:05:00Z",
        planned_end_at="2026-08-10T18:35:00Z",
        planned_qty=5,
    )
    validate_error(
        api.create_lineup_slot(payload, MERCHANDISER), ApiErrorId.ERR_PRODUCT_NOT_FOUND
    )

    rows, meta = validate_paginated(
        api.list_lineup_slots(MERCHANDISER, params={"show_id": scenario.show_id})
    )
    assert meta["total_count"] == 0, "a rejected create adds no segment to the lineup"
    assert rows == []
