"""Unknown identifiers in a path, and replayed transitions each answering for themselves."""

import pytest

from test_helpers import (
    ADMIN,
    MERCHANDISER,
    MODERATOR,
    NON_EXISTENT_UUID,
    PATH_ID_NOT_FOUND,
    PRODUCER,
    ApiErrorId,
    acknowledge_payload,
    add_cart_item_payload,
    api_client,
    captured_order_scenario,
    live_show_scenario,
    live_show_with_active_offer,
    make_host_headers,
    make_viewer_headers,
    moderate,
    moderate_payload,
    order_scenario,
    read_channel,
    read_offer,
    read_order,
    read_viewer,
    submit_chat,
    validate_error,
    validate_success,
)

READ_BY_PATH_ID = {
    "host_id": api_client.get_host,
    "product_id": api_client.get_product,
    "viewer_id": api_client.get_viewer,
    "show_id": api_client.get_show,
    "channel_id": api_client.get_stream_channel,
    "booking_id": api_client.get_host_booking,
    "slot_id": api_client.get_lineup_slot,
    "offer_id": api_client.get_flash_offer,
    "record_id": api_client.get_disclosure_record,
    "cart_id": api_client.get_cart,
    "item_id": api_client.get_cart_item,
    "order_id": api_client.get_order,
    "interaction_id": api_client.get_interaction,
}


@pytest.mark.parametrize("path_id", sorted(READ_BY_PATH_ID))
def test_every_path_identifier_has_its_own_not_found_answer(path_id):
    """Each of the thirteen path identifiers reports the absence of its own resource
    with that resource's own not-found code.

    PRD 2.6: "The path identifiers this API uses are `host_id`, `product_id`,
    `viewer_id`, `show_id`, `channel_id`, `booking_id`, `slot_id`, `offer_id`,
    `record_id`, `cart_id`, `item_id`, `order_id`, and `interaction_id`. Each maps to
    its own not-found code — `ERR_HOST_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_VIEWER_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_STREAM_CHANNEL_NOT_FOUND`,
    `ERR_HOST_BOOKING_NOT_FOUND`, `ERR_LINEUP_SLOT_NOT_FOUND`,
    `ERR_FLASH_OFFER_NOT_FOUND`, `ERR_DISCLOSURE_RECORD_NOT_FOUND`,
    `ERR_CART_NOT_FOUND`, `ERR_CART_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and
    `ERR_INTERACTION_NOT_FOUND` — each returned with HTTP 404."

    Design: Corner/errors/every_path_id_not_found_error_is_triggerable
    """
    response = READ_BY_PATH_ID[path_id](NON_EXISTENT_UUID, ADMIN)
    validate_error(response, PATH_ID_NOT_FOUND[path_id])


def test_provisioning_a_destination_that_is_already_on_air_is_a_channel_state_error():
    """Replaying the provisioning of a destination already carrying the broadcast is
    answered by the destination's own state error, not the show's.

    PRD 3.3: "Provisioning a destination that is already `PROVISIONED`, `LIVE` or
    `ENDED` is `ERR_INVALID_CHANNEL_STATE`, and provisioning against a show that has
    already gone `LIVE` or beyond is `ERR_INVALID_SHOW_STATE`." PRD 2.7 fixes which
    of the two answers: "**Own-state legality** — the target resource must currently
    be in a state from which the requested transition is declared."

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario = live_show_scenario()
    before = read_channel(scenario.channel_id)
    assert before["status"] == "LIVE", "the destination is carrying the broadcast"

    replayed = api_client.provision_stream_channel(scenario.channel_id, PRODUCER)
    validate_error(replayed, ApiErrorId.ERR_INVALID_CHANNEL_STATE)

    after = read_channel(scenario.channel_id)
    assert after["status"] == "LIVE", "the refused replay left the destination on air"
    assert after["version"] == before["version"], "and wrote nothing"


def test_acknowledging_a_disclosure_twice_is_a_disclosure_state_error():
    """A disclosure obligation that has already been spoken cannot be spoken again.

    PRD 3.1: "the record must still be `PENDING` — a record already `ACKNOWLEDGED`,
    or one already `VOIDED` by a booking cancellation, is refused with
    `ERR_INVALID_DISCLOSURE_STATE`".

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario = live_show_scenario()
    record_id = scenario.disclosure["id"]
    before = validate_success(api_client.get_disclosure_record(record_id, PRODUCER))
    assert before["status"] == "ACKNOWLEDGED", "the host already spoke the script"

    replayed = api_client.acknowledge_disclosure_record(
        record_id, acknowledge_payload(), make_host_headers(scenario.host_id)
    )
    validate_error(replayed, ApiErrorId.ERR_INVALID_DISCLOSURE_STATE)

    after = validate_success(api_client.get_disclosure_record(record_id, PRODUCER))
    assert after["status"] == "ACKNOWLEDGED", "the record stands where it was"
    assert after["version"] == before["version"], "and the replay wrote nothing"


