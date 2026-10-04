"""Breadth coverage for validation gates (refund windows, ownership, abuse)."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_refund_request_payload,
    create_released_title,
    get_success_data,
    make_user_headers,
    read_title,
    record_playtime,
    request_refund,
    set_clock,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

TRUST = TEST_USERS["trust_safety_headers"]


def test_refund_age_boundary_14_days_inclusive():
    """PRD §3.5: "the purchase is no older than fourteen days, with exactly
    fourteen days still qualifying"

    Design: Corner/validations/refund_age_boundary_14_days_inclusive
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    buyer1 = create_buyer()
    buyer2 = create_buyer()
    purchase1 = buy_title(buyer1, title)  # purchased at 2026-09-01T00:00:00Z
    purchase2 = buy_title(buyer2, title)

    # Exactly 14 days later: the age clause still passes -> auto-approve.
    set_clock("2026-09-15T00:00:00Z")
    rr1 = request_refund(purchase1, buyer1, reason="edge14")
    assert rr1["status"] == "APPROVED"

    # 14 days + 1 second: the age clause fails -> stays REQUESTED for review.
    set_clock("2026-09-15T00:00:01Z")
    rr2 = request_refund(purchase2, buyer2, reason="past14")
    assert rr2["status"] == "REQUESTED"


def test_restricted_user_cannot_request_refund():
    """PRD §3.5: "An account whose `refund_restricted` flag is set is rejected
    with `ERR_REFUND_ABUSE` (HTTP 422)."

    Design: Corner/validations/restricted_user_cannot_request_refund
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    buyer = create_buyer()
    purchase = buy_title(buyer, title)

    get_success_data(api_client.restrict_user(buyer["id"], TRUST))

    res = api_client.create_refund_request(
        create_refund_request_payload(purchase["id"], reason="while restricted"),
        make_user_headers(buyer["id"]),
    )
    # PRD §2.7: account-activity (ERR_ACCOUNT_RESTRICTED) outranks the
    # refund-abuse restriction gate, and TrustSafety restriction flips the
    # account out of ACTIVE.
    validate_error(res, ApiErrorId.ERR_ACCOUNT_RESTRICTED)


def test_pending_refund_blocks_second_request():
    """PRD §3.5: "At most one refund request per purchase may be open: if
    another request for the same purchase is still `REQUESTED`, the new one is
    rejected with `ERR_REFUND_ALREADY_PENDING` (HTTP 409)."

    Design: Corner/validations/pending_refund_blocks_second_request
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    buyer = create_buyer()
    purchase = buy_title(buyer, title)
    record_playtime(purchase, buyer, 200)

    first = request_refund(purchase, buyer, reason="first")
    assert first["status"] == "REQUESTED"  # over playtime -> manual queue

    res = api_client.create_refund_request(
        create_refund_request_payload(purchase["id"], reason="second"),
        make_user_headers(buyer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REFUND_ALREADY_PENDING)


def test_review_requires_ownership():
    """PRD §3.7: "must hold a stake in the title — either a purchase in
    `COMPLETED` or `PARTIALLY_REFUNDED`, or a `REDEEMED` activation key; a
    review from an account with neither is rejected with `ERR_REVIEW_NOT_OWNED`
    (HTTP 422)."

    Design: Corner/validations/review_requires_ownership
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    stranger = create_buyer()
    version = read_title(title["id"], developer)["version"]

    res = api_client.create_review(
        {
            "title_id": title["id"],
            "user_account_id": stranger["id"],
            "is_positive": True,
            "body": "never played",
            "expected_title_version": version,
        },
        make_user_headers(stranger["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_NOT_OWNED)
