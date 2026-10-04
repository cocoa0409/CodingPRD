"""Invalid transitions, terminal-state lockdown and repeat-transition refusals."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]


def _draft_event_with_listing(sku="NW-ST-1"):
    """Vendor + shop + DRAFT event with one listing whose starts_at has passed."""
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"}, MERCH))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"}, MERCH))
    event = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Fall Outerwear Daily",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 14}, MERCH))
    listing = get_success_data(api_client.create_listing({
        "event_id": event["id"], "vendor_sku": sku, "unit_price_cents": 100,
        "vendor_unit_cost_cents": 60, "allocation_units": 4,
        "reveal_at": "2026-09-01T00:00:00Z"}, MERCH))
    return vendor, shop, event, listing


def test_a_draft_event_may_not_be_launched_directly(api, merchandiser_headers):
    """PRD §2.12: "Then the platform asks whether the requested transition exists from
    the addressed resource's current state at all; a request that names a transition
    the state machine does not permit is refused with `ERR_INVALID_STATE`, and nothing
    else in the request is evaluated."

    Design: Corner/state_machines/event_launch_from_draft_returns_invalid_state
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = _draft_event_with_listing()

    response = api.launch_event(event["id"], merchandiser_headers)
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    event_after = validate_success(api.get_event(event["id"], ANY), 200)
    assert event_after["event_status"] == "DRAFT", (
        "the clock is past starts_at, yet there is no DRAFT-to-LIVE transition")
    assert event_after["open_event_for_shop"] is False

    shop_after = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_after["shop_status"] == "DRAFT"

    listing_after = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_after["listing_status"] == "DRAFT", (
        "the launch's listing-reveal side effect did not fire")


def test_a_cancelled_event_is_terminal_for_both_forward_paths(
        api, merchandiser_headers):
    """PRD §3.1: "From `DRAFT`, a merchandiser cancels freely and every listing of the
    event becomes `WITHDRAWN`."

    PRD §2.12: "a request that names a transition the state machine does not permit is
    refused with `ERR_INVALID_STATE`, and nothing else in the request is evaluated."

    Design: Corner/state_machines/event_cancel_from_draft_is_terminal_and_blocks_scheduling
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = _draft_event_with_listing(sku="NW-TM-1")

    cancelled = validate_success(api.cancel_event(
        event["id"], merchandiser_headers, {"reason_code": "MERCHANDISING_PULLED"}),
        200)
    assert cancelled["event_status"] == "CANCELLED"
    assert cancelled["checkpoint_index"] == 0

    listing_after = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_after["listing_status"] == "WITHDRAWN", (
        "the cancel withdraws every listing of the event")

    validate_error(api.schedule_event(event["id"], merchandiser_headers),
                   "ERR_INVALID_STATE", expected_status=409)
    validate_error(api.close_event(event["id"], merchandiser_headers),
                   "ERR_INVALID_STATE", expected_status=409)

    event_after = validate_success(api.get_event(event["id"], ANY), 200)
    assert event_after["event_status"] == "CANCELLED", (
        "both forward paths out of CANCELLED are sealed")
    assert event_after["units_ordered_total"] == 0
    assert event_after["oversell_units_total"] == 0


def test_scheduling_an_already_scheduled_event_is_refused(api, merchandiser_headers):
    """PRD §3.1: "Scheduling is a merchandiser action that moves `DRAFT → SCHEDULED`
    and it is where the brand-window buffer bites."

    PRD §2.12: "a request that names a transition the state machine does not permit is
    refused with `ERR_INVALID_STATE`, and nothing else in the request is evaluated."

    Design: Corner/state_machines/event_event_schedule_twice_returns_invalid_state
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = _draft_event_with_listing(sku="NW-ID-1")

    first = validate_success(api.schedule_event(event["id"], merchandiser_headers), 200)
    assert first["event_status"] == "SCHEDULED"

    validate_error(api.schedule_event(event["id"], merchandiser_headers),
                   "ERR_INVALID_STATE", expected_status=409)

    event_after = validate_success(api.get_event(event["id"], ANY), 200)
    assert event_after["event_status"] == "SCHEDULED", (
        "the refused call changed nothing")
    assert event_after["version"] == first["version"], (
        "the refused call bumped no version")
    assert event_after["version"] > 1, "the first schedule did apply"

    shop_after = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_after["shop_status"] == "SCHEDULED"

    rows = validate_success(api.list_event_listings(event["id"], ANY), 200)
    assert len(rows) == 1


def test_a_shop_closes_on_its_last_event_and_stays_closed(api, merchandiser_headers):
    """PRD §3.1: "a shop moves from `OPEN` to `CLOSED` — its terminal state — when it
    holds no event whose `event_status` is `SCHEDULED` or `LIVE`, at which point its
    `curated_sku_count` is set to 0."

    PRD §2.6: "a new line against a listing whose shop is `SUSPENDED` or `CLOSED`, and
    any attempt to launch an event under such a shop, is refused with
    `ERR_SHOP_SUSPENDED`."

    Design: Corner/state_machines/shop_closes_with_its_last_event_and_stays_closed
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = _draft_event_with_listing(sku="NW-SH-1")
    validate_success(api.schedule_event(event["id"], merchandiser_headers), 200)
    validate_success(api.launch_event(event["id"], merchandiser_headers), 200)

    before_shop = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert before_shop["shop_status"] == "OPEN"
    before_event = validate_success(api.get_event(event["id"], ANY), 200)
    assert before_event["event_status"] == "LIVE"

    validate_success(api.close_event(
        event["id"], merchandiser_headers, {"cancel_pending_aggregations": True}), 200)

    shop_after = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_after["shop_status"] == "CLOSED", (
        "the last event closed, so the shop bubbles to its terminal state")
    assert shop_after["curated_sku_count"] == 0

    event_after = validate_success(api.get_event(event["id"], ANY), 200)
    assert event_after["event_status"] == "CLOSED"
    assert event_after["open_event_for_shop"] is False

    # The closed shop gates any further line against a listing under it.
    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    response = api.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 1}, cust_h)
    validate_error(response, "ERR_SHOP_SUSPENDED", expected_status=409)