def test_activating_an_already_purchasable_offer_is_an_offer_state_error():
    """An offer that is already open for purchase cannot be opened a second time.

    PRD 3.5: "the offer must be `SCHEDULED` (an already-active, exhausted, expired,
    cancelled or superseded offer yields `ERR_INVALID_OFFER_STATE`)".

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario = live_show_with_active_offer()
    before = read_offer(scenario.offer_id)
    assert before["status"] == "ACTIVE", "the offer is already purchasable"

    replayed = api_client.activate_flash_offer(scenario.offer_id, MERCHANDISER)
    validate_error(replayed, ApiErrorId.ERR_INVALID_OFFER_STATE)

    after = read_offer(scenario.offer_id)
    assert after["status"] == "ACTIVE", "the offer is still purchasable"
    assert after["version"] == before["version"], "and the replay wrote nothing"


def test_adding_a_line_to_a_converted_basket_is_a_cart_state_error():
    """A basket that has already been converted into an order cannot take another
    line, however open the offer behind it still is.

    PRD 3.6: "The gauntlet, in ladder order, is: the acting viewer must own the cart
    (`ERR_NOT_RESOURCE_OWNER`); the cart must be `OPEN` (`ERR_INVALID_CART_STATE`)".

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario, order = order_scenario(qty=1)
    offer_before = read_offer(scenario.offer_id)
    assert offer_before["status"] == "ACTIVE", "the offer itself is not the obstacle"

    replayed = api_client.add_cart_item(
        scenario.cart_id,
        add_cart_item_payload(scenario.offer_id, 1),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(replayed, ApiErrorId.ERR_INVALID_CART_STATE)

    offer_after = read_offer(scenario.offer_id)
    assert offer_after["held_qty"] == 0, "the refused add held nothing"
    assert offer_after["version"] == offer_before["version"], "and wrote nothing"
    assert read_order(order["id"])["payment_state"] == "AUTHORIZED", (
        "the order the basket already became is untouched"
    )


def test_capturing_an_already_captured_order_is_an_order_state_error():
    """Money is taken once: a second capture of the same order is refused and the
    accrued commission is not doubled.

    PRD 3.7: "It requires `payment_state` to be `AUTHORIZED`
    (`ERR_INVALID_ORDER_STATE`) and the show to be in one of those two statuses
    (`ERR_INVALID_SHOW_STATE`)."

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario, order = captured_order_scenario(qty=1)
    assert order["payment_state"] == "CAPTURED", "the money is already taken"
    assert order["fulfillment_state"] == "ALLOCATED"

    replayed = api_client.capture_order(order["id"], MERCHANDISER)
    validate_error(replayed, ApiErrorId.ERR_INVALID_ORDER_STATE)

    after = read_order(order["id"])
    assert after["payment_state"] == "CAPTURED", "the order stays captured"
    assert after["version"] == order["version"], "the replay wrote nothing"
    assert after["host_commission_accrued_cents"] == order["host_commission_accrued_cents"], (
        "the commission was not accrued twice"
    )


def test_moderating_an_already_approved_message_is_an_interaction_state_error():
    """A message that has already cleared moderation cannot be blocked afterwards, and
    the refused block lays no strike on the viewer.

    PRD 3.8: "Only interactions in `PENDING_MODERATION` may be moderated — an
    interaction already `APPROVED`, already `BLOCKED`, already `QUEUED`, or in any
    other state is `ERR_INVALID_INTERACTION_STATE`".

    Design: Corner/errors/repeating_a_transition_returns_that_entity_s_own_state_error
    """
    scenario = live_show_scenario()
    chat = submit_chat(scenario.show_id, scenario.viewer_id, body="Loving this robe")
    approved = moderate(chat["id"], "APPROVE")
    assert approved["state"] == "APPROVED", "the message is already published"

    replayed = api_client.moderate_interaction(
        chat["id"], moderate_payload("BLOCK", blocked_reason="ABUSE"), MODERATOR
    )
    validate_error(replayed, ApiErrorId.ERR_INVALID_INTERACTION_STATE)

    after = validate_success(api_client.get_interaction(chat["id"], MODERATOR))
    assert after["state"] == "APPROVED", "the message stays published"
    assert after["version"] == approved["version"], "the replay wrote nothing"
    assert read_viewer(scenario.viewer_id)["strike_count"] == 0, (
        "a refused block lays no strike on the viewer"
    )
