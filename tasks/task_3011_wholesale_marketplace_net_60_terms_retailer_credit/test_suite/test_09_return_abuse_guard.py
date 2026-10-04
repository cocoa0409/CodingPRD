"""Return-abuse guard on review-approve (queue A,
priority_pair_validation_conflict): provisional return rate at or above 0.20
blocks approval."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    approve_return,
    delivered_order,
    first_line_id,
    get_success_data,
    make_brand_headers,
    order_line,
    receive_return,
    request_return,
    returned_all,
    validate_error,
    validate_success,
    verified_retailer_with_account,
)


def _rate_one_retailer_with_second_order(api):
    """Return a retailer whose received full return of the opening order
    leaves return_rate at 1.0, plus a second delivered order awaiting review."""
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    order1 = delivered_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 4)])
    returned_all(api, retailer["id"], brand["id"], order1["id"])
    order2 = delivered_order(api, retailer["id"], brand["id"], [order_line("S2", 5000, 4)])
    return retailer, brand, order2


def test_approval_blocked_when_provisional_rate_at_or_above_threshold(api):
    """PRD §3.6: "Approval moves it `REQUESTED → APPROVED` but is gated twice:
    the referenced order must be in `DELIVERED` or `PARTIALLY_RETURNED`, and
    the retailer's return rate, evaluated in its provisional form — that is,
    computed from returns already received before this authorization is
    processed — must be strictly below 0.20. A retailer at or above that
    boundary is rejected with `ERR_RETURN_ABUSE_GUARD` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_return_receive
    """
    retailer, brand, order2 = _rate_one_retailer_with_second_order(api)

    ra = request_return(api, retailer["id"], order2["id"],
                        first_line_id(api, order2["id"]), 4)
    response = api.review_return_authorization(
        ra["id"], {"decision": "APPROVE"}, make_brand_headers(brand["id"])
    )
    validate_error(response, ApiErrorId.ERR_RETURN_ABUSE_GUARD, 422)

    assert get_success_data(api.get_return_authorization(ra["id"], ADMIN))["status"] == (
        "REQUESTED"
    )


def test_approval_succeeds_below_threshold(api):
    """PRD §3.6: "the retailer's return rate, evaluated in its provisional form
    — that is, computed from returns already received before this authorization
    is processed — must be strictly below 0.20."
    PRD §3.6: "Review belongs to the selling brand, acting as itself. Rejection
    is always available and moves the authorization `REQUESTED → REJECTED`.
    Approval moves it `REQUESTED → APPROVED` but is gated twice: the referenced
    order must be in `DELIVERED` or `PARTIALLY_RETURNED`"

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_return_receive
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)

    # Partial return of 1 unit in 5 -> rate 0.2 exactly is NOT below; use 1 in 6.
    order1 = delivered_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 6)])
    ra1 = request_return(api, retailer["id"], order1["id"],
                         first_line_id(api, order1["id"]), 1)
    approve_return(api, ra1["id"], brand["id"])
    receive_return(api, ra1["id"])  # rate 1/6 ≈ 0.1667 < 0.20

    order2 = delivered_order(api, retailer["id"], brand["id"], [order_line("S2", 5000, 4)])
    ra2 = request_return(api, retailer["id"], order2["id"],
                         first_line_id(api, order2["id"]), 1)
    approved = validate_success(
        api.review_return_authorization(
            ra2["id"], {"decision": "APPROVE"}, make_brand_headers(brand["id"])
        )
    )
    assert approved["status"] == "APPROVED"
