"""Ticketing: the sellout boundary and the ticket-sale structural guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_agreement_with_record,
    create_complex,
    get_host_community_record,
    set_test_clock,
    validate_error,
    validate_success,
)


def _two_records_on_sale(ticket_price_cents=100, ticket_sellout_capacity=100):
    complex_ = create_complex()
    agreement, _record = create_active_agreement_with_record(
        complex_["id"], tickets=None,
        ticket_price_cents=ticket_price_cents,
        ticket_sellout_capacity=ticket_sellout_capacity)
    first = validate_success(api_client.open_host_community_record(
        agreement["id"], TEST_USERS["community_liaison_headers"]), 201)
    second = validate_success(api_client.open_host_community_record(
        agreement["id"], TEST_USERS["community_liaison_headers"]), 201)
    validate_success(api_client.open_ticketing(first["id"], TEST_USERS["community_liaison_headers"]))
    validate_success(api_client.open_ticketing(second["id"], TEST_USERS["community_liaison_headers"]))
    return first, second


def test_sellout_flips_at_exactly_the_declared_capacity_not_above_it():
    """PRD 3.7: "if the resulting `tickets_sold` has reached the agreement's
    `ticket_sellout_capacity`, `ticketing_status` moves to `SOLD_OUT`."
    PRD 3.7: "Selling a ticket block supplies a `quantity` and increments
    `tickets_sold` by it and `ticketing_revenue_cents` by the quantity multiplied
    by the agreement's `ticket_price_cents`"

    Design: Difficulty/boundary_precision_check/ticket_sellout_flips_at_exactly_the_capacity_not_above_it
    """
    set_test_clock()
    first, second = _two_records_on_sale()

    validate_success(api_client.sell_tickets(first["id"], 99, TEST_USERS["community_liaison_headers"]))
    validate_success(api_client.sell_tickets(second["id"], 100, TEST_USERS["community_liaison_headers"]))

    below = get_host_community_record(first["id"])
    assert below["ticketing_status"] == "ON_SALE"
    assert below["tickets_sold"] == 99
    assert below["ticketing_revenue_cents"] == 9900

    at = get_host_community_record(second["id"])
    assert at["ticketing_status"] == "SOLD_OUT"
    assert at["tickets_sold"] == 100
    assert at["ticketing_revenue_cents"] == 10000


def test_a_zero_quantity_sale_is_structurally_invalid_and_leaves_the_ledger():
    """PRD 2.9: "a zero or negative ticket `quantity`" is rejected as a structurally
    invalid value with `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Difficulty/boundary_precision_check/ticket_sellout_flips_at_exactly_the_capacity_not_above_it
    """
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=None,
        ticket_price_cents=100, ticket_sellout_capacity=100)
    first = record["id"]
    validate_success(api_client.open_ticketing(first, TEST_USERS["community_liaison_headers"]))
    validate_success(api_client.sell_tickets(first, 99, TEST_USERS["community_liaison_headers"]))

    validate_error(
        api_client.sell_tickets(first, 0, TEST_USERS["community_liaison_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    after = get_host_community_record(first)
    assert after["tickets_sold"] == 99
    assert after["ticketing_revenue_cents"] == 9900
    assert after["ticketing_status"] == "ON_SALE"