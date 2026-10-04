"""Breadth coverage for role-based access control."""
from test_helpers import (
    api_client,
    buy_title,
    create_active_developer,
    create_buyer,
    create_released_title,
    create_title,
    make_developer_headers,
    make_user_headers,
    read_title,
    record_playtime,
    request_refund,
    submit_and_get_review,
    validate_error,
    ApiErrorId,
)


def test_developer_cannot_approve_own_store_page():
    """PRD §2.1: "A request whose role is not permitted on the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/developer_cannot_approve_own_store_page
    """
    developer = create_active_developer()
    title = create_title(developer)
    review = submit_and_get_review(title, developer)
    assert review["status"] == "SUBMITTED"

    res = api_client.approve_store_page_review(
        review["id"], make_developer_headers(developer["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    unchanged = api_client.get_store_page_review(
        review["id"], make_developer_headers(developer["id"])
    ).json()["data"]
    assert unchanged["status"] == "SUBMITTED"


def test_developer_cannot_touch_other_developers_title():
    """PRD §2.1: "When `X-User-Role` is `Developer`, `X-User-ID` is the `id` of
    the acting `DeveloperAccount`; ownership checks on any resource that chains
    back to a developer (titles, regional price overrides, key batches) compare
    the resource's `developer_account_id` lineage to `X-User-ID`, and a mismatch
    is rejected with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/developer_cannot_touch_other_developers_title
    """
    developer_a = create_active_developer()
    developer_b = create_active_developer()
    title = create_title(developer_a, title_name="A Game")

    res = api_client.submit_title_review(
        title["id"], make_developer_headers(developer_b["id"])
    )
    validate_error(res, ApiErrorId.ERR_NOT_OWNER)

    unchanged = read_title(title["id"], developer_a)
    assert unchanged["status"] == "DRAFT"


def test_user_cannot_use_trustsafety_endpoints():
    """PRD §2.1: "`TrustSafety` handles refunds, moderation, and abuse control."

    Design: Corner/rbac/user_cannot_use_trustsafety_endpoints
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    buyer = create_buyer()
    purchase = buy_title(buyer, title)
    record_playtime(purchase, buyer, 200)

    rr = request_refund(purchase, buyer, reason="manual needed")
    assert rr["status"] == "REQUESTED"

    # The manual approve endpoint is TrustSafety-only.
    res = api_client.approve_refund_request(rr["id"], make_user_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    unchanged = api_client.get_refund_request(
        rr["id"], make_user_headers(buyer["id"])
    ).json()["data"]
    assert unchanged["status"] == "REQUESTED"
