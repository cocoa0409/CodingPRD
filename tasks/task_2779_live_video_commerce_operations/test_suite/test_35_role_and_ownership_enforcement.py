"""Who may call what, and who may act on whose row."""

from test_helpers import (
    ALL_ROLE_NAMES,
    CLOCK_EPOCH,
    MODERATOR,
    PRODUCER,
    ApiErrorId,
    acknowledge_payload,
    api_client,
    assert_disclosure_record,
    assert_instant,
    build_user_headers,
    cart_version,
    checkout_payload,
    create_chat_payload,
    create_show,
    create_show_payload,
    create_stream_channel_payload,
    held_cart_scenario,
    live_show_scenario,
    make_host_headers,
    make_viewer_headers,
    moderate,
    prepared_draft_show,
    read_cart,
    read_offer,
    register_certified_host,
    set_clock,
    submit_chat,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_role_name_outside_the_declared_seven_is_not_authenticated_at_all():
    """A caller naming a role the platform does not declare is turned away before any
    body is looked at, and the request writes nothing.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the seven
    role names declared below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)." PRD 2.7 puts that first: "**Header presence and role validity** —
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    set_clock(CLOCK_EPOCH)
    assert "NotARole" not in ALL_ROLE_NAMES, "the probe names a role the platform never declares"
    impostor = build_user_headers("11111111-1111-4111-8111-111111111111", "NotARole")

    refused = api_client.create_show(
        create_show_payload(title="Ghost Show"), impostor
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED)

    show = create_show(title="Autumn Silk Hour")
    refused_child = api_client.create_stream_channel(
        create_stream_channel_payload(show["id"]), impostor
    )
    validate_error(refused_child, ApiErrorId.ERR_UNAUTHENTICATED)

    channels, meta = validate_paginated(
        api_client.list_stream_channels(PRODUCER, {"show_id": show["id"]})
    )
    assert meta["total_count"] == 0, "the unauthenticated request wrote nothing"
    assert channels == [], "the unauthenticated request wrote nothing"


def test_a_viewer_may_not_open_a_flash_offer_for_purchase():
    """Opening an offer for purchase belongs to the merchandiser alone, so the viewer
    who would most benefit from it is refused and the offer stays scheduled.

    PRD 2.1: "If both headers are well formed but the named role is not among the
    roles authorised for the endpoint being called (see the endpoint table in §4),
    the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." PRD 4 names
    the single authorised role: "| POST | `/flash-offers/{offer_id}/activate` |
    Opens the offer for in-stream purchase | MerchandisingManager |".

    Design: Corner/rbac/viewer_cannot_activate_a_flash_offer
    """
    scenario = live_show_scenario()
    assert read_offer(scenario.offer_id)["status"] == "SCHEDULED"

    refused = api_client.activate_flash_offer(
        scenario.offer_id, make_viewer_headers(scenario.viewer_id)
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    offer = read_offer(scenario.offer_id)
    assert offer["status"] == "SCHEDULED", "the offer was never opened for purchase"
    assert offer["activated_at"] is None, "nothing was stamped"
    assert offer["version"] == scenario.offers[0]["version"], "the refusal wrote nothing"


def test_a_viewer_may_not_check_out_a_basket_belonging_to_another_viewer():
    """Ownership is decided before the version comparison, so a stranger presenting the
    basket's genuinely current version is still refused for ownership.

    PRD 2.1: "every cart, cart-line, order and interaction write compares the target
    row's `viewer_id` to `X-User-ID`, and a mismatch is likewise
    `ERR_NOT_RESOURCE_OWNER`". PRD 2.7 fixes the order: "**Resource ownership for
    entity-backed roles** — `ERR_NOT_RESOURCE_OWNER`. This applies to adding a cart
    line, abandoning a cart, recovering a cart, checking out a cart, cancelling an
    order, confirming a booking, cancelling a booking, acknowledging a disclosure
    record, and a host action on an interaction — nine operations in all."

    Design: Corner/rbac/viewer_cannot_check_out_another_viewers_cart
    """
    scenario = held_cart_scenario(1)
    owner_id = scenario.viewer_id
    stranger_id = scenario.viewers[1]["id"]
    current_version = cart_version(scenario.cart_id, owner_id)

    refused = api_client.checkout_cart(
        scenario.cart_id,
        checkout_payload(current_version),
        make_viewer_headers(stranger_id),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    cart = read_cart(scenario.cart_id, owner_id)
    assert cart["status"] == "OPEN", "the basket is still the owner's to convert"
    assert cart["checked_out_at"] is None, "nothing was converted"
    assert cart["version"] == current_version, "the refusal did not advance the basket"

    orders, meta = validate_paginated(
        api_client.list_orders(PRODUCER, {"cart_id": scenario.cart_id})
    )
    assert meta["total_count"] == 0, "no order was created"
    assert orders == [], "no order was created"


def test_a_host_may_not_speak_another_hosts_disclosure():
    """Only the booked host may acknowledge the disclosure obligation, so an equally
    certified colleague is refused and the obligation stays outstanding.

    PRD 3.1: "Only the booked host may acknowledge, and the acknowledgement must
    quote the script: the payload supplies `script_code_spoken`, which must equal the
    record's `required_script_code`, or the request is `ERR_INVALID_REQUEST`.
    `X-User-ID` must equal the `host_id` of the booking named by `host_booking_id`
    (`ERR_NOT_RESOURCE_OWNER`)".

    Design: Corner/rbac/host_cannot_acknowledge_another_hosts_disclosure
    """
    scenario = prepared_draft_show(acknowledge=False)
    colleague = register_certified_host()
    assert colleague["certification_status"] == "CERTIFIED", (
        "the colleague is no less certified than the booked host"
    )

    refused = api_client.acknowledge_disclosure_record(
        scenario.disclosure["id"],
        acknowledge_payload(),
        make_host_headers(colleague["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    record = validate_success(
        api_client.get_disclosure_record(scenario.disclosure["id"], PRODUCER)
    )
    assert_disclosure_record(record)
    assert record["status"] == "PENDING", "the obligation is still outstanding"
    assert record["acknowledged_at"] is None, "nothing was stamped"
    assert record["acknowledged_late"] is False
    assert record["version"] == scenario.disclosure["version"], "the refusal wrote nothing"


def test_a_moderator_may_decide_on_messages_but_neither_write_them_nor_read_baskets():
    """The moderator's authority covers deciding on interactions, not creating them and
    not reading commerce data.

    PRD 2.1: "A `Moderator` screens live chat and viewer questions and routes
    approved questions to the on-air host. It cannot submit an interaction, cannot
    answer a question, and cannot touch commerce state." PRD 4 lists the roles that
    may work the recovery worklist: "| GET | `/carts` | Reverse lookup: carts
    filtered by show, viewer and/or status — the recovery worklist | ShowProducer,
    MerchandisingManager, ComplianceOfficer, Viewer, PlatformAdmin |".

    Design: Corner/rbac/moderator_cannot_submit_interactions_or_list_carts
    """
    scenario = live_show_scenario()
    viewers_chat = submit_chat(
        scenario.show_id, scenario.viewer_id, body="is it in stock?"
    )
    assert viewers_chat["state"] == "PENDING_MODERATION"

    own_message = api_client.create_interaction(
        create_chat_payload(scenario.show_id, body="moderator speaking"), MODERATOR
    )
    validate_error(own_message, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    worklist = api_client.list_carts(MODERATOR, {"show_id": scenario.show_id})
    validate_error(worklist, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    rows, meta = validate_paginated(
        api_client.list_interactions(MODERATOR, {"show_id": scenario.show_id})
    )
    assert meta["total_count"] == 1, "the moderator's own submission created nothing"
    assert rows[0]["id"] == viewers_chat["id"], "the only row is the viewer's message"

    decided = moderate(viewers_chat["id"], "APPROVE")
    assert decided["state"] == "APPROVED", "deciding on a message is the moderator's own duty"
    assert_instant(decided["moderated_at"], "2026-08-10T18:10:00Z", "moderated_at")
