"""Difficulty tests — resource temporal overlap (queue A, rule `resource_temporal_overlap`).

One instance is the lead agent's half-open tour block window; the other is the
gap rule on a listing's registration windows.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    ApiErrorId,
    OPERATIONS_COORDINATOR,
    PLATFORM_ADMIN,
    create_region,
    create_lead_agent,
    create_client,
    assign_client,
    schedule_tour,
    create_listing,
    publish_listing,
    make_listing_agent_headers,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_tour_inside_the_block_window_is_refused_and_exact_adjacency_is_admitted():
    """PRD §3.7: "if the agent already has a tour in `ACCESS_PENDING`, `CONFIRMED` or `COMPLETED` whose block window — the half-hour starting at that tour's `scheduled_at` — overlaps the requested window, the schedule is refused with `ERR_TOUR_SCHEDULE_CONFLICT` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/lead_agent_block_window_adjacency_rule_with_buffer_on_tours
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    client_a = create_client(full_name="A Client", service_area_code="98101")
    client_b = create_client(full_name="B Client", service_area_code="98102")
    client_c = create_client(full_name="C Client", service_area_code="98103")
    for client in (client_a, client_b, client_c):
        assign_client(client["id"])

    schedule_tour(client_a["id"], "2026-09-02T10:00:00Z")

    inside = api_client.create_tour(
        {"client_id": client_b["id"], "scheduled_at": "2026-09-02T10:59:00Z",
         "access_instructions": "Lockbox 1001"},
        OPERATIONS_COORDINATOR,
    )
    inside_data = validate_error(inside, ApiErrorId.ERR_TOUR_SCHEDULE_CONFLICT)
    assert inside_data["error_id"] == "ERR_TOUR_SCHEDULE_CONFLICT", inside_data

    adjacent = schedule_tour(client_c["id"], "2026-09-02T11:00:00Z")
    assert adjacent["status"] == "ACCESS_PENDING", adjacent


def test_exact_adjacency_leaves_exactly_two_tours_on_the_lead_agent():
    """PRD §3.7: "And the same client may not have a duplicate tour."

    Design: Difficulty/resource_temporal_overlap/lead_agent_block_window_adjacency_rule_with_buffer_on_tours
    """
    region = create_region(target_client_ratio=4.0)
    lead = create_lead_agent(region["id"])
    clients = []
    for i, code in enumerate(["98101", "98102", "98103"]):
        client = create_client(full_name=f"Client {i}", service_area_code=code)
        assign_client(client["id"])
        clients.append(client)

    schedule_tour(clients[0]["id"], "2026-09-02T10:00:00Z")
    schedule_tour(clients[2]["id"], "2026-09-02T11:00:00Z")

    tours = get_success_data(api_client.list_tours(
        PLATFORM_ADMIN, params={"lead_agent_id": lead["id"]},
    ))
    rows = tours if isinstance(tours, list) else tours.get("data", [])
    assert len(rows) == 2, rows


def test_listing_registration_refuses_a_window_that_does_not_acknowledge_enrolment():
    """PRD §3.6: "on a region that requires enrolment the same acknowledgement rule applies, and the window is only written when each adjacent window leaves no unregistered gap".
    PRD §3.8: "when a region requires enrolment and a partner acceptance arrives without the enrolment acknowledgement, it is refused with `ERR_ENROLMENT_NOT_CONFIRMED` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/listing_registration_window_contiguous_no_gap_and_refuses_back_to_back
    """
    region = create_region(target_client_ratio=2.0, enrolment_is_required=True)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(seller["id"], lead["id"], region["id"])
    publish_listing(listing["id"], lead["id"])

    resp = api_client.register_listing_window(
        listing["id"], {"enrolment_acknowledged": False, "window_days": 14},
        make_listing_agent_headers(lead["id"]),
    )
    data = validate_error(resp, ApiErrorId.ERR_ENROLMENT_NOT_CONFIRMED)
    assert data["error_id"] == "ERR_ENROLMENT_NOT_CONFIRMED", data


def test_listing_registration_accepted_when_enrolment_is_acknowledged_or_not_required():
    """PRD §3.6: "on a region that requires enrolment the same acknowledgement rule applies, and the window is only written when each adjacent window leaves no unregistered gap".

    Design: Difficulty/resource_temporal_overlap/listing_registration_window_contiguous_no_gap_and_refuses_back_to_back
    """
    strict = create_region(target_client_ratio=2.0, enrolment_is_required=True)
    lead_strict = create_lead_agent(strict["id"])
    seller_strict = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller_strict["id"])
    listing_strict = create_listing(seller_strict["id"], lead_strict["id"], strict["id"])
    publish_listing(listing_strict["id"], lead_strict["id"])

    ok = api_client.register_listing_window(
        listing_strict["id"], {"enrolment_acknowledged": True, "window_days": 14},
        make_listing_agent_headers(lead_strict["id"]),
    )
    assert ok.status_code == 200, ok.text

    # The tier's commitment value is unaffected by a window registration.
    after = get_success_data(api_client.get_listing_agreement(listing_strict["id"], PLATFORM_ADMIN))
    assert after["service_commitment_hours"] == 24, after