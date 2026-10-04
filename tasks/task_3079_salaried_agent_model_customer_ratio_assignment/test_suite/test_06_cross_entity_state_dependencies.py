"""Difficulty tests — cross-entity state dependencies (queue A, rule `cross_entity_state_dependency`).

Both instances turn on a *different* resource's state: the tour request is well
formed but the client is not placed, and the offer acceptance is well formed but
the listing has already followed its client to CLOSED.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    OPERATIONS_COORDINATOR,
    PLATFORM_ADMIN,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    open_transaction,
    advance_to_review,
    close_transaction,
    create_listing,
    publish_listing,
    schedule_tour,
    make_listing_agent_headers,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_tour_for_an_unplaced_client_is_refused_on_the_clients_state():
    """PRD §3.7: "a tour may only be scheduled for a client that is `ASSIGNED` or `IN_TRANSACTION`; a client in any other state is refused with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/tour_requires_client_in_assigned_state
    """
    region = create_region(target_client_ratio=2.0)
    create_lead_agent(region["id"])
    unplaced = create_client(full_name="Unassigned Buyer", service_area_code="98101")

    resp = api_client.create_tour(
        {"client_id": unplaced["id"], "scheduled_at": "2026-09-02T10:00:00Z",
         "access_instructions": "Lockbox 4821"},
        OPERATIONS_COORDINATOR,
    )
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"client_id": unplaced["id"]},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert rows == [], rows


def test_tour_lead_agent_is_copied_from_the_placed_clients_assignment():
    """PRD §3.7: "The tour's lead agent is not supplied — it is copied from the client's `assigned_agent_id`".

    Design: Difficulty/cross_entity_state_dependency/tour_requires_client_in_assigned_state
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    placed = create_client(full_name="Assigned Buyer", service_area_code="98102")
    assign_client(placed["id"])

    tour = schedule_tour(placed["id"], "2026-09-02T10:00:00Z")
    assert tour["lead_agent_id"] == lead["id"], tour


def test_offer_acceptance_is_refused_once_the_listings_client_has_closed():
    """PRD §3.6: "when the listing's client has a transaction entering `CLOSED`, the listing follows it to `CLOSED` and its `final_listing_fee_cents` is frozen at whatever value it then held".
    PRD §3.5: "the work of buying or selling begins as a `Transaction`".

    Design: Difficulty/cross_entity_state_dependency/listing_agreement_requires_sell_client_and_live_listing_pair
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"])
    publish_listing(listing["id"], lead["id"])

    tx = open_transaction(seller["id"])
    advance_to_review(tx["id"], 60_000_000)
    close_transaction(tx["id"])

    resp = api_client.accept_offer(
        listing["id"], {"contract_price_cents": 61_000_000},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert data["error_id"] == "ERR_INVALID_STATE", data

    after = get_success_data(api_client.get_listing_agreement(listing["id"], PLATFORM_ADMIN))
    assert after["status"] == "CLOSED", after
    assert after["status"] != "UNDER_CONTRACT", after


def test_listing_follows_its_client_to_closed_when_the_transaction_closes():
    """PRD §3.6: "when the listing's client has a transaction entering `CLOSED`, the listing follows it to `CLOSED` and its `final_listing_fee_cents` is frozen at whatever value it then held".
    PRD §3.6: "Accepting an offer records a `contract_price_cents` of at least 1 and moves the listing to `UNDER_CONTRACT`".

    Design: Difficulty/cross_entity_state_dependency/listing_agreement_requires_sell_client_and_live_listing_pair
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"])
    publish_listing(listing["id"], lead["id"])
    live = get_success_data(api_client.get_listing_agreement(listing["id"], PLATFORM_ADMIN))
    assert live["status"] == "ACTIVE", live

    tx = open_transaction(seller["id"])
    advance_to_review(tx["id"], 60_000_000)
    close_transaction(tx["id"])

    after = get_success_data(api_client.get_listing_agreement(listing["id"], PLATFORM_ADMIN))
    assert after["status"] == "CLOSED", after
    assert after["final_listing_fee_cents"] >= 0, after